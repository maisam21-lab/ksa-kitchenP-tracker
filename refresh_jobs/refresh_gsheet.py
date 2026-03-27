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
# Preview regional kitchen masters (same DB sources as app.tracker_app)
KUWAIT_KITCHEN_SHEET_ID = "1N_Ar-KoFWGTHjbz-p_r1y8VeWGLNI4ZQUAbKZpAI99o"
KUWAIT_KITCHEN_WORKSHEET_GID = 1841714979
# Must match app/tracker_app.py — facility worksheets only
KUWAIT_KITCHEN_FACILITY_GIDS = [
    1238868875,
    1841714979,
    882958805,
    957808050,
    907327211,
    1936874701,
    477755898,
    968021133,
    1395349722,
    1364857082,
    1997767336,
    553716236,
    294895439,
    145680163,
    646323112,
    1007765601,
    1459899749,
    488170085,
    521341533,
]
UAE_KITCHEN_SHEET_ID = "1H9M4QoAz71LJlGMzIiLzy7FtIACtrCUF2pJ5Gr3eXIg"
UAE_KITCHEN_WORKSHEET_GID = 0
UAE_KITCHEN_FACILITY_GIDS = [
    1339914631,
    190735693,
    585677775,
    1359039456,
    1097068287,
    580811154,
    2116849928,
    1791734492,
    152450119,
    473484753,
    335341419,
    1141013645,
    2022030288,
    101319004,
    1189999475,
    887716464,
    915019099,
    766465559,
    528919076,
    1527607352,
    42129892,
    2143219525,
    121061187,
    498147837,
    2108732207,
    603226289,
    181577452,
    1503331412,
    515258982,
]
TAB_ID_KITCHEN_KW = "Kuwait Kitchen Master"
TAB_ID_KITCHEN_AE = "UAE Kitchen Master"
GSOURCE_KITCHEN_KW = "gsheet_kw"
GSOURCE_KITCHEN_AE = "gsheet_ae"
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


def fetch_workbook_tabs_by_gids(sheet_id: str, gids: list[int], credentials_path: str) -> dict:
    """Fetch only the listed worksheet gids; returns {worksheet_title: list of dicts}. Same as app regional load."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    out: dict = {}
    for gid in gids:
        ws = spreadsheet.get_worksheet_by_id(int(gid))
        if ws is None:
            continue
        rows = ws.get_all_values()
        if not rows:
            continue
        headers = [str(h).strip() or f"_col{i}" for i, h in enumerate(rows[0])]
        data = []
        for row in rows[1:]:
            r = list(row) + [""] * (len(headers) - len(row))
            data.append(dict(zip(headers, r[: len(headers)])))
        title = str(ws.title).strip() or f"gid_{gid}"
        out[title] = data
    return out


def fetch_worksheet_by_gid(sheet_id: str, worksheet_gid: int, credentials_path: str) -> list[dict]:
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    client = gspread.authorize(creds)
    ws = client.open_by_key(sheet_id).get_worksheet_by_id(int(worksheet_gid))
    if ws is None:
        return []
    rows = ws.get_all_values()
    if not rows:
        return []
    headers = [str(h).strip() or f"_col{i}" for i, h in enumerate(rows[0])]
    data = []
    for row in rows[1:]:
        r = list(row) + [""] * (len(headers) - len(row))
        data.append(dict(zip(headers, r[: len(headers)])))
    return data


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
        def _parse_gids_env(key: str, default_list: list[int]) -> list[int]:
            raw = os.environ.get(key, "").strip()
            if not raw:
                return list(default_list)
            out = []
            for token in raw.replace(";", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    out.append(int(token))
                except ValueError:
                    continue
            return out if out else list(default_list)

        regional_multi = [
            (
                os.environ.get("KUWAIT_KITCHEN_SHEET_ID", "").strip() or KUWAIT_KITCHEN_SHEET_ID,
                _parse_gids_env("KUWAIT_KITCHEN_FACILITY_GIDS", KUWAIT_KITCHEN_FACILITY_GIDS),
                GSOURCE_KITCHEN_KW,
            ),
            (
                os.environ.get("UAE_KITCHEN_SHEET_ID", "").strip() or UAE_KITCHEN_SHEET_ID,
                _parse_gids_env("UAE_KITCHEN_FACILITY_GIDS", UAE_KITCHEN_FACILITY_GIDS),
                GSOURCE_KITCHEN_AE,
            ),
        ]
        for sid, gids, gsrc in regional_multi:
            try:
                c.execute("DELETE FROM generic_tab_data WHERE source = ?", (gsrc,))
                reg_data = fetch_workbook_tabs_by_gids(sid, gids, creds_path)
                nrows = 0
                for ws_title, reg_rows in reg_data.items():
                    if not reg_rows:
                        continue
                    save_generic_tab(c, ws_title, reg_rows, source=gsrc)
                    nrows += len(reg_rows)
                c.execute(
                    "INSERT OR REPLACE INTO refresh_metadata (source, refreshed_at) VALUES (?, ?)",
                    (gsrc, now),
                )
                logger.info("Regional %s: %s sheets, %s rows", gsrc, len(reg_data), nrows)
            except Exception as e:
                logger.warning("Regional sheet %s skipped: %s", gsrc, e)
    # conn context manager commits on exit
    logger.info("GSheet refresh done: %s tabs", len(tab_order))
    return 0


if __name__ == "__main__":
    sys.exit(main())
