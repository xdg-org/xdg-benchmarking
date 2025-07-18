import dash
from dash import dcc, html, Input, Output, callback, dash_table
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime
import glob

# Initialize the Dash app with external stylesheets for better integration
app = dash.Dash(
    __name__,
    title="XDG Benchmarking Dashboard",
    external_stylesheets=[
        'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css'
    ],
    suppress_callback_exceptions=True
)
server = app.server

class BenchmarkDataManager:
    """Manages dynamic discovery and loading of benchmark data"""

    def __init__(self):
        self.runs = []
        self.models = set()
        self.executables = set()
        self.refresh()

    def discover_runs(self):
        """Find all runs that follow the standard schema"""
        runs = []
        runs_dir = "results/runs"

        if not os.path.exists(runs_dir):
            return runs

        for run_id in os.listdir(runs_dir):
            run_path = os.path.join(runs_dir, run_id)
            if os.path.isdir(run_path):
                config_file = os.path.join(run_path, "config.json")
                results_file = os.path.join(run_path, "results.json")

                if os.path.exists(config_file) and os.path.exists(results_file):
                    try:
                        with open(config_file, 'r') as f:
                            config = json.load(f)
                        with open(results_file, 'r') as f:
                            results = json.load(f)

                        # Basic validation
                        if self.validate_run_schema(config, results):
                            # Format the display name
                            display_name = self.format_run_display_name(run_id, config.get('date', ''))

                            runs.append({
                                'id': run_id,
                                'display_name': display_name,
                                'config': config,
                                'results': results,
                                'path': run_path
                            })
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid data in {run_id}: {e}")

        return sorted(runs, key=lambda x: x['config']['date'], reverse=True)

    def format_run_display_name(self, run_id, date_str):
        """Format run ID and date into a user-friendly display name"""
        try:
            # Try to parse the date
            if date_str:
                # Parse ISO format date
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                formatted_date = dt.strftime('%B %d, %Y at %I:%M %p')
            else:
                # Fallback to parsing run_id if it's a timestamp
                if len(run_id) >= 14:  # YYYYMMDD_HHMMSS format
                    try:
                        dt = datetime.strptime(run_id, '%Y%m%d_%H%M%S')
                        formatted_date = dt.strftime('%B %d, %Y at %I:%M %p')
                    except ValueError:
                        formatted_date = run_id
                else:
                    formatted_date = run_id

            return formatted_date
        except:
            # If all parsing fails, return a cleaned version of the run_id
            return run_id.replace('_', ' ').title()

    def validate_run_schema(self, config, results):
        """Basic schema validation"""
        try:
            # Check required fields
            required_config = ['run_id', 'date', 'models', 'executables']
            required_results = ['run_id', 'date', 'results']

            if not all(field in config for field in required_config):
                return False
            if not all(field in results for field in required_results):
                return False

            # Check consistency
            if config['run_id'] != results['run_id']:
                return False
            if config['date'] != results['date']:
                return False

            return True
        except:
            return False

    def discover_models_and_executables(self, runs):
        """Extract models and executables from actual data"""
        models = set()
        executables = set()

        for run in runs:
            models.update(run['config']['models'])
            executables.update(run['config']['executables'])

        return sorted(list(models)), sorted(list(executables))

    def refresh(self):
        """Re-scan for new data"""
        self.runs = self.discover_runs()
        self.models, self.executables = self.discover_models_and_executables(self.runs)

    def get_filtered_data(self, selected_models=None, selected_executables=None, selected_runs=None):
        """Get filtered data for dashboard"""
        filtered_runs = self.runs

        if selected_runs:
            filtered_runs = [run for run in filtered_runs if run['id'] in selected_runs]

        # Convert to DataFrame for easier manipulation
        data = []
        for run in filtered_runs:
            for model, model_results in run['results']['results'].items():
                if selected_models and model not in selected_models:
                    continue

                for executable, exec_results in model_results.items():
                    if selected_executables and executable not in selected_executables:
                        continue

                    for scaling_point in exec_results['scaling']:
                        data.append({
                            'run_id': run['id'],
                            'run_date': run['config']['date'],
                            'model': model,
                            'executable': executable,
                            'threads': scaling_point['threads'],
                            'active_rate': scaling_point['active_rate'],
                            'inactive_rate': scaling_point['inactive_rate']
                        })

        return pd.DataFrame(data)

# Initialize data manager
data_manager = BenchmarkDataManager()

# Dashboard layout
app.layout = html.Div([
    # Header
    html.Div([
        html.Div([
            html.Img(src="/assets/xdg-logo.png", alt="XDG Logo", className="xdg-logo"),
            html.Div([
                html.H1("XDG Benchmarking Dashboard",
                        className="dashboard-title"),
                html.P("Accelerated Discretized Geometry Performance Analysis",
                       className="dashboard-subtitle")
            ], className="header-text")
        ], className="header-left"),
        html.Div([
            html.Button([
                html.I(className="fas fa-sync-alt"),
                " Refresh Data"
            ], id="refresh-button", className="refresh-btn"),
            html.Div(id="last-updated", className="last-updated")
        ], className="header-controls")
    ], className="dashboard-header"),

    # Filters
    html.Div([
        html.H3("Filters", className="filters-title"),
        html.Div([
            html.Div([
                html.Label("Models:", className="filter-label"),
                dcc.Dropdown(
                    id='model-filter',
                    options=[{'label': model.title(), 'value': model} for model in data_manager.models],
                    value=data_manager.models if data_manager.models else None,
                    multi=True,
                    className="filter-dropdown"
                )
            ], className="filter-group"),

            html.Div([
                html.Label("Executables:", className="filter-label"),
                dcc.Dropdown(
                    id='executable-filter',
                    options=[{'label': exe.upper(), 'value': exe} for exe in data_manager.executables],
                    value=data_manager.executables if data_manager.executables else None,
                    multi=True,
                    className="filter-dropdown"
                )
            ], className="filter-group"),

            html.Div([
                html.Label("Runs:", className="filter-label"),
                dcc.Dropdown(
                    id='run-filter',
                    options=[{'label': run['display_name'], 'value': run['id']} for run in data_manager.runs],
                    value=[run['id'] for run in data_manager.runs] if data_manager.runs else None,
                    multi=True,
                    className="filter-dropdown"
                )
            ], className="filter-group"),

            html.Div([
                html.Label("Metric:", className="filter-label"),
                dcc.Dropdown(
                    id='metric-filter',
                    options=[
                        {'label': 'Active Rate (particles/sec)', 'value': 'active_rate'},
                        {'label': 'Inactive Rate (particles/sec)', 'value': 'inactive_rate'}
                    ],
                    value='active_rate',
                    className="filter-dropdown"
                )
            ], className="filter-group")
        ], className="filters-container")
    ], className="filters-section"),

    # Main charts
    html.Div([
        html.Div([
            html.H3("Performance Scaling", className="chart-title"),
            dcc.Graph(id='scaling-chart', className="chart-container")
        ], className="chart-section"),

        html.Div([
            html.H3("Speedup Analysis", className="chart-title"),
            dcc.Graph(id='speedup-chart', className="chart-container")
        ], className="chart-section")
    ], className="charts-row"),

    # Comparison and summary
    html.Div([
        html.Div([
            html.H3("Executable Comparison", className="chart-title"),
            dcc.Graph(id='comparison-chart', className="chart-container")
        ], className="chart-section"),

        html.Div([
            html.H3("Summary Statistics", className="chart-title"),
            html.Div(id='summary-stats', className="summary-container")
        ], className="chart-section")
    ], className="charts-row"),

    # Data table
    html.Div([
        html.H3("Raw Data", className="chart-title"),
        html.Div(id='data-table', className="table-container")
    ], className="table-section")
], className="dashboard-container")

# Callbacks
@callback(
    Output('last-updated', 'children'),
    Output('model-filter', 'options'),
    Output('model-filter', 'value'),
    Output('executable-filter', 'options'),
    Output('executable-filter', 'value'),
    Output('run-filter', 'options'),
    Output('run-filter', 'value'),
    Input('refresh-button', 'n_clicks')
)
def refresh_data(n_clicks):
    """Refresh data and update filter options"""
    if n_clicks:
        data_manager.refresh()

    last_updated = f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    model_options = [{'label': model.title(), 'value': model} for model in data_manager.models]
    model_value = data_manager.models if data_manager.models else None

    exec_options = [{'label': exe.upper(), 'value': exe} for exe in data_manager.executables]
    exec_value = data_manager.executables if data_manager.executables else None

    run_options = [{'label': run['display_name'], 'value': run['id']} for run in data_manager.runs]
    run_value = [run['id'] for run in data_manager.runs] if data_manager.runs else None

    return last_updated, model_options, model_value, exec_options, exec_value, run_options, run_value

@callback(
    Output('scaling-chart', 'figure'),
    Output('speedup-chart', 'figure'),
    Output('comparison-chart', 'figure'),
    Output('summary-stats', 'children'),
    Output('data-table', 'children'),
    Input('model-filter', 'value'),
    Input('executable-filter', 'value'),
    Input('run-filter', 'value'),
    Input('metric-filter', 'value')
)
def update_charts(selected_models, selected_executables, selected_runs, selected_metric):
    """Update all charts based on filter selections"""
    if not data_manager.runs:
        return {}, {}, {}, "No data available", "No data available"

    # Get filtered data
    df = data_manager.get_filtered_data(selected_models, selected_executables, selected_runs)

    if df.empty:
        return {}, {}, {}, "No data available for selected filters", "No data available"

    # Filter out null values for the selected metric
    df_filtered = df.dropna(subset=[selected_metric])

    if df_filtered.empty:
        return {}, {}, {}, "No data available for selected metric", "No data available"

    # Define line styles for different models
    model_line_styles = {
        'atr': 'solid',
        'tokamak': 'dash',
        'msre': 'dot',
        'default': 'solid'
    }

    # Define consistent colors for different executables
    executable_colors = {
        'moab': '#1f77b4',      # Blue
        'xdg': '#ff7f0e',       # Orange
        'double-down': '#2ca02c', # Green
        'default': '#d62728'    # Red for any new executables
    }

    # Scaling chart
    scaling_fig = go.Figure()

    # Plot each executable and model combination separately
    for executable in df_filtered['executable'].unique():
        for model in df_filtered['model'].unique():
            # Get data for this specific executable and model
            exec_model_data = df_filtered[(df_filtered['executable'] == executable) &
                                        (df_filtered['model'] == model)].copy()

            if not exec_model_data.empty:
                # Sort by thread count to ensure proper line plotting
                exec_model_data_sorted = exec_model_data.sort_values('threads')

                # Get line style for this model
                line_style = model_line_styles.get(model, model_line_styles['default'])

                # Get color for this executable
                line_color = executable_colors.get(executable, executable_colors['default'])

                scaling_fig.add_trace(go.Scatter(
                    x=exec_model_data_sorted['threads'],
                    y=exec_model_data_sorted[selected_metric],
                    mode='lines+markers',
                    name=f'{executable.upper()} - {model.title()}',
                    line=dict(dash=line_style, color=line_color),
                    marker=dict(color=line_color),
                    hovertemplate='Model: ' + model.title() + '<br>Threads: %{x}<br>' + selected_metric.replace('_', ' ').title() + ': %{y:.2f}<extra></extra>'
                ))

    scaling_fig.update_layout(
        title=f'{selected_metric.replace("_", " ").title()} vs Thread Count',
        xaxis_title="Number of Threads",
        yaxis_title=f"{selected_metric.replace('_', ' ').title()} (particles/sec)",
        hovermode='x unified',
        template='plotly_white',
        height=400,
        autosize=False
    )

        # Speedup chart
    speedup_fig = go.Figure()

    # Calculate speedup for each executable and model combination
    for executable in df_filtered['executable'].unique():
        for model in df_filtered['model'].unique():
            # Get data for this specific executable and model
            exec_model_data = df_filtered[(df_filtered['executable'] == executable) &
                                        (df_filtered['model'] == model)].copy()

            if not exec_model_data.empty:
                # Get single-thread performance as baseline for this specific model
                single_thread_data = exec_model_data[exec_model_data['threads'] == 1]
                if not single_thread_data.empty:
                    single_thread = single_thread_data[selected_metric].iloc[0]
                    if pd.notna(single_thread) and single_thread > 0:
                        exec_model_data['speedup'] = exec_model_data[selected_metric] / single_thread

                        # Sort by thread count to ensure proper line plotting
                        exec_model_data_sorted = exec_model_data.sort_values('threads')

                        # Get line style for this model
                        line_style = model_line_styles.get(model, model_line_styles['default'])

                        # Get color for this executable
                        line_color = executable_colors.get(executable, executable_colors['default'])

                        speedup_fig.add_trace(go.Scatter(
                            x=exec_model_data_sorted['threads'],
                            y=exec_model_data_sorted['speedup'],
                            mode='lines+markers',
                            name=f'{executable.upper()} - {model.title()}',
                            line=dict(dash=line_style, color=line_color),
                            marker=dict(color=line_color),
                            hovertemplate='Model: ' + model.title() + '<br>Threads: %{x}<br>Speedup: %{y:.2f}<extra></extra>'
                        ))

    # Add ideal speedup line
    max_threads = df_filtered['threads'].max()
    speedup_fig.add_trace(go.Scatter(
        x=[1, max_threads],
        y=[1, max_threads],
        mode='lines',
        name='Ideal Speedup',
        line=dict(dash='dash', color='gray'),
        hovertemplate='Threads: %{x}<br>Ideal Speedup: %{y}<extra></extra>'
    ))

    speedup_fig.update_layout(
        title='Speedup vs Thread Count',
        xaxis_title='Number of Threads',
        yaxis_title='Speedup',
        hovermode='x unified',
        template='plotly_white',
        height=400,
        autosize=False
    )

    # Comparison chart (bar chart for max performance)
    max_performance = df_filtered.groupby(['model', 'executable'])[selected_metric].max().reset_index()

    comparison_fig = px.bar(
        max_performance,
        x='model',
        y=selected_metric,
        color='executable',
        title=f'Maximum {selected_metric.replace("_", " ").title()} by Model and Executable',
        barmode='group',
        color_discrete_map=executable_colors
    )
    comparison_fig.update_layout(
        xaxis_title="Model",
        yaxis_title=f"{selected_metric.replace('_', ' ').title()} (particles/sec)",
        hovermode='x unified',
        template='plotly_white',
        height=400,
        autosize=False
    )

    # Summary statistics
    summary_stats = []

    # Overall statistics
    summary_stats.append(html.H4("Overall Statistics", className="summary-section"))
    summary_stats.append(html.P(f"Total data points: {len(df_filtered)}"))
    summary_stats.append(html.P(f"Models: {', '.join(df_filtered['model'].unique())}"))
    summary_stats.append(html.P(f"Executables: {', '.join(df_filtered['executable'].unique())}"))

    # Format run display names for summary
    run_display_names = []
    for run_id in df_filtered['run_id'].unique():
        for run in data_manager.runs:
            if run['id'] == run_id:
                run_display_names.append(run['display_name'])
                break
    summary_stats.append(html.P(f"Runs: {', '.join(run_display_names)}"))

    # Performance statistics
    summary_stats.append(html.H4("Performance Statistics", className="summary-section"))
    max_rate = df_filtered[selected_metric].max()
    min_rate = df_filtered[selected_metric].min()
    mean_rate = df_filtered[selected_metric].mean()

    summary_stats.append(html.P(f"Maximum {selected_metric.replace('_', ' ')}: {max_rate:.2e} particles/sec"))
    summary_stats.append(html.P(f"Minimum {selected_metric.replace('_', ' ')}: {min_rate:.2e} particles/sec"))
    summary_stats.append(html.P(f"Mean {selected_metric.replace('_', ' ')}: {mean_rate:.2e} particles/sec"))

    # Best performing configuration
    best_config = df_filtered.loc[df_filtered[selected_metric].idxmax()]
    summary_stats.append(html.H4("Best Performance", className="summary-section"))
    summary_stats.append(html.P(f"Model: {best_config['model']}"))
    summary_stats.append(html.P(f"Executable: {best_config['executable']}"))
    summary_stats.append(html.P(f"Threads: {best_config['threads']}"))
    summary_stats.append(html.P(f"Rate: {best_config[selected_metric]:.2e} particles/sec"))

    # Data table
    table_data = df_filtered.round(2).to_dict('records')

    # Replace run_id with display names in table data
    for row in table_data:
        for run in data_manager.runs:
            if run['id'] == row['run_id']:
                row['run_id'] = run['display_name']
                break

    table_columns = [{"name": col.replace('_', ' ').title(), "id": col} for col in df_filtered.columns]

    data_table = dash_table.DataTable(
        data=table_data,
        columns=table_columns,
        page_size=10,
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'color': '#2c3e50',
            'fontSize': '14px',
            'fontFamily': 'Segoe UI, Tahoma, Geneva, Verdana, sans-serif'
        },
        style_header={
            'backgroundColor': '#2c3e50',
            'color': 'white',
            'fontWeight': 'bold',
            'fontSize': '14px',
            'fontFamily': 'Segoe UI, Tahoma, Geneva, Verdana, sans-serif'
        },
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': '#f8f9fa'},
            {'if': {'row_index': 'even'}, 'backgroundColor': 'white'}
        ]
    )

    return scaling_fig, speedup_fig, comparison_fig, summary_stats, data_table

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)