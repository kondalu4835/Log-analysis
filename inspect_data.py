import argparse
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent
CSV_FILES = ("application_logs.csv", "requests.csv", "metrics.csv")


def inspect_csv(path, sample_rows):
    frame = pd.read_csv(path)

    print(f"\n{path.name}")
    print(f"Rows: {len(frame):,}")
    print(f"Columns ({len(frame.columns)}): {', '.join(frame.columns)}")
    print("Data types:")
    for column, dtype in frame.dtypes.items():
        print(f"  {column}: {dtype}")
    print(f"Sample rows ({min(sample_rows, len(frame))}):")
    if frame.empty:
        print("  <no rows>")
    else:
        print(frame.head(sample_rows).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="Print schema, row count, data types, and sample rows for the log CSV files."
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=5,
        help="Number of leading rows to display per file (default: 5).",
    )
    args = parser.parse_args()
    if args.sample_rows < 0:
        parser.error("--sample-rows must be zero or greater")

    for filename in CSV_FILES:
        path = DATA_DIR / filename
        if not path.is_file():
            parser.exit(1, f"Missing input file: {path}\n")
        inspect_csv(path, args.sample_rows)


if __name__ == "__main__":
    main()