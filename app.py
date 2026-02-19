import dash
from dash import dcc, html, Input, Output, callback
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from pathlib import Path

from schema_validator import discover_run_dirs_recursive, load_and_validate_run

# Initialize the Dash app
app = dash.Dash(__name__, title="XDG Benchmarking Dashboard")
server = app.server

# Data loading and processing functions
def load_benchmark_data():
    """Load all benchmark data from the results directory (schema-based)."""
    data = []
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

    if not data:
        return pd.DataFrame()

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

    print(f"Column names: {combined_df.columns.tolist()}")
    print(f"Sample data:\n{combined_df.head()}")

    return combined_df

# Load data
df = load_benchmark_data()

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
        dataframe[['Run_ID', 'Run_Date', 'Run_Date_Parsed']]
        .drop_duplicates()
        .sort_values(['Run_Date_Parsed', 'Run_ID'])
    )
    options = [
        {'label': f"{row['Run_ID']} ({row['Run_Date']})", 'value': row['Run_ID']}
        for _, row in runs.iterrows()
    ]
    values = runs['Run_ID'].tolist()
    return options, values

run_options, run_values = build_run_options(df)
config_options = build_filter_options(df.get('Config_File')) if not df.empty else []
machine_options = build_filter_options(df.get('Machine')) if not df.empty else []
os_options = build_filter_options(df.get('OS')) if not df.empty else []
python_options = build_filter_options(df.get('Python_Version')) if not df.empty else []
particles_options = build_filter_options(df.get('Particles_Per_Thread')) if not df.empty else []
max_threads_options = build_filter_options(df.get('Config_Max_Threads')) if not df.empty else []

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
            html.Label("Dataset / Run:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='run-filter',
                options=run_options,
                value=run_values if run_values else [],
                multi=True,
                style={'width': '100%'}
            )
        ], style={'backgroundColor': '#f8f9fa', 'padding': 20, 'borderRadius': 10, 'flex': '1 1 320px'}),

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
    Output('summary-stats', 'children'),
    Output('data-table', 'children'),
    Input('model-filter', 'value'),
    Input('executable-filter', 'value'),
    Input('run-filter', 'value'),
    Input('config-filter', 'value'),
    Input('particles-filter', 'value'),
    Input('maxthreads-filter', 'value'),
    Input('machine-filter', 'value'),
    Input('os-filter', 'value'),
    Input('python-filter', 'value'),
    Input('metric-filter', 'value')
)
def update_charts(
    model,
    executables,
    runs,
    config_files,
    particles_per_thread,
    max_threads_config,
    machines,
    os_values,
    python_versions,
    metric,
):
    if df.empty:
        return {}, {}, {}, "No data available", "No data available"

    # Filter data
    filtered_df = df.copy()
    if model:
        filtered_df = filtered_df[filtered_df['Model'] == model]
    if executables:
        filtered_df = filtered_df[filtered_df['Executable'].isin(executables)]
    if runs:
        filtered_df = filtered_df[filtered_df['Run_ID'].isin(runs)]
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
        return {}, {}, {}, "No data available for selected filters", "No data available"

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
        hover_data={'Executable': True, 'Run_Date': True, 'Run_ID': True},
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
        hover_data={'Executable': True, 'Run_Date': True, 'Run_ID': True},
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
        filtered_df.groupby(['Run_ID', 'Run_Date', 'Run_Date_Parsed', 'Executable', 'Model'])[metric]
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
            hover_data={'Run_ID': True, 'Run_Date': True, 'Executable': True, 'Run_Date_Parsed': False}
        )
        comparison_fig.update_layout(
            xaxis_title="Run Date",
            yaxis_title=f"{metric} (particles/sec)",
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
        'Run_ID', 'Run_Date', 'Model', 'Executable', '# Threads', 'Active rate', 'Inactive rate'
    ]
    table_df = filtered_df[table_columns_order].copy()
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

    return scaling_fig, speedup_fig, comparison_fig, summary_stats, data_table

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)
