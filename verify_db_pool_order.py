import argparse
import json
from pathlib import Path

import pandas as pd

from src.log_analyzer import load_data


DEFAULT_INCIDENT_START = "2026-11-18T10:45:00Z"
DEFAULT_INCIDENT_END = "2026-11-18T12:40:00Z"


def _first_row(frame):
    if frame.empty:
        return None
    return frame.sort_values("timestamp").iloc[0]


def _details_object(value):
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def verify(data, region, incident_start, incident_end, threshold_percent):
    requests = data["requests"]
    logs = data["application_logs"]
    metrics = data["metrics"]

    regional_requests = requests.loc[requests["region"].eq(region)].copy()
    regional_requests["_is_5xx"] = regional_requests["status"].between(500, 599)
    all_5xx = regional_requests.loc[regional_requests["_is_5xx"]]
    first_5xx = _first_row(all_5xx)

    incident_requests = regional_requests.loc[
        regional_requests["timestamp"].ge(incident_start)
        & regional_requests["timestamp"].lt(incident_end)
    ].copy()
    incident_requests["_interval"] = incident_requests["timestamp"].dt.floor("5min")
    buckets = (
        incident_requests.groupby("_interval", dropna=False)
        .agg(
            request_count=("trace_id", "nunique"),
            error_count=("_is_5xx", "sum"),
        )
        .reset_index()
    )
    buckets["error_rate_pct"] = (
        100.0 * buckets["error_count"] / buckets["request_count"]
    )
    elevated = buckets.loc[
        buckets["error_count"].gt(0)
        & buckets["error_rate_pct"].ge(threshold_percent)
    ].sort_values("_interval")
    first_elevated = None
    first_elevated_error = None
    first_bucket_codes = {}
    if not elevated.empty:
        first_elevated = elevated.iloc[0]
        first_bucket_requests = incident_requests.loc[
            incident_requests["_interval"].eq(first_elevated["_interval"])
            & incident_requests["_is_5xx"]
        ]
        first_elevated_error = _first_row(first_bucket_requests)
        first_bucket_codes = first_bucket_requests["error_code"].value_counts().to_dict()

    regional_logs = logs.loc[logs["region"].eq(region)]
    db_errors = regional_logs.loc[
        regional_logs["service"].eq("order-service")
        & regional_logs["event"].eq("db.pool.exhausted")
        & regional_logs["level"].astype(str).str.upper().eq("ERROR")
    ].copy()
    first_db_error = _first_row(db_errors)

    db_requests = regional_requests.loc[
        regional_requests["error_code"].eq("DB_POOL_EXHAUSTED")
        & regional_requests["status"].between(500, 599)
    ]
    first_db_request = _first_row(db_requests)

    pool_max = None
    if first_db_error is not None:
        pool_max = _details_object(first_db_error.get("details", "")).get("pool_max")
    db_metrics = metrics.loc[
        metrics["region"].eq(region) & metrics["metric"].eq("db_pool_active")
    ]
    full_pool_metric = pd.DataFrame()
    if pool_max is not None:
        full_pool_metric = db_metrics.loc[db_metrics["value"].ge(float(pool_max))]
    first_full_pool_metric = _first_row(full_pool_metric)

    print("Hypothesis: database pool exhaustion initiated the elevated HTTP 5xx incident.")
    print(f"Region: {region}")
    print(
        f"Elevated-error window checked: [{incident_start.isoformat()}, "
        f"{incident_end.isoformat()}) UTC; threshold: {threshold_percent:.2f}% 5xx per 5 minutes."
    )

    if first_5xx is None:
        print("No HTTP 5xx requests were found in this region.")
    else:
        print(
            f"First HTTP 5xx in all available data: {first_5xx['timestamp'].isoformat()} "
            f"({first_5xx['error_code']})."
        )

    if first_elevated is None:
        print("No interval in the selected window reached the configured 5xx threshold.")
        return

    print(
        f"First elevated 5xx interval: {first_elevated['_interval'].isoformat()} "
        f"({int(first_elevated['error_count'])}/{int(first_elevated['request_count'])} "
        f"requests, {first_elevated['error_rate_pct']:.2f}%)."
    )
    if first_elevated_error is not None:
        print(
            f"First 5xx request in that interval: "
            f"{first_elevated_error['timestamp'].isoformat()} "
            f"({first_elevated_error['error_code']})."
        )
    if first_bucket_codes:
        codes = ", ".join(
            f"{code}: {count}" for code, count in sorted(first_bucket_codes.items())
        )
        print(f"5xx error codes in the first elevated interval: {codes}.")

    if first_db_error is None:
        print("No order-service db.pool.exhausted ERROR event was found.")
    else:
        print(
            f"First order-service db.pool.exhausted event: "
            f"{first_db_error['timestamp'].isoformat()}."
        )
    if first_db_request is not None:
        print(
            f"First DB_POOL_EXHAUSTED HTTP request: "
            f"{first_db_request['timestamp'].isoformat()}."
        )
    if pool_max is not None:
        if first_full_pool_metric is None:
            print(f"No db_pool_active metric reached the logged pool_max of {pool_max}.")
        else:
            print(
                f"First db_pool_active metric at pool_max ({pool_max}): "
                f"{first_full_pool_metric['timestamp'].isoformat()} "
                f"({first_full_pool_metric['value']} connections)."
            )

    onset = first_elevated_error["timestamp"] if first_elevated_error is not None else first_elevated["_interval"]
    if first_db_error is not None and first_db_error["timestamp"] > onset:
        delay = first_db_error["timestamp"] - onset
        print(
            f"\nConclusion: the hypothesis is not supported as the initiator. "
            f"The first elevated 5xx request precedes the first pool-exhaustion "
            f"service event by {delay}. Pool exhaustion may have contributed to "
            "later errors, but it does not precede the elevated-error onset."
        )
    elif first_db_error is not None:
        print(
            "\nConclusion: pool exhaustion was logged before or at the elevated "
            "5xx onset. This timing is consistent with the hypothesis but does "
            "not by itself prove causation."
        )
    else:
        print(
            "\nConclusion: there is no service-level pool-exhaustion timestamp "
            "to compare with the 5xx onset."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Check whether database pool exhaustion preceded elevated HTTP 5xx errors."
    )
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--incident-start", default=DEFAULT_INCIDENT_START)
    parser.add_argument("--incident-end", default=DEFAULT_INCIDENT_END)
    parser.add_argument("--threshold-percent", type=float, default=5.0)
    args = parser.parse_args()

    incident_start, incident_end = (
        pd.to_datetime(args.incident_start, utc=True),
        pd.to_datetime(args.incident_end, utc=True),
    )
    if incident_start >= incident_end:
        parser.error("--incident-start must be earlier than --incident-end")
    if not 0 < args.threshold_percent <= 100:
        parser.error("--threshold-percent must be greater than 0 and at most 100")

    verify(
        load_data(args.data_dir),
        args.region,
        incident_start,
        incident_end,
        args.threshold_percent,
    )


if __name__ == "__main__":
    main()