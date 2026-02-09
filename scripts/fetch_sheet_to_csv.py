"""Fetch KSA Kitchen Tracker from Google Sheets and save as CSV. No Download button needed.
   One-time: Enable Google Sheets API, create a service account, download JSON key.
   Share the sheet with the service account email (Viewer). Put the JSON in this folder.
   Usage: python fetch_sheet_to_csv.py
"""
import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
OUTPUT_CSV = ROOT / "data" / "input" / "ksa_kitchen_tracker.csv"

# From your sheet URL: https://docs.google.com/spreadsheets/d/SHEET_ID/edit?gid=GID
SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"
GID = "1341293927"  # tab id from URL #gid=1341293927 — change if your tracker is another tab

CREDENTIALS_JSON = SCRIPT_DIR / "credentials.json"


def main():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("Install: python -m pip install gspread google-auth")
        sys.exit(1)

    if not CREDENTIALS_JSON.exists():
        print(f"Put your service account JSON key at: {CREDENTIALS_JSON}")
        print("See scripts/SETUP_GOOGLE_SHEETS_API.md for step-by-step setup.")
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(str(CREDENTIALS_JSON), scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)

    # Open the tab by gid (from URL #gid=...)
    sheet = None
    for ws in spreadsheet.worksheets():
        if str(ws.id) == str(GID):
            sheet = ws
            break
    if sheet is None:
        sheet = spreadsheet.sheet1

    rows = sheet.get_all_values()
    if not rows:
        print("Sheet is empty.")
        sys.exit(1)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    print(f"Fetched {len(rows)} rows to {OUTPUT_CSV}")
    print("Next: from repo root run  python validate_ksa_csv.py")


if __name__ == "__main__":
    main()
