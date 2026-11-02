import dash
from dash import dcc, html, Input, Output, State, ALL, callback, ctx
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import json
import os
import threading
from pathlib import Path

from schema_validator import discover_run_dirs_recursive, load_and_validate_run
from results_store import ResultsStore
from run_selection import PROPERTY_FILTERS, build_run_records, find_runs, select_runs
from comparison_url import parse_comparison_query, build_comparison_query

# Data refresh configuration
BASE_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG_PATH = BASE_DIR / "local_config.json"
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", BASE_DIR / "results")).resolve()
RESULTS_STORE = ResultsStore(RESULTS_DIR)
DATA_LOCK = threading.Lock()
LOCAL_DATA_VERSION = 0

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
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Invalid JSON in {LOCAL_CONFIG_PATH}: {exc}"
    if not isinstance(config, dict):
        return None, f"Expected a JSON object in {LOCAL_CONFIG_PATH}"
    url = config.get("results_zip_url") or config.get("results_url")
    if not url:
        return None, f"Missing results_zip_url in {LOCAL_CONFIG_PATH}"
    return url, None


def refresh_data_from_remote():
    def get_url():
        url, error = load_results_url()
        if error:
            raise ValueError(error)
        return url

    def validate(path):
        new_df, _ = load_benchmark_data(path)
        if new_df.empty:
            raise ValueError("Archive contains no usable benchmark data")

    return RESULTS_STORE.start(get_url, validate)


def load_benchmark_data(results_dir=None):
    """Load all benchmark data from the results directory (schema-based)."""
    data = []
    flux_data = []
    results_dir = Path(results_dir) if results_dir is not None else RESULTS_DIR
    if (results_dir / "runs").is_dir():
        results_dir = results_dir / "runs"

    if not results_dir.exists():
        return pd.DataFrame(), pd.DataFrame()

    run_dirs = [path for path in discover_run_dirs_recursive(results_dir)
                if ".remote" not in path.relative_to(results_dir).parts]
    if not run_dirs:
        return pd.DataFrame(), pd.DataFrame()

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
with RESULTS_STORE.dataset() as (dataset_path, LOCAL_DATA_VERSION):
    df, flux_df = load_benchmark_data(dataset_path)

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

def ensure_data_loaded(requested_version):
    global df, flux_df, LOCAL_DATA_VERSION
    # The browser may still carry an old version, and the request can land on
    # any worker. Always compare with the version published on disk.
    version = RESULTS_STORE.state()["version"]
    if version == LOCAL_DATA_VERSION:
        return
    with DATA_LOCK:
        with RESULTS_STORE.dataset() as (path, version):
            if version == LOCAL_DATA_VERSION:
                return
            new_df, new_flux_df = load_benchmark_data(path)
        df, flux_df = new_df, new_flux_df
        LOCAL_DATA_VERSION = version


def build_date_bounds(dataframe: pd.DataFrame):
    if dataframe.empty or dataframe['Run_Date_Parsed'].isna().all():
        return None, None, None, None
    min_date = dataframe['Run_Date_Parsed'].min().date()
    max_date = dataframe['Run_Date_Parsed'].max().date()
    return min_date, max_date, min_date, max_date

run_records = build_run_records(df)
initial_runs = [run_records[0]["id"]] if run_records else []
config_options = build_filter_options(df.get('Config_File')) if not df.empty else []
machine_options = build_filter_options(df.get('Machine')) if not df.empty else []
os_options = build_filter_options(df.get('OS')) if not df.empty else []
python_options = build_filter_options(df.get('Python_Version')) if not df.empty else []
particles_options = build_filter_options(df.get('Particles_Per_Thread')) if not df.empty else []
max_threads_options = build_filter_options(df.get('Config_Max_Threads')) if not df.empty else []
date_min, date_max, date_start_default, date_end_default = build_date_bounds(df)


def selected_run_chips(records, selected):
    by_id = {row["id"]: row for row in records}
    chips = []
    for run_id in selected:
        row = by_id.get(run_id)
        label = (f"{row['Date']} · {row['Config_File'] or 'Unknown configuration'}"
                 if row else f"{run_id} · unavailable")
        chips.append(html.Button(
            [html.Span(label), html.Span("×", className="chip-remove", **{"aria-hidden": "true"})],
            id={"type": "remove-run", "run": run_id}, n_clicks=0,
            className="run-chip" if row else "run-chip unavailable-run-chip",
            title=f"Remove run {run_id}",
            **{"aria-label": f"Remove run {run_id} from comparison"},
        ))
    return chips


@callback(
    Output("run-table", "data"),
    Output("run-table", "selected_row_ids"),
    Output("run-table", "selected_rows"),
    Output("selected-runs", "data"),
    Output("selected-run-chips", "children"),
    Output("selection-count", "children"),
    Output("matching-count", "children"),
    Output("run-browser-empty", "children"),
    Output("run-table", "page_current"),
    Output("comparison-url", "search"),
    Output("model-filter", "value"),
    Output("executable-filter", "value"),
    Output("metric-filter", "value"),
    Output("comparison-notices", "children"),
    Output("comparison-url-state", "data"),
    Output("model-filter", "options"),
    Output("executable-filter", "options"),
    Input("run-search", "value"),
    Input("run-date-range", "start_date"),
    Input("run-date-range", "end_date"),
    *[Input(component_id, "value") for component_id, _, _ in PROPERTY_FILTERS],
    Input("data-version", "data"),
    Input("run-table", "selected_row_ids"),
    Input("select-matching", "n_clicks"),
    Input("clear-selection", "n_clicks"),
    Input({"type": "remove-run", "run": ALL}, "n_clicks"),
    Input("comparison-url", "search"),
    Input("model-filter", "value"),
    Input("executable-filter", "value"),
    Input("metric-filter", "value"),
    State("selected-runs", "data"),
    State("run-table", "data"),
    State("comparison-url-state", "data"),
)
def update_run_browser(search, start_date, end_date, *args):
    properties = args[:len(PROPERTY_FILTERS)]
    (version, checked, _select_clicks, _clear_clicks, remove_clicks, url_search,
     model, executables, metric, selected, previous_rows, url_state) = args[len(PROPERTY_FILTERS):]
    trigger = ctx.triggered_id
    # Wait for Location to supply the real query before publishing defaults.
    if url_search is None or (isinstance(trigger, dict) and not any(remove_clicks)):
        return (dash.no_update,) * 17
    ensure_data_loaded(version)
    with DATA_LOCK:
        current_df = df.copy()
    records = build_run_records(current_df)
    model_options = build_filter_options(current_df.get("Model"))
    executable_options = build_filter_options(current_df.get("Executable"))
    default_model = model_options[0]["value"] if model_options else None
    default_executables = [option["value"] for option in executable_options]
    url_state = dict(url_state or {})
    initialized = url_state.get("initialized", False)
    restoring = not initialized or (
        "comparison-url.search" in ctx.triggered_prop_ids and url_search != url_state.get("search")
    )
    if restoring:
        settings, notices = parse_comparison_query(url_search)
        selected = settings["runs"] if settings["runs"] is not None else ([records[0]["id"]] if records else [])
        model = settings["model"] if settings["model"] is not None else default_model
        executables = settings["executables"] if settings["executables"] is not None else default_executables
        metric = settings["metric"] or "Active rate"
        url_state = {
            "notices": notices,
            "pending_default_runs": settings["runs"] is None and not records,
            "pending_default_executables": settings["executables"] is None and not default_executables,
        }
    else:
        if url_state.get("pending_default_runs") and records:
            selected = [records[0]["id"]]
            url_state["pending_default_runs"] = False
        if url_state.get("pending_default_executables") and default_executables:
            executables = default_executables
            url_state["pending_default_executables"] = False
        if model is None:
            model = default_model

    matches = find_runs(records, search, start_date, end_date, properties)
    action = "remove-run" if isinstance(trigger, dict) else trigger
    if not restoring:
        selected = select_runs(action, selected, checked, previous_rows, matches, records,
                               trigger.get("run") if isinstance(trigger, dict) else None,
                               retain_missing=True)
        if trigger in ("run-table", "select-matching", "clear-selection") or isinstance(trigger, dict):
            url_state["pending_default_runs"] = False
        if trigger == "executable-filter":
            url_state["pending_default_executables"] = False

    selected = selected or []
    executables = executables or []
    available_ids = {row["id"] for row in records}
    missing = [run_id for run_id in selected if run_id not in available_ids]
    visible_selected = [row["id"] for row in matches if row["id"] in selected]
    indices = [index for index, row in enumerate(matches) if row["id"] in selected]
    hidden_count = len(selected) - len(missing) - len(visible_selected)
    count = f"{len(selected)} run{'s' if len(selected) != 1 else ''} selected"
    if missing:
        count += f" · {len(missing)} unavailable"
    if hidden_count:
        count += f" · {hidden_count} outside current search"

    notices = list(url_state.get("notices", []))
    if missing:
        notices.append("Unavailable run tags: " + ", ".join(missing) + ". " +
                       ("Available runs are shown. " if len(missing) < len(selected) else "None of the selected runs are available. ") +
                       "Refresh data to try again, or remove the unavailable runs.")
    model_values = {option["value"] for option in model_options}
    if model and model not in model_values:
        notices.append(f"Model '{model}' is unavailable in the current data. Choose another model or refresh data.")
        model_options.append({"label": f"{model} (unavailable)", "value": model})
    else:
        for option in model_options:
            option["label"] = option["label"].upper()
    executable_values = {option["value"] for option in executable_options}
    for executable in executables:
        if executable not in executable_values:
            notices.append(f"Executable '{executable}' is unavailable in the current data.")
            executable_options.append({"label": f"{executable} (unavailable)", "value": executable})

    canonical_query = build_comparison_query(selected, model, executables, metric, url_search)
    # Returning to the bare homepage with Back restores its defaults without
    # immediately creating a new history entry that traps the Back button.
    leave_bare_home = restoring and initialized and not url_search
    next_search = url_search if leave_bare_home else canonical_query
    url_state.update(initialized=True, search=next_search)
    empty = "No runs match. Try a different search or reset the filters." if not matches else ""
    return (matches, visible_selected, indices, selected, selected_run_chips(records, selected), count,
            f"{len(matches)} of {len(records)} runs", empty,
            dash.no_update if trigger == "run-table" or isinstance(trigger, dict) else 0,
            next_search if next_search != url_search else dash.no_update,
            model, executables, metric, [html.P(notice) for notice in notices], url_state,
            model_options, executable_options)


@callback(
    Output("run-search", "value"),
    Output("run-date-range", "start_date", allow_duplicate=True),
    Output("run-date-range", "end_date", allow_duplicate=True),
    *[Output(component_id, "value", allow_duplicate=True) for component_id, _, _ in PROPERTY_FILTERS],
    Input("reset-run-filters", "n_clicks"),
    State("data-version", "data"),
    prevent_initial_call=True,
)
def reset_run_filters(_clicks, version):
    ensure_data_loaded(version)
    with DATA_LOCK:
        _, _, start, end = build_date_bounds(df)
    return ("", start, end, *[[] for _ in PROPERTY_FILTERS])


@callback(
    Output('refresh-status', 'children'),
    Output('data-version', 'data'),
    Input('refresh-button', 'n_clicks'),
    Input('refresh-poll', 'n_intervals'),
    State('data-version', 'data'),
)
def handle_refresh(n_clicks, _n_intervals, current_version):
    state = RESULTS_STORE.state()
    # Start on the first visit, after Gunicorn has forked its workers. Starting
    # threads at import time would leave preloaded workers without a downloader.
    initial_fetch = state["version"] == 0 and not state["message"]
    if ctx.triggered_id == 'refresh-button' or initial_fetch:
        url, error = load_results_url()
        if error:
            version = state["version"] if state["version"] != current_version else dash.no_update
            message = "Using local results · remote refresh is not configured."
            if ctx.triggered_id == "refresh-button":
                message = "Remote refresh is not configured. Set XDG_RESULTS_ZIP_URL to enable it."
            return message, version
        started = refresh_data_from_remote()
        state = RESULTS_STORE.state()
        if started:
            version = state["version"] if state["version"] != current_version else dash.no_update
            return "Refreshing data...", version
    version = state["version"] if state["version"] != current_version else dash.no_update
    return state["message"] or "Ready to refresh", version


@callback(
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
    State('executable-filter', 'options'),
    State('config-filter', 'options'),
    State('particles-filter', 'options'),
    State('maxthreads-filter', 'options'),
    State('machine-filter', 'options'),
    State('os-filter', 'options'),
    State('python-filter', 'options'),
)
def refresh_property_options(*args):
    return update_filter_options(*args)[4:]


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
    *previous_options,
):
    ensure_data_loaded(_data_version)
    with DATA_LOCK:
        current_df = df.copy()

    if current_df.empty:
        return [], None, [], [], [], [], [], [], [], [], [], [], [], [], [], []

    model_options = build_filter_options(current_df.get('Model'))
    for option in model_options:
        option['label'] = option['label'].upper()
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

    def intersect_or_all(current, available, previous, expand_all=False):
        if not available or not current:
            return []
        if expand_all and set(current or []) == {option['value'] for option in (previous or [])}:
            return available
        if current:
            filtered = [val for val in current if val in available]
            if filtered:
                return filtered
        return []

    new_executables = intersect_or_all(current_executables, executable_values, previous_options[0], expand_all=True) or executable_values
    new_configs = intersect_or_all(current_configs, config_values, previous_options[1])
    new_particles = intersect_or_all(current_particles, particles_values, previous_options[2])
    new_maxthreads = intersect_or_all(current_maxthreads, maxthreads_values, previous_options[3])
    new_machines = intersect_or_all(current_machines, machine_values, previous_options[4])
    new_os = intersect_or_all(current_os, os_values, previous_options[5])
    new_python = intersect_or_all(current_python, python_values, previous_options[6])

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
    State('run-date-range', 'min_date_allowed'),
    State('run-date-range', 'max_date_allowed'),
)
def update_date_bounds(_data_version, current_start, current_end, previous_min, previous_max):
    ensure_data_loaded(_data_version)
    with DATA_LOCK:
        current_df = df.copy()

    if current_df.empty or current_df['Run_Date_Parsed'].isna().all():
        return None, None, None, None

    min_date = current_df['Run_Date_Parsed'].min().date()
    max_date = current_df['Run_Date_Parsed'].max().date()

    start = pd.to_datetime(current_start, errors='coerce') if current_start else None
    end = pd.to_datetime(current_end, errors='coerce') if current_end else None

    if start is None or pd.isna(start) or str(start.date()) == str(previous_min):
        start = min_date
    else:
        start = min(max(start.date(), min_date), max_date)

    if end is None or pd.isna(end) or str(end.date()) == str(previous_max):
        end = max_date
    else:
        end = min(max(end.date(), min_date), max_date)

    if start > end:
        start, end = min_date, max_date

    return min_date, max_date, start, end

def dropdown_field(label, component_id, options, value, **kwargs):
    return html.Div([
        html.Label(label, htmlFor=component_id),
        dcc.Dropdown(id=component_id, options=options, value=value, **kwargs),
    ], className="browser-field")


property_options = [config_options, particles_options, max_threads_options,
                    machine_options, os_options, python_options]

# App layout
app.layout = html.Main([
    dcc.Location(id="comparison-url", refresh=False),
    dcc.Store(id="comparison-url-state", data={}),
    html.Header([
        html.Div([
            html.H1("XDG Benchmarking Dashboard"),
            html.P("Explore performance. Choose runs. Compare results."),
        ]),
        html.Div([
            html.Button("Refresh data", id="refresh-button", n_clicks=0, className="secondary-button"),
            html.Span(id="refresh-status", role="status"),
        ], className="refresh-controls"),
    ], className="benchmark-header"),

    html.Section([
        html.Div([
            html.Div([html.H2("Find runs"),
                      html.P("Search and filters help you browse. Your selected comparison stays in place.")]),
            html.Button("Reset filters", id="reset-run-filters", n_clicks=0, className="text-button"),
        ], className="browser-heading"),
        html.Div([
            html.Div([
                html.Label("Search runs", htmlFor="run-search"),
                dcc.Input(id="run-search", type="search", value="", debounce=0.25,
                          placeholder="Search date, run ID, configuration, machine…"),
            ], className="browser-field search-field"),
            html.Div([
                html.Label("Date range (UTC)"),
                dcc.DatePickerRange(
                    id="run-date-range", min_date_allowed=date_min, max_date_allowed=date_max,
                    start_date=date_start_default, end_date=date_end_default,
                    display_format="MMM D, YYYY", minimum_nights=0,
                    start_date_placeholder_text="Start date", end_date_placeholder_text="End date",
                ),
            ], className="browser-field date-field"),
        ], className="browser-search-row"),
        html.Details([
            html.Summary("Advanced filters"),
            html.Div([
                dropdown_field(label, component_id, options, [], multi=True, placeholder=f"All {label.lower()}")
                for (component_id, _, label), options in zip(PROPERTY_FILTERS, property_options)
            ], className="advanced-filter-grid"),
        ], className="advanced-filters"),
        html.Div([
            html.Span(id="matching-count", role="status"),
            html.Button("Select matching runs", id="select-matching", n_clicks=0, className="secondary-button"),
        ], className="run-table-toolbar"),
        dash.dash_table.DataTable(
            id="run-table", data=run_records,
            columns=[{"name": label, "id": column} for label, column in [
                ("Date (UTC)", "Date"), ("Configuration", "Config_File"),
                ("Particles / thread", "Particles_Per_Thread"), ("Max threads", "Config_Max_Threads"),
                ("Machine", "Machine"), ("Executable", "Executables"),
            ]],
            row_selectable="multi", selected_row_ids=initial_runs,
            selected_rows=[0] if initial_runs else [],
            sort_action="native", sort_mode="multi", page_size=5, page_current=0,
            cell_selectable=False,
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "left", "padding": "10px", "fontFamily": "Segoe UI, Arial, sans-serif", "fontSize": 13,
                        "whiteSpace": "normal", "height": "auto", "minWidth": "85px"},
            style_header={"backgroundColor": "#f3f6fa", "fontWeight": "600", "color": "#34495e",
                          "border": "none", "borderBottom": "1px solid #dbe3ed"},
            style_data={"border": "none", "borderBottom": "1px solid #e9eef4", "color": "#2c3e50"},
            style_data_conditional=[{"if": {"state": "selected"}, "backgroundColor": "#edf4ff"}],
        ),
        html.Div(id="run-browser-empty", className="browser-empty", role="status"),
        html.Div([
            html.Div([
                html.Strong(id="selection-count", role="status"),
                html.Button("Clear selection", id="clear-selection", n_clicks=0, className="text-button"),
            ], className="selection-heading"),
            html.Div(id="selected-run-chips", className="selected-run-chips"),
        ], className="selection-summary"),
    ], className="run-browser"),

    html.Div(id="comparison-notices", role="status", className="comparison-notices"),

    html.Section([
        dropdown_field("Model", "model-filter",
                       [{"label": model.upper(), "value": model} for model in sorted(df["Model"].unique())] if not df.empty else [],
                       sorted(df["Model"].unique())[0] if not df.empty else None, clearable=False),
        dropdown_field("Executables", "executable-filter",
                       build_filter_options(df.get("Executable")),
                       sorted(df["Executable"].unique()) if not df.empty else [], multi=True, clearable=False),
        dropdown_field("Metric", "metric-filter", [
            {"label": "Active rate (particles/sec)", "value": "Active rate"},
            {"label": "Inactive rate (particles/sec)", "value": "Inactive rate"},
        ], "Active rate", clearable=False),
    ], className="comparison-controls", **{"aria-label": "Comparison controls"}),

    dcc.Interval(id="refresh-poll", interval=2000, n_intervals=0),
    dcc.Store(id="data-version", data=LOCAL_DATA_VERSION),
    dcc.Store(id="selected-runs", data=initial_runs),

    html.Div([
        html.Section([
            html.H3("Performance scaling"),
            dcc.Graph(id="scaling-chart", style={"height": 430}),
        ], className="comparison-chart"),
        html.Section([
            html.H3("Speedup"),
            dcc.Graph(id="speedup-chart", style={"height": 430}),
        ], className="comparison-chart"),
    ], className="comparison-charts"),

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
], className='benchmark-page')

@callback(
    Output('scaling-chart', 'figure'),
    Output('speedup-chart', 'figure'),
    Output('comparison-chart', 'figure'),
    Output('flux-chart', 'figure'),
    Output('summary-stats', 'children'),
    Output('data-table', 'children'),
    Input('model-filter', 'value'),
    Input('executable-filter', 'value'),
    Input('selected-runs', 'data'),
    Input('metric-filter', 'value'),
    Input('data-version', 'data'),
    Input('comparison-url-state', 'data'),
)
def render_comparison(model, executables, runs, metric, version, url_state):
    if not (url_state or {}).get("initialized"):
        return empty_comparison("Loading comparison…")
    return update_comparison(model, executables, runs, metric, version)


def update_comparison(model, executables, runs, metric, version):
    return update_charts(model, executables, runs, None, None, [], [], [], [], [], [], metric, version)


def empty_comparison(message):
    def figure():
        result = go.Figure()
        result.add_annotation(text=message, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
        result.update_layout(xaxis={"visible": False}, yaxis={"visible": False},
                             plot_bgcolor="white", paper_bgcolor="white", margin={"t": 35, "b": 35})
        return result
    return figure(), figure(), figure(), figure(), message, message


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
    ensure_data_loaded(_data_version)
    with DATA_LOCK:
        current_df = df.copy()
        current_flux_df = flux_df.copy()

    if current_df.empty:
        return empty_comparison("No benchmark data is available. Refresh data to try again.")

    if not runs:
        return empty_comparison("Select runs above to start a comparison.")

    if not set(runs).intersection(current_df['Run_ID']):
        return empty_comparison("The selected runs are unavailable. Refresh data or choose other runs.")
    if not model or not executables:
        return empty_comparison("Select a model and at least one executable to compare runs.")
    if metric not in ("Active rate", "Inactive rate"):
        return empty_comparison("Choose a valid performance metric.")

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
        return empty_comparison("The selected runs have no results for this model and executable.")

    filtered_df = filtered_df.dropna(subset=[metric])
    if filtered_df.empty:
        return empty_comparison("The selected runs have no measurements for this metric.")
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
    if not flux_filtered.empty:
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
