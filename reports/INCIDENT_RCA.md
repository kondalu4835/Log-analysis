# ShopSphere incident review and root-cause assessment

**Incident data window:** 2026-11-18 09:00–13:00 UTC  
**Assessment status:** Evidence-based; incident-wide root cause not confirmed  
**Dataset note:** The supplied case study describes a synthetic teaching simulation. IPs, users, hosts, and transactions are fictional.

## 1. Executive summary

During the four-hour data window, the request dataset contains **12,000 requests**: 10,265 HTTP 200, 201 HTTP 401, 387 HTTP 409, and **1,147 HTTP 5xx**. The request-level 5xx rate is **9.56%**. The most affected business endpoint by 5xx count is checkout: **622/3,120 (19.94%)**. Orders has 252/1,700 (14.82%), cart 126/1,728 (7.29%), login 119/2,001 (5.95%), and products 28/3,451 (0.81%). The 401 and 409 responses are reported separately from server errors; they should not be added to the 5xx total.

The strongest acute degradation begins at **10:45 UTC**: that five-minute bucket has 30/250 5xx (12.00%) and request p95 latency of 4,640.65 ms, versus the 09:00–10:00 baseline mean 5xx rate of 1.67% and median interval p95 of 195.70 ms. Errors and latency remain elevated through 12:35. The maximum five-minute 5xx rate is **37.60% at 12:00** (94/250). At 12:40, the rate falls to 2.00% (5/250), near the baseline, but residual 5xxs continue.

**No single incident-wide root cause is confirmed by the available data.** The records do confirm multiple proximate failure mechanisms: payment timeouts, inventory deadlocks, order database pool exhaustion, and a later `NULL_CUSTOMER_CONTEXT` exception cluster. The `v2.8.0`/`new-checkout-context` association is strong for the latter cluster, but version, region, and time are confounded. Provider latency and payment timeouts co-occur, but the dataset does not independently establish an external provider outage as the initiating cause. Notification backlog is evidenced as asynchronous delivery delay, not as a demonstrated cause of checkout failures.

## 2. Incident timeline

Times are UTC. “Verified” entries below are observations in the supplied CSVs; they do not imply causal attribution beyond the recorded event.

| Time | Verified evidence | Interpretation |
|---|---|---|
| 09:02:32.440 | First request-level 5xx: `TRANSIENT_FAILURE`, HTTP 500, `/api/v1/orders`, `eu-west-1`, trace `1de86a4d0a84c18238da2d843cc54515`. | Isolated 5xxs predate the acute degradation; 10:45 is the sharp escalation, not the first error. |
| 09:00–10:00 | Across 12 five-minute intervals, mean 5xx rate is 1.67%; median interval p95 latency is 195.70 ms. | Reference baseline used by the timeline analysis. |
| 09:55:02–10:29:46 | 201 distinct auth failure traces and 201 matching brute-force indicators; all failed-login records use `source_ip=198.51.100.77`, across 195 users. | A separate security anomaly. The supplied README identifies all addresses as synthetic documentation IPs. No evidence ties it to the later 5xx surge. |
| 10:45 | 30/250 requests are 5xx (12.00%); p95 is 4,640.65 ms. First payment timeout log occurs at 10:45:12.872 in `us-east-1`. | Start of the pronounced request failure and latency escalation. |
| 10:46:57 onward | `notification-worker` emits `queue.consumer.lag` WARN records; 66 distinct warning traces occur through 11:55:09.937. | Confirms notification delay warnings, not failed customer requests. |
| 11:05:09 onward | First `INVENTORY_DEADLOCK` event; 387 distinct request traces end in HTTP 409, across all three regions. | Inventory contention/conflict adds checkout and cart failures, distinct from 5xxs. |
| 11:25:14 onward | First `DB_POOL_EXHAUSTED` log. The `order-service` records show `pool_active=30`, `pool_max=30`; 311 matching request traces end in HTTP 503 through 12:04:57.647. | Direct evidence that the order-service pool was at its recorded maximum when these exhaustion errors were logged. Why it saturated is not established. |
| 11:45:01–11:45:18 | First `v2.8.0` request at 11:45:01.445; first `NULL_CUSTOMER_CONTEXT` auth exception at 11:45:17.800. At the 11:45 interval, the request dataset has 82/250 5xx overall. | New version and error signature begin nearly together in `us-east-1`. |
| 12:00 | Worst five-minute request interval: 94/250 5xx (37.60%); p95 3,604.25 ms. | Peak measured request-level failure rate. |
| 12:39:52–12:40 | Last observed `NULL_CUSTOMER_CONTEXT` auth exception at 12:39:52.443. The next interval has 5/250 5xx (2.00%) and p95 201 ms. | Abrupt improvement; records do not identify what changed. |
| 12:40–13:00 | 21/1,000 requests are 5xx (2.10%); all four interval p95 values are approximately 188–213 ms. | Near-baseline behavior in the remaining sampled period, not proof of complete recovery beyond the data window. |

Five-minute rates and latency are plotted in [error_timeline.png](../charts/error_timeline.png); the values are in [error_timeline.csv](./error_timeline.csv).

## 3. Customer impact

### Request-level outcomes

| Outcome | Requests | Share of 12,000 |
|---|---:|---:|
| HTTP 200 | 10,265 | 85.54% |
| HTTP 401 | 201 | 1.68% |
| HTTP 409 | 387 | 3.23% |
| HTTP 500 | 657 | 5.48% |
| HTTP 503 | 311 | 2.59% |
| HTTP 504 | 179 | 1.49% |

The 5xx total is **1,147 (9.56%)**. Overall request latency is p50 76 ms, p95 1,921.05 ms, p99 4,115.01 ms, and max 6,322 ms. These are sample-wide statistics, not an estimate of every customer’s experience.

### Endpoint and regional distribution

| Endpoint | Requests | 5xx | 5xx rate |
|---|---:|---:|---:|
| `/api/v1/checkout` | 3,120 | 622 | 19.94% |
| `/api/v1/orders` | 1,700 | 252 | 14.82% |
| `/api/v1/cart` | 1,728 | 126 | 7.29% |
| `/api/v1/login` | 2,001 | 119 | 5.95% |
| `/api/v1/products` | 3,451 | 28 | 0.81% |

The `us-east-1` request cohort has 952/7,832 5xx (12.16%); `eu-west-1` has 116/2,356 (4.92%); `ap-south-1` has 79/1,812 (4.36%). The distribution indicates greater impact in `us-east-1`, but these rates also reflect different versions, routes, and time periods.

## 4. Affected microservices

The log counts below are **ERROR-level events**, not unique failed requests. A request can produce a service error and a later gateway response; do not sum service counts as customer-impact totals.

| Service | ERROR log events | Verified signature in records |
|---|---:|---|
| `api-gateway` | 1,147 | HTTP response records reporting request 5xx errors; all match a preceding same-trace service error with the same code in the service analysis. |
| `auth-service` | 510 | 460 `NULL_CUSTOMER_CONTEXT` exceptions; 50 `TRANSIENT_FAILURE` errors. Separately, 201 failed-login WARN records and matching security indicators. |
| `inventory-service` | 418 | 387 `INVENTORY_DEADLOCK`; 31 `TRANSIENT_FAILURE`. |
| `order-service` | 332 | 311 `DB_POOL_EXHAUSTED`; 21 `TRANSIENT_FAILURE`. |
| `payment-service` | 192 | 179 `PAYMENT_PROVIDER_TIMEOUT`; 13 `TRANSIENT_FAILURE`. |
| `cart-service` | 35 | `TRANSIENT_FAILURE` records. |
| `catalog-service` | 28 | `TRANSIENT_FAILURE` records. |
| `notification-worker` | 19 | `TRANSIENT_FAILURE` ERROR records; additionally, 66 queue-lag WARN traces. |

The service/region distribution is shown in [service_region_error_heatmap.png](../charts/service_region_error_heatmap.png). Gateway dominance in ERROR count is a reporting effect for these matching failures, not evidence that the gateway initiated them.

## 5. Confirmed root cause

**An incident-wide root cause is not confirmed by the supplied evidence.** The records do not establish one initiating event that explains every failure mode. They do establish the following proximate mechanisms:

1. **Payment timeout failures:** 179 request traces carry `PAYMENT_PROVIDER_TIMEOUT` and HTTP 504; the matching `payment-service` logs emit `payment.gateway.timeout`. The details identify provider `PayBridge`, upstream `payments.partner.example`, and retry/timeout fields. This confirms timeout behavior in the application, not an independently verified provider outage or why the timeout began.
2. **Inventory deadlocks:** 387 request traces carry `INVENTORY_DEADLOCK` and HTTP 409; matching `inventory-service` `inventory.tx.deadlock` records exist in all three regions. Logged lock waits range from 772 to 2,642 ms. This confirms a conflict/deadlock failure signature, not the transaction-level defect that created contention.
3. **Order database pool exhaustion:** 311 request traces carry `DB_POOL_EXHAUSTED` and HTTP 503; matching `order-service` logs report no available connection with `pool_active=30`, `pool_max=30`, and wait times. This confirms pool exhaustion at the logged limit, not the underlying cause of saturation (for example, demand, long-held connections, leaks, or query delays).
4. **Customer-context exceptions:** 460 request traces are HTTP 500 with `NULL_CUSTOMER_CONTEXT`; corresponding `auth-service` exceptions include feature flag `new-checkout-context` and stack `CheckoutContextResolver.resolve:118`. This confirms the exception path and tight association with `v2.8.0`; it does not prove which code/configuration change produced a null context.

Representative trace evidence:

| Failure signature | Trace ID | Request timestamp (UTC) | Request outcome | Earliest matching service event |
|---|---|---|---|---|
| Payment timeout | `41f4a967518b03f200b3b941c8dda779` | 10:45:12.722 | Checkout HTTP 504, 4,852 ms | `payment-service` `payment.gateway.timeout` at 10:45:12.872 |
| Inventory deadlock | `6b9e60b66c1e9473819d159144799ad4` | 11:05:09.422 | Checkout HTTP 409 | `inventory-service` `inventory.tx.deadlock` at 11:05:09.470 |
| Database pool exhaustion | `857e4cedd63fdc92adcb140612736285` | 11:25:14.709 | Checkout HTTP 503, 3,958 ms | `order-service` `db.pool.exhausted` at 11:25:14.792 |
| Context exception | `724198908c1f0229b9ed1e1d7c15023b` | 11:45:17.784 | Orders HTTP 500, 802 ms | `auth-service` `application.exception` at 11:45:17.800 |
| Earlier transient error | `1de86a4d0a84c18238da2d843cc54515` | 09:02:32.440 | Orders HTTP 500 | Request and related logs report `TRANSIENT_FAILURE` |

The service log is recorded before the corresponding gateway response in these representative traces. This supports service-side proximate attribution; it is not proof of the deeper root cause.

## 6. Contributing factors and hypotheses

### Verified contributing conditions

- **Several failure mechanisms overlapped.** Payment timeouts were logged from 10:45:12.872 to 11:34:07.092; inventory deadlocks from 11:05:09.470 to 11:49:54.014; database pool exhaustion from 11:25:14.792 to 12:04:57.647; and context exceptions from 11:45:17.800 to 12:39:52.443.
- **Retries/timeouts and contention merit review.** Payment details record four retries and a 2,500 ms timeout setting in representative events; DB error details record wait time; inventory logs record lock waits. These data show the settings/conditions, not that retry policy or lock handling caused the incident.
- **Notification work backed up.** The metric peaks at 6,476 queued messages (`eu-west-1`, 11:35); the logs contain 66 `QUEUE_CONSUMER_LAG` WARN traces from 10:46:57.194 to 11:55:09.937, with messages stating that order email was delayed. This is evidence of downstream notification delay, not failed order processing.
- **Heap utilization rose after the worst request-failure peak.** The API gateway heap metric reaches 96% in `us-east-1` at 12:45–12:55, when 2–4 5xx requests occur per five-minute interval. Its Pearson association is 0.332 with request 5xx counts and 0.228 with non-gateway ERROR traces across the 144 region-interval observations. This timing does not establish heap pressure as the cause of the earlier spike.
- **Security anomaly coincided earlier in the day.** 201 failed logins from the synthetic `198.51.100.77` source field affect 195 user IDs between 09:55:02 and 10:29:46. No evidence in the reviewed records ties this episode to the later payment, DB, inventory, or context failures.

### Hypotheses requiring corroboration

- **Likely `v2.8.0`/feature-path regression:** all 460 context failures occur on `v2.8.0` in `us-east-1`; the first request version appears at 11:45:01.445 and the first exception follows at 11:45:17.800. However, the version appears only in that region after 11:45, so version, region, and time are confounded. The errors stop after 12:39 while `v2.8.0` requests continue, which is not explained by an immutable version-only defect. A flag/configuration change or transient condition is possible but unverified.
- **External payment dependency degradation:** provider p95 latency and payment timeout counts have Pearson correlation 0.853 over 144 aligned region/intervals; at 10:50 in `us-east-1`, provider p95 is 5,804 ms and 21 requests have payment timeout codes. This is strong temporal association, not proof the provider initiated the issue.
- **DB pool pressure as a downstream effect or independent contributor:** pool saturation coincides with `DB_POOL_EXHAUSTED` errors (Pearson 0.637). The records do not distinguish a capacity limit from connection leaks, query stalls, traffic pressure, or another upstream condition.
- **Queue backlog and heap pressure as contributors:** both are observed, but queue lag is weakly correlated with HTTP 5xx counts (Pearson 0.197); heap peaks after the worst 5xx period. Neither is demonstrated as a cause of customer-facing failures.

Correlation coefficients and interval evidence are summarized in [metric_correlation.md](./metric_correlation.md), with the full join in [metric_correlation_evidence.csv](./metric_correlation_evidence.csv).

## 7. Supporting traces and evidence

The four detailed checkout traces, event sequences, and waterfall are in [checkout_traces.md](./checkout_traces.md) and [checkout_trace_waterfall.png](../charts/checkout_trace_waterfall.png). The trace IDs in the preceding table are actual IDs from the request and application log datasets.

Other evidence sources reviewed:

- Request totals, status counts, validation, and latency: [summary.json](./summary.json), [http_status_counts.csv](./http_status_counts.csv), [latency_overall.csv](./latency_overall.csv).
- Five-minute request failures and latency: [error_timeline.csv](./error_timeline.csv), [error_timeline.png](../charts/error_timeline.png).
- Service-level logs, event counts, and region distribution: [service_analysis.md](./service_analysis.md), [service_error_groups.csv](./service_error_groups.csv), [ranked_error_codes.csv](./ranked_error_codes.csv), [service_analysis.csv](./service_analysis.csv), [service_region_error_heatmap.png](../charts/service_region_error_heatmap.png).
- Version and context-error analysis: [deployment_analysis.md](./deployment_analysis.md), [deployment_version_summary.csv](./deployment_version_summary.csv), [deployment_endpoint_region.csv](./deployment_endpoint_region.csv), [deployment_5min.csv](./deployment_5min.csv), [deployment_route_comparison.csv](./deployment_route_comparison.csv), [null_customer_context_traces.csv](./null_customer_context_traces.csv).
- Authentication anomaly: [security_anomalies.md](./security_anomalies.md), [security_login_failures.csv](./security_login_failures.csv), [security_activity_5min.csv](./security_activity_5min.csv).

## 8. Immediate mitigation recommendations

These are recommended response actions, not actions confirmed by the dataset.

1. **Payment:** Use a bounded circuit breaker and carefully bounded retries with idempotency protection; verify provider health and latency directly. Avoid retry amplification while upstream latency is high.
2. **Order database:** Check live active/idle/waiting connections, query duration, pool configuration, and connection lifecycle; control concurrent DB work and protect the pool while diagnosing why all 30 connections are occupied.
3. **Inventory:** Reduce conflicting write concurrency if needed; use bounded deadlock retries with jitter and inspect lock ordering/hot SKUs. Confirm inventory correctness before replaying or retrying failed reservations.
4. **`v2.8.0`:** If the exception path is still active, disable `new-checkout-context` or roll back through the established release process while preserving evidence. Validate by route and region, not only aggregate rate.
5. **Notifications:** Scale or drain the `order-events` / `mailer-v2` backlog with rate limits and idempotent consumers; reconcile pending notifications against completed orders and communicate delays without treating email lag as a failed order.
6. **Authentication anomaly:** Investigate and apply rate limiting/account protections against the synthetic source only within this simulation. Do not block a real address based solely on these synthetic records.

## 9. Permanent corrective actions

- Add payment dependency timeouts, circuit breaking, idempotency, and retry budgets; test degraded-provider behavior.
- Review order-service pool sizing and connection ownership, add leak detection and query/connection duration telemetry, and load-test exhaustion recovery.
- Fix inventory transaction lock ordering and add contention/deadlock regression tests for concurrent reservations.
- Add validation and safe fallback handling for customer context in `CheckoutContextResolver`; test the `new-checkout-context` path across affected endpoints. Gate rollout by region and cohort with automated rollback criteria.
- Make notification consumers idempotent and autoscale on queue age/lag; define a user-visible notification-delay SLO distinct from order-processing success.
- Preserve `trace_id` and span-level dependency timing consistently; distinguish source-service exceptions from gateway response logs and async worker events.
- Improve security telemetry schema documentation so `source_ip`, `ip`, and `client_ip` semantics cannot be confused; add per-account and per-source rate controls with false-positive safeguards.

## 10. Monitoring improvements

Add regional, endpoint-, version-, and service-level dashboards and alerts. Suggested initial thresholds are operational starting points and should be tuned against real baselines:

| Signal | Suggested alert | Noise control |
|---|---|---|
| Gateway/request 5xx and latency | 5xx >5% for 5 minutes, or p95 >1 s for 5 minutes | Require a minimum request volume; split by region and endpoint; exclude expected 4xx. |
| Payment provider | Provider p95 >1 s or payment timeout rate >2% for 5 minutes | Alert on sustained windows; show provider/region and request count; distinguish provider timeouts from other 5xx. |
| Order DB pool | Active connections at configured max, or `DB_POOL_EXHAUSTED` >0.5% for 3 minutes | Alert on both saturation and user-visible errors; use actual configured limit and suppress low-volume noise. |
| Inventory locking | Deadlocks >1% of reservation attempts for 5 minutes | Normalize by attempt volume and alert on distinct affected traces, not duplicate log lines. |
| Deployment/context exception | Any `NULL_CUSTOMER_CONTEXT` on a new version, or elevated new-version 5xx against a matched route/region cohort | Canary by endpoint and region; require adequate denominator; automated rollback only after confirmation. |
| Notification backlog | Queue age >5 minutes or lag >1,000 messages for 10 minutes | Pair lag with consumer throughput and oldest-message age; notify async owner separately from checkout paging. |
| Heap / process health | Heap >85% for 10 minutes with GC pause or latency/error increase | Do not page on heap alone; correlate with GC, restarts, and customer-impact metrics. |
| Authentication abuse | Source failures >20/minute or many distinct accounts in a short window | Combine source and account signals; allow trusted automation and use progressive challenge/rate limit before hard blocks. |

Track error-budget burn using a stated service objective and request-level gateway outcomes; do not infer an SLO from this dataset. Preserve distinct-request denominators and annotate deployments, feature-flag changes, and dependency incidents on time-series charts.

## 11. Verification plan

After mitigations or fixes, replay representative traces and run a controlled canary with the same route, region, and time mix. Confirm that:

- 5xx rates and p95 latency return to a stable, pre-incident baseline across regions and endpoints;
- `PAYMENT_PROVIDER_TIMEOUT`, `DB_POOL_EXHAUSTED`, and `INVENTORY_DEADLOCK` rates fall without retry amplification or incorrect inventory/order state;
- `NULL_CUSTOMER_CONTEXT` does not recur on the feature-enabled path and the result holds across a representative canary period;
- queue lag and oldest notification age drain while order records remain correct;
- alerts fire on synthetic threshold tests and remain quiet on expected 401/409 traffic.

The supplied records cover only 09:00–13:00 UTC and do not include deployment-control history, provider-side telemetry, DB query/connection lifecycle traces, source code, or post-incident remediation records. Therefore they support a bounded, multi-symptom RCA—not a definitive causal narrative or proof that any recommended action was taken.
