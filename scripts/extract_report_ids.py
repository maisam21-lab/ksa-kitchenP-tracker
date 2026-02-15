"""Extract Salesforce Report IDs from KSA Kitchen Tracker Excel and print sf_tab_queries."""
import re
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("pip install pandas openpyxl", file=sys.stderr)
    sys.exit(1)

path = Path(r"C:/Users/MaysamAbuKashabeh/Downloads/KSA Kitchen Tracker (2).xlsx")
if not path.exists():
    path = Path(__file__).resolve().parent.parent.parent / "Downloads" / "KSA Kitchen Tracker (2).xlsx"
if not path.exists():
    print("File not found:", path, file=sys.stderr)
    sys.exit(1)

df = pd.read_excel(path, sheet_name="Auto Refresh Execution Log", header=0)
sheet_to_id = {}
for _, row in df.iterrows():
    sh = str(row.get("Sheet", "")).strip()
    op = str(row.get("Operation", ""))
    m = re.search(r"00O[a-zA-Z0-9]{12,15}", op)
    if m and sh:
        sheet_to_id.setdefault(sh, set()).add(m.group())

tab_to_report = {sh: sorted(ids)[0] for sh, ids in sorted(sheet_to_id.items())}

print("# Report IDs from KSA Kitchen Tracker (2).xlsx - Auto Refresh Execution Log (Sheet -> Operation)")
print("# Paste into Streamlit secrets [sf_tab_queries] or SF_TAB_QUERIES JSON")
print()
print("[sf_tab_queries]")
for tab, rid in sorted(tab_to_report.items()):
    print(f'"{tab}" = "{rid}"')
print()
print("# Or as single-line JSON (SF_TAB_QUERIES):")
import json
print(json.dumps(tab_to_report))
