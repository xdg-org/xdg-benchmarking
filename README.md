# XDG Benchmarking Data Generation

Benchmarking of the [XDG Project](https://github.com/pshriwise/xdg)

## Configuration (`scaling_config.i`)
`scaling_config.i` is an INI-style schema. Every key is case-sensitive.

```
[models]
<model_name> = /path/to/model-dir      # Required; used for dashboard labels

[options]
executable_label = <label>             # Required; label shown in plots/JSON
executable_path = /path/to/openmc      # Required; absolute path to the OpenMC binary
particles_per_thread = <int>           # Required; particles per thread
max_threads = <int>                    # Required; global thread limit
n_repeats = <int>                      # Required; runs averaged per thread count
output = <bool>                        # Optional (default true); pass OpenMC stdout through
results_dir = <path>                   # Optional (default results); root for study artifacts

[software_versions]
<component_name> = <version_or_commit> # Optional; copied verbatim into JSON metadata

[<custom_section>]
...                                    # Ignored by scaling_study.py but preserved for user notes
```

To add a model, append a new entry under `[models]`. Adjust `[options]` to point at a different executable or change run cadence without editing Python.

## Model Requirements
Entries listed in `[models]` must point to directories that can be loaded by OpenMC. Each directory should either:

- Contain a `model.xml` file compatible with `openmc.Model.from_model_xml`, or
- Provide the standard component files (`geometry.xml`, `materials.xml`, `settings.xml`, and optionally `tallies.xml`) so `openmc.Model.from_xml` succeeds.

When the scaling study runs, it temporarily overrides batch counts (10 total/5 inactive for eigenvalue cases, 5 batches for fixed-source) and appends a CCFE-709 flux tally. Models should therefore be set up so these adjustments are acceptable and so the provided executable can run them with varying thread counts.

## Scaling Study Script (`scaling_study.py`)
`scaling_study.py` reads `scaling_config.i`, executes the scaling runs (or does a dry run with `--skip-runs`), and writes structured results into `results/runs/<timestamp>/`. It also records architecture metadata, optional raw CSV traces (`--store-raw-csv`), and the normalized configuration used for the run. Use this script whenever you need benchmarking data in JSON form that matches `schema.md`, e.g.:

```bash
python scaling_study.py --config scaling_config.i
python scaling_study.py --config scaling_config.i --skip-runs --store-raw-csv
```
