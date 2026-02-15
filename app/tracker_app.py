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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import streamlit as st

try:
    import pandas as pd
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

# Online sheet: same ID as the workbook
SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"

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
            continue  # Section removed; skip loading
        if _is_main_tracker_tab(tab_id):
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

# Hierarchy view: Country → Facility → Kitchen dropdowns. Source tab + column mapping.
HIERARCHY_SOURCE_TABS = ["SF Churn Data", "SF Kitchen Data", "Sellable No Status", "All no status kitchens", "KSA Facility details", "Price Multipliers", "Area Data"]
# Kitchens tab: kitchen-level data only (excludes Price Multipliers, Area Data, KSA Facility details)
KITCHENS_SOURCE_TABS = ["SF Kitchen Data", "SF Churn Data", "Sellable No Status", "All no status kitchens"]
# Countries in Salesforce (UAE, Bahrain, Kuwait, Saudi Arabia, Qatar) — merged with data-derived countries
SF_COUNTRIES = ["UAE", "Bahrain", "BH", "Kuwait", "KW", "Saudi Arabia", "SA", "Qatar", "QA"]
# Tabs for regular users (kitchen-only). Super users see all tabs.
KITCHEN_ONLY_TABS = ["SF Kitchen Data", "SF Churn Data", "KSA Facility details", "Sellable No Status", "All no status kitchens"]
# 6 reports as sidebar functions for super users only (all countries). Facility Sell Price Multipliers, etc.
SUPERUSER_REPORTS = ["Price Multipliers", "Area Data", "SF Churn Data", "SF Kitchen Data", "Sellable No Status", "All no status kitchens"]
# Country name aliases: normalize for matching (e.g. "United Arab Emirates" ↔ "UAE")
COUNTRY_ALIASES = {
    "uae": ["united arab emirates", "uae", "ae"],
    "sa": ["saudi arabia", "sa", "ksa"],
    "kw": ["kuwait", "kwt", "kw"],
    "bh": ["bahrain", "bh"],
    "qa": ["qatar", "qa"],
}
# Column names to try (case-insensitive). Supports SA, UAE, Kuwait, Bahrain, Qatar.
HIERARCHY_COUNTRY_CANDIDATES = ["Country", "Country Name", "Account.Country", "country"]
HIERARCHY_ACCOUNT_CANDIDATES = ["Account Name", "Account.Name", "account name"]
HIERARCHY_FACILITY_CANDIDATES = ["Facility", "Facility Name", "Account Name", "Account.Name"]
HIERARCHY_KITCHEN_CANDIDATES = ["Kitchen Number Name", "Kitchen_Number__c.Name", "Kitchen Number ID 18", "Kitchen", "Name"]

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

TABLE_DATA_REFRESH_LOG = """
CREATE TABLE IF NOT EXISTS data_refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refreshed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    tabs_count INTEGER
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
        c.execute(TABLE_DATA_REFRESH_LOG)
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


def _allowlist_ids_from_secrets() -> set[str]:
    """IDs (emails/names) from ALLOWLIST_IDS secrets/env, lowercased."""
    try:
        raw = st.secrets.get("ALLOWLIST_IDS") or os.environ.get("ALLOWLIST_IDS", "")
    except Exception:
        raw = os.environ.get("ALLOWLIST_IDS", "")
    ids: set[str] = set()
    for part in str(raw).split(","):
        s = part.strip()
        if s:
            ids.add(s.lower())
    return ids


def is_user_allowed(identifier: str) -> bool:
    """True if the given email/name is in the allowlist (secrets or DB, case-insensitive)."""
    id_ = (identifier or "").strip().lower()
    if not id_:
        return False

    # 1) From ALLOWLIST_IDS in secrets/env
    allowed = _allowlist_ids_from_secrets()

    # 2) From allowed_users table (Developer UI)
    with get_conn() as c:
        r = c.execute("SELECT identifier FROM allowed_users")
        for row in r:
            s = (row["identifier"] or "").strip().lower()
            if s:
                allowed.add(s)

    return id_ in allowed


def _super_user_ids() -> set[str]:
    """IDs (emails/names) from SUPER_USER_IDS secrets/env, lowercased. Super users see all Data tabs."""
    try:
        raw = st.secrets.get("SUPER_USER_IDS") or os.environ.get("SUPER_USER_IDS", "")
    except Exception:
        raw = os.environ.get("SUPER_USER_IDS", "")
    ids: set[str] = set()
    for part in str(raw).split(","):
        s = part.strip()
        if s:
            ids.add(s.lower())
    return ids


def is_super_user(identifier: str) -> bool:
    """True if user can see all tabs (Price Multipliers, Area Data, etc.). Developers are super users."""
    if _is_developer():
        return True
    id_ = (identifier or "").strip().lower()
    return id_ in _super_user_ids()


def _visible_data_tab_ids(user_identifier: str) -> list[str]:
    """Tab IDs to show in Data section: kitchen-only for regular users, all for super users."""
    all_ids = [t for t in (SHEET_TAB_IDS + list_extra_tab_ids()) if t != MAIN_TRACKER_TAB_ID]
    if is_super_user(user_identifier):
        return all_ids
    return [t for t in all_ids if t in KITCHEN_ONLY_TABS]


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


def log_data_refresh(source: str, tabs_count: int = 0) -> None:
    """Log a successful SF or Sheet refresh for freshness tracking."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO data_refresh_log (refreshed_at, source, tabs_count) VALUES (?, ?, ?)",
            (now, source.strip().lower()[:50], tabs_count),
        )


def get_last_data_refresh() -> tuple[str | None, str | None]:
    """(refreshed_at_iso, source) of most recent refresh, or (None, None)."""
    with get_conn() as c:
        r = c.execute(
            "SELECT refreshed_at, source FROM data_refresh_log ORDER BY id DESC LIMIT 1"
        )
        row = r.fetchone()
        if row:
            return (row["refreshed_at"], row["source"] or "unknown")
        return (None, None)


def _humanize_ago(iso_ts: str) -> str:
    """Humanized 'X mins ago', '2h ago', '3 days ago'."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - ts
        secs = int(delta.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return "just now"
        if secs < 3600:
            m = secs // 60
            return f"{m}m ago"
        if secs < 86400:
            h = secs // 3600
            return f"{h}h ago"
        if secs < 604800:
            d = secs // 86400
            return f"{d} day{'s' if d > 1 else ''} ago"
        w = secs // 604800
        return f"{w} week{'s' if w > 1 else ''} ago"
    except Exception:
        return "—"


def _auto_refresh_enabled() -> bool:
    """True if auto-refresh every N minutes is enabled. Defaults to True (no manual refresh needed). Set AUTO_REFRESH_ENABLED = false to disable."""
    try:
        v = st.secrets.get("AUTO_REFRESH_ENABLED") or os.environ.get("AUTO_REFRESH_ENABLED", "")
    except Exception:
        v = os.environ.get("AUTO_REFRESH_ENABLED", "")
    s = str(v).strip().lower()
    if not s:
        return True  # Default: enabled, refresh SF data every 15 mins without manual intervention
    return s in ("1", "true", "yes")


def _auto_refresh_minutes() -> int:
    """Minutes between auto-refreshes (AUTO_REFRESH_MINUTES, default 15)."""
    try:
        v = st.secrets.get("AUTO_REFRESH_MINUTES") or os.environ.get("AUTO_REFRESH_MINUTES", "15")
    except Exception:
        v = os.environ.get("AUTO_REFRESH_MINUTES", "15")
    try:
        return max(1, int(v))
    except (ValueError, TypeError):
        return 15


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
    """Insert or replace by record_id (for GSheet/Salesforce import)."""
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


def _dashboard_sources(user_identifier: str) -> list[tuple[str, str]]:
    """(display_name, source_id). Filtered by role: regular users see kitchen tabs only."""
    out = [("Main tracker (kitchen data)", "main_tracker")]
    for tab_id in _visible_data_tab_ids(user_identifier):
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


def _find_col(row: dict, *candidates: str) -> str | None:
    """Return first matching column key (case-insensitive) from row, or None."""
    keys_lower = {str(k).strip().lower(): k for k in (row or {}).keys()}
    for c in candidates:
        c0 = (c or "").strip().lower()
        if c0 in keys_lower:
            return keys_lower[c0]
        for k in keys_lower:
            if c0 in k or k in c0:
                return keys_lower[k]
    return None


def _extract_hierarchy_from_row(
    row: dict,
    account_col: str | None,
    kitchen_col: str | None,
    country_col: str | None = None,
    facility_col: str | None = None,
) -> tuple[str, str, str]:
    """Extract (country, facility, kitchen) from a row. Supports SA, UAE, Kuwait, Bahrain, Qatar."""
    country, facility, kitchen = "", "", ""
    # Prefer dedicated Country column (e.g. Price Multipliers: "Saudi Arabia", "UAE", "Kuwait")
    if country_col and row.get(country_col):
        country = str(row[country_col]).strip()
    # Prefer dedicated Facility column
    if facility_col and row.get(facility_col):
        facility = str(row[facility_col]).strip()
    # Fallback: parse from Account Name (e.g. "SA - RUH - Sweidi", "UAE - DXB - Bur Dubai")
    if account_col and row.get(account_col):
        parts = [p.strip() for p in str(row[account_col]).split(" - ") if p.strip()]
        if not country and len(parts) >= 1:
            country = parts[0]
        if not facility:
            if len(parts) >= 2:
                facility = " - ".join(parts[1:])
            elif len(parts) == 1:
                facility = parts[0]
    if kitchen_col and row.get(kitchen_col):
        kitchen = str(row[kitchen_col]).strip()
    return (country, facility, kitchen)


def _country_matches(a: str, b: str) -> bool:
    """True if a and b represent the same country (handles UAE/United Arab Emirates etc)."""
    if not a or not b:
        return a == b
    ax, bx = a.strip().lower(), b.strip().lower()
    if ax == bx:
        return True
    for canonical, aliases in COUNTRY_ALIASES.items():
        if ax in aliases and bx in aliases:
            return True
    return False


def _get_hierarchy_data() -> tuple[list[dict], str, str | None, str | None, str | None, str | None]:
    """
    Get rows from first available hierarchy source tab.
    Returns (rows, tab_id, account_col, kitchen_col, country_col, facility_col).
    """
    for tab_id in HIERARCHY_SOURCE_TABS:
        rows = list_generic_tab(tab_id)
        if not rows:
            continue
        r0 = rows[0]
        account_col = _find_col(r0, *HIERARCHY_ACCOUNT_CANDIDATES)
        kitchen_col = _find_col(r0, *HIERARCHY_KITCHEN_CANDIDATES)
        country_col = _find_col(r0, *HIERARCHY_COUNTRY_CANDIDATES)
        facility_col = _find_col(r0, *HIERARCHY_FACILITY_CANDIDATES)
        return (rows, tab_id, account_col, kitchen_col, country_col, facility_col)
    return ([], "", None, None, None, None)


def _get_combined_kitchens_dataset() -> tuple[list[dict], list[str], dict]:
    """
    Build a unified Kitchens dataset from kitchen-level tabs only (SF Kitchen Data, Churn, Sellable/No Status).
    Returns (rows, all_columns, col_map). Each row gets _Country, _Facility, _Kitchen, _Source.
    """
    all_rows: list[dict] = []
    all_keys: set[str] = set()
    col_map = {}

    for tab_id in KITCHENS_SOURCE_TABS:
        rows = list_generic_tab(tab_id)
        if not rows:
            continue
        r0 = rows[0]
        account_col = _find_col(r0, *HIERARCHY_ACCOUNT_CANDIDATES)
        kitchen_col = _find_col(r0, *HIERARCHY_KITCHEN_CANDIDATES)
        country_col = _find_col(r0, *HIERARCHY_COUNTRY_CANDIDATES)
        facility_col = _find_col(r0, *HIERARCHY_FACILITY_CANDIDATES)
        if not col_map:
            col_map = {"account_col": account_col, "kitchen_col": kitchen_col, "country_col": country_col, "facility_col": facility_col}

        for r in rows:
            c, f, k = _extract_hierarchy_from_row(r, account_col, kitchen_col, country_col, facility_col)
            row = dict(r)
            row["_Country"] = c
            row["_Facility"] = f
            row["_Kitchen"] = k
            row["_Source"] = tab_id
            all_rows.append(row)
            all_keys.update(row.keys())

    # Ensure consistent columns: _Source, _Country, _Facility, _Kitchen first, then rest
    meta = ["_Source", "_Country", "_Facility", "_Kitchen"]
    others = sorted(k for k in all_keys if k not in meta)
    columns = meta + others
    return (all_rows, columns, col_map)


def _hierarchy_filtered_rows(
    rows: list[dict],
    account_col: str | None,
    kitchen_col: str | None,
    country: str | None,
    facility: str | None,
    kitchen: str | None,
    country_col: str | None = None,
    facility_col: str | None = None,
) -> list[dict]:
    """Filter rows by selected country, facility, kitchen."""
    if not country and not facility and not kitchen:
        return rows
    filtered = []
    for r in rows:
        c, f, k = _extract_hierarchy_from_row(r, account_col, kitchen_col, country_col, facility_col)
        if country and not _country_matches(c, country):
            continue
        if facility and f != facility:
            continue
        if kitchen and k != kitchen:
            continue
        filtered.append(r)
    return filtered


def _get_google_credentials_path():
    """Resolve credentials for Google Sheets API.

    If [gsheet_service_account] is in Streamlit secrets, return a sentinel
    value so we know to use that dict instead of a file path.
    """
    # Prefer service account from Streamlit secrets
    try:
        if hasattr(st, "secrets") and "gsheet_service_account" in st.secrets:
            return "__FROM_SECRETS__"
    except Exception:
        pass

    # Fallbacks: old path-based behaviour
    if hasattr(st, "secrets") and st.secrets:
        p = st.secrets.get("google_credentials_path") or st.secrets.get("GOOGLE_APPLICATION_CREDENTIALS")
        if p and Path(p).exists():
            return str(p)
    p = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if p and Path(p).exists():
        return p
    for rel in ["scripts/credentials.json", ".secrets/gsheet-service.json", "app/data/credentials.json"]:
        path = REPO_ROOT / rel
        if path.exists():
            return str(path)
    return None


def _salesforce_token_from_refresh(
    consumer_key: str,
    consumer_secret: str,
    refresh_token: str,
    use_sandbox: bool = False,
) -> tuple[dict | None, str | None]:
    """Get access_token and instance_url via OAuth refresh_token flow. No username/password."""
    login_host = "https://test.salesforce.com" if use_sandbox else "https://login.salesforce.com"
    url = f"{login_host}/services/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": consumer_key,
        "client_secret": consumer_secret,
        "refresh_token": refresh_token,
    }
    try:
        resp = requests.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        if resp.ok:
            out = resp.json()
            base = (out.get("instance_url") or "").rstrip("/")
            token = out.get("access_token")
            if base and token:
                return ({"base_url": base, "token": token}, None)
            return (None, "Salesforce returned no instance_url or access_token.")
        try:
            err = resp.json()
            msg = err.get("error_description") or err.get("error") or resp.text or f"HTTP {resp.status_code}"
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        return (None, f"Salesforce OAuth: {msg}")
    except requests.RequestException as e:
        return (None, f"Network error: {e}")
    except Exception as e:
        return (None, str(e))


def _salesforce_token_from_password(
    consumer_key: str,
    consumer_secret: str,
    username: str,
    password: str,
    use_sandbox: bool = False,
) -> tuple[dict | None, str | None]:
    """Get access_token and instance_url via OAuth password flow. Returns (config, None) on success or (None, error_message) on failure."""
    login_host = "https://test.salesforce.com" if use_sandbox else "https://login.salesforce.com"
    url = f"{login_host}/services/oauth2/token"
    data = {
        "grant_type": "password",
        "client_id": consumer_key,
        "client_secret": consumer_secret,
        "username": username,
        "password": password,
    }
    try:
        resp = requests.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        if resp.ok:
            out = resp.json()
            base = (out.get("instance_url") or "").rstrip("/")
            token = out.get("access_token")
            if base and token:
                return ({"base_url": base, "token": token}, None)
            return (None, "Salesforce returned no instance_url or access_token.")
        # Capture Salesforce error for debugging
        try:
            err = resp.json()
            msg = err.get("error_description") or err.get("error") or resp.text or f"HTTP {resp.status_code}"
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        return (None, f"Salesforce OAuth: {msg}")
    except requests.RequestException as e:
        return (None, f"Network error: {e}")
    except Exception as e:
        return (None, str(e))


def _get_from_obj(obj, key: str):
    """Get value from obj (dict or Streamlit secret section)."""
    if obj is None:
        return None
    try:
        if hasattr(obj, "get"):
            v = obj.get(key)
            if v is not None:
                return v
        if hasattr(obj, "__getitem__"):
            return obj[key]
    except (KeyError, TypeError):
        pass
    try:
        return getattr(obj, key, None) or getattr(obj, key.lower(), None)
    except Exception:
        return None


def _sf_secret(secrets: dict, section, *key_variants: str) -> str:
    """Get first non-empty value from env, then section, then secrets, trying each key variant."""
    for key in key_variants:
        val = os.environ.get(key) or _get_from_obj(section, key) or secrets.get(key)
        if val and str(val).strip():
            return str(val).strip()
    # Fallback: SF_* keys may have been pasted under [gsheet_service_account] by mistake
    gsheet = secrets.get("gsheet_service_account") if isinstance(secrets, dict) else None
    if gsheet:
        for key in key_variants:
            val = _get_from_obj(gsheet, key)
            if val and str(val).strip():
                return str(val).strip()
    return ""


def _get_salesforce_config() -> dict | None:
    """Salesforce connection: use SF_ACCESS_TOKEN + SF_INSTANCE_URL, or Consumer Key/Secret + Username/Password."""
    try:
        raw = getattr(st, "secrets", None)
        try:
            secrets = dict(raw) if raw else {}
        except Exception:
            secrets = {}
        section = None
        try:
            section = secrets.get("salesforce") or (getattr(raw, "salesforce", None) if raw else None)
        except Exception:
            pass

        base_url = _sf_secret(secrets, section, "SF_INSTANCE_URL", "sf_instance_url")
        token = _sf_secret(secrets, section, "SF_ACCESS_TOKEN", "sf_access_token")
        if base_url and token:
            return {"base_url": base_url.rstrip("/"), "token": token}

        consumer_key = _sf_secret(secrets, section, "SF_CONSUMER_KEY", "sf_consumer_key")
        consumer_secret = _sf_secret(secrets, section, "SF_CONSUMER_SECRET", "sf_consumer_secret")
        refresh_token = _sf_secret(secrets, section, "SF_REFRESH_TOKEN", "sf_refresh_token")
        use_sandbox_raw = _sf_secret(secrets, section, "SF_USE_SANDBOX", "sf_use_sandbox") or ""
        use_sandbox = use_sandbox_raw.lower() in ("1", "true", "yes")

        # Option 1: Refresh token (no username/password)
        if consumer_key and consumer_secret and refresh_token:
            cache_key = "sf_api_config_cache"
            cache = st.session_state.get(cache_key)
            if isinstance(cache, dict) and cache.get("expires_at") and datetime.now(timezone.utc).timestamp() < cache.get("expires_at", 0):
                return {"base_url": cache["base_url"], "token": cache["token"]}
            cfg, err = _salesforce_token_from_refresh(consumer_key, consumer_secret, refresh_token, use_sandbox)
            if err:
                st.session_state["sf_last_auth_error"] = err
            if cfg:
                st.session_state[cache_key] = {
                    "base_url": cfg["base_url"],
                    "token": cfg["token"],
                    "expires_at": datetime.now(timezone.utc).timestamp() + 5400,
                }
                return cfg

        # Option 2: Username + password
        username = _sf_secret(secrets, section, "SF_USERNAME", "sf_username")
        password = _sf_secret(secrets, section, "SF_PASSWORD", "sf_password")
        security_token = _sf_secret(secrets, section, "SF_SECURITY_TOKEN", "sf_security_token")
        if security_token:
            password = password + security_token

        if not (consumer_key and consumer_secret and (refresh_token or (username and password))):
            parts = []
            if not consumer_key:
                parts.append("SF_CONSUMER_KEY")
            if not consumer_secret:
                parts.append("SF_CONSUMER_SECRET")
            if not refresh_token and not username:
                parts.append("SF_REFRESH_TOKEN (or SF_USERNAME + SF_PASSWORD)")
            elif not refresh_token and not password:
                parts.append("SF_PASSWORD")
            try:
                top = list(secrets.keys())[:25] if isinstance(secrets, dict) else []
                sec = list(section.keys())[:25] if hasattr(section, "keys") else []
                seen = f" Top-level keys: {', '.join(str(k) for k in top)}."
                if sec:
                    seen += f" Under [salesforce]: {', '.join(str(k) for k in sec)}."
            except Exception:
                seen = ""
            st.session_state["sf_last_auth_error"] = (
                f"Missing in secrets: {', '.join(parts)}."
                f"{seen} Use SF_REFRESH_TOKEN (no username/password) or SF_USERNAME + SF_PASSWORD. Save, then Reboot."
            )

        if consumer_key and consumer_secret and username and password:
            cache_key = "sf_api_config_cache"
            cache = st.session_state.get(cache_key)
            if isinstance(cache, dict) and cache.get("expires_at") and datetime.now(timezone.utc).timestamp() < cache.get("expires_at", 0):
                return {"base_url": cache["base_url"], "token": cache["token"]}
            cfg, err = _salesforce_token_from_password(consumer_key, consumer_secret, username, password, use_sandbox)
            if err:
                st.session_state["sf_last_auth_error"] = err
            if cfg:
                st.session_state[cache_key] = {
                    "base_url": cfg["base_url"],
                    "token": cfg["token"],
                    "expires_at": datetime.now(timezone.utc).timestamp() + 5400,
                }
                return cfg
    except Exception as e:
        st.session_state["sf_last_auth_error"] = str(e)
    return None


def _salesforce_query(soql: str, config: dict) -> list[dict]:
    """Run a SOQL query via REST API; return list of records (strip attributes)."""
    url = f"{config['base_url']}/services/data/v59.0/query"
    headers = {"Authorization": f"Bearer {config['token']}", "Content-Type": "application/json"}
    resp = requests.get(url, headers=headers, params={"q": soql}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    records = data.get("records", [])
    cleaned = []
    for r in records:
        r = dict(r)
        r.pop("attributes", None)
        cleaned.append(r)
    return cleaned


def _is_report_id(value: str) -> bool:
    """True if value looks like a Salesforce Report ID (00O... 15 or 18 chars)."""
    if not value or not isinstance(value, str):
        return False
    s = value.strip()
    return len(s) in (15, 18) and s.startswith("00O") and s[3:].replace("_", "").isalnum()


def _salesforce_report_data(report_id: str, config: dict) -> list[dict]:
    """Fetch report by ID via Analytics REST API; return list of row dicts (column label -> value)."""
    url = f"{config['base_url']}/services/data/v59.0/analytics/reports/{report_id.strip()}"
    headers = {"Authorization": f"Bearer {config['token']}", "Content-Type": "application/json"}
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # Column labels (detailColumns or reportMetadata.detailColumns)
    detail_cols = data.get("reportMetadata", {}).get("detailColumns") or data.get("detailColumns") or []
    if isinstance(detail_cols, list) and detail_cols:
        cols = [c.get("label") or c.get("name") or str(c) if isinstance(c, dict) else str(c) for c in detail_cols]
    else:
        cols = []
    # Rows from factMap (tabular: T!T, summary: 0!T, or first key with "rows")
    fact_map = data.get("factMap") or {}
    rows_data = []
    for key in ("T!T", "0!T", "T!F"):
        if key in fact_map and isinstance(fact_map[key], dict):
            rows_data = fact_map[key].get("rows") or fact_map[key].get("data") or []
            break
    if not rows_data and fact_map:
        for v in fact_map.values():
            if isinstance(v, dict) and (v.get("rows") or v.get("data")):
                rows_data = v.get("rows") or v.get("data")
                break
    out = []
    for r in rows_data:
        cells = r.get("dataCells") or r.get("cells") or r.get("cell") or []
        if not isinstance(cells, list):
            continue
        row = {}
        for i, cell in enumerate(cells):
            label = cols[i] if i < len(cols) else f"Column{i}"
            if isinstance(cell, dict):
                row[label] = cell.get("label") if cell.get("label") is not None else cell.get("value")
            else:
                row[label] = cell
        if row:
            out.append(row)
    return out


def _get_salesforce_tab_queries() -> dict[str, str]:
    """Tab name → SOQL. From secrets [sf_tab_queries], or SF_TAB_QUERIES (JSON string), or env."""
    out: dict[str, str] = {}
    try:
        raw_secrets = getattr(st, "secrets", None)
        if raw_secrets is not None:
            # 1) Section [sf_tab_queries] — Streamlit may expose as non-dict; normalize to dict
            sq = raw_secrets.get("sf_tab_queries") if hasattr(raw_secrets, "get") else None
            if sq is not None:
                try:
                    d = dict(sq) if not isinstance(sq, dict) else sq
                    out = {str(k).strip(): str(v).strip() for k, v in d.items() if v}
                except (TypeError, AttributeError):
                    pass
            # 2) Top-level key SF_TAB_QUERIES = "{\"Tab\": \"SOQL\"}" (JSON string)
            if not out:
                json_str = raw_secrets.get("SF_TAB_QUERIES") if hasattr(raw_secrets, "get") else None
                if isinstance(json_str, str) and json_str.strip():
                    out = {k: str(v).strip() for k, v in json.loads(json_str).items() if v}
        # 3) Environment variable (e.g. in CI or Streamlit env)
        if not out:
            raw = os.environ.get("SF_TAB_QUERIES", "")
            if raw and raw.strip():
                out = {k: str(v).strip() for k, v in json.loads(raw).items() if v}
    except (json.JSONDecodeError, TypeError, KeyError, Exception):
        pass
    return out


def _refresh_from_salesforce():
    """Pull real-time data from Salesforce API and load into Data tabs. Returns (success, message)."""
    config = _get_salesforce_config()
    if not config:
        err = st.session_state.pop("sf_last_auth_error", None)
        if err:
            return False, err
        return False, (
            "Salesforce not configured. Use (1) SF_INSTANCE_URL + SF_ACCESS_TOKEN, "
            "or (2) SF_CONSUMER_KEY + SF_CONSUMER_SECRET + SF_REFRESH_TOKEN (no username/password), "
            "or (3) SF_CONSUMER_KEY + SF_CONSUMER_SECRET + SF_USERNAME + SF_PASSWORD."
        )
    tab_queries = _get_salesforce_tab_queries()
    if not tab_queries:
        return False, (
            "No SOQL or Report IDs configured. In Streamlit secrets add [sf_tab_queries] (or SF_TAB_QUERIES) with e.g. "
            '"SF Kitchen Data" = "SELECT Id, Name FROM YourObject__c" or "SF Kitchen Data" = "00O1234567890AbC" (Report ID).'
        )
    loaded = []
    errors = []
    for tab_id, soql_or_report_id in tab_queries.items():
        if not soql_or_report_id:
            continue
        try:
            if _is_report_id(soql_or_report_id):
                rows = _salesforce_report_data(soql_or_report_id, config)
            else:
                rows = _salesforce_query(soql_or_report_id, config)
            if rows:
                save_generic_tab(tab_id, rows)
                loaded.append(f"{tab_id} ({len(rows)} rows)")
            else:
                loaded.append(f"{tab_id} (0 rows)")
        except Exception as e:
            errors.append(f"{tab_id}: {e}")
    if loaded and not errors:
        log_data_refresh("salesforce", len(loaded))
        return True, "Real-time Salesforce: " + "; ".join(loaded)
    if errors:
        return False, "Salesforce: " + "; ".join(errors)
    return False, "No Salesforce data returned. Check SOQL in sf_tab_queries."


def _fetch_online_sheet(sheet_id: str, credentials_path: str) -> dict:
    """Fetch all worksheets from the online Google Sheet. Returns {worksheet_title: list of dicts}."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Install: pip install gspread google-auth") from None

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    # Use service account from secrets when credentials_path is the sentinel
    if credentials_path == "__FROM_SECRETS__":
        info = dict(st.secrets["gsheet_service_account"])
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
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
            continue  # Section removed; skip loading
        if _is_main_tracker_tab(tab_id):
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
        log_data_refresh("google_sheet", len(loaded))
    return True, "Loaded: " + "; ".join(loaded) if loaded else "No data in sheet."


def _render_generic_tab(tab_id, key_suffix="", is_developer=False):
    """View/filter/download for a generic tab. Data is loaded from Google Sheet or Salesforce only."""
    rows = list_generic_tab(tab_id)
    if not rows:
        st.info("No data yet. Use **Refresh from online sheet** or **Refresh from Salesforce** above to load data.")
        return
    # Cleaner filtering: one search box + optional single-column filter in expander
    cols = list(rows[0].keys()) if rows else []
    search_all = st.text_input(
        "Search in all columns",
        key=f"f_{key_suffix}_search",
        placeholder="Type to search across every column…",
        help="Filters rows where any column contains this text.",
    )
    rows_shown = rows
    if (search_all or "").strip():
        term = search_all.strip().lower()
        all_keys = list(rows[0].keys()) if rows else []
        rows_shown = [r for r in rows_shown if any(term in str(r.get(k) or "").lower() for k in all_keys)]
    with st.expander("Filter by one column (optional)", expanded=False):
        chosen_col = st.selectbox("Column", ["— None —"] + cols, key=f"f_{key_suffix}_col")
        col_val = None
        if chosen_col and chosen_col != "— None —":
            uniq_vals = sorted({str(r.get(chosen_col, "")).strip() for r in rows_shown if r.get(chosen_col) is not None and str(r.get(chosen_col, "")).strip()})
            if len(uniq_vals) <= 50:
                opts = ["— All —"] + uniq_vals
                col_val = st.selectbox("Value", opts, key=f"f_{key_suffix}_col_val")
                if col_val and col_val != "— All —":
                    rows_shown = [r for r in rows_shown if str(r.get(chosen_col, "")) == str(col_val)]
            else:
                col_val = st.text_input("Contains", key=f"f_{key_suffix}_col_val", placeholder="Type to filter this column…")
                if (col_val or "").strip():
                    t = col_val.strip().lower()
                    rows_shown = [r for r in rows_shown if t in str(r.get(chosen_col, "") or "").lower()]
    st.caption(f"Showing **{len(rows_shown)}** of **{len(rows)}** row(s).")
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

    # Auto-refresh: on session start if stale + every 15 mins while open (when AUTO_REFRESH_ENABLED)
    if _auto_refresh_enabled():
        interval_mins = _auto_refresh_minutes()

        def _should_refresh() -> bool:
            refreshed_at, _ = get_last_data_refresh()
            if not refreshed_at:
                return True
            try:
                ts = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
                return (datetime.now(timezone.utc) - ts).total_seconds() >= interval_mins * 60
            except Exception:
                return True

        def _do_refresh() -> bool:
            try:
                ok, _ = _refresh_from_salesforce()
                if not ok:
                    ok, _ = _refresh_from_online_sheet()
                if ok:
                    st.session_state["goto_data_after_refresh"] = True
                    return True
            except Exception:
                pass
            return False

        # Refresh on session start if data is stale (handles app wake-up on Streamlit Cloud)
        if not st.session_state.get("auto_refresh_done") and _should_refresh():
            if _do_refresh():
                _rerun()
            st.session_state["auto_refresh_done"] = True

        # Periodic refresh while app is open (every 5 mins)
        if hasattr(st, "fragment"):

            @st.fragment(run_every=timedelta(minutes=min(5, interval_mins)))
            def _auto_refresh_fragment():
                if _should_refresh() and _do_refresh():
                    _rerun()

            _auto_refresh_fragment()

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
        /* Sidebar metric: smaller font */
        section[data-testid="stSidebar"] [data-testid="stMetricValue"],
        section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
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
    # Last refresh + Refresh button
    refreshed_at, refresh_source = get_last_data_refresh()
    if refreshed_at:
        ago = _humanize_ago(refreshed_at)
        source_label = "SF" if (refresh_source or "").startswith("salesforce") else "Sheet"
        st.sidebar.metric(
            "Last refresh",
            f"{ago} ({source_label})",
            help="Auto-refreshes every 15 mins from Salesforce (or Google Sheet fallback).",
        )
    else:
        st.sidebar.metric("Last refresh", "—", help="Data auto-refreshes every 15 mins when the app is open.")
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
    # Kitchens for everyone; 6 reports as sidebar functions for super users only
    base_sections = ["Kitchens", "Dashboard", "Discussions", "Data", "Search"]
    sections = base_sections
    if is_super_user(current_user):
        sections = ["Kitchens"] + SUPERUSER_REPORTS + ["Dashboard", "Discussions", "Data", "Search"]
    # After SF/Sheet refresh, switch to Data so user sees the refreshed tabs
    if st.session_state.pop("goto_data_after_refresh", False):
        st.session_state["sidebar_section"] = "Data"
    default_idx = sections.index(st.session_state.get("sidebar_section", "Kitchens")) if st.session_state.get("sidebar_section") in sections else 0
    section = st.sidebar.radio(
        "Section",
        sections,
        index=default_idx,
        key="sidebar_section",
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

    # Kitchens: raw kitchen data only (SF Kitchen Data, Churn, Sellable/No Status)
    if section == "Kitchens":
        st.title("Kitchens")
        st.caption("Raw kitchen data. Filter by Country, Facility, Kitchen, or search.")
        rows, columns, col_map = _get_combined_kitchens_dataset()
        if not rows:
            st.info("No kitchen data yet. Data auto-refreshes every 15 mins. Developers can trigger a refresh in **Data** → Refresh from Salesforce or Google Sheet.")
            st.stop()

        # Build hierarchy values from _Country, _Facility, _Kitchen
        countries: set[str] = set()
        facilities_by_country: dict[str, set[str]] = {}
        kitchens_by_facility: dict[tuple[str, str], set[str]] = {}
        for r in rows:
            c, f, k = r.get("_Country", ""), r.get("_Facility", ""), r.get("_Kitchen", "")
            if c:
                countries.add(c)
                facilities_by_country.setdefault(c, set()).add(f or "—")
                if f:
                    facilities_by_country[c].discard("—")
                key = (c, f or "—")
                if k:
                    kitchens_by_facility.setdefault(key, set()).add(k)
        countries.update(SF_COUNTRIES)
        countries_sorted = sorted(countries)

        # Filters: Country, Facility, Kitchen + search + column filter
        f1, f2, f3 = st.columns(3)
        with f1:
            country_sel = st.selectbox("Country", ["— All —"] + countries_sorted, key="h_country")
        with f2:
            fac_set = set()
            if country_sel and country_sel != "— All —":
                for c, fset in facilities_by_country.items():
                    if _country_matches(c, country_sel):
                        fac_set.update(fset)
            else:
                fac_set = set()
                for fset in facilities_by_country.values():
                    fac_set.update(fset)
            facility_sel = st.selectbox("Facility", ["— All —"] + sorted(fac_set), key="h_facility")
        with f3:
            k_set = set()
            if country_sel and country_sel != "— All —" and facility_sel and facility_sel != "— All —":
                for (c, f), kset in kitchens_by_facility.items():
                    if _country_matches(c, country_sel) and f == facility_sel:
                        k_set.update(kset)
            elif country_sel and country_sel != "— All —":
                for (c, f), kset in kitchens_by_facility.items():
                    if _country_matches(c, country_sel):
                        k_set.update(kset)
            else:
                for kset in kitchens_by_facility.values():
                    k_set.update(kset)
            kitchen_sel = st.selectbox("Kitchen", ["— All —"] + sorted(k_set), key="h_kitchen")

        # Filter by hierarchy
        c_filter = country_sel if country_sel and country_sel != "— All —" else None
        f_filter = facility_sel if facility_sel and facility_sel != "— All —" else None
        k_filter = kitchen_sel if kitchen_sel and kitchen_sel != "— All —" else None
        filtered = rows
        if c_filter or f_filter or k_filter:
            filtered = [r for r in filtered if
                (not c_filter or _country_matches(r.get("_Country", ""), c_filter)) and
                (not f_filter or r.get("_Facility", "") == f_filter) and
                (not k_filter or r.get("_Kitchen", "") == k_filter)]

        # Search across all columns
        search_all = st.text_input("Search in all columns", key="h_search", placeholder="Filter by any value…")
        if (search_all or "").strip():
            term = search_all.strip().lower()
            filtered = [r for r in filtered if any(term in str(v).lower() for v in r.values() if v is not None)]

        # Filter by one column (optional)
        with st.expander("Filter by column", expanded=False):
            chosen_col = st.selectbox("Column", ["— None —"] + columns, key="h_col_filter")
            if chosen_col and chosen_col != "— None —":
                uniq = sorted({str(r.get(chosen_col, "")).strip() for r in filtered if r.get(chosen_col) is not None})
                if len(uniq) <= 80:
                    col_val = st.selectbox("Value", ["— All —"] + uniq, key="h_col_val")
                    if col_val and col_val != "— All —":
                        filtered = [r for r in filtered if str(r.get(chosen_col, "")) == col_val]
                else:
                    col_val = st.text_input("Contains", key="h_col_val", placeholder="Type to filter…")
                    if (col_val or "").strip():
                        t = col_val.strip().lower()
                        filtered = [r for r in filtered if t in str(r.get(chosen_col, "") or "").lower()]

        st.caption(f"Showing **{len(filtered)}** of **{len(rows)}** kitchen row(s).")
        if filtered:
            # Order columns for display
            display_cols = [c for c in columns if c in (filtered[0].keys() if filtered else [])]
            out_rows = [{k: r.get(k, "") for k in display_cols} for r in filtered]
            st.dataframe(out_rows, use_container_width=True, hide_index=True)
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=display_cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(out_rows)
            st.download_button("Download filtered CSV", data=buf.getvalue(), file_name="kitchens_filtered.csv", mime="text/csv", key="dl_hierarchy")
        else:
            st.info("No rows match your filters. Try changing Country, Facility, or search.")
        return

    # Super-user reports: Facility Sell Price Multipliers, Area Data, etc. — all countries
    if section in SUPERUSER_REPORTS:
        st.title(section)
        st.caption(f"Report data for all countries (SA, UAE, Kuwait, Bahrain, Qatar). Filter by any column.")
        _render_generic_tab(section, key_suffix=section.replace(" ", "_"), is_developer=is_developer)
        return

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
        sources = _dashboard_sources(current_user)
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
            with st.expander("Refresh data (Google Sheet & Salesforce)", expanded=True):
                st.caption(
                    "**Salesforce** = real-time data from the SF API. "
                    "**Google Sheet** = fallback when SF isn't configured or unavailable — same data, synced every 4 hours from Salesforce."
                )
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Google Sheet API (fallback)** — service account JSON (share the sheet with its email).")
                    if st.button("Refresh from online sheet", key="btn_gsheet"):
                        with st.spinner("Loading from Google Sheet…"):
                            ok, msg = _refresh_from_online_sheet()
                        if ok:
                            st.session_state["goto_data_after_refresh"] = True
                            st.success(msg)
                            _rerun()
                        else:
                            st.error(msg)
                with col2:
                    st.markdown("**Salesforce API (real-time)** — Refresh token or username/password + sf_tab_queries.")
                    st.caption("If SF auth isn’t set up yet, use **Refresh from online sheet** — it’s synced from Salesforce every 4 hours.")
                    if st.button("Refresh from Salesforce", key="btn_salesforce"):
                        with st.spinner("Loading from Salesforce…"):
                            ok, msg = _refresh_from_salesforce()
                        if ok:
                            st.session_state["goto_data_after_refresh"] = True
                            st.success(msg)
                            _rerun()
                        else:
                            st.error(msg)
                with st.expander("How to configure real-time Salesforce", expanded=False):
                    st.markdown("""
                    In **Streamlit Cloud** → app → **Settings** → **Secrets**, add either:

                    **Option A — Access token (manual)**  
                    - `SF_INSTANCE_URL` — e.g. `https://yourdomain.my.salesforce.com`  
                    - `SF_ACCESS_TOKEN` — token from your OAuth/Connected App flow  

                    **Option B — Refresh token (no username/password)**  
                    - `SF_CONSUMER_KEY` — Connected App Consumer Key  
                    - `SF_CONSUMER_SECRET` — Connected App Consumer Secret  
                    - `SF_REFRESH_TOKEN` — refresh token (get once via OAuth in browser or from admin)  
                    - `SF_USE_SANDBOX` — set to `true` for sandbox  

                    **Option C — Username + password**  
                    - `SF_CONSUMER_KEY`, `SF_CONSUMER_SECRET`, `SF_USERNAME`, `SF_PASSWORD`, optional `SF_SECURITY_TOKEN`, `SF_USE_SANDBOX`  

                    **Tab → SOQL or Report ID (required for real-time data)**  
                    - `sf_tab_queries` — map each tab name to a **SOQL** query or a **Report ID** (15/18 chars starting with `00O`). Use Report ID to run a report directly without writing SOQL.

                    ```toml
                    [sf_tab_queries]
                    "SF Kitchen Data" = "SELECT Id, Name, Region__c FROM YourObject__c"
                    "SF Churn Data"   = "00Oca000001AbCd"
                    ```

                    Tab names must match the Data tabs. Results replace that tab with **real-time** Salesforce data.
                    """)
        else:
            st.info("Refresh is available only to developers. Unlock **Developer access** in the sidebar.")
        # Tabbed view enabled only when data loaded from online sheet (not Salesforce)
        _, refresh_source = get_last_data_refresh()
        from_online_sheet = (refresh_source or "").strip().lower().startswith("google_sheet")
        if not from_online_sheet:
            st.info(
                "The tabbed data view (SF Kitchen Data, Sellable No Status, etc.) is available only when data is loaded from the **online Google Sheet**. "
                "Use **Refresh from online sheet** above to enable it."
            )
            st.caption("Data refreshed from Salesforce does not use this view.")
        # Regular users: kitchen tabs only. Super users: all tabs (Price Multipliers, Area Data, etc.)
        all_tab_ids = _visible_data_tab_ids(current_user) if from_online_sheet else []
        if not is_super_user(current_user) and all_tab_ids:
            st.caption("You’re viewing kitchen data. Super users see additional tabs (Price Multipliers, Area Data, Execution Log, etc.).")
        if not all_tab_ids and from_online_sheet:
            st.info("No data tabs available for your role. Kitchen users see SF Kitchen Data, Churn, Facility details, Sellable/No Status. Super users see all tabs.")
            st.caption("Add SUPER_USER_IDS in secrets to grant full access (e.g. SUPER_USER_IDS = \"email@company.com, other@company.com\").")
        elif all_tab_ids:
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
                    _render_generic_tab(tab_id, key_suffix=(tab_id or str(tab_index)).replace(" ", "_"), is_developer=is_developer)

if __name__ == "__main__":
    main()
