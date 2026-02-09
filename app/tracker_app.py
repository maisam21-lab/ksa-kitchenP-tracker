"""
KSA Kitchens Tracker — web app. Run: streamlit run app/tracker_app.py
All sheet tabs in tool form: view, filter, add/edit, export. Single source of truth.
Accepts CSV or Excel (.xlsx) uploads. Can refresh directly from the online Google Sheet.
"""
import csv
import io
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

import streamlit as st

try:
    import pandas as pd
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

# Online sheet: same ID as the workbook
SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"

# Trino: same tabs as KSA_TRACKER_GOOGLE_SHEETS_QUERIES.sql (tabs that have data)
TRINO_TAB_RANGES = [
    "Auto Refresh Execution Log",
    "SF Kitchen Data",
    "Sellable No Status",
    "All no status kitchens",
    "LF Comp",
    "Pivot Table 10",
    "Area Data",
    "SF Churn Data",
    "KSA Facility details",
    "Inflation FPx",
    "Price Multipliers",
    "Occupancy",
    "Pivot Table 4",
    "Qurtoba - Old",
    "Jarir - Old",
    "Salam - Old",
    "Narjis - Old",
    "Aqrabiya - Old",
    "Zuhur - Old",
    "Hofuf - Old",
]

# Rerun works in Streamlit 1.27+; fallback for older versions
def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
DB_PATH = APP_DIR / "data" / "tracker.db"
STATIC_DIR = APP_DIR / "static"


def _logo_path():
    """Path to KitchenPark logo if present."""
    for name in ("kitchenpark_logo.png", "logo.png", "kitchenpark_logo.svg", "logo.svg"):
        p = STATIC_DIR / name
        if p.exists():
            return p
    return None

# Standardized column order for stakeholder export (matches ETL output)
EXPORT_COLUMNS = [
    "record_id", "report_date", "site_id", "site_name", "region",
    "metric_name", "value", "status", "notes",
]

# Map common Google Sheet export headers to our schema (case-insensitive, strip spaces)
GSHEET_HEADER_MAP = {
    "record id": "record_id",
    "record_id": "record_id",
    "recordid": "record_id",
    "record-id": "record_id",
    "report date": "report_date",
    "report_date": "report_date",
    "reportdate": "report_date",
    "report-date": "report_date",
    "site id": "site_id",
    "site_id": "site_id",
    "siteid": "site_id",
    "site-id": "site_id",
    "site name": "site_name",
    "site_name": "site_name",
    "sitename": "site_name",
    "region": "region",
    "metric name": "metric_name",
    "metric_name": "metric_name",
    "metricname": "metric_name",
    "metric-name": "metric_name",
    "value": "value",
    "status": "status",
    "notes": "notes",
}


def _get_github_data_url() -> str:
    """Return URL to fetch tracker data from GitHub (set GITHUB_TRACKER_CSV_URL in secrets or env)."""
    try:
        url = st.secrets.get("GITHUB_TRACKER_CSV_URL") or os.environ.get("GITHUB_TRACKER_CSV_URL", "")
    except Exception:
        url = os.environ.get("GITHUB_TRACKER_CSV_URL", "")
    return (url or "").strip()


def _fetch_and_parse_from_url(url: str):
    """Fetch CSV or Excel from URL; return list of dicts. Raises on failure."""
    with urlopen(url, timeout=60) as resp:
        content = resp.read()
    # If we got HTML (e.g. GitHub blob or error page), raise a clear error
    if content.lstrip()[:500].lower().startswith((b"<!doctype", b"<html")):
        raise ValueError(
            "The URL returned a web page instead of a file. Use the **raw** file URL: "
            "on GitHub open the file, click 'Raw', and copy that URL (it must start with https://raw.githubusercontent.com/...)."
        )
    name = url.split("/")[-1].split("?")[0] or "data.csv"
    if not name.lower().endswith((".csv", ".xlsx", ".xls")):
        name = "data.csv"
    buf = io.BytesIO(content)
    buf.name = name
    return _parse_uploaded_file(buf)


def _fetch_workbook_from_url(url: str) -> dict[str, list[dict]] | None:
    """Fetch Excel from URL and return {sheet_name: rows} for all sheets, or None if not Excel."""
    with urlopen(url, timeout=60) as resp:
        content = resp.read()
    if content.lstrip()[:500].lower().startswith((b"<!doctype", b"<html")):
        raise ValueError(
            "The URL returned a web page instead of a file. Use the **raw** file URL (https://raw.githubusercontent.com/...)."
        )
    name = url.split("/")[-1].split("?")[0] or "data.xlsx"
    if not name.lower().endswith((".xlsx", ".xls")):
        return None
    buf = io.BytesIO(content)
    buf.name = name
    return _parse_workbook_all_sheets(buf, only_known_tabs=False)


def _parse_uploaded_file(upload):
    """Read uploaded CSV or Excel (.xlsx); return list of dicts (first row = headers)."""
    name = (upload.name or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        if not HAS_EXCEL:
            raise ValueError("Excel support requires pandas and openpyxl. Install: pip install pandas openpyxl")
        df = pd.read_excel(upload, sheet_name=0)
        df = df.astype(str).replace("nan", "")
        return [dict(row) for _, row in df.iterrows()]
    # CSV
    text = upload.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def _parse_workbook_all_sheets(upload, only_known_tabs: bool = True) -> dict[str, list[dict]]:
    """Read an Excel workbook and return {sheet_name: list of dicts}. If only_known_tabs, only read sheets matching SHEET_TAB_IDS (faster for large workbooks)."""
    if not HAS_EXCEL:
        raise ValueError("Excel support requires pandas and openpyxl. Install: pip install pandas openpyxl")
    name = (upload.name or "").lower()
    if not (name.endswith(".xlsx") or name.endswith(".xls")):
        raise ValueError("Upload an Excel file (.xlsx or .xls)")
    xl = pd.ExcelFile(upload)
    to_read = xl.sheet_names
    if only_known_tabs:
        known = {s.strip().lower() for s in SHEET_TAB_IDS} | {s.strip().lower() for s in KITCHEN_TRACKER_SHEET_ALIASES}
        to_read = [s for s in xl.sheet_names if s.strip().lower() in known]
        if not to_read:
            to_read = xl.sheet_names[:20]  # fallback: first 20 sheets
    out = {}
    for sheet_name in to_read:
        df = pd.read_excel(xl, sheet_name=sheet_name)
        df = df.astype(str).replace("nan", "")
        rows = [dict(row) for _, row in df.iterrows()]
        out[sheet_name] = rows
    return out


def _load_workbook_into_db(data: dict[str, list[dict]], progress_placeholder=None) -> tuple[bool, str]:
    """Load {sheet_name: rows} into app DB (same logic as refresh from sheet). Returns (success, message)."""
    loaded = []
    items = list(data.items())
    n = len(items)
    for i, (ws_title, rows) in enumerate(items):
        if progress_placeholder and n > 0:
            progress_placeholder.progress((i + 1) / n, text=f"Loading {ws_title[:35]}…")
        if not rows:
            continue
        tab_id = None
        if ws_title.strip() in KITCHEN_TRACKER_SHEET_ALIASES or ws_title.strip().lower() in {s.strip().lower() for s in KITCHEN_TRACKER_SHEET_ALIASES}:
            tab_id = MAIN_TRACKER_TAB_ID
        if tab_id is None:
            for tid in SHEET_TAB_IDS:
                if (tid == ws_title or tid.strip() == ws_title.strip() or
                    ws_title.strip().lower() == tid.strip().lower()):
                    tab_id = tid
                    break
        if tab_id is None:
            tab_id = ws_title
        if tab_id == "Auto Refresh Execution Log":
            with get_conn() as c:
                c.execute("DELETE FROM ksa_auto_refresh_execution_log")
            for r in rows:
                insert_exec_log({
                    "refresh_time": _row_key(r, "Refresh Time", "refresh_time") or datetime.now().strftime("%m/%d/%Y %H:%M"),
                    "sheet": _row_key(r, "Sheet", "sheet"),
                    "operation": _row_key(r, "Operation", "operation"),
                    "status": _row_key(r, "Status", "status"),
                    "user": _row_key(r, "User", "user"),
                })
            loaded.append(f"{tab_id} ({len(rows)} rows)")
        elif _is_main_tracker_tab(tab_id):
            for r in rows:
                row = _normalize_gsheet_row(r)
                rid = (row.get("record_id") or "").strip()
                if not rid:
                    continue
                if not row.get("report_date") or not row.get("site_id") or not row.get("region") or not row.get("metric_name"):
                    continue
                upsert_row(row)
            loaded.append(f"{tab_id} ({len(rows)} rows)")
        else:
            save_generic_tab(tab_id, rows)
            loaded.append(f"{tab_id} ({len(rows)} rows)")
    if progress_placeholder:
        progress_placeholder.empty()
    return True, "Loaded: " + "; ".join(loaded) if loaded else "No sheets with data found."


def _normalize_gsheet_row(raw: dict) -> dict:
    """Convert a row from CSV (possibly with GSheet-style headers) to tracker schema keys."""
    out = {}
    for k, v in raw.items():
        key_lower = (k or "").strip().lower()
        key_with_underscore = key_lower.replace(" ", "_").replace("-", "_")
        canonical = GSHEET_HEADER_MAP.get(key_lower) or GSHEET_HEADER_MAP.get(key_with_underscore)
        if canonical:
            out[canonical] = v
        elif key_with_underscore in EXPORT_COLUMNS:
            out[key_with_underscore] = v
    return out

# Main tracker: one tab in the app; workbook/sheet may use any of these names
MAIN_TRACKER_TAB_ID = "Tracker"
KITCHEN_TRACKER_SHEET_ALIASES = ["Kitchen Tracker", "Smart Tracker", "Tracker", "KitchenTracker", "KSA Kitchen Tracker"]


def _is_main_tracker_tab(tab_id: str) -> bool:
    """True if this tab id is the main data tracker (Tracker)."""
    return (tab_id or "").strip() == MAIN_TRACKER_TAB_ID


# Short descriptions for tab tooltips (hover); Tracker is not shown as a tab (moved to Dashboard)
TAB_DESCRIPTIONS = {
    "Auto Refresh Execution Log": "Log of auto-refresh runs and sheet operations. View or add rows.",
    "SF Kitchen Data": "SF Kitchen dataset. View, filter, and download.",
    "Sellable No Status": "Sellable no-status data. View and filter.",
    "All no status kitchens": "All no-status kitchens. View and filter.",
    "LF Comp": "LF Comp data. View and filter.",
    "Pivot Table 10": "Pivot Table 10 dataset. View and filter.",
    "Area Data": "Area data. View and filter.",
    "SF Churn Data": "SF Churn data. View and filter.",
    "KSA Facility details": "KSA facility details. View and filter.",
    "Inflation FPx": "Inflation FPx data. View and filter.",
    "Price Multipliers": "Price multipliers. View and filter.",
    "Occupancy": "Occupancy data. View and filter.",
    "Pivot Table 4": "Pivot Table 4. View and filter.",
    "Qurtoba - Old": "Qurtoba (old). View and filter.",
    "Jarir - Old": "Jarir (old). View and filter.",
    "Salam - Old": "Salam (old). View and filter.",
    "Narjis - Old": "Narjis (old). View and filter.",
    "Aqrabiya - Old": "Aqrabiya (old). View and filter.",
    "Zuhur - Old": "Zuhur (old). View and filter.",
    "Hofuf - Old": "Hofuf (old). View and filter.",
}

# Sheet tab names shown in the app; last 7 also loaded via Trino
# Tracker data is no longer a Data tab; users customize their view on Dashboard
SHEET_TAB_IDS = [
    "Auto Refresh Execution Log",
    "SF Kitchen Data",
    "Sellable No Status",
    "All no status kitchens",
    "LF Comp",
    "Pivot Table 10",
    "Area Data",
    "SF Churn Data",
    "KSA Facility details",
    "Inflation FPx",
    "Price Multipliers",
    "Occupancy",
    "Pivot Table 4",
    "Qurtoba - Old",
    "Jarir - Old",
    "Salam - Old",
    "Narjis - Old",
    "Aqrabiya - Old",
    "Zuhur - Old",
    "Hofuf - Old",
]

TABLE = """
CREATE TABLE IF NOT EXISTS ksa_kitchen_tracker (
    record_id TEXT NOT NULL,
    report_date TEXT NOT NULL,
    site_id TEXT NOT NULL,
    site_name TEXT,
    region TEXT NOT NULL DEFAULT 'KSA',
    metric_name TEXT NOT NULL,
    value REAL,
    status TEXT,
    notes TEXT,
    updated_at TEXT,
    PRIMARY KEY (record_id)
)
"""

TABLE_EXEC_LOG = """
CREATE TABLE IF NOT EXISTS ksa_auto_refresh_execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_time TEXT NOT NULL,
    sheet TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    user TEXT NOT NULL
)
"""
EXEC_LOG_COLUMNS = ["refresh_time", "sheet", "operation", "status", "user"]

# Generic tab data: any sheet tab (SF Kitchen Data, Area Data, etc.) — store rows as JSON per row
TABLE_GENERIC_TAB = """
CREATE TABLE IF NOT EXISTS generic_tab_data (
    tab_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (tab_id, row_index)
)
"""

TABLE_FEEDBACK = """
CREATE TABLE IF NOT EXISTS tracker_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    message TEXT NOT NULL,
    contact TEXT,
    page_or_section TEXT
)
"""

TABLE_TRAFFIC = """
CREATE TABLE IF NOT EXISTS tracker_traffic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visited_at TEXT NOT NULL
)
"""

TABLE_RECORD_COMMENTS = """
CREATE TABLE IF NOT EXISTS record_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL,
    comment_text TEXT NOT NULL
)
"""

TABLE_RECORD_ACTIVITY = """
CREATE TABLE IF NOT EXISTS record_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    by_user TEXT,
    details TEXT
)
"""

TABLE_TRACKER_TEMPLATES = """
CREATE TABLE IF NOT EXISTS tracker_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
)
"""

TABLE_SAVED_VIEWS = """
CREATE TABLE IF NOT EXISTS saved_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    filters_json TEXT NOT NULL
)
"""

# Optional access control: only these users can use the app (when allowlist is enabled)
TABLE_ALLOWED_USERS = """
CREATE TABLE IF NOT EXISTS allowed_users (
    identifier TEXT NOT NULL PRIMARY KEY,
    added_at TEXT NOT NULL
)
"""

# App-wide discussions: comments and questions from users (not tied to a record)
# parent_id: NULL = top-level post; else = reply to that id
TABLE_APP_DISCUSSIONS = """
CREATE TABLE IF NOT EXISTS app_discussions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL,
    message TEXT NOT NULL,
    parent_id INTEGER NULL
)
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_updated_at():
    """Add updated_at column if missing (migration)."""
    with get_conn() as c:
        try:
            c.execute("SELECT updated_at FROM ksa_kitchen_tracker LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE ksa_kitchen_tracker ADD COLUMN updated_at TEXT")


def _ensure_discussions_parent_id():
    """Add parent_id to app_discussions if missing (migration)."""
    with get_conn() as c:
        try:
            c.execute("SELECT parent_id FROM app_discussions LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE app_discussions ADD COLUMN parent_id INTEGER NULL")


def init_db():
    with get_conn() as c:
        c.execute(TABLE)
        c.execute(TABLE_EXEC_LOG)
        c.execute(TABLE_GENERIC_TAB)
        c.execute(TABLE_FEEDBACK)
        c.execute(TABLE_TRAFFIC)
        c.execute(TABLE_RECORD_COMMENTS)
        c.execute(TABLE_RECORD_ACTIVITY)
        c.execute(TABLE_TRACKER_TEMPLATES)
        c.execute(TABLE_SAVED_VIEWS)
        c.execute(TABLE_ALLOWED_USERS)
        c.execute(TABLE_APP_DISCUSSIONS)
    _ensure_updated_at()
    _ensure_discussions_parent_id()


def _get_allowlist_ids_from_config() -> list[str]:
    """Return allowlisted identifiers from ALLOWLIST_IDS (secrets or env)."""
    try:
        ids = st.secrets.get("ALLOWLIST_IDS") or os.environ.get("ALLOWLIST_IDS", "")
    except Exception:
        ids = os.environ.get("ALLOWLIST_IDS", "")
    return [s.strip() for s in str(ids).split(",") if s.strip()]


def _sync_allowlist_from_config():
    """If ALLOWLIST_IDS is set, keep DB allowlist in sync with that config.

    This lets admins manage the allowlist from the backend (secrets/env)
    instead of through the UI inside the tracker.
    """
    ids = _get_allowlist_ids_from_config()
    if not ids:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute("DELETE FROM allowed_users")
        for identifier in ids:
            c.execute(
                "INSERT INTO allowed_users (identifier, added_at) VALUES (?, ?)",
                (identifier, now),
            )
    _sync_allowlist_from_config()


def _allowlist_enabled() -> bool:
    """True if access is restricted to allowed users only (set ALLOWLIST_ENABLED=1 or in secrets)."""
    try:
        v = st.secrets.get("ALLOWLIST_ENABLED") or os.environ.get("ALLOWLIST_ENABLED", "")
    except Exception:
        v = os.environ.get("ALLOWLIST_ENABLED", "")
    return str(v).strip().lower() in ("1", "true", "yes")


def list_allowed_users():
    """Return list of allowed identifiers (email or name)."""
    with get_conn() as c:
        r = c.execute("SELECT identifier, added_at FROM allowed_users ORDER BY identifier")
        return [dict(row) for row in r]


def add_allowed_user(identifier: str) -> bool:
    """Add an email or name to the allowlist. Returns True if added."""
    id_ = (identifier or "").strip()
    if not id_:
        return False
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        try:
            c.execute("INSERT INTO allowed_users (identifier, added_at) VALUES (?, ?)", (id_, now))
            return True
        except sqlite3.IntegrityError:
            return False  # already exists


def remove_allowed_user(identifier: str) -> bool:
    """Remove an identifier from the allowlist. Returns True if removed."""
    id_ = (identifier or "").strip()
    if not id_:
        return False
    with get_conn() as c:
        c.execute("DELETE FROM allowed_users WHERE identifier = ?", (id_,))
        return c.rowcount > 0


def is_user_allowed(identifier: str) -> bool:
    """True if the given email/name is in the allowlist (case-insensitive)."""
    id_ = (identifier or "").strip()
    if not id_:
        return False
    with get_conn() as c:
        r = c.execute(
            "SELECT 1 FROM allowed_users WHERE LOWER(TRIM(identifier)) = LOWER(?) LIMIT 1",
            (id_,),
        )
        return r.fetchone() is not None


def insert_app_discussion(author: str, message: str, parent_id: int | None = None) -> None:
    """Add a discussion post or reply (parent_id=None for top-level)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO app_discussions (created_at, author, message, parent_id) VALUES (?, ?, ?, ?)",
            (now, (author or "Anonymous").strip(), (message or "").strip(), parent_id),
        )


def list_app_discussions(limit: int = 200) -> list[dict]:
    """Return all discussion posts and replies (with parent_id), newest first."""
    with get_conn() as c:
        r = c.execute(
            "SELECT id, created_at, author, message, parent_id FROM app_discussions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in r]


def list_rows():
    with get_conn() as c:
        r = c.execute(
            "SELECT * FROM ksa_kitchen_tracker ORDER BY report_date DESC, record_id"
        )
        return [dict(row) for row in r]


def filter_rows(rows, filters):
    """Apply filters; only affects what is shown, not the data."""
    for key, val in filters.items():
        if val is None or val == "" or val == ["All"] or val == "All":
            continue
        if isinstance(val, list):
            rows = [r for r in rows if r.get(key) in val]
        else:
            rows = [r for r in rows if r.get(key) == val]
    return rows


def insert_row(row, by_user: str = ""):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rid = (row.get("record_id") or "").strip()
    with get_conn() as c:
        c.execute(
            """INSERT INTO ksa_kitchen_tracker
               (record_id, report_date, site_id, site_name, region, metric_name, value, status, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rid,
                row.get("report_date", "").strip(),
                row.get("site_id", "").strip(),
                row.get("site_name") or "",
                row.get("region") or "KSA",
                row.get("metric_name", "").strip(),
                row.get("value") if row.get("value") != "" else None,
                row.get("status") or "",
                row.get("notes") or "",
                now,
            ),
        )
    log_record_activity(rid, "created", by_user, "")


def update_row(record_id, row, by_user: str = ""):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            """UPDATE ksa_kitchen_tracker SET
               report_date=?, site_id=?, site_name=?, region=?, metric_name=?, value=?, status=?, notes=?, updated_at=?
               WHERE record_id=?""",
            (
                row.get("report_date", "").strip(),
                row.get("site_id", "").strip(),
                row.get("site_name") or "",
                row.get("region") or "KSA",
                row.get("metric_name", "").strip(),
                row.get("value") if row.get("value") != "" else None,
                row.get("status") or "",
                row.get("notes") or "",
                now,
                record_id,
            ),
        )
    log_record_activity(record_id, "updated", by_user, "")


def delete_row(record_id):
    with get_conn() as c:
        c.execute("DELETE FROM ksa_kitchen_tracker WHERE record_id=?", (record_id,))


def insert_feedback(message: str, contact: str = "", page_or_section: str = ""):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO tracker_feedback (created_at, message, contact, page_or_section) VALUES (?, ?, ?, ?)",
            (now, (message or "").strip(), (contact or "").strip(), (page_or_section or "").strip()),
        )


def log_traffic():
    """Log one visit (call once per session)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute("INSERT INTO tracker_traffic (visited_at) VALUES (?)", (now,))


def get_daily_traffic_count() -> int:
    """Number of visits logged today (UTC date)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_conn() as c:
        r = c.execute(
            "SELECT COUNT(*) AS n FROM tracker_traffic WHERE date(visited_at) = ?",
            (today,),
        )
        row = r.fetchone()
        return row["n"] if row else 0


def get_tracker_record_count() -> int:
    """Total number of records in the main kitchen tracker (lightweight COUNT)."""
    with get_conn() as c:
        r = c.execute("SELECT COUNT(*) AS n FROM ksa_kitchen_tracker")
        row = r.fetchone()
        return row["n"] if row else 0


def get_records_updated_today_count() -> int:
    """Number of records updated today (UTC). Indicates fresh activity."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_conn() as c:
        r = c.execute(
            "SELECT COUNT(*) AS n FROM ksa_kitchen_tracker WHERE date(updated_at) = ?",
            (today,),
        )
        row = r.fetchone()
        return row["n"] if row else 0


def _get_developer_key() -> str:
    """Secret key from secrets; only who has it gets developer access. No email shown in UI."""
    try:
        return (st.secrets.get("DEVELOPER_KEY") or os.environ.get("DEVELOPER_KEY") or "").strip()
    except Exception:
        return ""


def _is_developer() -> bool:
    """True if session is unlocked with the developer key (no email shown in sidebar)."""
    return bool(st.session_state.get("developer_unlocked", False))


# —— Comments (Quip-style) ——
def add_comment(record_id: str, author: str, comment_text: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO record_comments (record_id, created_at, author, comment_text) VALUES (?, ?, ?, ?)",
            (record_id.strip(), now, (author or "Anonymous").strip(), (comment_text or "").strip()),
        )


def list_comments(record_id: str):
    with get_conn() as c:
        r = c.execute(
            "SELECT id, record_id, created_at, author, comment_text FROM record_comments WHERE record_id = ? ORDER BY created_at ASC",
            (record_id.strip(),),
        )
        return [dict(row) for row in r]


# —— Activity log (Quip-style history) ——
def log_record_activity(record_id: str, action: str, by_user: str = "", details: str = ""):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO record_activity (record_id, at, action, by_user, details) VALUES (?, ?, ?, ?, ?)",
            (record_id.strip(), now, action, (by_user or "").strip(), (details or "").strip()),
        )


def list_record_activity(record_id: str):
    with get_conn() as c:
        r = c.execute(
            "SELECT id, record_id, at, action, by_user, details FROM record_activity WHERE record_id = ? ORDER BY at DESC LIMIT 50",
            (record_id.strip(),),
        )
        return [dict(row) for row in r]


def list_recent_activity_global(limit: int = 20):
    """Recent activity across all records for Dashboard."""
    with get_conn() as c:
        r = c.execute(
            "SELECT id, record_id, at, action, by_user, details FROM record_activity ORDER BY at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in r]


# —— Saved views (global-tracker style) ——
def save_saved_view(name: str, filters: dict):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO saved_views (name, created_at, filters_json) VALUES (?, ?, ?)",
            (name.strip(), now, json.dumps(filters, ensure_ascii=False)),
        )


def list_saved_views():
    with get_conn() as c:
        r = c.execute("SELECT id, name, created_at, filters_json FROM saved_views ORDER BY created_at DESC")
        return [dict(row) for row in r]


def get_saved_view(view_id: int):
    with get_conn() as c:
        r = c.execute("SELECT id, name, created_at, filters_json FROM saved_views WHERE id = ?", (view_id,))
        row = r.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["filters_json"] = json.loads(d["filters_json"])
        except (json.JSONDecodeError, TypeError):
            d["filters_json"] = {}
        return d


def delete_saved_view(view_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))


def build_summary_report_html(rows: list) -> str:
    """Build an HTML summary report (global-tracker style) from tracker rows."""
    if not rows:
        return "<html><body><p>No data.</p></body></html>"
    total = len(rows)
    sites = len(set(r.get("site_id") for r in rows if r.get("site_id")))
    metrics = len(set(r.get("metric_name") for r in rows if r.get("metric_name")))
    regions = {}
    for r in rows:
        reg = r.get("region") or "—"
        regions[reg] = regions.get(reg, 0) + 1
    by_metric = {}
    for r in rows:
        m = r.get("metric_name") or "—"
        by_metric[m] = by_metric.get(m, 0) + 1
    last_updated = get_last_updated(rows) or "—"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>KSA Kitchens Summary Report</title>
<style>body{{font-family:sans-serif;margin:24px;background:#f8fafc;}} h1{{color:#0f172a;}} .card{{background:white;padding:16px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin:12px 0;}} table{{border-collapse:collapse;width:100%;}} th,td{{text-align:left;padding:8px;border-bottom:1px solid #e2e8f0;}} th{{color:#64748b;font-weight:600;}}</style></head><body>
<h1>KSA Kitchens Summary Report</h1>
<p>Generated {generated}</p>
<div class="card"><h2>Overview</h2><p><strong>Total records:</strong> {total} &nbsp;|&nbsp; <strong>Sites:</strong> {sites} &nbsp;|&nbsp; <strong>Metrics:</strong> {metrics} &nbsp;|&nbsp; <strong>Last updated:</strong> {last_updated}</p></div>
<div class="card"><h2>By region</h2><table><tr><th>Region</th><th>Count</th></tr>"""
    for reg, count in sorted(regions.items(), key=lambda x: -x[1]):
        html += f"<tr><td>{reg}</td><td>{count}</td></tr>"
    html += '</table></div><div class="card"><h2>By metric</h2><table><tr><th>Metric</th><th>Count</th></tr>'
    for m, count in sorted(by_metric.items(), key=lambda x: -x[1])[:30]:
        html += f"<tr><td>{m}</td><td>{count}</td></tr>"
    if len(by_metric) > 30:
        html += f"<tr><td colspan='2'>… and {len(by_metric) - 30} more</td></tr>"
    html += "</table></div></body></html>"
    return html


# —— Templates (Quip-style save/load) ——
def save_template(name: str, data: dict):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO tracker_templates (name, created_at, data) VALUES (?, ?, ?)",
            (name.strip(), now, json.dumps(data, ensure_ascii=False)),
        )


def list_templates():
    with get_conn() as c:
        r = c.execute("SELECT id, name, created_at, data FROM tracker_templates ORDER BY created_at DESC")
        return [dict(row) for row in r]


def get_template(template_id: int):
    with get_conn() as c:
        r = c.execute("SELECT id, name, created_at, data FROM tracker_templates WHERE id = ?", (template_id,))
        row = r.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["data"] = json.loads(d["data"])
        except (json.JSONDecodeError, TypeError):
            d["data"] = {}
        return d


def upsert_row(row):
    """Insert or replace by record_id (for CSV import)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO ksa_kitchen_tracker
               (record_id, report_date, site_id, site_name, region, metric_name, value, status, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row.get("record_id", "").strip(),
                row.get("report_date", "").strip(),
                row.get("site_id", "").strip(),
                row.get("site_name") or "",
                row.get("region") or "KSA",
                row.get("metric_name", "").strip(),
                row.get("value") if row.get("value") != "" else None,
                row.get("status") or "",
                row.get("notes") or "",
                now,
            ),
        )


def upsert_row(row):
    """Insert or replace (for CSV import)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            """INSERT INTO ksa_kitchen_tracker
               (record_id, report_date, site_id, site_name, region, metric_name, value, status, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(record_id) DO UPDATE SET
               report_date=excluded.report_date, site_id=excluded.site_id, site_name=excluded.site_name,
               region=excluded.region, metric_name=excluded.metric_name, value=excluded.value,
               status=excluded.status, notes=excluded.notes, updated_at=excluded.updated_at""",
            (
                row.get("record_id", "").strip(),
                row.get("report_date", "").strip(),
                row.get("site_id", "").strip(),
                row.get("site_name") or "",
                row.get("region") or "KSA",
                row.get("metric_name", "").strip(),
                row.get("value") if row.get("value") != "" else None,
                row.get("status") or "",
                row.get("notes") or "",
                now,
            ),
        )


def get_last_updated(rows):
    """Latest updated_at from rows (or None)."""
    times = [r.get("updated_at") for r in rows if r.get("updated_at")]
    return max(times) if times else None


def export_csv(rows):
    """Standardized CSV for stakeholders (same format as ETL output)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in EXPORT_COLUMNS})
    return buf.getvalue()


def export_csv_generic(rows: list[dict]) -> str:
    """Export any list of dicts to CSV (all keys; column order from first row)."""
    if not rows:
        return ""
    keys = list(rows[0].keys()) if rows else []
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in keys})
    return buf.getvalue()


def _dashboard_sources() -> list[tuple[str, str]]:
    """(display_name, source_id). source_id is 'main_tracker', 'exec_log', or tab_id."""
    out = [("Main tracker (kitchen data)", "main_tracker"), ("Execution Log", "exec_log")]
    for tab_id in SHEET_TAB_IDS[2:] + list_extra_tab_ids():
        out.append((tab_id, tab_id))
    return out


def _dashboard_load_source(source_id: str) -> list[dict]:
    """Load rows for the given dashboard source_id."""
    if source_id == "main_tracker":
        return list_rows()
    if source_id == "exec_log":
        return list_exec_log()  # already list of dicts
    return list_generic_tab(source_id)


# —— Auto Refresh Execution Log ——
def list_exec_log():
    with get_conn() as c:
        r = c.execute(
            "SELECT id, refresh_time, sheet, operation, status, user FROM ksa_auto_refresh_execution_log ORDER BY refresh_time DESC"
        )
        return [dict(row) for row in r]


def insert_exec_log(row):
    with get_conn() as c:
        c.execute(
            """INSERT INTO ksa_auto_refresh_execution_log (refresh_time, sheet, operation, status, user)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (row.get("refresh_time") or "").strip(),
                (row.get("sheet") or "").strip(),
                (row.get("operation") or "").strip(),
                (row.get("status") or "").strip(),
                (row.get("user") or "").strip(),
            ),
        )


# —— Generic tab data (any sheet tab: SF Kitchen Data, Area Data, etc.) ——
def list_generic_tab(tab_id):
    with get_conn() as c:
        r = c.execute(
            "SELECT data FROM generic_tab_data WHERE tab_id = ? ORDER BY row_index",
            (tab_id,),
        )
        return [json.loads(row[0]) for row in r]


def list_extra_tab_ids() -> list[str]:
    """Tab IDs that have data in generic_tab_data but are not in SHEET_TAB_IDS (e.g. from Excel sheets)."""
    known = set(SHEET_TAB_IDS)
    with get_conn() as c:
        r = c.execute("SELECT DISTINCT tab_id FROM generic_tab_data ORDER BY tab_id")
        return [row[0] for row in r if row[0] not in known]


def _search_all_tabs(term: str) -> dict:
    """Search across main Tracker, Execution Log, and all generic tabs. Returns {tab_id: [matching rows]}."""
    if not term or not term.strip():
        return {}
    q = term.strip().lower()
    out = {}

    # Main Tracker
    rows = list_rows()
    matches = [r for r in rows if any(q in str(v).lower() for v in (r or {}).values() if v is not None)]
    if matches:
        out[MAIN_TRACKER_TAB_ID] = matches

    # Auto Refresh Execution Log
    log_rows = list_exec_log()
    log_matches = [dict(r) for r in log_rows if any(q in str(v).lower() for v in (r or {}).values() if v is not None)]
    if log_matches:
        out["Auto Refresh Execution Log"] = log_matches

    # Generic tabs (fixed list + any extra from loaded workbooks)
    for tab_id in SHEET_TAB_IDS[2:] + list_extra_tab_ids():
        rows = list_generic_tab(tab_id)
        matches = [r for r in rows if any(q in str(v).lower() for v in (r or {}).values() if v is not None)]
        if matches:
            out[tab_id] = matches

    return out


def save_generic_tab(tab_id, rows):
    with get_conn() as c:
        c.execute("DELETE FROM generic_tab_data WHERE tab_id = ?", (tab_id,))
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                row = dict(row)
            c.execute(
                "INSERT INTO generic_tab_data (tab_id, row_index, data) VALUES (?, ?, ?)",
                (tab_id, i, json.dumps(row, ensure_ascii=False)),
            )


def _get_google_credentials_path():
    """Resolve path to Google service account JSON for Sheets API."""
    # Streamlit secrets (e.g. on Cloud)
    if hasattr(st, "secrets") and st.secrets:
        p = st.secrets.get("google_credentials_path") or st.secrets.get("GOOGLE_APPLICATION_CREDENTIALS")
        if p and Path(p).exists():
            return str(p)
    # Env
    p = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if p and Path(p).exists():
        return p
    # Repo paths
    for rel in ["scripts/credentials.json", ".secrets/gsheet-service.json", "app/data/credentials.json"]:
        path = REPO_ROOT / rel
        if path.exists():
            return str(path)
    return None


def _get_trino_config():
    """Trino connection: from env TRINO_HOST, TRINO_PORT, TRINO_CATALOG, TRINO_USER or Streamlit secrets."""
    try:
        secrets = getattr(st, "secrets", None) or {}
        host = os.environ.get("TRINO_HOST") or secrets.get("TRINO_HOST") or secrets.get("trino_host")
        port = int(os.environ.get("TRINO_PORT", "443") or secrets.get("TRINO_PORT") or secrets.get("trino_port") or "443")
        catalog = os.environ.get("TRINO_CATALOG", "google_spreadsheets") or secrets.get("TRINO_CATALOG") or secrets.get("trino_catalog") or "google_spreadsheets"
        user = os.environ.get("TRINO_USER", "trino") or secrets.get("TRINO_USER") or secrets.get("trino_user") or "trino"
        if host:
            return {"host": host, "port": port, "catalog": catalog, "user": user}
    except Exception:
        pass
    return None


def _fetch_trino_sheet(tab_name: str, config: dict) -> list[dict]:
    """Run one Trino sheet query; return list of dicts (column name -> value)."""
    try:
        from trino.dbapi import connect
    except ImportError:
        raise ImportError("Trino support requires: pip install trino") from None
    query = (
        "SELECT * FROM TABLE(google_spreadsheets.system.sheet("
        f"id => '{SHEET_ID}', "
        f"range => '{tab_name}!A1:Z1000'))"
    )
    conn = connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        catalog=config["catalog"],
        schema="system",
        http_scheme="https" if config["port"] == 443 else "http",
    )
    rows = []
    cur = conn.cursor()
    try:
        cur.execute(query)
        if cur.description:
            columns = [d[0] for d in cur.description]
            for row in cur.fetchall():
                rows.append(dict(zip(columns, ((str(v) if v is not None else "") for v in row))))
    finally:
        cur.close()
        conn.close()
    return rows


def _refresh_from_trino():
    """Pull sheet data via Trino (same queries as Superset) and load into app DB. Returns (success, message)."""
    try:
        config = _get_trino_config()
        if not config:
            return False, "Trino not configured. Set TRINO_HOST (and optionally TRINO_PORT, TRINO_CATALOG, TRINO_USER) in env or Streamlit secrets."
        loaded = []
        errors = []
        for tab_name in TRINO_TAB_RANGES:
            try:
                rows = _fetch_trino_sheet(tab_name, config)
            except Exception as e:
                errors.append(f"{tab_name}: {e}")
                continue
            if not rows:
                continue
            tab_id = MAIN_TRACKER_TAB_ID if (tab_name.strip() in KITCHEN_TRACKER_SHEET_ALIASES or tab_name.strip().lower() in {s.strip().lower() for s in KITCHEN_TRACKER_SHEET_ALIASES}) else tab_name
            if tab_id == "Auto Refresh Execution Log":
                with get_conn() as c:
                    c.execute("DELETE FROM ksa_auto_refresh_execution_log")
                for r in rows:
                    insert_exec_log({
                        "refresh_time": _row_key(r, "Refresh Time", "refresh_time") or datetime.now().strftime("%m/%d/%Y %H:%M"),
                        "sheet": _row_key(r, "Sheet", "sheet"),
                        "operation": _row_key(r, "Operation", "operation"),
                        "status": _row_key(r, "Status", "status"),
                        "user": _row_key(r, "User", "user"),
                    })
                loaded.append(f"{tab_id} ({len(rows)} rows)")
            elif _is_main_tracker_tab(tab_id):
                for r in rows:
                    row = _normalize_gsheet_row(r)
                    rid = (row.get("record_id") or "").strip()
                    if not rid:
                        continue
                    if not row.get("report_date") or not row.get("site_id") or not row.get("region") or not row.get("metric_name"):
                        continue
                    upsert_row(row)
                loaded.append(f"{tab_id} ({len(rows)} rows)")
            else:
                save_generic_tab(tab_id, rows)
                loaded.append(f"{tab_id} ({len(rows)} rows)")
        if loaded:
            return True, "Loaded via Trino: " + "; ".join(loaded)
        if errors:
            return False, "Trino connection or query failed (e.g. host unreachable from this machine). First error: " + (errors[0][:200] if errors else "")
        return False, "No data returned from Trino."
    except Exception as e:
        return False, "Trino refresh failed: " + str(e)


def _fetch_online_sheet(sheet_id: str, credentials_path: str) -> dict:
    """Fetch all worksheets from the online Google Sheet. Returns {worksheet_title: list of dicts}."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Install: pip install gspread google-auth") from None
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
        # Pad short rows so zip doesn't drop columns
        data = []
        for row in rows[1:]:
            r = list(row) + [""] * (len(headers) - len(row))
            data.append(dict(zip(headers, r[: len(headers)])))
        out[ws.title] = data
    return out


def _row_key(row: dict, *keys) -> str:
    """First non-empty key (case-insensitive) from row."""
    row_lower = {str(k).strip().lower(): v for k, v in (row or {}).items()}
    for k in keys:
        for rk, v in row_lower.items():
            if rk == k.lower() and v:
                return str(v).strip()
    return ""


def _refresh_from_online_sheet():
    """Pull all tabs from the online sheet and load into app DB. Returns (success, message)."""
    creds_path = _get_google_credentials_path()
    if not creds_path:
        return False, "No Google credentials. Add a service account JSON at scripts/credentials.json or set GOOGLE_APPLICATION_CREDENTIALS. Share the sheet with the service account email (Viewer)."
    try:
        data = _fetch_online_sheet(SHEET_ID, creds_path)
    except Exception as e:
        return False, str(e)
    loaded = []
    for ws_title, rows in data.items():
        if not rows:
            continue
        # Match our tab names (exact or strip); main tracker accepts several sheet names
        tab_id = None
        if ws_title.strip() in KITCHEN_TRACKER_SHEET_ALIASES or ws_title.strip().lower() in {s.strip().lower() for s in KITCHEN_TRACKER_SHEET_ALIASES}:
            tab_id = MAIN_TRACKER_TAB_ID
        if tab_id is None:
            for tid in SHEET_TAB_IDS:
                if (tid == ws_title or tid.strip() == ws_title.strip() or
                    ws_title.strip().lower() == tid.strip().lower()):
                    tab_id = tid
                    break
        if tab_id is None:
            tab_id = ws_title
        if tab_id == "Auto Refresh Execution Log":
            with get_conn() as c:
                c.execute("DELETE FROM ksa_auto_refresh_execution_log")
            for r in rows:
                insert_exec_log({
                    "refresh_time": _row_key(r, "Refresh Time", "refresh_time") or datetime.now().strftime("%m/%d/%Y %H:%M"),
                    "sheet": _row_key(r, "Sheet", "sheet"),
                    "operation": _row_key(r, "Operation", "operation"),
                    "status": _row_key(r, "Status", "status"),
                    "user": _row_key(r, "User", "user"),
                })
            loaded.append(f"{tab_id} ({len(rows)} rows)")
        elif _is_main_tracker_tab(tab_id):
            for r in rows:
                row = _normalize_gsheet_row(r)
                rid = (row.get("record_id") or "").strip()
                if not rid:
                    continue
                if not row.get("report_date") or not row.get("site_id") or not row.get("region") or not row.get("metric_name"):
                    continue
                upsert_row(row)
            loaded.append(f"{tab_id} ({len(rows)} rows)")
        else:
            save_generic_tab(tab_id, rows)
            loaded.append(f"{tab_id} ({len(rows)} rows)")
    return True, "Loaded: " + "; ".join(loaded) if loaded else "No data in sheet."


def _render_generic_tab(tab_id, key_suffix="", is_developer=False):
    """Full tool UI for a generic sheet tab: upload CSV (developer only), view/filter, download."""
    rows = list_generic_tab(tab_id)
    sub_view, sub_upload = st.tabs(["View & filter", "Upload / replace"])

    with sub_upload:
        if not is_developer:
            st.info("Only developers can upload or replace this tab's data. Unlock **Developer access** in the sidebar.")
        else:
            st.caption("Upload CSV or Excel (.xlsx) to load or replace this tab's data. All records stay here.")
            upload = st.file_uploader("CSV or Excel", type=["csv", "xlsx", "xls"], key=f"gen_upload_{key_suffix}")
            if upload:
                try:
                    loaded = _parse_uploaded_file(upload)
                    if loaded:
                        save_generic_tab(tab_id, loaded)
                        st.success(f"Loaded {len(loaded)} row(s).")
                        _rerun()
                    else:
                        st.warning("File has no data rows.")
                except Exception as e:
                    st.error(f"Upload failed: {e}")

    with sub_view:
        if not rows:
            st.info("No data yet." + (" Click the **Upload / replace** tab above to load data." if is_developer else ""))
            return
        # Filter bar: clear visual section, then one filter per column
        cols = list(rows[0].keys()) if rows else []
        st.markdown(
            '<div style="background: linear-gradient(90deg, #F0FDFA 0%, #F8FAFC 100%); border-left: 4px solid #0F766E; '
            'padding: 10px 14px; margin-bottom: 12px; border-radius: 0 8px 8px 0; font-weight: 600; color: #134E4A;">'
            "Filter by column</div>",
            unsafe_allow_html=True,
        )
        n = len(cols)
        filter_cols = st.columns(min(n, 14) if n > 0 else 1)
        filter_vals = {}
        selectbox_cols = set()
        for i, col in enumerate(cols[: len(filter_cols)]):
            with filter_cols[i]:
                st.markdown(f'<span style="font-size: 0.85rem; font-weight: 600; color: #475569;">{col}</span>', unsafe_allow_html=True)
                uniq_vals = sorted({str(r.get(col, "")).strip() for r in rows if r.get(col) is not None and str(r.get(col, "")).strip()})
                if len(uniq_vals) <= 30:
                    opts = ["All"] + uniq_vals
                    filter_vals[col] = st.selectbox(col, opts, key=f"f_{key_suffix}_{col}", label_visibility="collapsed")
                    selectbox_cols.add(col)
                else:
                    filter_vals[col] = st.text_input(col, key=f"f_{key_suffix}_{col}", placeholder="Search…", label_visibility="collapsed")
        rows_shown = rows
        for col, val in filter_vals.items():
            if not val or val == "All":
                continue
            if col in selectbox_cols:
                rows_shown = [r for r in rows_shown if str(r.get(col, "")) == str(val)]
            else:
                term = str(val).strip().lower()
                if term:
                    rows_shown = [r for r in rows_shown if term in str(r.get(col, "") or "").lower()]
        extra = f" (first {len(filter_cols)} columns)" if len(cols) > len(filter_cols) else ""
        st.caption(f"Showing **{len(rows_shown)}** of **{len(rows)}** row(s){extra}. Leave empty or All for no filter.")
        st.divider()
        st.dataframe(rows_shown, use_container_width=True, hide_index=True)
        # Download CSV
        buf = io.StringIO()
        if rows_shown:
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_shown)
        st.download_button(
            "Download CSV",
            data=buf.getvalue(),
            file_name=f"{tab_id.replace(' ', '_')}.csv",
            mime="text/csv",
            key=f"dl_{key_suffix}",
        )


def main():
    st.set_page_config(page_title="KSA Kitchens Tracker", layout="wide")
    init_db()

    # Pre-fill name/email from URL so users can bookmark and avoid typing each time
    prefilled = (st.query_params.get("email") or st.query_params.get("name") or st.query_params.get("user") or "").strip()
    if prefilled:
        st.session_state["user_display_name"] = prefilled

    # KitchenPark-style theme: light header, teal hero + CTAs (match KitchenPark site)
    st.markdown("""
        <style>
        /* App: clean light background like KitchenPark */
        .stApp { background: #FAFBFC; font-family: sans-serif; }
        /* Header: light grey bar, dark text (like KitchenPark top nav) */
        header[data-testid="stHeader"] {
            background: #F1F3F4 !important;
            border-bottom: 1px solid #E2E8F0;
        }
        header[data-testid="stHeader"] * { color: #1E293B !important; }
        /* Sidebar: white, teal accent stripe */
        section[data-testid="stSidebar"] {
            background: #FFFFFF;
            border-right: 4px solid #0F766E;
        }
        section[data-testid="stSidebar"] .stMarkdown { color: #1E293B !important; font-weight: 600 !important; }
        /* Page title = hero block: teal bar, white headline (like "Commercial kitchen spaces...") */
        h1 {
            background: #0F766E !important;
            color: white !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em !important;
            padding: 20px 28px !important;
            margin: 0 0 1.5rem 0 !important;
            border-radius: 0 10px 10px 0 !important;
            box-shadow: 0 2px 8px rgba(15,118,110,0.2);
        }
        h2, h3 { color: #1E293B !important; font-weight: 600 !important; }
        /* Tabs: neutral bar, selected = solid teal (like CONTACT US button) */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px; background: #F1F5F9; padding: 8px; border-radius: 10px;
            overflow-x: auto !important; overflow-y: hidden;
            flex-wrap: nowrap !important;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: thin;
            padding-bottom: 8px;
        }
        .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { height: 8px; }
        .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-thumb { background: #94A3B8; border-radius: 4px; }
        .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-thumb:hover { background: #0F766E; }
        .stTabs [data-baseweb="tab"] { padding: 10px 18px; border-radius: 8px; font-weight: 500; flex-shrink: 0; color: #475569; }
        .stTabs [aria-selected="true"] {
            background: #0F766E !important;
            color: white !important;
        }
        .stTabs [aria-selected="true"] span { color: white !important; }
        /* Primary buttons: solid teal like CONTACT US */
        .stButton > button { border-radius: 8px; font-weight: 500; }
        .stButton > button[kind="primary"] {
            background: #0F766E !important;
            border: none !important;
            color: white !important;
        }
        .stButton > button[kind="primary"]:hover {
            background: #0D9488 !important;
            color: white !important;
        }
        /* Expanders: light grey, teal left border */
        .streamlit-expanderHeader { background: #F8FAFC; border-radius: 8px; font-weight: 500; border-left: 4px solid #0F766E; }
        /* Filter inputs: consistent, polished */
        .stTextInput input, .stSelectbox > div { border-radius: 6px !important; background: #F8FAFC !important; border: 1px solid #E2E8F0 !important; }
        .stTextInput input:focus { border-color: #0F766E !important; box-shadow: 0 0 0 1px #0F766E !important; }
        /* Dataframes: clean card, clear header */
        .stDataFrame { border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #E2E8F0; }
        .stDataFrame thead th { background: #F1F5F9 !important; color: #1E293B !important; font-weight: 600 !important; padding: 10px 12px !important; border-bottom: 2px solid #0F766E !important; }
        .stDataFrame tbody td { padding: 8px 12px !important; }
        /* Metrics / captions: dark grey */
        [data-testid="stMetricValue"] { color: #1E293B !important; font-weight: 600 !important; }
        [data-testid="stMetricLabel"] { color: #64748B !important; }
        .stCaption { color: #64748B !important; }
        div[data-testid="stVerticalBlock"] > div { padding-top: 0.25rem; }
        </style>
        """, unsafe_allow_html=True)

    # Sidebar (KitchenPark-style: logo + header)
    logo_path = _logo_path()
    if logo_path:
        st.sidebar.image(str(logo_path), use_container_width=True)
    else:
        st.sidebar.markdown('<span style="color: #2E7D6E; font-size: 1.4rem; font-weight: 700;">KitchenPark</span>', unsafe_allow_html=True)
    st.sidebar.markdown("**KSA Kitchens Tracker**")
    st.sidebar.caption("KSA kitchen data & execution log")
    # Log this session once (for analytics); show record count — more meaningful than "traffic"
    if not st.session_state.get("traffic_logged"):
        log_traffic()
        st.session_state["traffic_logged"] = True
    updated_today = get_records_updated_today_count()
    # Data pulse: status only (no exact count) — cooler label, less info leakage
    pulse_status = "Live" if updated_today > 0 else "Idle"
    st.sidebar.metric("Data pulse", pulse_status, help="Activity in the last 24h — status only, no counts shown")
    # Name / identity for comments, activity, and (optionally) developer visibility
    st.sidebar.text_input("Your name or email", key="user_display_name", placeholder="e.g. jane@company.com")
    current_user = (st.session_state.get("user_display_name") or "").strip()
    # Keep email in URL so refreshing or reopening the bookmarked link remembers you (no retyping)
    if current_user and current_user != prefilled:
        st.query_params["email"] = current_user
    st.sidebar.caption("Used for access, comments, and \"Updated by\". We save it in the URL — bookmark this page and you won't need to retype.")
    st.sidebar.markdown("---")
    st.sidebar.caption("Developed by **RevOps** team")

    is_developer = _is_developer()

    # Helper: list of configured developer identifiers from secrets/env
    def _get_developer_ids_list() -> list[str]:
        try:
            ids = st.secrets.get("DEVELOPER_IDS") or os.environ.get("DEVELOPER_IDS", "")
        except Exception:
            ids = os.environ.get("DEVELOPER_IDS", "")
        return [s.strip().lower() for s in str(ids).split(",") if s.strip()]

    # Optionally hide the Developer access section for non-developer users.
    # If DEVELOPER_IDS is set (comma-separated names/emails),
    # only those identifiers (case-insensitive) will see this expander.
    def _developer_section_visible(user: str) -> bool:
        """Show Developer access only for configured developers.

        If DEVELOPER_IDS is set (comma-separated), only those names/emails
        will ever see the Developer access box. If it is NOT set, the box
        is hidden for everyone (no public developer UI).
        """
        ids_list = _get_developer_ids_list()
        if not ids_list:
            # No explicit developer list configured: hide for all users
            return False
        if _is_developer():
            return True
        return (user or "").strip().lower() in ids_list

    # If the current user is listed in DEVELOPER_IDS, auto-unlock developer mode
    dev_ids = _get_developer_ids_list()
    if dev_ids and (current_user or "").strip().lower() in dev_ids and not is_developer:
        st.session_state["developer_unlocked"] = True
        is_developer = True

    if _developer_section_visible(current_user):
        with st.sidebar.expander("Developer access", expanded=False):
            if is_developer:
                st.caption("Unlocked for this session.")
                if st.button("Lock", key="dev_lock"):
                    st.session_state["developer_unlocked"] = False
                    _rerun()
            else:
                key_in = st.text_input("Key", type="password", key="dev_key_input", placeholder="Enter key")
                if st.button("Unlock", key="dev_unlock") and key_in.strip():
                    if key_in.strip() == _get_developer_key() and _get_developer_key():
                        st.session_state["developer_unlocked"] = True
                        _rerun()
                    else:
                        st.error("Invalid key")

    st.sidebar.divider()
    section = st.sidebar.radio(
        "Section",
        ["Dashboard", "Discussions", "Data", "Search"],
        index=0,
        label_visibility="collapsed",
    )

    # Access control: if allowlist is enabled, only allowed users (or developers) can see content
    current_user = (st.session_state.get("user_display_name") or "").strip()
    if _allowlist_enabled() and not _is_developer():
        if not current_user:
            st.warning("Enter your name or email in the sidebar to access the tracker.")
            st.info("If you don't have access, contact [Maysam on Slack](https://urbankitchens.slack.com/team/U0A9Q0NJ9KJ) to be added to the allowed users list.")
            st.stop()
        if not is_user_allowed(current_user):
            st.error("Access restricted. Your name or email is not on the authorized list.")
            st.caption("Contact [Maysam on Slack](https://urbankitchens.slack.com/team/U0A9Q0NJ9KJ) to be added, or sign in with developer access if you have the key.")
            st.stop()

    # Dashboard: choose any tab → filter → download report
    if section == "Dashboard":
        st.title("Dashboard")
        with st.expander("How this Dashboard works", expanded=False):
            st.markdown("""
            The **Dashboard** is a read-only overview of your main data (the **Data** section). It does not change any data.
            - **Top row:** Four numbers — total records, number of sites, number of metrics, and last updated time.
            - **Records by date:** Line chart of how many records exist per report date.
            - **Top regions / Top metrics:** Bar charts of the most common regions and metric names.
            - **Recent activity:** Last 15 changes (who created or updated which record).
            - **Summary report:** Download an HTML file with the same overview and tables (by region, by metric).
            - **Customize your data view:** Filter the main data by date, site, region, and metric; save and load named views. The Tracker tab has been removed; use this section to build your own views.
            To edit or add data, use **Data** in the sidebar.’            """)
        st.caption("Pick **any data source** (main tracker, Execution Log, or any Data tab), filter, and **download your report** as CSV.")
        sources = _dashboard_sources()
        source_options = [s[0] for s in sources]
        source_ids = {s[0]: s[1] for s in sources}
        chosen_label = st.selectbox(
            "Data source (any tab)",
            options=source_options,
            key="dash_source",
            help="Main tracker, Execution Log, or any Data tab — use this data for your report.",
        )
        source_id = source_ids.get(chosen_label, "main_tracker")
        rows = _dashboard_load_source(source_id)
        if not rows:
            st.info(f"No data in **{chosen_label}** yet. Use **Data** in the sidebar to import or add data.")
        else:
            total = len(rows)
            is_tracker = source_id == "main_tracker"
            # —— Filters: clean card-style ——
            st.markdown("---")
            st.subheader("Refine your data")
            if st.session_state.pop("dash_clear_filters", False):
                for key in ("dash_f_date_multi", "dash_f_site_multi", "dash_f_region_multi", "dash_f_metric_multi", "dash_search", "dash_f_status_filter"):
                    st.session_state[key] = [] if "multi" in key else ("" if key == "dash_search" else None)
                st.session_state["dash_from_date"] = None
                st.session_state["dash_to_date"] = None
                _rerun()
            view_id = st.session_state.pop("dash_apply_saved_view", None)
            if view_id is not None and is_tracker:
                v = get_saved_view(view_id)
                if v and isinstance(v.get("filters_json"), dict):
                    fj = v["filters_json"]
                    st.session_state["dash_f_date_multi"] = fj.get("report_date") or []
                    st.session_state["dash_f_site_multi"] = fj.get("site_id") or []
                    st.session_state["dash_f_region_multi"] = fj.get("region") or []
                    st.session_state["dash_f_metric_multi"] = fj.get("metric_name") or []
                    st.session_state["dash_search"] = fj.get("search") or ""
                    _rerun()
            search = st.text_input("Search in all columns", key="dash_search", placeholder="Type to filter rows by any column…")
            if is_tracker:
                no_status = [r for r in rows if not (r.get("status") or "").strip() or str(r.get("status") or "").strip().lower() in ("no status", "n/a", "na", "—", "-")]
                if no_status:
                    st.caption(f"**{len(no_status)}** records with no or empty status. ")
                    if st.button("Show only these", key="dash_show_no_status"):
                        st.session_state["dash_f_status_filter"] = "no_status"
                        _rerun()
                uniq = lambda k: sorted(set(r.get(k) for r in rows if r.get(k)))
                default_dates = [x for x in (st.session_state.get("dash_f_date_multi") or []) if x in uniq("report_date")]
                default_sites = [x for x in (st.session_state.get("dash_f_site_multi") or []) if x in uniq("site_id")]
                default_reg = [x for x in (st.session_state.get("dash_f_region_multi") or []) if x in uniq("region")]
                default_met = [x for x in (st.session_state.get("dash_f_metric_multi") or []) if x in uniq("metric_name")]
                with st.expander("Filter by column (optional)", expanded=False):
                    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
                    with c1:
                        st.multiselect("Report date", uniq("report_date"), default=default_dates, key="dash_f_date_multi", placeholder="All", label_visibility="visible")
                    with c2:
                        st.multiselect("Site", uniq("site_id"), default=default_sites, key="dash_f_site_multi", placeholder="All", label_visibility="visible")
                    with c3:
                        st.multiselect("Region", uniq("region"), default=default_reg, key="dash_f_region_multi", placeholder="All", label_visibility="visible")
                    with c4:
                        st.multiselect("Metric", uniq("metric_name"), default=default_met, key="dash_f_metric_multi", placeholder="All", label_visibility="visible")
                    with c5:
                        st.write("")
                        st.write("")
                        if st.button("Clear filters", key="dash_btn_clear"):
                            st.session_state["dash_clear_filters"] = True
                            _rerun()
                    # Optional date range (report_date between From and To)
                    st.caption("Optional date range (filters by report date):")
                    d1, d2 = st.columns(2)
                    with d1:
                        from_date = st.date_input("From report date", value=None, key="dash_from_date")
                    with d2:
                        to_date = st.date_input("To report date", value=None, key="dash_to_date")
            rows_filtered = rows
            if is_tracker:
                filters = {
                    "report_date": st.session_state.get("dash_f_date_multi") or None,
                    "site_id": st.session_state.get("dash_f_site_multi") or None,
                    "region": st.session_state.get("dash_f_region_multi") or None,
                    "metric_name": st.session_state.get("dash_f_metric_multi") or None,
                }
                rows_filtered = filter_rows(rows, {k: v for k, v in filters.items() if v})
                if st.session_state.get("dash_f_status_filter") == "no_status":
                    rows_filtered = [r for r in rows_filtered if not (r.get("status") or "").strip() or str(r.get("status") or "").strip().lower() in ("no status", "n/a", "na", "—", "-")]
                # Optional date range (report_date)
                from_date = st.session_state.get("dash_from_date")
                to_date = st.session_state.get("dash_to_date")
                if from_date or to_date:
                    def _parse_rd(s):
                        if not s:
                            return None
                        s = str(s).strip()[:10]
                        try:
                            return datetime.strptime(s, "%Y-%m-%d").date()
                        except Exception:
                            try:
                                return datetime.strptime(s, "%d/%m/%Y").date()
                            except Exception:
                                return None
                    rows_filtered = [
                        r for r in rows_filtered
                        if (_parse_rd(r.get("report_date")) is not None
                            and (from_date is None or _parse_rd(r.get("report_date")) >= from_date)
                            and (to_date is None or _parse_rd(r.get("report_date")) <= to_date))
                    ]
            if (search or "").strip():
                term = (search or "").strip().lower()
                all_keys = set()
                for r in rows_filtered:
                    all_keys.update(r.keys() if isinstance(r, dict) else [])
                rows_filtered = [r for r in rows_filtered if any(term in str(r.get(k) or "").lower() for k in (all_keys or ["_"]))]
            st.markdown("---")
            st.caption(f"**{len(rows_filtered)}** of **{total}** rows")
            if total > 0 and len(rows_filtered) == 0:
                st.info("No rows match your filters. Try clearing or relaxing filters.")
            # Column picker: choose which columns to show in the table
            if rows_filtered:
                all_cols = list(rows_filtered[0].keys()) if rows_filtered else []
                default_show = st.session_state.get("dash_columns_show") or all_cols
                default_show = [c for c in default_show if c in all_cols] or all_cols
                cols_to_show = st.multiselect("Columns to show", options=all_cols, default=default_show, key="dash_columns_show", placeholder="All columns")
                if not cols_to_show:
                    cols_to_show = all_cols
            if HAS_EXCEL and rows_filtered:
                display_df = pd.DataFrame(rows_filtered)[cols_to_show] if cols_to_show else pd.DataFrame(rows_filtered)
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            elif rows_filtered:
                for r in rows_filtered[:100]:
                    st.json({k: r[k] for k in (cols_to_show or r.keys()) if k in r} if (cols_to_show and set(cols_to_show) != set(r.keys())) else r)
                if len(rows_filtered) > 100:
                    st.caption(f"… and {len(rows_filtered) - 100} more.")
            if rows_filtered:
                csv_data = export_csv(rows_filtered) if is_tracker else export_csv_generic(rows_filtered)
                safe_name = (chosen_label or "report").replace(" ", "_")[:40]
                st.download_button("Download my report (CSV)", data=csv_data, file_name=f"{safe_name}.csv", mime="text/csv", key="dash_dl_report_csv")

            # —— Pivot view (like Excel pivot, interactive) ——
            if HAS_EXCEL and rows_filtered and len(rows_filtered) > 0:
                st.markdown("---")
                st.subheader("Pivot view")
                st.caption("Slice your data by rows and columns, then view as a table or heatmap.")
                df = pd.DataFrame(rows_filtered)
                cols = [c for c in df.columns if df[c].notna().any()]
                if len(cols) < 2:
                    st.caption("Need at least 2 columns to build a pivot.")
                else:
                    row_opts = ["— None —"] + cols
                    col_opts = ["— None —"] + cols
                    numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
                    agg_opts = ["Count"]
                    for c in numeric_cols:
                        agg_opts.append(f"Sum of {c}")
                        agg_opts.append(f"Mean of {c}")
                    pv_row = st.selectbox("Rows", row_opts, key="pivot_row")
                    pv_col = st.selectbox("Columns", col_opts, key="pivot_col")
                    pv_agg = st.selectbox("Value", agg_opts, key="pivot_agg")
                    if pv_row != "— None —" and pv_col != "— None —":
                        try:
                            if pv_agg == "Count":
                                pivot = pd.pivot_table(df, index=pv_row, columns=pv_col, aggfunc=len, fill_value=0)
                                pivot = pivot.rename(columns=lambda x: str(x))
                                pivot = pivot.astype(int)
                            else:
                                if pv_agg.startswith("Sum of "):
                                    val_col = pv_agg.replace("Sum of ", "")
                                    pivot = pd.pivot_table(df, index=pv_row, columns=pv_col, values=val_col, aggfunc="sum", fill_value=0)
                                else:
                                    val_col = pv_agg.replace("Mean of ", "")
                                    pivot = pd.pivot_table(df, index=pv_row, columns=pv_col, values=val_col, aggfunc="mean", fill_value=0)
                                pivot = pivot.round(2)
                                # Subtotals: row totals (right) and column total (bottom)
                                pivot["Total"] = pivot.sum(axis=1)
                                pivot.loc["Total", :] = pivot.sum(axis=0)
                            st.dataframe(pivot, use_container_width=True, hide_index=False)
                            # Download current pivot as CSV
                            try:
                                pivot_csv = pivot.to_csv()
                                st.download_button("Download pivot (CSV)", data=pivot_csv, file_name="dashboard_pivot.csv", mime="text/csv", key="dash_dl_pivot_csv")
                            except Exception:
                                pass
                            try:
                                import plotly.graph_objects as go
                                fig = go.Figure(data=go.Heatmap(
                                    z=pivot.values.tolist(),
                                    x=[str(x) for x in pivot.columns],
                                    y=[str(y) for y in pivot.index],
                                    colorscale="Teal",
                                    text=[[f"{v:.0f}" if isinstance(v, (int, float)) else str(v) for v in row] for row in pivot.values],
                                    texttemplate="%{text}",
                                    textfont={"size": 11},
                                    hovertemplate="%{y} × %{x}<br>Value: %{z}<extra></extra>",
                                ))
                                fig.update_layout(xaxis_title=pv_col, yaxis_title=pv_row, margin=dict(l=100, r=40, t=30, b=80), height=min(500, 200 + len(pivot) * 22))
                                st.plotly_chart(fig, use_container_width=True)
                            except Exception:
                                pass
                        except Exception as e:
                            st.caption(f"Could not build pivot: {e}")
            if is_tracker:
                saved_views = list_saved_views()
                view_opts = {"— None —": None}
                for v in saved_views:
                    view_opts[v["name"]] = v["id"]
                with st.expander("Save / load view (main tracker only)", expanded=False):
                    v1, v2, v3 = st.columns(3)
                    with v1:
                        chosen = st.selectbox("Load saved view", options=list(view_opts.keys()), key="dash_load_view")
                        if st.button("Apply", key="dash_apply_view_btn") and chosen and view_opts.get(chosen):
                            st.session_state["dash_apply_saved_view"] = view_opts[chosen]
                            _rerun()
                    with v2:
                        save_name = st.text_input("Save current filters as", key="dash_saved_view_name", placeholder="e.g. Riyadh weekly")
                    with v3:
                        if st.button("Save view", key="dash_save_view_btn") and (save_name or "").strip():
                            save_saved_view((save_name or "").strip(), {
                                "report_date": st.session_state.get("dash_f_date_multi") or [],
                                "site_id": st.session_state.get("dash_f_site_multi") or [],
                                "region": st.session_state.get("dash_f_region_multi") or [],
                                "metric_name": st.session_state.get("dash_f_metric_multi") or [],
                                "search": st.session_state.get("dash_search") or "",
                            })
                            st.success("Saved.")
                            _rerun()

            with st.expander("Recent activity", expanded=False):
                recent = list_recent_activity_global(15)
                if not recent:
                    st.caption("No activity yet.")
                else:
                    for a in recent:
                        st.caption(f"**{a.get('at', '')[:19]}** · {a.get('record_id', '')[:40]} · **{a.get('action', '')}** by {a.get('by_user') or '—'}")
        return

    # Search (all tabs)
    if section == "Search":
        st.title("Search")
        st.caption("Find text across main data, Execution Log, and every sheet tab.")
        search_input = st.text_input("Search", key="global_search_q", placeholder="Type to search across all data…")
        if st.button("Search", key="btn_global_search") or search_input:
            if search_input and search_input.strip():
                results = _search_all_tabs(search_input.strip())
                if not results:
                    st.info("No matches found.")
                else:
                    total = sum(len(rows) for rows in results.values())
                    st.success(f"Found **{total}** row(s) in **{len(results)}** tab(s).")
                    for tab_id, rows in results.items():
                        with st.expander(f"**{tab_id}** — {len(rows)} row(s)", expanded=True):
                            if rows and HAS_EXCEL:
                                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                            elif rows:
                                for i, r in enumerate(rows[:50]):
                                    st.json(r)
                                if len(rows) > 50:
                                    st.caption(f"… and {len(rows) - 50} more.")
            else:
                st.caption("Enter a search term and click Search.")
        return

    # Discussions: app-wide comments and questions (with replies)
    if section == "Discussions":
        st.title("Discussions")
        st.caption("Ask questions or add comments. You can reply to any post.")
        current_name = (st.session_state.get("user_display_name") or "").strip()
        all_posts = list_app_discussions(200)
        roots = [p for p in all_posts if p.get("parent_id") is None]
        replies_by_parent = {}
        for p in all_posts:
            pid = p.get("parent_id")
            if pid is not None:
                replies_by_parent.setdefault(pid, []).append(p)
        for r in replies_by_parent.values():
            r.sort(key=lambda x: x.get("id", 0))

        # Reply form (shown when user clicked "Reply" on a post)
        reply_to_id = st.session_state.get("discussion_reply_to_id")
        if reply_to_id is not None:
            root = next((p for p in all_posts if p.get("id") == reply_to_id), None)
            if root is None:
                st.session_state.pop("discussion_reply_to_id", None)
            else:
                with st.form("reply_form", clear_on_submit=True):
                    snippet = (root.get("message") or "")[:60] + ("…" if len(root.get("message") or "") > 60 else "")
                    st.caption(f"Replying to: **{snippet}**")
                    reply_author = st.text_input("Your name", value=current_name, key="reply_author", placeholder="e.g. Jane")
                    reply_message = st.text_area("Your reply", key="reply_message", placeholder="Type your reply…", height=80)
                    col_r1, col_r2 = st.columns(2)
                    with col_r1:
                        post_clicked = st.form_submit_button("Post reply")
                    with col_r2:
                        cancel_clicked = st.form_submit_button("Cancel")
                    if cancel_clicked:
                        st.session_state.pop("discussion_reply_to_id", None)
                        _rerun()
                    if post_clicked:
                        if not (reply_message or "").strip():
                            st.error("Please enter a reply.")
                        else:
                            insert_app_discussion(reply_author or "Anonymous", reply_message.strip(), parent_id=reply_to_id)
                            st.session_state.pop("discussion_reply_to_id", None)
                            st.success("Reply posted.")
                            _rerun()
                st.divider()

        with st.form("discussion_form", clear_on_submit=True):
            author = st.text_input("Your name", value=current_name, key="discussion_author", placeholder="e.g. Jane")
            message = st.text_area("Comment or question", key="discussion_message", placeholder="Type your message…", height=120)
            if st.form_submit_button("Post"):
                if not (message or "").strip():
                    st.error("Please enter a message.")
                else:
                    insert_app_discussion(author or "Anonymous", message.strip())
                    st.success("Posted.")
                    _rerun()
        st.divider()
        st.subheader("Recent discussions")
        if not roots:
            st.info("No discussions yet. Post a comment or question above.")
        else:
            for p in roots:
                with st.container():
                    st.markdown(
                        f"**{p.get('author') or 'Anonymous'}** · {p.get('created_at', '')[:19].replace('T', ' ')}"
                    )
                    st.markdown(p.get("message", ""))
                    if st.button("Reply", key=f"reply_btn_{p.get('id')}"):
                        st.session_state["discussion_reply_to_id"] = p.get("id")
                        _rerun()
                    for r in replies_by_parent.get(p.get("id"), []):
                        st.markdown(
                            f"↳ **{r.get('author') or 'Anonymous'}** · {r.get('created_at', '')[:19].replace('T', ' ')}"
                        )
                        st.markdown(r.get("message", ""))
                    st.divider()
        return

    # —— Data: all sheet tabs as horizontal tabs ——
    if section == "Data":
        st.title("Data")
        st.caption("All records live here. Add, filter, edit, and export from this page.")
        # Exports (moved from separate section)
        rows_for_export = list_rows()
        with st.expander("Exports", expanded=False):
            if not rows_for_export:
                st.caption("No data yet. Import or add data in the **Data** section below.")
            else:
                csv_content = export_csv(rows_for_export)
                st.download_button("Download full CSV (ksa_kitchen_tracker.csv)", data=csv_content, file_name="ksa_kitchen_tracker.csv", mime="text/csv", key="dl_csv")
                report_html = build_summary_report_html(rows_for_export)
                st.download_button("Download summary report (HTML)", data=report_html, file_name="tracker_summary_report.html", mime="text/html", key="dl_report_exports")
        if is_developer:
            # One Excel file → all tabs (developer only)
            with st.expander("Import workbook (one Excel file → all tabs)", expanded=True):
                st.caption("Upload one .xlsx export. Sheets named **Smart Tracker**, **Kitchen Tracker**, or **KitchenTracker** load into the main Data tab; other sheets match by name. No credentials needed.")
                workbook_upload = st.file_uploader("Excel workbook (.xlsx)", type=["xlsx", "xls"], key="workbook_import")
                if workbook_upload:
                    try:
                        with st.spinner("Reading workbook (large files may take 1–2 min)…"):
                            data = _parse_workbook_all_sheets(workbook_upload)
                        prog = st.progress(0, text="Loading into tabs…")
                        ok, msg = _load_workbook_into_db(data, progress_placeholder=prog)
                        if ok:
                            st.success(msg)
                            _rerun()
                        else:
                            st.warning(msg)
                    except Exception as e:
                        st.error(str(e))
            with st.expander("Refresh data from online sheet"):
                st.caption("Pull the latest data into the app. Choose one source:")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Google Sheet API** — service account JSON (share the sheet with its email).")
                    if st.button("Refresh from online sheet", key="btn_gsheet"):
                        with st.spinner("Loading from Google Sheet…"):
                            ok, msg = _refresh_from_online_sheet()
                        if ok:
                            st.success(msg)
                            _rerun()
                        else:
                            st.error(msg)
                with col2:
                    st.markdown("**Trino** — same queries as Superset. (From a PC, Trino may be unreachable; use Google Sheet API if so.)")
                    if st.button("Refresh from Trino", key="btn_trino"):
                        with st.spinner("Loading from Trino (this can take a minute)…"):
                            ok, msg = _refresh_from_trino()
                        if ok:
                            st.success(msg)
                            _rerun()
                        else:
                            st.error(msg)
        else:
            st.info("Import and refresh are available only to developers. Unlock **Developer access** in the sidebar.")
        github_data_url = _get_github_data_url()
        if is_developer and github_data_url:
            with st.expander("Load from GitHub", expanded=True):
                st.caption("Pull the latest data from your GitHub repo. **Excel (.xlsx)**: all sheets load into their tabs (Tracker, Execution Log, SF Kitchen Data, Pivot Table 10, etc.). **CSV**: loads into the Tracker tab only. Set **GITHUB_TRACKER_CSV_URL** in Settings → Secrets to the full **raw** URL.")
                st.code(github_data_url, language=None)
                if not github_data_url.startswith("https://raw.githubusercontent.com/"):
                    st.warning("The URL above should start with `https://raw.githubusercontent.com/`. If it is cut off or wrong, update it in app Secrets.")
                if st.button("Load from GitHub", key="btn_load_github"):
                    try:
                        url_lower = github_data_url.lower()
                        if url_lower.endswith(".xlsx") or url_lower.endswith(".xls"):
                            with st.spinner("Fetching Excel from GitHub…"):
                                workbook_data = _fetch_workbook_from_url(github_data_url)
                            if not workbook_data:
                                st.error("Could not parse the Excel file.")
                                _rerun()
                            prog = st.progress(0, text="Loading all sheets into tabs…")
                            ok, msg = _load_workbook_into_db(workbook_data, progress_placeholder=prog)
                            prog.empty()
                            if ok:
                                st.success(msg)
                                _rerun()
                            else:
                                st.warning(msg)
                        else:
                            with st.spinner("Fetching from GitHub…"):
                                rows_from_file = _fetch_and_parse_from_url(github_data_url)
                            if not rows_from_file:
                                st.warning("The file is empty or has no data rows.")
                                _rerun()
                            imported = 0
                            for r in rows_from_file:
                                row = _normalize_gsheet_row(dict(r))
                                rid = (row.get("record_id") or "").strip()
                                if not rid:
                                    continue
                                if not row.get("report_date") or not row.get("site_id") or not row.get("region") or not row.get("metric_name"):
                                    continue
                                upsert_row({
                                    "record_id": rid,
                                    "report_date": (row.get("report_date") or "").strip(),
                                    "site_id": (row.get("site_id") or "").strip(),
                                    "site_name": row.get("site_name") or "",
                                    "region": row.get("region") or "KSA",
                                    "metric_name": (row.get("metric_name") or "").strip(),
                                    "value": row.get("value"),
                                    "status": row.get("status") or "",
                                    "notes": row.get("notes") or "",
                                })
                                imported += 1
                            if imported > 0:
                                st.success(f"Imported {imported} row(s) into Tracker. Existing record_ids were updated.")
                                _rerun()
                            else:
                                sample = rows_from_file[0] if rows_from_file else {}
                                file_columns = list(sample.keys()) if isinstance(sample, dict) else []
                                st.warning(
                                    f"**No rows were imported** (0 of {len(rows_from_file)}). "
                                    "Each row needs: **record_id**, **report_date**, **site_id**, **region**, **metric_name**. "
                                    "Your file's columns: **" + ", ".join(str(c) for c in file_columns[:15]) + ("…" if len(file_columns) > 15 else "") + "**. "
                                    "Rename columns to match (e.g. 'Record ID' → record_id) or use an **Excel file** with multiple sheets to load all tabs."
                                )
                    except HTTPError as e:
                        st.error(f"Could not fetch from GitHub (HTTP {e.code}): {e.reason}. Check that the URL is correct and the repo/file is **public**. Use the **Raw** link from the file page on GitHub.")
                    except URLError as e:
                        st.error(f"Could not reach GitHub: {e.reason}. Check the URL and your network.")
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"Import failed: {e}")
        if is_developer:
            with st.expander("Import from CSV or Excel", expanded=False):
                st.caption("Upload CSV or Excel (.xlsx) to import into the main data. Columns: record_id, report_date, site_id, site_name, region, metric_name, value, status, notes.")
                upload = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"], key="import_csv")
                if upload:
                    try:
                        rows_from_file = _parse_uploaded_file(upload)
                        imported = 0
                        for r in rows_from_file:
                            row = _normalize_gsheet_row(dict(r))
                            rid = (row.get("record_id") or "").strip()
                            if not rid:
                                continue
                            if not row.get("report_date") or not row.get("site_id") or not row.get("region") or not row.get("metric_name"):
                                continue
                            upsert_row({
                                "record_id": rid,
                                "report_date": (row.get("report_date") or "").strip(),
                                "site_id": (row.get("site_id") or "").strip(),
                                "site_name": row.get("site_name") or "",
                                "region": row.get("region") or "KSA",
                                "metric_name": (row.get("metric_name") or "").strip(),
                                "value": row.get("value"),
                                "status": row.get("status") or "",
                                "notes": row.get("notes") or "",
                            })
                            imported += 1
                        st.success(f"Imported {imported} row(s). Existing record_ids were updated.")
                        _rerun()
                    except Exception as e:
                        st.error(f"Import failed: {e}")
        # Exclude Tracker from tabs; Tracker data is customized on Dashboard instead
        all_tab_ids = [t for t in (SHEET_TAB_IDS + list_extra_tab_ids()) if t != MAIN_TRACKER_TAB_ID]
        sheet_tabs = st.tabs(all_tab_ids)
        # Tab tooltips: descriptions shown on hover
        tab_tips = [TAB_DESCRIPTIONS.get(tid, f"View and filter: {tid}") for tid in all_tab_ids]
        st.markdown(
            f'<script>(function(){{var d = {json.dumps(tab_tips)}; '
            'var tabs = document.querySelectorAll(".stTabs [data-baseweb=\\"tab\\"]"); '
            'tabs.forEach(function(tab, i){{ if(d[i]) tab.setAttribute("title", d[i]); }}); }})();</script>',
            unsafe_allow_html=True,
        )

        for tab_index, tab_id in enumerate(all_tab_ids):
            with sheet_tabs[tab_index]:
                if tab_id == "Auto Refresh Execution Log":
                    sub_list, sub_add = st.tabs(["List", "Add row"])
                    with sub_list:
                        rows_log = list_exec_log()
                        if not rows_log:
                            st.info("No rows yet." + (" Use **Add row** to add one." if is_developer else ""))
                        else:
                            st.markdown(
                                '<div style="background: linear-gradient(90deg, #F0FDFA 0%, #F8FAFC 100%); border-left: 4px solid #0F766E; '
                                'padding: 10px 14px; margin-bottom: 12px; border-radius: 0 8px 8px 0; font-weight: 600; color: #134E4A;">'
                                "Filter by column</div>",
                                unsafe_allow_html=True,
                            )
                            exec_cols = ["Refresh Time", "Sheet", "Operation", "Status", "User"]
                            exec_keys = ["refresh_time", "sheet", "operation", "status", "user"]
                            uniq = lambda k: sorted(set(r.get(k) for r in rows_log if r.get(k)))
                            fcols = st.columns(5)
                            filters_exec = {}
                            for i, (label, key) in enumerate(zip(exec_cols, exec_keys)):
                                with fcols[i]:
                                    st.markdown(f'<span style="font-size: 0.85rem; font-weight: 600; color: #475569;">{label}</span>', unsafe_allow_html=True)
                                    if key in ("sheet", "status", "user"):
                                        opts = uniq(key)
                                        filters_exec[key] = st.multiselect(label, opts, key=f"exec_f_{key}", placeholder="All", label_visibility="collapsed")
                                    else:
                                        filters_exec[key] = st.text_input(label, key=f"exec_f_{key}", placeholder="Search…", label_visibility="collapsed")
                            rows_shown = rows_log
                            for key in exec_keys:
                                val = filters_exec.get(key)
                                if key in ("sheet", "status", "user") and val:
                                    rows_shown = [r for r in rows_shown if r.get(key) in val]
                                elif key in ("refresh_time", "operation") and val and str(val).strip():
                                    term = str(val).strip().lower()
                                    rows_shown = [r for r in rows_shown if term in str(r.get(key) or "").lower()]
                            st.caption(f"Showing **{len(rows_shown)}** of **{len(rows_log)}** row(s).")
                            st.divider()
                            st.dataframe(
                                [{"Refresh Time": r["refresh_time"], "Sheet": r["sheet"], "Operation": r["operation"], "Status": r["status"], "User": r["user"]} for r in rows_shown],
                                use_container_width=True,
                                hide_index=True,
                            )
                    with sub_add:
                        if not is_developer:
                            st.info("Only developers can add rows here. Unlock **Developer access** in the sidebar.")
                        else:
                            with st.form("exec_log_form"):
                                refresh_time = st.text_input("Refresh Time *", value=datetime.now().strftime("%m/%d/%Y %H:%M"))
                                sheet = st.text_input("Sheet *", placeholder="e.g. Price Multipliers, SF Kitchen Data")
                                operation = st.text_input("Operation *", placeholder="e.g. Report Id: 000V0000003z 2092AI")
                                status = st.text_input("Status *", value="Success")
                                user = st.text_input("User *", placeholder="email@cloudkitchens.com")
                                if st.form_submit_button("Add"):
                                    if refresh_time and sheet and operation and status and user:
                                        insert_exec_log({"refresh_time": refresh_time, "sheet": sheet, "operation": operation, "status": status, "user": user})
                                        st.success("Added.")
                                        _rerun()
                                    else:
                                        st.error("Fill all required fields.")
                else:
                    _render_generic_tab(tab_id, key_suffix=(tab_id or str(tab_index)).replace(" ", "_"), is_developer=is_developer)

if __name__ == "__main__":
    main()
                    # Apply saved view (set filter state and rerun)
                    view_id = st.session_state.pop("apply_saved_view", None)
                    if view_id is not None:
                        v = get_saved_view(view_id)
                        if v and v.get("filters_json"):
                            f = v["filters_json"]
                            for key, sk in [("report_date", "f_date_multi"), ("site_id", "f_site_multi"), ("region", "f_region_multi"), ("metric_name", "f_metric_multi")]:
                                val = f.get(key)
                                st.session_state[sk] = val if isinstance(val, list) else ([val] if val else [])
                            st.session_state["smart_tracker_search"] = f.get("search", "")
                        _rerun()
                    last_updated = get_last_updated(rows)
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.metric("Total records", len(rows))
                    with c2:
                        st.metric("Sites", len(set(r.get("site_id") for r in rows if r.get("site_id"))))
                    with c3:
                        st.metric("Metrics", len(set(r.get("metric_name") for r in rows if r.get("metric_name"))))
                    with c4:
                        st.metric("Last updated", last_updated or "—")
                    st.divider()

                    # Saved views (global-tracker style)
                    with st.expander("Saved views", expanded=False):
                        saved_list = list_saved_views()
                        if saved_list:
                            view_opts = {f"{v['name']} ({v['created_at'][:10]})": v["id"] for v in saved_list}
                            sv_col1, sv_col2 = st.columns([2, 1])
                            with sv_col1:
                                chosen_view = st.selectbox("Load view", ["— None —"] + list(view_opts.keys()), key="saved_view_select")
                            with sv_col2:
                                if st.button("Apply view", key="apply_view_btn") and chosen_view and chosen_view != "— None —":
                                    st.session_state["apply_saved_view"] = view_opts.get(chosen_view)
                                    _rerun()
                        save_name = st.text_input("Save current filters as view", key="saved_view_name", placeholder="e.g. Riyadh weekly")
                        if st.button("Save view", key="save_view_btn") and save_name.strip():
                            save_saved_view(save_name.strip(), {
                                "report_date": st.session_state.get("f_date_multi") or [],
                                "site_id": st.session_state.get("f_site_multi") or [],
                                "region": st.session_state.get("f_region_multi") or [],
                                "metric_name": st.session_state.get("f_metric_multi") or [],
                                "search": st.session_state.get("smart_tracker_search", ""),
                            })
                            st.success("View saved.")
                            _rerun()

                    # Filter bar + row (same look as other tabs)
                    st.markdown(
                        '<div style="background: linear-gradient(90deg, #F0FDFA 0%, #F8FAFC 100%); border-left: 4px solid #0F766E; '
                        'padding: 10px 14px; margin-bottom: 12px; border-radius: 0 8px 8px 0; font-weight: 600; color: #134E4A;">'
                        "Filter by column</div>",
                        unsafe_allow_html=True,
                    )
                    tracker_cols = ["record_id", "report_date", "site_id", "site_name", "region", "metric_name", "value", "status", "notes"]
                    uniq = lambda k: sorted(set(r.get(k) for r in rows if r.get(k)))
                    multiselect_keys = ("report_date", "site_id", "region", "metric_name")
                    default_dates = [x for x in (st.session_state.get("f_date_multi") or []) if x in uniq("report_date")]
                    default_sites = [x for x in (st.session_state.get("f_site_multi") or []) if x in uniq("site_id")]
                    default_reg = [x for x in (st.session_state.get("f_region_multi") or []) if x in uniq("region")]
                    default_met = [x for x in (st.session_state.get("f_metric_multi") or []) if x in uniq("metric_name")]
                    fcols = st.columns(9)
                    filter_vals_tracker = {}
                    for i, col in enumerate(tracker_cols):
                        with fcols[i]:
                            st.markdown(f'<span style="font-size: 0.85rem; font-weight: 600; color: #475569;">{col}</span>', unsafe_allow_html=True)
                            if col in multiselect_keys:
                                opts = uniq(col)
                                default = default_dates if col == "report_date" else default_sites if col == "site_id" else default_reg if col == "region" else default_met
                                key = {"report_date": "f_date_multi", "site_id": "f_site_multi", "region": "f_region_multi", "metric_name": "f_metric_multi"}[col]
                                filter_vals_tracker[col] = st.multiselect(col, opts, default=default, key=key, placeholder="All", label_visibility="collapsed")
                            else:
                                filter_vals_tracker[col] = st.text_input(col, key=f"f_txt_{col}", placeholder="Filter…", label_visibility="collapsed")
                    clear_col, _ = st.columns([1, 8])
                    with clear_col:
                        if st.button("Clear all filters", key="btn_clear_filters"):
                            st.session_state["smart_tracker_clear_filters"] = True
                            _rerun()
                    filters = {
                        "report_date": None if not filter_vals_tracker.get("report_date") else filter_vals_tracker["report_date"],
                        "site_id": None if not filter_vals_tracker.get("site_id") else filter_vals_tracker["site_id"],
                        "region": None if not filter_vals_tracker.get("region") else filter_vals_tracker["region"],
                        "metric_name": None if not filter_vals_tracker.get("metric_name") else filter_vals_tracker["metric_name"],
                    }
                    rows_filtered = filter_rows(rows, filters)
                    for col in ("record_id", "site_name", "value", "status", "notes"):
                        val = (filter_vals_tracker.get(col) or "").strip() if isinstance(filter_vals_tracker.get(col), str) else ""
                        if val:
                            term = val.lower()
                            rows_filtered = [r for r in rows_filtered if term in str(r.get(col) or "").lower()]
                    # Saved view may restore a global search
                    saved_search = (st.session_state.get("smart_tracker_search") or "").strip()
                    if saved_search:
                        term = saved_search.lower()
                        rows_filtered = [r for r in rows_filtered if any(term in str(r.get(k) or "").lower() for k in ("record_id", "site_id", "site_name", "region", "metric_name", "status", "notes"))]
                    st.caption(f"Showing **{len(rows_filtered)}** of **{len(rows)}** record(s). Filters do not change stored data.")
                    st.divider()

                    # Summary charts (interactive: respond to current filters)
                    if rows_filtered:
                        if HAS_EXCEL:
                            df_f = pd.DataFrame(rows_filtered)
                            chart_col1, chart_col2 = st.columns(2)
                            with chart_col1:
                                by_region = df_f.get("region", pd.Series(dtype=object)).value_counts()
                                if not by_region.empty:
                                    st.bar_chart(pd.DataFrame({"Records": by_region}), height=220)
                            with chart_col2:
                                by_metric = df_f.get("metric_name", pd.Series(dtype=object)).value_counts()
                                if not by_metric.empty:
                                    st.bar_chart(pd.DataFrame({"Records": by_metric}), height=220)

                    # Single interactive table: edit in place, then Save or Download
                    display_cols = [c for c in EXPORT_COLUMNS if c in (rows_filtered[0] if rows_filtered else [])]
                    if not display_cols and rows_filtered:
                        display_cols = list(rows_filtered[0].keys())
                    if rows_filtered and display_cols:
                        df_display = pd.DataFrame(rows_filtered)[display_cols]
                        # Ensure all columns are string so st.data_editor TextColumn is compatible (avoids type errors)
                        df_display = df_display.astype(str).replace("nan", "")
                        if is_developer:
                            col_config = {c: st.column_config.TextColumn(c) for c in display_cols}
                            col_config["record_id"] = st.column_config.TextColumn("record_id", disabled=True)
                            edited_df = st.data_editor(
                                df_display,
                                column_config=col_config,
                                hide_index=True,
                                key="smart_tracker_editor",
                                use_container_width=True,
                                num_rows="fixed",
                            )
                            btn_col1, btn_col2, _ = st.columns([1, 1, 2])
                            with btn_col1:
                                if st.button("Save changes to database", key="btn_save_editor"):
                                    try:
                                        by_user = st.session_state.get("user_display_name", "")
                                        for _, r in edited_df.iterrows():
                                            rec = {}
                                            for k, v in r.to_dict().items():
                                                if v is None or (isinstance(v, float) and (v != v)):
                                                    rec[k] = None if k == "value" else ""
                                                else:
                                                    rec[k] = v
                                            rid = str(rec.get("record_id", "")).strip()
                                            if not rid:
                                                continue
                                            update_row(rid, rec, by_user=by_user)
                                        st.success("Saved.")
                                        _rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with btn_col2:
                                csv_filtered = export_csv(rows_filtered)
                                st.download_button(
                                    "Download filtered CSV",
                                    data=csv_filtered,
                                    file_name="smart_tracker_filtered.csv",
                                    mime="text/csv",
                                    key="dl_filtered_csv",
                                )
                        else:
                            st.dataframe(df_display, use_container_width=True, hide_index=True)
                            csv_filtered = export_csv(rows_filtered)
                            st.download_button(
                                "Download filtered CSV",
                                data=csv_filtered,
                                file_name="smart_tracker_filtered.csv",
                                mime="text/csv",
                                key="dl_filtered_csv",
                            )
                    elif rows_filtered:
                        st.caption("No standard columns to display. Use the **Exports** expander above for full data.")

                    # Comments & activity (Quip-style)
                    if rows_filtered:
                        with st.expander("Comments & activity (by record)"):
                            st.caption("Select a record to view or add comments and see activity history. Use **@name** in comments to mention someone.")
                            record_ids = [r.get("record_id") for r in rows_filtered if r.get("record_id")]
                            selected_rid = st.selectbox("Record", record_ids, key="comment_record_select", format_func=lambda x: str(x)[:60] + ("…" if len(str(x)) > 60 else ""))
                            if selected_rid:
                                activity = list_record_activity(selected_rid)
                                comments = list_comments(selected_rid)
                                ac, co = st.columns(2)
                                with ac:
                                    st.markdown("**Activity**")
                                    if not activity:
                                        st.caption("No activity yet.")
                                    else:
                                        for a in activity[:15]:
                                            who = (a.get("by_user") or "—") or "—"
                                            st.caption(f"{a.get('at', '')[:16]} · **{a.get('action', '')}** by {who}")
                                with co:
                                    st.markdown("**Comments**")
                                    for c in comments:
                                        st.caption(f"**{c.get('author', '')}** · {c.get('created_at', '')[:16]}")
                                        st.markdown(c.get("comment_text", ""))
                                    st.markdown("**Add comment**")
                                    with st.form("comment_form"):
                                        author = st.text_input("Your name", value=st.session_state.get("user_display_name", ""), key="comment_author")
                                        msg = st.text_area("Comment (use @name to mention)")
                                        if st.form_submit_button("Post"):
                                            if msg.strip():
                                                add_comment(selected_rid, author or "Anonymous", msg)
                                                st.success("Comment added.")
                                                _rerun()
                                            else:
                                                st.error("Enter a comment.")

            with tab_add:
                if not is_developer:
                    st.info("Only developers can add or edit source data. Unlock **Developer access** in the sidebar.")
                    st.caption("You can still view, filter, search, export, and add comments.")
                else:
                    st.caption("Add new records only. Required: record_id, report_date, site_id, region, metric_name.")
                    templates = list_templates()
                    template_options = {f"{t['name']} ({t['created_at'][:10]})": t["id"] for t in templates}
                    if template_options:
                        tcol1, tcol2 = st.columns([2, 1])
                        with tcol1:
                            chosen = st.selectbox("Load template", options=["— None —"] + list(template_options.keys()), key="template_select")
                        with tcol2:
                            if st.button("Apply template", key="btn_apply_tpl"):
                                if chosen and chosen != "— None —":
                                    tid = template_options.get(chosen)
                                    if tid:
                                        t = get_template(tid)
                                        if t and t.get("data"):
                                            st.session_state["add_form_template"] = t["data"]
                                            _rerun()
                        defaults = st.session_state.pop("add_form_template", None) or {}
                    else:
                        defaults = {}
                    with st.form("add_form"):
                        record_id = st.text_input("record_id *", value=defaults.get("record_id", ""))
                        report_date = st.text_input("report_date * (YYYY-MM-DD)", value=defaults.get("report_date", ""))
                        site_id = st.text_input("site_id *", value=defaults.get("site_id", ""))
                        site_name = st.text_input("site_name", value=defaults.get("site_name", ""))
                        region = st.text_input("region", value=defaults.get("region", "KSA"))
                        metric_name = st.text_input("metric_name *", value=defaults.get("metric_name", ""))
                        value = st.text_input("value (number or leave empty)", value=defaults.get("value", ""))
                        status = st.text_input("status", value=defaults.get("status", ""))
                        notes = st.text_input("notes", value=defaults.get("notes", ""))
                        if st.form_submit_button("Add"):
                            if record_id and report_date and site_id and region and metric_name:
                                by_user = st.session_state.get("user_display_name", "")
                                insert_row({
                                    "record_id": record_id.strip(),
                                    "report_date": report_date.strip(),
                                    "site_id": site_id.strip(),
                                    "site_name": site_name,
                                    "region": region or "KSA",
                                    "metric_name": metric_name.strip(),
                                    "value": value,
                                    "status": status,
                                    "notes": notes,
                                }, by_user=by_user)
                                st.success("Added.")
                                _rerun()
                            else:
                                st.error("Fill required fields: record_id, report_date, site_id, region, metric_name.")
                    with st.expander("Save as template"):
                        st.caption("Save current values as a reusable template for the Add form.")
                        with st.form("save_template_form"):
                            tpl_name = st.text_input("Template name", key="tpl_name", placeholder="e.g. Riyadh weekly")
                            tpl_id = st.text_input("record_id", key="tpl_record_id")
                            tpl_date = st.text_input("report_date", key="tpl_report_date")
                            tpl_site = st.text_input("site_id", key="tpl_site_id")
                            tpl_site_name = st.text_input("site_name", key="tpl_site_name")
                            tpl_region = st.text_input("region", value="KSA", key="tpl_region")
                            tpl_metric = st.text_input("metric_name", key="tpl_metric")
                            tpl_value = st.text_input("value", key="tpl_value")
                            tpl_status = st.text_input("status", key="tpl_status")
                            tpl_notes = st.text_input("notes", key="tpl_notes")
                            if st.form_submit_button("Save template"):
                                if tpl_name.strip():
                                    save_template(tpl_name.strip(), {
                                        "record_id": st.session_state.get("tpl_record_id", ""),
                                        "report_date": st.session_state.get("tpl_report_date", ""),
                                        "site_id": st.session_state.get("tpl_site_id", ""),
                                        "site_name": st.session_state.get("tpl_site_name", ""),
                                        "region": st.session_state.get("tpl_region", "KSA") or "KSA",
                                        "metric_name": st.session_state.get("tpl_metric", ""),
                                        "value": st.session_state.get("tpl_value", ""),
                                        "status": st.session_state.get("tpl_status", ""),
                                        "notes": st.session_state.get("tpl_notes", ""),
                                    })
                                    st.success("Template saved. Use \"Load template\" above to apply it.")
                                    _rerun()
                                else:
                                    st.error("Enter a template name.")

                else:
                    _render_generic_tab(tab_id, key_suffix=(tab_id or str(tab_index)).replace(" ", "_"), is_developer=is_developer)

if __name__ == "__main__":
    main()
