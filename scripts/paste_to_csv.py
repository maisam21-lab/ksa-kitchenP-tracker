"""Convert a pasted-from-Sheets file (tabs or commas) to proper CSV.
   Usage: python paste_to_csv.py [path/to/pasted.txt]
   Reads the file, detects delimiter, writes ../data/input/ksa_kitchen_tracker.csv
   Then run from repo root: python validate_ksa_csv.py
"""
import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
OUTPUT_CSV = ROOT / "data" / "input" / "ksa_kitchen_tracker.csv"


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python paste_to_csv.py <path_to_pasted_file>")
        print("Example: paste from Sheets into Notepad, save as ksa_paste.txt, then:")
        print("         python paste_to_csv.py ksa_paste.txt")
        sys.exit(1)
    if not path.is_absolute():
        # Resolve relative to current working directory (e.g. repo root)
        path = Path.cwd() / path
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()

    # Detect delimiter: if first line has tabs and no commas, use tab
    first_line = raw.split("\n")[0] if raw else ""
    if "\t" in first_line and first_line.count(",") < 2:
        delimiter = "\t"
    else:
        delimiter = ","

    reader = csv.reader(raw.splitlines(), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        print("No rows in file.")
        sys.exit(1)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")
    print("Next: from repo root run  python validate_ksa_csv.py")


if __name__ == "__main__":
    main()
