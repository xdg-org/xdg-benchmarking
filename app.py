import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import json
import os
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from schema_validator import discover_run_dirs_recursive, load_and_validate_run

# Data refresh configuration
LOCAL_CONFIG_PATH = Path("local_config.json")
RESULTS_DIR = Path("results")
DATA_LOCK = threading.Lock()
DOWNLOAD_LOCK = threading.Lock()
DOWNLOAD_STATE = {"status": "idle", "message": "", "version": 0}

# Initialize the Dash app
app = dash.Dash(__name__, title="XDG Benchmarking Dashboard")
server = app.server

# Data loading and processing functions
def build_energy_axis(mean_flux, energy_divs):
    if isinstance(energy_divs, list) and energy_divs:
        if len(energy_divs) == len(mean_flux):
            return energy_divs
        if len(energy_divs) == len(mean_flux) + 1:
            return [
                (energy_divs[i] + energy_divs[i + 1]) / 2
                for i in range(len(mean_flux))
            ]
    return list(range(1, len(mean_flux) + 1))

def format_run_date(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return series
    parsed = pd.to_datetime(series, errors='coerce', utc=True).dt.tz_convert(None)
    formatted = parsed.dt.strftime('%B %-d, %Y %-I:%M %p')
    return formatted.fillna(series)

def parse_date_range(start_date, end_date):
    start_ts = pd.to_datetime(start_date, errors='coerce') if start_date else None
    end_ts = pd.to_datetime(end_date, errors='coerce') if end_date else None
    if end_ts is not None and pd.notna(end_ts):
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return start_ts, end_ts

def load_results_url():
    env_url = os.environ.get("XDG_RESULTS_ZIP_URL")
    if env_url:
        return env_url, None
    if not LOCAL_CONFIG_PATH.exists():
        return None, f"Missing {LOCAL_CONFIG_PATH}"
    try:
        config = json.loads(LOCAL_CONFIG_PATH.read_text())
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON in {LOCAL_CONFIG_PATH}: {exc}"
    url = config.get("results_zip_url") or config.get("results_url")
    if not url:
        return None, f"Missing results_zip_url in {LOCAL_CONFIG_PATH}"
    return url, None


def set_download_state(*, status=None, message=None, increment_version=False):
    with DOWNLOAD_LOCK:
        if status is not None:
            DOWNLOAD_STATE["status"] = status
        if message is not None:
            DOWNLOAD_STATE["message"] = message
        if increment_version:
            DOWNLOAD_STATE["version"] += 1


def extract_results_zip(zip_path: Path, target_dir: Path) -> None:
    print(f"[refresh] Extracting zip: {zip_path}")
    with tempfile.TemporaryDirectory() as tmpdir:
        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        run_dirs = discover_run_dirs_recursive(extract_dir)
        print(f"[refresh] Found {len(run_dirs)} run(s) in extracted data")

        target_runs_dir = target_dir / "runs"
        target_runs_dir.mkdir(parents=True, exist_ok=True)
        for run_dir in run_dirs:
            dest = target_runs_dir / run_dir.name
            print(f"[refresh] Copying run {run_dir} -> {dest}")
            shutil.copytree(run_dir, dest, dirs_exist_ok=True)


def download_and_extract_results(url: str, target_dir: Path) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "results.zip"
        print(f"[refresh] Downloading results from {url}")
        urllib.request.urlretrieve(url, zip_path)
        extract_results_zip(zip_path, target_dir)


def refresh_data_from_remote():
    with DOWNLOAD_LOCK:
        if DOWNLOAD_STATE["status"] == "downloading":
            return False
        DOWNLOAD_STATE["status"] = "downloading"
        DOWNLOAD_STATE["message"] = "Starting refresh..."

    def _worker():
        try:
            set_download_state(message="Loading results URL...")
            url, error = load_results_url()
            if error:
                set_download_state(message=f"Refresh failed: {error}", status="idle")
                print(f"[refresh] {error}")
                return

            set_download_state(message="Downloading ZIP...")
            download_and_extract_results(url, RESULTS_DIR)
            set_download_state(message="Loading data...")
            new_df, new_flux_df = load_benchmark_data()
            with DATA_LOCK:
                global df, flux_df
                df = new_df
                flux_df = new_flux_df

            runs_count = 0 if df.empty else df['Run_ID'].nunique()
            message = f"Loaded {runs_count} dataset(s) at {datetime.now().strftime('%b %d, %Y %I:%M %p')}"
            set_download_state(message=message, status="idle", increment_version=True)
            print(f"[refresh] {message}")
        except Exception as exc:
            set_download_state(message=f"Refresh failed: {exc}", status="idle")
            print(f"[refresh] Refresh failed: {exc}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return True


def load_benchmark_data():
    """Load all benchmark data from the results directory (schema-based)."""
    data = []
    flux_data = []
    results_dir = Path("results")

    if not results_dir.exists():
        return pd.DataFrame()

    run_dirs = discover_run_dirs_recursive(results_dir)
    if not run_dirs:
        return pd.DataFrame()

    for run_dir in run_dirs:
        config, results, validation = load_and_validate_run(run_dir)
        if not validation.ok:
            print(f"Skipping invalid run: {run_dir}")
            for message in validation.errors:
                print(f"  - {message}")
            continue

        if validation.warnings:
            print(f"Warnings for run: {run_dir}")
            for message in validation.warnings:
                print(f"  - {message}")

        run_id = config.get("run_id", run_dir.name)
        run_date = config.get("date", run_dir.name)
        arch = config.get("architecture", {}) if isinstance(config.get("architecture"), dict) else {}

        results_obj = results.get("results", {})
        for model_id, model_results in results_obj.items():
            for exec_id, exec_results in model_results.items():
                for point in exec_results.get("scaling", []):
                    data.append(
                        {
                            "Model": model_id,
                            "Executable": exec_id,
                            "Run_ID": run_id,
                            "Run_Date": run_date,
                            "Config_File": config.get("config_file"),
                            "Particles_Per_Thread": config.get("particles_per_thread"),
                            "Config_Max_Threads": config.get("max_threads"),
                            "N_Repeats": config.get("n_repeats"),
                            "Machine": arch.get("machine"),
                            "Processor": arch.get("processor"),
                            "CPU_Count": arch.get("cpu_count"),
                            "OS": arch.get("os"),
                            "Python_Version": arch.get("python_version"),
                            "# Threads": point.get("threads"),
                            "Active rate": point.get("active_rate"),
                            "Inactive rate": point.get("inactive_rate"),
                        }
                    )

                flux = exec_results.get("flux")
                if isinstance(flux, dict):
                    mean_flux = flux.get("mean_flux")
                    if isinstance(mean_flux, list) and mean_flux:
                        energy_axis = build_energy_axis(mean_flux, flux.get("energy_divs"))
                        for idx, flux_val in enumerate(mean_flux):
                            flux_data.append(
                                {
                                    "Model": model_id,
                                    "Executable": exec_id,
                                    "Run_ID": run_id,
                                    "Run_Date": run_date,
                                    "Config_File": config.get("config_file"),
                                    "Particles_Per_Thread": config.get("particles_per_thread"),
                                    "Config_Max_Threads": config.get("max_threads"),
                                    "N_Repeats": config.get("n_repeats"),
                                    "Machine": arch.get("machine"),
                                    "Processor": arch.get("processor"),
                                    "CPU_Count": arch.get("cpu_count"),
                                    "OS": arch.get("os"),
                                    "Python_Version": arch.get("python_version"),
                                    "Energy": energy_axis[idx] if idx < len(energy_axis) else idx + 1,
                                    "Energy_Index": idx,
                                    "Mean_Flux": flux_val,
                                }
                            )

    if not data:
        return pd.DataFrame(), pd.DataFrame()

    combined_df = pd.DataFrame(data)
    combined_df['# Threads'] = pd.to_numeric(combined_df['# Threads'], errors='coerce')
    combined_df['Active rate'] = pd.to_numeric(combined_df['Active rate'], errors='coerce')
    combined_df['Inactive rate'] = pd.to_numeric(combined_df['Inactive rate'], errors='coerce')
    combined_df['Particles_Per_Thread'] = pd.to_numeric(
        combined_df['Particles_Per_Thread'], errors='coerce'
    )
    combined_df['Config_Max_Threads'] = pd.to_numeric(
        combined_df['Config_Max_Threads'], errors='coerce'
    )
    combined_df['N_Repeats'] = pd.to_numeric(combined_df['N_Repeats'], errors='coerce')
    combined_df['CPU_Count'] = pd.to_numeric(combined_df['CPU_Count'], errors='coerce')
    combined_df['Run_Date_Parsed'] = pd.to_datetime(
        combined_df['Run_Date'], errors='coerce', utc=True
    ).dt.tz_convert(None)
    combined_df['Run_Date_Display'] = format_run_date(combined_df['Run_Date'])

    print(f"Column names: {combined_df.columns.tolist()}")
    print(f"Sample data:\n{combined_df.head()}")

    flux_df = pd.DataFrame(flux_data)
    if not flux_df.empty:
        flux_df['Mean_Flux'] = pd.to_numeric(flux_df['Mean_Flux'], errors='coerce')
        flux_df['Energy'] = pd.to_numeric(flux_df['Energy'], errors='coerce')
        flux_df['Particles_Per_Thread'] = pd.to_numeric(
            flux_df['Particles_Per_Thread'], errors='coerce'
        )
        flux_df['Config_Max_Threads'] = pd.to_numeric(
            flux_df['Config_Max_Threads'], errors='coerce'
        )
        flux_df['N_Repeats'] = pd.to_numeric(flux_df['N_Repeats'], errors='coerce')
        flux_df['CPU_Count'] = pd.to_numeric(flux_df['CPU_Count'], errors='coerce')
        flux_df['Run_Date_Parsed'] = pd.to_datetime(
            flux_df['Run_Date'], errors='coerce', utc=True
        ).dt.tz_convert(None)
        flux_df['Run_Date_Display'] = format_run_date(flux_df['Run_Date'])

    return combined_df, flux_df

# Load data
df, flux_df = load_benchmark_data()

def normalize_value(value):
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def build_filter_options(series: pd.Series):
    if series is None or series.empty:
        return []
    values = [normalize_value(v) for v in series.dropna().unique().tolist()]
    try:
        values = sorted(values)
    except TypeError:
        values = sorted(values, key=lambda v: str(v))
    return [{'label': str(v), 'value': v} for v in values]


def build_run_options(dataframe: pd.DataFrame):
    if dataframe.empty:
        return [], []
    runs = (
        dataframe[['Run_ID', 'Run_Date', 'Run_Date_Display', 'Run_Date_Parsed']]
        .drop_duplicates()
        .sort_values(['Run_Date_Parsed', 'Run_ID'])
    )
    options = [
        {'label': f"{row['Run_ID']} ({row['Run_Date_Display']})", 'value': row['Run_ID']}
        for _, row in runs.iterrows()
    ]
    values = runs['Run_ID'].tolist()
    return options, values

def build_date_bounds(dataframe: pd.DataFrame):
    if dataframe.empty or dataframe['Run_Date_Parsed'].isna().all():
        return None, None, None, None
    min_date = dataframe['Run_Date_Parsed'].min().date()
    max_date = dataframe['Run_Date_Parsed'].max().date()
    return min_date, max_date, min_date, max_date

run_options, run_values = build_run_options(df)
config_options = build_filter_options(df.get('Config_File')) if not df.empty else []
machine_options = build_filter_options(df.get('Machine')) if not df.empty else []
os_options = build_filter_options(df.get('OS')) if not df.empty else []
python_options = build_filter_options(df.get('Python_Version')) if not df.empty else []
particles_options = build_filter_options(df.get('Particles_Per_Thread')) if not df.empty else []
max_threads_options = build_filter_options(df.get('Config_Max_Threads')) if not df.empty else []
date_min, date_max, date_start_default, date_end_default = build_date_bounds(df)


@callback(
    Output('run-filter', 'options'),
    Output('run-filter', 'value'),
    Input('run-date-range', 'start_date'),
    Input('run-date-range', 'end_date'),
    Input('data-version', 'data'),
    State('run-filter', 'value'),
)
def update_run_options(start_date, end_date, _data_version, current_runs):
    with DATA_LOCK:
        current_df = df.copy()
    if current_df.empty:
        return [], []

    mask = pd.Series(True, index=current_df.index)
    start_ts, end_ts = parse_date_range(start_date, end_date)

    if start_ts is not None and pd.notna(start_ts):
        mask &= current_df['Run_Date_Parsed'] >= start_ts
    if end_ts is not None and pd.notna(end_ts):
        mask &= current_df['Run_Date_Parsed'] <= end_ts

    runs = (
        current_df.loc[mask, ['Run_ID', 'Run_Date_Display', 'Run_Date_Parsed']]
        .drop_duplicates()
        .sort_values(['Run_Date_Parsed', 'Run_ID'])
    )
    options = [
        {'label': f"{row['Run_ID']} ({row['Run_Date_Display']})", 'value': row['Run_ID']}
        for _, row in runs.iterrows()
    ]
    available = runs['Run_ID'].tolist()

    if current_runs:
        new_value = [run_id for run_id in current_runs if run_id in available]
    else:
        new_value = []

    if not new_value and available:
        new_value = available

    return options, new_value


@callback(
    Output('refresh-status', 'children'),
    Output('data-version', 'data'),
    Input('refresh-button', 'n_clicks'),
    Input('refresh-poll', 'n_intervals'),
    State('data-version', 'data'),
)
def handle_refresh(n_clicks, _n_intervals, current_version):
    trigger = ctx.triggered_id
    if trigger == 'refresh-button':
        started = refresh_data_from_remote()
        if started:
            return "Refreshing data...", current_version
        return "Refresh already in progress", current_version

    message = DOWNLOAD_STATE.get("message") or ""
    status = DOWNLOAD_STATE.get("status")
    version = DOWNLOAD_STATE.get("version", current_version)

    if version != current_version:
        return message or "Data updated", version

    if status == "downloading":
        return message or "Refreshing data...", current_version
    return message or "Idle", current_version


@callback(
    Output('model-filter', 'options'),
    Output('model-filter', 'value'),
    Output('executable-filter', 'options'),
    Output('executable-filter', 'value'),
    Output('config-filter', 'options'),
    Output('config-filter', 'value'),
    Output('particles-filter', 'options'),
    Output('particles-filter', 'value'),
    Output('maxthreads-filter', 'options'),
    Output('maxthreads-filter', 'value'),
    Output('machine-filter', 'options'),
    Output('machine-filter', 'value'),
    Output('os-filter', 'options'),
    Output('os-filter', 'value'),
    Output('python-filter', 'options'),
    Output('python-filter', 'value'),
    Input('data-version', 'data'),
    State('model-filter', 'value'),
    State('executable-filter', 'value'),
    State('config-filter', 'value'),
    State('particles-filter', 'value'),
    State('maxthreads-filter', 'value'),
    State('machine-filter', 'value'),
    State('os-filter', 'value'),
    State('python-filter', 'value'),
)
def update_filter_options(
    _data_version,
    current_model,
    current_executables,
    current_configs,
    current_particles,
    current_maxthreads,
    current_machines,
    current_os,
    current_python,
):
    with DATA_LOCK:
        current_df = df.copy()

    if current_df.empty:
        return [], None, [], [], [], [], [], [], [], [], [], [], [], [], [], []

    model_options = build_filter_options(current_df.get('Model'))
    executable_options = build_filter_options(current_df.get('Executable'))
    config_opts = build_filter_options(current_df.get('Config_File'))
    particles_opts = build_filter_options(current_df.get('Particles_Per_Thread'))
    maxthreads_opts = build_filter_options(current_df.get('Config_Max_Threads'))
    machine_opts = build_filter_options(current_df.get('Machine'))
    os_opts = build_filter_options(current_df.get('OS'))
    python_opts = build_filter_options(current_df.get('Python_Version'))

    model_values = [opt['value'] for opt in model_options]
    executable_values = [opt['value'] for opt in executable_options]
    config_values = [opt['value'] for opt in config_opts]
    particles_values = [opt['value'] for opt in particles_opts]
    maxthreads_values = [opt['value'] for opt in maxthreads_opts]
    machine_values = [opt['value'] for opt in machine_opts]
    os_values = [opt['value'] for opt in os_opts]
    python_values = [opt['value'] for opt in python_opts]

    if current_model in model_values:
        new_model = current_model
    else:
        new_model = model_values[0] if model_values else None

    def intersect_or_all(current, available):
        if not available:
            return []
        if current:
            filtered = [val for val in current if val in available]
            if filtered:
                return filtered
        return available

    new_executables = intersect_or_all(current_executables, executable_values)
    new_configs = intersect_or_all(current_configs, config_values)
    new_particles = intersect_or_all(current_particles, particles_values)
    new_maxthreads = intersect_or_all(current_maxthreads, maxthreads_values)
    new_machines = intersect_or_all(current_machines, machine_values)
    new_os = intersect_or_all(current_os, os_values)
    new_python = intersect_or_all(current_python, python_values)

    return (
        model_options,
        new_model,
        executable_options,
        new_executables,
        config_opts,
        new_configs,
        particles_opts,
        new_particles,
        maxthreads_opts,
        new_maxthreads,
        machine_opts,
        new_machines,
        os_opts,
        new_os,
        python_opts,
        new_python,
    )


@callback(
    Output('run-date-range', 'min_date_allowed'),
    Output('run-date-range', 'max_date_allowed'),
    Output('run-date-range', 'start_date'),
    Output('run-date-range', 'end_date'),
    Input('data-version', 'data'),
    State('run-date-range', 'start_date'),
    State('run-date-range', 'end_date'),
)
def update_date_bounds(_data_version, current_start, current_end):
    with DATA_LOCK:
        current_df = df.copy()

    if current_df.empty or current_df['Run_Date_Parsed'].isna().all():
        return None, None, None, None

    min_date = current_df['Run_Date_Parsed'].min().date()
    max_date = current_df['Run_Date_Parsed'].max().date()

    start = pd.to_datetime(current_start, errors='coerce') if current_start else None
    end = pd.to_datetime(current_end, errors='coerce') if current_end else None

    if start is None or pd.isna(start) or start.date() < min_date:
        start = min_date
    else:
        start = start.date()

    if end is None or pd.isna(end) or end.date() > max_date:
        end = max_date
    else:
        end = end.date()

    return min_date, max_date, start, end

# App layout
app.layout = html.Div([
    html.Div([
        html.H1("XDG Benchmarking Dashboard",
                style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 30}),
        html.P("Accelerated Discretized Geometry Performance Analysis",
               style={'textAlign': 'center', 'color': '#7f8c8d', 'fontSize': 18, 'marginBottom': 40})
    ]),

    # Dataset and filter sections
    html.Div([
        html.Div([
            html.H3("Datasets", style={'color': '#2c3e50', 'marginBottom': 10}),
            html.P(
                "Choose the datasets you want to compare. Filters below narrow by dataset properties.",
                style={'color': '#7f8c8d', 'marginBottom': 15}
            ),
            html.Div([
                html.Button(
                    "Refresh Data",
                    id="refresh-button",
                    n_clicks=0,
                    style={
                        'backgroundColor': '#2c3e50',
                        'color': 'white',
                        'border': 'none',
                        'padding': '6px 12px',
                        'borderRadius': 6,
                        'cursor': 'pointer'
                    }
                ),
                html.Span(id='refresh-status', style={'color': '#7f8c8d'})
            ], style={'display': 'flex', 'gap': 10, 'alignItems': 'center', 'marginBottom': 12}),
            html.Div([
                html.Label("Date Range:", style={'fontWeight': 'bold'}),
                dcc.DatePickerRange(
                    id='run-date-range',
                    min_date_allowed=date_min,
                    max_date_allowed=date_max,
                    start_date=date_start_default,
                    end_date=date_end_default,
                    display_format='MMM D, YYYY',
                    style={'width': '100%'}
                )
            ], style={'marginBottom': 12}),
            html.Label("Dataset / Run:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='run-filter',
                options=run_options,
                value=run_values if run_values else [],
                multi=True,
                style={'width': '100%'}
            ),
        ], style={'backgroundColor': '#f8f9fa', 'padding': 20, 'borderRadius': 10, 'flex': '1 1 320px', 'minWidth': 360}),

        html.Div([
            html.H3("Dataset Filters", style={'color': '#2c3e50', 'marginBottom': 10}),
            html.Div([
                html.Div([
                    html.Label("Config File:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='config-filter',
                        options=config_options,
                        value=config_options and [opt['value'] for opt in config_options],
                        multi=True,
                        style={'width': '100%'}
                    )
                ], style={'marginBottom': 12}),

                html.Div([
                    html.Label("Particles / Thread:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='particles-filter',
                        options=particles_options,
                        value=particles_options and [opt['value'] for opt in particles_options],
                        multi=True,
                        style={'width': '100%'}
                    )
                ], style={'marginBottom': 12}),

                html.Div([
                    html.Label("Max Threads (Config):", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='maxthreads-filter',
                        options=max_threads_options,
                        value=max_threads_options and [opt['value'] for opt in max_threads_options],
                        multi=True,
                        style={'width': '100%'}
                    )
                ], style={'marginBottom': 12}),

                html.Div([
                    html.Label("Machine:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='machine-filter',
                        options=machine_options,
                        value=machine_options and [opt['value'] for opt in machine_options],
                        multi=True,
                        style={'width': '100%'}
                    )
                ], style={'marginBottom': 12}),

                html.Div([
                    html.Label("OS:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='os-filter',
                        options=os_options,
                        value=os_options and [opt['value'] for opt in os_options],
                        multi=True,
                        style={'width': '100%'}
                    )
                ], style={'marginBottom': 12}),

                html.Div([
                    html.Label("Python Version:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='python-filter',
                        options=python_options,
                        value=python_options and [opt['value'] for opt in python_options],
                        multi=True,
                        style={'width': '100%'}
                    )
                ])
            ])
        ], style={'backgroundColor': '#f8f9fa', 'padding': 20, 'borderRadius': 10, 'flex': '1 1 320px'}),

        html.Div([
            html.H3("Result Filters", style={'color': '#2c3e50', 'marginBottom': 10}),
            html.Div([
                html.Label("Model:", style={'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='model-filter',
                    options=[{'label': model, 'value': model} for model in sorted(df['Model'].unique())] if not df.empty else [],
                    value=sorted(df['Model'].unique())[0] if not df.empty else None,
                    style={'width': '100%'}
                )
            ], style={'marginBottom': 12}),

            html.Div([
                html.Label("Executable:", style={'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='executable-filter',
                    options=[{'label': exe, 'value': exe} for exe in sorted(df['Executable'].unique())] if not df.empty else [],
                    value=sorted(df['Executable'].unique()) if not df.empty else [],
                    multi=True,
                    style={'width': '100%'}
                )
            ], style={'marginBottom': 12}),

            html.Div([
                html.Label("Metric:", style={'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='metric-filter',
                    options=[
                        {'label': 'Active Rate (particles/sec)', 'value': 'Active rate'},
                        {'label': 'Inactive Rate (particles/sec)', 'value': 'Inactive rate'}
                    ],
                    value='Active rate',
                    style={'width': '100%'}
                )
            ])
        ], style={'backgroundColor': '#f8f9fa', 'padding': 20, 'borderRadius': 10, 'flex': '1 1 260px'})
    ], style={'display': 'flex', 'gap': 20, 'flexWrap': 'wrap', 'marginBottom': 30}),

    dcc.Interval(id='refresh-poll', interval=2000, n_intervals=0),
    dcc.Store(id='data-version', data=0),

    # Main charts section
    html.Div([
        html.Div([
            html.H3("Performance Scaling by Dataset", style={'color': '#2c3e50', 'marginBottom': 15}),
            dcc.Graph(id='scaling-chart', style={'height': 500})
        ], style={'width': '50%', 'display': 'inline-block', 'verticalAlign': 'top'}),

        html.Div([
            html.H3("Speedup by Dataset", style={'color': '#2c3e50', 'marginBottom': 15}),
            dcc.Graph(id='speedup-chart', style={'height': 500})
        ], style={'width': '50%', 'display': 'inline-block', 'verticalAlign': 'top'})
    ], style={'marginBottom': 30}),

    # Comparison section
    html.Div([
        html.H3("Max Performance Over Time", style={'color': '#2c3e50', 'marginBottom': 15}),
        dcc.Graph(id='comparison-chart', style={'height': 400})
    ], style={'marginBottom': 30}),

    # Flux section
    html.Div([
        html.H3("Flux Spectrum", style={'color': '#2c3e50', 'marginBottom': 15}),
        dcc.Graph(id='flux-chart', style={'height': 400})
    ], style={'marginBottom': 30}),

    # Summary statistics
    html.Div([
        html.H3("Summary Statistics", style={'color': '#2c3e50', 'marginBottom': 15}),
        html.Div(id='summary-stats', style={'backgroundColor': '#ecf0f1', 'padding': 20, 'borderRadius': 10})
    ], style={'marginBottom': 30}),

    # Data table
    html.Div([
        html.H3("Raw Data", style={'color': '#2c3e50', 'marginBottom': 15}),
        html.Div(id='data-table')
    ])
], style={'padding': 20, 'fontFamily': 'Arial, sans-serif'})

# Callback for filtering data
@callback(
    Output('scaling-chart', 'figure'),
    Output('speedup-chart', 'figure'),
    Output('comparison-chart', 'figure'),
    Output('flux-chart', 'figure'),
    Output('summary-stats', 'children'),
    Output('data-table', 'children'),
    Input('model-filter', 'value'),
    Input('executable-filter', 'value'),
    Input('run-filter', 'value'),
    Input('run-date-range', 'start_date'),
    Input('run-date-range', 'end_date'),
    Input('config-filter', 'value'),
    Input('particles-filter', 'value'),
    Input('maxthreads-filter', 'value'),
    Input('machine-filter', 'value'),
    Input('os-filter', 'value'),
    Input('python-filter', 'value'),
    Input('metric-filter', 'value'),
    Input('data-version', 'data')
)
def update_charts(
    model,
    executables,
    runs,
    start_date,
    end_date,
    config_files,
    particles_per_thread,
    max_threads_config,
    machines,
    os_values,
    python_versions,
    metric,
    _data_version,
):
    with DATA_LOCK:
        current_df = df.copy()
        current_flux_df = flux_df.copy()

    if current_df.empty:
        return {}, {}, {}, {}, "No data available", "No data available"

    # Filter data
    filtered_df = current_df.copy()
    if model:
        filtered_df = filtered_df[filtered_df['Model'] == model]
    if executables:
        filtered_df = filtered_df[filtered_df['Executable'].isin(executables)]
    if runs:
        filtered_df = filtered_df[filtered_df['Run_ID'].isin(runs)]
    if start_date:
        start_ts, _ = parse_date_range(start_date, None)
        if pd.notna(start_ts):
            filtered_df = filtered_df[filtered_df['Run_Date_Parsed'] >= start_ts]
    if end_date:
        _, end_ts = parse_date_range(None, end_date)
        if pd.notna(end_ts):
            filtered_df = filtered_df[filtered_df['Run_Date_Parsed'] <= end_ts]
    if config_files:
        filtered_df = filtered_df[filtered_df['Config_File'].isin(config_files)]
    if particles_per_thread:
        filtered_df = filtered_df[filtered_df['Particles_Per_Thread'].isin(particles_per_thread)]
    if max_threads_config:
        filtered_df = filtered_df[filtered_df['Config_Max_Threads'].isin(max_threads_config)]
    if machines:
        filtered_df = filtered_df[filtered_df['Machine'].isin(machines)]
    if os_values:
        filtered_df = filtered_df[filtered_df['OS'].isin(os_values)]
    if python_versions:
        filtered_df = filtered_df[filtered_df['Python_Version'].isin(python_versions)]

    if filtered_df.empty:
        return {}, {}, {}, {}, "No data available for selected filters", "No data available"

    filtered_df = filtered_df.sort_values(['Run_Date_Parsed', 'Run_ID', '# Threads'])
    run_order = filtered_df['Run_ID'].drop_duplicates().tolist()
    dash_by = 'Executable' if filtered_df['Executable'].nunique() > 1 else None

    # Scaling chart (dataset-oriented)
    scaling_kwargs = dict(
        data_frame=filtered_df,
        x='# Threads',
        y=metric,
        color='Run_ID',
        title=f'{metric} vs Thread Count',
        labels={'# Threads': 'Number of Threads', metric: f'{metric} (particles/sec)'},
        hover_data={'Executable': True, 'Run_Date_Display': True, 'Run_ID': True},
        category_orders={'Run_ID': run_order},
        markers=True,
    )
    if dash_by:
        scaling_kwargs['line_dash'] = dash_by
    scaling_fig = px.line(**scaling_kwargs)
    scaling_fig.update_layout(
        xaxis_title="Number of Threads",
        yaxis_title=f"{metric} (particles/sec)",
        hovermode='x unified'
    )

    # Speedup chart (dataset-oriented)
    speedup_df = filtered_df.copy()
    baseline = (
        speedup_df[speedup_df['# Threads'] == 1]
        .groupby(['Run_ID', 'Executable', 'Model'])[metric]
        .first()
        .reset_index()
        .rename(columns={metric: 'Baseline'})
    )
    speedup_df = speedup_df.merge(
        baseline, on=['Run_ID', 'Executable', 'Model'], how='left'
    )
    speedup_df = speedup_df[pd.notna(speedup_df['Baseline']) & (speedup_df['Baseline'] > 0)]
    speedup_df['Speedup'] = speedup_df[metric] / speedup_df['Baseline']

    speedup_kwargs = dict(
        data_frame=speedup_df,
        x='# Threads',
        y='Speedup',
        color='Run_ID',
        title='Speedup vs Thread Count',
        labels={'# Threads': 'Number of Threads', 'Speedup': 'Speedup'},
        hover_data={'Executable': True, 'Run_Date_Display': True, 'Run_ID': True},
        category_orders={'Run_ID': run_order},
        markers=True,
    )
    if dash_by:
        speedup_kwargs['line_dash'] = dash_by
    if speedup_df.empty:
        speedup_fig = go.Figure()
        speedup_fig.update_layout(
            title='Speedup vs Thread Count',
            xaxis_title='Number of Threads',
            yaxis_title='Speedup'
        )
    else:
        speedup_fig = px.line(**speedup_kwargs)

        max_threads = speedup_df['# Threads'].max()
        if pd.notna(max_threads):
            speedup_fig.add_trace(go.Scatter(
                x=[1, max_threads],
                y=[1, max_threads],
                mode='lines',
                name='Ideal Speedup',
                line=dict(dash='dash', color='gray'),
                hovertemplate='Threads: %{x}<br>Ideal Speedup: %{y}<extra></extra>'
            ))

        speedup_fig.update_layout(
            xaxis_title='Number of Threads',
            yaxis_title='Speedup',
            hovermode='x unified'
        )

    # Max performance over time
    max_performance = (
        filtered_df.groupby(
            ['Run_ID', 'Run_Date', 'Run_Date_Display', 'Run_Date_Parsed', 'Executable', 'Model']
        )[metric]
        .max()
        .reset_index()
        .sort_values(['Run_Date_Parsed', 'Run_ID'])
    )

    if max_performance.empty:
        comparison_fig = go.Figure()
        comparison_fig.update_layout(
            title=f'Maximum {metric} Over Time',
            xaxis_title="Run Date",
            yaxis_title=f"{metric} (particles/sec)"
        )
    else:
        comparison_fig = px.line(
            max_performance,
            x='Run_Date_Parsed',
            y=metric,
            color='Executable',
            markers=True,
            title=f'Maximum {metric} Over Time',
            labels={'Run_Date_Parsed': 'Run Date', metric: f'{metric} (particles/sec)'},
            hover_data={'Run_ID': True, 'Run_Date_Display': True, 'Executable': True, 'Run_Date_Parsed': False}
        )
        comparison_fig.update_layout(
            xaxis_title="Run Date",
            yaxis_title=f"{metric} (particles/sec)",
            hovermode='x unified'
        )
        comparison_fig.update_xaxes(tickformat='%b %d, %Y %I:%M %p')

    # Flux chart
    flux_filtered = current_flux_df.copy()
    if model:
        flux_filtered = flux_filtered[flux_filtered['Model'] == model]
    if executables:
        flux_filtered = flux_filtered[flux_filtered['Executable'].isin(executables)]
    if runs:
        flux_filtered = flux_filtered[flux_filtered['Run_ID'].isin(runs)]
    if start_date:
        start_ts, _ = parse_date_range(start_date, None)
        if pd.notna(start_ts):
            flux_filtered = flux_filtered[flux_filtered['Run_Date_Parsed'] >= start_ts]
    if end_date:
        _, end_ts = parse_date_range(None, end_date)
        if pd.notna(end_ts):
            flux_filtered = flux_filtered[flux_filtered['Run_Date_Parsed'] <= end_ts]
    if config_files:
        flux_filtered = flux_filtered[flux_filtered['Config_File'].isin(config_files)]
    if particles_per_thread:
        flux_filtered = flux_filtered[flux_filtered['Particles_Per_Thread'].isin(particles_per_thread)]
    if max_threads_config:
        flux_filtered = flux_filtered[flux_filtered['Config_Max_Threads'].isin(max_threads_config)]
    if machines:
        flux_filtered = flux_filtered[flux_filtered['Machine'].isin(machines)]
    if os_values:
        flux_filtered = flux_filtered[flux_filtered['OS'].isin(os_values)]
    if python_versions:
        flux_filtered = flux_filtered[flux_filtered['Python_Version'].isin(python_versions)]

    if flux_filtered.empty:
        flux_fig = go.Figure()
        flux_fig.update_layout(
            title='Flux Spectrum',
            xaxis_title='Energy (eV)',
            yaxis_title='Mean Flux'
        )
    else:
        flux_filtered = flux_filtered.sort_values(['Run_Date_Parsed', 'Run_ID', 'Energy'])
        flux_run_order = flux_filtered['Run_ID'].drop_duplicates().tolist()
        flux_dash_by = 'Executable' if flux_filtered['Executable'].nunique() > 1 else None
        flux_facet = 'Model' if flux_filtered['Model'].nunique() > 1 else None

        flux_kwargs = dict(
            data_frame=flux_filtered,
            x='Energy',
            y='Mean_Flux',
            color='Run_ID',
            title='Flux Spectrum',
            labels={'Energy': 'Energy (eV)', 'Mean_Flux': 'Mean Flux'},
            hover_data={'Executable': True, 'Run_Date_Display': True, 'Run_ID': True},
            category_orders={'Run_ID': flux_run_order},
            markers=True,
        )
        if flux_dash_by:
            flux_kwargs['line_dash'] = flux_dash_by
        if flux_facet:
            flux_kwargs['facet_row'] = flux_facet

        flux_fig = px.line(**flux_kwargs)
        min_energy = flux_filtered['Energy'].min()
        if pd.notna(min_energy) and min_energy > 0:
            flux_fig.update_xaxes(type='log')

        flux_fig.update_layout(
            xaxis_title='Energy (eV)',
            yaxis_title='Mean Flux',
            hovermode='x unified'
        )

    # Summary statistics
    summary_stats = []

    # Overall statistics
    summary_stats.append(html.H4("Overall Statistics"))
    summary_stats.append(html.P(f"Total data points: {len(filtered_df)}"))
    summary_stats.append(html.P(f"Models: {', '.join(filtered_df['Model'].unique())}"))
    summary_stats.append(html.P(f"Executables: {', '.join(filtered_df['Executable'].unique())}"))
    summary_stats.append(html.P(f"Datasets: {filtered_df['Run_ID'].nunique()}"))
    if filtered_df['Run_Date_Parsed'].notna().any():
        min_date = filtered_df['Run_Date_Parsed'].min().strftime('%Y-%m-%d')
        max_date = filtered_df['Run_Date_Parsed'].max().strftime('%Y-%m-%d')
        summary_stats.append(html.P(f"Date Range: {min_date} to {max_date}"))

    # Performance statistics
    summary_stats.append(html.H4("Performance Statistics"))
    max_rate = filtered_df[metric].max()
    min_rate = filtered_df[metric].min()
    mean_rate = filtered_df[metric].mean()

    summary_stats.append(html.P(f"Maximum {metric}: {max_rate:.2e} particles/sec"))
    summary_stats.append(html.P(f"Minimum {metric}: {min_rate:.2e} particles/sec"))
    summary_stats.append(html.P(f"Mean {metric}: {mean_rate:.2e} particles/sec"))

    # Best performing configuration
    best_config = filtered_df.loc[filtered_df[metric].idxmax()]
    summary_stats.append(html.H4("Best Performance"))
    summary_stats.append(html.P(f"Model: {best_config['Model']}"))
    summary_stats.append(html.P(f"Executable: {best_config['Executable']}"))
    summary_stats.append(html.P(f"Threads: {best_config['# Threads']}"))
    summary_stats.append(html.P(f"Rate: {best_config[metric]:.2e} particles/sec"))

    # Data table
    table_columns_order = [
        'Run_ID', 'Run_Date_Display', 'Model', 'Executable', '# Threads', 'Active rate', 'Inactive rate'
    ]
    table_df = filtered_df[table_columns_order].copy()
    table_df = table_df.rename(columns={'Run_Date_Display': 'Run_Date'})
    table_data = table_df.round(2).to_dict('records')
    table_columns = [{"name": col, "id": col} for col in table_df.columns]

    data_table = dash.dash_table.DataTable(
        data=table_data,
        columns=table_columns,
        page_size=10,
        style_table={'overflowX': 'auto'},
        style_cell={'textAlign': 'left', 'padding': '10px'},
        style_header={'backgroundColor': '#2c3e50', 'color': 'white', 'fontWeight': 'bold'},
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': '#f8f9fa'}
        ]
    )

    return scaling_fig, speedup_fig, comparison_fig, flux_fig, summary_stats, data_table

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)
