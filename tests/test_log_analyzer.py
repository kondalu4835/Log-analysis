import pandas as pd
import pytest

from src import log_analyzer


def _requests(rows):
    frame = pd.DataFrame(
        rows,
        columns=[
            "timestamp",
            "trace_id",
            "region",
            "endpoint",
            "status",
            "latency_ms",
            "error_code",
        ],
    )
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], utc=True, format="mixed"
    )
    return frame


def _metrics(rows):
    frame = pd.DataFrame(rows, columns=["timestamp", "region", "metric", "value"])
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], utc=True, format="mixed"
    )
    return frame


def test_total_request_count_and_http_5xx_calculation():
    requests = _requests(
        [
            ("2026-11-18T10:00:00Z", "ok", "us-east-1", "/checkout", 200, 80, ""),
            ("2026-11-18T10:00:01Z", "unauth", "us-east-1", "/login", 401, 20, ""),
            ("2026-11-18T10:00:02Z", "conflict", "us-east-1", "/checkout", 409, 40, ""),
            ("2026-11-18T10:00:03Z", "server", "us-east-1", "/checkout", 500, 300, "FAIL"),
            ("2026-11-18T10:00:04Z", "unavailable", "us-east-1", "/orders", 503, 500, "POOL"),
            ("2026-11-18T10:00:05Z", "timeout", "us-east-1", "/checkout", 504, 700, "TIMEOUT"),
        ]
    )

    result = log_analyzer.analyze_http_status(requests)

    assert result["total_requests"] == 6
    assert result["failed_requests"] == 3
    assert result["failure_percentage"] == pytest.approx(50.0)
    assert result["status_counts"]["request_count"].sum() == 6


def test_checkout_trace_extraction_joins_only_matching_trace_id():
    trace_id = "actual-trace-123"
    requests = _requests(
        [
            ("2026-11-18T10:00:00Z", trace_id, "us-east-1", "/api/v1/checkout", 504, 900, "PAY_TIMEOUT"),
            ("2026-11-18T10:00:01Z", "other-trace", "us-east-1", "/api/v1/checkout", 500, 400, "OTHER"),
        ]
    )
    logs = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-11-18T10:00:00.100Z"),
                "trace_id": trace_id,
                "service": "payment-service",
                "level": "ERROR",
                "error_code": "PAY_TIMEOUT",
                "latency_ms": 850,
                "http_status": 504,
            },
            {
                "timestamp": pd.Timestamp("2026-11-18T10:00:00.200Z"),
                "trace_id": trace_id,
                "service": "api-gateway",
                "level": "ERROR",
                "error_code": "PAY_TIMEOUT",
                "latency_ms": 900,
                "http_status": 504,
            },
            {
                "timestamp": pd.Timestamp("2026-11-18T10:00:00.050Z"),
                "trace_id": "unrelated",
                "service": "cart-service",
                "level": "ERROR",
                "error_code": "OTHER",
                "latency_ms": 5,
                "http_status": 500,
            },
        ]
    )

    cases = log_analyzer.analyze_checkout_traces(
        requests, logs, error_codes=["PAY_TIMEOUT"]
    )

    assert len(cases) == 1
    assert cases[0]["request"]["trace_id"] == trace_id
    assert cases[0]["trace"]["trace_id"].tolist() == [trace_id, trace_id]
    assert cases[0]["earliest_failure"]["service"] == "payment-service"


def test_five_minute_groups_are_floored_in_utc_and_kept_by_region():
    requests = _requests(
        [
            ("2026-11-18T10:04:59.999Z", "before", "us-east-1", "/checkout", 500, 100, "ERR"),
            ("2026-11-18T10:05:00Z", "boundary", "us-east-1", "/checkout", 503, 200, "ERR"),
            ("2026-11-18T10:04:00Z", "other-region", "eu-west-1", "/orders", 200, 30, ""),
        ]
    )
    metrics = _metrics(
        [
            ("2026-11-18T10:04:30Z", "us-east-1", "db_pool_active", 8),
            ("2026-11-18T10:05:30Z", "us-east-1", "db_pool_active", 12),
            ("2026-11-18T10:04:30Z", "eu-west-1", "db_pool_active", 3),
        ]
    )

    windows = log_analyzer.analyze_time_windows(requests, metrics)
    us_east = windows.loc[windows["region"].eq("us-east-1")].set_index("timestamp")

    assert us_east.loc[pd.Timestamp("2026-11-18T10:00:00Z"), "request_count"] == 1
    assert us_east.loc[pd.Timestamp("2026-11-18T10:00:00Z"), "failed_requests"] == 1
    assert us_east.loc[pd.Timestamp("2026-11-18T10:00:00Z"), "db_pool_active"] == 8
    assert us_east.loc[pd.Timestamp("2026-11-18T10:05:00Z"), "request_count"] == 1
    assert us_east.loc[pd.Timestamp("2026-11-18T10:05:00Z"), "db_pool_active"] == 12


def test_metric_correlation_join_uses_utc_bucket_and_region():
    requests = _requests(
        [
            ("2026-11-18T10:01:00Z", "db-fail", "us-east-1", "/orders", 503, 500, "DB_POOL_EXHAUSTED"),
            ("2026-11-18T10:06:00Z", "ok", "us-east-1", "/orders", 200, 50, ""),
        ]
    )
    logs = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-11-18T10:01:10Z"),
                "trace_id": "db-fail",
                "region": "us-east-1",
                "service": "order-service",
                "event": "db.pool.exhausted",
                "level": "ERROR",
                "error_code": "DB_POOL_EXHAUSTED",
            }
        ]
    )
    metrics = _metrics(
        [
            (timestamp, "us-east-1", metric, value)
            for timestamp, values in [
                ("2026-11-18T10:00:00Z", [30, 2000, 100, 50]),
                ("2026-11-18T10:05:00Z", [10, 200, 20, 40]),
            ]
            for metric, value in zip(
                ["db_pool_active", "provider_p95_ms", "queue_lag_messages", "heap_used_pct"],
                values,
            )
        ]
    )

    aligned, _ = log_analyzer.analyze_metric_correlations(requests, logs, metrics)

    first = aligned.loc[
        aligned["timestamp"].eq(pd.Timestamp("2026-11-18T10:00:00Z"))
    ].iloc[0]
    second = aligned.loc[
        aligned["timestamp"].eq(pd.Timestamp("2026-11-18T10:05:00Z"))
    ].iloc[0]
    assert first["region"] == "us-east-1"
    assert first["db_pool_active"] == 30
    assert first["request_count"] == 1
    assert first["request_db_pool_exhausted"] == 1
    assert first["db_pool_error_traces"] == 1
    assert second["db_pool_active"] == 10
    assert second["request_count"] == 1
    assert second["request_db_pool_exhausted"] == 0


def test_exact_duplicate_requests_count_once_and_conflicts_are_rejected():
    request = (
        "2026-11-18T10:00:00Z",
        "duplicate",
        "us-east-1",
        "/checkout",
        500,
        300,
        "FAIL",
    )
    requests = _requests([request, request])

    result = log_analyzer.analyze_http_status(requests)
    windows = log_analyzer.analyze_time_windows(
        requests,
        _metrics([("2026-11-18T10:00:00Z", "us-east-1", "db_pool_active", 5)]),
    )

    assert result["total_requests"] == 1
    assert result["failed_requests"] == 1
    assert windows.iloc[0]["request_count"] == 1
    assert windows.iloc[0]["failed_requests"] == 1

    conflicting = _requests(
        [
            request,
            (
                "2026-11-18T10:00:00Z",
                "duplicate",
                "us-east-1",
                "/checkout",
                200,
                300,
                "",
            ),
        ]
    )
    with pytest.raises(ValueError, match="Conflicting request records"):
        log_analyzer.analyze_http_status(conflicting)


def test_actual_dataset_totals_and_duplicate_validation():
    data = log_analyzer.load_data()

    result = log_analyzer.analyze_http_status(data["requests"])
    validation = log_analyzer.validate_data(data)

    assert result["total_requests"] == 12_000
    assert result["failed_requests"] == 1_147
    assert result["failure_percentage"] == pytest.approx(9.5583333333)
    assert validation["requests"]["duplicate_trace_ids"] == 0
