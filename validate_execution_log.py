"""Validate KSA Kitchen Tracker - Auto Refresh Execution Log CSV and write to output.
   Usage: python validate_execution_log.py [path/to/execution_log.csv]
   Default: data/input/ksa_auto_refresh_execution_log.csv
   Writes: data/output/ksa_auto_refresh_execution_log.csv
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "config" / "schemas" / "ksa_auto_refresh_execution_log.json"
DEFAULT_CSV = ROOT / "data" / "input" / "ksa_auto_refresh_execution_log.csv"
OUTPUT_PATH = ROOT / "data" / "output" / "ksa_auto_refresh_execution_log.csv"


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    if not csv_path.is_absolute():
        csv_path = Path.cwd() / csv_path
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        print("Usage: python validate_execution_log.py [path/to/execution_log.csv]")
        sys.exit(1)

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    required = set(schema.get("required", []))

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    valid, invalid = [], []
    for i, row in enumerate(rows):
        missing = required - set(k for k, v in row.items() if v is not None and str(v).strip() != "")
        if missing:
            invalid.append((i + 2, row, f"Missing required: {missing}"))
        else:
            valid.append(row)

    print(f"KSA Auto Refresh Execution Log: {csv_path.name}")
    print(f"  Total rows: {len(rows)}")
    print(f"  Valid:     {len(valid)}")
    print(f"  Invalid:   {len(invalid)}")
    for line, _, err in invalid:
        print(f"    Row {line}: {err}")

    if valid:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(valid[0].keys()))
            w.writeheader()
            w.writerows(valid)
        print(f"  Output:    {OUTPUT_PATH}")
    if invalid:
        sys.exit(1)
    print("  OK - all rows pass.")


if __name__ == "__main__":
    main()
