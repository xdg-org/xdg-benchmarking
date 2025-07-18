#!/usr/bin/env python3
"""
XDG Benchmarking Dashboard - Production Version
Enhanced with logging, error handling, health checks, and monitoring
"""

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
from flask import Flask, jsonify
import traceback

# Import our custom modules
from config import get_config
from logging_config import setup_logging, get_logger
from health import get_health_status

# Setup logging
logger = setup_logging()

# Get configuration
config = get_config()

# Initialize the Dash app with external stylesheets for better integration
app = dash.Dash(
    __name__,
    title=config.DASHBOARD_TITLE,
    external_stylesheets=[
        'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css'
    ],
    suppress_callback_exceptions=True
)

# Get the Flask server for adding routes
server = app.server

# Add health check endpoint
@server.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        health_status = get_health_status()
        status_code = 200 if health_status['status'] == 'healthy' else 503
        return jsonify(health_status), status_code
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Health check failed: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500

@server.route('/health/simple')
def simple_health_check():
    """Simple health check for load balancers"""
    try:
        health_status = get_health_status()
        if health_status['status'] == 'healthy':
            return 'OK', 200
        else:
            return 'UNHEALTHY', 503
    except Exception as e:
        logger.error(f"Simple health check failed: {e}")
        return 'ERROR', 500

class BenchmarkDataManager:
    """Manages dynamic discovery and loading of benchmark data with error handling"""

    def __init__(self):
        self.runs = []
        self.models = set()
        self.executables = set()
        self.logger = get_logger('data_manager')
        self.refresh()

    def discover_runs(self):
        """Find all runs that follow the standard schema with error handling"""
        runs = []
        runs_dir = config.RUNS_DIR

        if not os.path.exists(runs_dir):
            self.logger.warning(f"Results directory not found: {runs_dir}")
            return runs

        try:
            for run_id in os.listdir(runs_dir):
                run_path = os.path.join(runs_dir, run_id)
                if os.path.isdir(run_path):
                    config_file = os.path.join(run_path, "config.json")
                    results_file = os.path.join(run_path, "results.json")

                    if os.path.exists(config_file) and os.path.exists(results_file):
                        try:
                            with open(config_file, 'r') as f:
                                config_data = json.load(f)
                            with open(results_file, 'r') as f:
                                results_data = json.load(f)

                            # Basic validation
                            if self.validate_run_schema(config_data, results_data):
                                # Format the display name
                                display_name = self.format_run_display_name(run_id, config_data.get('date', ''))

                                runs.append({
                                    'id': run_id,
                                    'display_name': display_name,
                                    'config': config_data,
                                    'results': results_data,
                                    'path': run_path
                                })
                                self.logger.info(f"Loaded run: {run_id} ({display_name})")
                            else:
                                self.logger.warning(f"Invalid schema for run: {run_id}")
                        except (json.JSONDecodeError, KeyError) as e:
                            self.logger.error(f"Error loading run {run_id}: {e}")
                    else:
                        self.logger.debug(f"Missing config or results for run: {run_id}")

        except Exception as e:
            self.logger.error(f"Error discovering runs: {e}")
            self.logger.error(traceback.format_exc())

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
        except Exception as e:
            self.logger.warning(f"Error formatting run display name for {run_id}: {e}")
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
        except Exception as e:
            self.logger.error(f"Schema validation error: {e}")
            return False

    def discover_models_and_executables(self, runs):
        """Extract models and executables from actual data"""
        models = set()
        executables = set()

        try:
            for run in runs:
                models.update(run['config']['models'])
                executables.update(run['config']['executables'])
        except Exception as e:
            self.logger.error(f"Error discovering models and executables: {e}")

        return sorted(list(models)), sorted(list(executables))

    def refresh(self):
        """Re-scan for new data with error handling"""
        try:
            self.logger.info("Refreshing benchmark data...")
            self.runs = self.discover_runs()
            self.models, self.executables = self.discover_models_and_executables(self.runs)
            self.logger.info(f"Data refresh complete. Found {len(self.runs)} runs, {len(self.models)} models, {len(self.executables)} executables")
        except Exception as e:
            self.logger.error(f"Error refreshing data: {e}")
            self.logger.error(traceback.format_exc())

    def get_filtered_data(self, selected_models=None, selected_executables=None, selected_runs=None):
        """Get filtered data for dashboard with error handling"""
        try:
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
        except Exception as e:
            self.logger.error(f"Error getting filtered data: {e}")
            self.logger.error(traceback.format_exc())
            return pd.DataFrame()

# Initialize data manager
data_manager = BenchmarkDataManager()

# Dashboard layout with error handling
def create_layout():
    """Create the dashboard layout with error handling"""
    try:
        return html.Div([
            # Header
            html.Div([
                html.Div([
                    html.Img(src="/assets/xdg-logo.png", alt="XDG Logo", className="xdg-logo"),
                    html.Div([
                        html.H1(config.DASHBOARD_TITLE, className="dashboard-title"),
                        html.P(config.DASHBOARD_SUBTITLE, className="dashboard-subtitle")
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
                            options=[{'label': exec_name.upper(), 'value': exec_name} for exec_name in data_manager.executables],
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
                                {'label': 'Active Rate', 'value': 'active_rate'},
                                {'label': 'Inactive Rate', 'value': 'inactive_rate'}
                            ],
                            value='active_rate',
                            className="filter-dropdown"
                        )
                    ], className="filter-group")
                ], className="filters-container")
            ], className="filters-section"),

            # Charts
            html.Div([
                html.Div([
                    html.Div([
                        html.H3("Scaling Performance", className="chart-title"),
                        dcc.Graph(id='scaling-chart', className="chart-container")
                    ], className="chart-section"),
                    html.Div([
                        html.H3("Speedup Analysis", className="chart-title"),
                        dcc.Graph(id='speedup-chart', className="chart-container")
                    ], className="chart-section")
                ], className="charts-row"),
                html.Div([
                    html.H3("Performance Comparison", className="chart-title"),
                    dcc.Graph(id='comparison-chart', className="chart-container")
                ], className="chart-section")
            ], className="charts-section"),

            # Summary and Data Table
            html.Div([
                html.Div([
                    html.H3("Summary Statistics", className="chart-title"),
                    html.Div(id='summary-stats', className="summary-container")
                ], className="summary-section"),
                html.Div([
                    html.H3("Data Table", className="chart-title"),
                    html.Div(id='data-table', className="table-container")
                ], className="table-section")
            ], className="summary-table-section"),

            # Error display
            html.Div(id='error-display', className="error-display", style={'display': 'none'})

        ], className="dashboard-container")
    except Exception as e:
        logger.error(f"Error creating layout: {e}")
        logger.error(traceback.format_exc())
        return html.Div([
            html.H1("Error Loading Dashboard"),
            html.P(f"An error occurred while loading the dashboard: {str(e)}"),
            html.Button("Retry", id="retry-button", className="retry-btn")
        ], className="error-container")

app.layout = create_layout()

# Callbacks with error handling
@callback(
    Output('last-updated', 'children'),
    Output('model-filter', 'options'),
    Output('model-filter', 'value'),
    Output('executable-filter', 'options'),
    Output('executable-filter', 'value'),
    Output('run-filter', 'options'),
    Output('run-filter', 'value'),
    Output('error-display', 'children'),
    Output('error-display', 'style'),
    Input('refresh-button', 'n_clicks')
)
def refresh_data(n_clicks):
    """Refresh data with error handling"""
    try:
        if n_clicks is None:
            n_clicks = 0

        logger.info(f"Data refresh requested (click #{n_clicks})")
        data_manager.refresh()

        # Update last updated time
        last_updated = f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Update filter options
        model_options = [{'label': model.title(), 'value': model} for model in data_manager.models]
        model_value = data_manager.models if data_manager.models else None

        executable_options = [{'label': exec_name.upper(), 'value': exec_name} for exec_name in data_manager.executables]
        executable_value = data_manager.executables if data_manager.executables else None

        run_options = [{'label': run['display_name'], 'value': run['id']} for run in data_manager.runs]
        run_value = [run['id'] for run in data_manager.runs] if data_manager.runs else None

        return last_updated, model_options, model_value, executable_options, executable_value, run_options, run_value, "", {'display': 'none'}

    except Exception as e:
        logger.error(f"Error in refresh_data callback: {e}")
        logger.error(traceback.format_exc())
        error_message = f"Error refreshing data: {str(e)}"
        return "Error occurred", [], None, [], None, [], None, error_message, {'display': 'block', 'color': 'red', 'padding': '10px'}

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
    """Update all charts based on filter selections with error handling"""
    try:
        if not data_manager.runs:
            logger.warning("No benchmark runs available")
            return {}, {}, {}, "No data available", "No data available"

        # Get filtered data
        df = data_manager.get_filtered_data(selected_models, selected_executables, selected_runs)

        if df.empty:
            logger.warning("No data available for selected filters")
            return {}, {}, {}, "No data available for selected filters", "No data available"

        # Filter out null values for the selected metric
        df_filtered = df.dropna(subset=[selected_metric])

        if df_filtered.empty:
            logger.warning(f"No data available for selected metric: {selected_metric}")
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

        # Generate scaling chart
        scaling_fig = go.Figure()
        for executable in df_filtered['executable'].unique():
            for model in df_filtered['model'].unique():
                exec_model_data = df_filtered[(df_filtered['executable'] == executable) &
                                            (df_filtered['model'] == model)].copy()

                if not exec_model_data.empty:
                    exec_model_data_sorted = exec_model_data.sort_values('threads')
                    line_style = model_line_styles.get(model, model_line_styles['default'])
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
            height=400
        )

        # Generate speedup chart
        speedup_fig = go.Figure()
        for executable in df_filtered['executable'].unique():
            for model in df_filtered['model'].unique():
                exec_model_data = df_filtered[(df_filtered['executable'] == executable) &
                                            (df_filtered['model'] == model)].copy()

                if not exec_model_data.empty:
                    single_thread_data = exec_model_data[exec_model_data['threads'] == 1]
                    if not single_thread_data.empty:
                        single_thread = single_thread_data[selected_metric].iloc[0]
                        if pd.notna(single_thread) and single_thread > 0:
                            exec_model_data['speedup'] = exec_model_data[selected_metric] / single_thread
                            exec_model_data_sorted = exec_model_data.sort_values('threads')
                            line_style = model_line_styles.get(model, model_line_styles['default'])
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
            height=400
        )

        # Generate comparison chart
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
            height=400
        )

        # Summary statistics
        summary_stats = [html.H4("Data loaded successfully", className="summary-section")]

        # Data table
        data_table = dash_table.DataTable(
            data=df_filtered.head(10).to_dict('records'),
            columns=[{"name": col.replace('_', ' ').title(), "id": col} for col in df_filtered.columns],
            page_size=10
        )

        return scaling_fig, speedup_fig, comparison_fig, summary_stats, data_table

    except Exception as e:
        logger.error(f"Error in update_charts callback: {e}")
        logger.error(traceback.format_exc())
        error_fig = go.Figure().add_annotation(
            text=f"Error loading charts: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        error_message = f"Error updating charts: {str(e)}"
        return error_fig, error_fig, error_fig, error_message, error_message

if __name__ == '__main__':
    logger.info("Starting XDG Benchmarking Dashboard...")
    logger.info(f"Configuration: DEBUG={config.DEBUG}, PORT={config.PORT}")

    try:
        app.run(
            debug=config.DEBUG,
            host=config.HOST,
            port=config.PORT
        )
    except Exception as e:
        logger.error(f"Failed to start dashboard: {e}")
        logger.error(traceback.format_exc())
        raise