#!/usr/bin/env python3
"""
Generate static HTML version of the XDG Benchmarking Dashboard
for GitHub Pages hosting
"""

import json
import os
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

class StaticDashboardGenerator:
    def __init__(self):
        self.results_dir = "results"
        self.output_dir = "docs"  # GitHub Pages serves from /docs

    def load_data(self):
        """Load all benchmark data"""
        data = []
        # Discover runs
        runs_dir = os.path.join(self.results_dir, "runs")
        print(f"Looking for runs in: {runs_dir}")
        if os.path.exists(runs_dir):
            print(f"Found runs directory: {runs_dir}")
            for run_id in os.listdir(runs_dir):
                run_path = os.path.join(runs_dir, run_id)
                print(f"Checking run: {run_id}")
                if os.path.isdir(run_path):
                    config_file = os.path.join(run_path, "config.json")
                    results_file = os.path.join(run_path, "results.json")
                    if os.path.exists(config_file) and os.path.exists(results_file):
                        print(f"  Found config and results for {run_id}")
                        with open(config_file, 'r') as f:
                            config = json.load(f)
                        with open(results_file, 'r') as f:
                            results = json.load(f)
                        # Process results
                        for model, model_results in results['results'].items():
                            for executable, exec_results in model_results.items():
                                for scaling_point in exec_results['scaling']:
                                    data.append({
                                        'run_id': run_id,
                                        'run_date': config['date'],
                                        'model': model,
                                        'executable': executable,
                                        'threads': scaling_point['threads'],
                                        'active_rate': scaling_point['active_rate'],
                                        'inactive_rate': scaling_point['inactive_rate']
                                    })
                        print(f"  Added {len([d for d in data if d['run_id'] == run_id])} data points for {run_id}")
                    else:
                        print(f"  Missing config or results for {run_id}")
        else:
            print(f"Runs directory not found: {runs_dir}")
        df = pd.DataFrame(data)
        print(f"Total data points loaded: {len(df)}")
        if not df.empty:
            print(f"Models: {df['model'].unique()}")
            print(f"Executables: {df['executable'].unique()}")
            print(f"Runs: {df['run_id'].unique()}")
        return df

    def format_run_display_name(self, run_id, date_str):
        """Format run ID for display"""
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime("%B %d, %Y at %I:%M %p")
        except:
            return run_id

    def generate_charts(self, df, metric='active_rate'):
        """Generate static charts"""
        if df.empty:
            return "", "", ""

        # Filter out null values
        df_filtered = df.dropna(subset=[metric])
        if df_filtered.empty:
            return "", "", ""

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
                        y=exec_model_data_sorted[metric],
                        mode='lines+markers',
                        name=f'{executable.upper()} - {model.title()}',
                        line=dict(dash=line_style, color=line_color),
                        marker=dict(color=line_color),
                        hovertemplate='Model: ' + model.title() + '<br>Threads: %{x}<br>' +
                                    metric.replace('_', ' ').title() + ': %{y:.2f}<extra></extra>'
                    ))

        scaling_fig.update_layout(
            title=f'{metric.replace("_", " ").title()} vs Thread Count',
            xaxis_title="Number of Threads",
            yaxis_title=f"{metric.replace('_', ' ').title()} (particles/sec)",
            hovermode='x unified',
            template='plotly_white',
            height=400
        )

        # Speedup chart
        speedup_fig = go.Figure()
        for executable in df_filtered['executable'].unique():
            for model in df_filtered['model'].unique():
                exec_model_data = df_filtered[(df_filtered['executable'] == executable) &
                                            (df_filtered['model'] == model)].copy()

                if not exec_model_data.empty:
                    single_thread_data = exec_model_data[exec_model_data['threads'] == 1]
                    if not single_thread_data.empty:
                        single_thread = single_thread_data[metric].iloc[0]
                        if pd.notna(single_thread) and single_thread > 0:
                            exec_model_data['speedup'] = exec_model_data[metric] / single_thread
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

        # Comparison chart
        max_performance = df_filtered.groupby(['model', 'executable'])[metric].max().reset_index()
        comparison_fig = px.bar(
            max_performance,
            x='model',
            y=metric,
            color='executable',
            title=f'Maximum {metric.replace("_", " ").title()} by Model and Executable',
            barmode='group',
            color_discrete_map=executable_colors
        )
        comparison_fig.update_layout(
            xaxis_title="Model",
            yaxis_title=f"{metric.replace('_', ' ').title()} (particles/sec)",
            hovermode='x unified',
            template='plotly_white',
            height=400
        )

        return scaling_fig.to_html(include_plotlyjs=False, full_html=False), \
               speedup_fig.to_html(include_plotlyjs=False, full_html=False), \
               comparison_fig.to_html(include_plotlyjs=False, full_html=False)

    def generate_summary_stats(self, df, metric='active_rate'):
        """Generate summary statistics HTML"""
        if df.empty:
            return "<p>No data available</p>"

        df_filtered = df.dropna(subset=[metric])
        if df_filtered.empty:
            return "<p>No data available for selected metric</p>"

        stats_html = []

        # Overall statistics
        stats_html.append("<h4>Overall Statistics</h4>")
        stats_html.append(f"<p>Total data points: {len(df_filtered)}</p>")
        stats_html.append(f"<p>Models: {', '.join(df_filtered['model'].unique())}</p>")
        stats_html.append(f"<p>Executables: {', '.join(df_filtered['executable'].unique())}</p>")

        # Format run display names
        run_display_names = []
        for run_id in df_filtered['run_id'].unique():
            for _, row in df_filtered[df_filtered['run_id'] == run_id].iterrows():
                run_display_names.append(self.format_run_display_name(run_id, row['run_date']))
                break
        stats_html.append(f"<p>Runs: {', '.join(run_display_names)}</p>")

        # Performance statistics
        stats_html.append("<h4>Performance Statistics</h4>")
        max_rate = df_filtered[metric].max()
        min_rate = df_filtered[metric].min()
        mean_rate = df_filtered[metric].mean()

        stats_html.append(f"<p>Maximum {metric.replace('_', ' ')}: {max_rate:.2e} particles/sec</p>")
        stats_html.append(f"<p>Minimum {metric.replace('_', ' ')}: {min_rate:.2e} particles/sec</p>")
        stats_html.append(f"<p>Mean {metric.replace('_', ' ')}: {mean_rate:.2e} particles/sec</p>")

        # Best performing configuration
        best_config = df_filtered.loc[df_filtered[metric].idxmax()]
        stats_html.append("<h4>Best Performance</h4>")
        stats_html.append(f"<p>Model: {best_config['model']}</p>")
        stats_html.append(f"<p>Executable: {best_config['executable']}</p>")
        stats_html.append(f"<p>Threads: {best_config['threads']}</p>")
        stats_html.append(f"<p>Rate: {best_config[metric]:.2e} particles/sec</p>")

        return "".join(stats_html)

    def generate_data_table(self, df, metric='active_rate'):
        """Generate data table HTML"""
        if df.empty:
            return "<p>No data available</p>"

        df_filtered = df.dropna(subset=[metric])
        if df_filtered.empty:
            return "<p>No data available for selected metric</p>"

        # Format run display names
        df_display = df_filtered.copy()
        for idx, row in df_display.iterrows():
            df_display.at[idx, 'run_id'] = self.format_run_display_name(row['run_id'], row['run_date'])

        # Round numeric columns
        df_display = df_display.round(2)

        # Generate HTML table
        table_html = ['<table class="data-table">']
        table_html.append('<thead><tr>')
        for col in df_display.columns:
            table_html.append(f'<th>{col.replace("_", " ").title()}</th>')
        table_html.append('</tr></thead>')

        table_html.append('<tbody>')
        for _, row in df_display.iterrows():
            table_html.append('<tr>')
            for value in row:
                table_html.append(f'<td>{value}</td>')
            table_html.append('</tr>')
        table_html.append('</tbody>')
        table_html.append('</table>')

        return "".join(table_html)

    def generate_html(self):
        """Generate complete HTML dashboard"""
        # Load data
        df = self.load_data()

        # Generate charts
        scaling_html, speedup_html, comparison_html = self.generate_charts(df)

        # Generate summary and table
        summary_html = self.generate_summary_stats(df)
        table_html = self.generate_data_table(df)

        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)

        # Copy assets
        if os.path.exists("assets"):
            import shutil
            shutil.copytree("assets", os.path.join(self.output_dir, "assets"), dirs_exist_ok=True)

        # Generate HTML
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>XDG Benchmarking Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <link rel="stylesheet" href="assets/dashboard.css">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
</head>
<body>
    <div class="dashboard-container">
        <!-- Header -->
        <div class="dashboard-header">
            <div class="header-left">
                <img src="assets/xdg-logo.png" alt="XDG Logo" class="xdg-logo">
                <div class="header-text">
                    <h1 class="dashboard-title">XDG Benchmarking Dashboard</h1>
                    <p class="dashboard-subtitle">Accelerated Discretized Geometry Performance Analysis</p>
                </div>
            </div>
            <div class="header-controls">
                <div class="last-updated">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            </div>
        </div>

        <!-- Charts -->
        <div class="charts-row">
            <div class="chart-section">
                <h3 class="chart-title">Performance Scaling</h3>
                <div class="chart-container">
                    {scaling_html}
                </div>
            </div>

            <div class="chart-section">
                <h3 class="chart-title">Speedup Analysis</h3>
                <div class="chart-container">
                    {speedup_html}
                </div>
            </div>
        </div>

        <div class="charts-row">
            <div class="chart-section">
                <h3 class="chart-title">Executable Comparison</h3>
                <div class="chart-container">
                    {comparison_html}
                </div>
            </div>

            <div class="chart-section">
                <h3 class="chart-title">Summary Statistics</h3>
                <div class="summary-container">
                    {summary_html}
                </div>
            </div>
        </div>

        <!-- Data Table -->
        <div class="table-section">
            <h3 class="chart-title">Raw Data</h3>
            <div class="table-container">
                {table_html}
            </div>
        </div>
    </div>
</body>
</html>
"""

        # Write HTML file
        with open(os.path.join(self.output_dir, "index.html"), 'w') as f:
            f.write(html_content)

        print(f"Static dashboard generated in {self.output_dir}/index.html")
        print("You can now push this to GitHub and enable GitHub Pages!")

if __name__ == "__main__":
    generator = StaticDashboardGenerator()
    generator.generate_html()