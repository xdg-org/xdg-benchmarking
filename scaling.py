from argparse import ArgumentParser, BooleanOptionalAction
from pathlib import Path
import markdown
import json


import openmc
import numpy as np
from matplotlib import pyplot as plt
from plotly.subplots import make_subplots
import configparser
import plotly.graph_objects as go
from datetime import datetime
import csv
import os


# Using this config parser to preserve case sensitivity
class MyConfigParser(configparser.ConfigParser):

    def __init__(self, *args, **kwargs):
        super(MyConfigParser, self).__init__(*args, **kwargs)
        self.optionxform = str


def json_obj_hook(dct):
    for k, v in dct.items():
        if isinstance(v, list):
            dct[k] = np.asarray(v)
    return dct
class NumpyArrayEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


def gather_scaling_data(model_name, openmc_exe, config, results_dir):
    max_threads = config.getint('options', 'max_threads')
    if openmc_exe in config['exec_max_threads']:
        max_threads = min(config.getint('exec_max_threads', openmc_exe), max_threads)

    input_path = config['models'][model_name]

    # data storage
    threads = np.array(range(0, max_threads, 5))
    inactive_particles = np.zeros(len(threads), dtype=int)
    active_particles = np.zeros(len(threads), dtype=int)
    inactive_time = np.zeros(len(threads), dtype=float)
    active_time = np.zeros(len(threads), dtype=float)


    executable = config['executables'][openmc_exe]

    for i, n_threads in enumerate(threads):
        n_threads = max(1, n_threads)

        openmc.reset_auto_ids()
        try:
            model = openmc.Model.from_model_xml(input_path + '/model.xml')
        except:
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

        results = {}

        particles_per_thread = config.getint('options', 'particles_per_thread')
        output = config.getboolean('options', 'output')

        print(f'Running {openmc_exe} with {n_threads} threads')
        threads[i] = n_threads
        n_runs = config.getint('options', 'n_repeats')
        for _ in range(n_runs):
            try:
                statepoint = model.run(openmc_exec=executable, threads=n_threads, particles=particles_per_thread*n_threads, output=output, event_based=True)
            except Exception as e:
                print(f'Error running {openmc_exe} for model {Path(input_path) / 'model.xml'} with {n_threads} threads: {e}')
                raise e

            with openmc.StatePoint(statepoint, autolink=False) as sp:
                if sp.run_mode == 'eigenvalue':
                    inactive_particles[i] = sp.n_inactive * sp.n_particles
                    inactive_time[i] += sp.runtime['inactive batches']
                    inactive_batches = sp.n_inactive
                else:
                    inactive_particles[i] = 0
                    inactive_batches = 0
                active_particles[i] = sp.n_particles* (sp.n_batches - inactive_batches)
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


def generate_model_figure(model_name, results):
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=('Flux vs Energy', 'Inactive Rate Scaling', 'Active Rate Scaling'),
        specs=[[{"colspan": 2}, None], [{}, {}], [{"colspan": 2, "type": "table"}, None]]
    )
    fig.update_xaxes(title_text='Energy (eV)', row=1, col=1)
    fig.update_yaxes(title_text='Flux', row=1, col=1)
    fig.update_xaxes(title_text='Threads', row=2, col=1)
    fig.update_yaxes(title_text='Particles per second', row=2, col=1)
    fig.update_xaxes(title_text='Threads', row=2, col=2)
    fig.update_yaxes(title_text='Particles per second', row=2, col=2)
    fig.update_layout(
        xaxis=dict(showgrid=True, type='log'),
        yaxis=dict(showgrid=True, type='log'),
        xaxis2=dict(showgrid=True),
        yaxis2=dict(showgrid=True),
        xaxis3=dict(showgrid=True),
        yaxis3=dict(showgrid=True)
    )

    eigenvalues = []
    for n, r in results.items():
        if r['eigenvalue'] is None:
            r['run_mode'] = 'fixed source'
        else:
            r['run_mode'] = 'eigenvalue'

        print(f'Generating a figure for executable: {n}')
        threads, inactive_rates, active_rates = r['threads'], r['inactive_rates'], r['active_rates']
        if 'flux_values' in r:
            flux_values, energy_divs = r['flux_values'], r['energy_divs']
        eigenvalue = f'{r["eigenvalue"]:0.7f}' if r['eigenvalue'] is not None else 'N/A'
        eigenvalues.append([n, eigenvalue])

        if 'flux_values' in r:
            fig.add_trace(
                go.Scatter(x=energy_divs, y=flux_values, mode='lines+markers', name=f'{n} Flux', line_shape='hv', legendgroup='flux', legendgrouptitle_text="Flux", showlegend=True),
                row=1, col=1
            )

        if r['run_mode'] == 'eigenvalue':
            fig.add_trace(
                go.Scatter(x=threads, y=inactive_rates, mode='lines+markers', name=n, legendgroup='inactive', legendgrouptitle_text="Inactive Rates", showlegend=True),
                row=2, col=1
            )

        fig.add_trace(
            go.Scatter(x=threads, y=active_rates, mode='lines+markers', name=n, legendgroup='active', legendgrouptitle_text="Active Rates", showlegend=True, hovertemplate='%{y:d} particles/s'),

            row=2, col=2
        )

        if r['run_mode'] == 'eigenvalue':
            fig.add_trace(
                go.Table(
                    header=dict(values=['Ray Tracer', 'Eigenvalue']),
                    cells=dict(values=list(zip(*eigenvalues)))
                ),
                row=3, col=1
            )

    fig.update_layout(
        legend=dict(
            x=1,
            y=1,
            tracegroupgap=50,
            groupclick='toggleitem'
        ),
        modebar_add = ['v1hovermode'],
    )

    return fig

def model_results(model_name, config, results_dir):
    execuable_results = {}
    for executable_name in config['executables']:
        execuable_results[executable_name] = gather_scaling_data(model_name, executable_name, config, results_dir)
    return execuable_results


def get_all_results(config_file='scaling_config.i', results_dir=None):
    if not isinstance(config_file, MyConfigParser):
        config = MyConfigParser()
        config.optionxform = str
        config.read(config_file)
    else:
        config = config_file

    all_results = {}
    for model_name in config['models']:
        all_results[model_name] = model_results(model_name, config, results_dir)
    return all_results


def model_figures(config, all_results=None):
    if all_results is None:
        all_results = get_all_results(config)
    figure_dict = {}
    for model_name in config['models']:
        figure_dict[model_name] = generate_model_figure(model_name, all_results[model_name])
    return figure_dict


def get_config(config_file='scaling_config.i'):
    config = MyConfigParser()
    config.read(config_file)
    return config

def model_flux_figure(model_name, config, all_results):
    fig = make_subplots(rows=1, cols=1, subplot_titles=(f'{model_name} Flux'))

    fig.update_xaxes(title_text='Energy (eV)', row=1, col=1)
    fig.update_yaxes(title_text='Flux', row=1, col=1)
    fig.update_layout(
        xaxis=dict(showgrid=True, type='log'),
        yaxis=dict(showgrid=True, type='log')
    )

    results = all_results[model_name]
    for executable_name, exec_results in results.items():
        if 'flux_values' not in exec_results:
            continue
        energy_divs = exec_results['energy_divs']
        flux_values = exec_results['flux_values']

        fig.add_trace(
            go.Scatter(x=energy_divs, y=flux_values, mode='lines+markers', name=executable_name, line_shape='hv'),
            row=1, col=1
        )

    return fig

def flux_figures(config, all_results=None):
    if all_results is None:
        all_results = get_all_results(config)
    figure_dict = {}
    for model_name in config['models']:
        figure_dict[model_name] = model_flux_figure(model_name, config, all_results)
    return figure_dict

def model_html(config_file='scaling_config.i', results_dir=None):
    config = get_config(config_file)
    all_results = get_all_results(config, results_dir)
    figure_dict = model_figures(config, all_results)
    dashboard_files = {}

    # Create dashboards directory in results_dir if specified
    dashboards_dir = results_dir / 'dashboards'
    dashboards_dir.mkdir(exist_ok=True)

    for title, fig in figure_dict.items():
        filename = dashboards_dir / f"{title.replace(' ', '_').lower()}.html"
        fig.write_html(str(filename), full_html=True, include_plotlyjs="cdn")
        dashboard_files[title] = str(filename)

    for model_name, model_path in config['models'].items():
        description_file = Path(model_path) / "description.md"
        print( f"Processing description for {model_name} from {description_file}")
        description_filename = None
        if description_file.exists():
            with open(description_file, 'r') as desc:
                description_content = desc.read()
                html = markdown.markdown(description_content)
            description_filename = dashboards_dir / f"{model_name.replace(' ', '_').lower()}_description.html"
            with open(description_filename, 'w', encoding="utf-8", errors="xmlcharrefreplace") as desc_html_file:
                desc_html_file.write(html)
        dashboard_files[model_name] = (dashboard_files[model_name], str(description_filename))

    # Create index.html in results directory if specified
    index_html = results_dir / "index.html"
    with open(index_html, 'w') as f:
        f.write("<!DOCTYPE html>\n<html>\n<head>\n")
        f.write("<title>XDG Benchmarking Results</title>\n")
        f.write("<style>\n")
        f.write("body { font-family: Arial, sans-serif; margin: 40px; }\n")
        f.write("h1 { color: #333; }\n")
        f.write("a { color: #0066cc; text-decoration: none; }\n")
        f.write("a:hover { text-decoration: underline; }\n")
        f.write(".model { margin: 20px 0; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }\n")
        f.write("</style>\n</head>\n<body>\n")
        f.write("<h1>XDG Benchmarking Results</h1>\n")
        f.write(f"<p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>\n")
        f.write(f"<p><strong>Results Directory:</strong> {results_dir}</p>\n\n")

        for model_name, (dashboard_file, desc_file) in dashboard_files.items():
            f.write(f'<div class="model">\n')
            f.write(f'<h2>{model_name}</h2>\n')
            f.write(f'<p><a href="{dashboard_file}">View Dashboard</a></p>\n')
            if desc_file:
                f.write(f'<p><a href="{desc_file}">View Description</a></p>\n')
            f.write(f'</div>\n')

        f.write("</body>\n</html>")
    print(f"Index file written to: {index_html}")

    return dashboard_files


def get_results_dir(config, custom_name=None):
    base_dir = config['options'].get('results_dir', 'results') if 'options' in config and 'results_dir' in config['options'] else 'results'
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if custom_name:
        results_dir = Path(base_dir) / f"{timestamp}_{custom_name}"
    else:
        results_dir = Path(base_dir) / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir


def write_run_summary(results_dir, config, args):
    """Write a summary file with run information to the results directory."""
    summary_file = results_dir / "run_summary.txt"
    with open(summary_file, 'w') as f:
        f.write(f"XDG Benchmarking Run Summary\n")
        f.write(f"============================\n\n")
        f.write(f"Run Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Results Directory: {results_dir}\n\n")

        f.write(f"Configuration:\n")
        f.write(f"  Config File: {args.config}\n")
        if args.results_name:
            f.write(f"  Custom Results Name: {args.results_name}\n")
        f.write(f"\n")

        f.write(f"Models:\n")
        for model_name, model_path in config['models'].items():
            f.write(f"  {model_name}: {model_path}\n")
        f.write(f"\n")

        f.write(f"Executables:\n")
        for exec_name, exec_path in config['executables'].items():
            f.write(f"  {exec_name}: {exec_path}\n")
        f.write(f"\n")

        f.write(f"Options:\n")
        for option, value in config['options'].items():
            f.write(f"  {option}: {value}\n")

    print(f"Run summary written to: {summary_file}")


def write_results_readme(results_dir):
    """Write a README file explaining the results directory structure."""
    readme_file = results_dir / "README.md"
    with open(readme_file, 'w') as f:
        f.write("# XDG Benchmarking Results\n\n")
        f.write("This directory contains the results from an XDG benchmarking run.\n\n")
        f.write("## Directory Structure\n\n")
        f.write("- `index.html` - Main results page with links to all dashboards\n")
        f.write("- `run_summary.txt` - Detailed summary of the run configuration and parameters\n")
        f.write("- `README.md` - This file\n")
        f.write("- `dashboards/` - Interactive HTML dashboards for each model\n")
        f.write("  - `{model_name}.html` - Main dashboard for each model\n")
        f.write("  - `{model_name}_description.html` - Model description (if available)\n")
        f.write("- `{model_name}_dashboard.html` - Individual model dashboards\n")
        f.write("- `{model_name}_{executable}_scaling.csv` - CSV files with scaling data\n\n")
        f.write("## Viewing Results\n\n")
        f.write("1. Open `index.html` in a web browser to see all results\n")
        f.write("2. Or open individual dashboard files directly\n")
        f.write("3. Check `run_summary.txt` for detailed run information\n\n")
        f.write("## Files\n\n")
        f.write("- **CSV files**: Scaling data in comma-separated format\n")
        f.write("- **Dashboard files**: Interactive Plotly charts showing scaling performance\n")
        f.write("- **Description files**: Markdown descriptions of each model (if available)\n")

    print(f"README written to: {readme_file}")


def write_csv_results(model_name, results, results_dir):
    """Write CSV files for scaling results to the results directory."""

    for executable_name, exec_results in results.items():
        if 'threads' in exec_results and 'active_rates' in exec_results:
            csv_file = results_dir / f"{model_name}_{executable_name}_scaling.csv"

            with open(csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['# Threads', 'Inactive rate', 'Active rate'])

                threads = exec_results['threads']
                active_rates = exec_results['active_rates']

                # Handle inactive rates - they might not exist for fixed source runs
                if 'inactive_rates' in exec_results:
                    inactive_rates = exec_results['inactive_rates']
                else:
                    inactive_rates = np.zeros_like(active_rates)

                for i, thread in enumerate(threads):
                    writer.writerow([
                        f"{thread:.15e}",
                        f"{inactive_rates[i]:.15e}",
                        f"{active_rates[i]:.15e}"
                    ])

            print(f"CSV results written to: {csv_file}")


def main():
    ap = ArgumentParser()

    ap.add_argument('--config', type=str, help='Path to configuration file', default='scaling_config.i')
    ap.add_argument('--results-name', type=str, help='Custom name for results directory (will be appended to timestamp)', default=None)

    args = ap.parse_args()

    config = MyConfigParser()
    config.read(args.config)

    # Use get_results_dir to determine results_dir - CALL ONLY ONCE
    results_dir = get_results_dir(config, args.results_name)
    print(f"Writing results to: {results_dir}")

    # Write run summary
    write_run_summary(results_dir, config, args)

    # Write README
    write_results_readme(results_dir)

    print(f"Models: {config['models']}")
    print(f"OpenMC Executables: {config['executables']}")

    fig = make_subplots(rows=len(config['models']), cols=2, subplot_titles=('Inactive Rate Scaling', 'Active Rate Scaling'))
    fig.update_xaxes(title_text='Threads', row=1, col=1)
    fig.update_yaxes(title_text='Particles per second', row=1, col=1)
    fig.update_xaxes(title_text='Threads', row=1, col=2)
    fig.update_yaxes(title_text='Particles per second', row=1, col=2)
    fig.update_layout(
        xaxis=dict(showgrid=True),
        yaxis=dict(showgrid=True),
        xaxis2=dict(showgrid=True),
        yaxis2=dict(showgrid=True)
    )

    config = get_config(args.config)
    results = get_all_results(config, results_dir)
    figure_dict = model_figures(config, results)

    for i, (model_name, input_path) in enumerate(config['models'].items()):
        fig.update_yaxes(title_text=model_name, row=i+1, col=1)
        fig.update_yaxes(title_text=model_name, row=i+1, col=2)

    for model_name, fig in figure_dict.items():
        dashboard_file = results_dir / f'{model_name}_dashboard.html'
        fig.write_html(str(dashboard_file))
        print(f"Dashboard written to: {dashboard_file}")

    # Generate comprehensive dashboards
    print("Generating comprehensive dashboards...")
    dashboard_files = model_html(args.config, results_dir)
    print("All results generated successfully!")

    # Write CSV results
    for model_name, model_results_data in results.items():
        write_csv_results(model_name, model_results_data, results_dir)


if __name__ == '__main__':
    main()
