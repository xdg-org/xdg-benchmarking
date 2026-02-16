#!/usr/bin/env python3
"""Generate JSON benchmarking data conforming to schema in schema.md.

This script reuses scaling utilities from scaling.py to perform a scaling study
and produces two JSON files:
  results/runs/{run_id}/config.json
  results/runs/{run_id}/results.json
Optionally writes raw CSV traceability files to results/runs/{run_id}/raw/.

Schema additions: includes architecture object with machine, processor,
CPU count, OS and python version.

Example usage:
  python scaling_json.py --config scaling_config.i
  python scaling_json.py --config scaling_config.i --skip-runs   # Dry run (no OpenMC execution)
  python scaling_json.py --config scaling_config.i --store-raw-csv

"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone
import platform

from typing import Dict, Any

# Reuse existing functions/classes from scaling.py
from scaling import (
    gather_scaling_data,
    get_config,
    MyConfigParser,
)

try:
    import numpy as np
except ImportError:  # Should exist, but guard anyway
    np = None  # type: ignore

# ---------- Helpers ---------- #

def iso_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_identifier(name: str) -> str:
    return name.strip().lower().replace(' ', '_')


def collect_architecture() -> Dict[str, Any]:
    return {
        "machine": platform.machine(),
        "processor": platform.processor() or platform.uname().processor,
        "cpu_count": os.cpu_count(),
        "os": f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
    }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sanitize_rate(value: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value) or value <= 0:
            return None
        return float(value)
    return None


def build_scaling_entries(threads, inactive_rates, active_rates):
    entries = []
    for i, t in enumerate(threads):
        inactive = sanitize_rate(inactive_rates[i]) if inactive_rates is not None else None
        active = sanitize_rate(active_rates[i])
        entries.append({
            "threads": int(t),
            "active_rate": active,
            "inactive_rate": inactive,
        })
    return entries


def compute_max_performance(entries):
    # Select entry with max active_rate (excluding null)
    valid = [e for e in entries if e["active_rate"] is not None]
    if not valid:
        return {"threads": None, "active_rate": None, "inactive_rate": None}
    best = max(valid, key=lambda e: e["active_rate"])
    return {
        "threads": best["threads"],
        "active_rate": best["active_rate"],
        "inactive_rate": best["inactive_rate"],
    }

# ---------- Main routine ---------- #

def generate_results(config: MyConfigParser, skip_runs: bool, store_raw_csv: bool, raw_dir: Path) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for model_name in config['models']:
        model_key = normalize_identifier(model_name)
        results[model_key] = {}
        for exe_name in config['executables']:
            exe_key = normalize_identifier(exe_name)
            if skip_runs:
                # Produce placeholder thread scaling (minimal) for dry-run
                threads = [1]
                entries = [{"threads": 1, "active_rate": None, "inactive_rate": None}]
            else:
                data = gather_scaling_data(model_name, exe_name, config, results_dir=None)
                threads = data['threads']
                inactive_rates = data.get('inactive_rates')
                active_rates = data['active_rates']
                entries = build_scaling_entries(threads, inactive_rates, active_rates)
                if store_raw_csv:
                    # Write a raw CSV for traceability
                    raw_csv = raw_dir / f"{model_key}_{exe_key}_scaling.csv"
                    with open(raw_csv, 'w') as f:
                        f.write("threads,inactive_rate,active_rate\n")
                        for e in entries:
                            f.write(f"{e['threads']},{e['inactive_rate'] if e['inactive_rate'] is not None else ''},{e['active_rate'] if e['active_rate'] is not None else ''}\n")
            results[model_key][exe_key] = {
                "scaling": entries,
                "max_performance": compute_max_performance(entries)
            }
    return results


def main():
    parser = argparse.ArgumentParser(description="Generate JSON benchmark results matching schema.md")
    parser.add_argument('--config', default='scaling_config.i', help='Path to scaling configuration file')
    parser.add_argument('--run-id', default=None, help='Override run id (timestamp if omitted)')
    parser.add_argument('--skip-runs', action='store_true', help='Skip actual OpenMC execution (dry run with placeholders)')
    parser.add_argument('--store-raw-csv', action='store_true', help='Store raw CSV scaling data in raw/ directory')
    args = parser.parse_args()

    config = get_config(args.config)
    
    run_id = args.run_id or datetime.now().strftime('%Y%m%d_%H%M%S')
    date_iso = iso_timestamp()

    base_results_dir = Path('results') / 'runs' / run_id
    ensure_dir(base_results_dir)
    raw_dir = base_results_dir / 'raw'
    if args.store_raw_csv:
        ensure_dir(raw_dir)

    architecture = collect_architecture()

    # Build config.json structure
    config_json = {
        "run_id": run_id,
        "date": date_iso,
        "config_file": args.config,
        "models": [normalize_identifier(m) for m in config['models']],
        "executables": [normalize_identifier(e) for e in config['executables']],
        "particles_per_thread": config.getint('options', 'particles_per_thread'),
        "max_threads": config.getint('options', 'max_threads'),
        "n_repeats": config.getint('options', 'n_repeats'),
        "architecture": architecture,
    }

    # Generate results.json
    results_json = {
        "run_id": run_id,
        "date": date_iso,
        "results": generate_results(config, args.skip_runs, args.store_raw_csv, raw_dir if args.store_raw_csv else Path('.')),
    }

    # Write JSON files
    with open(base_results_dir / 'config.json', 'w') as f:
        json.dump(config_json, f, indent=2)
    with open(base_results_dir / 'results.json', 'w') as f:
        json.dump(results_json, f, indent=2)

    print(f"JSON benchmarking data written to {base_results_dir}")
    if args.skip_runs:
        print("Dry run completed (no OpenMC executions).")


if __name__ == '__main__':
    main()
