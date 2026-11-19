import argparse
from pathlib import Path

import pandas as pd

from src.log_analyzer import analyze_time_windows, load_data


DEFAULT_INCIDENT_START = "2026-11-18T10:45:00Z"
DEFAULT_INCIDENT_END = "2026-11-18T12:40:00Z"
DEFAULT_BASELINE_START = "2026-11-18T09:00:00Z"
DEFAULT_BASELINE_END = "2026-11-18T10:00:00Z"
METRIC_LABELS = {
    "db_pool_active": "Database active connections",
    "heap_used_pct": "API gateway heap used (%)",
    "provider_p95_ms": "Payment provider p95 latency (ms)",
}
METRIC_FAILURES = {
    "db_pool_active": ("request_db_pool_exhausted", "DB_POOL_EXHAUSTED"),
    "heap_used_pct": ("request_5xx", "HTTP 5xx"),
    "provider_p95_ms": ("request_payment_timeouts", "PAYMENT_PROVIDER_TIMEOUT"),
}


def _period_rows(frame, start, end):
    return frame.loc[frame["timestamp"].ge(start) & frame["timestamp"].lt(end)]


def _print_metric_check(aligned, metric, label, baseline_start, baseline_end,
                        incident_start, incident_end, request_counts,
                        failure_column="request_5xx", failure_label="HTTP 5xx"):
    baseline = _period_rows(aligned, baseline_start, baseline_end).dropna(
        subset=[metric]
    )
    incident = _period_rows(aligned, incident_start, incident_end).dropna(
        subset=[metric]
    )
    if baseline.empty or incident.empty:
        print(f"\n{label}: insufficient data in the baseline or incident window")
        return

    peak = incident.loc[incident[metric].idxmax()]
    peak_time = peak["timestamp"]
    peak_region = peak["region"]
    matching = request_counts.loc[
        request_counts["timestamp"].eq(peak_time)
        & request_counts["region"].eq(peak_region)
    ]
    peak_requests = int(matching.iloc[0]["request_count"]) if not matching.empty else 0
    peak_5xx = int(matching.iloc[0]["request_5xx"]) if not matching.empty else 0
    peak_rate = (
        100.0 * peak_5xx / peak_requests if peak_requests else 0.0
    )
    baseline_max = float(baseline[metric].max())
    incident_max = float(peak[metric])
    comparison = "above" if incident_max > baseline_max else "not above"

    valid = incident[[metric, failure_column]].dropna()
    correlation = valid[metric].corr(valid[failure_column])
    correlation_text = f"{correlation:.3f}" if pd.notna(correlation) else "undefined"
    matching_failures = (
        int(matching.iloc[0][failure_column]) if not matching.empty else 0
    )

    print(f"\n{label}")
    print(
        f"  Baseline mean/max: {baseline[metric].mean():.2f} / "
        f"{baseline_max:.2f} ({len(baseline)} region-intervals)"
    )
    print(
        f"  Incident mean/max: {incident[metric].mean():.2f} / "
        f"{incident_max:.2f} ({len(incident)} region-intervals)"
    )
    print(
        f"  Peak: {peak_time.isoformat()} {peak_region}, "
        f"{incident_max:.2f}; same interval has {peak_5xx}/{peak_requests} "
        f"HTTP 5xx ({peak_rate:.2f}%) and {matching_failures} {failure_label}"
    )
    print(
        f"  Incident-window correlation with {failure_label} counts: "
        f"{correlation_text}"
    )
    print(f"  Incident peak is {comparison} the baseline maximum.")


def main():
    parser = argparse.ArgumentParser(
        description="Compare incident-window metrics with HTTP errors and a baseline."
    )
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--incident-start", default=DEFAULT_INCIDENT_START)
    parser.add_argument("--incident-end", default=DEFAULT_INCIDENT_END)
    parser.add_argument("--baseline-start", default=DEFAULT_BASELINE_START)
    parser.add_argument("--baseline-end", default=DEFAULT_BASELINE_END)
    args = parser.parse_args()

    incident_start, incident_end, baseline_start, baseline_end = map(
        lambda value: pd.Timestamp(value, tz="UTC"),
        (
            args.incident_start,
            args.incident_end,
            args.baseline_start,
            args.baseline_end,
        ),
    )
    if incident_start >= incident_end or baseline_start >= baseline_end:
        parser.error("each window start must be earlier than its end")

    data = load_data(args.data_dir)
    aligned = analyze_time_windows(data["requests"], data["metrics"]).rename(
        columns={"failed_requests": "request_5xx"}
    )
    request_rows = data["requests"].copy()
    request_rows["timestamp"] = request_rows["timestamp"].dt.floor("5min")
    request_rows["_is_5xx"] = request_rows["status"].between(500, 599)
    request_rows["_is_db_pool_error"] = request_rows["error_code"].eq(
        "DB_POOL_EXHAUSTED"
    ) & request_rows["_is_5xx"]
    request_rows["_is_payment_timeout"] = request_rows["error_code"].eq(
        "PAYMENT_PROVIDER_TIMEOUT"
    ) & request_rows["_is_5xx"]
    request_counts = (
        request_rows.groupby(["timestamp", "region"], dropna=False)
        .agg(
            request_count=("trace_id", "nunique"),
            request_5xx=("_is_5xx", "sum"),
            request_db_pool_exhausted=("_is_db_pool_error", "sum"),
            request_payment_timeouts=("_is_payment_timeout", "sum"),
        )
        .reset_index()
    )
    aligned = aligned.merge(
        request_counts[
            [
                "timestamp",
                "region",
                "request_db_pool_exhausted",
                "request_payment_timeouts",
            ]
        ],
        on=["timestamp", "region"],
        how="left",
    )

    print(
        f"Incident window: [{incident_start.isoformat()}, "
        f"{incident_end.isoformat()}) UTC"
    )
    print(
        f"Baseline window: [{baseline_start.isoformat()}, "
        f"{baseline_end.isoformat()}) UTC"
    )
    available_metrics = set(data["metrics"]["metric"].dropna().astype(str))
    for metric, label in METRIC_LABELS.items():
        if metric in available_metrics:
            failure_column, failure_label = METRIC_FAILURES[metric]
            _print_metric_check(
                aligned,
                metric,
                label,
                baseline_start,
                baseline_end,
                incident_start,
                incident_end,
                request_counts,
                failure_column,
                failure_label,
            )
        else:
            print(f"\n{label}: no `{metric}` series in metrics.csv")

    if not any("cpu" in name.lower() for name in available_metrics):
        print("\nCPU: no CPU metric is present in metrics.csv; CPU spikes cannot be checked.")

    request_latency = data["requests"].copy()
    request_latency["timestamp"] = request_latency["timestamp"].dt.floor("5min")
    request_latency["_is_5xx"] = request_latency["status"].between(500, 599)
    request_latency["_is_payment_timeout"] = request_latency["error_code"].eq(
        "PAYMENT_PROVIDER_TIMEOUT"
    ) & request_latency["_is_5xx"]
    request_latency["_is_db_pool_error"] = request_latency["error_code"].eq(
        "DB_POOL_EXHAUSTED"
    ) & request_latency["_is_5xx"]
    latency_windows = (
        request_latency.groupby(["timestamp", "region"], dropna=False)
        .agg(
            request_latency_p95_ms=("latency_ms", lambda values: values.quantile(0.95)),
            request_count=("trace_id", "nunique"),
            request_5xx=("_is_5xx", "sum"),
            request_db_pool_exhausted=("_is_db_pool_error", "sum"),
            request_payment_timeouts=("_is_payment_timeout", "sum"),
        )
        .reset_index()
    )
    _print_metric_check(
        latency_windows,
        "request_latency_p95_ms",
        "API request p95 latency (ms)",
        baseline_start,
        baseline_end,
        incident_start,
        incident_end,
        request_counts,
    )


if __name__ == "__main__":
    main()