"""
Refresh Google Sheet data into the app DB. Run on a schedule (e.g. every 15 min with run_all.py)
so users don't have to press "Refresh from Google Sheet" in the app.

Usage:
  python refresh_jobs/refresh_gsheet.py
  # or from repo root: python -m refresh_jobs.refresh_gsheet

Requires: GOOGLE_APPLICATION_CREDENTIALS (path to service account JSON) or
  GSHEET_CREDENTIALS_JSON (path) or gsheet_service_account in Streamlit secrets (not available in cron).
  Optional: GSHEET_SHEET_ID (defaults to the KSA tracker sheet ID).
"""
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "app" / "data" / "tracker.db"

# Match app: sheet ID and tab mapping
DEFAULT_SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"
MAIN_TRACKER_TAB_ID = "Tracker"
KITCHEN_TRACKER_SHEET_ALIASES = ["Kitchen Tracker", "Smart Tracker", "Tracker", "KitchenTracker", "KSA Kitchen Tracker"]
SHEET_TAB_IDS = [
    "Kitchens", "Master Kitchens list", "Sellable No Status", "All no status kitchens",
    "LF Comp", "Pivot Table 10", "Area Data", "KSA Facility details",
    "Inflation FPx", "Price Multipliers", "Occupancy", "Pivot Table 4",
    "Qurtoba - Old", "Jarir - Old", "Salam - Old", "Narjis - Old", "Aqrabiya - Old", "Zuhur - Old", "Hofuf - Old",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


TABLE_GSHEET_TAB_ORDER = """
CREATE TABLE IF NOT EXISTS gsheet_tab_order (
    tab_index INTEGER NOT NULL,
    tab_id TEXT NOT NULL PRIMARY KEY
)
"""
TABLE_REFRESH_METADATA = """
CREATE TABLE IF NOT EXISTS refresh_metadata (
    source TEXT NOT NULL PRIMARY KEY,
    refreshed_at TEXT NOT NULL
)
"""
TABLE_GENERIC_TAB = """
CREATE TABLE IF NOT EXISTS generic_tab_data (
    source TEXT NOT NULL,
    tab_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (source, tab_id, row_index)
)
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(TABLE_GENERIC_TAB)
    conn.executescript(TABLE_GSHEET_TAB_ORDER)
    conn.executescript(TABLE_REFRESH_METADATA)
    return conn


def fetch_sheet(sheet_id: str, credentials_path: str) -> dict:
    """Fetch all worksheets; returns {worksheet_title: list of dicts}."""
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    out = {}
    for ws in spreadsheet.worksheets():
        rows = ws.get_all_values()
        if not rows:
            out[ws.title] = []
            continue
        headers = [str(h).strip() or f"_col{i}" for i, h in enumerate(rows[0])]
        data = []
        for row in rows[1:]:
            r = list(row) + [""] * (len(headers) - len(row))
            data.append(dict(zip(headers, r[: len(headers)])))
        out[ws.title] = data
    return out


def resolve_tab_id(ws_title: str) -> str:
    if ws_title.strip() in KITCHEN_TRACKER_SHEET_ALIASES or ws_title.strip().lower() in {s.strip().lower() for s in KITCHEN_TRACKER_SHEET_ALIASES}:
        return MAIN_TRACKER_TAB_ID
    for tid in SHEET_TAB_IDS:
        if tid == ws_title or tid.strip() == ws_title.strip() or ws_title.strip().lower() == tid.strip().lower():
            return tid
    if ws_title.strip() == "SF Kitchen Data":
        return "Kitchens"
    return ws_title


def is_main_tracker(tab_id: str) -> bool:
    return (tab_id or "").strip() == MAIN_TRACKER_TAB_ID


def save_generic_tab(c, tab_id: str, rows: list, source: str = "gsheet"):
    c.execute("DELETE FROM generic_tab_data WHERE source = ? AND tab_id = ?", (source, tab_id))
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            row = dict(row)
        c.execute(
            "INSERT INTO generic_tab_data (source, tab_id, row_index, data) VALUES (?, ?, ?, ?)",
            (source, tab_id, i, json.dumps(row, ensure_ascii=False)),
        )


def main() -> int:
    sheet_id = os.environ.get("GSHEET_SHEET_ID", "").strip() or DEFAULT_SHEET_ID
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not creds_path or not Path(creds_path).exists():
        for rel in ["scripts/credentials.json", ".secrets/gsheet-service.json", "app/data/credentials.json"]:
            p = REPO_ROOT / rel
            if p.exists():
                creds_path = str(p)
                break
        else:
            logger.error("No Google credentials. Set GOOGLE_APPLICATION_CREDENTIALS or add credentials JSON under scripts/ or .secrets/")
            return 1
    try:
        data = fetch_sheet(sheet_id, creds_path)
    except Exception as e:
        logger.exception("Fetch failed: %s", e)
        return 1
    tab_order = []
    with get_conn() as c:
        for ws_title, rows in data.items():
            if not rows:
                continue
            tab_id = resolve_tab_id(ws_title)
            if tab_id == "Auto Refresh Execution Log":
                continue
            if is_main_tracker(tab_id):
                continue
            save_generic_tab(c, tab_id, rows)
            tab_order.append((len(tab_order), tab_id))
        if tab_order:
            c.execute("DELETE FROM gsheet_tab_order")
            for i, tid in tab_order:
                c.execute("INSERT OR REPLACE INTO gsheet_tab_order (tab_index, tab_id) VALUES (?, ?)", (i, tid))
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        c.execute("INSERT OR REPLACE INTO refresh_metadata (source, refreshed_at) VALUES (?, ?)", ("gsheet", now))
    # conn context manager commits on exit
    logger.info("GSheet refresh done: %s tabs", len(tab_order))
    return 0


if __name__ == "__main__":
    sys.exit(main())
