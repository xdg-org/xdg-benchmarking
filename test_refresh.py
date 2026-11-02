"""Regression tests for remote refresh and dashboard updates (no external URL)."""

import contextlib
import importlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from results_store import ResultsStore


def run_files(run_id="new", date="2026-11-02T12:00:00Z"):
    config = {
        "run_id": run_id, "date": date, "config_file": "benchmark.json",
        "models": ["tokamak"], "executables": ["xdg"],
        "particles_per_thread": 100, "max_threads": 1, "n_repeats": 1,
        "architecture": {"machine": "test", "processor": "cpu", "cpu_count": 1,
                         "os": "Linux", "python_version": "3.9"},
    }
    point = {"threads": 1, "active_rate": 10, "inactive_rate": None}
    results = {"run_id": run_id, "date": date, "results": {
        "tokamak": {"xdg": {"scaling": [point], "max_performance": point}}
    }}
    return {"config.json": json.dumps(config), "results.json": json.dumps(results)}


def make_zip(path, runs=None):
    with zipfile.ZipFile(path, "w") as archive:
        for prefix, files in (runs or {"bundle/new": run_files()}).items():
            for name, content in files.items():
                archive.writestr(f"{prefix}/{name}", content)
    return path.as_uri()


def probe_worker(root, url, queue):
    store = ResultsStore(root)
    state = store.state()
    with store.dataset() as (path, version):
        runs = sorted(p.name for p in path.iterdir() if p.is_dir()) if path.exists() else []
    started = store.start(lambda: url, lambda path: None)
    if started:
        store.thread.join(10)
    queue.put((state, version, runs, started))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ResultsStore(self.root / "results")
        self.url = make_zip(self.root / "results.zip")

    def refresh(self, url=None, validator=None):
        self.assertTrue(self.store.start(lambda: url or self.url, validator or (lambda path: None)))
        self.store.thread.join(10)
        self.assertFalse(self.store.thread.is_alive())
        return self.store.state()

    def test_workers_share_progress_and_allow_one_download(self):
        entered, release = threading.Event(), threading.Event()

        def get_url():
            entered.set()
            if not release.wait(10):
                raise TimeoutError("test did not release download")
            return self.url

        self.assertTrue(self.store.start(get_url, lambda path: None))
        self.assertTrue(entered.wait(5))
        try:
            context = multiprocessing.get_context("spawn")
            queue = context.Queue()
            process = context.Process(target=probe_worker, args=(self.store.root, self.url, queue))
            process.start()
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            state, version, _, started = queue.get(timeout=2)
            self.assertEqual(state["status"], "downloading")
            self.assertEqual(version, 0)
            self.assertFalse(started)
        finally:
            release.set()
            self.store.thread.join(10)
        other_worker = ResultsStore(self.store.root)
        self.assertEqual(other_worker.state()["version"], 1)
        with other_worker.dataset() as (path, version):
            self.assertEqual(version, 1)
            self.assertEqual([p.name for p in path.iterdir()], ["new"])

    def test_failed_archives_preserve_published_data(self):
        original = self.refresh()
        invalid = run_files()
        invalid["results.json"] = "{}"
        conflict = run_files()
        conflict["results.json"] = conflict["results.json"].replace('"active_rate": 10', '"active_rate": 20')
        cases = {
            "empty": {"empty": {"README": "no data"}},
            "invalid": {"new": invalid},
            "conflicting": {"a/new": run_files(), "b/new": conflict},
            "unsafe": {"../escape": run_files()},
        }
        for name, runs in cases.items():
            with self.subTest(name=name), self.assertLogs("results_store", level="ERROR"):
                state = self.refresh(make_zip(self.root / f"{name}.zip", runs))
                self.assertEqual(state["version"], original["version"])
                self.assertEqual(state["snapshot"], original["snapshot"])
                self.assertIn("Refresh failed", state["message"])
                with self.store.dataset() as (path, _):
                    self.assertTrue((path / "new" / "results.json").exists())

    def test_timeout_and_invalid_zip_preserve_data(self):
        original = self.refresh()
        for failure in (TimeoutError("timed out"), zipfile.BadZipFile("not a zip")):
            with self.subTest(failure=failure), patch("results_store.urllib.request.urlopen", side_effect=failure):
                with self.assertLogs("results_store", level="ERROR"):
                    state = self.refresh()
                self.assertEqual(state["snapshot"], original["snapshot"])
                self.assertEqual(state["version"], 1)
                self.assertIn(str(failure), state["message"])

    def test_dataframe_failure_does_not_publish(self):
        original = self.refresh()

        def fail(path):
            raise ValueError("No usable scaling data")

        with self.assertLogs("results_store", level="ERROR"):
            state = self.refresh(validator=fail)
        self.assertEqual(state["snapshot"], original["snapshot"])
        self.assertEqual(state["version"], 1)

    def test_publication_failure_preserves_previous_snapshot(self):
        original = self.refresh()
        write_state = self.store._write_state

        def fail_publication(state):
            if state["version"] == 2:
                raise OSError("Cannot publish state")
            write_state(state)

        with patch.object(self.store, "_write_state", side_effect=fail_publication):
            with self.assertLogs("results_store", level="ERROR"):
                state = self.refresh()
        self.assertEqual(state["snapshot"], original["snapshot"])
        self.assertEqual(state["version"], 1)
        self.assertIn("Cannot publish state", state["message"])

    def test_identical_archive_copies_are_deduplicated(self):
        state = self.refresh(make_zip(self.root / "duplicate.zip", {
            "results/new": run_files(), "results/runs/new": run_files(),
        }))
        self.assertIn("Loaded 1 dataset(s)", state["message"])

    def test_mixed_archive_loads_valid_runs_and_reports_invalid_runs(self):
        with self.assertLogs("results_store", level="WARNING"):
            state = self.refresh(make_zip(self.root / "mixed.zip", {
                "new": run_files(), "legacy": {"config.json": "{}", "results.json": "{}"},
            }))
        self.assertEqual(state["version"], 1)
        self.assertIn("skipped 1 invalid run(s)", state["message"])
        with self.store.dataset() as (path, _):
            self.assertEqual([p.name for p in path.iterdir()], ["new"])

    def test_refresh_replaces_remote_snapshot_and_cleans_old_snapshots(self):
        self.refresh()
        state = self.refresh(make_zip(self.root / "next.zip", {"next": run_files("next")}))
        self.assertEqual(state["version"], 2)
        self.assertEqual(len(list(self.store.cache.glob("snapshot-*"))), 1)
        with self.store.dataset() as (path, _):
            self.assertEqual([p.name for p in path.iterdir()], ["next"])

    def test_interrupted_worker_can_be_retried(self):
        self.refresh()
        state = self.store.state()
        state.update(status="downloading", message="Downloading...")
        self.store._write_state(state)
        recovered = ResultsStore(self.store.root).state()
        self.assertIn("interrupted", recovered["message"])
        self.assertEqual(recovered["version"], 1)
        self.assertEqual(self.refresh()["version"], 2)


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {"RESULTS_DIR": cls.temporary.name})
        cls.environment.start()
        # Import with an empty cache: this used to fail unpacking one DataFrame.
        cls.module = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temporary.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ResultsStore(self.root / "cache")
        self.url = make_zip(self.root / "data.zip")
        self.patch = patch.multiple(self.module, RESULTS_STORE=self.store, RESULTS_DIR=self.store.root,
                                    LOCAL_DATA_VERSION=0)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.module.df, self.module.flux_df = self.module.load_benchmark_data(self.root / "missing")

    def refresh(self, url=None):
        with patch.object(self.module, "load_results_url", return_value=(url or self.url, None)):
            self.assertTrue(self.module.refresh_data_from_remote())
            self.store.thread.join(10)
        self.assertFalse(self.store.thread.is_alive())
        with contextlib.redirect_stdout(io.StringIO()):
            self.module.ensure_data_loaded(0)  # A stale browser still loads the published version.

    def test_empty_directory_returns_two_dataframes(self):
        for root in (self.root / "missing", self.root):
            scaling, flux = self.module.load_benchmark_data(root)
            self.assertTrue(scaling.empty)
            self.assertTrue(flux.empty)

    def test_remote_snapshot_excludes_bundled_and_duplicate_results(self):
        local = self.store.root / "runs" / "local"
        local.mkdir(parents=True)
        for name, content in run_files("local").items():
            (local / name).write_text(content)
        self.refresh()
        self.assertEqual(self.module.df["Run_ID"].tolist(), ["new"])
        self.assertEqual(self.module.LOCAL_DATA_VERSION, 1)
        self.assertTrue((local / "results.json").exists())

    def test_scaling_only_archive_renders_without_optional_flux(self):
        self.refresh()
        charts = self.module.update_charts(
            "tokamak", ["xdg"], ["new"], None, None, [], [], [], [], [], [], "Active rate", 1)
        self.assertEqual(len(charts[0].data), 1)
        self.assertEqual(len(charts[3].data), 0)
        self.assertEqual(charts[5].data[0]["Run_ID"], "new")

    def test_default_dates_include_new_results_and_narrowed_dates_are_preserved(self):
        self.refresh()
        self.refresh(make_zip(self.root / "next.zip", {
            "new": run_files(), "next": run_files("next", "2026-11-03T12:00:00Z"),
        }))
        minimum, maximum, start, end = self.module.update_date_bounds(
            2, "2026-11-02", "2026-11-02", "2026-11-02", "2026-11-02")
        self.assertEqual(str(end), "2026-11-03")
        _, _, _, end = self.module.update_date_bounds(
            2, "2026-11-02", "2026-11-02", "2026-11-02", "2026-11-03")
        self.assertEqual(str(end), "2026-11-02")

    def test_date_range_clamps_when_replacement_has_no_overlap(self):
        self.refresh()
        _, _, start, end = self.module.update_date_bounds(
            1, "2025-01-01", "2025-02-01", "2024-01-01", "2025-03-01")
        self.assertEqual(str(start), "2026-11-02")
        self.assertEqual(str(end), "2026-11-02")

    def test_unrestricted_properties_stay_unrestricted_and_explicit_values_are_preserved(self):
        self.refresh()
        previous = self.module.update_filter_options(1, None, [], [], [], [], [], [], [], *([[]] * 7))
        next_run = run_files("next", "2026-11-03T12:00:00Z")
        config = json.loads(next_run["config.json"])
        config["architecture"]["machine"] = "new-machine"
        next_run["config.json"] = json.dumps(config)
        self.refresh(make_zip(self.root / "next.zip", {"new": run_files(), "next": next_run}))
        current_values = [previous[index] for index in range(1, 16, 2)]
        previous_options = [previous[index] for index in range(2, 16, 2)]
        expanded = self.module.update_filter_options(2, *current_values, *previous_options)
        self.assertEqual(expanded[11], [])  # The All placeholder includes both machines.
        self.assertEqual([option['value'] for option in expanded[10]], ["new-machine", "test"])
        # Retain an explicit machine subset when both machines were available.
        current_values = [expanded[index] for index in range(1, 16, 2)]
        current_values[5] = ["test"]
        previous_options = [expanded[index] for index in range(2, 16, 2)]
        narrowed = self.module.update_filter_options(2, *current_values, *previous_options)
        self.assertEqual(narrowed[11], ["test"])

    def test_empty_run_selection_clears_comparison(self):
        self.refresh()
        charts = self.module.update_comparison("tokamak", ["xdg"], [], "Active rate", 1)
        self.assertEqual(len(charts[0].data), 0)
        self.assertIn("Select runs", charts[4])

    def test_missing_metric_has_an_explanatory_empty_state(self):
        self.refresh()
        charts = self.module.update_comparison("tokamak", ["xdg"], ["new"], "Inactive rate", 1)
        self.assertEqual(len(charts[0].data), 0)
        self.assertIn("no measurements", charts[4])

    def linked_browser(self, query, selected=None, state=None, trigger="comparison-url",
                       model="tokamak", executables=None):
        context = SimpleNamespace(triggered_id=trigger, triggered_prop_ids={f"{trigger}.search": trigger})
        with patch.object(self.module, "ctx", context):
            return self.module.update_run_browser(
                "", None, None, *([[]] * 6), self.module.LOCAL_DATA_VERSION,
                [], 0, 0, [], query, model, ["xdg"] if executables is None else executables,
                "Active rate", selected, [], state,
            )

    def test_shared_link_restores_settings_and_retains_missing_runs(self):
        self.refresh()
        result = self.linked_browser("?run=new&run=missing&model=tokamak&exe=xdg&metric=active")
        self.assertEqual(result[3], ["new", "missing"])
        self.assertEqual(result[1], ["new"])
        self.assertEqual(result[10:13], ("tokamak", ["xdg"], "Active rate"))
        self.assertIn("missing", result[13][0].children)
        self.assertIn("Available runs are shown", result[13][0].children)
        self.assertTrue(result[14]["initialized"])
        charts = self.module.update_comparison(result[10], result[11], result[3], result[12], 1)
        self.assertEqual(len(charts[0].data), 1)

    def test_link_with_only_missing_runs_never_selects_the_default(self):
        self.refresh()
        result = self.linked_browser("?run=missing&model=tokamak&exe=xdg&metric=active")
        self.assertEqual(result[3], ["missing"])
        self.assertEqual(result[1], [])
        self.assertIn("None of the selected runs", result[13][0].children)
        charts = self.module.update_comparison(result[10], result[11], result[3], result[12], 1)
        self.assertEqual(len(charts[0].data), 0)
        self.assertIn("unavailable", charts[4])

    def test_missing_linked_run_is_restored_when_refresh_finishes(self):
        query = "?run=new&model=tokamak&exe=xdg&metric=active"
        pending = self.linked_browser(query)
        self.assertEqual(pending[3], ["new"])
        self.assertIn("unavailable", pending[13][0].children.lower())
        self.refresh()
        restored = self.linked_browser(query, pending[3], pending[14], trigger="data-version")
        self.assertEqual(restored[3], ["new"])
        self.assertEqual(restored[1], ["new"])
        self.assertEqual(restored[13], [])

    def test_unknown_model_and_executable_are_visible_instead_of_silently_replaced(self):
        self.refresh()
        result = self.linked_browser("?run=new&model=unknown&exe=other&metric=active")
        self.assertEqual(result[10:12], ("unknown", ["other"]))
        self.assertIn({"label": "unknown (unavailable)", "value": "unknown"}, result[15])
        self.assertIn({"label": "other (unavailable)", "value": "other"}, result[16])
        charts = self.module.update_comparison(result[10], result[11], result[3], result[12], 1)
        self.assertEqual(len(charts[0].data), 0)

    def test_refresh_callback_starts_on_first_visit_and_polls_shared_version(self):
        client = self.module.server.test_client()
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/_dash-layout").status_code, 200)
        key = next(key for key in self.module.app.callback_map if 'refresh-status' in key)
        payload = {
            "output": key,
            "outputs": [{"id": "refresh-status", "property": "children"},
                        {"id": "data-version", "property": "data"}],
            "inputs": [{"id": "refresh-button", "property": "n_clicks", "value": 0},
                       {"id": "refresh-poll", "property": "n_intervals", "value": 0}],
            "state": [{"id": "data-version", "property": "data", "value": 0}],
            "changedPropIds": [],
        }
        with patch.object(self.module, "load_results_url", return_value=(self.url, None)):
            response = client.post("/_dash-update-component", json=payload)
            self.assertEqual(response.status_code, 200, response.data)
            self.store.thread.join(10)
        payload["changedPropIds"] = ["refresh-poll.n_intervals"]
        response = client.post("/_dash-update-component", json=payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json["response"]["data-version"]["data"], 1)
        self.assertIn("Loaded 1 dataset(s)", response.json["response"]["refresh-status"]["children"])
        payload["state"][0]["value"] = 1
        response = client.post("/_dash-update-component", json=payload)
        self.assertNotIn("data-version", response.json["response"])


if __name__ == "__main__":
    unittest.main()
