# XDG Benchmarking Results

This directory contains the results from an XDG benchmarking run.

## Directory Structure

- `index.html` - Main results page with links to all dashboards
- `run_summary.txt` - Detailed summary of the run configuration and parameters
- `README.md` - This file
- `dashboards/` - Interactive HTML dashboards for each model
  - `{model_name}.html` - Main dashboard for each model
  - `{model_name}_description.html` - Model description (if available)
- `{model_name}_dashboard.html` - Individual model dashboards
- `{model_name}_{executable}_scaling.csv` - CSV files with scaling data

## Viewing Results

1. Open `index.html` in a web browser to see all results
2. Or open individual dashboard files directly
3. Check `run_summary.txt` for detailed run information

## Files

- **CSV files**: Scaling data in comma-separated format
- **Dashboard files**: Interactive Plotly charts showing scaling performance
- **Description files**: Markdown descriptions of each model (if available)
