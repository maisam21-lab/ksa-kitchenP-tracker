"""Extract data from Google Sheets API — read from Sheets without Download button."""

import os
from pathlib import Path
from typing import Any


def extract_google_sheets(
    sheet_id: str,
    table_name_or_gid: str,
    credentials_path: str | Path | None = None,
    credentials_json: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch all rows from a Google Sheet (one sheet tab) via the Google Sheets API.
    Returns list of dicts (first row = headers).

    sheet_id: From URL https://docs.google.com/spreadsheets/d/SHEET_ID/edit
    table_name_or_gid: Sheet tab name (e.g. "KSA Kitchen Tracker") or gid number (e.g. "1341293927")
    credentials_path: Path to service account JSON key file. If None, uses credentials_json or env GOOGLE_APPLICATION_CREDENTIALS.
    credentials_json: In-memory dict of service account JSON (e.g. from env). If set, used instead of file.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Install: pip install gspread google-auth") from None

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    if credentials_json:
        creds = Credentials.from_service_account_info(credentials_json, scopes=scopes)
    else:
        path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not path or not Path(path).exists():
            raise ValueError(
                "Google Sheets API credentials required: set credentials_path in config, "
                "or GOOGLE_APPLICATION_CREDENTIALS to a service account JSON file path."
            )
        creds = Credentials.from_service_account_file(str(path), scopes=scopes)

    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)

    # Open by gid (numeric string) or by worksheet name
    sheet = None
    try:
        gid_num = int(table_name_or_gid)
        for ws in spreadsheet.worksheets():
            if str(ws.id) == str(gid_num):
                sheet = ws
                break
    except ValueError:
        sheet = spreadsheet.worksheet(table_name_or_gid)

    if sheet is None:
        sheet = spreadsheet.sheet1

    rows = sheet.get_all_values()
    if not rows:
        return []

    # First row = headers, rest = data
    headers = [str(h).strip() or f"_col{i}" for i, h in enumerate(rows[0])]
    return [dict(zip(headers, row)) for row in rows[1:]]
