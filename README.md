# ShopSphere | Enterprise Distributed Log Investigation

## Scenario
A fictional e-commerce company has experienced payment failures, checkout delays, login abuse, inventory conflicts, DB pool exhaustion, notification backlogs, and post-deployment exceptions. Investigate what happened during **2026-11-18 09:00–13:00 UTC**. All names, hosts, IPs, users, and transactions are synthetic. Reserved documentation IP ranges are used deliberately.

## Data dictionary

### `application_logs.jsonl` / `application_logs.csv`
42,354 records. Each log includes `timestamp`, `level`, `service`, `environment`, `region`, `host`, `deployment_version`, `trace_id`, `span_id`, `parent_span_id`, `request_id`, `tenant_id`, `user_id`, `method`, `endpoint`, `event`, `message`, `http_status`, `latency_ms`, `error_code`, `details` (serialized JSON).

**Important:** Each request may produce several service logs plus a gateway response log. Counting every 4xx/5xx log as a failed API request **double-counts** failures. Use `requests.csv` for request-level denominators or filter to `service=api-gateway` and `event=http.response`. Spans approximate dependencies; sequential durations are synthetic. Extra security and async-worker events are not unique customer requests.

### `requests.csv`
12,000 requests, one per `trace_id`, with request-level `status`, `latency_ms`, `error_code`, `region`, `endpoint`, `version`, and user/tenant IDs. This is the preferred table for SLA/SLO metrics.

### `metrics.csv`
576 rows (3 regions x 48 five-minute periods x 4 metrics). Fields: `timestamp`, `region`, `service`, `metric`, `value`, `unit`. Metrics: DB pool active connections, gateway heap utilization percentage, worker queue lag messages, and external payment provider p95 milliseconds.

## Investigation tasks
1. Establish baseline: total requests, error percentages, per-region throughput, latency p50/p95/p99.
2. Plot a five-minute time series of failed requests. Separate 4xx from 5xx; explain why 401/409 should not always be considered a server outage.
3. Rank microservices by ERROR logs, error codes, and dependency failure impact. Avoid double counting spans.
4. Reconstruct at least three failed checkout journeys via `trace_id` and `parent_span_id`.
5. Detect anomalous authentication attempts: source IP, timeline, failed user IDs, user agent, and rate.
6. Identify the payment degradation window, region, error codes, provider, and affected business endpoints.
7. Find competing hypotheses for checkout failure: inventory deadlock vs payment timeout vs DB connection pool exhaustion; explain impact and ordering.
8. Join infrastructure metrics by rounded five-minute timestamp + region to confirm/refute suspected causes.
9. Detect a version/region-specific regression following rollout of `v2.8.0`. Compare error rate and failure signatures with `v2.7.3`, controlling for route mix and time.
10. Identify the notification queue backlog. Distinguish successful order processing from delayed downstream emails.
11. Write a one-page incident report: impact, timeline, technical causes, evidence, actions, ownership, and follow-up validation.
12. Design at least five dashboard panels and six practical alert rules; include false-positive mitigation.

## Suggested deliverables
- Notebook or Python analysis (`analysis.py` starter included)
- Time-series plots, service error heatmap, and trace waterfall
- At least five SQL / Splunk / OpenSearch queries
- Root-cause report for leadership
- Five remediation tickets with priority and validation criteria

## Start
```bash
python analysis.py
```

Python's standard library is enough for `analysis.py`; optionally import the CSVs into SQLite, DuckDB, Pandas, Splunk, Elasticsearch, or OpenSearch.

## Suggested assessment rubric (100 points)
- Parsing, type handling, timestamps: 15
- Valid denominators and quantitative metrics: 20
- Correlation and root-cause investigation: 25
- Security anomaly analysis: 10
- Deployment and metric correlation: 15
- Incident communication and actions: 15

## Caveats
This is a **purpose-built teaching simulation**. It uses synthetic traffic, approximate spans, simplified queue metrics and deliberately planted patterns. The answer key is held separately in `INSTRUCTOR_ANSWER_KEY.md` so instructors can distribute only the data and case brief.
# Log-analysis
