# XDG Benchmarking Dashboard

A comprehensive Plotly Dash web application for exploring and analyzing XDG (Accelerated Discretized Geometry) benchmarking results.

## Features

### 📊 Interactive Visualizations
- **Performance Scaling Charts**: Compare thread scaling across different executables
- **Speedup Analysis**: Visualize parallel efficiency and speedup curves
- **Executable Comparison**: Bar charts comparing maximum performance across models
- **Real-time Filtering**: Filter by model, executable, run ID, and performance metric

### 🔍 Data Analysis
- **Summary Statistics**: Key performance metrics and best configurations
- **Raw Data Table**: Interactive table with all benchmark data
- **Multi-run Support**: Compare results across different benchmark runs
- **Statistical Analysis**: Performance comparisons and efficiency calculations

### 🎯 Key Metrics
- **Active Rate**: Particles processed per second during active simulation
- **Inactive Rate**: Particles processed per second during inactive/burnup cycles
- **Speedup**: Performance improvement relative to single-thread execution
- **Efficiency**: Speedup divided by number of threads

## Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Setup
1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Running the Dashboard
1. Ensure your benchmark results are in the `results/` directory
2. Start the dashboard:
   ```bash
   python app.py
   ```
3. Open your web browser and navigate to `http://localhost:8050`

### Fetching Remote Results

Set `XDG_RESULTS_ZIP_URL` to the direct download URL of your benchmark ZIP before
starting the app. Alternatively, create `local_config.json` beside `app.py`:

```json
{"results_zip_url": "https://example.com/benchmark-results.zip"}
```

The environment variable takes precedence. The ZIP can contain nested folders;
each run needs schema-valid `config.json` and `results.json` files as described in
[the schema documentation](docs/schema.md). Identical copies of a run are loaded
once. Invalid runs are skipped and counted in the status message; archives with
no valid data or conflicting copies fail the refresh.

The first page visit fetches remote data if no remote snapshot is cached. Click
**Refresh Data** to fetch later changes. The dashboard polls progress every two
seconds and updates the charts and filters when the new dataset is ready. A date
range covering all available dates expands to include new results. Selected run
tags are preserved; refresh does not select new runs. Unavailable selections are
identified on the page and restored automatically if a later refresh finds them.
Empty advanced filters mean **All**, and explicit property selections are
preserved where possible.

Downloads have a 30-second socket timeout and a 120-second overall download
budget. Data is validated before publishing, and failures keep the last working
dataset. After a successful fetch, only the remote snapshot feeds the dashboard;
bundled data is used until then. Downloaded data is cached under
`results/.remote/` (or `$RESULTS_DIR/.remote/`) without modifying bundled runs.

Gunicorn workers on one host share progress and cache files using filesystem
locks. Multiple service instances need a shared filesystem for this mechanism.
Use `gunicorn app:server` for deployment; the server honors `PORT` and
`MAX_WORKERS`. The static GitHub Pages export has a separate, manual rebuild
process described in [GITHUB_PAGES_SETUP.md](GITHUB_PAGES_SETUP.md).

Run regression tests with
`python -m unittest test_refresh test_run_selection test_comparison_url -v`.

### Data Structure
The dashboard expects benchmark results in the following structure:
```
results/
├── 20250715_171058/
│   ├── run_summary.txt
│   ├── Model_executable_scaling.csv
│   └── ...
└── 20250715_181043/
    ├── run_summary.txt
    ├── Model_executable_scaling.csv
    └── ...
```

### CSV File Format
Each scaling CSV file should contain:
```csv
# Threads,Inactive rate,Active rate
1.000000000000000e+00,nan,5.704179589970383e+03
5.000000000000000e+00,nan,1.762661104642666e+04
1.000000000000000e+01,nan,3.233096046521205e+04
1.500000000000000e+01,nan,4.361667815749022e+04
```

## Dashboard Features

### Filters
- **Find runs**: Search across run IDs, UTC dates, configurations, and machine
  metadata. Use the date range and collapsible advanced filters to narrow the
  table. These discovery controls do not change your selected comparison.
- **Selection**: The newest run starts selected. Check rows to compare runs,
  choose **Select matching runs** to add all search results, or remove runs using
  their selection chips. **Clear selection** leaves the charts empty until you
  choose runs. Sorting, pagination, and searching preserve selected runs.
- **Model**: Select specific reactor models (Tokamak, ATR, MSRE)
- **Executable**: Choose which OpenMC implementations to compare
- **Metric**: Switch between Active and Inactive rates

### Sharing a comparison

The address bar updates automatically with the selected run tags, model,
executables, and metric. Copy that URL to reopen the same comparison or share it
using the deployed site's address. Run discovery searches and advanced filters
are separate from the plotted comparison and are not included in the link.

For example:

```text
/?run=20251121_153916&run=20251121_225203&model=msre&exe=xdg&metric=active
```

Use repeated `run` and `exe` parameters for multiple selections. `metric` is
`active` or `inactive`. An explicit `run=` preserves an empty selection on
reload. Browser Back and Forward restore previous comparisons.

Missing run tags stay in the URL and appear as removable **unavailable** chips.
The page identifies missing tags and plots only available selected runs. If none
are available, the charts explain how to recover rather than substituting a
different run. Refreshing data retries those selections. Unknown model or
executable choices are also identified; invalid metrics use active rate with a
notice, and unreadable query parameters produce an empty comparison with a
recovery message.

### Charts
1. **Performance Scaling**: Line charts showing performance vs thread count
2. **Speedup Analysis**: Speedup curves with ideal scaling reference
3. **Executable Comparison**: Bar charts comparing maximum performance
4. **Summary Statistics**: Key metrics and best configurations
5. **Raw Data Table**: Interactive table with all data points

### Interactivity
- Hover over data points for detailed information
- Zoom and pan on charts
- Download charts as PNG images
- Filter data dynamically
- Sort and search in data tables

## Supported Models and Executables

### Models
- **Tokamak**: Fusion reactor geometry
- **ATR**: Advanced Test Reactor (fission)
- **MSRE**: Molten Salt Reactor Experiment

### Executables
- **double-down**: Reference/baseline OpenMC implementation
- **xdg**: Accelerated Discretized Geometry implementation
- **moab**: MOAB mesh-based optimization

## Development

### Adding New Features
The dashboard is built with Plotly Dash and can be easily extended:
- Add new chart types in the callback functions
- Implement additional filtering options
- Create custom analysis functions
- Add export capabilities

### Customization
- Modify the layout in `app.layout`
- Add new callbacks for interactive features
- Customize styling and themes
- Implement additional data processing functions

## Troubleshooting

### Common Issues
1. **No data displayed**: Check that CSV files are in the correct format and location
2. **Import errors**: Ensure all dependencies are installed with `pip install -r requirements.txt`
3. **Port conflicts**: Change the port in `app.py` if 8050 is already in use

### Data Validation
The dashboard automatically validates:
- CSV file format and column names
- Numeric data conversion
- Missing or invalid data points

## Contributing

To contribute to this project:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source and available under the MIT License.

## Support

For questions or issues:
1. Check the troubleshooting section
2. Review the data format requirements
3. Ensure all dependencies are properly installed
4. Create an issue with detailed error information
