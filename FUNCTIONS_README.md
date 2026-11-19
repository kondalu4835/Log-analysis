# ShopSphere Log Analysis Project Guide

This guide explains the `loganalytics` project, the analysis work represented by its files, and every function in `src/log_analyzer.py`. It is a reference for understanding and presenting the completed practical.

## Project overview

The project analyzes a synthetic ShopSphere e-commerce incident covering **2026-11-18 09:00-13:00 UTC**. The project README and case study describe the exercise as a teaching simulation; names, hosts, IP addresses, users, and transactions are fictional. The analysis combines request outcomes, detailed application events, and infrastructure metrics.

## Folder guide

### Source datasets

- `requests.csv`: 12,000 request-level records, one per `trace_id`. Use this as the denominator for request totals and HTTP 5xx rates.
- `application_logs.csv`: 42,354 detailed service and gateway log records.
- `application_logs.jsonl`: the application-log records in JSON Lines format; it has the same 42,354-record count. It is an alternate representation, not an additional set of events to add to the CSV count.
- `metrics.csv`: 576 metric records, covering four metrics at five-minute intervals across three regions: active database connections, API gateway heap percentage, notification queue lag, and payment-provider p95 latency. It does not contain CPU data.

### Project documentation and code

- `README.md`: scenario, data dictionary, investigation tasks, and important counting caveats.
- `CASE_STUDY.md`: the ShopSphere business scenario, customer symptoms, and required investigation tasks.
- `INSTRUCTOR_ANSWER_KEY.md`: an instructor-facing answer-key file. Treat it as instructor material when presenting.
- `Copilot analysis.docx` and `Manual analysis.docx`: Word documents present in the folder. Their contents are not described here because this guide is based on the inspectable source and generated reports.
- `src/log_analyzer.py`: the primary pandas-based analyzer, documented function-by-function below.
- `analysis.py`: a simpler Python standard-library starter that reads `requests.csv` and prints status, error-rate, latency, and five-minute summaries.
- `generate_logs.py`: deterministic generator for this synthetic dataset. It uses a fixed random seed and writes the generated CSV/JSONL datasets. Running it can replace the existing generated data, so it is not required for presenting the existing analysis.
- `tests/test_log_analyzer.py`: pytest checks for core analysis behavior.
- `.venv/`: project virtual environment.
- `.git/`, `__pycache__/`, and `.pytest_cache/`: version-control or tool-generated support folders; they are not incident evidence.

### Additional analysis scripts

- `inspect_data.py`: prints CSV row counts, column names, inferred pandas data types, and sample rows.
- `summarize_failures.py`: reports request-level failed and 5xx totals, groups request failures by endpoint, and separately counts ERROR log records by service.
- `timeseries_errors.py`: prints 4xx and 5xx counts/rates by time bucket and flags periods above a configurable 5xx threshold. Its default 5% threshold is an analysis choice, not a threshold specified by the dataset.
- `check_incident_metrics.py`: compares database, heap, provider-latency, and request-latency metrics against the baseline, aligned to request errors by time and region. It reports that CPU cannot be checked because that metric is absent.
- `verify_db_pool_order.py`: tests whether database pool exhaustion appeared before elevated 5xx errors in a selected region and period. The default region is `us-east-1` and the elevated-rate threshold is configurable.

## Work completed in this project

1. Reviewed the dataset and its schemas before analysis.
2. Built or used a repeatable analyzer to load and validate the CSVs, calculate request-level HTTP outcomes and latency, and summarize error codes and services.
3. Grouped requests into five-minute intervals, compared the incident with a 09:00-10:00 UTC baseline, and created an error-rate/latency timeline.
4. Joined application events to request records by `trace_id`, summarized service errors by region, and created a service-region heatmap.
5. Reconstructed representative failed checkout traces and created a trace waterfall.
6. Aligned infrastructure metrics and application/request errors by five-minute UTC interval and region; documented that correlation is not proof of causation.
7. Analyzed failed-login activity from serialized event details and kept those 401 outcomes separate from 5xx server failures.
8. Compared deployment versions and documented the null-customer-context failure association and the confounding limits.
9. Added focused helper scripts for data inspection, failure totals, the error time series, metric checks, and database-pool event ordering.
10. Added and ran analyzer tests. The recorded project-environment test result is **6 passed**.
11. Prepared a detailed RCA and a shorter post-mortem report.

Exact Copilot Prompt 1-10 text is not stored in the readable project files listed here. Describe prompt goals when presenting, but do not quote wording unless you have it saved separately.

## Main findings from the saved reports

- **Request impact:** 12,000 requests; 1,147 HTTP 5xx responses (**9.56%**). There were also 201 HTTP 401 responses and 387 HTTP 409 responses; these are not part of the 5xx numerator.
- **Latency:** request p50 76 ms, p95 about 1,921 ms, p99 about 4,115 ms.
- **Timeline:** the sharp 5xx increase starts around **10:45 UTC**; the highest overall five-minute rate is **37.6% at 12:00** (94 of 250 requests). At 12:40, the rate falls to 2%, with residual errors continuing.
- **Endpoint impact:** checkout has 622/3,120 5xx (19.94%); orders 252/1,700 (14.82%); cart 126/1,728 (7.29%); login 119/2,001 (5.95%); products 28/3,451 (0.81%).
- **Payment:** 179 `PAYMENT_PROVIDER_TIMEOUT` request traces. Provider p95 latency peaks at 5,804 ms in `us-east-1` at 10:50. These measurements align, but do not prove an external provider outage caused the incident.
- **Inventory:** 387 `INVENTORY_DEADLOCK` requests returned HTTP 409 across the three regions.
- **Database:** 311 `DB_POOL_EXHAUSTED` requests returned HTTP 503. Order-service logs report `pool_active=30` and `pool_max=30`. This began after the 10:45 elevated-error onset, so it does not explain that onset, although it accounts for later errors.
- **Deployment:** `v2.7.3` has 575/9,561 5xx (6.01%); `v2.8.0` has 572/2,439 (23.45%). All 460 `NULL_CUSTOMER_CONTEXT` request errors are associated with `v2.8.0` in `us-east-1`, across four routes. The logs name `new-checkout-context` and `CheckoutContextResolver.resolve:118`. This strongly associates the failure pattern with that path but does not prove the release caused every incident symptom; version, region, and time overlap.
- **Security:** 201 failed-login traces between 09:55:02 and 10:29:46 UTC are associated with synthetic source IP `198.51.100.77` and 195 user IDs. The records show failed attempts, not account compromise.
- **Notifications and memory:** queue-lag warnings indicate delayed downstream email work; they do not prove failed checkout. Heap later reaches 96%, after the largest 5xx period. CPU telemetry is not present.
- **Root-cause status:** the reports confirm several proximate failure mechanisms, but **do not establish one incident-wide root cause**.

## Generated charts

- `charts/error_timeline.png`: five-minute request 5xx rate and p95 latency with a baseline reference.
- `charts/service_region_error_heatmap.png`: distinct ERROR traces by service and region.
- `charts/checkout_trace_waterfall.png`: timestamped service events for selected failed checkout traces.
- `charts/metric_correlation_timeline.png`: infrastructure metrics and aligned request/service-event counts by region.

## Generated reports

### Markdown reports

- `reports/INCIDENT_RCA.md`: detailed investigation, impact, failure mechanisms, contributing hypotheses, mitigation, permanent actions, monitoring ideas, and validation plan.
- `reports/incident_postmortem.md`: concise post-mortem with timeline, impact, root-cause assessment, and recommendations.
- `reports/service_analysis.md`: service ERROR counts, error-code groups, and gateway-versus-service trace discussion.
- `reports/checkout_traces.md`: representative request details and timestamp-ordered service logs.
- `reports/metric_correlation.md`: metric alignment, sample correlations, evidence, and causality caveats.
- `reports/deployment_analysis.md`: version/endpoint/region comparison and `NULL_CUSTOMER_CONTEXT` analysis.
- `reports/security_anomalies.md`: failed-login and brute-force-indicator analysis with synthetic-data caveats.

### CSV and JSON evidence

- `reports/summary.json`: headline request, 5xx, latency, and validation totals.
- `reports/http_status_counts.csv`: request counts by HTTP status.
- `reports/error_timeline.csv` and `reports/time_windows.csv`: time-bucketed request and metric summaries.
- `reports/latency_overall.csv` and `reports/latency_by_endpoint.csv`: latency statistics.
- `reports/errors_by_service.csv`, `reports/service_analysis.csv`, `reports/service_error_groups.csv`, and `reports/ranked_error_codes.csv`: service and error-code summaries.
- `reports/metric_correlation_evidence.csv`: aligned metric, request, and service-log evidence.
- `reports/deployment_5min.csv`, `reports/deployment_endpoint_region.csv`, `reports/deployment_error_codes.csv`, `reports/deployment_route_comparison.csv`, and `reports/deployment_version_summary.csv`: release comparison tables.
- `reports/null_customer_context_traces.csv`: request/log evidence for affected traces.
- `reports/security_activity_5min.csv`, `reports/security_affected_users.csv`, and `reports/security_login_failures.csv`: authentication activity evidence.

## Suggested presentation flow

1. Introduce the synthetic incident and the three source datasets.
2. Show `src/log_analyzer.py` and explain request-level counting and trace IDs.
3. Present the timeline chart and 09:00-10:00 baseline.
4. Show the service heatmap and one trace waterfall.
5. Compare metric and deployment reports, explaining correlation and confounding.
6. Present the security findings with the synthetic-data caveat.
7. Close with `reports/INCIDENT_RCA.md`, the shorter post-mortem, the six passing tests, and the conclusion that there is no proven single incident-wide cause.

## Commands for every project Python file

Open a terminal in the project folder first:

```bash
cd ~/Desktop/debug_lab/loganalytics
```

Use the virtual-environment interpreter (`.venv/bin/python`) so the scripts use the project's installed packages. The commands below run each file's normal entry point. Helper functions are generally called by that entry point and are not separate command-line programs.

| Python file | Command | Functions exercised |
|---|---|---|
| `analysis.py` | `.venv/bin/python analysis.py` | `percentile()` is used for p50, p95, and p99; the rest of the analysis runs at file level. |
| `src/log_analyzer.py` | `.venv/bin/python src/log_analyzer.py` | `main()` runs the complete analyzer, including loading, validation, status/error/service/latency/time-window analyses, trace reports, charts, correlations, and summary generation. |
| `inspect_data.py` | `.venv/bin/python inspect_data.py --sample-rows 5` | `main()` calls `inspect_csv()` for each of the three CSV files. Change `5` to choose another sample size. |
| `summarize_failures.py` | `.venv/bin/python summarize_failures.py` | `main()` calls `read_csv()` and `summarize_failures()` for request and application-log records. |
| `timeseries_errors.py` | `.venv/bin/python timeseries_errors.py --interval-minutes 5 --threshold-percent 5` | `main()` calls `load_requests()`, `bucket_start()`, and `print_timeseries()`. The 5% marker is a configurable analysis threshold, not a threshold specified by the dataset. |
| `check_incident_metrics.py` | `.venv/bin/python check_incident_metrics.py` | `main()` loads/alines the data and calls `_period_rows()` and `_print_metric_check()` for each available metric. Options include `--incident-start`, `--incident-end`, `--baseline-start`, `--baseline-end`, and `--data-dir`. |
| `verify_db_pool_order.py` | `.venv/bin/python verify_db_pool_order.py --region us-east-1 --threshold-percent 5` | `main()` calls `verify()`, which uses `_first_row()` and `_details_object()` to compare first errors, service events, and full-pool metrics. |
| `tests/test_log_analyzer.py` | `.venv/bin/python -m pytest -q tests/test_log_analyzer.py` | Pytest calls the six `test_*` functions. Their `_requests()` and `_metrics()` helpers build test DataFrames. |
| `generate_logs.py` | **Do not run for routine analysis.** If you intentionally want to regenerate the synthetic data, use `.venv/bin/python generate_logs.py` only after preserving the current CSV/JSONL files. | The top-level generation flow uses `between()`, `mins()`, `choose_route()`, and `emit()`, then writes the generated dataset files. It can replace the existing data. |

### Run individual tests

These commands run one named test at a time:

```bash
.venv/bin/python -m pytest -q tests/test_log_analyzer.py::test_total_request_count_and_http_5xx_calculation
.venv/bin/python -m pytest -q tests/test_log_analyzer.py::test_checkout_trace_extraction_joins_only_matching_trace_id
.venv/bin/python -m pytest -q tests/test_log_analyzer.py::test_five_minute_groups_are_floored_in_utc_and_kept_by_region
.venv/bin/python -m pytest -q tests/test_log_analyzer.py::test_metric_correlation_join_uses_utc_bucket_and_region
.venv/bin/python -m pytest -q tests/test_log_analyzer.py::test_exact_duplicate_requests_count_once_and_conflicts_are_rejected
.venv/bin/python -m pytest -q tests/test_log_analyzer.py::test_actual_dataset_totals_and_duplicate_validation
```

### Recommended routine run order

```bash
.venv/bin/python -m pytest -q tests/test_log_analyzer.py
.venv/bin/python src/log_analyzer.py
.venv/bin/python inspect_data.py --sample-rows 5
.venv/bin/python summarize_failures.py
.venv/bin/python timeseries_errors.py
.venv/bin/python check_incident_metrics.py
.venv/bin/python verify_db_pool_order.py
```

The system `python3 -m pytest -v` command previously exited with code 1, while the recorded `.venv/bin/python -m pytest -q tests/test_log_analyzer.py` run passed six tests. Prefer the latter command in this project. The exact error output for the failed system-Python command is not included in this guide.

## Function reference

The sections below explain the functions in `src/log_analyzer.py`. They describe the current code; they do not change or execute the analyzer.

## Data loading and request analysis

### `load_data(data_dir=DEFAULT_DATA_DIR)`
Reads `requests.csv`, `application_logs.csv`, and `metrics.csv` from the supplied directory (the project directory by default). It checks that required columns exist, parses timestamps as UTC, and converts numeric fields. Returns a dictionary containing the three pandas DataFrames. Raises an error if an input file or required column is missing.

### `validate_data(data)`
Checks each loaded dataset for required columns and missing timestamps. For requests, it also counts invalid HTTP statuses, missing trace IDs, and duplicate trace IDs. Returns a dictionary of row and data-quality counts; it raises an error if required columns are absent.

### `_deduplicate_requests(requests)`
Internal helper for request-level analyses. It collapses exact duplicate rows with the same `trace_id` and raises an error if one trace ID has conflicting request records. This prevents a repeated row from inflating request totals.

### `analyze_http_status(requests)`
Counts requests by HTTP status and calculates the request-level 5xx rate as `5xx requests / total requests * 100`. Returns the total request count, 5xx count, percentage, and a status-count DataFrame. It deduplicates exact requests first.

### `analyze_error_codes(application_logs)`
Groups log records with a non-empty `error_code` by service and code. Returns both the number of log events and the number of distinct affected trace IDs. This function groups coded records; it does not filter only on the `ERROR` level.

### `analyze_services(application_logs)`
Summarizes each service's total log events, ERROR-level events, records with an error code, HTTP error events, and distinct traces with an error code. It includes all log levels in the service totals.

### `analyze_latency(requests)`
Calculates request latency overall and by endpoint: count, mean, median, p95, p99, and maximum. Returns two DataFrames (`overall` and `by_endpoint`) after removing exact duplicate requests.

## Service error analysis and reports

### `analyze_service_errors(application_logs)`
Filters to `level == ERROR`, then groups errors by service, region, event, level, and error code. It also produces service totals, ranked error codes, a service-by-region heatmap DataFrame, unique error-trace counts, and same-trace matches between gateway responses and earlier service errors. These are log and trace counts, not counts to add together as unique requests.

### `create_service_region_heatmap(service_errors, chart_dir=DEFAULT_CHART_DIR)`
Renders distinct ERROR trace counts by service and region as a heatmap and saves `service_region_error_heatmap.png`. Returns the output path.

### `_markdown_table(frame)`
Internal formatting helper. Converts a DataFrame to a Markdown table, escapes vertical bars in cell text, and returns a short no-records message for an empty DataFrame.

### `write_service_error_report(application_logs, service_errors, report_dir=DEFAULT_REPORT_DIR)`
Writes the grouped service errors to `service_error_groups.csv`, ranked codes to `ranked_error_codes.csv`, and a narrative summary to `service_analysis.md`. The report distinguishes gateway response logs from earlier service errors and warns against summing overlapping trace counts.

## Trace investigation

### `analyze_checkout_traces(requests, application_logs, error_codes=None)`
Selects HTTP 5xx requests for `/api/v1/checkout`, joins each request to application log records using `trace_id`, sorts events by timestamp, and identifies the earliest ERROR event. If error codes are supplied, it selects the earliest matching checkout request for each code; otherwise it selects the first three checkout failures. Returns trace cases containing the request, ordered log records, and earliest failure evidence.

### `create_checkout_trace_waterfall(cases, chart_dir=DEFAULT_CHART_DIR)`
Plots the logged service events for each selected trace relative to request start time. ERROR events receive a different color. Saves `checkout_trace_waterfall.png` and returns its path. The spans in this teaching dataset are approximate.

### `write_checkout_trace_report(cases, report_dir=DEFAULT_REPORT_DIR)`
Writes `checkout_traces.md`, including request details, service sequence, earliest failure event, and an event table with timestamps, elapsed times, service, level, error code, latency, and HTTP status. It also adds a causality caveat.

## Time windows and infrastructure metrics

### `analyze_time_windows(requests, metrics, interval="5min")`
Floors request and metric timestamps to the selected interval, aggregates request counts and 5xx counts by UTC interval and region, calculates a 5xx percentage, pivots metric names into columns, and joins the results by time and region. Returns the combined DataFrame.

### `analyze_metric_correlations(requests, application_logs, metrics, interval="5min")`
Aligns request outcomes, relevant application-log events, and metrics by five-minute UTC interval and region. It counts request-level DB pool and payment errors, service error traces, notification lag warnings, and application errors, then calculates Pearson correlations for configured metric/outcome pairs. Returns the aligned evidence DataFrame and a correlation DataFrame. Correlation is descriptive and does not prove causation.

### `create_metric_correlation_chart(aligned, chart_dir=DEFAULT_CHART_DIR)`
Creates four time-series panels for DB pool connections, provider p95 latency, notification queue lag, and gateway heap, with aligned request or service-event counts. Saves `metric_correlation_timeline.png` and returns its path.

### `write_metric_correlation_report(aligned, correlations, report_dir=DEFAULT_REPORT_DIR)`
Writes the full aligned data to `metric_correlation_evidence.csv` and a Markdown analysis to `metric_correlation.md`. The report describes sample peaks and correlations, and explicitly cautions against interpreting correlation as causation. Returns both output paths.

## Error timeline and output generation

### `analyze_error_timeline(requests, interval="5min")`
Groups request-level 4xx counts, 5xx counts, request totals, and p95 latency into time intervals. It compares each interval with the fixed 09:00-10:00 UTC baseline on November 18, 2026. Returns the timeline DataFrame and baseline statistics.

### `create_error_timeline_chart(timeline, chart_dir=DEFAULT_CHART_DIR)`
Plots the five-minute 5xx rate and p95 latency, with baseline reference lines. Saves `error_timeline.png` and returns its path.

### `generate_summary(data, validation, http_status, error_codes, services, latency, time_windows, error_timeline, baseline, report_dir=DEFAULT_REPORT_DIR)`
Writes CSV summaries for HTTP status, error codes, services, latency by endpoint, joined time windows, and the error timeline. It also writes `latency_overall.csv` and `summary.json`. Returns the summary dictionary.

### `main()`
Command-line entry point. Parses `--data-dir`, `--report-dir`, and `--chart-dir`; loads and validates the data; calls the analysis, chart, trace, and report functions; then prints headline request/latency information and output paths. The default paths are based on the location of `src/log_analyzer.py`, so it can be run with:

```bash
.venv/bin/python src/log_analyzer.py
```

## Output files created by the analyzer

The default run writes its reports under `reports/` and charts under `charts/`:

- `reports/summary.json`
- `reports/http_status_counts.csv`
- `reports/errors_by_service.csv`
- `reports/service_analysis.csv`
- `reports/latency_by_endpoint.csv`
- `reports/latency_overall.csv`
- `reports/time_windows.csv`
- `reports/error_timeline.csv`
- `reports/service_error_groups.csv`
- `reports/ranked_error_codes.csv`
- `reports/service_analysis.md`
- `reports/checkout_traces.md`
- `reports/metric_correlation.md`
- `reports/metric_correlation_evidence.csv`
- `charts/error_timeline.png`
- `charts/service_region_error_heatmap.png`
- `charts/checkout_trace_waterfall.png`
- `charts/metric_correlation_timeline.png`

Counts from different service log rows can refer to the same request. Use `requests.csv` and unique `trace_id` values for request-level totals, and use the service log outputs to understand which component emitted an error.
