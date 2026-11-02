"""Download and publish validated datasets shared by the Gunicorn workers.

File locks coordinate processes on one host. A small, atomically replaced state
file points at an immutable snapshot, so a failed refresh leaves readers on the
last successful dataset.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import logging
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile

from schema_validator import discover_run_dirs_recursive, load_and_validate_run

logger = logging.getLogger(__name__)


def extract_results_zip(zip_path, target_dir):
    """Stage valid runs, rejecting unusable archives and conflicting copies."""
    target_dir = Path(target_dir)
    with tempfile.TemporaryDirectory() as temporary:
        extracted = Path(temporary)
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Archive contains an unsafe path")
            archive.extractall(extracted)

        run_dirs = discover_run_dirs_recursive(extracted)
        if not run_dirs:
            raise ValueError("Archive contains no benchmark runs")

        seen = {}
        skipped = []
        for run_dir in run_dirs:
            config, _, validation = load_and_validate_run(run_dir)
            if not validation.ok:
                message = f"Invalid run {run_dir.name}: {'; '.join(validation.errors)}"
                skipped.append(message)
                logger.warning("%s", message)
                continue
            run_id = config["run_id"]
            if run_id in (".", "..") or Path(run_id).name != run_id:
                raise ValueError(f"Invalid run ID: {run_id}")
            contents = tuple((run_dir / name).read_bytes() for name in ("config.json", "results.json"))
            if run_id in seen:
                if seen[run_id] != contents:
                    raise ValueError(f"Conflicting copies of run {run_id}")
                continue
            seen[run_id] = contents
            destination = target_dir / "runs" / run_id
            destination.mkdir(parents=True)
            # Only these files feed the dashboard; generated HTML and simulation
            # artifacts in the ZIP do not need to be duplicated in the cache.
            for name in ("config.json", "results.json"):
                shutil.copy2(run_dir / name, destination / name)
        if not seen:
            raise ValueError(f"Archive contains no valid benchmark runs. {skipped[0]}")
        return len(seen), len(skipped)


def download_and_extract_results(url, target_dir):
    with tempfile.TemporaryDirectory() as temporary:
        zip_path = Path(temporary) / "results.zip"
        deadline = time.monotonic() + 120
        with urllib.request.urlopen(url, timeout=30) as response, zip_path.open("wb") as output:
            # HTTPResponse.read(size) can wait for the whole buffer while a
            # server trickles bytes. read1 lets us check the budget each receive.
            read_chunk = getattr(response, "read1", response.read)
            while True:
                chunk = read_chunk(1024 * 1024)
                if time.monotonic() > deadline:
                    raise TimeoutError("Results download exceeded 120 seconds")
                if not chunk:
                    break
                output.write(chunk)
        return extract_results_zip(zip_path, target_dir)


class ResultsStore:
    def __init__(self, root):
        self.root = Path(root)
        self.cache = self.root / ".remote"
        self.thread = None

    def _lock(self, name, *, shared=False, blocking=True):
        self.cache.mkdir(parents=True, exist_ok=True)
        handle = (self.cache / name).open("a+")
        flags = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(handle, flags | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            handle.close()
            return None
        return handle

    def _read_state(self):
        try:
            return json.loads((self.cache / "state.json").read_text())
        except FileNotFoundError:
            return {"status": "idle", "message": "", "version": 0}

    def _write_state(self, state):
        with tempfile.NamedTemporaryFile(mode="w", dir=self.cache, delete=False) as output:
            temporary = Path(output.name)
            try:
                json.dump(state, output)
                output.flush()
                temporary.replace(self.cache / "state.json")
            finally:
                temporary.unlink(missing_ok=True)

    def state(self):
        state = self._read_state()
        if state["status"] == "downloading":
            # A worker may have restarted during a refresh. The OS releases its
            # lock, allowing another worker to report the interruption and retry.
            lock = self._lock("refresh.lock", blocking=False)
            if lock is not None:
                with lock:
                    state = self._read_state()
                    if state["status"] == "downloading":
                        state.update(status="idle", message="Refresh interrupted. Click Refresh Data to retry.")
                        self._write_state(state)
        return state

    @contextmanager
    def dataset(self):
        with self._lock("data.lock", shared=True):
            state = self._read_state()
            if state.get("snapshot"):
                path = self.cache / state["snapshot"] / "runs"
            else:
                path = self.root / "runs" if (self.root / "runs").is_dir() else self.root
            yield path, state["version"]

    def start(self, get_url, validate):
        """Start one refresh across all workers; validate before publication."""
        lock = self._lock("refresh.lock", blocking=False)
        if lock is None:
            return False
        try:
            state = self._read_state()
            state.update(status="downloading", message="Downloading results ZIP...")
            self._write_state(state)
            self.thread = threading.Thread(target=self._refresh, args=(lock, state, get_url, validate), daemon=True)
            self.thread.start()
        except Exception:
            lock.close()
            raise
        return True

    def _refresh(self, lock, state, get_url, validate):
        snapshot = None
        with lock:
            try:
                snapshot = self.cache / f"snapshot-{uuid.uuid4().hex}"
                snapshot.mkdir()
                count, skipped = download_and_extract_results(get_url(), snapshot)
                state.update(message="Validating downloaded data...")
                self._write_state(state)
                validate(snapshot / "runs")
                updated = datetime.now(timezone.utc).strftime("%b %d, %Y %I:%M %p UTC")
                warning = f"; skipped {skipped} invalid run(s)" if skipped else ""
                new_state = dict(state, status="idle", message=f"Loaded {count} dataset(s) at {updated}{warning}",
                                 version=state["version"] + 1, snapshot=snapshot.name)
                with self._lock("data.lock"):
                    self._write_state(new_state)
                    state = new_state
                    snapshot = None  # The state now owns this validated snapshot.
                    # Readers hold data.lock until they finish loading; old
                    # snapshots can be removed without racing those readers.
                    for old in self.cache.glob("snapshot-*"):
                        if old.name != new_state["snapshot"]:
                            shutil.rmtree(old, ignore_errors=True)
            except Exception as exc:
                logger.exception("Results refresh failed")
                state.update(status="idle", message=f"Refresh failed: {exc}")
                self._write_state(state)
            finally:
                if snapshot is not None:
                    shutil.rmtree(snapshot, ignore_errors=True)
