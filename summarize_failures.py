import csv
from collections import Counter, defaultdict
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def summarize_failures(requests, application_logs):
    status_counts = Counter()
    endpoint_failures = defaultdict(Counter)
    for request in requests:
        try:
            status = int(request["status"])
        except (KeyError, TypeError, ValueError):
            continue
        status_counts[status] += 1
        if status >= 400:
            endpoint = f"{request.get('method', '')} {request.get('endpoint', '')}".strip()
            endpoint_failures[endpoint]["failures"] += 1
            if 500 <= status < 600:
                endpoint_failures[endpoint]["5xx"] += 1

    service_errors = Counter(
        log.get("service", "unknown")
        for log in application_logs
        if log.get("level", "").upper() == "ERROR"
    )
    server_errors = Counter(
        status for status, count in status_counts.items() if 500 <= status < 600
        for _ in range(count)
    )

    failed_requests = sum(count for status, count in status_counts.items() if status >= 400)
    total_5xx = sum(server_errors.values())

    print("Request-level totals (from requests.csv)")
    print(f"Total requests: {sum(status_counts.values()):,}")
    print(f"Total failed requests (HTTP 4xx and 5xx): {failed_requests:,}")
    print(f"Total HTTP 5xx responses: {total_5xx:,}")
    print("HTTP 5xx status codes:")
    if server_errors:
        for status, count in sorted(server_errors.items()):
            print(f"  {status}: {count:,}")
    else:
        print("  None")

    print("\nFailed requests by endpoint")
    print("Endpoint | Failures (4xx + 5xx) | 5xx")
    for endpoint, counts in sorted(
        endpoint_failures.items(), key=lambda item: (-item[1]["failures"], item[0])
    ):
        print(f"{endpoint} | {counts['failures']:,} | {counts['5xx']:,}")

    print("\nERROR log records by service (from application_logs.csv)")
    if service_errors:
        for service, count in service_errors.most_common():
            print(f"{service}: {count:,}")
    else:
        print("No ERROR records")
    print("Note: service ERROR log counts can include multiple records for one request.")


def main():
    requests_path = DATA_DIR / "requests.csv"
    logs_path = DATA_DIR / "application_logs.csv"
    for path in (requests_path, logs_path):
        if not path.is_file():
            raise SystemExit(f"Missing input file: {path}")

    summarize_failures(read_csv(requests_path), read_csv(logs_path))


if __name__ == "__main__":
    main()