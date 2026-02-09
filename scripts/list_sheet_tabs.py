"""
List all tab names and gids in a Google Sheet. Use this to get exact names for Trino range.
Run from repo root: python scripts/list_sheet_tabs.py [SPREADSHEET_ID]
Default spreadsheet ID: KSA Kitchen Tracker.
Requires: service account JSON at scripts/credentials.json (or set GOOGLE_APPLICATION_CREDENTIALS).
Share the sheet with the service account email (Viewer).
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"


def main():
    sheet_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SHEET_ID

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path and Path(creds_path).exists():
        pass
    else:
        for rel in ["scripts/credentials.json", ".secrets/gsheet-service.json"]:
            p = REPO_ROOT / rel
            if p.exists():
                creds_path = str(p)
                break
    if not creds_path or not Path(creds_path).exists():
        print("ERROR: No credentials. Put service account JSON at scripts/credentials.json or set GOOGLE_APPLICATION_CREDENTIALS.")
        sys.exit(1)

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("Install: pip install gspread google-auth")
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)

    print(f"Spreadsheet: {spreadsheet.title}")
    print(f"ID: {sheet_id}")
    print()
    print("Tabs (use exact name in Trino range => 'TabName!A1:Z1000'):")
    print("-" * 60)
    for i, ws in enumerate(spreadsheet.worksheets(), 1):
        # gid is the numeric id in the URL (?gid=...)
        gid = ws.id
        title = ws.title
        print(f"  {i:2}.  gid={gid}  |  {repr(title)}")
    print("-" * 60)
    print()
    print("Trino range examples (copy exact tab name from above):")
    for ws in spreadsheet.worksheets():
        name = ws.title
        if " " in name:
            print(f"  range => '''{name}''!A1:Z1000'   -- or try unquoted: '{name}!A1:Z1000'")
        else:
            print(f"  range => '{name}!A1:Z1000'")


if __name__ == "__main__":
    main()
