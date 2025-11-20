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
  python scaling_study.py --config scaling_config.i
  python scaling_study.py --config scaling_config.i --skip-runs   # Dry run (no OpenMC execution)
  python scaling_study.py --config scaling_config.i --store-raw-csv

"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone
import platform
import configparser

from typing import Dict, Any

try:
    import numpy as np
except ImportError:  # Should exist, but guard anyway
    np = None  # type: ignore

try:
    import openmc
except ImportError:
    openmc = None  # type: ignore


class MyConfigParser(configparser.ConfigParser):
    """Config parser that preserves option case."""

    def __init__(self, *args, **kwargs):
        super(MyConfigParser, self).__init__(*args, **kwargs)
        self.optionxform = str


def get_config(config_file: str = 'scaling_config.i') -> MyConfigParser:
    config = MyConfigParser()
    config.read(config_file)
    return config


def get_executable_config(config: MyConfigParser) -> tuple[str, str]:
    if not config.has_option('options', 'executable_label'):
        raise ValueError("Missing 'executable_label' in [options] section of scaling_config.i.")
    if not config.has_option('options', 'executable_path'):
        raise ValueError("Missing 'executable_path' in [options] section of scaling_config.i.")
    label = config.get('options', 'executable_label')
    path = config.get('options', 'executable_path')
    return label, path


def gather_scaling_data(model_name, executable_label, executable_path, config, results_dir):  # type: ignore[override]
    if np is None:
        raise ImportError("NumPy is required to gather scaling data.")
    if openmc is None:
        raise ImportError("OpenMC is required to gather scaling data.")

    max_threads = config.getint('options', 'max_threads')

    input_path = config['models'][model_name]

    # data storage
    threads = np.array(range(0, max_threads, 5))
    inactive_particles = np.zeros(len(threads), dtype=int)
    active_particles = np.zeros(len(threads), dtype=int)
    inactive_time = np.zeros(len(threads), dtype=float)
    active_time = np.zeros(len(threads), dtype=float)

    executable = executable_path
    results = {}
    flux_results = None
    energy_divs = None
    eigenvalue = None
    run_mode = None

    for i, n_threads in enumerate(threads):
        n_threads = max(1, n_threads)

        openmc.reset_auto_ids()
        try:
            model = openmc.Model.from_model_xml(input_path + '/model.xml')
        except Exception:
            paths = [input_path + '/' + p for p in ['geometry.xml', 'materials.xml', 'settings.xml', 'tallies.xml']]
            model = openmc.Model.from_xml(*paths)

        if model.settings.run_mode == 'eigenvalue':
            model.settings.batches = 10
            model.settings.inactive = 5
        if model.settings.run_mode == 'fixed source':
            model.settings.batches = 5

        # add flux tally to model based on fine energy group structure
        tally = openmc.Tally()
        tally.scores = ['flux']
        e_filter = openmc.EnergyFilter.from_group_structure('CCFE-709')
        tally.filters = [e_filter]

        model.tallies.append(tally)

        particles_per_thread = config.getint('options', 'particles_per_thread')
        output = config.getboolean('options', 'output')

        print(f'Running {executable_label} with {n_threads} threads')
        threads[i] = n_threads
        n_runs = config.getint('options', 'n_repeats')
        for _ in range(n_runs):
            try:
                statepoint = model.run(openmc_exec=executable, threads=n_threads, particles=particles_per_thread*n_threads, output=output, event_based=True)
            except Exception as e:
                print(f"Error running {executable_label} for model {Path(input_path) / 'model.xml'} with {n_threads} threads: {e}")
                raise e

            with openmc.StatePoint(statepoint, autolink=False) as sp:
                if sp.run_mode == 'eigenvalue':
                    inactive_particles[i] = sp.n_inactive * sp.n_particles
                    inactive_time[i] += sp.runtime['inactive batches']
                    inactive_batches = sp.n_inactive
                else:
                    inactive_particles[i] = 0
                    inactive_batches = 0
                active_particles[i] = sp.n_particles * (sp.n_batches - inactive_batches)
                active_time[i] += sp.runtime['active batches']

        # after the last run, get some data from the final statepoint.
        # it will be run with the most particles and results should
        # have the lowest variance
        with openmc.StatePoint(statepoint, autolink=False) as sp:
            run_mode = sp.run_mode
            print(f'Run mode is: {run_mode}')
            if sp.run_mode == 'eigenvalue':
                eigenvalue = sp.keff.nominal_value
            else:
                eigenvalue = None

            # extract flux results from the statepoint file
            sp_tally = sp.tallies[tally.id]
            flux_results = sp_tally.get_reshaped_data().squeeze()
            energy_divs = e_filter.values

    inactive_time /= n_runs
    active_time /= n_runs

    inactive_rates = np.asarray(inactive_particles) / np.asarray(inactive_time)
    active_rates = np.asarray(active_particles) / np.asarray(active_time)

    results['run_mode'] = run_mode
    results['inactive_rates'] = inactive_rates
    results['active_rates'] = active_rates
    results['threads'] = threads
    results['eigenvalue'] = eigenvalue
    results['flux_values'] = flux_results
    results['energy_divs'] = energy_divs

    return results

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
    exe_label, exe_path = get_executable_config(config)
    exe_key = normalize_identifier(exe_label)
    for model_name in config['models']:
        model_key = normalize_identifier(model_name)
        results[model_key] = {}
        if skip_runs:
            # Produce placeholder thread scaling (minimal) for dry-run
            threads = [1]
            entries = [{"threads": 1, "active_rate": None, "inactive_rate": None}]
        else:
            data = gather_scaling_data(model_name, exe_label, exe_path, config, results_dir=None)
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

    exe_label, exe_path = get_executable_config(config)

    # Build config.json structure
    config_json = {
        "run_id": run_id,
        "date": date_iso,
        "config_file": args.config,
        "models": [normalize_identifier(m) for m in config['models']],
        "executables": [normalize_identifier(exe_label)],
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
