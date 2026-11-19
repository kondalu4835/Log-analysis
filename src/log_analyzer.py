import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT_DIR
DEFAULT_REPORT_DIR = ROOT_DIR / "reports"
DEFAULT_CHART_DIR = ROOT_DIR / "charts"
BASELINE_START = pd.Timestamp("2026-11-18T09:00:00Z")
BASELINE_END = pd.Timestamp("2026-11-18T10:00:00Z")

REQUIRED_COLUMNS = {
    "requests": {
        "timestamp",
        "trace_id",
        "region",
        "endpoint",
        "status",
        "latency_ms",
        "error_code",
    },
    "application_logs": {
        "timestamp",
        "trace_id",
        "service",
        "level",
        "http_status",
        "error_code",
    },
    "metrics": {"timestamp", "region", "service", "metric", "value", "unit"},
}


def load_data(data_dir=DEFAULT_DATA_DIR):
    """Load the three source CSVs and normalize timestamps and numeric fields."""
    data_dir = Path(data_dir)
    filenames = {
        "requests": "requests.csv",
        "application_logs": "application_logs.csv",
        "metrics": "metrics.csv",
    }
    data = {}

    for key, filename in filenames.items():
        path = data_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required input file not found: {path}")
        frame = pd.read_csv(path)
        missing_columns = REQUIRED_COLUMNS[key] - set(frame.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"{path} is missing required columns: {missing}")
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"], utc=True, errors="coerce"
        )
        data[key] = frame

    data["requests"]["status"] = pd.to_numeric(
        data["requests"]["status"], errors="coerce"
    )
    data["requests"]["latency_ms"] = pd.to_numeric(
        data["requests"]["latency_ms"], errors="coerce"
    )
    data["application_logs"]["http_status"] = pd.to_numeric(
        data["application_logs"]["http_status"], errors="coerce"
    )
    data["application_logs"]["latency_ms"] = pd.to_numeric(
        data["application_logs"]["latency_ms"], errors="coerce"
    )
    data["metrics"]["value"] = pd.to_numeric(
        data["metrics"]["value"], errors="coerce"
    )
    return data


def validate_data(data):
    """Return data quality counts and warnings without altering the input frames."""
    validation = {}
    for name, required_columns in REQUIRED_COLUMNS.items():
        frame = data[name]
        missing_columns = sorted(required_columns - set(frame.columns))
        if missing_columns:
            raise ValueError(
                f"{name} is missing required columns: {', '.join(missing_columns)}"
            )

        dataset_result = {
            "rows": int(len(frame)),
            "missing_timestamps": int(frame["timestamp"].isna().sum()),
        }
        if name == "requests":
            statuses = frame["status"]
            dataset_result.update(
                {
                    "invalid_statuses": int(
                        (statuses.isna() | ~statuses.between(100, 599)).sum()
                    ),
                    "missing_trace_ids": int(frame["trace_id"].isna().sum()),
                    "duplicate_trace_ids": int(
                        frame["trace_id"].duplicated(keep=False).sum()
                    ),
                }
            )
        validation[name] = dataset_result
    return validation


def _deduplicate_requests(requests):
    """Collapse exact duplicate requests and reject conflicting trace records."""
    if "trace_id" not in requests.columns:
        raise ValueError("requests is missing required column: trace_id")

    identified_requests = requests.loc[requests["trace_id"].notna()]
    duplicate_rows = identified_requests.loc[
        identified_requests["trace_fzid"].duplicated(keep=False)
    ]
    if not duplicate_rows.empty:
        for trace_id, rows in duplicate_rows.groupby("trace_id", sort=False):
            if len(rows.drop_duplicates()) > 1:
                raise ValueError(
                    f"Conflicting request records found for trace_id {trace_id!r}."
                )

    duplicate_indices = identified_requests.index[
        identified_requests["trace_id"].duplicated(keep="first")
    ]
    return requests.drop(index=duplicate_indices)


def analyze_http_status(requests):
    """Summarize request-level HTTP codes and calculate the 5xx failure rate."""
    requests = _deduplicate_requests(requests)
    total_requests = int(len(requests))
    statuses = requests["status"]
    failed_requests = int(statuses.between(500, 599).sum())
    failure_percentage = (
        100.0 * failed_requests / total_requests if total_requests else 0.0
    )
    status_counts = (
        requests.groupby("status", dropna=False)
        .size()
        .rename("request_count")
        .reset_index()
    )
    status_counts["percentage"] = (
        status_counts["request_count"] * 100.0 / total_requests
        if total_requests
        else 0.0
    )
    return {
        "total_requests": total_requests,
        "failed_requests": failed_requests,
        "failure_percentage": failure_percentage,
        "status_counts": status_counts,
    }


def analyze_error_codes(application_logs):
    """Count application log errors by service and distinct affected traces."""
    errors = application_logs.loc[
        application_logs["error_code"].notna()
        & application_logs["error_code"].astype(str).str.strip().ne("")
    ]
    return (
        errors.groupby(["service", "error_code"], dropna=False)
        .agg(
            log_events=("trace_id", "size"),
            affected_requests=("trace_id", "nunique"),
        )
        .reset_index()
        .sort_values(["log_events", "service"], ascending=[False, True])
    )


def analyze_services(application_logs):
    """Summarize service log volume, error events, and unique affected traces."""
    logs = application_logs.copy()
    logs["_is_error_level"] = logs["level"].astype(str).str.upper().eq("ERROR")
    logs["_has_error_code"] = (
        logs["error_code"].notna()
        & logs["error_code"].astype(str).str.strip().ne("")
    )
    logs["_is_http_error"] = logs["http_status"].between(400, 599)
    logs["_error_trace_id"] = logs["trace_id"].where(logs["_has_error_code"])

    return (
        logs.groupby("service", dropna=False)
        .agg(
            log_events=("trace_id", "size"),
            error_level_events=("_is_error_level", "sum"),
            error_code_events=("_has_error_code", "sum"),
            http_error_events=("_is_http_error", "sum"),
            affected_error_traces=("_error_trace_id", "nunique"),
        )
        .reset_index()
        .sort_values(["error_level_events", "error_code_events"], ascending=False)
    )


def analyze_service_errors(application_logs):
    """Group ERROR records and correlate gateway errors with earlier service errors."""
    errors = application_logs.loc[
        application_logs["level"].astype(str).str.upper().eq("ERROR")
    ].copy()
    grouping_columns = ["service", "region", "event", "level", "error_code"]
    grouped_errors = (
        errors.groupby(grouping_columns, dropna=False)
        .agg(
            error_events=("trace_id", "size"),
            affected_traces=("trace_id", "nunique"),
        )
        .reset_index()
        .sort_values(["error_events", "service"], ascending=[False, True])
    )
    service_summary = (
        errors.groupby("service", dropna=False)
        .agg(
            error_events=("trace_id", "size"),
            affected_traces=("trace_id", "nunique"),
        )
        .reset_index()
        .sort_values(["error_events", "service"], ascending=[False, True])
    )
    heatmap = errors.pivot_table(
        index="service",
        columns="region",
        values="trace_id",
        aggfunc="nunique",
        fill_value=0,
    )
    heatmap = heatmap.astype(int)

    error_codes = (
        errors.groupby("error_code", dropna=False)
        .agg(
            error_log_events=("trace_id", "size"),
            affected_traces=("trace_id", "nunique"),
            services=("service", lambda values: ", ".join(sorted(set(values)))),
            events=("event", lambda values: ", ".join(sorted(set(values)))),
        )
        .reset_index()
        .sort_values(
            ["affected_traces", "error_log_events", "error_code"],
            ascending=[False, False, True],
        )
    )

    gateway_errors = errors.loc[
        errors["service"].eq("api-gateway")
        & errors["trace_id"].notna()
        & errors["error_code"].notna(),
        ["trace_id", "error_code", "timestamp"],
    ].drop_duplicates()
    source_errors = errors.loc[
        ~errors["service"].eq("api-gateway")
        & errors["trace_id"].notna()
        & errors["error_code"].notna(),
        ["trace_id", "error_code", "service", "event", "timestamp"],
    ]
    preceding_matches = gateway_errors.merge(
        source_errors,
        on=["trace_id", "error_code"],
        suffixes=("_gateway", "_source"),
    )
    preceding_matches = preceding_matches.loc[
        preceding_matches["timestamp_source"]
        .le(preceding_matches["timestamp_gateway"])
    ].sort_values(["timestamp_source", "trace_id"])
    first_source_by_trace = preceding_matches.drop_duplicates(
        "trace_id", keep="first"
    )
    source_summary = (
        first_source_by_trace.groupby(["service", "error_code"], dropna=False)
        .agg(
            gateway_error_traces=("trace_id", "nunique"),
            source_events=("event", "size"),
        )
        .reset_index()
        .sort_values(
            ["gateway_error_traces", "service"], ascending=[False, True]
        )
    )

    return {
        "error_events": errors,
        "grouped_errors": grouped_errors,
        "service_summary": service_summary,
        "heatmap": heatmap,
        "error_codes": error_codes,
        "gateway_error_traces": int(gateway_errors["trace_id"].nunique()),
        "gateway_traces_with_prior_service_error": int(
            first_source_by_trace["trace_id"].nunique()
        ),
        "source_summary": source_summary,
        "unique_error_traces": int(errors["trace_id"].nunique()),
    }


def create_service_region_heatmap(service_errors, chart_dir=DEFAULT_CHART_DIR):
    """Save distinct ERROR trace counts by service and region as a heatmap."""
    chart_dir = Path(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    output_path = chart_dir / "service_region_error_heatmap.png"
    heatmap = service_errors["heatmap"]

    figure_width = max(8, 2.2 + 1.5 * len(heatmap.columns))
    figure_height = max(4, 1.8 + 0.55 * len(heatmap.index))
    fig, axis = plt.subplots(figsize=(figure_width, figure_height))
    image = axis.imshow(heatmap.to_numpy(), cmap="Reds", aspect="auto")
    axis.set_xticks(range(len(heatmap.columns)), labels=heatmap.columns)
    axis.set_yticks(range(len(heatmap.index)), labels=heatmap.index)
    axis.set_xlabel("Region")
    axis.set_ylabel("Microservice")
    axis.set_title("Distinct traces with ERROR logs by service and region")
    for row_index in range(len(heatmap.index)):
        for column_index in range(len(heatmap.columns)):
            value = heatmap.iat[row_index, column_index]
            axis.text(
                column_index,
                row_index,
                str(value),
                ha="center",
                va="center",
                color="white" if value > heatmap.to_numpy().max() / 2 else "black",
            )
    fig.colorbar(image, ax=axis, label="Distinct error traces")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _markdown_table(frame):
    """Format a dataframe as a Markdown table without optional dependencies."""
    if frame.empty:
        return "_No matching records._"
    headers = [str(column) for column in frame.columns]
    rows = [
        [
            str(value).replace("|", "\\|").replace("\n", " ")
            for value in row
        ]
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def write_service_error_report(
    application_logs, service_errors, report_dir=DEFAULT_REPORT_DIR
):
    """Write service error groupings, ranked codes, and trace evidence to Markdown."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    grouped_path = report_dir / "service_error_groups.csv"
    codes_path = report_dir / "ranked_error_codes.csv"
    service_errors["grouped_errors"].to_csv(grouped_path, index=False)
    service_errors["error_codes"].to_csv(codes_path, index=False)

    errors = service_errors["error_events"]
    gateway_count = service_errors["gateway_error_traces"]
    matched_count = service_errors["gateway_traces_with_prior_service_error"]
    service_table = service_errors["service_summary"].copy()
    service_table["error_events"] = service_table["error_events"].astype(int)
    service_table["affected_traces"] = service_table["affected_traces"].astype(int)
    non_gateway_table = service_table.loc[
        service_table["service"].ne("api-gateway")
    ]
    top_non_gateway = (
        non_gateway_table.iloc[0] if not non_gateway_table.empty else None
    )

    source_services = service_errors["source_summary"]
    top_service = service_table.iloc[0] if not service_table.empty else None
    gateway_assessment = (
        f"The gateway has the most ERROR records ({int(top_service['error_events'])} "
        f"events across {int(top_service['affected_traces'])} traces). Of "
        f"{gateway_count} distinct gateway ERROR traces, {matched_count} have an "
        "earlier non-gateway ERROR in the same trace with the same error code. "
        "This indicates the gateway is recording the outward HTTP failure after "
        "a service-level error, rather than originating those matched failures."
        if top_service is not None and top_service["service"] == "api-gateway"
        else "The gateway is not the highest-ERROR-count service in this dataset."
    )
    if top_non_gateway is not None:
        gateway_assessment += (
            f" Excluding the gateway, {top_non_gateway['service']} has the most "
            f"ERROR records ({int(top_non_gateway['error_events'])}); this is "
            "the largest non-gateway count, not proof of the incident's single "
            "root cause."
        )

    report = [
        "# ShopSphere application log service analysis",
        "",
        "This report analyzes `application_logs.csv` records whose `level` is "
        "`ERROR`. It reports both ERROR log events and unique `trace_id` counts. "
        "An error trace can appear under multiple services, so service counts "
        "must not be summed to estimate unique failed requests.",
        "",
        "## Overall counts",
        "",
        f"- Application log records: {len(application_logs):,}",
        f"- ERROR log events: {len(errors):,}",
        f"- Distinct traces containing an ERROR: "
        f"{service_errors['unique_error_traces']:,}",
        f"- Distinct traces with an ERROR at `api-gateway`: {gateway_count:,}",
        "",
        "## ERROR counts by microservice",
        "",
        _markdown_table(service_table),
        "",
        "## Service-versus-region heatmap",
        "",
        "Values are distinct traces with an ERROR for that service and region "
        "(not raw log-event counts). A trace appearing in multiple services is "
        "shown in each relevant service cell, so do not sum across services.",
        "",
        "![Distinct error traces by service and region](../charts/"
        "service_region_error_heatmap.png)",
        "",
        "## Grouping by service, region, event, log level, and error code",
        "",
        "Each row below is one combination of the requested fields. "
        "`affected_traces` de-duplicates repeated records within that combination.",
        "",
        _markdown_table(service_errors["grouped_errors"]),
        "",
        "## Ranked error codes",
        "",
        "Ranked by distinct affected traces, then ERROR log-event count. "
        "A code can have multiple records for the same trace in different services.",
        "",
        _markdown_table(service_errors["error_codes"]),
        "",
        "## Is the highest-count service the source?",
        "",
        gateway_assessment,
        "",
        "Same-trace ordering supports attribution of the gateway response to a "
        "preceding service error; it does not prove a deeper infrastructure or "
        "business-logic root cause. The earliest matching service event is a "
        "proximate emitter in the logs, not necessarily the ultimate cause.",
        "",
        "### Earlier service errors associated with gateway errors",
        "",
        _markdown_table(source_services),
        "",
        f"Supporting tables: [`service_error_groups.csv`](./{grouped_path.name}) "
        f"and [`ranked_error_codes.csv`](./{codes_path.name}).",
    ]
    report_path = report_dir / "service_analysis.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    return report_path


def analyze_checkout_traces(requests, application_logs, error_codes=None):
    """Select real failed checkout requests and retrieve their complete trace logs."""
    requests = _deduplicate_requests(requests)
    checkout_failures = requests.loc[
        requests["endpoint"].astype(str).str.lower().eq("/api/v1/checkout")
        & requests["status"].between(500, 599)
        & requests["trace_id"].notna()
    ].copy()
    if checkout_failures.empty:
        raise ValueError("No failed checkout requests with HTTP 5xx status were found.")

    if error_codes is None:
        selected_requests = checkout_failures.sort_values("timestamp").head(3)
    else:
        selected = []
        for error_code in error_codes:
            matches = checkout_failures.loc[
                checkout_failures["error_code"].eq(error_code)
            ].sort_values("timestamp")
            if matches.empty:
                raise ValueError(
                    f"No failed checkout request found for error code {error_code!r}."
                )
            selected.append(matches.iloc[0])
        selected_requests = pd.DataFrame(selected)

    cases = []
    for _, request in selected_requests.iterrows():
        trace = application_logs.loc[
            application_logs["trace_id"].eq(request["trace_id"])
        ].copy()
        if trace.empty:
            raise ValueError(
                f"No application log records found for trace_id "
                f"{request['trace_id']}."
            )
        trace = trace.sort_values(["timestamp", "service"], kind="stable")
        trace["latency_ms"] = pd.to_numeric(trace["latency_ms"], errors="coerce")
        trace["http_status"] = pd.to_numeric(
            trace["http_status"], errors="coerce"
        )
        failures = trace.loc[
            trace["level"].astype(str).str.upper().eq("ERROR")
        ].sort_values("timestamp")
        if failures.empty:
            raise ValueError(
                f"Failed checkout trace {request['trace_id']} has no ERROR log event."
            )
        earliest_failure = failures.iloc[0]
        cases.append(
            {
                "request": request,
                "trace": trace,
                "earliest_failure": earliest_failure,
            }
        )
    return cases


def create_checkout_trace_waterfall(cases, chart_dir=DEFAULT_CHART_DIR):
    """Plot logged service spans using each event timestamp and latency."""
    chart_dir = Path(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    output_path = chart_dir / "checkout_trace_waterfall.png"
    row_counts = [len(case["trace"]) for case in cases]
    fig, axes = plt.subplots(
        len(cases),
        1,
        figsize=(14, max(4.5, 1.8 * len(cases) + 0.65 * sum(row_counts))),
        squeeze=False,
    )
    error_color = "#c62828"
    normal_color = "#1976d2"

    for axis, case in zip(axes[:, 0], cases):
        request = case["request"]
        trace = case["trace"]
        request_start = request["timestamp"]
        total_latency = float(request["latency_ms"])
        for row_index, (_, event) in enumerate(trace.iterrows()):
            event_time = event["timestamp"]
            if pd.isna(event_time):
                continue
            start_ms = (event_time - request_start).total_seconds() * 1000.0
            latency_ms = event["latency_ms"]
            width_ms = max(float(latency_ms), 1.0) if pd.notna(latency_ms) else 1.0
            is_error = str(event["level"]).upper() == "ERROR"
            color = error_color if is_error else normal_color
            axis.add_patch(
                Rectangle(
                    (start_ms, row_index - 0.28),
                    width_ms,
                    0.56,
                    facecolor=color,
                    edgecolor=color,
                    alpha=0.82,
                )
            )
            label = str(event["service"])
            if is_error:
                label += f" — {event['error_code']}"
            axis.text(
                start_ms + width_ms + max(total_latency * 0.005, 5),
                row_index,
                label,
                va="center",
                fontsize=8,
            )

        axis.set_yticks(range(len(trace)))
        axis.set_yticklabels(trace["service"].astype(str).tolist(), fontsize=8)
        axis.axvline(
            total_latency,
            color="#424242",
            linestyle="--",
            linewidth=1,
            label="Request completion",
        )
        axis.set_xlim(left=0, right=max(total_latency * 1.35, 100))
        axis.set_ylim(len(trace) - 0.5, -0.5)
        axis.set_xlabel("Milliseconds since request timestamp (UTC)")
        axis.grid(axis="x", alpha=0.2)
        axis.set_title(
            f"{request['trace_id']} | {request['error_code']} | "
            f"{request['timestamp'].isoformat()} | "
            f"HTTP {int(request['status'])} ({total_latency:.0f} ms)",
            loc="left",
            fontsize=10,
        )

    fig.legend(
        handles=[
            Patch(facecolor=normal_color, label="Non-error service log"),
            Patch(facecolor=error_color, label="ERROR log"),
        ],
        loc="upper right",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.99))
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output_path


def write_checkout_trace_report(cases, report_dir=DEFAULT_REPORT_DIR):
    """Write request facts, ordered events, and earliest failure evidence."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Failed checkout trace investigation",
        "",
        "The three examples below are actual HTTP 5xx checkout requests selected "
        "from `requests.csv` and joined to all matching records in "
        "`application_logs.csv` by `trace_id`. Records are shown in timestamp "
        "order; logged latency is the event's `latency_ms`, and elapsed time is "
        "relative to the request timestamp.",
        "",
        "![Checkout trace waterfall](../charts/checkout_trace_waterfall.png)",
        "",
    ]

    for index, case in enumerate(cases, start=1):
        request = case["request"]
        trace = case["trace"]
        earliest = case["earliest_failure"]
        service_sequence = " → ".join(trace["service"].astype(str).tolist())
        lines.extend(
            [
                f"## Trace {index}: `{request['trace_id']}`",
                "",
                f"- **Request timestamp (UTC):** {request['timestamp'].isoformat()}",
                f"- **Request:** `{request['method']} {request['endpoint']}`",
                f"- **Region/version:** `{request['region']}` / "
                f"`{request['version']}`",
                f"- **HTTP status and request latency:** "
                f"`{int(request['status'])}` / `{float(request['latency_ms']):.0f} ms`",
                f"- **Request error code:** `{request['error_code']}`",
                f"- **Microservice sequence from log timestamps:** {service_sequence}",
                f"- **Earliest failure evidence:** "
                f"`{earliest['timestamp'].isoformat()}` — "
                f"`{earliest['service']}` / `{earliest['event']}` / "
                f"`{earliest['error_code']}` (HTTP "
                f"`{int(earliest['http_status'])}` if available).",
                "",
                "| Event timestamp (UTC) | Elapsed from request (ms) | Service | Event | Level | Error code | Log latency (ms) | HTTP status |",
                "| --- | ---: | --- | --- | --- | --- | ---: | ---: |",
            ]
        )
        for _, event in trace.iterrows():
            elapsed_ms = (
                (event["timestamp"] - request["timestamp"]).total_seconds() * 1000.0
                if pd.notna(event["timestamp"])
                else float("nan")
            )
            event_latency = (
                f"{float(event['latency_ms']):.0f}"
                if pd.notna(event["latency_ms"])
                else "—"
            )
            http_status = (
                str(int(event["http_status"]))
                if pd.notna(event["http_status"])
                else "—"
            )
            error_code = (
                str(event["error_code"])
                if pd.notna(event["error_code"])
                and str(event["error_code"]).strip()
                else "—"
            )
            event_timestamp = (
                event["timestamp"].isoformat()
                if pd.notna(event["timestamp"])
                else "—"
            )
            lines.append(
                f"| {event_timestamp} | {elapsed_ms:.1f} | "
                f"{event['service']} | {event['event']} | {event['level']} | "
                f"{error_code} | {event_latency} | {http_status} |"
            )
        lines.extend(["", ""])

    lines.extend(
        [
            "## Interpretation",
            "",
            "For each trace, the earliest timestamped `ERROR` log is the first "
            "direct failure evidence in the available application logs. Later "
            "gateway `http.response` records report the resulting HTTP failure "
            "and should not be mistaken for an earlier originating event. "
            "Trace ordering identifies the earliest observed service-side "
            "failure, but does not by itself establish the underlying root cause.",
        ]
    )
    report_path = report_dir / "checkout_traces.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def analyze_latency(requests):
    """Summarize request-level API response latency overall and by endpoint."""
    requests = _deduplicate_requests(requests)
    valid_latency = requests.loc[requests["latency_ms"].notna()]
    values = valid_latency["latency_ms"]
    overall = pd.DataFrame(
        [
            {
                "request_count": int(len(values)),
                "mean_ms": float(values.mean()) if len(values) else None,
                "median_ms": float(values.quantile(0.50)) if len(values) else None,
                "p95_ms": float(values.quantile(0.95)) if len(values) else None,
                "p99_ms": float(values.quantile(0.99)) if len(values) else None,
                "max_ms": float(values.max()) if len(values) else None,
            }
        ]
    )
    by_endpoint = (
        valid_latency.groupby("endpoint", dropna=False)
        .agg(
            request_count=("latency_ms", "size"),
            mean_ms=("latency_ms", "mean"),
            median_ms=("latency_ms", "median"),
            p95_ms=("latency_ms", lambda column: column.quantile(0.95)),
            p99_ms=("latency_ms", lambda column: column.quantile(0.99)),
            max_ms=("latency_ms", "max"),
        )
        .reset_index()
        .sort_values("p95_ms", ascending=False)
    )
    return {"overall": overall, "by_endpoint": by_endpoint}


def analyze_time_windows(requests, metrics, interval="5min"):
    """Aggregate request outcomes into UTC windows and join matching metrics."""
    requests = _deduplicate_requests(requests)
    request_windows = requests.loc[requests["timestamp"].notna()].copy()
    request_windows["timestamp"] = request_windows["timestamp"].dt.floor(interval)
    request_windows["_is_5xx"] = request_windows["status"].between(500, 599)
    request_summary = (
        request_windows.groupby(["timestamp", "region"], dropna=False)
        .agg(
            request_count=("trace_id", "size"),
            failed_requests=("_is_5xx", "sum"),
        )
        .reset_index()
    )
    request_summary["failure_percentage"] = (
        request_summary["failed_requests"]
        * 100.0
        / request_summary["request_count"]
    )

    metric_windows = metrics.loc[metrics["timestamp"].notna()].copy()
    metric_windows["timestamp"] = metric_windows["timestamp"].dt.floor(interval)
    metric_summary = metric_windows.pivot_table(
        index=["timestamp", "region"],
        columns="metric",
        values="value",
        aggfunc="mean",
    ).reset_index()
    metric_summary.columns.name = None
    return request_summary.merge(
        metric_summary, on=["timestamp", "region"], how="left"
    ).sort_values(["timestamp", "region"])


def analyze_metric_correlations(requests, application_logs, metrics, interval="5min"):
    """Align request, service-event, and infrastructure data by UTC interval and region."""
    requests = _deduplicate_requests(requests)
    request_rows = requests.loc[
        requests["timestamp"].notna() & requests["trace_id"].notna()
    ].copy()
    request_rows["timestamp"] = request_rows["timestamp"].dt.floor(interval)
    request_rows["_is_5xx"] = request_rows["status"].between(500, 599)
    for code, column in (
        ("DB_POOL_EXHAUSTED", "_request_db_pool_exhausted"),
        ("PAYMENT_PROVIDER_TIMEOUT", "_request_payment_timeout"),
    ):
        request_rows[column] = (
            request_rows["error_code"].eq(code) & request_rows["_is_5xx"]
        )
    request_summary = (
        request_rows.groupby(["timestamp", "region"], dropna=False)
        .agg(
            request_count=("trace_id", "nunique"),
            request_5xx=("_is_5xx", "sum"),
            request_db_pool_exhausted=("_request_db_pool_exhausted", "sum"),
            request_payment_timeouts=("_request_payment_timeout", "sum"),
        )
        .reset_index()
    )
    request_summary["request_5xx_pct"] = (
        100.0 * request_summary["request_5xx"] / request_summary["request_count"]
    )

    log_rows = application_logs.loc[
        application_logs["timestamp"].notna()
        & application_logs["trace_id"].notna()
    ].copy()
    log_rows["timestamp"] = log_rows["timestamp"].dt.floor(interval)
    log_rows["_level_upper"] = log_rows["level"].astype(str).str.upper()
    log_rows["_db_pool_error"] = (
        log_rows["service"].eq("order-service")
        & log_rows["error_code"].eq("DB_POOL_EXHAUSTED")
        & log_rows["_level_upper"].eq("ERROR")
    )
    log_rows["_payment_timeout"] = (
        log_rows["service"].eq("payment-service")
        & log_rows["error_code"].eq("PAYMENT_PROVIDER_TIMEOUT")
        & log_rows["_level_upper"].eq("ERROR")
    )
    log_rows["_notification_lag"] = (
        log_rows["service"].eq("notification-worker")
        & log_rows["event"].eq("queue.consumer.lag")
    )
    log_rows["_app_error"] = (
        log_rows["service"].ne("api-gateway")
        & log_rows["_level_upper"].eq("ERROR")
    )
    log_summary = (
        log_rows.groupby(["timestamp", "region"], dropna=False)
        .agg(
            db_pool_error_events=("_db_pool_error", "sum"),
            db_pool_error_traces=(
                "trace_id",
                lambda values: values[
                    log_rows.loc[values.index, "_db_pool_error"]
                ].nunique(),
            ),
            payment_timeout_events=("_payment_timeout", "sum"),
            payment_timeout_traces=(
                "trace_id",
                lambda values: values[
                    log_rows.loc[values.index, "_payment_timeout"]
                ].nunique(),
            ),
            notification_lag_events=("_notification_lag", "sum"),
            notification_lag_traces=(
                "trace_id",
                lambda values: values[
                    log_rows.loc[values.index, "_notification_lag"]
                ].nunique(),
            ),
            app_error_events=("_app_error", "sum"),
            app_error_traces=(
                "trace_id",
                lambda values: values[
                    log_rows.loc[values.index, "_app_error"]
                ].nunique(),
            ),
        )
        .reset_index()
    )

    metric_rows = metrics.loc[metrics["timestamp"].notna()].copy()
    metric_rows["timestamp"] = metric_rows["timestamp"].dt.floor(interval)
    metric_summary = metric_rows.pivot_table(
        index=["timestamp", "region"],
        columns="metric",
        values="value",
        aggfunc="mean",
    ).reset_index()
    metric_summary.columns.name = None

    aligned = metric_summary.merge(
        request_summary, on=["timestamp", "region"], how="left"
    ).merge(log_summary, on=["timestamp", "region"], how="left")
    count_columns = [
        "request_count",
        "request_5xx",
        "request_db_pool_exhausted",
        "request_payment_timeouts",
        "db_pool_error_events",
        "db_pool_error_traces",
        "payment_timeout_events",
        "payment_timeout_traces",
        "notification_lag_events",
        "notification_lag_traces",
        "app_error_events",
        "app_error_traces",
    ]
    aligned[count_columns] = aligned[count_columns].fillna(0).astype(int)
    aligned["request_5xx_pct"] = aligned["request_5xx_pct"].fillna(0.0)
    aligned = aligned.sort_values(["timestamp", "region"]).reset_index(drop=True)

    correlation_pairs = [
        ("db_pool_active", "request_db_pool_exhausted"),
        ("provider_p95_ms", "request_payment_timeouts"),
        ("queue_lag_messages", "notification_lag_traces"),
        ("queue_lag_messages", "request_5xx"),
        ("heap_used_pct", "app_error_traces"),
        ("heap_used_pct", "request_5xx"),
    ]
    correlations = []
    for metric, outcome in correlation_pairs:
        correlation = aligned[metric].corr(aligned[outcome])
        correlations.append(
            {
                "metric": metric,
                "outcome": outcome,
                "pearson_correlation": (
                    float(correlation) if pd.notna(correlation) else None
                ),
                "aligned_region_intervals": int(
                    aligned[[metric, outcome]].dropna().shape[0]
                ),
            }
        )
    return aligned, pd.DataFrame(correlations)


def create_metric_correlation_chart(aligned, chart_dir=DEFAULT_CHART_DIR):
    """Plot each infrastructure metric with its aligned event/request indicator."""
    chart_dir = Path(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    output_path = chart_dir / "metric_correlation_timeline.png"
    metric_specs = [
        (
            "db_pool_active",
            "request_db_pool_exhausted",
            "Order database pool active connections",
            "DB_POOL_EXHAUSTED requests",
        ),
        (
            "provider_p95_ms",
            "request_payment_timeouts",
            "Payment provider p95 latency (ms)",
            "Payment timeout requests",
        ),
        (
            "queue_lag_messages",
            "notification_lag_traces",
            "Notification queue lag (messages)",
            "Queue-lag warning traces",
        ),
        (
            "heap_used_pct",
            "app_error_traces",
            "API gateway heap utilization (%)",
            "Non-gateway application ERROR traces",
        ),
    ]
    regions = sorted(aligned["region"].dropna().unique())
    region_colors = dict(zip(regions, plt.get_cmap("tab10").colors))
    fig, axes = plt.subplots(4, 1, figsize=(15, 15), sharex=True)

    for axis, (metric, outcome, metric_label, outcome_label) in zip(
        axes, metric_specs
    ):
        outcome_axis = axis.twinx()
        for region in regions:
            region_data = aligned.loc[aligned["region"].eq(region)].sort_values(
                "timestamp"
            )
            color = region_colors[region]
            axis.plot(
                region_data["timestamp"],
                region_data[metric],
                color=color,
                linewidth=1.6,
                label=f"{region} metric",
            )
            outcome_axis.plot(
                region_data["timestamp"],
                region_data[outcome],
                color=color,
                linestyle="--",
                marker=".",
                markersize=3,
                linewidth=1,
                alpha=0.8,
                label=f"{region} {outcome_label}",
            )
        axis.set_ylabel(metric_label)
        outcome_axis.set_ylabel(outcome_label)
        axis.grid(axis="y", alpha=0.2)
        handles, labels = axis.get_legend_handles_labels()
        other_handles, other_labels = outcome_axis.get_legend_handles_labels()
        axis.legend(
            handles + other_handles,
            labels + other_labels,
            loc="upper left",
            ncol=3,
            fontsize=7,
        )

    axes[-1].set_xlabel("Five-minute interval start (UTC)")
    fig.suptitle(
        "ShopSphere infrastructure metrics and aligned outcomes by region\n"
        "Solid lines: metric; dashed lines: request or service-event counts",
        y=1.01,
    )
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output_path


def write_metric_correlation_report(
    aligned, correlations, report_dir=DEFAULT_REPORT_DIR
):
    """Save aligned evidence and a cautious correlation analysis in Markdown."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = report_dir / "metric_correlation_evidence.csv"
    aligned.to_csv(evidence_path, index=False)

    evidence_specs = [
        (
            "Database pool",
            "db_pool_active",
            "request_db_pool_exhausted",
            "db_pool_error_traces",
        ),
        (
            "Payment provider",
            "provider_p95_ms",
            "request_payment_timeouts",
            "payment_timeout_traces",
        ),
        (
            "Notification queue",
            "queue_lag_messages",
            "request_5xx",
            "notification_lag_traces",
        ),
        (
            "API gateway heap",
            "heap_used_pct",
            "request_5xx",
            "app_error_traces",
        ),
    ]
    evidence_rows = []
    for label, metric, request_column, log_column in evidence_specs:
        selected = aligned.nlargest(2, metric)
        selected = pd.concat(
            [
                selected,
                aligned.nlargest(2, request_column),
                aligned.nlargest(2, log_column),
            ]
        ).drop_duplicates(["timestamp", "region"])
        for _, row in selected.iterrows():
            evidence_rows.append(
                {
                    "signal": label,
                    "interval_utc": row["timestamp"].isoformat(),
                    "region": row["region"],
                    "metric_value": row[metric],
                    "request_indicator": request_column,
                    "request_indicator_count": row[request_column],
                    "service_log_indicator": log_column,
                    "service_log_trace_count": row[log_column],
                    "all_request_5xx": row["request_5xx"],
                    "application_error_traces": row["app_error_traces"],
                }
            )
    evidence_table = pd.DataFrame(evidence_rows).drop_duplicates(
        ["signal", "interval_utc", "region"]
    )

    correlation_display = correlations.copy()
    correlation_display["pearson_correlation"] = correlation_display[
        "pearson_correlation"
    ].map(lambda value: f"{value:.3f}" if pd.notna(value) else "not defined")

    def format_evidence(value):
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    evidence_table = evidence_table.map(format_evidence)
    report_path = report_dir / "metric_correlation.md"
    report = [
        "# ShopSphere metric correlation investigation",
        "",
        "## Method",
        "",
        "Request, application-log, and metric timestamps were normalized to "
        "five-minute UTC interval starts and joined by both interval and region. "
        "The evidence CSV contains all 144 region-interval joins. Request "
        "failures come from `requests.csv`; service indicators use matching "
        "application events and distinct `trace_id` values. Gateway response "
        "records are excluded from service error-trace counts to avoid counting "
        "the same propagated failure twice.",
        "",
        "The reported Pearson coefficients describe association across "
        "region-interval rows only. They are not causal estimates, do not "
        "control for other conditions, and can be affected by regional or "
        "temporal clustering. A missing / constant signal has no defined "
        "coefficient.",
        "",
        "![Four aligned metric time series](../charts/"
        "metric_correlation_timeline.png)",
        "",
        "## Correlation summary",
        "",
        _markdown_table(correlation_display),
        "",
        "## Evidence table",
        "",
        "Rows show peak metric intervals and intervals with high paired "
        "request/log counts. DB and payment request counts are sourced from "
        "request error codes; service-log trace counts are grouped independently "
        "by service, error code, and interval. A small mismatch at five-minute "
        "boundaries is possible because a request and its log event can fall "
        "into adjacent buckets. Notification queue warnings are WARN events, "
        "not HTTP failures.",
        "",
        _markdown_table(evidence_table),
        "",
        "The full aligned interval dataset is available in "
        f"[`{evidence_path.name}`](./{evidence_path.name}).",
        "",
        "## Findings and limitations",
        "",
        "### Database connections and `DB_POOL_EXHAUSTED`",
        "",
        "Compare `db_pool_active` against `request_db_pool_exhausted` and "
        "`db_pool_error_traces`. `db_pool_active` reaches 30 connections in "
        "`us-east-1` at 11:25, 11:30, and 11:35 UTC; request-level "
        "`DB_POOL_EXHAUSTED` counts in those buckets are 27, 35, and 28. Across "
        "all 144 region-intervals, the Pearson correlation is 0.637. The "
        "311 order-service `DB_POOL_EXHAUSTED` records also report "
        "`pool_active=30` and `pool_max=30`, direct evidence that the pool was "
        "at its application-reported limit when those errors were logged. "
        "Neither this observation nor the correlation explains why connections "
        "were occupied or establishes the initiating cause.",
        "",
        "### Payment provider latency and payment timeouts",
        "",
        "Provider p95 latency and request-level payment timeout counts have "
        "the strongest aligned relationship measured here (Pearson 0.853 "
        "across the 144 region-intervals). At 10:50 UTC in `us-east-1`, "
        "provider p95 reaches 5,804 ms and 21 requests have "
        "`PAYMENT_PROVIDER_TIMEOUT` (23 total 5xx requests). Matching "
        "`payment-service` timeout events are also present. These associations "
        "do not prove whether provider behavior initiated the degradation or "
        "whether another condition contributed to both.",
        "",
        "### Notification queue backlog",
        "",
        "`queue_lag_messages` rises substantially and `notification-worker` "
        "`queue.consumer.lag` WARN traces are present. These indicate delayed "
        "asynchronous work. The queue-lag metric and distinct warning traces "
        "have Pearson correlation 0.602; correlation with request 5xx counts "
        "is only 0.197. The metric's maximum is 6,476 messages in `eu-west-1` "
        "at 11:35 UTC. Queue lag does not itself establish a checkout failure: "
        "the WARN events are distinct from request-level HTTP 5xx records and "
        "may indicate delayed downstream email after order processing.",
        "",
        "### Memory utilization and application failures",
        "",
        "The heap metric's correlation is weaker than payment latency: Pearson "
        "0.228 with non-gateway application ERROR traces and 0.332 with "
        "request 5xx counts. Heap reaches 96% in `us-east-1` from 12:45–12:55, "
        "when the corresponding buckets have only 2–4 HTTP 5xx requests. "
        "Earlier high-failure buckets include 11:45–12:00, before this heap "
        "peak. The timing does not demonstrate that memory utilization caused "
        "the failures; heap/GC telemetry and process-level evidence would be "
        "needed to assess that hypothesis.",
        "",
        "## Causality caveat",
        "",
        "These results establish time-and-region co-occurrence only. Correlated "
        "signals may share a common cause, have a lag, or be unrelated. Confirm "
        "causality with trace/span ordering, database and provider telemetry, "
        "deployment timelines, and controlled follow-up rather than inferring "
        "a root cause from correlation coefficients.",
    ]
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    return report_path, evidence_path


def analyze_error_timeline(requests, interval="5min"):
    """Roll up request outcomes and compare intervals with the 09:00-10:00 UTC baseline."""
    requests = _deduplicate_requests(requests)
    valid_requests = requests.loc[
        requests["timestamp"].notna() & requests["status"].notna()
    ].copy()
    valid_requests["interval_start"] = valid_requests["timestamp"].dt.floor(interval)
    valid_requests["_http_4xx"] = valid_requests["status"].between(400, 499)
    valid_requests["_http_5xx"] = valid_requests["status"].between(500, 599)

    timeline = (
        valid_requests.groupby("interval_start")
        .agg(
            request_count=("trace_id", "size"),
            http_4xx_count=("_http_4xx", "sum"),
            http_5xx_count=("_http_5xx", "sum"),
            p95_latency_ms=("latency_ms", lambda values: values.quantile(0.95)),
        )
        .reset_index()
        .sort_values("interval_start")
    )
    timeline["failure_percentage_5xx"] = (
        timeline["http_5xx_count"] * 100.0 / timeline["request_count"]
    )

    baseline_mask = timeline["interval_start"].between(
        BASELINE_START, BASELINE_END, inclusive="left"
    )
    baseline_intervals = timeline.loc[baseline_mask]
    if baseline_intervals.empty:
        raise ValueError(
            "Cannot calculate the normal baseline: no request intervals exist "
            "between 09:00 and 10:00 UTC on 2026-11-18."
        )

    baseline_failure_percentage = float(
        baseline_intervals["failure_percentage_5xx"].mean()
    )
    baseline_p95_latency_ms = float(baseline_intervals["p95_latency_ms"].median())
    timeline["baseline_failure_percentage_5xx"] = baseline_failure_percentage
    timeline["baseline_p95_latency_ms"] = baseline_p95_latency_ms
    timeline["failure_rate_vs_baseline"] = (
        timeline["failure_percentage_5xx"] / baseline_failure_percentage
        if baseline_failure_percentage
        else float("nan")
    )
    return timeline, {
        "period_start_utc": BASELINE_START.isoformat(),
        "period_end_utc_exclusive": BASELINE_END.isoformat(),
        "interval_count": int(len(baseline_intervals)),
        "mean_failure_percentage_5xx": baseline_failure_percentage,
        "median_interval_p95_latency_ms": baseline_p95_latency_ms,
    }


def create_error_timeline_chart(timeline, chart_dir=DEFAULT_CHART_DIR):
    """Save a five-minute 5xx-rate and p95-latency chart."""
    chart_dir = Path(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    output_path = chart_dir / "error_timeline.png"

    times = timeline["interval_start"]
    fig, rate_axis = plt.subplots(figsize=(13, 6))
    rate_axis.plot(
        times,
        timeline["failure_percentage_5xx"],
        color="#c62828",
        marker="o",
        markersize=3,
        linewidth=1.8,
        label="HTTP 5xx failure rate",
    )
    rate_axis.axhline(
        timeline["baseline_failure_percentage_5xx"].iloc[0],
        color="#ef8f00",
        linestyle="--",
        linewidth=1.5,
        label="09:00–10:00 UTC baseline mean",
    )
    rate_axis.set_ylabel("HTTP 5xx failure rate (%)")
    rate_axis.set_xlabel("Time (UTC)")
    rate_axis.set_ylim(bottom=0)
    rate_axis.grid(axis="y", alpha=0.25)
    rate_axis.legend(loc="upper left")

    latency_axis = rate_axis.twinx()
    latency_axis.plot(
        times,
        timeline["p95_latency_ms"],
        color="#1565c0",
        marker=".",
        linewidth=1.3,
        alpha=0.75,
        label="P95 response latency",
    )
    latency_axis.axhline(
        timeline["baseline_p95_latency_ms"].iloc[0],
        color="#1565c0",
        linestyle=":",
        linewidth=1.4,
        label="Baseline median interval P95 latency",
    )
    latency_axis.set_ylabel("P95 response latency (ms)")
    latency_axis.set_ylim(bottom=0)
    latency_axis.legend(loc="upper right")

    rate_axis.set_title(
        "ShopSphere five-minute HTTP 5xx rate and response latency"
    )
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def generate_summary(
    data,
    validation,
    http_status,
    error_codes,
    services,
    latency,
    time_windows,
    error_timeline,
    baseline,
    report_dir=DEFAULT_REPORT_DIR,
):
    """Write analysis tables and a JSON summary to the reports directory."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    tables = {
        "http_status_counts.csv": http_status["status_counts"],
        "errors_by_service.csv": error_codes,
        "service_analysis.csv": services,
        "latency_by_endpoint.csv": latency["by_endpoint"],
        "time_windows.csv": time_windows,
        "error_timeline.csv": error_timeline,
    }
    for filename, table in tables.items():
        table.to_csv(report_dir / filename, index=False)
    latency["overall"].to_csv(report_dir / "latency_overall.csv", index=False)

    summary = {
        "total_requests": http_status["total_requests"],
        "failed_requests_5xx": http_status["failed_requests"],
        "failure_percentage_5xx": round(http_status["failure_percentage"], 4),
        "log_records": int(len(data["application_logs"])),
        "metric_records": int(len(data["metrics"])),
        "latency_overall_ms": latency["overall"].iloc[0].where(
            pd.notna(latency["overall"].iloc[0]), None
        ).to_dict(),
        "error_timeline_baseline": baseline,
        "validation": validation,
        "reports": list(tables) + ["latency_overall.csv"],
    }
    with (report_dir / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, allow_nan=False, default=str)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Analyze ShopSphere request, application-log, and metric CSVs."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing the three input CSVs.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory where generated reports are written.",
    )
    parser.add_argument(
        "--chart-dir",
        type=Path,
        default=DEFAULT_CHART_DIR,
        help="Directory where generated charts are written.",
    )
    args = parser.parse_args()

    data = load_data(args.data_dir)
    validation = validate_data(data)
    http_status = analyze_http_status(data["requests"])
    error_codes = analyze_error_codes(data["application_logs"])
    services = analyze_services(data["application_logs"])
    latency = analyze_latency(data["requests"])
    time_windows = analyze_time_windows(data["requests"], data["metrics"])
    error_timeline, baseline = analyze_error_timeline(data["requests"])
    worst_intervals = error_timeline.nlargest(
        10, ["failure_percentage_5xx", "http_5xx_count"]
    )
    chart_path = create_error_timeline_chart(error_timeline, args.chart_dir)
    service_errors = analyze_service_errors(data["application_logs"])
    service_heatmap_path = create_service_region_heatmap(
        service_errors, args.chart_dir
    )
    service_report_path = write_service_error_report(
        data["application_logs"], service_errors, args.report_dir
    )
    metric_evidence, metric_correlations = analyze_metric_correlations(
        data["requests"], data["application_logs"], data["metrics"]
    )
    metric_chart_path = create_metric_correlation_chart(
        metric_evidence, args.chart_dir
    )
    metric_report_path, evidence_csv_path = write_metric_correlation_report(
        metric_evidence, metric_correlations, args.report_dir
    )
    checkout_cases = analyze_checkout_traces(
        data["requests"],
        data["application_logs"],
        error_codes=[
            "PAYMENT_PROVIDER_TIMEOUT",
            "DB_POOL_EXHAUSTED",
            "NULL_CUSTOMER_CONTEXT",
        ],
    )
    checkout_chart_path = create_checkout_trace_waterfall(
        checkout_cases, args.chart_dir
    )
    checkout_report_path = write_checkout_trace_report(
        checkout_cases, args.report_dir
    )
    summary = generate_summary(
        data,
        validation,
        http_status,
        error_codes,
        services,
        latency,
        time_windows,
        error_timeline,
        baseline,
        args.report_dir,
    )

    print(f"Requests: {summary['total_requests']:,}")
    print(
        f"HTTP 5xx failures: {summary['failed_requests_5xx']:,} "
        f"({summary['failure_percentage_5xx']:.2f}%)"
    )
    print(
        "Overall latency p50/p95/p99: "
        f"{summary['latency_overall_ms']['median_ms']:.2f}/"
        f"{summary['latency_overall_ms']['p95_ms']:.2f}/"
        f"{summary['latency_overall_ms']['p99_ms']:.2f} ms"
    )
    print(
        "Normal baseline (09:00-10:00 UTC): "
        f"{baseline['mean_failure_percentage_5xx']:.2f}% mean 5xx; "
        f"{baseline['median_interval_p95_latency_ms']:.2f} ms median interval p95"
    )
    print("Ten worst five-minute intervals (UTC):")
    print(
        worst_intervals[
            [
                "interval_start",
                "request_count",
                "http_4xx_count",
                "http_5xx_count",
                "failure_percentage_5xx",
                "p95_latency_ms",
                "failure_rate_vs_baseline",
            ]
        ].to_string(index=False, formatters={
            "failure_percentage_5xx": "{:.2f}%".format,
            "p95_latency_ms": "{:.2f}".format,
            "failure_rate_vs_baseline": "{:.1f}x".format,
        })
    )
    print(f"Reports written to: {args.report_dir.resolve()}")
    print(f"Error timeline chart written to: {chart_path.resolve()}")
    print("ERROR counts by service:")
    print(
        service_errors["service_summary"].to_string(
            index=False, formatters={"error_events": "{:,}".format}
        )
    )
    print(f"Service analysis report written to: {service_report_path.resolve()}")
    print(f"Service-region heatmap written to: {service_heatmap_path.resolve()}")
    print(f"Checkout trace report written to: {checkout_report_path.resolve()}")
    print(f"Checkout trace waterfall written to: {checkout_chart_path.resolve()}")
    print(f"Metric correlation report written to: {metric_report_path.resolve()}")
    print(f"Metric evidence table written to: {evidence_csv_path.resolve()}")
    print(f"Metric correlation chart written to: {metric_chart_path.resolve()}")


if __name__ == "__main__":
    main()
