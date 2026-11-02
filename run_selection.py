"""Run discovery and selection, independent of the plotted comparison."""

import pandas as pd


PROPERTY_FILTERS = [
    ("config-filter", "Config_File", "Configuration"),
    ("particles-filter", "Particles_Per_Thread", "Particles / thread"),
    ("maxthreads-filter", "Config_Max_Threads", "Max threads"),
    ("machine-filter", "Machine", "Machine"),
    ("os-filter", "OS", "Operating system"),
    ("python-filter", "Python_Version", "Python version"),
]


def build_run_records(dataframe):
    """One searchable record per run, newest first, with stable row IDs."""
    if dataframe.empty:
        return []
    records = []
    ordered = dataframe.sort_values(
        ["Run_Date_Parsed", "Run_ID"], ascending=False, na_position="last"
    )
    for run_id, group in ordered.groupby("Run_ID", sort=False):
        row = group.iloc[0]
        date = row["Run_Date_Parsed"]
        record = {
            "id": run_id,
            "Run_ID": run_id,
            "Date": date.strftime("%b %d, %Y %H:%M") if pd.notna(date) else str(row["Run_Date"]),
            "Date_ISO": date.strftime("%Y-%m-%d") if pd.notna(date) else "",
            "Models": ", ".join(sorted(group["Model"].unique())),
            "Executables": ", ".join(sorted(group["Executable"].unique())),
        }
        for _, column, _ in PROPERTY_FILTERS:
            value = row.get(column)
            record[column] = None if pd.isna(value) else value.item() if hasattr(value, "item") else value
        records.append(record)
    return records


def find_runs(records, search="", start_date=None, end_date=None, properties=()):
    """Match all search words across metadata; empty property filters mean All."""
    words = (search or "").casefold().split()
    matches = []
    for record in records:
        date = record["Date_ISO"]
        if start_date and (not date or date < str(start_date)[:10]):
            continue
        if end_date and (not date or date > str(end_date)[:10]):
            continue
        if any(values and record[column] not in values
               for (_, column, _), values in zip(PROPERTY_FILTERS, properties)):
            continue
        searchable = " ".join(str(value) for value in record.values() if value is not None).casefold()
        if all(word in searchable for word in words):
            matches.append(record)
    return matches


def select_runs(action, selected, checked, previous_rows, matching_rows, all_rows, remove_id=None,
                retain_missing=False):
    """Retain hidden selections, and never interpret an empty selection as All."""
    selection = set(selected or [])
    if action == "run-table":
        selection.difference_update(row["id"] for row in (previous_rows or []))
        selection.update(checked or [])
    elif action == "select-matching":
        selection.update(row["id"] for row in matching_rows)
    elif action == "clear-selection":
        selection.clear()
    elif action == "remove-run":
        selection.discard(remove_id)
    available = [row["id"] for row in all_rows if row["id"] in selection]
    # Linked tags remain part of the intended comparison while a refresh is
    # pending, or if the current snapshot no longer contains a requested run.
    if retain_missing:
        available += sorted(selection.difference(row["id"] for row in all_rows))
    return available
