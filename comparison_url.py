"""Read and write portable comparison links without depending on Dash."""

from urllib.parse import parse_qsl, urlencode


METRICS = {"active": "Active rate", "inactive": "Inactive rate"}
COMPARISON_PARAMETERS = {"run", "model", "exe", "metric"}


def parse_comparison_query(search):
    """None means unspecified; an explicit blank run/exe means select nothing."""
    settings = {"runs": None, "model": None, "executables": None, "metric": None}
    notices = []
    try:
        pairs = parse_qsl((search or "").lstrip("?"), keep_blank_values=True,
                          errors="strict", max_num_fields=2048)
    except (ValueError, UnicodeError):
        settings["runs"] = []
        return settings, ["This comparison link could not be read. Please select runs below."]

    for key, destination in (("run", "runs"), ("exe", "executables")):
        values = [value for name, value in pairs if name == key]
        if values:
            settings[destination] = list(dict.fromkeys(value for value in values if value))

    for key in ("model", "metric"):
        values = [value for name, value in pairs if name == key]
        if len(values) > 1:
            notices.append(f"The link specifies more than one {key}; the default is shown.")
        elif values and values[0]:
            settings[key] = values[0]

    if settings["metric"] is not None:
        metric = METRICS.get(settings["metric"])
        if metric is None:
            notices.append(f"Unknown metric '{settings['metric']}'; active rate is shown.")
            metric = METRICS["active"]
        settings["metric"] = metric
    return settings, notices


def build_comparison_query(runs, model, executables, metric, existing_search=""):
    """Canonical repeated parameters support tags containing punctuation/Unicode."""
    try:
        pairs = [(key, value) for key, value in parse_qsl(
            (existing_search or "").lstrip("?"), keep_blank_values=True,
            errors="strict", max_num_fields=2048,
        ) if key not in COMPARISON_PARAMETERS]
    except (ValueError, UnicodeError):
        pairs = []
    pairs += [("run", run_id) for run_id in sorted(set(runs or []))] or [("run", "")]
    pairs.append(("model", model or ""))
    pairs += [("exe", executable) for executable in sorted(set(executables or []))] or [("exe", "")]
    pairs.append(("metric", next((key for key, value in METRICS.items() if value == metric), "active")))
    return "?" + urlencode(pairs)
