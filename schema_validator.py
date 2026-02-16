#!/usr/bin/env python3
"""
Validate XDG benchmarking data against docs/schema.md.

Usage:
  python schema_validator.py results/runs
  python schema_validator.py results/runs/20250715_171058
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def is_int_number(value: Any) -> bool:
    if not is_number(value):
        return False
    if isinstance(value, int):
        return True
    return float(value).is_integer()


def is_finite_number(value: Any) -> bool:
    return is_number(value) and math.isfinite(float(value))


def is_positive_number(value: Any) -> bool:
    return is_finite_number(value) and float(value) > 0


def is_iso8601(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_identifier(value: Any) -> bool:
    return isinstance(value, str) and IDENTIFIER_RE.match(value) is not None


@dataclass
class ValidationResult:
    run_path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def _require_keys(obj: dict[str, Any], required: Iterable[str], result: ValidationResult, scope: str) -> None:
    for key in required:
        if key not in obj:
            result.add_error(f"{scope}: missing required field '{key}'")


def _validate_string_field(obj: dict[str, Any], key: str, result: ValidationResult, scope: str) -> None:
    if key in obj and not is_non_empty_str(obj[key]):
        result.add_error(f"{scope}: '{key}' must be a non-empty string")


def _validate_number_field(
    obj: dict[str, Any],
    key: str,
    result: ValidationResult,
    scope: str,
    *,
    positive: bool = False,
    integer: bool = False,
) -> None:
    if key not in obj:
        return
    value = obj[key]
    if integer:
        valid = is_int_number(value)
    else:
        valid = is_number(value) and is_finite_number(value)
    if not valid:
        result.add_error(f"{scope}: '{key}' must be a finite number{' (integer)' if integer else ''}")
        return
    if positive and float(value) <= 0:
        result.add_error(f"{scope}: '{key}' must be positive")


def validate_config(config: dict[str, Any], result: ValidationResult) -> None:
    scope = "config.json"
    required = [
        "run_id",
        "date",
        "config_file",
        "models",
        "executables",
        "particles_per_thread",
        "max_threads",
        "n_repeats",
        "architecture",
    ]
    _require_keys(config, required, result, scope)

    _validate_string_field(config, "run_id", result, scope)

    if "date" in config and not is_iso8601(config["date"]):
        result.add_error(f"{scope}: 'date' must be ISO 8601 (e.g., 2025-07-15T17:10:58Z)")

    _validate_string_field(config, "config_file", result, scope)

    for list_key, label in [("models", "model_id"), ("executables", "executable_id")]:
        if list_key in config:
            items = config[list_key]
            if not isinstance(items, list) or not items:
                result.add_error(f"{scope}: '{list_key}' must be a non-empty array of strings")
                continue
            seen = set()
            for item in items:
                if not validate_identifier(item):
                    result.add_error(f"{scope}: {label} '{item}' must be lowercase and contain no spaces")
                if item in seen:
                    result.add_error(f"{scope}: duplicate {label} '{item}' in '{list_key}'")
                seen.add(item)

    _validate_number_field(config, "particles_per_thread", result, scope, positive=True)
    _validate_number_field(config, "max_threads", result, scope, positive=True)
    _validate_number_field(config, "n_repeats", result, scope, positive=True)

    if "architecture" in config:
        arch = config["architecture"]
        if not isinstance(arch, dict):
            result.add_error(f"{scope}: 'architecture' must be an object")
        else:
            _require_keys(
                arch,
                ["machine", "processor", "cpu_count", "os", "python_version"],
                result,
                f"{scope}.architecture",
            )
            _validate_string_field(arch, "machine", result, f"{scope}.architecture")
            _validate_string_field(arch, "processor", result, f"{scope}.architecture")
            _validate_string_field(arch, "os", result, f"{scope}.architecture")
            _validate_string_field(arch, "python_version", result, f"{scope}.architecture")
            _validate_number_field(arch, "cpu_count", result, f"{scope}.architecture", positive=True, integer=True)

    if "software_versions" in config:
        versions = config["software_versions"]
        if not isinstance(versions, dict):
            result.add_error(f"{scope}: 'software_versions' must be an object")
        else:
            for key, value in versions.items():
                if not is_non_empty_str(key) or not is_non_empty_str(value):
                    result.add_error(f"{scope}: 'software_versions' must map strings to strings")


def _validate_rate(value: Any, result: ValidationResult, scope: str) -> None:
    if value is None:
        return
    if not is_finite_number(value):
        result.add_error(f"{scope}: rate must be a finite number or null")
        return
    if float(value) <= 0:
        result.add_error(f"{scope}: rate must be positive when not null")


def validate_results(config: dict[str, Any], results: dict[str, Any], result: ValidationResult) -> None:
    scope = "results.json"
    required = ["run_id", "date", "results"]
    _require_keys(results, required, result, scope)

    _validate_string_field(results, "run_id", result, scope)

    if "date" in results and not is_iso8601(results["date"]):
        result.add_error(f"{scope}: 'date' must be ISO 8601 (e.g., 2025-07-15T17:10:58Z)")

    if "run_id" in config and "run_id" in results and config["run_id"] != results["run_id"]:
        result.add_error(f"{scope}: run_id mismatch with config.json")
    if "date" in config and "date" in results and config["date"] != results["date"]:
        result.add_error(f"{scope}: date mismatch with config.json")

    if "software_versions" in results:
        versions = results["software_versions"]
        if not isinstance(versions, dict):
            result.add_error(f"{scope}: 'software_versions' must be an object")
        else:
            for key, value in versions.items():
                if not is_non_empty_str(key) or not is_non_empty_str(value):
                    result.add_error(f"{scope}: 'software_versions' must map strings to strings")

    if "results" not in results:
        return

    results_obj = results["results"]
    if not isinstance(results_obj, dict):
        result.add_error(f"{scope}: 'results' must be an object")
        return

    config_models = set(config.get("models", [])) if isinstance(config.get("models"), list) else set()
    config_executables = set(config.get("executables", [])) if isinstance(config.get("executables"), list) else set()

    # Completeness checks
    missing_models = config_models - set(results_obj.keys())
    if missing_models:
        result.add_error(f"{scope}: missing results for models: {sorted(missing_models)}")

    thread_sets: list[list[int]] = []

    for model_id, model_results in results_obj.items():
        if not validate_identifier(model_id):
            result.add_error(f"{scope}: model_id '{model_id}' must be lowercase and contain no spaces")
        if config_models and model_id not in config_models:
            result.add_error(f"{scope}: model_id '{model_id}' not listed in config.json")

        if not isinstance(model_results, dict):
            result.add_error(f"{scope}: results for model '{model_id}' must be an object")
            continue

        missing_execs = config_executables - set(model_results.keys())
        if missing_execs:
            result.add_error(
                f"{scope}: model '{model_id}' missing executables: {sorted(missing_execs)}"
            )

        for exec_id, exec_results in model_results.items():
            if not validate_identifier(exec_id):
                result.add_error(f"{scope}: executable_id '{exec_id}' must be lowercase and contain no spaces")
            if config_executables and exec_id not in config_executables:
                result.add_error(f"{scope}: executable_id '{exec_id}' not listed in config.json")

            if not isinstance(exec_results, dict):
                result.add_error(f"{scope}: results for {model_id}/{exec_id} must be an object")
                continue

            if "scaling" not in exec_results:
                result.add_error(f"{scope}: missing 'scaling' for {model_id}/{exec_id}")
                continue
            if "max_performance" not in exec_results:
                result.add_error(f"{scope}: missing 'max_performance' for {model_id}/{exec_id}")
                continue

            scaling = exec_results["scaling"]
            if not isinstance(scaling, list) or not scaling:
                result.add_error(f"{scope}: 'scaling' for {model_id}/{exec_id} must be a non-empty array")
                continue

            threads_seen: set[int] = set()
            threads_list: list[int] = []
            for idx, point in enumerate(scaling):
                if not isinstance(point, dict):
                    result.add_error(
                        f"{scope}: scaling[{idx}] for {model_id}/{exec_id} must be an object"
                    )
                    continue

                if "threads" not in point:
                    result.add_error(
                        f"{scope}: scaling[{idx}] for {model_id}/{exec_id} missing 'threads'"
                    )
                else:
                    threads_val = point["threads"]
                    if not is_int_number(threads_val) or float(threads_val) <= 0:
                        result.add_error(
                            f"{scope}: scaling[{idx}] for {model_id}/{exec_id} 'threads' must be a positive integer"
                        )
                    else:
                        threads_int = int(threads_val)
                        if threads_int in threads_seen:
                            result.add_error(
                                f"{scope}: duplicate thread count {threads_int} for {model_id}/{exec_id}"
                            )
                        threads_seen.add(threads_int)
                        threads_list.append(threads_int)

                if "active_rate" not in point:
                    result.add_error(
                        f"{scope}: scaling[{idx}] for {model_id}/{exec_id} missing 'active_rate'"
                    )
                if "inactive_rate" not in point:
                    result.add_error(
                        f"{scope}: scaling[{idx}] for {model_id}/{exec_id} missing 'inactive_rate'"
                    )

                _validate_rate(point.get("active_rate"), result, f"{scope}: scaling[{idx}] {model_id}/{exec_id}")
                _validate_rate(
                    point.get("inactive_rate"), result, f"{scope}: scaling[{idx}] {model_id}/{exec_id}"
                )

            if threads_list:
                thread_sets.append(sorted(threads_list))

            max_perf = exec_results["max_performance"]
            if not isinstance(max_perf, dict):
                result.add_error(f"{scope}: max_performance for {model_id}/{exec_id} must be an object")
            else:
                if "threads" not in max_perf:
                    result.add_error(f"{scope}: max_performance for {model_id}/{exec_id} missing 'threads'")
                else:
                    threads_val = max_perf["threads"]
                    if not is_int_number(threads_val) or float(threads_val) <= 0:
                        result.add_error(
                            f"{scope}: max_performance for {model_id}/{exec_id} 'threads' must be a positive integer"
                        )
                    elif threads_list and int(threads_val) not in threads_list:
                        result.add_warning(
                            f"{scope}: max_performance threads {int(threads_val)} not in scaling list for {model_id}/{exec_id}"
                        )

                if "active_rate" not in max_perf:
                    result.add_error(
                        f"{scope}: max_performance for {model_id}/{exec_id} missing 'active_rate'"
                    )
                if "inactive_rate" not in max_perf:
                    result.add_error(
                        f"{scope}: max_performance for {model_id}/{exec_id} missing 'inactive_rate'"
                    )

                _validate_rate(max_perf.get("active_rate"), result, f"{scope}: max_performance {model_id}/{exec_id}")
                _validate_rate(
                    max_perf.get("inactive_rate"), result, f"{scope}: max_performance {model_id}/{exec_id}"
                )

    # Thread consistency across models/executables
    if thread_sets:
        baseline = thread_sets[0]
        for threads in thread_sets[1:]:
            if threads != baseline:
                result.add_error(f"{scope}: thread counts are inconsistent across models/executables")
                break


def load_json(path: Path, result: ValidationResult, scope: str) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            result.add_error(f"{scope}: root JSON value must be an object")
            return None
        return data
    except FileNotFoundError:
        result.add_error(f"{scope}: file not found")
    except json.JSONDecodeError as exc:
        result.add_error(f"{scope}: invalid JSON ({exc})")
    return None


def load_and_validate_run(run_dir: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None, ValidationResult]:
    result = ValidationResult(run_path=run_dir)
    config_path = run_dir / "config.json"
    results_path = run_dir / "results.json"

    config = load_json(config_path, result, "config.json")
    results = load_json(results_path, result, "results.json")

    if config is None or results is None:
        return None, None, result

    validate_config(config, result)
    validate_results(config, results, result)

    if config.get("run_id") and config["run_id"] != run_dir.name:
        result.add_warning("config.json run_id does not match directory name")

    return config, results, result


def validate_run_dir(run_dir: Path) -> ValidationResult:
    _, _, result = load_and_validate_run(run_dir)
    return result


def discover_run_dirs_recursive(root: Path) -> list[Path]:
    run_dirs: set[Path] = set()
    if (root / "config.json").exists() and (root / "results.json").exists():
        run_dirs.add(root)

    for config_path in root.rglob("config.json"):
        run_dir = config_path.parent
        if (run_dir / "results.json").exists():
            run_dirs.add(run_dir)

    return sorted(run_dirs, key=lambda path: path.as_posix())


def discover_run_dirs(root: Path) -> list[Path]:
    if (root / "config.json").exists() and (root / "results.json").exists():
        return [root]

    run_dirs = [
        child
        for child in root.iterdir()
        if child.is_dir()
        and (child / "config.json").exists()
        and (child / "results.json").exists()
    ]
    if run_dirs:
        return sorted(run_dirs, key=lambda path: path.name)

    runs_subdir = root / "runs"
    if runs_subdir.is_dir():
        run_dirs = [
            child
            for child in runs_subdir.iterdir()
            if child.is_dir()
            and (child / "config.json").exists()
            and (child / "results.json").exists()
        ]
        return sorted(run_dirs, key=lambda path: path.name)

    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate XDG benchmark data against docs/schema.md")
    parser.add_argument(
        "paths",
        nargs="+",
        help="Run directory or parent directory containing runs (accepts multiple)",
    )
    args = parser.parse_args()

    any_invalid = False
    any_missing = False
    total_paths = len(args.paths)
    checked_paths = 0
    missing_paths = 0
    no_run_paths = 0
    total_runs = 0
    total_valid = 0
    total_invalid = 0
    total_warnings = 0

    for raw_path in args.paths:
        root = Path(raw_path).expanduser().resolve()
        print(f"\nPath: {root}")

        if not root.exists() or not root.is_dir():
            print(f"Error: '{root}' is not a directory", file=sys.stderr)
            any_missing = True
            missing_paths += 1
            continue

        run_dirs = discover_run_dirs(root)
        if not run_dirs:
            print(
                f"No runs found in '{root}' (expected config.json and results.json)",
                file=sys.stderr,
            )
            any_missing = True
            no_run_paths += 1
            continue

        checked_paths += 1
        print(f"Validating {len(run_dirs)} run(s) in {root}")
        valid_count = 0
        warnings_count = 0
        for run_dir in run_dirs:
            run_id = run_dir.name
            result = validate_run_dir(run_dir)
            if result.ok:
                valid_count += 1
                status = "OK"
            else:
                status = f"ERRORS ({len(result.errors)})"

            if result.warnings:
                warnings_count += len(result.warnings)
                status = f"{status}, WARNINGS ({len(result.warnings)})"

            print(f"- {run_id}: {status}")
            for message in result.errors:
                print(f"  - {message}")
            for message in result.warnings:
                print(f"  - {message}")

        print(f"Summary: {valid_count} valid, {len(run_dirs) - valid_count} invalid")
        if warnings_count:
            print(f"Warnings: {warnings_count}")

        total_runs += len(run_dirs)
        total_valid += valid_count
        total_invalid += len(run_dirs) - valid_count
        total_warnings += warnings_count

        if valid_count != len(run_dirs):
            any_invalid = True

    print("\nOverall Summary")
    print(f"Paths provided: {total_paths}")
    print(f"Paths checked: {checked_paths}")
    if missing_paths:
        print(f"Paths missing/invalid: {missing_paths}")
    if no_run_paths:
        print(f"Paths with no runs: {no_run_paths}")
    print(f"Runs checked: {total_runs}")
    print(f"Runs valid: {total_valid}")
    print(f"Runs invalid: {total_invalid}")
    if total_warnings:
        print(f"Total warnings: {total_warnings}")

    if any_missing:
        return 2
    return 1 if any_invalid else 0


if __name__ == "__main__":
    sys.exit(main())
