import argparse
import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


REQUESTS_FILE = Path(__file__).resolve().with_name("requests.csv")


def load_requests(path):
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            try:
                row["timestamp"] = datetime.fromisoformat(
                    row["timestamp"].replace("Z", "+00:00")
                )
                row["status"] = int(row["status"])
            except (KeyError, TypeError, ValueError):
                continue
            yield row


def bucket_start(timestamp, interval_minutes):
    minute = (timestamp.minute // interval_minutes) * interval_minutes
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def print_timeseries(requests, interval_minutes, threshold_percent):
    buckets = defaultdict(list)
    for request in requests:
        start = bucket_start(request["timestamp"], interval_minutes)
        buckets[start].append(request)

    elevated = []
    print("Interval (UTC) | Requests | 4xx | 5xx | 4xx rate | 5xx rate | High 5xx")
    for start, rows in sorted(buckets.items()):
        total = len(rows)
        count_4xx = sum(400 <= row["status"] < 500 for row in rows)
        count_5xx = sum(500 <= row["status"] < 600 for row in rows)
        rate_4xx = 100 * count_4xx / total
        rate_5xx = 100 * count_5xx / total
        high = rate_5xx >= threshold_percent
        print(
            f"{start:%Y-%m-%d %H:%M} | {total:8} | {count_4xx:3} | {count_5xx:3} "
            f"| {rate_4xx:7.2f}% | {rate_5xx:7.2f}% | {'YES' if high else ''}"
        )
        if high:
            elevated.append((start, rows))

    if not elevated:
        print(f"\nNo interval reached the {threshold_percent:.2f}% 5xx threshold.")
        return

    windows = []
    window_start = previous_start = elevated[0][0]
    window_rows = list(elevated[0][1])
    step = timedelta(minutes=interval_minutes)
    for start, rows in elevated[1:]:
        if start != previous_start + step:
            windows.append((window_start, previous_start, window_rows))
            window_start = start
            window_rows = []
        window_rows.extend(rows)
        previous_start = start
    windows.append((window_start, previous_start, window_rows))

    print(f"\nHigh-error windows (5xx rate >= {threshold_percent:.2f}%):")
    for start, last_start, rows in windows:
        end = last_start + step
        failed_requests = [row for row in rows if 500 <= row["status"] < 600]
        first_error = min(row["timestamp"] for row in failed_requests)
        last_error = max(row["timestamp"] for row in failed_requests)
        print(f"  Buckets: {start:%Y-%m-%d %H:%M} to {end:%H:%M} UTC (end exclusive)")
        print(f"  First 5xx request: {first_error.isoformat()}")
        print(f"  Last 5xx request:  {last_error.isoformat()}")


def main():
    parser = argparse.ArgumentParser(
        description="Print request error rates over time and flag high-5xx intervals."
    )
    parser.add_argument(
        "--interval-minutes", type=int, default=5, help="Bucket size in minutes (default: 5)."
    )
    parser.add_argument(
        "--threshold-percent",
        type=float,
        default=5.0,
        help="5xx rate used to flag high-error intervals (default: 5).",
    )
    args = parser.parse_args()
    if not 1 <= args.interval_minutes <= 60:
        parser.error("--interval-minutes must be between 1 and 60")
    if not 0 <= args.threshold_percent <= 100:
        parser.error("--threshold-percent must be between 0 and 100")

    if not REQUESTS_FILE.is_file():
        parser.exit(1, f"Missing input file: {REQUESTS_FILE}\n")
    print_timeseries(
        load_requests(REQUESTS_FILE), args.interval_minutes, args.threshold_percent
    )


if __name__ == "__main__":
    main()