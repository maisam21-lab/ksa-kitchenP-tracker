"""Validate KSA Kitchen Tracker CSV and write valid rows to output (stdlib only).
   Usage: python validate_ksa_csv.py [input.csv]
   Writes: data/output/ksa_kitchen_tracker.csv (valid rows only)
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "config" / "schemas" / "ksa_kitchen_tracker.json"
DEFAULT_CSV = ROOT / "data" / "input" / "ksa_kitchen_tracker.csv"
OUTPUT_PATH = ROOT / "data" / "output" / "ksa_kitchen_tracker.csv"


def validate_and_split(rows, schema):
    required = set(schema.get("required", []))
    region_enum = schema.get("properties", {}).get("region", {}).get("enum")
    valid, invalid = [], []
    for i, row in enumerate(rows):
        missing = required - set(k for k, v in row.items() if v is not None and str(v).strip() != "")
        if missing:
            invalid.append((i + 2, row, f"Missing required: {missing}"))
            continue
        if region_enum and row.get("region") not in region_enum:
            invalid.append((i + 2, row, f"region must be one of {region_enum}"))
            continue
        valid.append(row)
    return valid, invalid


def write_output(valid_rows, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not valid_rows:
        return
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(valid_rows[0].keys()))
        w.writeheader()
        w.writerows(valid_rows)


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    if not csv_path.is_absolute():
        csv_path = ROOT / csv_path

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    valid, invalid = validate_and_split(rows, schema)

    print(f"KSA Kitchen Tracker: {csv_path.name}")
    print(f"  Total rows: {len(rows)}")
    print(f"  Valid:      {len(valid)}")
    print(f"  Invalid:    {len(invalid)}")
    for line, _, err in invalid:
        print(f"    Row {line}: {err}")

    if valid:
        write_output(valid, OUTPUT_PATH)
        print(f"  Output:     {OUTPUT_PATH}")
    if invalid:
        sys.exit(1)
    print("  OK - all rows pass.")


if __name__ == "__main__":
    main()
