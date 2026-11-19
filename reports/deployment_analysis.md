# Deployment comparison: v2.7.3 vs v2.8.0

## Method and definitions

HTTP error rate means **request-level HTTP 5xx responses divided by unique request `trace_id` counts** in `requests.csv`; 4xx counts are reported separately. Version, endpoint, region, and time groupings use request records. `NULL_CUSTOMER_CONTEXT` log events were linked to requests by `trace_id`; gateway responses are not counted as separate requests. Five-minute times are UTC bucket starts.

This is an observational comparison. `v2.8.0` occurs only in `us-east-1`, beginning at 11:45 UTC; it does not overlap with `v2.7.3` in that region at the same time. Version is therefore confounded with rollout time and region. Route-specific same-region comparisons help assess association but cannot fully isolate a causal release effect.

## Overall request-level rates

| version | requests | http_4xx | http_4xx_rate_pct | http_5xx | http_5xx_rate_pct | null_customer_context | other_http_5xx | first_request_utc | last_request_utc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v2.7.3 | 9561 | 573 | 5.99% | 575 | 6.01% | 0 | 575 | 2026-11-18 09:00:00.294+00:00 | 2026-11-18 12:59:58.468+00:00 |
| v2.8.0 | 2439 | 15 | 0.62% | 572 | 23.45% | 460 | 112 | 2026-11-18 11:45:01.445+00:00 | 2026-11-18 12:59:57.778+00:00 |

Overall `v2.8.0` had 572/2,439 5xx requests (23.45%) versus 575/9,561 (6.01%) for `v2.7.3`, a raw increase of 17.44 percentage points. The raw comparison mixes versions across regions and deployment periods.

## Error rates by endpoint and region

| version | region | endpoint | requests | http_4xx | http_5xx | http_5xx_rate_pct | null_customer_context | other_http_5xx |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v2.7.3 | ap-south-1 | /api/v1/cart | 256 | 22 | 4 | 1.56% | 0 | 4 |
| v2.7.3 | eu-west-1 | /api/v1/cart | 360 | 32 | 12 | 3.33% | 0 | 12 |
| v2.7.3 | us-east-1 | /api/v1/cart | 752 | 81 | 15 | 1.99% | 0 | 15 |
| v2.8.0 | us-east-1 | /api/v1/cart | 360 | 7 | 95 | 26.39% | 92 | 3 |
| v2.7.3 | ap-south-1 | /api/v1/checkout | 498 | 36 | 51 | 10.24% | 0 | 51 |
| v2.7.3 | eu-west-1 | /api/v1/checkout | 588 | 40 | 55 | 9.35% | 0 | 55 |
| v2.7.3 | us-east-1 | /api/v1/checkout | 1418 | 161 | 292 | 20.59% | 0 | 292 |
| v2.8.0 | us-east-1 | /api/v1/checkout | 616 | 8 | 224 | 36.36% | 160 | 64 |
| v2.7.3 | ap-south-1 | /api/v1/login | 309 | 31 | 1 | 0.32% | 0 | 1 |
| v2.7.3 | eu-west-1 | /api/v1/login | 373 | 28 | 5 | 1.34% | 0 | 5 |
| v2.7.3 | us-east-1 | /api/v1/login | 902 | 142 | 5 | 0.55% | 0 | 5 |
| v2.8.0 | us-east-1 | /api/v1/login | 417 | 0 | 108 | 25.90% | 103 | 5 |
| v2.7.3 | ap-south-1 | /api/v1/orders | 239 | 0 | 20 | 8.37% | 0 | 20 |
| v2.7.3 | eu-west-1 | /api/v1/orders | 353 | 0 | 36 | 10.20% | 0 | 36 |
| v2.7.3 | us-east-1 | /api/v1/orders | 753 | 0 | 56 | 7.44% | 0 | 56 |
| v2.8.0 | us-east-1 | /api/v1/orders | 355 | 0 | 140 | 39.44% | 105 | 35 |
| v2.7.3 | ap-south-1 | /api/v1/products | 510 | 0 | 3 | 0.59% | 0 | 3 |
| v2.7.3 | eu-west-1 | /api/v1/products | 682 | 0 | 8 | 1.17% | 0 | 8 |
| v2.7.3 | us-east-1 | /api/v1/products | 1568 | 0 | 12 | 0.77% | 0 | 12 |
| v2.8.0 | us-east-1 | /api/v1/products | 691 | 0 | 5 | 0.72% | 0 | 5 |

`v2.8.0` requests appear only in `us-east-1`. The per-endpoint same-region comparison below uses all observed `v2.7.3` requests in `us-east-1` as a route-specific reference, then applies each old-version route rate to the new-version route volume. This controls route mix but **not time-varying incident conditions**; it is descriptive, not a causal estimate.

| endpoint | requests_v2_7_3 | http_5xx_v2_7_3 | http_5xx_rate_pct_v2_7_3 | requests_v2_8_0 | http_5xx_v2_8_0 | http_5xx_rate_pct_v2_8_0 | null_customer_context | expected_v2_8_0_5xx_at_v2_7_3_rate | observed_minus_expected_5xx |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| /api/v1/cart | 752 | 15 | 1.99% | 360 | 95 | 26.39% | 92 | 7.2 | 87.8 |
| /api/v1/checkout | 1418 | 292 | 20.59% | 616 | 224 | 36.36% | 160 | 126.8 | 97.2 |
| /api/v1/login | 902 | 5 | 0.55% | 417 | 108 | 25.90% | 103 | 2.3 | 105.7 |
| /api/v1/orders | 753 | 56 | 7.44% | 355 | 140 | 39.44% | 105 | 26.4 | 113.6 |
| /api/v1/products | 1568 | 12 | 0.77% | 691 | 5 | 0.72% | 0 | 5.3 | -0.3 |

Applying these same-region route rates to 2,439 `v2.8.0` requests predicts about 168.0 5xx responses; 572 were observed (about 404.0 more). This excess is not solely attributable to deployment: the time period also contains the broader payment/database incident, and the versions do not overlap in the same region/time.

## `NULL_CUSTOMER_CONTEXT` evidence

There are 460 distinct request traces with `NULL_CUSTOMER_CONTEXT`; all are HTTP 500 requests on `v2.8.0` in `us-east-1`. No request with `v2.7.3` carries this error code. It appears in `auth-service` as `application.exception`, and the same traces have a gateway response. The auth-service log detail records feature flag `new-checkout-context` and stack `CheckoutContextResolver.resolve:118` on these exceptions.

First matching auth-service exception: 2026-11-18T11:45:17.800000+00:00. Last: 2026-11-18T12:39:52.443000+00:00. `v2.8.0` request traffic starts at 2026-11-18T11:45:01.445000+00:00. Requests continue on `v2.8.0` after 12:40 UTC, but no further `NULL_CUSTOMER_CONTEXT` request errors appear in the data. This cessation while the version remains active is evidence against attributing the pattern to an immutable version-only defect; a feature/configuration change or transient condition is possible but not established by these CSVs.

| endpoint | v2_8_requests | null_context_traces | rate_of_v2_8_endpoint_requests_pct | affected_users | first_event_utc | last_event_utc |
| --- | --- | --- | --- | --- | --- | --- |
| /api/v1/cart | 360 | 92 | 25.56% | 90 | 2026-11-18T11:45:28.919000+00:00 | 2026-11-18T12:39:37.257000+00:00 |
| /api/v1/checkout | 616 | 160 | 25.97% | 156 | 2026-11-18T11:45:31.603000+00:00 | 2026-11-18T12:39:40.939000+00:00 |
| /api/v1/login | 417 | 103 | 24.70% | 101 | 2026-11-18T11:45:25.426000+00:00 | 2026-11-18T12:39:52.443000+00:00 |
| /api/v1/orders | 355 | 105 | 29.58% | 103 | 2026-11-18T11:45:17.800000+00:00 | 2026-11-18T12:39:16.806000+00:00 |

## Five-minute time series for v2.8.0

| interval_5m_utc | region | requests | http_4xx | http_5xx | http_5xx_rate_pct | null_customer_context | other_http_5xx |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-18T11:45:00+00:00 | us-east-1 | 147 | 15 | 63 | 42.86% | 42 | 21 |
| 2026-11-18T11:50:00+00:00 | us-east-1 | 160 | 0 | 64 | 40.00% | 47 | 17 |
| 2026-11-18T11:55:00+00:00 | us-east-1 | 166 | 0 | 59 | 35.54% | 37 | 22 |
| 2026-11-18T12:00:00+00:00 | us-east-1 | 174 | 0 | 75 | 43.10% | 50 | 25 |
| 2026-11-18T12:05:00+00:00 | us-east-1 | 167 | 0 | 46 | 27.54% | 44 | 2 |
| 2026-11-18T12:10:00+00:00 | us-east-1 | 171 | 0 | 55 | 32.16% | 54 | 1 |
| 2026-11-18T12:15:00+00:00 | us-east-1 | 162 | 0 | 35 | 21.60% | 31 | 4 |
| 2026-11-18T12:20:00+00:00 | us-east-1 | 159 | 0 | 31 | 19.50% | 29 | 2 |
| 2026-11-18T12:25:00+00:00 | us-east-1 | 162 | 0 | 48 | 29.63% | 45 | 3 |
| 2026-11-18T12:30:00+00:00 | us-east-1 | 162 | 0 | 48 | 29.63% | 47 | 1 |
| 2026-11-18T12:35:00+00:00 | us-east-1 | 155 | 0 | 36 | 23.23% | 34 | 2 |
| 2026-11-18T12:40:00+00:00 | us-east-1 | 164 | 0 | 3 | 1.83% | 0 | 3 |
| 2026-11-18T12:45:00+00:00 | us-east-1 | 164 | 0 | 2 | 1.22% | 0 | 2 |
| 2026-11-18T12:50:00+00:00 | us-east-1 | 166 | 0 | 3 | 1.81% | 0 | 3 |
| 2026-11-18T12:55:00+00:00 | us-east-1 | 160 | 0 | 4 | 2.50% | 0 | 4 |

By endpoint, the context error rate was 92/360 cart requests (25.56%), 160/616 checkout requests (25.97%), 103/417 login requests (24.70%), and 105/355 orders requests (29.58%). Products had zero context errors (0/691); its 5xx rate was 0.72% on `v2.8.0`, close to the same-region `v2.7.3` rate of 0.77%.

Before 12:40 UTC, 1,785 `v2.8.0` requests had 560 5xx responses (31.37%), including 460 context errors. From 12:40 UTC to the end of the dataset, 654 `v2.8.0` requests had 12 5xx responses (1.83%) and zero context errors.

## Determination and uncertainty

**Evidence supports a likely `v2.8.0`-associated regression in the new checkout-context path, but it does not prove that the deployment caused all incident failures.** The strongest signal is 460 trace-linked `NULL_CUSTOMER_CONTEXT` exceptions, all on `v2.8.0`, across four routes and starting shortly after the version first appears; matching logs identify `new-checkout-context` and `CheckoutContextResolver.resolve:118`. Route baseline comparison also shows elevated 5xx rates for cart, checkout, login, and orders, while products are essentially unchanged.

Important limits: `v2.8.0` is present only in `us-east-1` after 11:45 UTC, so there is no same-region, same-time old-version control. `v2.7.3` already has failures before rollout (including payment timeouts and other errors), and region/time changes coincide with these independent incident conditions. The context errors stop after 12:39 while `v2.8.0` traffic continues. These data support association with the new version/feature path, not definitive release causation; they also do not support claiming that `v2.8.0` introduced the entire outage.

For stronger attribution, compare an exact rollout/feature-flag change timeline, inspect code/configuration at `CheckoutContextResolver.resolve:118`, and use a controlled canary or rollback/flag-off comparison with the same route, region, and time mix.

## Supporting evidence files

- [`deployment_version_summary.csv`](./deployment_version_summary.csv): aggregate request-level rates and coverage by version.
- [`deployment_endpoint_region.csv`](./deployment_endpoint_region.csv): version × endpoint × region counts/rates.
- [`deployment_route_comparison.csv`](./deployment_route_comparison.csv): same-region route-rate comparison and route-mix projection.
- [`deployment_5min.csv`](./deployment_5min.csv): five-minute version × region counts, rates, and error-code counts.
- [`deployment_error_codes.csv`](./deployment_error_codes.csv): request-level error-code counts by version.
- [`null_customer_context_traces.csv`](./null_customer_context_traces.csv): each affected request trace joined to its auth-service exception.
