# Authentication and security anomaly investigation

## Scope and method

Parsed the serialized `details` JSON object in each `application_logs.csv` row. Counts below use `auth-service` events and distinct `trace_id` values so the matching `api-gateway` HTTP response is not counted as another failed login. The dataset README describes this simulation as synthetic and deliberately uses reserved documentation IP ranges; therefore these indicators support investigation in the dataset, not attribution to a real actor.

## Findings

- **Failed-login events:** 201 `auth.login.failed` records, all HTTP 401 with `AUTH_INVALID_CREDENTIALS`; **201 distinct traces**.
- **Brute-force indicators:** 201 `security.brute_force_indicator` records; all 201 failed-login trace IDs have a matching indicator.
- **Shared source IP in details:** `198.51.100.77` appears on 201/201 failed-login events and the matching indicator IP agrees on 201/201 traces.
- **Affected users:** 195 unique user IDs. 6 users have two failed events each; the other 189 have one each.
- **Activity period (UTC):** 2026-11-18T09:55:02.496000+00:00 through 2026-11-18T10:29:46.695000+00:00 (34.74 minutes).
- **Peak five-minute bucket:** 2026-11-18T09:55:00+00:00 — 35 failures affecting 35 users (about 7.0 per minute).
- **Peak one-minute bucket:** 2026-11-18T10:00:00+00:00 — 11 distinct failed-login traces.
- **Client identifier:** `python-requests/2.32` appears on all 201 failed-login events.
- **Indicator risk scores:** 80–99; median 89.

## Suspicious source and field distinction

The explicit `source_ip` field on `auth.login.failed` is `198.51.100.77` for all flagged attempts. The separate `ip` field in those same failed-login detail objects varies across 148 values; it must not be substituted for `source_ip`. The security-indicator event stores the shared address under its `ip` key. The 201 matching indicator traces carry risk scores from 80 to 99.

The same source is associated with failures in multiple regions: `us-east-1` 142, `ap-south-1` 31, `eu-west-1` 28. This may reflect the synthetic data model; it does not, by itself, establish physical source location or infrastructure routing.

## Repeated users

| User ID | Failed events | First failed event (UTC) | Last failed event (UTC) |
| --- | ---: | --- | --- |
| `user-0665` | 2 | 2026-11-18T10:02:37.174000+00:00 | 2026-11-18T10:08:54.214000+00:00 |
| `user-1372` | 2 | 2026-11-18T09:58:31.605000+00:00 | 2026-11-18T10:01:00.344000+00:00 |
| `user-2047` | 2 | 2026-11-18T09:57:18.226000+00:00 | 2026-11-18T10:12:52.479000+00:00 |
| `user-2249` | 2 | 2026-11-18T10:04:28.966000+00:00 | 2026-11-18T10:16:41.840000+00:00 |
| `user-2451` | 2 | 2026-11-18T09:57:35.758000+00:00 | 2026-11-18T10:23:29.113000+00:00 |
| `user-2580` | 2 | 2026-11-18T10:14:58.687000+00:00 | 2026-11-18T10:29:36.429000+00:00 |

## Activity windows (five-minute UTC buckets)

| Window start (UTC) | Failed traces | Distinct users | Exact event span in bucket | Max risk score |
| --- | ---: | ---: | --- | ---: |
| 2026-11-18T09:55:00+00:00 | 35 | 35 | 2026-11-18T09:55:02.496000+00:00–2026-11-18T09:59:38.144000+00:00 | 99 |
| 2026-11-18T10:00:00+00:00 | 34 | 34 | 2026-11-18T10:00:02.605000+00:00–2026-11-18T10:04:52.409000+00:00 | 99 |
| 2026-11-18T10:05:00+00:00 | 26 | 26 | 2026-11-18T10:05:10.951000+00:00–2026-11-18T10:09:35.041000+00:00 | 99 |
| 2026-11-18T10:10:00+00:00 | 20 | 20 | 2026-11-18T10:10:06.413000+00:00–2026-11-18T10:14:58.687000+00:00 | 98 |
| 2026-11-18T10:15:00+00:00 | 33 | 33 | 2026-11-18T10:15:22.388000+00:00–2026-11-18T10:19:26.012000+00:00 | 99 |
| 2026-11-18T10:20:00+00:00 | 28 | 28 | 2026-11-18T10:20:38.196000+00:00–2026-11-18T10:24:52.645000+00:00 | 98 |
| 2026-11-18T10:25:00+00:00 | 25 | 25 | 2026-11-18T10:25:25.020000+00:00–2026-11-18T10:29:46.695000+00:00 | 99 |

## Trace-level duplication check

The matching API gateway has 201 `AUTH_INVALID_CREDENTIALS` response rows across 201 trace IDs; 201 overlap the auth-service failed-login traces. They are the corresponding outward responses, not additional login attempts. `security.brute_force_indicator` rows likewise match the failed-login traces and are treated as evidence attached to those attempts, not as extra failures.

## Caveats

- “Suspicious” here means the dataset explicitly labels the event with `security.brute_force_indicator`, and it shows high-volume, same-source failures across many users. Logs alone do not prove the intent or identity behind that source.
- The `attempt` field ranges from 10 to 895; its exact semantics are not documented, so it is reported only as a raw field in the evidence CSV, not treated as an account failure count.
- No successful authentication outcome is established by these records; do not infer account compromise from failed attempts alone.
- All IPs, users, and hosts in this teaching dataset are synthetic.

## Supporting evidence files

- [`security_login_failures.csv`](./security_login_failures.csv): one row per failed-login trace joined to its matching security indicator by `trace_id`.
- [`security_affected_users.csv`](./security_affected_users.csv): per-user failed-attempt counts and first/last timestamps.
- [`security_activity_5min.csv`](./security_activity_5min.csv): five-minute activity, distinct users, and risk score by source IP.
