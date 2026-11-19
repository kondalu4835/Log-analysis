# ShopSphere Incident Post-Mortem

**Incident window:** November 18, 2026, 09:00-13:00 UTC  
**Scope:** Synthetic case-study data from `requests.csv`, `application_logs.csv`, and `metrics.csv`.

## Incident Timeline

| Time (UTC) | Event |
|---|---|
| 09:02 | First isolated HTTP 5xx in the request data. The 09:00-10:00 baseline averaged 1.67% 5xx. |
| 09:55-10:29 | 201 failed-login traces and matching security indicators came from the same recorded source IP across regions. No evidence links this activity to the later service failures. |
| 10:45 | Sharp increase in errors and latency. The five-minute bucket had 30/250 5xx (12%); a checkout payment timeout was logged at 10:45:12.872. The elevated 5xx period continued through the 12:35 bucket; the 12:40 bucket fell to 2%. |
| 11:05 | Inventory deadlock errors began. The dataset records 387 HTTP 409 inventory-conflict requests across the three regions. |
| 11:25 | First order database pool exhaustion. The service log reported 30 active connections out of a maximum of 30. There were 311 matching HTTP 503 requests in total. This began after the 10:45 elevated-error onset. |
| 11:45 | `v2.8.0` traffic appeared in `us-east-1`. The first `NULL_CUSTOMER_CONTEXT` exception followed at 11:45:17.800. |
| 12:00 | Worst overall five-minute interval: 94/250 requests returned 5xx (37.6%). |
| 12:39-12:40 | Last logged null-context exception occurred at 12:39:52.443. The next five-minute bucket had a 2% 5xx rate; residual errors remained. |

## Impact

- **12,000 requests** were recorded. **1,147 (9.56%)** returned HTTP 5xx: 657 status 500, 311 status 503, and 179 status 504.
- **Checkout** was most affected by server errors: 622/3,120 requests (19.94%). Orders had 252/1,700 5xx (14.82%).
- Overall request latency was p50 76 ms, p95 1,921 ms, and p99 4,115 ms. During the incident, the highest five-minute p95 was approximately 5.1 seconds in `us-east-1`.
- The 201 HTTP 401 login rejections and 387 HTTP 409 inventory conflicts are reported separately from 5xx service failures.
- Notification processing was delayed: 66 queue-lag warnings were logged, and queue lag peaked at 6,476 messages. The data does not show that this caused order failures.
- The data is synthetic and covers only 09:00-13:00 UTC; impact outside this window is unknown.

## Root Cause

**No single incident-wide root cause is confirmed.** The records show several proximate failure mechanisms, with different start times:

- **Payment dependency timeouts** initiated the pronounced 10:45 degradation in `us-east-1`. There were 179 `PAYMENT_PROVIDER_TIMEOUT` requests. Provider p95 latency peaked at 5,804 ms at 10:50, alongside 21 payment-timeout requests in that region and interval. The temporal correlation is strong, but the logs do not independently prove an external provider outage or its initiating cause.
- **Database pool exhaustion** contributed later. The order service reported no available connection, with `pool_active=30` and `pool_max=30`. Because this began about 40 minutes after the elevated 5xx onset, it does not explain the start of the incident, though it explains later 503s.
- **Inventory transaction deadlocks** produced 387 HTTP 409 conflicts. Their underlying transaction or lock-order cause is not established by the logs.
- **A likely `v2.8.0`/feature-path regression** produced 460 `NULL_CUSTOMER_CONTEXT` HTTP 500s across checkout, cart, login, and orders. The matching auth-service exceptions name `new-checkout-context` and `CheckoutContextResolver.resolve:118`. All occurred on `v2.8.0` in `us-east-1`, shortly after rollout. This is strong association, not proof that the release caused every error: version, region, and time are confounded, and the context errors stopped while `v2.8.0` traffic continued.
- **Memory pressure is not established as a cause.** Heap reached 96% after the elevated 5xx period had subsided. The CSV contains no CPU metric, so CPU cannot be assessed.

## Recommended Fixes

1. **Contain and fix the context exception:** review `CheckoutContextResolver.resolve:118` and the `new-checkout-context` flag path; validate required context and add safe handling. Canary by route and region, with automatic rollback on new-version 5xx or null-context exceptions.
2. **Stabilize payment calls:** verify provider-side telemetry, cap retries with a retry budget and jitter, and use a circuit breaker and idempotency protections. Alert on provider latency and timeout rate by region.
3. **Investigate database saturation:** determine why all 30 connections were occupied; inspect connection lifecycle, query duration, waits, and pool sizing. Add alerts for pool saturation and `DB_POOL_EXHAUSTED` request rate.
4. **Reduce inventory deadlocks:** inspect transaction lock ordering and hot inventory records; add concurrency/deadlock regression tests and only retry conflicts with bounded backoff and idempotency.
5. **Keep asynchronous notifications isolated:** drain and scale the mailer queue safely, use idempotent consumers, and alert on oldest-message age separately from checkout health.
6. **Improve release and incident controls:** use staged rollout and route/region/version dashboards; page on sustained request-level 5xx and latency with minimum-volume safeguards. Do not count gateway and service log records as separate failed requests.
7. **Validate recovery:** replay representative traces and run a matched canary. Confirm 5xx and p95 return to baseline, the context exception does not recur, DB pool use stays below its limit, payment timeouts fall, inventory remains consistent, and notification backlog drains.

Correlation and timing support these actions but do not by themselves prove causation. See [the detailed RCA](./INCIDENT_RCA.md), [deployment analysis](./deployment_analysis.md), and [metric correlation evidence](./metric_correlation.md) for supporting counts and limitations.