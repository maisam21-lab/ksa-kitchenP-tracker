"""
KSA Kitchens Tracker — web app. Run: streamlit run app/tracker_app.py
All sheet tabs in tool form: view, filter, add/edit, export. Single source of truth.
Accepts CSV or Excel (.xlsx) uploads. Can refresh directly from the online Google Sheet.
"""
import base64
import csv
import hashlib
import html
import io
import json
import os
import re
import urllib.parse
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import streamlit as st

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode, DataReturnMode
    _HAS_AGGRI = True
except ImportError:
    try:
        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
        JsCode = None
        _HAS_AGGRI = True
    except ImportError:
        try:
            from st_aggrid import AgGrid, GridOptionsBuilder
            JsCode = None
            GridUpdateMode = None
            DataReturnMode = None
            _HAS_AGGRI = True
        except ImportError:
            JsCode = None
            GridUpdateMode = None
            DataReturnMode = None
            _HAS_AGGRI = False

try:
    from app import auth
except ImportError:
    try:
        import auth
    except ImportError:
        auth = None
try:
    from app import snapshot as snapshot_mod
except ImportError:
    try:
        import snapshot as snapshot_mod
    except ImportError:
        snapshot_mod = None
try:
    from app import fx as fx_mod
except ImportError:
    try:
        import fx as fx_mod
    except ImportError:
        fx_mod = None
try:
    from app import multipliers as multipliers_mod
except ImportError:
    try:
        import multipliers as multipliers_mod
    except ImportError:
        multipliers_mod = None
try:
    from app import data_store as data_store_mod
except ImportError:
    try:
        import data_store as data_store_mod
    except ImportError:
        data_store_mod = None

try:
    import pandas as pd
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

try:
    import pydeck as pdk
except ImportError:
    pdk = None

# Online sheet: same ID as the workbook (docs.google.com/.../d/SHEET_ID/edit?gid=...)
# Same logic as the sheet: country merge (SA/regions → Saudi Arabia, BH → Bahrain), status color coding.
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


def _row_has_opportunity_name(row) -> bool:
    """True if row has any Opportunity Name–style field filled (for coloring: Vacant + opportunity → red)."""
    if row is None:
        return False
    # Same keys as Dashboard _opportunity_name (SF / GSheet / BigQuery)
    for k in ("Opportunity Name", "Opportunity__r.Name", "Opportunity_Name__c", "Opportunity Name__c", "Opportunity name", "opportunity_name", "opportunity name", "Opportunity_Name"):
        v = row.get(k) if hasattr(row, "get") else (row[k] if k in (row.index if hasattr(row, "index") else []) else None)
        if v is not None and str(v).strip() and str(v).strip().lower() not in ("nan", "none"):
            return True
    # Fallback: any key containing "opportunity" with non-empty value
    try:
        for k in (row.keys() if hasattr(row, "keys") else (row.index if hasattr(row, "index") else [])):
            if "opportunity" not in str(k).lower():
                continue
            v = row.get(k) if hasattr(row, "get") else row[k]
            if v is not None and str(v).strip() and str(v).strip().lower() not in ("nan", "none"):
                return True
    except Exception:
        pass
    return False


def _apply_conditional_filters(rows: list[dict], rules: list[dict], columns: list[str] | None = None) -> list[dict]:
    """Filter rows by a list of rules (AND). Each rule: {"col": str, "op": str, "val": str}. Op: contains, equals, not equals, starts with, ends with, is empty, is not empty."""
    if not rules or not rows:
        return rows
    cols = columns or (list(rows[0].keys()) if rows else [])
    out = []
    for r in rows:
        match = True
        for rule in rules:
            col = rule.get("col") or (rule.get("column") if isinstance(rule.get("column"), str) else None)
            if not col or col not in cols:
                continue
            op = (rule.get("op") or "").strip().lower()
            val = (rule.get("val") or rule.get("value") or "").strip()
            cell = r.get(col)
            cell_str = str(cell).strip() if cell is not None else ""
            if op == "contains":
                if val.lower() not in cell_str.lower():
                    match = False
                    break
            elif op == "equals":
                if cell_str.lower() != val.lower():
                    match = False
                    break
            elif op == "not equals":
                if cell_str.lower() == val.lower():
                    match = False
                    break
            elif op == "starts with":
                if not cell_str.lower().startswith(val.lower()):
                    match = False
                    break
            elif op == "ends with":
                if not cell_str.lower().endswith(val.lower()):
                    match = False
                    break
            elif op == "is empty":
                if cell is not None and cell_str != "":
                    match = False
                    break
            elif op == "is not empty":
                if cell is None or cell_str == "":
                    match = False
                    break
        if match:
            out.append(r)
    return out


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


def _excel_sf_report_header_row(xl, sheet_name: str) -> int | None:
    """If the sheet looks like a Salesforce report export (title rows then header with 'Account Name'), return the 0-based header row index; else None."""
    try:
        df = pd.read_excel(xl, sheet_name=sheet_name, header=None)
        if len(df) < 17:
            return None
        row16 = df.iloc[16].astype(str).str.strip()
        if row16.str.contains("Account Name", case=False, na=False).any():
            return 16
        for r in range(14, min(20, len(df))):
            row = df.iloc[r].astype(str).str.strip()
            if row.str.contains("Account Name", case=False, na=False).any():
                return r
    except Exception:
        pass
    return None


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
        # Also include Salesforce report exports (e.g. "SF Kitchen Data - KSA")
        to_read = list(to_read) + [s for s in xl.sheet_names if s.strip().lower().startswith("sf kitchen data")]
        to_read = list(dict.fromkeys(to_read))  # dedupe, keep order
        if not to_read:
            to_read = xl.sheet_names[:20]  # fallback: first 20 sheets
    out = {}
    for sheet_name in to_read:
        header_row = _excel_sf_report_header_row(xl, sheet_name)
        if header_row is not None:
            df = pd.read_excel(xl, sheet_name=sheet_name, header=header_row)
        else:
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
        # SF Kitchen Data sheet -> Kitchens tab (single main view)
        if tab_id == "SF Kitchen Data" or (tab_id or "").startswith("SF Kitchen Data"):
            tab_id = "Kitchens"
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
            save_generic_tab(tab_id, rows, source="gsheet")
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
    "Kitchens": "All kitchen details. View and filter.",
    "Master Kitchens list": "Master list of all kitchens. View and filter.",
    "Sellable No Status": "Sellable no-status data. View and filter.",
    "All no status kitchens": "All no-status kitchens. View and filter.",
    "LF Comp": "LF Comp data. View and filter.",
    "Pivot Table 10": "Pivot Table 10 dataset. View and filter.",
    "Area Data": "Area data. View and filter.",
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
    "Kitchens",
    "Master Kitchens list",
    "Sellable No Status",
    "All no status kitchens",
    "LF Comp",
    "Pivot Table 10",
    "Area Data",
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

# Generic tab data: any sheet tab (SF Kitchen Data, Area Data, etc.) — store rows as JSON per row.
# source = 'salesforce' | 'gsheet' so SF data is never overwritten by GSheet and vice versa.
TABLE_GENERIC_TAB = """
CREATE TABLE IF NOT EXISTS generic_tab_data (
    source TEXT NOT NULL,
    tab_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (source, tab_id, row_index)
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
# role: associate_viewer | manager_viewer | super_user (added by migration)
TABLE_ALLOWED_USERS = """
CREATE TABLE IF NOT EXISTS allowed_users (
    identifier TEXT NOT NULL PRIMARY KEY,
    added_at TEXT NOT NULL
)
"""

# Daily kitchen snapshots for "what changed today" (Prompt 5)
TABLE_KITCHEN_DAILY_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS kitchen_daily_snapshot (
    snapshot_date TEXT NOT NULL,
    kitchen_key TEXT NOT NULL,
    facility TEXT,
    kitchen_name TEXT,
    status TEXT,
    churn_date TEXT,
    floor_price TEXT,
    data_json TEXT,
    PRIMARY KEY (snapshot_date, kitchen_key)
)
"""

# GSheet tab order: matches worksheet order from last refresh (so Data tabs match your sheet)
TABLE_GSHEET_TAB_ORDER = """
CREATE TABLE IF NOT EXISTS gsheet_tab_order (
    tab_index INTEGER NOT NULL,
    tab_id TEXT NOT NULL PRIMARY KEY
)
"""

# Last refresh timestamps per source (Prompt 3)
TABLE_REFRESH_METADATA = """
CREATE TABLE IF NOT EXISTS refresh_metadata (
    source TEXT NOT NULL PRIMARY KEY,
    refreshed_at TEXT NOT NULL
)
"""

# FX rates for Currency Converter (Prompt 7)
TABLE_FX_RATES = """
CREATE TABLE IF NOT EXISTS fx_rates (
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL,
    rate REAL NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (from_currency, to_currency)
)
"""

# Facility multipliers for Price Multipliers tool (Prompt 9)
TABLE_FACILITY_MULTIPLIERS = """
CREATE TABLE IF NOT EXISTS facility_multipliers (
    facility_id TEXT NOT NULL PRIMARY KEY,
    facility_name TEXT,
    current_multiplier REAL,
    suggested_multiplier REAL,
    updated_by TEXT,
    updated_at TEXT
)
"""

# Facility inflation model (optional future use, Prompt 8)
TABLE_FACILITY_INFLATION = """
CREATE TABLE IF NOT EXISTS facility_inflation_model (
    facility_id TEXT NOT NULL PRIMARY KEY,
    go_live_date TEXT,
    inflation_index REAL,
    recommended_multiplier REAL,
    updated_at TEXT
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


def _ensure_allowed_users_role():
    """Add role column to allowed_users if missing (RBAC migration)."""
    with get_conn() as c:
        try:
            c.execute("SELECT role FROM allowed_users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE allowed_users ADD COLUMN role TEXT DEFAULT 'associate_viewer'")
        try:
            c.execute("UPDATE allowed_users SET role = 'associate_viewer' WHERE role IS NULL OR role = ''")
        except sqlite3.OperationalError:
            pass


def _migrate_generic_tab_data_if_needed(c):
    """If generic_tab_data has old schema (no source column), migrate to source-separated schema."""
    r = c.execute("PRAGMA table_info(generic_tab_data)").fetchall()
    columns = [row[1] for row in r]
    if not columns:
        return  # table didn't exist; TABLE_GENERIC_TAB created it with new schema
    if "source" in columns:
        return
    # Old schema: (tab_id, row_index, data). Copy into new table with source='salesforce'.
    c.execute(
        "CREATE TABLE generic_tab_data_new (source TEXT NOT NULL, tab_id TEXT NOT NULL, row_index INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (source, tab_id, row_index))"
    )
    c.execute("INSERT INTO generic_tab_data_new (source, tab_id, row_index, data) SELECT 'salesforce', tab_id, row_index, data FROM generic_tab_data")
    c.execute("DROP TABLE generic_tab_data")
    c.execute("ALTER TABLE generic_tab_data_new RENAME TO generic_tab_data")


def init_db():
    with get_conn() as c:
        c.execute(TABLE)
        c.execute(TABLE_EXEC_LOG)
        # Create generic_tab_data (may create with old schema on first run if table name reused; migration fixes it)
        try:
            c.execute(TABLE_GENERIC_TAB)
        except Exception:
            pass
        # If table existed with old 3-column schema, migrate to source-separated schema
        try:
            _migrate_generic_tab_data_if_needed(c)
        except Exception:
            pass
        c.execute(TABLE_GSHEET_TAB_ORDER)
        c.execute(TABLE_FEEDBACK)
        c.execute(TABLE_TRAFFIC)
        c.execute(TABLE_RECORD_COMMENTS)
        c.execute(TABLE_RECORD_ACTIVITY)
        c.execute(TABLE_TRACKER_TEMPLATES)
        c.execute(TABLE_SAVED_VIEWS)
        c.execute(TABLE_ALLOWED_USERS)
        c.execute(TABLE_APP_DISCUSSIONS)
        c.execute(TABLE_KITCHEN_DAILY_SNAPSHOT)
        c.execute(TABLE_REFRESH_METADATA)
        c.execute(TABLE_FX_RATES)
        c.execute(TABLE_FACILITY_MULTIPLIERS)
        c.execute(TABLE_FACILITY_INFLATION)
    _ensure_updated_at()
    _ensure_discussions_parent_id()
    _ensure_allowed_users_role()
    _sync_allowlist_from_config()


def _get_allowlist_ids_from_config() -> list[str]:
    """Return allowlisted identifiers from ALLOWLIST_IDS (secrets or env)."""
    try:
        ids = st.secrets.get("ALLOWLIST_IDS") or os.environ.get("ALLOWLIST_IDS", "")
    except Exception:
        ids = os.environ.get("ALLOWLIST_IDS", "")
    if isinstance(ids, list):
        return [str(s).strip() for s in ids if s and str(s).strip()]
    return [s.strip() for s in str(ids).split(",") if s.strip()]


def _sync_allowlist_from_config():
    """If ALLOWLIST_IDS is set, keep DB allowlist in sync with that config.

    This lets admins manage the allowlist from the backend (secrets/env)
    instead of through the UI inside the tracker.
    Deduplicates identifiers so duplicate entries in ALLOWLIST_IDS do not cause IntegrityError.
    """
    ids = _get_allowlist_ids_from_config()
    if not ids:
        return
    # Deduplicate (preserve order) to avoid PRIMARY KEY IntegrityError
    seen = set()
    unique_ids = []
    for i in ids:
        key = (i or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_ids.append((i or "").strip())
    if not unique_ids:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute("DELETE FROM allowed_users")
        for identifier in unique_ids:
            c.execute(
                "INSERT INTO allowed_users (identifier, added_at, role) VALUES (?, ?, ?)",
                (identifier, now, "associate_viewer"),
            )


def _allowlist_enabled() -> bool:
    """True if access is restricted to allowed users only (set ALLOWLIST_ENABLED=1 or in secrets)."""
    try:
        v = st.secrets.get("ALLOWLIST_ENABLED") or os.environ.get("ALLOWLIST_ENABLED", "")
    except Exception:
        v = os.environ.get("ALLOWLIST_ENABLED", "")
    return str(v).strip().lower() in ("1", "true", "yes")


# Session persistence: remember user across browser refresh for several hours (via URL params)
SESSION_PERSISTENCE_HOURS = 6
_TRACKER_PARAM_USER = "u"
_TRACKER_PARAM_EXPIRY = "e"


def _restore_session_from_params() -> bool:
    """If URL has valid tracker session params, restore user_display_name and return True."""
    try:
        q = getattr(st, "query_params", None) or getattr(st, "experimental_get_query_params", lambda: {})()
        if callable(q):
            q = q()
        if not q:
            return False
        u = q.get(_TRACKER_PARAM_USER)
        e = q.get(_TRACKER_PARAM_EXPIRY)
        if not u or not e:
            return False
        u = u[0] if isinstance(u, list) else u
        e = e[0] if isinstance(e, list) else e
        try:
            expiry_ts = int(e)
        except (TypeError, ValueError):
            return False
        import time
        if time.time() > expiry_ts:
            return False
        try:
            email = base64.b64decode(u.encode()).decode()
        except Exception:
            return False
        if email and "@" in email:
            st.session_state["user_display_name"] = email
            return True
    except Exception:
        pass
    return False


def _persist_session_to_params(user: str) -> None:
    """Store user in URL params so next refresh restores session (expiry in SESSION_PERSISTENCE_HOURS)."""
    if not (user or "").strip():
        return
    try:
        import time
        expiry_ts = int(time.time()) + (SESSION_PERSISTENCE_HOURS * 3600)
        u = base64.b64encode((user or "").strip().encode()).decode()
        qp = getattr(st, "query_params", None)
        if qp is not None:
            qp[_TRACKER_PARAM_USER] = u
            qp[_TRACKER_PARAM_EXPIRY] = str(expiry_ts)
    except Exception:
        pass


def _clear_session_params() -> None:
    """Remove session params from URL."""
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None:
            qp.clear()
    except Exception:
        pass

def list_allowed_users():
    """Return list of allowed identifiers with role: [{identifier, added_at, role}, ...]."""
    with get_conn() as c:
        try:
            r = c.execute("SELECT identifier, added_at, role FROM allowed_users ORDER BY identifier")
        except sqlite3.OperationalError:
            r = c.execute("SELECT identifier, added_at FROM allowed_users ORDER BY identifier")
        rows = [dict(row) for row in r]
    for row in rows:
        if row.get("role") is None or (isinstance(row.get("role"), str) and not row.get("role").strip()):
            row["role"] = "associate_viewer"
    return rows


def add_allowed_user(identifier: str, role: str = "associate_viewer") -> bool:
    """Add an email or name to the allowlist with optional role. Returns True if added."""
    id_ = (identifier or "").strip()
    if not id_:
        return False
    role = (role or "associate_viewer").strip() or "associate_viewer"
    if role not in ("associate_viewer", "manager_viewer", "super_user"):
        role = "associate_viewer"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        try:
            c.execute(
                "INSERT INTO allowed_users (identifier, added_at, role) VALUES (?, ?, ?)",
                (id_, now, role),
            )
            return True
        except sqlite3.OperationalError:
            try:
                c.execute("INSERT INTO allowed_users (identifier, added_at) VALUES (?, ?)", (id_, now))
                return True
            except sqlite3.IntegrityError:
                return False
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


def _get_secrets_roles() -> dict:
    """Return {identifier_lower: role} from secrets (e.g. [allowed_user_roles] or ALLOWED_USER_ROLES JSON)."""
    out = {}
    try:
        raw = st.secrets.get("allowed_user_roles") or st.secrets.get("ALLOWED_USER_ROLES")
    except Exception:
        raw = os.environ.get("ALLOWED_USER_ROLES", "")
    if isinstance(raw, dict):
        for k, v in raw.items():
            key = (str(k).strip() or "").lower()
            if key and v:
                out[key] = str(v).strip().lower()
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k, v in data.items():
                    key = (str(k).strip() or "").lower()
                    if key and v:
                        out[key] = str(v).strip().lower()
        except json.JSONDecodeError:
            pass
    return out


def _get_super_user_emails() -> set[str]:
    """Return set of emails (lower) that should get super_user. From SUPER_USER_EMAILS or SUPER_USER_IDS in secrets/env."""
    out = set()
    raw = None
    try:
        raw = (
            st.secrets.get("SUPER_USER_EMAILS") or st.secrets.get("super_user_emails")
            or st.secrets.get("SUPER_USER_IDS") or st.secrets.get("super_user_ids")
            or os.environ.get("SUPER_USER_EMAILS") or os.environ.get("SUPER_USER_IDS", "")
        )
    except Exception:
        raw = os.environ.get("SUPER_USER_EMAILS") or os.environ.get("SUPER_USER_IDS", "")
    if isinstance(raw, list):
        for item in raw:
            s = (str(item).strip() or "").lower()
            if s and "@" in s:
                out.add(s)
    else:
        for part in str(raw or "").split(","):
            s = (part or "").strip().lower()
            if s and "@" in s:
                out.add(s)
    return out


def set_last_refresh(source: str) -> None:
    """Record last refresh timestamp for the given source (salesforce | gsheet)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO refresh_metadata (source, refreshed_at) VALUES (?, ?)",
            (source, now),
        )


def get_last_refresh(source: str) -> str | None:
    """Return last refresh timestamp for the given source, or None."""
    with get_conn() as c:
        r = c.execute("SELECT refreshed_at FROM refresh_metadata WHERE source = ?", (source,))
        row = r.fetchone()
        return row[0] if row else None


def _data_status_from_pulse(last_ts: str | None) -> tuple[str, str, str]:
    """From last refresh timestamp return (status_label, dot_color, formatted_ts).
    status_label: 'Live Data' | 'Delayed' | 'Stale'
    dot_color: green / yellow / red
    formatted_ts: e.g. '04 Mar 10:56' or '—'
    """
    if not last_ts:
        return "Stale", "#dc2626", "—"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_min = (now - dt).total_seconds() / 60
        fmt = dt.strftime("%d %b %H:%M")
        if age_min <= 30:
            return "Live Data", "#22c55e", fmt
        if age_min <= 120:
            return "Delayed", "#eab308", fmt
        return "Stale", "#dc2626", fmt
    except Exception:
        return "Stale", "#dc2626", last_ts[:16] if last_ts else "—"


def _format_updated_ago(last_ts: str | None) -> str:
    """Return human-readable relative time for status pill, e.g. 'Updated 2 min ago'."""
    if not last_ts:
        return "Updated never"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_sec = (now - dt).total_seconds()
        if age_sec < 60:
            return "Updated just now"
        if age_sec < 3600:
            m = int(age_sec / 60)
            return f"Updated {m} min ago"
        if age_sec < 86400:
            h = int(age_sec / 3600)
            return f"Updated {h} hour ago" if h == 1 else f"Updated {h} hours ago"
        d = int(age_sec / 86400)
        return f"Updated {d} day ago" if d == 1 else f"Updated {d} days ago"
    except Exception:
        return "Updated —"


def _gsheet_refresh_is_stale(minutes: int = 15) -> bool:
    """True if no GSheet refresh yet or last refresh was more than `minutes` ago."""
    ts = get_last_refresh("gsheet")
    if not ts:
        return True
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
        return age_sec > minutes * 60
    except Exception:
        return True


def insert_app_discussion(author: str, message: str, parent_id: int | None = None) -> None:
    """Add a discussion post or reply (parent_id=None for top-level)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_conn() as c:
        c.execute(
            "INSERT INTO app_discussions (created_at, author, message, parent_id) VALUES (?, ?, ?, ?)",
            (now, (author or "Anonymous").strip(), (message or "").strip(), parent_id),
        )
    _slack_notify_discussion(author, message, parent_id)


def _get_slack_discussion_url() -> str | None:
    """Return configured Slack channel URL for discussions (secrets or env)."""
    try:
        url = st.secrets.get("SLACK_DISCUSSION_CHANNEL_URL") or os.environ.get("SLACK_DISCUSSION_CHANNEL_URL", "")
    except Exception:
        url = os.environ.get("SLACK_DISCUSSION_CHANNEL_URL", "")
    return (url or "").strip() or None


def _get_slack_mention_ids() -> dict[str, str]:
    """Return map of mention key (lowercase name/email) -> Slack user ID (U0xxx) for @mention notifications."""
    out: dict[str, str] = {}
    try:
        table = st.secrets.get("slack_mention_ids")
        if isinstance(table, dict):
            for k, v in table.items():
                if k and v and isinstance(v, str) and v.strip().startswith("U"):
                    out[str(k).strip().lower()] = v.strip()
    except Exception:
        pass
    env_val = os.environ.get("SLACK_MENTION_IDS", "")
    if env_val:
        for part in str(env_val).split(","):
            part = part.strip()
            if ":" in part:
                key, val = part.split(":", 1)
                key, val = key.strip().lower(), val.strip()
                if key and val and val.startswith("U"):
                    out[key] = val
    return out


def _slack_notify_discussion(author: str, message: str, parent_id: int | None) -> None:
    """Post to Slack: prefer Slack app (SLACK_BOT_TOKEN + SLACK_CHANNEL_ID), else Incoming Webhook. @mentions become <@ID>."""
    try:
        bot_token = (st.secrets.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_BOT_TOKEN", "")).strip()
        channel_id = (st.secrets.get("SLACK_CHANNEL_ID") or os.environ.get("SLACK_CHANNEL_ID", "")).strip()
        webhook = (st.secrets.get("SLACK_WEBHOOK_URL") or os.environ.get("SLACK_WEBHOOK_URL", "")).strip()
    except Exception:
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
        channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not bot_token and not webhook:
        return
    try:
        snippet = (message or "").strip()[:500]
        if len((message or "").strip()) > 500:
            snippet += "…"
        mention_ids = _get_slack_mention_ids()
        if mention_ids:
            def _repl(match):
                key = (match.group(1) or "").strip().lower()
                if key and key in mention_ids:
                    return f"<@{mention_ids[key]}>"
                return match.group(0)
            snippet = re.sub(r"@([a-zA-Z0-9_.-]+)", _repl, snippet)
        label = "Reply" if parent_id else "New discussion"
        text = f"*{label}* from *{author or 'Anonymous'}*:\n{snippet}"
        if bot_token and channel_id:
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
                json={"channel": channel_id, "text": text},
                timeout=10,
            )
            if resp.status_code != 200 or not (resp.json() or {}).get("ok"):
                pass
        elif webhook:
            resp = requests.post(webhook, json={"text": text}, timeout=5)
            if resp.status_code != 200:
                pass
    except Exception:
        pass


def _render_discussion_message(msg: str) -> str:
    """Render message with @mentions highlighted (bold). Use in st.markdown."""
    if not msg:
        return ""
    # @username or @first.last — make them bold for visibility
    return re.sub(r"@([a-zA-Z0-9_.-]+)", r"**@\1**", msg)


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


def list_recent_comments_global(limit: int = 30):
    """Recent comments across all records for notifications feed."""
    with get_conn() as c:
        r = c.execute(
            "SELECT id, record_id, created_at, author, comment_text FROM record_comments ORDER BY created_at DESC LIMIT ?",
            (limit,),
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


def get_unread_notification_count(since_iso: str) -> int:
    """Count activity and comments newer than since_iso (e.g. last read timestamp)."""
    if not (since_iso or since_iso.strip()):
        since_iso = "1970-01-01T00:00:00Z"
    with get_conn() as c:
        a = c.execute(
            "SELECT COUNT(1) FROM record_activity WHERE at > ?",
            (since_iso.strip(),),
        ).fetchone()[0]
        b = c.execute(
            "SELECT COUNT(1) FROM record_comments WHERE created_at > ?",
            (since_iso.strip(),),
        ).fetchone()[0]
        return a + b


def list_notifications_feed(limit: int = 50):
    """Merged feed of recent activity and comments, sorted by time desc."""
    activities = list_recent_activity_global(limit)
    comments = list_recent_comments_global(limit)
    feed = []
    for r in activities:
        feed.append({
            "type": "activity",
            "at": r["at"],
            "record_id": r["record_id"],
            "author": r.get("by_user") or "Someone",
            "action": r.get("action") or "updated",
            "details": (r.get("details") or "")[:80],
        })
    for r in comments:
        feed.append({
            "type": "comment",
            "at": r["created_at"],
            "record_id": r["record_id"],
            "author": r.get("author") or "Anonymous",
            "snippet": (r.get("comment_text") or "")[:100].replace("\n", " "),
        })
    feed.sort(key=lambda x: x["at"], reverse=True)
    return feed[:limit]


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


def _export_allowed_ids_from_secrets() -> set[str]:
    """IDs (emails) allowed to export data. Supports comma string or list in secrets/env."""
    try:
        raw = (
            st.secrets.get("EXPORT_ALLOWED_IDS")
            or st.secrets.get("export_allowed_ids")
            or os.environ.get("EXPORT_ALLOWED_IDS", "")
        )
    except Exception:
        raw = os.environ.get("EXPORT_ALLOWED_IDS", "")
    out: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            s = (str(item).strip() or "").lower()
            if s:
                out.add(s)
    else:
        for part in str(raw or "").split(","):
            s = (part or "").strip().lower()
            if s:
                out.add(s)
    return out


def _can_user_export(current_user: str, is_developer: bool = False) -> bool:
    """True if current user can export CSV."""
    if is_developer:
        return True
    u = (current_user or "").strip().lower()
    if not u:
        return False
    return u in _export_allowed_ids_from_secrets()


def _render_export_button(rows: list[dict], file_stem: str, key: str):
    """Render CSV download button when rows exist."""
    if not rows:
        return
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(file_stem or "export")).strip("_") or "export"
    st.download_button(
        "Export CSV",
        data=export_csv_generic(rows),
        file_name=f"{safe_stem}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key=key,
    )


def _dashboard_sources() -> list[tuple[str, str]]:
    """(display_name, source_id). source_id is 'main_tracker' or tab_id. All tabs."""
    out = [("Main tracker (kitchen data)", "main_tracker")]
    for tab_id in SHEET_TAB_IDS + list_extra_tab_ids():
        out.append((tab_id, tab_id))
    return out


# Tab options in Kitchen Master Data: all facility/sheet names that fetch from GSheet (or SF) when selected in Data
MASTER_KITCHENS_TAB_SHEETS = [
    "Muraslat",
    "rawda",
    "Arida",
    "Tuawiq",
    "Bishr",
    "Hofuf",
    "Rawda - DMM",
    "Zuhur DMM",
    "Rakah KBR",
    "Aqrabiya KBR",
    "Wurud",
    "Yasmin",
    "king faisal",
    "narjis",
    "Arid2",
    "kinf Fahd",
    "Jarir",
    "Aqiq2",
    "Salam",
    "Khaleej",
    "Malaga2",
    "Malaga1",
    "swueidi2",
    "swueidi",
    "dahrat Laban",
    "wadi",
    "sulimaniah",
    "olaya",
    "qortuba",
]


# Tab IDs hidden from Kitchen Master Data facility/sheet filter (these sheets are excluded from the dropdown)
# Per user: exclude Auto Refresh Execution Log, SF Kitchen Data, SF Churn Data, KSA Facility details, Pivot Table 11
MASTER_KITCHENS_HIDDEN_TABS = {
    "Auto Refresh Execution Log",
    "KSA Facility details",
    "SF Churn Data",
    "SF Kitchen Data",
    "Kitchens",
    "Master Kitchens list",
    "Pivot Table 11",
}


def _master_kitchens_other_sheet_ids() -> list[str]:
    """Sheet tab IDs shown as facilities in Kitchen Master Data. Excludes execution log, SF data, KSA facility details, pivot table 11."""
    _hidden_lower = {s.strip().lower() for s in MASTER_KITCHENS_HIDDEN_TABS}
    return [t for t in list_tab_ids_for_source("gsheet") if (t or "").strip().lower() not in _hidden_lower]


def _master_kitchens_sources() -> list[tuple[str, str]]:
    """(display_name, source_id). Only Qurtoba - Old and sheets after it (no Kitchens / Master Kitchens list / Main tracker)."""
    return [(tab_id, tab_id) for tab_id in _master_kitchens_other_sheet_ids()]


def _dashboard_load_source(source_id: str) -> list[dict]:
    """Load rows for the given dashboard source_id."""
    if source_id == "main_tracker":
        return list_rows()
    if source_id == "exec_log":
        return list_exec_log()  # already list of dicts
    return list_generic_tab(source_id)


def _get_superset_master_kitchens():
    """
    If data_store has master_kitchens_live, return (rows as list of dicts, metadata dict).
    Else return (None, None). Used so Streamlit reads only from persisted store, never calls Superset live.
    """
    if not data_store_mod:
        return None, None
    try:
        name = getattr(data_store_mod, "MASTER_KITCHENS_LIVE", "master_kitchens_live")
        df = data_store_mod.read_dataset(name)
        meta = data_store_mod.read_metadata(name)
        if df is not None and not df.empty:
            return df.to_dict("records"), meta
    except Exception:
        pass
    return None, None


def _superset_stale_warning(meta: dict) -> bool:
    """True if last refresh is older than 30 minutes or status != success."""
    if not meta:
        return False
    if (meta.get("status") or "").strip().lower() != "success":
        return True
    ts = meta.get("last_refresh_ts_utc") or ""
    if not ts:
        return False
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
        return age_min > 30
    except Exception:
        return False


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
# source = 'salesforce' | 'gsheet'. When None, uses st.session_state["data_source"] so SF and GSheet data stay separate.
def list_generic_tab(tab_id, source=None):
    if source is None:
        source = (st.session_state.get("data_source") or "salesforce").strip() or "salesforce"
    with get_conn() as c:
        r = c.execute(
            "SELECT data FROM generic_tab_data WHERE source = ? AND tab_id = ? ORDER BY row_index",
            (source, tab_id),
        )
        return [json.loads(row[0]) for row in r]


def list_tab_ids_for_source(source: str) -> list[str]:
    """All tab IDs that have data in generic_tab_data for the given source (e.g. 'gsheet')."""
    with get_conn() as c:
        r = c.execute("SELECT DISTINCT tab_id FROM generic_tab_data WHERE source = ? ORDER BY tab_id", (source,))
        return [row[0] for row in r]


def list_gsheet_tab_ids_in_sheet_order() -> list[str]:
    """All GSheet tab IDs that have data, in worksheet order when available (from last refresh). Never omit a tab."""
    with get_conn() as c:
        order_rows = c.execute(
            "SELECT tab_id FROM gsheet_tab_order ORDER BY tab_index"
        ).fetchall()
        ordered = [row[0] for row in order_rows]
        have_data = list(
            row[0] for row in c.execute(
                "SELECT DISTINCT tab_id FROM generic_tab_data WHERE source = ?", ("gsheet",)
            ).fetchall()
        )
    # Show all tabs that have data; use saved order when available, then append any others (e.g. from older refresh)
    ordered_set = set(ordered)
    in_order = [t for t in ordered if t in set(have_data)]
    not_in_order = [t for t in have_data if t not in ordered_set]
    return in_order + not_in_order


def list_extra_tab_ids(source=None) -> list[str]:
    """Tab IDs that have data in generic_tab_data for the given source but are not in SHEET_TAB_IDS."""
    if source is None:
        source = (st.session_state.get("data_source") or "salesforce").strip() or "salesforce"
    known = set(SHEET_TAB_IDS)
    with get_conn() as c:
        r = c.execute("SELECT DISTINCT tab_id FROM generic_tab_data WHERE source = ? ORDER BY tab_id", (source,))
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


def save_generic_tab(tab_id, rows, source: str):
    """Save rows for a tab under the given source ('salesforce' or 'gsheet'). SF and GSheet data are stored separately."""
    with get_conn() as c:
        c.execute("DELETE FROM generic_tab_data WHERE source = ? AND tab_id = ?", (source, tab_id))
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                row = dict(row)
            c.execute(
                "INSERT INTO generic_tab_data (source, tab_id, row_index, data) VALUES (?, ?, ?, ?)",
                (source, tab_id, i, json.dumps(row, ensure_ascii=False)),
            )


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


def _fetch_facility_go_live_csv() -> list[dict] | None:
    """Load facility go-live from CSV (e.g. data/sa_bh_facility_go_live.csv).
    Returns list of dicts with kitchen_number (empty), account_name, go_live_date, is_live.
    Rule: is_live = (go_live_date is set and go_live_date <= today); otherwise not live.
    """
    path = REPO_ROOT / "data" / "sa_bh_facility_go_live.csv"
    try:
        cfg = (getattr(st, "secrets", None) or {}).get("go_live_facilities")
        if isinstance(cfg, dict) and cfg.get("path"):
            path = Path(cfg["path"]).expanduser().resolve()
        if not path.exists():
            return None
        today = date.today()
        out = []
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                an = (row.get("account_name") or "").strip()
                if not an:
                    continue
                gl = (row.get("go_live_date") or "").strip()
                # Rule: go_live_date on or before today → Live; otherwise Not live
                is_live = False
                if gl:
                    try:
                        go_date = datetime.strptime(gl, "%Y-%m-%d").date()
                        is_live = go_date <= today
                    except (ValueError, TypeError):
                        pass
                out.append({
                    "kitchen_number": "",
                    "account_name": an,
                    "go_live_date": gl,
                    "is_live": is_live,
                })
        return out if out else None
    except Exception:
        return None


def _fetch_bigquery_go_live() -> list[dict] | None:
    """Fetch kitchen go-live / is_live from BigQuery when configured.
    Expects st.secrets.bigquery_go_live with project_id and query (or dataset_id + table_id).
    Returns list of dicts with keys kitchen_number, account_name, is_live, go_live_date; or None if not configured or error.
    """
    try:
        cfg = (getattr(st, "secrets", None) or {}).get("bigquery_go_live")
        if not cfg or not isinstance(cfg, dict):
            cfg = None
        if not cfg:
            return None
        project_id = (cfg.get("project_id") or "").strip()
        query = (cfg.get("query") or "").strip()
        dataset_id = (cfg.get("dataset_id") or "").strip()
        table_id = (cfg.get("table_id") or "").strip()
        if not project_id:
            return None
        if not query and dataset_id and table_id:
            query = f"SELECT kitchen_number, account_name, go_live_date, is_live FROM `{project_id}.{dataset_id}.{table_id}`"
        if not query:
            return None
        creds_path = _get_google_credentials_path()
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError:
            return None
        if creds_path == "__FROM_SECRETS__":
            info = dict(getattr(st, "secrets", {}).get("gsheet_service_account", {}))
            if not info:
                client = bigquery.Client(project=project_id)
            else:
                info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
                info.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/bigquery.readonly"]
                )
                client = bigquery.Client(project=project_id, credentials=creds)
        elif creds_path and Path(creds_path).exists():
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/bigquery.readonly"]
            )
            client = bigquery.Client(project=project_id, credentials=creds)
        else:
            client = bigquery.Client(project=project_id)
        job = client.query(query)
        rows = list(job.result())
        today = date.today()
        out = []
        for row in rows:
            d = dict(row)
            # Normalize keys (BQ may return various names: Kitchen Number ID 18, Account Name, Go Live Date)
            kn = (
                d.get("kitchen_number") or d.get("Kitchen_Number")
                or d.get("Kitchen_Number_ID_18__c") or d.get("Kitchen Number ID 18")
                or ""
            )
            kn = str(kn).strip() or None
            an = (
                d.get("account_name") or d.get("Account_Name")
                or d.get("Account Name") or d.get("Account_Name__c") or ""
            )
            an = str(an).strip() or None
            gl = d.get("go_live_date") or d.get("Go_Live_Date__c") or d.get("Go Live Date")
            if gl is not None and hasattr(gl, "strftime"):
                gl = gl.strftime("%Y-%m-%d")
            elif isinstance(gl, str) and gl.strip():
                gl = gl.strip()
            else:
                gl = ""
            # Rule: go_live_date on or before today → Live; otherwise Not live
            is_live = False
            go_date = None
            if gl:
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                    try:
                        go_date = datetime.strptime(gl[:10], fmt).date()
                        if fmt != "%Y-%m-%d":
                            gl = go_date.strftime("%Y-%m-%d")
                        break
                    except (ValueError, TypeError):
                        continue
                if go_date is not None:
                    is_live = go_date <= today
            out.append({"kitchen_number": kn, "account_name": an, "is_live": is_live, "go_live_date": gl or ""})
        return out if out else None
    except Exception:
        return None


def _fetch_bigquery_sf_churn_data() -> list[dict] | None:
    """Fetch SF Churn Data from BigQuery when configured.
    Expects st.secrets.bigquery_sf_churn_data with project_id and query.
    Returns list of dicts (one per row, keys = column names) or None if not configured or error.
    Used as data source for the SF Churn Data tab when set; overrides Salesforce for that tab on refresh.
    """
    try:
        cfg = (getattr(st, "secrets", None) or {}).get("bigquery_sf_churn_data")
        if not cfg or not isinstance(cfg, dict):
            return None
        project_id = (cfg.get("project_id") or "").strip()
        query = (cfg.get("query") or "").strip()
        if not project_id or not query:
            return None
        creds_path = _get_google_credentials_path()
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError:
            return None
        if creds_path == "__FROM_SECRETS__":
            info = dict(getattr(st, "secrets", {}).get("gsheet_service_account", {}))
            if not info:
                client = bigquery.Client(project=project_id)
            else:
                info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
                info.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/bigquery.readonly"]
                )
                client = bigquery.Client(project=project_id, credentials=creds)
        elif creds_path and Path(creds_path).exists():
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/bigquery.readonly"]
            )
            client = bigquery.Client(project=project_id, credentials=creds)
        else:
            client = bigquery.Client(project=project_id)
        job = client.query(query)
        rows = list(job.result())
        # BQ Row supports dict(row); normalize to plain dicts for JSON storage
        out = [dict(r) for r in rows]
        return out if out else None
    except Exception:
        return None


def _fetch_bigquery_master_kitchens() -> tuple[list[dict] | None, str | None]:
    """Fetch Kitchen Master Data from BigQuery when configured.
    Expects st.secrets.bigquery_master_kitchens with project_id and query (or query_file).
    query_file: path relative to repo root (e.g. docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql); file may contain comments and only the last SELECT is used.
    Returns (list of dicts, None) on success or (None, error_message) if not configured or on error.
    """
    try:
        cfg = (getattr(st, "secrets", None) or {}).get("bigquery_master_kitchens")
        if not cfg or not isinstance(cfg, dict):
            return None, None
        project_id = (cfg.get("project_id") or "").strip()
        query = (cfg.get("query") or "").strip()
        query_file = (cfg.get("query_file") or "").strip()
        if not project_id:
            return None, None
        if not query and query_file:
            base = Path(__file__).resolve().parent.parent
            path = (base / query_file) if not Path(query_file).is_absolute() else Path(query_file)
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                for part in raw.split(";"):
                    part = part.strip()
                    if part.upper().startswith("SELECT"):
                        query = part
                        break
            if not query:
                return None, f"query_file not found or no SELECT in: {query_file}"
        if not query:
            return None, "Missing query or query_file in bigquery_master_kitchens"
        creds_path = _get_google_credentials_path()
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError:
            return None, "Missing google-cloud-bigquery (pip install google-cloud-bigquery)"
        if creds_path == "__FROM_SECRETS__":
            info = dict(getattr(st, "secrets", {}).get("gsheet_service_account", {}))
            if not info:
                client = bigquery.Client(project=project_id)
            else:
                info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
                info.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/bigquery.readonly"]
                )
                client = bigquery.Client(project=project_id, credentials=creds)
        elif creds_path and Path(creds_path).exists():
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/bigquery.readonly"]
            )
            client = bigquery.Client(project=project_id, credentials=creds)
        else:
            client = bigquery.Client(project=project_id)
        job = client.query(query)
        rows = list(job.result())
        out = []
        for row in rows:
            d = dict(row)
            for k, v in list(d.items()):
                if hasattr(v, "strftime"):
                    try:
                        d[k] = v.strftime("%Y-%m-%d")
                    except Exception:
                        d[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
            out.append(d)
        return (out if out else None, None)
    except Exception as e:
        return None, str(e)


def _merge_go_live_into_kitchens(rows_kitchens: list[dict], bq_rows: list[dict]) -> list[dict]:
    """Merge BigQuery go-live result into kitchen rows. Adds 'Is Live' and 'Go Live Date' to each row when matched."""
    def _kitchen_key(r):
        for k in ("Kitchen Number", "Kitchen_Number_ID_18__c", "Name", "Kitchen Number Name", "Kitchen_Number__c.Name"):
            v = r.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""
    def _account_key(r):
        for k in ("Account Name", "Account__r.Name", "facility", "Facility"):
            v = r.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""
    lookup = {}
    for b in bq_rows:
        kn = (b.get("kitchen_number") or "").strip()
        an = (b.get("account_name") or "").strip()
        if kn or an:
            lookup[(kn, an)] = {"is_live": b.get("is_live", False), "go_live_date": b.get("go_live_date") or ""}
    for r in rows_kitchens:
        kn = _kitchen_key(r)
        an = _account_key(r)
        info = lookup.get((kn, an)) or lookup.get((kn, "")) or lookup.get(("", an))
        if info:
            r["Is Live"] = info["is_live"]
            r["Go Live Date"] = info.get("go_live_date") or ""
        else:
            r["Is Live"] = None  # unknown
            r["Go Live Date"] = ""
    return rows_kitchens


def _salesforce_token_from_password(
    consumer_key: str,
    consumer_secret: str,
    username: str,
    password: str,
    use_sandbox: bool = False,
) -> dict | None:
    """Get access_token and instance_url via OAuth password flow. Returns {"base_url": ..., "token": ...} or None."""
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
        resp.raise_for_status()
        out = resp.json()
        base = (out.get("instance_url") or "").rstrip("/")
        token = out.get("access_token")
        if base and token:
            return {"base_url": base, "token": token}
    except Exception:
        pass
    return None


def _get_salesforce_config(force_sandbox: bool | None = None) -> dict | None:
    """Salesforce connection. force_sandbox: True = sandbox, False = prod, None = use SF_USE_SANDBOX from env/secrets."""
    try:
        secrets = getattr(st, "secrets", None) or {}
        base_url = os.environ.get("SF_INSTANCE_URL") or secrets.get("SF_INSTANCE_URL")
        token = os.environ.get("SF_ACCESS_TOKEN") or secrets.get("SF_ACCESS_TOKEN")

        if base_url and token:
            return {"base_url": str(base_url).rstrip("/"), "token": str(token)}

        # Password flow: Consumer Key + Secret + Username + Password (password = user password + security token if required)
        consumer_key = os.environ.get("SF_CONSUMER_KEY") or secrets.get("SF_CONSUMER_KEY")
        consumer_secret = os.environ.get("SF_CONSUMER_SECRET") or secrets.get("SF_CONSUMER_SECRET")
        username = os.environ.get("SF_USERNAME") or secrets.get("SF_USERNAME")
        password = (os.environ.get("SF_PASSWORD") or secrets.get("SF_PASSWORD") or "").strip()
        security_token = (os.environ.get("SF_SECURITY_TOKEN") or secrets.get("SF_SECURITY_TOKEN") or "").strip()
        if security_token:
            password = password + security_token
        if force_sandbox is not None:
            use_sandbox = force_sandbox
        else:
            use_sandbox = str(os.environ.get("SF_USE_SANDBOX") or secrets.get("SF_USE_SANDBOX") or "").strip().lower() in ("1", "true", "yes")

        if consumer_key and consumer_secret and username and password:
            cache_key = f"sf_api_config_cache_{use_sandbox}"
            cache = st.session_state.get(cache_key)
            if isinstance(cache, dict) and cache.get("expires_at") and datetime.now(timezone.utc).timestamp() < cache.get("expires_at", 0):
                return {"base_url": cache["base_url"], "token": cache["token"]}
            cfg = _salesforce_token_from_password(consumer_key, consumer_secret, username, password, use_sandbox)
            if cfg:
                st.session_state[cache_key] = {
                    "base_url": cfg["base_url"],
                    "token": cfg["token"],
                    "expires_at": datetime.now(timezone.utc).timestamp() + 5400,
                }
                return cfg
    except Exception:
        pass
    return None


def _salesforce_query(soql: str, config: dict) -> list[dict]:
    """Run a SOQL query via REST API; return list of records (strip attributes)."""
    url = f"{config['base_url']}/services/data/v59.0/query"
    headers = {"Authorization": f"Bearer {config['token']}", "Content-Type": "application/json"}
    resp = requests.get(url, headers=headers, params={"q": soql}, timeout=60)
    if resp.status_code == 400:
        msg = "Invalid query (check field/relationship names in your org)."
        try:
            err = resp.json()
            if isinstance(err, list) and len(err) > 0 and isinstance(err[0], dict):
                msg = err[0].get("message", msg)
            elif isinstance(err, dict):
                msg = err.get("message", msg)
        except Exception:
            pass
        if resp.text and msg == "Invalid query (check field/relationship names in your org).":
            msg = resp.text[:500] if len(resp.text) > 500 else resp.text
        # Raise so the exact Salesforce message appears in the app error box
        raise ValueError(f"SF query failed: {msg}")
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
    resp = requests.get(url, headers=headers, params={"includeDetails": "true"}, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    fact_map = data.get("factMap") or {}
    # Tabular reports use key "T!T"
    tabular = fact_map.get("T!T") or fact_map.get("T!t") or {}
    rows_data = tabular.get("rows") or []
    if not rows_data:
        return []
    out = []
    for row in rows_data:
        cells = row.get("dataCells") or []
        out.append({str(c.get("label", f"_col{i}")): c.get("value") for i, c in enumerate(cells)})
    return out


# Direct Report IDs: fetch these from Salesforce when sf_tab_queries is not set.
# First report is used for both Kitchens and Master Kitchens list (same data, two tabs).
SALESFORCE_DIRECT_REPORT_IDS = [
    ("Kitchens", "00OVO000003z2O92AI"),
    ("Master Kitchens list", "00OVO000003z2O92AI"),
    ("SF Churn Data", "00O6T000006Y5DiUAK"),
    ("Report Y0l6", "00O6T000006Y0l6UAC"),
    ("Report DPig", "00O6T000006DPigUAG"),
    ("Report DXT0", "00O6T000006DXT0UAO"),
]


def _get_salesforce_tab_queries() -> dict[str, str]:
    """Tab name → SOQL or Report ID (00O...). From secrets [sf_tab_queries], env SF_TAB_QUERIES, or SALESFORCE_DIRECT_REPORT_IDS."""
    try:
        # Streamlit secrets: [sf_tab_queries] with keys like "Kitchens" = "00O..."
        sq = getattr(st, "secrets", None) and st.secrets.get("sf_tab_queries")
        if isinstance(sq, dict):
            out = {k: str(v).strip() for k, v in sq.items() if v}
            if out:
                return out
        raw = os.environ.get("SF_TAB_QUERIES", "")
        if raw and raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, TypeError, Exception):
        pass
    # Default: use direct report IDs so data is fetched from these reports
    return {name: rid for name, rid in SALESFORCE_DIRECT_REPORT_IDS}


def _default_mock_tab_queries() -> dict[str, str]:
    """Default tabs to load when SFDC_PROVIDER=mock and [sf_tab_queries] is empty."""
    return {
        "Kitchens": "00OVO00000PMnq92AD",
        "Master Kitchens list": "00OVO00000PMnq92AD",
    }


def _refresh_from_salesforce():
    """Pull data from Salesforce (or mock) and load into Data tabs. Provider: SFDC_PROVIDER=mock|sandbox|prod."""
    import sfdc_providers as sfdc  # noqa: PLC0415

    provider = sfdc.get_sfdc_provider()
    tab_queries = _get_salesforce_tab_queries()
    if not tab_queries and provider == "mock":
        tab_queries = _default_mock_tab_queries()
    if not tab_queries:
        return False, (
            "No SOQL or Report IDs configured. In Streamlit secrets add [sf_tab_queries] with e.g. "
            '"Kitchens" = "00OVO00000PMnq92AD", "Master Kitchens list" = "00OVO00000PMnq92AD". See docs/SETUP_SF_SECRETS.md.'
        )
    KITCHENS_TAB = "Kitchens"
    loaded = []
    errors = []

    # —— Mock provider: read from app/data/mock/{tab_slug}.json or .csv ——
    if provider == "mock":
        for tab_id, soql_or_report_id in tab_queries.items():
            if not soql_or_report_id:
                continue
            save_to = KITCHENS_TAB if tab_id == "SF Kitchen Data" else tab_id
            if tab_id == "SF Churn Data":
                bq_rows = _fetch_bigquery_sf_churn_data()
                if bq_rows is not None:
                    save_generic_tab(save_to, bq_rows, source="salesforce")
                    loaded.append(f"{save_to} (BQ, {len(bq_rows)} rows)")
                    continue
            try:
                rows = sfdc.mock_fetch_tab_data(tab_id, soql_or_report_id)
                save_generic_tab(save_to, rows, source="salesforce")
                loaded.append(f"{save_to} ({len(rows)} rows)")
            except Exception as e:
                errors.append(f"{tab_id}: {e}")
        if loaded and not errors:
            return True, "Mock data: " + "; ".join(loaded)
        if errors:
            return False, "Mock: " + "; ".join(errors)
        return False, "No mock data. Add JSON/CSV files in app/data/mock/ (e.g. Kitchens.json). See docs/SFDC_PROVIDERS.md."

    # —— Sandbox / Prod: use Salesforce API (force_sandbox from provider) ——
    force_sandbox = provider == "sandbox"
    config = _get_salesforce_config(force_sandbox=force_sandbox)
    if not config:
        return False, (
            "Salesforce not configured. Use (1) SF_INSTANCE_URL + SF_ACCESS_TOKEN, or "
            "(2) SF_CONSUMER_KEY + SF_CONSUMER_SECRET + SF_USERNAME + SF_PASSWORD. "
            f"Provider={provider}."
        )
    for tab_id, soql_or_report_id in tab_queries.items():
        if not soql_or_report_id:
            continue
        save_to = KITCHENS_TAB if tab_id == "SF Kitchen Data" else tab_id
        # SF Churn Data: prefer BigQuery when configured (same tab, source=salesforce)
        if tab_id == "SF Churn Data":
            bq_rows = _fetch_bigquery_sf_churn_data()
            if bq_rows is not None:
                save_generic_tab(save_to, bq_rows, source="salesforce")
                loaded.append(f"{save_to} (BQ, {len(bq_rows)} rows)")
                continue
        try:
            if _is_report_id(soql_or_report_id):
                rows = _salesforce_report_data(soql_or_report_id, config)
            else:
                rows = _salesforce_query(soql_or_report_id, config)
            if rows:
                save_generic_tab(save_to, rows, source="salesforce")
                loaded.append(f"{save_to} ({len(rows)} rows)")
            else:
                loaded.append(f"{save_to} (0 rows)")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 403 and _is_report_id(soql_or_report_id):
                errors.append(
                    f"{tab_id}: 403 Forbidden — the API user cannot run this report. "
                    "Grant 'Run Reports' and report folder access, or use SOQL. See docs/SETUP_SF_SECRETS.md."
                )
            else:
                errors.append(f"{tab_id}: {e}")
        except Exception as e:
            errors.append(f"{tab_id}: {e}")
    if loaded and not errors:
        return True, f"{provider.capitalize()} Salesforce: " + "; ".join(loaded)
    if errors:
        return False, "Salesforce: " + "; ".join(errors)
    return False, "No Salesforce data returned. Check SOQL or Report IDs in sf_tab_queries."


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
        # Google sometimes requires these; add if missing so "working before" configs keep working
        info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
        info.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
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


def _fetch_bq_export_sheet() -> tuple[list[dict] | None, str | None]:
    """Load Kitchen Master Data from a Google Sheet that is fed by BigQuery (pipeline/scheduled query).
    Expects secrets bq_export_sheet_id = \"sheet-id\" or full docs URL. Uses same [gsheet_service_account].
    Returns (rows, None) on success or (None, error_message)."""
    secrets = getattr(st, "secrets", None) or {}
    sheet_id_or_url = (secrets.get("bq_export_sheet_id") or "").strip()
    if not sheet_id_or_url:
        return None, None
    # Allow full URL: extract ID from docs.google.com/spreadsheets/d/ID/...
    sheet_id = sheet_id_or_url
    if "docs.google.com" in sheet_id_or_url and "/d/" in sheet_id_or_url:
        try:
            sheet_id = sheet_id_or_url.split("/d/")[1].split("/")[0].strip()
        except Exception:
            return None, "Invalid bq_export_sheet_id URL"
    creds_path = _get_google_credentials_path()
    if not creds_path:
        return None, "No Google credentials (need [gsheet_service_account] or GOOGLE_APPLICATION_CREDENTIALS)"
    try:
        data = _fetch_online_sheet(sheet_id, creds_path)
    except Exception as e:
        return None, str(e)
    # Use first worksheet with data
    for _title, rows in data.items():
        if rows:
            return rows, None
    return None, "Sheet has no data"


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
        return False, (
            "No Google credentials. "
            "Streamlit Cloud: in Secrets add [gsheet_service_account] with your service account JSON. "
            "Local: put the JSON at scripts/credentials.json or set GOOGLE_APPLICATION_CREDENTIALS. "
            "Share the sheet with the service account email (Viewer). See docs/REFRESH_FROM_ONLINE_SHEET.md."
        )
    try:
        data = _fetch_online_sheet(SHEET_ID, creds_path)
    except Exception as e:
        err = str(e)
        if "403" in err or "permission" in err.lower() or "Permission" in err:
            err = err + " — Share the Google Sheet with the service account email (Viewer). See docs/REFRESH_FROM_ONLINE_SHEET.md."
        return False, err
    loaded = []
    tab_order: list[tuple[int, str]] = []  # (index, tab_id) to match sheet order
    for idx, (ws_title, rows) in enumerate(data.items()):
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
        # SF Kitchen Data sheet -> Kitchens tab (single main view)
        if tab_id == "SF Kitchen Data" or (tab_id or "").startswith("SF Kitchen Data"):
            tab_id = "Kitchens"
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
            # Apply same logic as the Google Sheet: country merge (SA/regions → Saudi Arabia, BH → Bahrain) for all tabs
            rows = _ensure_account_country_in_kitchens(rows)
            save_generic_tab(tab_id, rows, source="gsheet")
            loaded.append(f"{tab_id} ({len(rows)} rows)")
        # Record tab order (skip exec log so Data tabs match sheet tabs)
        if tab_id != "Auto Refresh Execution Log" and not _is_main_tracker_tab(tab_id):
            tab_order.append((len(tab_order), tab_id))
    # Persist worksheet order so Data section tabs match the Google Sheet
    if tab_order:
        with get_conn() as c:
            c.execute("DELETE FROM gsheet_tab_order")
            for i, tid in tab_order:
                c.execute("INSERT OR REPLACE INTO gsheet_tab_order (tab_index, tab_id) VALUES (?, ?)", (i, tid))
    return True, "Loaded: " + "; ".join(loaded) if loaded else "No data in sheet."


# When a row has any of these (Account.Country__c, Account__r.Country__c, Country__c, Country, County),
# that value is shown in the "Account Country" column on the Kitchens tab. Case-insensitive match.
_COUNTRY_HEADERS = (
    "account.country__c",
    "account__r.country__c",
    "country__c",
    "country",
    "county",
    "account country",
    "account country__c",
    "account_country__c",
    "billingcountry",
)
_ACCOUNT_NAME_HEADERS = (
    "account.name", "account__r.name", "account name", "account_name",
)
# Merge all entries with Saudi Arabia except Bahrain. SA/regions (North, South, etc.) → Saudi Arabia; BH → Bahrain.
_COUNTRY_FROM_PREFIX = {
    "bh": "Bahrain", "bhr": "Bahrain",
}
# Any other prefix (sa, ksa, north, south, etc.) → Saudi Arabia via .get(prefix, "Saudi Arabia")


def _ensure_account_country_in_kitchens(rows: list[dict]) -> list[dict]:
    """Ensure each row has 'Account Country'; derive from existing country field or Account name. For SF Kitchen Data."""
    if not rows:
        return rows
    first = rows[0]
    keys_lower = {str(k).strip().lower(): k for k in first.keys()}
    country_key = None
    for h in _COUNTRY_HEADERS:
        if h in keys_lower:
            country_key = keys_lower[h]
            break
    account_name_key = None
    for h in _ACCOUNT_NAME_HEADERS:
        if h in keys_lower:
            account_name_key = keys_lower[h]
            break
    # Merge all with Saudi Arabia except Bahrain (North, South, SA, Last, etc. → Saudi Arabia; only BH → Bahrain)
    def _normalize_country_value(val: str) -> str:
        v = (val or "").strip()
        if not v:
            return v
        v_lower = v.lower()
        if v_lower in ("bh", "bhr", "bahrain"):
            return "Bahrain"
        return "Saudi Arabia"
    out = []
    for r in rows:
        row = dict(r)
        if country_key and (row.get(country_key) or "").strip():
            row["Account Country"] = _normalize_country_value(str(row.get(country_key, "")))
        elif account_name_key:
            name = str(row.get(account_name_key, "") or "").strip()
            if " - " in name:
                prefix = name.split(" - ")[0].strip().lower()
                row["Account Country"] = _COUNTRY_FROM_PREFIX.get(prefix, "Saudi Arabia")
            else:
                raw = row.get("Account Country", "") or ""
                row["Account Country"] = _normalize_country_value(str(raw)) if raw else ""
        else:
            raw = row.get("Account Country", "") or ""
            row["Account Country"] = _normalize_country_value(str(raw)) if raw else ""
        out.append(row)
    return out


# SF Kitchen Data: API name → display label (from your org report)
SF_KITCHEN_DATA_LABELS = {
    "Account__r.Name": "Account Name",
    "Type__c": "Type",
    "Category__c": "Category",
    "Kitchen_Number_ID_18__c": "Kitchen Number",
    "Name": "Kitchen Number Name",
    "Status__c": "Status",
    "Kitchen_Size_Sq_Meters__c": "Kitchen Size",
    "Hood_Size__c": "Hood Size",
    "Floor_Price__c": "Floor Price",
    "Sell_Price__c": "List Price",
    "Activation_Fee__c": "Activation Fee",
    "Opportunity__r.Id": "Opportunity",
    "Opportunity__r.Name": "Opportunity Name",
    "Opportunity__r.Owner.Name": "Opportunity Owner",
    "Floor__c": "Floor",
    "Account__r.Country__c": "County",
    "Opportunity__r.Churn_Date__c": "Churn Date",
    "Account Country": "County",
}


def _apply_kitchen_labels(rows: list[dict], cols: list[str]) -> tuple[list[dict], list[str]]:
    """Rename API keys to display labels for SF Kitchen Data; keep column order unique."""
    labels = SF_KITCHEN_DATA_LABELS
    out_rows = []
    for r in rows:
        new_r = {}
        for k, v in r.items():
            L = labels.get(k, k)
            if L not in new_r:
                new_r[L] = v
        out_rows.append(new_r)
    seen = set()
    out_cols = []
    for c in cols:
        L = labels.get(c, c)
        if L not in seen:
            seen.add(L)
            out_cols.append(L)
    return out_rows, out_cols


def _kitchens_column_order(cols: list[str]) -> list[str]:
    """Put County/Account Country near the start for Kitchens/SF Kitchen Data."""
    cols = list(cols)
    for first in ("County", "Account Country"):
        if first in cols:
            cols.remove(first)
            return [first] + cols
    return cols


def _get_facility_column(keys: list) -> str | None:
    """Return the column name used for facility/account name, or None. Prefer Account Name, then Facility. Case-insensitive and flexible."""
    if not keys:
        return None
    preferred = ("Account Name", "Account__r.Name", "Facility", "Account Name__c", "Account_Name__c", "Facility__c", "facility_name", "account_name", "Facility Name")
    for name in preferred:
        for k in keys:
            if str(k).strip().lower() == name.lower():
                return k
    def _norm(s):
        return re.sub(r"[\s_\.]+", "", str(s).lower()).replace("__c", "")
    for k in keys:
        n = _norm(k)
        if n in ("accountname", "facility", "facilityname", "accountnamec"):
            return k
        if "account" in n and "name" in n and "country" not in n:
            return k
        if "facility" in n and "country" not in n and "go" not in n and "live" not in n:
            return k
    # Fallback: first column with "Name" in the name (and not Country)
    for k in keys:
        if "name" in str(k).lower() and "country" not in str(k).lower():
            return k
    return None


def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert columns that look numeric (e.g. string '14.78') to numeric type so AgGrid sorts by value, not text."""
    if df is None or df.empty:
        return df
    df = df.copy()
    skip = {"_has_opportunity"}
    for col in df.columns:
        if col in skip:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        ser = pd.to_numeric(df[col], errors="coerce")
        non_null = ser.notna().sum()
        if non_null >= max(1, len(df) * 0.5):
            df[col] = ser
    return df


def _is_account_country_column(col_name: str) -> bool:
    """True if this column is Account Country / facility_country (any casing/spacing/dots/prefix). Hide in Master Kitchens."""
    if not col_name:
        return False
    n = str(col_name).strip().lower().replace(".", "_")
    n = re.sub(r"[\s_]+", "_", n).strip("_")
    # Strip trailing __c (Salesforce convention)
    if n.endswith("__c"):
        n = re.sub(r"_+c$", "", n)
    # Match exact, suffix, or name containing both "account" and "country" / facility_country
    return (
        n == "accountcountry"
        or n in ("account_country", "facility_country")
        or n.endswith("account_country")
        or n.endswith("facility_country")
        or ("account" in n and "country" in n)
    )


def _normalize_status_label(val) -> str:
    """Normalize status value for filter: Vacant, Churning, Occupied, Sold, or raw. Used for Status filter and row count."""
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return "No status"
    low = s.lower()
    if low in ("no status", "n/a", "na", "—", "-", "blocked"):
        return "No status"
    if low == "churning":
        return "Churning"
    if low in ("occupied", "sold"):
        return "Occupied" if low == "occupied" else "Sold"
    if low == "vacant" or (low.startswith("vacant") and "occupied" not in low and "sold" not in low and "churning" not in low):
        return "Vacant"
    return s


def _is_empty_record(row) -> bool:
    """True if the row has no meaningful data (all values empty, null, or whitespace)."""
    if not row or not isinstance(row, dict):
        return True
    for v in row.values():
        s = str(v).strip() if v is not None else ""
        if s and s.lower() not in ("nan", "none", "n/a", "na", "—", "-"):
            return False
    return True


def _status_row_class_rules_and_css(status_col_name: str):
    """Return (rowClassRules dict, custom_css str) for AgGrid status color coding. status_col_name is the exact dataframe column name (e.g. 'Status' or 'status__c')."""
    # JS-safe column key for data[] access
    col_key = status_col_name.replace("\\", "\\\\").replace("'", "\\'")
    # Expressions use AG Grid rowClassRules context: 'data' is the row data
    data_ref = f"data['{col_key}']"
    data_ref_ho = "data['_has_opportunity']"
    row_class_rules = {
        "status-no-status": f"(function(){{var s=({data_ref}!=null?String({data_ref}).trim():'').toLowerCase(); return !s||s==='no status'||s==='n/a'||s==='na'||s==='—'||s==='-'||s==='blocked';}})()",
        "status-vacant-opp": f"(function(){{var s=({data_ref}!=null?String({data_ref}).trim():'').toLowerCase(); var v=(s==='vacant'||(s.indexOf('vacant')===0&&s.indexOf('occupied')<0&&s.indexOf('sold')<0&&s.indexOf('churning')<0)); return v&&{data_ref_ho};}})()",
        "status-vacant": f"(function(){{var s=({data_ref}!=null?String({data_ref}).trim():'').toLowerCase(); var v=(s==='vacant'||(s.indexOf('vacant')===0&&s.indexOf('occupied')<0&&s.indexOf('sold')<0&&s.indexOf('churning')<0)); return v&&!{data_ref_ho};}})()",
        "status-churning": f"({data_ref}!=null?String({data_ref}).trim():'').toLowerCase()==='churning'",
        "status-occupied": f"(function(){{var s=({data_ref}!=null?String({data_ref}).trim():'').toLowerCase(); return s==='occupied'||s==='sold';}})()",
    }
    # String CSS with .ag-row selector and !important so it overrides AG Grid theme in iframe
    custom_css = """
    .ag-row.status-no-status { background-color: #B22222 !important; color: white !important; }
    .ag-row.status-no-status .ag-cell { background-color: #B22222 !important; color: white !important; }
    .ag-row.status-vacant-opp { background-color: #FEE2E2 !important; }
    .ag-row.status-vacant-opp .ag-cell { background-color: #FEE2E2 !important; }
    .ag-row.status-vacant { background-color: #D1FAE5 !important; }
    .ag-row.status-vacant .ag-cell { background-color: #D1FAE5 !important; }
    .ag-row.status-churning { background-color: #FDE68A !important; }
    .ag-row.status-churning .ag-cell { background-color: #FDE68A !important; }
    .ag-row.status-occupied { background-color: #FEE2E2 !important; }
    .ag-row.status-occupied .ag-cell { background-color: #FEE2E2 !important; }
    """
    return row_class_rules, custom_css


def _status_get_row_style_js(status_col_name: str):
    """Return JsCode for getRowStyle to apply status colors as inline styles (works when custom_css does not in iframe)."""
    if not JsCode:
        return None
    col_key = status_col_name.replace("\\", "\\\\").replace("'", "\\'")
    # getRowStyle(params): params.data has the row
    return JsCode("""
    function(params) {
        var d = params.data;
        if (!d) return null;
        var col = '%s';
        var v = (d[col] != null ? String(d[col]).trim() : '');
        var low = v.toLowerCase();
        var hasOpp = d['_has_opportunity'];
        if (!v || low === 'no status' || low === 'n/a' || low === 'na' || low === '—' || low === '-' || low === 'blocked')
            return { backgroundColor: '#B22222', color: 'white' };
        if (low === 'vacant' || (low.indexOf('vacant') === 0 && low.indexOf('occupied') < 0 && low.indexOf('sold') < 0 && low.indexOf('churning') < 0))
            return { backgroundColor: hasOpp ? '#FEE2E2' : '#D1FAE5' };
        if (low === 'churning') return { backgroundColor: '#FDE68A' };
        if (low === 'occupied' || low === 'sold') return { backgroundColor: '#FEE2E2' };
        return { backgroundColor: '#FEE2E2' };
    }
    """ % col_key)


_FACILITY_COORDS_APPROX = {
    # Approximate coordinates to visualize facilities on landing map.
    "qurtoba": (24.8106, 46.7810),
    "wadi": (24.7880, 46.7180),
    "olaya": (24.7118, 46.6753),
    "dahrat laban": (24.5935, 46.5585),
    "suwaidi": (24.5926, 46.6861),
    "malga": (24.8216, 46.6142),
    "khaleej": (24.7713, 46.8022),
    "nahda": (24.7487, 46.7769),
    "safa": (24.6856, 46.7347),
    "zuhur": (24.8390, 46.6640),
    "aqiq": (24.7896, 46.6326),
    "king fahd": (24.7685, 46.6652),
    "malga 2": (24.8255, 46.6201),
    "rawdah": (24.7417, 46.7492),
    "bawadi": (24.7244, 46.7483),
    "salam": (24.6698, 46.6714),
    "marwa": (21.5850, 39.2248),
    "tuwaiq": (24.5232, 46.5382),
    "muraslat": (24.7445, 46.7062),
    "aqrabiya": (26.3035, 50.1875),
    "jarir": (24.5553, 46.7078),
    "sulimaniah": (24.7056, 46.6780),
    "rehab": (24.9235, 46.6680),
    "rawda": (24.7417, 46.7492),
    "narjis": (24.8460, 46.7280),
    "hofuf": (25.3833, 49.5877),
    "yasmin": (24.7950, 46.6420),
    "mishrifah": (24.7580, 46.7380),
    "arid": (24.9010, 46.6160),
    "bishir": (24.7720, 46.7020),
    "al nazim": (24.8100, 46.7650),
    "sweidi 2": (24.6000, 46.6880),
    "king faisal": (24.7580, 46.7720),
    "arid 2": (24.9050, 46.6180),
    "ghirnatah 2": (24.7820, 46.6550),
    "aqiq 2": (24.7920, 46.6350),
    "rakah": (26.3520, 50.1920),
    "wurud": (24.6980, 46.6620),
}


# Map pin colors (hex) for inline SVG teardrop pins.
_MAP_PIN_HEX = {
    "Vacant": "#22c55e",
    "Churning": "#eab308",
    "Occupied/Sold": "#ef4444",
    "Unknown": "#64748b",
}


def _svg_pin_data_url(fill_hex: str) -> str:
    """Return a data URL for a teardrop map pin SVG (no external assets/CORS)."""
    fill = (fill_hex or "#64748b").strip()
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <defs>
    <radialGradient id="g" cx="28%" cy="22%" r="55%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.65"/>
      <stop offset="35%" stop-color="#ffffff" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.12"/>
    </radialGradient>
  </defs>
  <path d="M32 2C20.4 2 11 11.4 11 23c0 15.6 21 39 21 39s21-23.4 21-39C53 11.4 43.6 2 32 2z"
        fill="{fill}" stroke="#0f172a" stroke-opacity="0.55" stroke-width="2" />
  <circle cx="32" cy="23" r="10" fill="url(#g)"/>
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def _facility_jitter_lat_lon(facility_key: str) -> tuple[float, float]:
    """Stable pseudo-location for facilities without coordinates (spread around Riyadh)."""
    h = int(hashlib.md5(facility_key.encode("utf-8")).hexdigest()[:8], 16)
    lat0, lon0 = 24.7136, 46.6753
    dlat = ((h % 1000) / 1000.0 - 0.5) * 0.14
    dlon = (((h // 1000) % 1000) / 1000.0 - 0.5) * 0.16
    return lat0 + dlat, lon0 + dlon


def _resolve_facility_lat_lon(facility: str, lat_raw: str, lon_raw: str) -> tuple[float | None, float | None]:
    """Resolve coordinates from row values, static table, fuzzy name match, or jitter fallback."""
    facility_lower = (facility or "").strip().lower()
    if not facility_lower:
        return None, None
    lat = lon = None
    try:
        lat = float(lat_raw) if lat_raw else None
        lon = float(lon_raw) if lon_raw else None
    except Exception:
        lat, lon = None, None
    if lat is not None and lon is not None:
        return lat, lon
    lat, lon = _FACILITY_COORDS_APPROX.get(facility_lower, (None, None))
    if lat is None or lon is None:
        f_norm = re.sub(r"[^a-z0-9]+", " ", facility_lower).strip()
        for k, (k_lat, k_lon) in _FACILITY_COORDS_APPROX.items():
            k_norm = re.sub(r"[^a-z0-9]+", " ", str(k).strip().lower()).strip()
            if not k_norm:
                continue
            if f_norm == k_norm or f_norm.startswith(k_norm) or k_norm.startswith(f_norm) or (k_norm in f_norm) or (f_norm in k_norm):
                lat, lon = k_lat, k_lon
                break
    if lat is None or lon is None:
        lat, lon = _facility_jitter_lat_lon(facility_lower)
    return lat, lon


def _all_gsheet_facility_rows_for_map(source_ids: dict | None, source_options: list | None) -> list[dict]:
    """Load every Master Kitchens sheet tab once for the map (independent of table multiselect)."""
    if not source_ids or not source_options:
        return []
    combined: list[dict] = []
    for label in source_options:
        tab_id = source_ids.get(label, label)
        try:
            sheet_rows = list_generic_tab(tab_id, source="gsheet") or []
        except Exception:
            sheet_rows = []
        for r in sheet_rows:
            if isinstance(r, dict) and not _is_empty_record(r):
                combined.append(r)
    return combined


def _row_value_by_candidates(row: dict, candidates: list[str]) -> str:
    if not row or not isinstance(row, dict):
        return ""
    by_norm = {re.sub(r"[\s_\.]+", "", str(k).strip().lower()): k for k in row.keys()}
    for c in candidates:
        if c in row and row.get(c) is not None and str(row.get(c)).strip():
            return str(row.get(c)).strip()
    for c in candidates:
        key = by_norm.get(re.sub(r"[\s_\.]+", "", c.strip().lower()))
        if key is not None:
            v = row.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


def _render_master_kitchens_map(rows: list[dict], map_title: str = "Facilities map (preview)"):
    """Landing map: one marker per facility, status-colored teardrop pins (inline SVG icons)."""
    if not rows:
        return
    try:
        facility_key = _get_facility_column(list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [])
        if not facility_key:
            return
        buckets: dict[str, dict] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            facility = (str(r.get(facility_key, "")).strip() or "").lower()
            if not facility:
                continue
            lat_raw = _row_value_by_candidates(r, ["Latitude", "lat", "facility_latitude", "facility_lat"])
            lon_raw = _row_value_by_candidates(r, ["Longitude", "lon", "lng", "facility_longitude", "facility_lon"])
            resolved = _resolve_facility_lat_lon(str(r.get(facility_key) or "").strip(), lat_raw, lon_raw)
            if resolved[0] is None or resolved[1] is None:
                continue
            lat, lon = resolved
            b = buckets.setdefault(
                facility,
                {
                    "facility": str(r.get(facility_key) or "").strip(),
                    "lat": lat,
                    "lon": lon,
                    "total": 0,
                    "vacant": 0,
                    "churning": 0,
                    "occupied": 0,
                    "sold": 0,
                },
            )
            b["total"] += 1
            s = _normalize_status_label(r.get("Status") if "Status" in r else r.get("status__c") if "status__c" in r else r.get("status"))
            s_low = str(s).strip().lower()
            if s_low == "vacant":
                b["vacant"] += 1
            elif s_low == "churning":
                b["churning"] += 1
            elif s_low == "occupied":
                b["occupied"] += 1
            elif s_low == "sold":
                b["sold"] += 1
        if not buckets:
            return
        map_rows = []
        for b in buckets.values():
            if b["vacant"] > 0:
                status = "Vacant"
            elif b["churning"] > 0:
                status = "Churning"
            elif (b["occupied"] + b["sold"]) > 0:
                status = "Occupied/Sold"
            else:
                status = "Unknown"
            rgba = _MAP_MARKER_RGBA.get(status, _MAP_MARKER_RGBA["Unknown"])
            map_rows.append(
                {
                    "facility": b["facility"],
                    "lat": b["lat"],
                    "lon": b["lon"],
                    "total": b["total"],
                    "vacant": b["vacant"],
                    "churning": b["churning"],
                    "occupied": b["occupied"],
                    "sold": b["sold"],
                    "status": status,
                    "marker_rgba": rgba,
                }
            )
        map_df = pd.DataFrame(map_rows)
        if map_df.empty:
            return
        st.caption(
            f"**{map_title}** — all facilities (default). **Pins:** green = Vacant, yellow = Churning, "
            "red = Occupied/Sold, gray = other."
        )
        if pdk is None:
            st.map(map_df.rename(columns={"lat": "latitude", "lon": "longitude"})[["latitude", "longitude"]])
        else:
            tooltip = {
                "html": "<b>{facility}</b><br/>Status: <b>{status}</b><br/>Total: {total}<br/>Vacant: {vacant}<br/>Churning: {churning}<br/>Occupied/Sold: {occupied}/{sold}",
                "style": {"backgroundColor": "#111827", "color": "white"},
            }
            _map_records = map_df.to_dict("records")
            # Build one IconLayer per status so each can use its own inline SVG icon atlas.
            layers = []
            for status, sub in map_df.groupby("status", sort=False):
                if sub.empty:
                    continue
                fill = _MAP_PIN_HEX.get(str(status), _MAP_PIN_HEX["Unknown"])
                icon_atlas = _svg_pin_data_url(fill)
                _sub_records = sub.to_dict("records")
                for _r in _sub_records:
                    _r["icon"] = "pin"
                layers.append(
                    pdk.Layer(
                        "IconLayer",
                        data=_sub_records,
                        get_position="[lon, lat]",
                        pickable=True,
                        icon_atlas=icon_atlas,
                        icon_mapping={
                            "pin": {"x": 0, "y": 0, "width": 64, "height": 64, "anchorY": 64, "anchorX": 32}
                        },
                        get_icon="icon",
                        size_scale=1,
                        get_size=24,
                        size_min_pixels=18,
                        size_max_pixels=30,
                    )
                )
            if not layers:
                return
            try:
                st.pydeck_chart(
                    pdk.Deck(
                        layers=layers,
                        initial_view_state=pdk.ViewState(
                            latitude=float(map_df["lat"].mean()),
                            longitude=float(map_df["lon"].mean()),
                            zoom=8.2,
                            pitch=0,
                        ),
                        tooltip=tooltip,
                        map_style=None,
                    ),
                    use_container_width=True,
                )
            except Exception:
                # Fallback: circles if SVG IconLayer fails in the browser
                layer = pdk.Layer(
                    "ScatterplotLayer",
                    data=_map_records,
                    get_position="[lon, lat]",
                    get_fill_color=[100, 116, 139, 235],
                    get_radius=1,
                    radius_scale=2500,
                    radius_min_pixels=10,
                    radius_max_pixels=24,
                    pickable=True,
                    stroked=True,
                    line_width_min_pixels=2,
                    get_line_color=[15, 23, 42, 220],
                )
                try:
                    st.pydeck_chart(
                        pdk.Deck(
                            layers=[layer],
                            initial_view_state=pdk.ViewState(
                                latitude=float(map_df["lat"].mean()),
                                longitude=float(map_df["lon"].mean()),
                                zoom=8.2,
                                pitch=0,
                            ),
                            tooltip=tooltip,
                            map_style=None,
                        ),
                        use_container_width=True,
                    )
                except Exception:
                    st.map(map_df.rename(columns={"lat": "latitude", "lon": "longitude"})[["latitude", "longitude"]])
    except Exception:
        # Keep existing tracker flow untouched even if map rendering fails.
        return


def _render_generic_tab(tab_id, key_suffix="", is_developer=False, source=None, allow_download=False, hide_account_country=False):
    """View/filter for a generic tab. When source is set (e.g. 'gsheet'), read only from that source; else use session data_source. hide_account_country: when True (e.g. single facility in Master Kitchens), hide Account Country column."""
    rows = list_generic_tab(tab_id, source=source) if source else list_generic_tab(tab_id)
    # Kitchens: fallback to legacy SF Kitchen Data (before rename)
    if not rows and tab_id == "Kitchens":
        rows = list_generic_tab("SF Kitchen Data", source=source) if source else list_generic_tab("SF Kitchen Data")
    # Master Kitchens list: fallback to Kitchens if empty
    if not rows and tab_id == "Master Kitchens list":
        rows = (list_generic_tab("Kitchens", source=source) or list_generic_tab("SF Kitchen Data", source=source)) if source else (list_generic_tab("Kitchens") or list_generic_tab("SF Kitchen Data"))
    if not rows:
        st.info("No data yet. Data is refreshed every 15 minutes by the scheduler.")
        return
    rows = [r for r in rows if not _is_empty_record(r)]
    if not rows:
        st.info("No data yet (all rows are empty).")
        return
    is_kitchens_tab = tab_id in ("Kitchens", "Master Kitchens list")
    if tab_id == "Kitchens":
        st.caption("**Main view:** All kitchens under accounts in all countries. Filter by **Account Country** or search in any column to navigate.")
    if tab_id == "Master Kitchens list":
        st.caption("**Master list:** All kitchens. Filter or search in any column.")
    if tab_id == "SF Churn Data":
        st.caption("To match the live Kitchen Tracker columns, set **sf_tab_queries** → \"SF Churn Data\" to the **same Report ID** as the live churn report. See **docs/SETUP_SF_SECRETS.md**.")
    # For Kitchens / Master Kitchens list: ensure Account Country, labels, column order
    if is_kitchens_tab:
        rows = _ensure_account_country_in_kitchens(rows)
    cols = list(rows[0].keys()) if rows else []
    if is_kitchens_tab:
        rows, cols = _apply_kitchen_labels(rows, cols)
        cols = _kitchens_column_order(cols)
    # Master Kitchens list (or single-facility Master Kitchens view): hide Account Country and Sheet columns from display
    if tab_id == "Master Kitchens list" or hide_account_country:
        cols = [c for c in cols if not _is_account_country_column(c) and str(c).strip().lower() != "sheet"]
    rows_shown = rows
    _row_count_placeholder = st.empty()
    st.divider()
    # Build display dataframe with selected columns only (Master list excludes Account Country)
    display_cols = [c for c in cols if rows_shown and c in (rows_shown[0].keys() if rows_shown else [])] or (list(rows_shown[0].keys()) if rows_shown else [])
    df_display = pd.DataFrame(rows_shown)[display_cols] if display_cols and rows_shown else pd.DataFrame(rows_shown)
    # Status color coding: use AgGrid with getRowStyle when available (same approach as test_aggrid_colors.py)
    _status_colors = {"Vacant": "#D1FAE5", "Occupied": "#FEE2E2", "Sold": "#FEE2E2", "Churning": "#FDE68A"}
    _no_status_bg = "#B22222"
    status_col = None
    for c in df_display.columns:
        if str(c).strip().lower() in ("status", "status__c"):
            status_col = c
            break
    if _HAS_AGGRI and HAS_EXCEL and not df_display.empty:
        if status_col:
            df_display = df_display.copy()
            df_display["_has_opportunity"] = [_row_has_opportunity_name(r) for r in rows_shown]
        df_display = _coerce_numeric_columns(df_display)
        gb = GridOptionsBuilder.from_dataframe(df_display)
        gb.configure_default_column(
            filter=True,
            sortable=True,
            resizable=True,
            floatingFilter=False,
            suppressHeaderMenuButton=False,
            suppressHeaderFilterButton=False,
            menuTabs=["filterMenuTab", "generalMenuTab", "columnsMenuTab"],
        )
        _max_set_filter_values = 500
        for col in df_display.columns:
            if pd.api.types.is_numeric_dtype(df_display[col]):
                gb.configure_column(col, filter="agNumberColumnFilter", floatingFilter=False)
            elif pd.api.types.is_datetime64_any_dtype(df_display[col]):
                gb.configure_column(col, filter="agDateColumnFilter", floatingFilter=False)
            else:
                # Set filter so all unique values appear when user clicks Filter (checkboxes)
                ser = df_display[col].dropna().astype(str).str.strip()
                uniq = ser[ser != ""].unique()
                if len(uniq) <= _max_set_filter_values:
                    vals = sorted(uniq.tolist(), key=str)
                    gb.configure_column(col, filter="agSetColumnFilter", filterParams={"values": vals, "maxDisplayedRows": 500}, floatingFilter=False)
                else:
                    gb.configure_column(col, filter="agTextColumnFilter", floatingFilter=False)
        gb.configure_grid_options(
            domLayout="normal",
            suppressMenuHide=False,
            columnMenu="legacy",
        )
        gb.configure_side_bar(filters_panel=False, columns_panel=False)
        go = gb.build()
        go["suppressCsvExport"] = True
        if "defaultColDef" not in go:
            go["defaultColDef"] = {}
        go["defaultColDef"]["filter"] = True
        go["defaultColDef"]["floatingFilter"] = False
        go["defaultColDef"]["suppressHeaderMenuButton"] = False
        go["defaultColDef"]["suppressHeaderFilterButton"] = False
        if "floatingFiltersHeight" in go:
            del go["floatingFiltersHeight"]
        _column_defs = [c for c in (go.get("columnDefs") or []) if c.get("field") != "_has_opportunity"]
        go["columnDefs"] = _column_defs
        for cdef in _column_defs:
            cdef["filter"] = True
            cdef["floatingFilter"] = False
            cdef["suppressHeaderFilterButton"] = False
            if cdef.get("type") == []:
                cdef.pop("type", None)
        if status_col and JsCode:
            go["getRowStyle"] = _status_get_row_style_js(status_col)
        _update_mode = (GridUpdateMode.FILTERING_CHANGED | GridUpdateMode.SORTING_CHANGED) if GridUpdateMode else None
        _data_mode = DataReturnMode.FILTERED_AND_SORTED if DataReturnMode else None
        _grid_kw = dict(update_mode=_update_mode, data_return_mode=_data_mode) if (_update_mode and _data_mode) else {}
        grid_response = AgGrid(
            df_display,
            gridOptions=go,
            use_container_width=True,
            height=700,
            theme="streamlit",
            show_toolbar=True,
            show_search=True,
            show_download_button=False,
            enable_enterprise_modules=True,
            allow_unsafe_jscode=True,
            key=f"master_kitchens_grid_{key_suffix}",
            **_grid_kw,
        )
        _total_count = len(rows_shown) if rows_shown else 0
        _displayed_count = _total_count
        if grid_response and grid_response.get("data") is not None:
            _displayed_count = len(grid_response["data"])
        if rows_shown:
            _row_count_placeholder.caption(
                f"**{_displayed_count}** rows shown (out of **{_total_count}** total)"
            )
            if allow_download:
                _rows_to_export = grid_response.get("data") if (grid_response and grid_response.get("data") is not None) else rows_shown
                _render_export_button(_rows_to_export, f"{tab_id}_filtered", key=f"export_{key_suffix}_{tab_id}_grid")
    else:
        st.dataframe(df_display, use_container_width=True, hide_index=True, height=700)
        if rows_shown:
            _total_count = len(rows_shown)
            _row_count_placeholder.caption(
                f"**{_total_count}** rows shown (out of **{_total_count}** total)"
            )
            if allow_download:
                _render_export_button(rows_shown, f"{tab_id}_filtered", key=f"export_{key_suffix}_{tab_id}_df")
    # CSV download disabled app-wide (no Download CSV button)


def main():
    st.set_page_config(page_title="KSA Kitchens Tracker", layout="wide", initial_sidebar_state="collapsed")
    init_db()

    # Identity: prefer verified (Streamlit OIDC st.user) when available; never trust URL params for access
    _streamlit_user = getattr(st, "user", None)
    _verified_email = None
    if _streamlit_user and getattr(_streamlit_user, "is_logged_in", False) and getattr(_streamlit_user, "email", None):
        _verified_email = (_streamlit_user.email or "").strip()
        if _verified_email:
            st.session_state["user_display_name"] = _verified_email
    # Do NOT pre-fill from URL (?email= etc.) — that would allow anyone to impersonate by link

    # One-time fetch from Salesforce (direct report IDs) when Superset store is empty, so data is available without manual refresh.
    if not st.session_state.get("auto_refresh_done"):
        st.session_state["auto_refresh_done"] = True
        has_superset = False
        if data_store_mod:
            try:
                df = data_store_mod.read_dataset(getattr(data_store_mod, "MASTER_KITCHENS_LIVE", "master_kitchens_live"))
                has_superset = df is not None and not df.empty
            except Exception:
                pass
        if not has_superset:
            ok, _ = _refresh_from_salesforce()
            if ok:
                st.session_state["data_source"] = "salesforce"
                set_last_refresh("salesforce")
            else:
                ok, _ = _refresh_from_online_sheet()
                if ok:
                    st.session_state["data_source"] = "gsheet"
                    set_last_refresh("gsheet")
            if ok:
                _rerun()

    # Theme: light (default) or dark mode — applied based on sidebar toggle
    _dark = st.session_state.get("dark_mode", False)
    if _dark:
        st.markdown("""
        <style>
        .stApp { background: #0F172A; font-family: sans-serif; font-size: 0.8125rem !important; }
        header[data-testid="stHeader"] { background: #1E293B !important; border-bottom: 1px solid #334155; }
        header[data-testid="stHeader"] * { color: #F1F5F9 !important; }
        section[data-testid="stSidebar"] { background: #1E293B; border-right: 4px solid #0F766E; }
        section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] .stCaption { color: #E2E8F0 !important; }
        section[data-testid="stSidebar"] input { background: #334155 !important; color: #F1F5F9 !important; border-color: #475569 !important; }
        h1 { background: #0F766E !important; color: white !important; font-weight: 700 !important; padding: 20px 28px !important; margin: 0 0 1.5rem 0 !important; border-radius: 0 10px 10px 0 !important; }
        .header-top-bar + div h1, .header-brand-title { background: transparent !important; color: inherit !important; padding: 0 !important; margin: 0 !important; border-radius: 0 !important; }
        h2, h3, p, span, label { color: #E2E8F0 !important; }
        .stCaption { color: #94A3B8 !important; }
        .stTabs [data-baseweb="tab-list"] { background: #1E293B; padding: 8px; border-radius: 10px; overflow-x: auto !important; overflow-y: hidden !important; flex-wrap: nowrap !important; -webkit-overflow-scrolling: touch; scrollbar-width: thin; }
        .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { height: 10px; }
        .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-thumb { background: #475569; border-radius: 5px; }
        .stTabs [data-baseweb="tab"] { color: #94A3B8 !important; flex-shrink: 0; }
        .stTabs [aria-selected="true"] { background: #0F766E !important; color: white !important; }
        .stTabs [aria-selected="true"] span { color: white !important; }
        .stButton > button[kind="primary"] { background: #0F766E !important; color: white !important; border: none !important; }
        .streamlit-expanderHeader { background: #334155 !important; color: #E2E8F0 !important; border-left: 4px solid #0F766E; }
        .stTextInput input, .stSelectbox > div { background: #334155 !important; color: #F1F5F9 !important; border: 1px solid #475569 !important; }
        .stDataFrame { border-radius: 8px; border: 1px solid #475569; background: #1E293B !important; }
        .stDataFrame thead th { background: #334155 !important; color: #F1F5F9 !important; border-bottom: 2px solid #0F766E !important; }
        .stDataFrame tbody td { background: #1E293B !important; color: #E2E8F0 !important; }
        [data-testid="stMetricValue"] { color: #F1F5F9 !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] { font-size: 0.8rem !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
        [data-testid="stMetricLabel"] { color: #94A3B8 !important; }
        div[data-testid="stVerticalBlock"] > div { color: #E2E8F0; }
        .section-title-banner { background: #0f766e !important; color: white !important; }
        </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <style>
        .stApp { background: #FAFBFC; font-family: sans-serif; font-size: 0.8125rem !important; }
        header[data-testid="stHeader"] { background: #F1F3F4 !important; border-bottom: 1px solid #E2E8F0; }
        header[data-testid="stHeader"] * { color: #1E293B !important; }
        section[data-testid="stSidebar"] { background: #FFFFFF; border-right: 4px solid #0F766E; }
        section[data-testid="stSidebar"] .stMarkdown { color: #1E293B !important; font-weight: 600 !important; }
        h1 { background: #0F766E !important; color: white !important; font-weight: 700 !important; padding: 20px 28px !important; margin: 0 0 1.5rem 0 !important; border-radius: 0 10px 10px 0 !important; }
        .header-top-bar + div h1, .header-brand-title { background: transparent !important; color: inherit !important; padding: 0 !important; margin: 0 !important; border-radius: 0 !important; }
        h2, h3 { color: #1E293B !important; font-weight: 600 !important; }
        .stTabs [data-baseweb="tab-list"] { gap: 8px; background: #F1F5F9; padding: 8px; border-radius: 10px; overflow-x: auto !important; overflow-y: hidden !important; flex-wrap: nowrap !important; -webkit-overflow-scrolling: touch; scrollbar-width: thin; }
        .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { height: 10px; }
        .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-thumb { background: #94A3B8; border-radius: 5px; }
        .stTabs [data-baseweb="tab"] { padding: 10px 18px; border-radius: 8px; font-weight: 500; color: #475569; flex-shrink: 0; }
        .stTabs [aria-selected="true"] { background: #0F766E !important; color: white !important; }
        .stTabs [aria-selected="true"] span { color: white !important; }
        .stButton > button[kind="primary"] { background: #0F766E !important; border: none !important; color: white !important; }
        .streamlit-expanderHeader { background: #F8FAFC; border-radius: 8px; border-left: 4px solid #0F766E; }
        .stTextInput input, .stSelectbox > div { border-radius: 6px !important; background: #F8FAFC !important; border: 1px solid #E2E8F0 !important; }
        .stDataFrame { border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #E2E8F0; }
        .stDataFrame thead th { background: #F1F5F9 !important; color: #1E293B !important; font-weight: 600 !important; padding: 10px 12px !important; border-bottom: 2px solid #0F766E !important; }
        .stDataFrame tbody td { padding: 8px 12px !important; }
        [data-testid="stMetricValue"] { color: #1E293B !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] { font-size: 0.8rem !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
        .stCaption { color: #64748B !important; }
        div[data-testid="stVerticalBlock"] > div { padding-top: 0.25rem; }
        </style>
        """, unsafe_allow_html=True)

    # Section nav: tabs only (no dots) — bold text, active tab with teal underline
    st.markdown("""
    <style>
    /* Disable download on all sheets but keep Search and Maximize/Fullscreen in dataframe toolbar */
    [data-testid="stElementToolbar"] { display: flex !important; visibility: visible !important; }
    /* Hide only the 2nd toolbar control (Download CSV) — keep 1st=Search, 3rd=Fullscreen */
    [data-testid="stElementToolbar"] > *:nth-child(2) { display: none !important; visibility: hidden !important; }
    [data-testid="stElementToolbar"] button:nth-of-type(2) { display: none !important; visibility: hidden !important; }
    /* Hide by aria-label/title so download is disabled even if DOM order differs */
    [data-testid="stElementToolbar"] [aria-label*="ownload"],
    [data-testid="stElementToolbar"] [aria-label*=" CSV"],
    [data-testid="stElementToolbar"] [title*="ownload"],
    [data-testid="stElementToolbar"] [title*=" CSV"] { display: none !important; visibility: hidden !important; }
    /* AgGrid toolbar: hide Download as CSV (tooltip title) */
    [title="Download as CSV"],
    button[title="Download as CSV"],
    .ag-toolbar [title*="Download"],
    .ag-toolbar button[title*="CSV"],
    [class*="ag-"] [title="Download as CSV"] { display: none !important; visibility: hidden !important; pointer-events: none !important; }
    /* Toolbar expand/fullscreen: entire sheet fills viewport; scrollbars only when content exceeds screen */
    [data-testid="stFullscreenFrame"],
    [data-testid="stFullscreenFrame"] > div,
    div[data-testid="stAppViewContainer"] [data-testid="stFullscreenFrame"],
    section[data-testid="stFullscreenFrame"],
    .stFullscreenFrame,
    [class*="fullscreenFrame"],
    [class*="FullscreenFrame"] {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        max-width: 100vw !important;
        max-height: 100vh !important;
        z-index: 999999 !important;
        margin: 0 !important;
        padding: 0 !important;
        background: var(--background-color, #0f172a) !important;
        overflow: auto !important;
    }
    [data-testid="stFullscreenFrame"] [data-testid="stDataFrame"],
    [data-testid="stFullscreenFrame"] .glide-data-grid-container,
    [data-testid="stFullscreenFrame"] [class*="dataFrame"],
    .stFullscreenFrame [data-testid="stDataFrame"],
    [class*="fullscreenFrame"] [data-testid="stDataFrame"] {
        width: 100% !important;
        min-height: calc(100vh - 2rem) !important;
        height: calc(100vh - 2rem) !important;
        max-height: none !important;
    }
    /* Remove space above section tabs and shift main content up */
    [data-testid="stAppViewContainer"] > div { padding-top: 0 !important; margin-top: 0 !important; }
    [data-testid="stAppViewContainer"] { padding-top: 0 !important; }
    .block-container { padding-top: 0 !important; }
    [data-testid="stVerticalBlock"] > div:first-child { padding-top: 0 !important; margin-top: 0 !important; }
    /* Slightly smaller base font app-wide */
    .stApp h1 { font-size: 1.2rem !important; }
    .stApp h2 { font-size: 1rem !important; }
    .stApp h3 { font-size: 0.9rem !important; }
    /* Section nav now uses buttons (no radio/dots). Teal banner below. */
    .section-title-banner {
        background: #0f766e !important;
        color: white !important;
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        padding: 10px 20px !important;
        margin: 0 0 0.75rem 0 !important;
        border-radius: 0 0 10px 10px !important;
        box-shadow: 0 1px 3px rgba(15,118,110,0.2);
    }
    /* Hide Streamlit default header (teal bar with page title and link icon) */
    header[data-testid="stHeader"] { display: none !important; }
    /* ========== Header: Tailwind-style single row (px-6 py-3, border-gray-100, shadow-sm) ========== */
    .header-top-bar + div {
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        height: 72px !important;
        min-height: 72px !important;
        max-width: 1600px !important;
        width: 100% !important;
        margin: 0 auto !important;
        padding: clamp(12px, 2vw, 24px) clamp(16px, 3vw, 24px) !important;
        border-bottom: 1px solid #f3f4f6 !important;
        background: #ffffff !important;
        box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05) !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
        box-sizing: border-box !important;
    }
    @media (max-width: 768px) {
        .header-top-bar + div { padding: 12px 16px !important; min-height: auto !important; height: auto !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; height: auto !important; min-height: 56px !important; gap: 12px !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"] { height: auto !important; min-height: 44px !important; }
        .header-top-bar + div [data-testid="stVerticalBlock"] { height: auto !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child { min-width: 0 !important; }
        .header-brand-title { font-size: 0.9375rem !important; }
        .header-status-pill { font-size: 0.75rem !important; }
        .header-divider { margin: 0 8px !important; }
    }
    @media (max-width: 480px) {
        .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child [data-testid="stHorizontalBlock"] { min-width: 0 !important; gap: 8px !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; justify-content: flex-end !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"] { height: auto !important; min-height: 40px !important; }
    }

    .header-top-bar + div [data-testid="stHorizontalBlock"] {
        width: 100% !important;
        display: flex !important;
        justify-content: space-between !important;
        align-items: center !important;
        gap: clamp(12px, 2vw, 16px) !important;
        flex-wrap: wrap !important;
        height: 72px !important;
        min-height: 72px !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] [data-testid="column"] {
        display: flex !important;
        align-items: center !important;
        flex-shrink: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        min-height: 0 !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        height: 72px !important;
        min-height: 72px !important;
    }
    .header-top-bar + div [data-testid="stVerticalBlock"] {
        padding: 0 !important;
        margin: 0 !important;
        min-height: 0 !important;
        height: 72px !important;
        display: flex !important;
        align-items: center !important;
    }
    .header-top-bar + div [data-testid="stVerticalBlock"] > div {
        padding: 0 !important;
        margin: 0 !important;
        min-height: 0 !important;
        max-width: 100% !important;
        display: flex !important;
        align-items: center !important;
    }
    .header-top-bar + div [data-testid="stVerticalBlock"] *,
    .header-top-bar + div [data-testid="stHorizontalBlock"] [data-testid="column"] * {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }

    /* LEFT GROUP: logo + divider + title/status */
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        gap: clamp(16px, 2.5vw, 24px) !important;
        min-width: 0 !important;
        flex: 0 1 auto !important;
        max-width: 100% !important;
        height: 72px !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        gap: clamp(8px, 1.5vw, 12px) !important;
        min-width: 0 !important;
        flex: 0 1 auto !important;
        height: 72px !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child [data-testid="stHorizontalBlock"] [data-testid="column"] {
        display: flex !important;
        align-items: center !important;
        height: 72px !important;
        min-height: 72px !important;
    }
    /* Logo: KitchenPark wordmark — larger so it’s clearly visible (was too small) */
    .header-logo-box {
        width: 24px !important;
        height: 24px !important;
        min-width: 24px !important;
        min-height: 24px !important;
        background: #00766c !important;
        border-radius: 6px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 0.75rem !important;
        line-height: 1 !important;
        margin: 0 !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child [data-testid="column"]:first-child,
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child [data-testid="stVerticalBlock"]:first-child,
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child [data-testid="column"]:first-child div[data-testid="stImage"] {
        width: 24px !important;
        min-width: 24px !important;
        max-width: 24px !important;
        height: 24px !important;
        min-height: 24px !important;
        max-height: 24px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
        background: transparent !important;
        border-radius: 0 !important;
    }
    .header-top-bar + div img {
        max-height: 24px !important;
        max-width: 24px !important;
        width: auto !important;
        height: auto !important;
        object-fit: contain !important;
        object-position: center !important;
        display: block !important;
        margin: 0 !important;
        flex-shrink: 0 !important;
    }
    .header-left-inner {
        display: flex !important;
        align-items: center !important;
        gap: 16px !important;
        flex-wrap: nowrap !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    /* Brand + status: vertical divider then title block */
    .header-brand-status {
        display: flex !important;
        align-items: center !important;
        flex: 1 !important;
        min-width: 0 !important;
        height: 72px !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    .header-divider {
        width: 1px !important;
        min-width: 1px !important;
        height: 32px !important;
        align-self: center !important;
        background: #e5e7eb !important;
        margin: 0 16px !important;
        padding: 0 !important;
    }
    .header-title-block {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-start !important;
        gap: 12px !important;
        flex-wrap: wrap !important;
        line-height: 1 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    .header-status-row { display: flex !important; align-items: center !important; gap: 12px !important; flex-wrap: nowrap !important; margin: 0 !important; }
    .header-brand-title {
        color: #0f172a !important;
        font-size: 1.375rem !important;
        font-weight: 700 !important;
        margin: 0 !important;
        letter-spacing: -0.025em !important;
        line-height: 1 !important;
        display: inline !important;
        background: transparent !important;
        padding: 0 !important;
        border-radius: 0 !important;
    }
    .header-status-pill {
        display: inline-flex !important;
        align-items: center !important;
        gap: 4px !important;
        padding: 4px 10px !important;
        border-radius: 9999px !important;
        font-size: 0.75rem !important;
        font-weight: 700 !important;
        flex-shrink: 0 !important;
        margin: 0 !important;
        line-height: 1 !important;
    }
    .header-status-pill.live { background: #dcfce7 !important; color: #15803d !important; border: none !important; }
    .header-status-pill.delayed { background: #fef9c3 !important; color: #854d0e !important; border: none !important; }
    .header-status-pill.stale { background: #fee2e2 !important; color: #991b1b !important; border: none !important; }
    .header-status-dot { width: 6px !important; height: 6px !important; border-radius: 999px !important; flex-shrink: 0 !important; }
    .header-status-pill.live .header-status-dot { background: #16a34a !important; }
    .header-status-pill.delayed .header-status-dot { background: #eab308 !important; }
    .header-status-pill.stale .header-status-dot { background: #ef4444 !important; }
    .header-updated-muted {
        color: #6b7280 !important;
        font-size: 0.8125rem !important;
        font-weight: 500 !important;
        margin: 0 !important;
        line-height: 1 !important;
        display: inline-flex !important;
        align-items: center !important;
    }

    /* Right: search + help + avatar + Sign out */
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {
        display: flex !important;
        align-items: center !important;
        justify-content: flex-end !important;
        gap: clamp(8px, 1.5vw, 16px) !important;
        flex: 1 1 auto !important;
        min-width: 0 !important;
        height: 72px !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="stHorizontalBlock"] {
        display: flex !important;
        align-items: center !important;
        justify-content: flex-end !important;
        gap: clamp(8px, 1.5vw, 16px) !important;
        flex-wrap: wrap !important;
        height: 72px !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"] {
        flex: 0 0 auto !important;
        display: flex !important;
        align-items: center !important;
        padding: 0 !important;
        margin: 0 !important;
        height: 72px !important;
        min-height: 72px !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"]:nth-child(2) {
        border-left: 1px solid #f3f4f6 !important;
        border-right: 1px solid #f3f4f6 !important;
        padding-left: 16px !important;
        padding-right: 16px !important;
        margin-right: 4px !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="stVerticalBlock"] {
        padding: 0 !important;
        margin: 0 !important;
        min-height: 0 !important;
        height: 72px !important;
        display: flex !important;
        align-items: center !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"] > div,
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"] [data-testid="stVerticalBlock"] {
        margin: 0 !important;
        padding: 0 !important;
        display: flex !important;
        align-items: center !important;
        height: 72px !important;
    }
    .header-top-bar + div form,
    .header-top-bar + div [data-testid="stVerticalBlock"] > div > div {
        margin: 0 !important;
        padding: 0 !important;
    }
    .header-top-bar + div label { margin: 0 !important; padding: 0 !important; min-height: 0 !important; }
    /* Right-group buttons: 40px height, consistent padding (px-3 py-2). Sign out: no wrap, min-width 96px */
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child button {
        height: 40px !important;
        min-height: 40px !important;
        margin: 0 !important;
        padding: 8px 12px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 6px !important;
        font-size: 0.8125rem !important;
        font-weight: 500 !important;
        line-height: 1 !important;
        transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child button:hover {
        background-color: rgba(0,0,0,0.04) !important;
    }
    /* Sign out: px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 */
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"]:last-child button {
        white-space: nowrap !important;
        min-width: 96px !important;
        padding: 8px 16px !important;
        border-radius: 8px !important;
        background: transparent !important;
        border: 1px solid #d1d5db !important;
        color: #374151 !important;
        font-size: 0.875rem !important;
        font-weight: 600 !important;
        transition: background-color 0.15s ease, border-color 0.15s ease !important;
    }
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"]:last-child button:hover {
        background: #f9fafb !important;
        border-color: #d1d5db !important;
        color: #111827 !important;
    }
    .header-icon-btn {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 40px !important;
        height: 40px !important;
        min-width: 40px !important;
        min-height: 40px !important;
        border-radius: 6px !important;
        color: #6b7280 !important;
        text-decoration: none !important;
        flex-shrink: 0 !important;
        border: none !important;
        background: transparent !important;
        cursor: pointer !important;
        margin: 0 !important;
        line-height: 1 !important;
    }
    .header-icon-btn:hover { background: rgba(0,0,0,0.06) !important; color: #111827 !important; }
    .header-help-btn {
        border: 1px solid #e5e7eb !important;
        border-radius: 9999px !important;
        font-weight: 600 !important;
        background: transparent !important;
        color: #6b7280 !important;
    }
    .header-help-btn:hover { background: #f9fafb !important; color: #059669 !important; border-color: #d1d5db !important; }
    /* Header search input: compact */
    .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="column"]:first-child input {
        max-width: 180px !important;
        height: 36px !important;
        min-height: 36px !important;
        font-size: 0.8125rem !important;
    }
    /* Avatar: 36px circle centered in 40px container */
    .header-avatar-chevron {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 4px !important;
        margin: 0 !important;
        width: 40px !important;
        height: 40px !important;
        min-width: 40px !important;
        min-height: 40px !important;
    }
    .header-chevron { color: #6b7280 !important; font-size: 0.7rem !important; margin: 0 !important; line-height: 1 !important; }
    .header-user-avatar {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 36px !important;
        height: 36px !important;
        min-width: 36px !important;
        min-height: 36px !important;
        border-radius: 50% !important;
        background: #064e3b !important;
        color: #ffffff !important;
        font-size: 0.75rem !important;
        font-weight: 700 !important;
        flex-shrink: 0 !important;
        margin: 0 !important;
        line-height: 1 !important;
    }
    .header-user-avatar:hover { transform: scale(1.05) !important; box-shadow: 0 2px 8px rgba(15,118,110,0.35) !important; }
    @media (max-width: 600px) { .header-email-mobile { display: none !important; } }
    </style>
    """, unsafe_allow_html=True)

    # Top bar (replaces sidebar): compact two-row layout
    last_gsheet = get_last_refresh("gsheet")
    if last_gsheet:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(last_gsheet.replace("Z", "+00:00"))
            pulse_display = dt.strftime("%d %b %H:%M")
        except Exception:
            pulse_display = last_gsheet
    else:
        pulse_display = "—"
    if not st.session_state.get("traffic_logged"):
        log_traffic()
        st.session_state["traffic_logged"] = True

    # Restore session from URL params so user is remembered across refresh for SESSION_PERSISTENCE_HOURS
    if not _verified_email:
        _restore_session_from_params()

    # When allowlist is on: require verified sign-in, developer key, or (if fallback allowed) typed email
    def _require_verified_signin() -> bool:
        """If true, only verified sign-in or developer key; no typed email. Set ALLOWLIST_REQUIRE_VERIFIED_SIGNIN=1 for strict."""
        try:
            v = st.secrets.get("ALLOWLIST_REQUIRE_VERIFIED_SIGNIN") or os.environ.get("ALLOWLIST_REQUIRE_VERIFIED_SIGNIN", "")
        except Exception:
            v = os.environ.get("ALLOWLIST_REQUIRE_VERIFIED_SIGNIN", "")
        return str(v).strip().lower() in ("1", "true", "yes")
    if _allowlist_enabled():
        is_developer = _is_developer()
        if not _verified_email and not is_developer:
            if _require_verified_signin():
                st.error("Sign-in required")
                st.markdown("Access is restricted. You must **sign in** with your company account.")
                _st_login = getattr(st, "login", None)
                if callable(_st_login):
                    if st.button("Sign in", type="primary", key="gate_sign_in"):
                        try:
                            _st_login()
                        except Exception:
                            st.error("Sign-in is not configured. Use **Developer access** below (key), or ask the app admin to enable Sign in with Google in Streamlit settings.")
                else:
                    st.info("The app administrator must enable **Sign in with Google** (or OIDC) in Streamlit deployment settings. Until then, only developer key access is possible below.")
                with st.expander("Developer access (key only)", expanded=False):
                    key_in = st.text_input("Key", type="password", key="gate_dev_key", placeholder="Enter developer key")
                    if st.button("Unlock", key="gate_dev_unlock") and key_in.strip() and key_in.strip() == _get_developer_key() and _get_developer_key():
                        st.session_state["developer_unlocked"] = True
                        _rerun()
                st.markdown("---")
                st.info("**You must sign in to use this app.** Use the **Sign in** button above, or unlock with a developer key if you have one.")
                st.stop()
            # Fallback: Sign-in not required — allow typed email (identity not verified)
            _prefill = (st.session_state.get("user_display_name") or "").strip()
            if _prefill:
                pass  # Shown in row 2 below
            else:
                st.text_input("Your email", key="user_display_name", placeholder="e.g. jane@company.com", help="Used for access check and comments. Must be on the allowed list.")
            current_user = (st.session_state.get("user_display_name") or "").strip()
            if not current_user:
                st.warning("Enter your email to continue.")
                st.stop()
            if "@" not in current_user or "." not in current_user.split("@")[-1]:
                st.warning("Enter a valid email address (e.g. name@company.com).")
                st.stop()
        else:
            # Allowlist on and (verified or developer): identity is verified email only, or developer key
            if _verified_email:
                st.session_state["user_display_name"] = _verified_email
                current_user = _verified_email
                pass  # Shown in row 2 below
            else:
                # Developer session: only show name input when no name yet (e.g. after session expired)
                current_user = (st.session_state.get("user_display_name") or "Developer").strip()
                if current_user and current_user != "Developer":
                    pass  # Shown in row 2 below
                else:
                    st.text_input("Your name (for comments)", key="user_display_name", placeholder="e.g. Admin", help="Developer session. Name shown on comments.")
                    current_user = (st.session_state.get("user_display_name") or "Developer").strip()
                pass  # "Developer session (key unlocked)" shown in row 2
    else:
        # Allowlist off: allow typed email for display only (not for access control)
        is_developer = _is_developer()
        if _verified_email:
            current_user = _verified_email
            pass  # Shown in row 2 below
        else:
            _prefill = (st.session_state.get("user_display_name") or "").strip()
            if _prefill:
                pass  # Shown in row 2 below
            else:
                st.text_input("Your name or email", key="user_display_name", placeholder="e.g. jane@company.com", help="Shown on comments and discussions. Not used for access when allowlist is off.")
            current_user = (st.session_state.get("user_display_name") or "").strip()

    # Persist session to URL params so refresh keeps user for SESSION_PERSISTENCE_HOURS
    if current_user:
        _persist_session_to_params(current_user)

    # Helper: list of configured developer identifiers from secrets/env
    def _get_developer_ids_list() -> list[str]:
        try:
            ids = st.secrets.get("DEVELOPER_IDS") or os.environ.get("DEVELOPER_IDS", "")
        except Exception:
            ids = os.environ.get("DEVELOPER_IDS", "")
        return [s.strip().lower() for s in str(ids).split(",") if s.strip()]

    def _developer_section_visible(user: str) -> bool:
        ids_list = _get_developer_ids_list()
        if not ids_list:
            return False
        if _is_developer():
            return True
        return (user or "").strip().lower() in ids_list

    dev_ids = _get_developer_ids_list()
    if dev_ids and (current_user or "").strip().lower() in dev_ids and not is_developer:
        st.session_state["developer_unlocked"] = True
        is_developer = True

    # Single-row top bar: logo + title/status (left) | help, avatar, sign out (right)
    status_label, status_color, status_ts = _data_status_from_pulse(last_gsheet)
    status_class = "live" if "Live" in status_label else ("delayed" if "Delayed" in status_label else "stale")
    updated_ago = _format_updated_ago(last_gsheet)
    st.markdown('<div class="header-top-bar"></div>', unsafe_allow_html=True)
    with st.container():
        left_col, right_col = st.columns([4, 1])  # Left fills space (title + status); right compact for help/avatar/sign out
        with left_col:
            l1, l2 = st.columns([1, 12])
            with l1:
                logo_path = _logo_path()
                if logo_path:
                    st.image(str(logo_path), use_container_width=True)
                else:
                    st.markdown('<div class="header-logo-box">K</div>', unsafe_allow_html=True)
            with l2:
                st.markdown(
                    f'<div class="header-brand-status">'
                    f'<div class="header-divider"></div>'
                    f'<div class="header-title-block">'
                    f'<h1 class="header-brand-title">KSA Kitchens Tracker</h1>'
                    f'<div class="header-status-row">'
                    f'<span class="header-status-pill {status_class}">'
                    f'<span class="header-status-dot"></span> {status_label.replace(" ", " ")}</span>'
                    f'<span class="header-updated-muted">{updated_ago}</span>'
                    f'</div></div></div>',
                    unsafe_allow_html=True,
                )
        with right_col:
            r1, r2, r3 = st.columns([1, 1, 1])
            with r1:
                st.markdown(
                    '<a href="mailto:maysam.abukashabeh@cloudkitchens.com" class="header-icon-btn header-help-btn" title="Help">?</a>',
                    unsafe_allow_html=True,
                )
            with r2:
                initials = "".join((c[0] for c in (current_user or "?").split("@")[0].split(".")[:2]))[:2].upper() if current_user else "?"
                st.markdown(
                    f'<div class="header-avatar-chevron" title="{current_user or ""}">'
                    f'<span class="header-user-avatar">{initials}</span>'
                    f'<span class="header-chevron">▼</span></div>',
                    unsafe_allow_html=True,
                )
            with r3:
                if st.button("Sign out", key="header_sign_out", help="Sign out"):
                    if "user_display_name" in st.session_state:
                        del st.session_state["user_display_name"]
                    st.session_state["developer_unlocked"] = False
                    _clear_session_params()
                    _rerun()
    st.markdown(
        '<div class="header-bottom-line" style="height:1px;background:rgba(0,0,0,0.06);margin:0 16px;max-width:1600px;margin-left:auto;margin-right:auto;"></div>',
        unsafe_allow_html=True,
    )
    # In-page search: highlight matches (query from header_search_query)
    _search_q = (st.session_state.get("header_search_query") or "").strip()
    if _search_q:
        _search_escaped = html.escape(_search_q, quote=True)
        st.markdown(
            f'<div id="app-search-query" data-query="{_search_escaped}"></div>'
            '<style>.app-search-highlight{background:#fef08a;border-radius:2px;}.app-search-current{background:#facc15 !important;}</style>'
            r'''
            <script>
            (function(){
                function runSearch() {
                    var el = document.getElementById("app-search-query");
                    if (!el) return;
                    var q = (el.getAttribute("data-query") || "").trim();
                    if (!q) return;
                    var container = document.querySelector("[data-testid=\"stAppViewContainer\"]") || document.body;
                    var regex = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
                    var toReplace = [];
                    var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
                        acceptNode: function(n) {
                            var p = n.parentNode;
                            if (!p || p.nodeName === "SCRIPT" || p.nodeName === "STYLE" || p.nodeName === "NOSCRIPT") return NodeFilter.FILTER_REJECT;
                            if (p.closest && p.closest("script, style, noscript")) return NodeFilter.FILTER_REJECT;
                            return NodeFilter.FILTER_ACCEPT;
                        }
                    }, false);
                    var textNode;
                    while (textNode = walker.nextNode()) {
                        var text = textNode.textContent;
                        if (!regex.test(text)) continue;
                        toReplace.push({ node: textNode, text: text });
                    }
                    var marks = [];
                    toReplace.forEach(function(item) {
                        var textNode = item.node;
                        var text = item.text;
                        regex.lastIndex = 0;
                        var parent = textNode.parentNode;
                        if (!parent || parent.classList && parent.classList.contains("app-search-highlight")) return;
                        var frag = document.createDocumentFragment();
                        var idx = 0;
                        var m;
                        regex.lastIndex = 0;
                        while ((m = regex.exec(text)) !== null) {
                            if (m.index > idx) frag.appendChild(document.createTextNode(text.slice(idx, m.index)));
                            var mark = document.createElement("mark");
                            mark.className = "app-search-highlight";
                            mark.textContent = m[0];
                            marks.push(mark);
                            frag.appendChild(mark);
                            idx = m.index + m[0].length;
                        }
                        if (idx < text.length) frag.appendChild(document.createTextNode(text.slice(idx)));
                        parent.replaceChild(frag, textNode);
                    });
                    var prevBar = document.getElementById("app-search-bar");
                    if (prevBar) prevBar.remove();
                    var bar = document.createElement("div");
                    bar.id = "app-search-bar";
                    bar.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:9999;background:#111;color:#fff;padding:8px 12px;border-radius:8px;font-size:13px;display:flex;align-items:center;gap:8px;box-shadow:0 4px 12px rgba(0,0,0,0.3);";
                    if (marks.length === 0) {
                        bar.innerHTML = "<span id=\"app-search-status\">No matches</span>";
                    } else {
                        bar.innerHTML = "<span id=\"app-search-status\">1 of " + marks.length + "</span><button type=\"button\" id=\"app-search-prev\">Prev</button><button type=\"button\" id=\"app-search-next\">Next</button>";
                    }
                    document.body.appendChild(bar);
                    var cur = 0;
                    function updateStatus() {
                        var status = document.getElementById("app-search-status");
                        if (status) status.textContent = marks.length === 0 ? "No matches" : (cur + 1) + " of " + marks.length;
                    }
                    function goTo(i) {
                        if (marks.length === 0) return;
                        cur = (i + marks.length) % marks.length;
                        marks.forEach(function(m){ m.classList.remove("app-search-current"); });
                        marks[cur].classList.add("app-search-current");
                        marks[cur].scrollIntoView({ behavior: "smooth", block: "center" });
                        updateStatus();
                    }
                    if (marks.length > 0) {
                        document.getElementById("app-search-prev").onclick = function(){ goTo(cur - 1); };
                        document.getElementById("app-search-next").onclick = function(){ goTo(cur + 1); };
                        goTo(0);
                    }
                }
                setTimeout(runSearch, 600);
            })();
            </script>''',
            unsafe_allow_html=True,
        )
    # Access control: when allowlist is on, identity is already verified (or developer); just check allowlist membership
    if _allowlist_enabled() and not _is_developer():
        if not current_user:
            st.warning("No identity available. Sign in or use developer key.")
            st.stop()
        if not is_user_allowed(current_user):
            st.error("Access restricted. Your account is not on the authorized list.")
            st.caption("Contact [Maysam on Slack](https://urbankitchens.slack.com/team/U0A9Q0NJ9KJ) to be added.")
            st.stop()

    # RBAC: resolve role and build sidebar sections.
    if not _allowlist_enabled() or _is_developer():
        user_role = "super_user"
    else:
        id_lower = (current_user or "").strip().lower() if current_user else ""
        # 1) SUPER_USER_EMAILS in secrets = reliable way to grant Dashboard
        super_emails = _get_super_user_emails()
        # 2) DEVELOPER_IDS in secrets = same list can grant super_user (Dashboard) when signed in (no key needed)
        try:
            dev_ids_set = set(_get_developer_ids_list())
        except Exception:
            dev_ids_set = set()
        if id_lower and (id_lower in super_emails or id_lower in dev_ids_set):
            user_role = "super_user"
        else:
            secrets_roles = _get_secrets_roles()
            # 2) [allowed_user_roles] dict in secrets
            if id_lower and secrets_roles and id_lower in secrets_roles:
                r = (secrets_roles.get(id_lower) or "").strip().lower()
                if r in ("manager_viewer", "super_user"):
                    user_role = r
                else:
                    user_role = auth.get_user_role(
                        current_user,
                        is_developer=False,
                        list_allowed_with_roles=list_allowed_users,
                        allowlist_ids_from_secrets=_allowlist_ids_from_secrets,
                        secrets_roles=secrets_roles,
                    ) if auth else "associate_viewer"
                    user_role = user_role if user_role else "associate_viewer"
            elif auth:
                user_role = auth.get_user_role(
                    current_user,
                    is_developer=False,
                    list_allowed_with_roles=list_allowed_users,
                    allowlist_ids_from_secrets=_allowlist_ids_from_secrets,
                    secrets_roles=secrets_roles,
                )
                if user_role is None:
                    user_role = "associate_viewer"
            else:
                user_role = "associate_viewer"
    st.session_state["user_role"] = user_role
    can_export = _can_user_export(current_user, is_developer=_is_developer())
    st.session_state["can_export"] = can_export

    # Product shape: section navigation by role (Admin tab removed)
    if _is_developer() or user_role == "super_user" or user_role == "manager_viewer":
        section_options = ["Kitchen Master Data", "Dashboard", "Discussions"]
    else:
        section_options = ["Kitchen Master Data", "Discussions"]
    # Ensure Admin never appears (defensive)
    section_options = [s for s in section_options if s != "Admin / Data Health"]
    if not section_options:
        section_options = ["Kitchen Master Data", "Discussions"]
    # Website-style layout: section navigation as tabs
    if "section_radio" not in st.session_state:
        st.session_state["section_radio"] = section_options[0]
    section = st.session_state["section_radio"]
    # Ensure current value is in options (e.g. after role change or Search tab removed)
    if section not in section_options:
        section = section_options[0]
        st.session_state["section_radio"] = section

    # Tab row: one button per section (selected = primary, rest = secondary)
    tab_cols = st.columns(len(section_options))
    for i, opt in enumerate(section_options):
        with tab_cols[i]:
            is_selected = opt == section
            if st.button(
                opt,
                key=f"section_tab_{i}_{opt.replace(' ', '_')}",
                type="primary" if is_selected else "secondary",
                use_container_width=True,
            ):
                st.session_state["section_radio"] = opt
                _rerun()

    # Master Kitchens: prefer persisted Superset store; else legacy Kitchens/generic_tab
    if section == "Kitchen Master Data":
        _show_refresh_btn = _is_developer() or user_role == "super_user"
        superset_rows, superset_meta = _get_superset_master_kitchens()
        if superset_rows is not None:
            last_refresh = (superset_meta or {}).get("last_refresh_ts_utc")
            if _superset_stale_warning(superset_meta or {}):
                st.warning("Last refresh is older than 30 minutes or last run failed. Data may be stale.")
            st.caption("Filter kitchen details and view your report.")
            chosen_label = "Master Kitchens (Live)"
            source_id = "superset"
            rows = superset_rows
            source_options = []
            is_other_sheet = False
        else:
            # BigQuery Master Kitchens: cache in session_state; refresh every 3 minutes
            import time
            _bq_cache_key = "bq_master_kitchens_rows"
            _bq_ts_key = "bq_master_kitchens_fetched_at"
            _bq_refresh_interval_sec = 180  # 3 minutes
            now_sec = time.time()
            cached_rows = st.session_state.get(_bq_cache_key)
            fetched_at = st.session_state.get(_bq_ts_key) or 0
            if cached_rows is not None and (now_sec - fetched_at) < _bq_refresh_interval_sec:
                bq_rows = cached_rows
                bq_error = None
            else:
                bq_rows, bq_error = _fetch_bigquery_master_kitchens()
                if bq_rows is not None:
                    st.session_state[_bq_cache_key] = bq_rows
                    st.session_state[_bq_ts_key] = now_sec
                    bq_error = None
            if bq_rows is not None:
                _mins_ago = (now_sec - st.session_state.get(_bq_ts_key, 0)) / 60.0
                # Check if GSheet also has data; default source without showing UI (refresh/source moved to Admin / Data Health)
                sources = _master_kitchens_sources()
                gsheet_tab_options = [s[0] for s in sources]
                source_ids_gsheet = {s[0]: s[1] for s in sources}
                both_sources_available = bool(gsheet_tab_options)
                _src_key = "master_kitchens_data_source"
                if both_sources_available:
                    if _src_key not in st.session_state:
                        st.session_state[_src_key] = "bigquery" if bq_rows is not None else "gsheet"
                else:
                    st.session_state[_src_key] = "bigquery"
                use_bq = st.session_state.get(_src_key) == "bigquery"
                if use_bq:
                    st.caption(f"Filter kitchen details and view your report. **BigQuery source** — refreshes every 3 min. Last refresh: {_mins_ago:.1f} min ago.")
                    chosen_label = "Master Kitchens (BigQuery)"
                    source_id = "bigquery"
                    rows = bq_rows
                    source_options = []
                    is_other_sheet = False
                else:
                    # User chose Google Sheet; show sheet selector (multi-select: one or multiple facilities/sheets)
                    first_tab = next((t for t in gsheet_tab_options if str(t).strip().lower() != "aqiq"), gsheet_tab_options[0])
                    _sel_key = "master_sheets_selection"
                    # Use default only when key not yet set (let widget own session state to avoid Streamlit warning)
                    _initial = st.session_state.get(_sel_key) if _sel_key in st.session_state else [first_tab]
                    if not isinstance(_initial, list):
                        _initial = [_initial] if _initial else [first_tab]
                    _default = _initial if set(_initial) <= set(gsheet_tab_options) else [first_tab]
                    chosen_labels = st.multiselect("**Facility** — select one or multiple facilities (sheets) to view", options=gsheet_tab_options, default=_default, key=_sel_key, placeholder="Select facilities")
                    if not chosen_labels:
                        chosen_labels = [first_tab]
                    chosen_labels = [t for t in chosen_labels if t in gsheet_tab_options] or [first_tab]
                    source_id = source_ids_gsheet.get(chosen_labels[0], first_tab)
                    rows = list_generic_tab(source_id, source="gsheet")
                    source_options = gsheet_tab_options
                    source_ids = source_ids_gsheet
                    chosen_label = "Master Kitchens (Google Sheet)"
                    is_other_sheet = True
            else:
                # BigQuery not available — try optional "BQ export" sheet (pipeline/scheduled query → Sheet)
                _bq_export_sheet_id = (getattr(st, "secrets", None) or {}).get("bq_export_sheet_id") or ""
                bq_export_rows, bq_export_error = None, None
                if _bq_export_sheet_id:
                    _export_cache_key = "bq_export_sheet_rows"
                    _export_ts_key = "bq_export_sheet_fetched_at"
                    _export_ttl = 300  # 5 min
                    now_sec = time.time()
                    if (st.session_state.get(_export_ts_key) or 0) + _export_ttl > now_sec and st.session_state.get(_export_cache_key):
                        bq_export_rows = st.session_state[_export_cache_key]
                    else:
                        bq_export_rows, bq_export_error = _fetch_bq_export_sheet()
                        if bq_export_rows:
                            st.session_state[_export_cache_key] = bq_export_rows
                            st.session_state[_export_ts_key] = now_sec
                if bq_export_rows:
                    st.caption("**Master Kitchens (from BQ export sheet)** — Data is pushed to this sheet by your BigQuery pipeline or scheduled query.")
                    chosen_label = "Master Kitchens (from BQ export sheet)"
                    source_id = "bigquery_export_sheet"
                    rows = bq_export_rows
                    source_options = []
                    is_other_sheet = False
                else:
                    pass  # No BQ/export data; config messages and refresh moved to Admin / Data Health
                _bq_cfg = (getattr(st, "secrets", None) or {}).get("bigquery_master_kitchens")
                _has_bq_cfg = _bq_cfg and isinstance(_bq_cfg, dict) and (_bq_cfg.get("project_id") or _bq_cfg.get("query") or _bq_cfg.get("query_file"))
                # Kitchen Master Data: GSheet only, no SF. Show tabs only if GSheet has been refreshed.
                last_refresh = get_last_refresh("gsheet")
                # Auto-refresh when no data or stale (>15 min), no click needed (cooldown 15 min)
                import time
                now_sec = time.time()
                last_run = st.session_state.get("gsheet_auto_refresh_last_run") or 0
                if _gsheet_refresh_is_stale(15) and (now_sec - last_run) >= 900:  # 15 min cooldown
                    st.session_state["gsheet_auto_refresh_last_run"] = now_sec
                    ok, msg = _refresh_from_online_sheet()
                    if ok:
                        set_last_refresh("gsheet")
                        st.session_state["data_source"] = "gsheet"
                        _rerun()
                    last_refresh = get_last_refresh("gsheet")
                # Refresh from Google Sheet moved to Admin / Data Health
                sources = _master_kitchens_sources()
                source_options = [s[0] for s in sources]
                source_ids = {s[0]: s[1] for s in sources}
                if not source_options:
                    st.info("No sheet data yet. Data is refreshed every 15 minutes by the scheduler.")
                    rows = []
                    source_id = None
                    chosen_label = ""
                    is_other_sheet = False
                else:
                    # Sheet selector: multi-select so user can view one or multiple sheets
                    first_tab = next((t for t in source_options if str(t).strip().lower() != "aqiq"), source_options[0])
                    _sel_key = "master_sheets_selection"
                    # Use default only when key not yet set (let widget own session state to avoid Streamlit warning)
                    _initial = st.session_state.get(_sel_key) if _sel_key in st.session_state else [first_tab]
                    if not isinstance(_initial, list):
                        _initial = [_initial] if _initial else [first_tab]
                    _default = _initial if set(_initial) <= set(source_options) else [first_tab]
                    chosen_labels = st.multiselect("**Facility** — select one or multiple facilities (sheets) to view", options=source_options, default=_default, key=_sel_key, placeholder="Select facilities")
                    if not chosen_labels:
                        chosen_labels = [first_tab]
                    chosen_labels = [t for t in chosen_labels if t in source_options] or [first_tab]
                    source_id = source_ids.get(chosen_labels[0], first_tab)
                    rows = list_generic_tab(source_id, source="gsheet")
                    is_other_sheet = True
        # Render: 1 facility = single view; 2+ = combined table (no extra View choice)
        if is_other_sheet and chosen_labels:
            _all_for_map = _all_gsheet_facility_rows_for_map(source_ids, source_options)
            if _all_for_map:
                _render_master_kitchens_map(_all_for_map, map_title="Facilities map")
            _labels_to_use = [t for t in (st.session_state.get("master_sheets_selection") or chosen_labels) if t in (source_options or [])]
            if not _labels_to_use:
                _labels_to_use = chosen_labels[:1]
            _show_combined = len(_labels_to_use) > 1
            if not _show_combined:
                _render_generic_tab(
                    source_ids.get(_labels_to_use[0], _labels_to_use[0]),
                    key_suffix="master_other",
                    is_developer=is_developer,
                    source="gsheet",
                    allow_download=can_export,
                    hide_account_country=True,
                )
            else:
                # Combined view: load every selected sheet and merge into one table
                combined_rows = []
                for label in _labels_to_use:
                    tab_id = source_ids.get(label, label)
                    sheet_rows = list_generic_tab(tab_id, source="gsheet") or []
                    for r in sheet_rows:
                        combined_rows.append({"Sheet": label, **r})
                combined_rows = [r for r in combined_rows if not _is_empty_record(r)]
                if not combined_rows:
                    st.info("No rows in the selected sheets yet. Pick sheets that have data, or check that the refresh has run.")
                else:
                    st.caption(f"**Combined view:** {len(combined_rows):,} rows from **{len(_labels_to_use)}** sheets.")
                    cols_combined = sorted(set().union(*(r.keys() for r in combined_rows if isinstance(r, dict)))) if combined_rows else []
                    if combined_rows and isinstance(combined_rows[0], dict):
                        _df_temp = pd.DataFrame(combined_rows)
                        cols_combined = sorted(_df_temp.columns.tolist())
                    cols_combined = [c for c in cols_combined if not _is_account_country_column(c) and str(c).strip().lower() != "sheet"]
                    rows_shown = combined_rows
                    _row_count_placeholder_combined = st.empty()
                    st.divider()
                    df_combined = pd.DataFrame(rows_shown)
                    _disp_cols = [c for c in df_combined.columns if c in cols_combined]
                    if _disp_cols:
                        df_combined = df_combined[_disp_cols]
                    df_combined["_has_opportunity"] = [_row_has_opportunity_name(r) for r in rows_shown]
                    df_combined = _coerce_numeric_columns(df_combined)
                    status_col_combined = None
                    for c in df_combined.columns:
                        if str(c).strip().lower() in ("status", "status__c"):
                            status_col_combined = c
                            break
                    if _HAS_AGGRI and not df_combined.empty:
                        gb = GridOptionsBuilder.from_dataframe(df_combined)
                        gb.configure_default_column(
                            filter=True,
                            sortable=True,
                            resizable=True,
                            floatingFilter=False,
                            suppressHeaderMenuButton=False,
                            suppressHeaderFilterButton=False,
                            menuTabs=["filterMenuTab", "generalMenuTab", "columnsMenuTab"],
                        )
                        _max_set_combined = 500
                        for col in df_combined.columns:
                            if pd.api.types.is_numeric_dtype(df_combined[col]):
                                gb.configure_column(col, filter="agNumberColumnFilter", floatingFilter=False)
                            elif pd.api.types.is_datetime64_any_dtype(df_combined[col]):
                                gb.configure_column(col, filter="agDateColumnFilter", floatingFilter=False)
                            else:
                                ser = df_combined[col].dropna().astype(str).str.strip()
                                uniq = ser[ser != ""].unique()
                                if len(uniq) <= _max_set_combined:
                                    vals = sorted(uniq.tolist(), key=str)
                                    gb.configure_column(col, filter="agSetColumnFilter", filterParams={"values": vals, "maxDisplayedRows": 500}, floatingFilter=False)
                                else:
                                    gb.configure_column(col, filter="agTextColumnFilter", floatingFilter=False)
                        gb.configure_grid_options(
                            domLayout="normal",
                            suppressMenuHide=False,
                            columnMenu="legacy",
                        )
                        gb.configure_side_bar(filters_panel=False, columns_panel=False)
                        go = gb.build()
                        go["suppressCsvExport"] = True
                        if "defaultColDef" not in go:
                            go["defaultColDef"] = {}
                        go["defaultColDef"]["filter"] = True
                        go["defaultColDef"]["floatingFilter"] = False
                        go["defaultColDef"]["suppressHeaderMenuButton"] = False
                        go["defaultColDef"]["suppressHeaderFilterButton"] = False
                        if "floatingFiltersHeight" in go:
                            del go["floatingFiltersHeight"]
                        _col_defs = [c for c in (go.get("columnDefs") or []) if c.get("field") != "_has_opportunity"]
                        go["columnDefs"] = _col_defs
                        for cdef in _col_defs:
                            cdef["filter"] = True
                            cdef["floatingFilter"] = False
                            cdef["suppressHeaderFilterButton"] = False
                            if cdef.get("type") == []:
                                cdef.pop("type", None)
                        if status_col_combined and JsCode:
                            go["getRowStyle"] = _status_get_row_style_js(status_col_combined)
                        _um = (GridUpdateMode.FILTERING_CHANGED | GridUpdateMode.SORTING_CHANGED) if GridUpdateMode else None
                        _dm = DataReturnMode.FILTERED_AND_SORTED if DataReturnMode else None
                        _kw = dict(update_mode=_um, data_return_mode=_dm) if (_um and _dm) else {}
                        grid_res = AgGrid(
                            df_combined,
                            gridOptions=go,
                            use_container_width=True,
                            height=700,
                            theme="streamlit",
                            show_toolbar=True,
                            show_search=True,
                            show_download_button=False,
                            enable_enterprise_modules=True,
                            allow_unsafe_jscode=True,
                            key="master_kitchens_grid_combined",
                            **_kw,
                        )
                        _total_combined = len(rows_shown) if rows_shown else 0
                        _cnt = _total_combined
                        if grid_res and grid_res.get("data") is not None:
                            _cnt = len(grid_res["data"])
                        if rows_shown:
                            _row_count_placeholder_combined.caption(
                                f"**{_cnt}** rows shown (out of **{_total_combined}** total)"
                            )
                            if can_export:
                                _rows_to_export = grid_res.get("data") if (grid_res and grid_res.get("data") is not None) else rows_shown
                                _render_export_button(_rows_to_export, "master_kitchens_combined_filtered", key="export_master_kitchens_combined")
                    else:
                        st.dataframe(df_combined, use_container_width=True, hide_index=True, column_config={"_has_opportunity": None}, height=700)
                        if rows_shown:
                            _total_combined = len(rows_shown)
                            _row_count_placeholder_combined.caption(
                                f"**{_total_combined}** rows shown (out of **{_total_combined}** total)"
                            )
                            if can_export:
                                _render_export_button(rows_shown, "master_kitchens_combined_filtered", key="export_master_kitchens_combined_df")
        if not rows and not is_other_sheet and chosen_label:
            st.info(f"No rows in **{chosen_label}** yet. Data refreshes automatically every 15 minutes — try again shortly or check the source sheet.")
        elif not is_other_sheet and source_id:
            _render_master_kitchens_map(rows, map_title="Facilities map")
            total = len(rows)
            is_tracker = source_id == "main_tracker"
            # No filter bar: single table like Excel sheet (filter via column filters below)
            use_facility_tabs = False
            rows_filtered = [r for r in rows if not _is_empty_record(r)]
            rows_display = rows_filtered  # used for table; updated by column filters when applied
            st.markdown("---")
            if total > 0 and len(rows_filtered) == 0 and not use_facility_tabs:
                st.info("No data in this source.")
            if rows_filtered and not use_facility_tabs:
                all_cols = list(rows_filtered[0].keys()) if rows_filtered else []
                # Master Kitchens: hide Account Country and Sheet from the sheet
                all_cols = [c for c in all_cols if not _is_account_country_column(c) and str(c).strip().lower() != "sheet"]
                cols_to_show = all_cols
                rows_display = rows_filtered
            if HAS_EXCEL and rows_filtered and not use_facility_tabs:
                display_df = pd.DataFrame(rows_display)[cols_to_show] if cols_to_show else pd.DataFrame(rows_display)
                display_df = display_df.copy()
                display_df["_has_opportunity"] = [_row_has_opportunity_name(r) for r in rows_display]
                display_df = _coerce_numeric_columns(display_df)
                _row_count_placeholder_single = st.empty()
                if _HAS_AGGRI:
                    # AgGrid with header filters; add getRowStyle when Status column exists (same as test that worked)
                    status_col_ag = next((c for c in display_df.columns if str(c).strip().lower() in ("status", "status__c")), None)
                    gb = GridOptionsBuilder.from_dataframe(display_df)
                    gb.configure_default_column(
                        filter=True,
                        sortable=True,
                        resizable=True,
                        floatingFilter=False,
                        suppressHeaderMenuButton=False,
                        suppressHeaderFilterButton=False,
                        menuTabs=["filterMenuTab", "generalMenuTab", "columnsMenuTab"],
                    )
                    _max_set_master = 500
                    for col in display_df.columns:
                        if pd.api.types.is_numeric_dtype(display_df[col]):
                            gb.configure_column(col, filter="agNumberColumnFilter", floatingFilter=False)
                        elif pd.api.types.is_datetime64_any_dtype(display_df[col]):
                            gb.configure_column(col, filter="agDateColumnFilter", floatingFilter=False)
                        else:
                            ser = display_df[col].dropna().astype(str).str.strip()
                            uniq = ser[ser != ""].unique()
                            if len(uniq) <= _max_set_master:
                                vals = sorted(uniq.tolist(), key=str)
                                gb.configure_column(col, filter="agSetColumnFilter", filterParams={"values": vals, "maxDisplayedRows": 500}, floatingFilter=False)
                            else:
                                gb.configure_column(col, filter="agTextColumnFilter", floatingFilter=False)
                    gb.configure_grid_options(
                        domLayout="normal",
                        suppressMenuHide=False,
                        columnMenu="legacy",
                    )
                    gb.configure_side_bar(filters_panel=False, columns_panel=False)
                    go = gb.build()
                    go["suppressCsvExport"] = True
                    if "defaultColDef" not in go:
                        go["defaultColDef"] = {}
                    go["defaultColDef"]["filter"] = True
                    go["defaultColDef"]["floatingFilter"] = False
                    go["defaultColDef"]["suppressHeaderMenuButton"] = False
                    go["defaultColDef"]["suppressHeaderFilterButton"] = False
                    if "floatingFiltersHeight" in go:
                        del go["floatingFiltersHeight"]
                    _col_defs_m = [c for c in (go.get("columnDefs") or []) if c.get("field") != "_has_opportunity"]
                    go["columnDefs"] = _col_defs_m
                    for cdef in _col_defs_m:
                        cdef["filter"] = True
                        cdef["floatingFilter"] = False
                        cdef["suppressHeaderFilterButton"] = False
                        if cdef.get("type") == []:
                            cdef.pop("type", None)
                    if status_col_ag and JsCode:
                        go["getRowStyle"] = _status_get_row_style_js(status_col_ag)
                    _um_m = (GridUpdateMode.FILTERING_CHANGED | GridUpdateMode.SORTING_CHANGED) if GridUpdateMode else None
                    _dm_m = DataReturnMode.FILTERED_AND_SORTED if DataReturnMode else None
                    _kw_m = dict(update_mode=_um_m, data_return_mode=_dm_m) if (_um_m and _dm_m) else {}
                    grid_res_m = AgGrid(
                        display_df,
                        gridOptions=go,
                        use_container_width=True,
                        height=700,
                        theme="streamlit",
                        show_toolbar=True,
                        show_search=True,
                        show_download_button=False,
                        enable_enterprise_modules=True,
                        allow_unsafe_jscode=True,
                        key="master_kitchens_grid_single",
                        **_kw_m,
                    )
                    _total_single = len(rows_display) if rows_display else 0
                    _cnt_m = _total_single
                    if grid_res_m and grid_res_m.get("data") is not None:
                        _cnt_m = len(grid_res_m["data"])
                    if rows_display is not None:
                        _row_count_placeholder_single.caption(
                            f"**{_cnt_m}** rows shown (out of **{_total_single}** total)"
                        )
                        if can_export:
                            _rows_to_export = grid_res_m.get("data") if (grid_res_m and grid_res_m.get("data") is not None) else rows_display
                            _render_export_button(_rows_to_export, "master_kitchens_filtered", key="export_master_kitchens_single")
                else:
                    display_df["_has_opportunity"] = [_row_has_opportunity_name(r) for r in rows_display]
                    _sc = {"Occupied": "#FEE2E2", "Sold": "#FEE2E2", "Vacant": "#D1FAE5", "Churning": "#FDE68A"}
                    _ns = "#B22222"
                    status_col_m = next((c for c in display_df.columns if str(c).strip().lower() in ("status", "status__c")), None)
                    if status_col_m and not display_df.empty:
                        def _row_bg_m(row):
                            v = (str(row[status_col_m]) if row[status_col_m] is not None else "").strip()
                            low = v.lower()
                            if not v or low in ("no status", "n/a", "na", "—", "-", "blocked"):
                                return [f"background-color: {_ns}; color: white"] * len(row)
                            key = "Vacant" if (low == "vacant" or (low.startswith("vacant") and "occupied" not in low and "sold" not in low and "churning" not in low)) else "Churning" if low == "churning" else "Occupied" if low == "occupied" else "Sold" if low == "sold" else None
                            bg = _sc.get(key, "") if key else _sc.get(v, "")
                            if key == "Vacant" and bg:
                                has_opp = row.get("_has_opportunity", False)
                                if has_opp:
                                    bg = _sc.get("Occupied", bg)
                            return [f"background-color: {bg}" if bg else ""] * len(row)
                        display_df = display_df.style.apply(_row_bg_m, axis=1)
                    st.dataframe(display_df, use_container_width=True, hide_index=True, column_config={"_has_opportunity": None}, height=700)
                    if rows_display is not None:
                        _total_single = len(rows_display)
                        _row_count_placeholder_single.caption(
                            f"**{_total_single}** rows shown (out of **{_total_single}** total)"
                        )
                        if can_export:
                            _render_export_button(rows_display, "master_kitchens_filtered", key="export_master_kitchens_single_df")
            elif rows_filtered and not use_facility_tabs:
                _show = rows_display if rows_filtered else []
                for r in _show[:100]:
                    st.json({k: r[k] for k in (cols_to_show or r.keys()) if k in r} if (cols_to_show and set(cols_to_show) != set(r.keys())) else r)
                if len(_show) > 100:
                    st.caption(f"… and {len(_show) - 100} more.")
            if HAS_EXCEL and rows_filtered and len(rows_filtered) > 0 and not use_facility_tabs:
                st.markdown("---")
                st.subheader("Pivot view")
                st.caption("Slice your data by rows and columns.")
                df = pd.DataFrame(rows_display)
                cols = [c for c in df.columns if df[c].notna().any()]
                cols = [c for c in cols if not _is_account_country_column(c) and str(c).strip().lower() != "sheet"]
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
                    pv_row = st.selectbox("Rows", row_opts, key="master_pivot_row")
                    pv_col = st.selectbox("Columns", col_opts, key="master_pivot_col")
                    pv_agg = st.selectbox("Value", agg_opts, key="master_pivot_agg")
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
                                pivot["Total"] = pivot.sum(axis=1)
                                pivot.loc["Total", :] = pivot.sum(axis=0)
                            st.dataframe(pivot, use_container_width=True, hide_index=False)
                            try:
                                import plotly.graph_objects as go
                                fig = go.Figure(data=go.Heatmap(
                                    z=pivot.values.tolist(),
                                    x=[str(x) for x in pivot.columns],
                                    y=[str(y) for y in pivot.index],
                                    colorscale="Teal",
                                ))
                                fig.update_layout(title="Pivot heatmap", xaxis_title="", yaxis_title="", height=400)
                                st.plotly_chart(fig, use_container_width=True)
                            except Exception:
                                pass
                        except Exception:
                            pass

    # Dashboard: management view (section_options already restricts who sees the button)
    elif section == "Dashboard":
        superset_rows, superset_meta = _get_superset_master_kitchens()
        if superset_rows is not None:
            if _superset_stale_warning(superset_meta or {}):
                st.warning("Last refresh is older than 30 minutes or last run failed.")
            rows_kitchens = superset_rows
        else:
            # Always use GSheet for Dashboard so regular users see data (session data_source may default to salesforce)
            rows_kitchens = list_generic_tab("Kitchens", source="gsheet") or list_generic_tab("Master Kitchens list", source="gsheet") or []
        today_str = date.today().isoformat()
        if snapshot_mod and rows_kitchens:
            if not snapshot_mod.snapshot_exists_for_date(today_str):
                try:
                    snapshot_mod.write_daily_snapshot(rows_kitchens, today_str)
                except Exception:
                    pass
        # Ensure Account Country for filtering (Kitchens / Master list may use County or other keys)
        rows_kitchens = _ensure_account_country_in_kitchens(rows_kitchens)
        # Enrich with go-live / is_live: facility CSV (data/sa_bh_facility_go_live.csv) + optional BigQuery
        bq_go_live = _fetch_bigquery_go_live()
        csv_go_live = _fetch_facility_go_live_csv()
        go_live_rows = (csv_go_live or []) + (bq_go_live or [])
        if go_live_rows:
            rows_kitchens = _merge_go_live_into_kitchens(rows_kitchens, go_live_rows)
        has_go_live = bool(go_live_rows)
        def _country(r):
            """Country for a row (Account Country, County, or other country header)."""
            for k in ("Account Country", "County", "Account__r.Country__c", "Country__c", "Country", "account country", "county"):
                v = r.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            return ""
        def _facility(r):
            for k in ("Account Name", "Account__r.Name", "facility", "Facility"):
                v = r.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            return ""
        # —— Country, Facility, and Live status filters (drive all dashboard data) ——
        unique_countries = sorted({(_country(r) or "(No country)") for r in rows_kitchens})
        if not unique_countries:
            unique_countries = ["(No country)"]
        n_filter_cols = 3 if has_go_live else 2
        filter_cols = st.columns(n_filter_cols)
        with filter_cols[0]:
            selected_country = st.selectbox(
                "Country",
                options=["All"] + unique_countries,
                key="dashboard_country",
                help="Filter all dashboard metrics and tables by country.",
            )
        with filter_cols[1]:
            # Facilities depend on selected country
            if selected_country and selected_country != "All":
                rows_for_facilities = [r for r in rows_kitchens if (_country(r) or "(No country)") == selected_country]
            else:
                rows_for_facilities = rows_kitchens
            facility_set = sorted({(_facility(r) or "(No facility)") for r in rows_for_facilities})
            facility_set = [f for f in facility_set if f]
            if not facility_set:
                facility_set = ["(No facility)"]
            selected_facility = st.selectbox(
                "Facility",
                options=["All"] + facility_set,
                key="dashboard_facility",
                help="Filter by facility within the selected country.",
            )
        selected_live = "All"
        if has_go_live and n_filter_cols >= 3:
            with filter_cols[2]:
                selected_live = st.selectbox(
                    "Live status",
                    options=["All", "Live", "Not live"],
                    key="dashboard_live",
                    help="Filter by kitchens marked live vs not live (from BigQuery go-live data).",
                )
        # Apply filters
        if selected_country and selected_country != "All":
            rows_kitchens = [r for r in rows_kitchens if (_country(r) or "(No country)") == selected_country]
        if selected_facility and selected_facility != "All":
            rows_kitchens = [r for r in rows_kitchens if (_facility(r) or "(No facility)") == selected_facility]
        if selected_live == "Live":
            rows_kitchens = [r for r in rows_kitchens if r.get("Is Live") is True]
        elif selected_live == "Not live":
            rows_kitchens = [r for r in rows_kitchens if r.get("Is Live") is False]
        cap = f"Showing data for **{selected_country or 'All'}** · **{selected_facility or 'All'}** facilities ({len(rows_kitchens):,} kitchens)."
        if has_go_live:
            n_live = sum(1 for r in rows_kitchens if r.get("Is Live") is True)
            n_not = sum(1 for r in rows_kitchens if r.get("Is Live") is False)
            cap += f" **{n_live}** live, **{n_not}** not live (go-live from facility list / BigQuery)."
        st.caption(cap)
        st.divider()
        def _s(r):
            v = None
            for k in ("Status", "Status__c", "status", "Kitchen_Status__c", "state", "Kitchen_Number__c.Status__c"):
                if k in r and r.get(k) is not None and str(r.get(k)).strip():
                    v = str(r.get(k)).strip()
                    break
            if v is None:
                for k, val in (r or {}).items():
                    if val is not None and str(k).strip().lower() == "status":
                        v = str(val).strip()
                        if v:
                            break
            return v or ""
        def _status_normalized(r):
            """Return one of Vacant, Churning, Occupied, Sold for counting (case-insensitive match)."""
            raw = _s(r)
            if not raw:
                return ""
            low = raw.strip().lower()
            if low == "vacant" or (low.startswith("vacant") and "occupied" not in low and "sold" not in low and "churning" not in low):
                return "Vacant"
            if low == "churning":
                return "Churning"
            if low == "occupied":
                return "Occupied"
            if low == "sold":
                return "Sold"
            return raw  # keep as-is so it won't match and will fall into "other" (not counted)
        def _kitchen_name(r):
            for k in ("Kitchen Number", "Name", "Kitchen_Number_ID_18__c", "Kitchen Number Name", "Kitchen_Number__c.Name"):
                v = r.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            return ""
        def _churn_date(r):
            """Return churn date normalized to YYYY-MM-DD for sorting; raw for display may be DD/MM/YYYY."""
            for k in ("Churn Date", "Churn_Date__c", "Opportunity__r.Churn_Date__c", "churn_date"):
                v = r.get(k)
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                try:
                    if "T" in s:
                        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
                    else:
                        raw = s[:10]
                        try:
                            d = datetime.strptime(raw, "%Y-%m-%d")
                        except Exception:
                            d = datetime.strptime(raw, "%d/%m/%Y")
                    return d.strftime("%Y-%m-%d")
                except Exception:
                    pass
            return ""
        def _opportunity_name(r):
            # Explicit keys first (SF / report / BigQuery column names)
            for k in ("Opportunity Name", "Opportunity__r.Name", "Opportunity_Name__c", "Opportunity Name__c", "Opportunity name", "opportunity_name", "opportunity name", "Opportunity_Name"):
                v = r.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            # Fallback: any key containing "opportunity" (e.g. from GSheet headers)
            for k, v in (r or {}).items():
                if v is not None and str(v).strip() and "opportunity" in str(k).lower():
                    return str(v).strip()
            return ""
        def _is_vacant_approved_deal(r):
            """True if status is Vacant and Opportunity Name column has any value (approved deal = vacant with an opportunity)."""
            if _status_normalized(r) != "Vacant":
                return False
            return bool(_opportunity_name(r).strip())
        vacant = sum(1 for r in rows_kitchens if _status_normalized(r) == "Vacant")
        churning = sum(1 for r in rows_kitchens if _status_normalized(r) == "Churning")
        occupied = sum(1 for r in rows_kitchens if _status_normalized(r) == "Occupied")
        sold = sum(1 for r in rows_kitchens if _status_normalized(r) == "Sold")
        vacant_approved_deal = sum(1 for r in rows_kitchens if _is_vacant_approved_deal(r))
        total = vacant + churning + occupied + sold
        occ_pct = ((occupied + churning) / total * 100) if total else 0  # Occupancy = Churning + Occupied
        sold_rate_pct = ((occupied + sold + churning + vacant_approved_deal) / total * 100) if total else 0  # Sales view: includes Vacant with Opportunity name "approved deal"
        vac_pct = (vacant / total * 100) if total else 0
        churn_pct = (churning / total * 100) if total else 0
        sold_pct = (sold / total * 100) if total else 0
        def _pct_fmt(x: float) -> str:
            """Format percentage so 0 is always visible as 0.0%."""
            return f"{x:.1f}%" if x == x else "0.0%"
        DASHBOARD_CURRENCY = "USD"
        def _curr(v) -> str:
            """Format as currency in USD (e.g. $1,234,567 or $0)."""
            if v is None or v == "": return "—"
            try: return f"${float(v):,.0f}"
            except (TypeError, ValueError): return "—"
        def _parse_price(v):
            if v is None: return None
            try:
                s = str(v).replace(",", "").strip()
                if s:
                    return float(s)
            except (ValueError, TypeError):
                pass
            return None
        _LIST_KEYS = ("List Price", "List_Price__c", "Sell_Price__c", "Kitchen_Number__c.Sell_Price__c")
        def _get_list(r):
            for k in _LIST_KEYS:
                p = _parse_price(r.get(k))
                if p is not None:
                    return p
            return None
        def _price(r):
            """List price only (for tables etc.)."""
            return _get_list(r)
        def _price_vacant_row(r):
            """Vacant: List price only. Returns (value, missing_price)."""
            p = _get_list(r)
            return (p or 0.0, p is None)
        def _price_occupied_row(r):
            """Occupied: List price only. Returns (value, missing_price)."""
            p = _get_list(r)
            return (p or 0.0, p is None)
        def _price_churn_row(r):
            """Churning: List price only. Returns (value, missing_price)."""
            p = _get_list(r)
            return (p or 0.0, p is None)
        def _price_for_value(r, status: str):
            """All metrics use List price only."""
            return _get_list(r)
        # Card totals + missing-price counts (numbers unchanged from before)
        vacant_rows = [r for r in rows_kitchens if _status_normalized(r) == "Vacant"]
        churning_rows_for_val = [r for r in rows_kitchens if _status_normalized(r) == "Churning"]
        occupied_rows = [r for r in rows_kitchens if _status_normalized(r) == "Occupied"]
        sum_vacant_val = 0.0
        n_vacant_missing = 0
        for r in vacant_rows:
            v, missing = _price_vacant_row(r)
            sum_vacant_val += v
            if missing:
                n_vacant_missing += 1
        sum_churning_val = 0.0
        n_churn_missing = 0
        for r in churning_rows_for_val:
            v, missing = _price_churn_row(r)
            sum_churning_val += v
            if missing:
                n_churn_missing += 1
        sum_occupied_val = 0.0
        n_occupied_missing = 0
        for r in occupied_rows:
            v, missing = _price_occupied_row(r)
            sum_occupied_val += v
            if missing:
                n_occupied_missing += 1
        has_cost = sum_vacant_val > 0 or sum_churning_val > 0 or sum_occupied_val > 0
        # —— Dashboard styling: summary bar, scorecard, value cards ——
        st.markdown("""
        <style>
        .dashboard-summary { background: linear-gradient(135deg, #f0fdf4 0%, #ecfeff 100%); border-radius: 12px; padding: 14px 18px; margin-bottom: 1rem; border-left: 4px solid #0F766E; font-size: 0.875rem; }
        div[data-testid="stMetric"] { background: linear-gradient(145deg, #f0fdf4 0%, #e0f2fe 100%); border-radius: 10px; padding: 12px 14px; border-left: 4px solid #0F766E; transition: transform 0.15s ease, box-shadow 0.15s ease; }
        div[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(15,118,110,0.2); }
        .dashboard-value-row { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }
        .dashboard-value-card { flex: 1; min-width: 160px; border-radius: 12px; padding: 16px 18px; transition: transform 0.2s ease, box-shadow 0.2s ease; cursor: default; }
        .dashboard-value-card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,0.12); }
        .dashboard-value-card.vacant { background: linear-gradient(145deg, #D1FAE5 0%, #A7F3D0 100%); border-left: 4px solid #059669; }
        .dashboard-value-card.churning { background: linear-gradient(145deg, #FFEDD5 0%, #FED7AA 100%); border-left: 4px solid #EA580C; }
        .dashboard-value-card.occupied { background: linear-gradient(145deg, #FEE2E2 0%, #FECACA 100%); border-left: 4px solid #DC2626; }
        .dashboard-value-card .label { font-size: 0.8rem; color: #374151; font-weight: 600; margin-bottom: 4px; }
        .dashboard-value-card .value { font-size: 1.2rem; font-weight: 700; color: #111827; }
        .dashboard-value-card .currency-hint { font-size: 0.7rem; color: #6B7280; margin-top: 4px; }
        .dashboard-facility-card { background: linear-gradient(145deg, #f0fdf4 0%, #e0f2fe 100%); border-radius: 12px; padding: 16px; margin: 1rem 0; border-left: 4px solid #0F766E; overflow-x: auto; }
        .dashboard-facility-table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; }
        .dashboard-facility-table th { background: rgba(15,118,110,0.15); color: #134e4a; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #0F766E; }
        .dashboard-facility-table td { padding: 8px 12px; border-bottom: 1px solid rgba(15,118,110,0.2); }
        .dashboard-facility-table tr:hover { background: rgba(255,255,255,0.7); }
        .dashboard-facility-table tr:nth-child(even) { background: rgba(255,255,255,0.4); }
        .dashboard-facility-table tr:nth-child(even):hover { background: rgba(255,255,255,0.8); }
        .dashboard-facility-summary { background: linear-gradient(135deg, #ecfeff 0%, #f0fdf4 100%); border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; border-left: 4px solid #0d9488; font-size: 0.8125rem; }
        .dashboard-churn-card { background: linear-gradient(145deg, #FFEDD5 0%, #FED7AA 100%); border-radius: 12px; padding: 16px; margin: 1rem 0; border-left: 4px solid #EA580C; overflow-x: auto; }
        .dashboard-churn-table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; }
        .dashboard-churn-table th { background: rgba(234,88,12,0.2); color: #9a3412; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #EA580C; }
        .dashboard-churn-table td { padding: 8px 12px; border-bottom: 1px solid rgba(234,88,12,0.25); }
        .dashboard-churn-table tr:hover { background: rgba(255,255,255,0.6); }
        .dashboard-churn-table tr:nth-child(even) { background: rgba(255,255,255,0.35); }
        .dashboard-churn-table tr:nth-child(even):hover { background: rgba(255,255,255,0.75); }
        .dashboard-churn-metric { background: linear-gradient(145deg, #FFEDD5 0%, #FED7AA 100%); border-radius: 12px; padding: 16px 18px; margin-bottom: 12px; border-left: 4px solid #EA580C; display: inline-block; min-width: 200px; }
        .dashboard-churn-metric .label { font-size: 0.8rem; color: #9a3412; font-weight: 600; margin-bottom: 4px; }
        .dashboard-churn-metric .value { font-size: 1.2rem; font-weight: 700; color: #111827; }
        .churn-section-panel { background: linear-gradient(180deg, #FFFBEB 0%, #FFF7ED 50%, #FEF3C7 100%); border-radius: 12px; padding: 20px 24px; margin: 16px 0; border-left: 4px solid #EA580C; box-shadow: 0 2px 12px rgba(234,88,12,0.08); }
        .churn-month-card { background: white; border-radius: 10px; padding: 14px 18px; margin: 8px 0; border: 1px solid rgba(234,88,12,0.25); box-shadow: 0 1px 4px rgba(0,0,0,0.06); transition: box-shadow 0.2s ease; }
        .churn-month-card:hover { box-shadow: 0 4px 12px rgba(234,88,12,0.15); }
        .churn-month-card .month-name { font-weight: 700; color: #9a3412; font-size: 0.9rem; margin-bottom: 4px; }
        .churn-month-card .month-stats { font-size: 0.8125rem; color: #374151; }
        div[data-testid="stDataFrame"] { border-radius: 10px; box-shadow: 0 2px 8px rgba(15,118,110,0.08); border: 1px solid rgba(15,118,110,0.2); overflow: hidden; }
        div[data-testid="stDataFrame"]:hover { box-shadow: 0 4px 14px rgba(15,118,110,0.12); }
        </style>
        """, unsafe_allow_html=True)
        glance_label = f"{selected_country or 'All'} at a glance" if (selected_country and selected_country != "All") else "All countries at a glance"
        st.markdown(
            f'<div class="dashboard-summary"><strong>{glance_label}</strong> · {total:,} kitchens · {vacant:,} vacant · {occupied:,} occupied · {sold:,} sold · {vacant_approved_deal:,} approved deal{"s" if vacant_approved_deal != 1 else ""}</div>',
            unsafe_allow_html=True,
        )
        # —— Scorecard (Sales-first: Sold Rate + Ops Occupancy) ——
        st.subheader("Scorecard")
        sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
        with sc1:
            st.metric("Total kitchens", f"{total:,}", help="Sellable only (Vacant+Sold+Occupied+Churning)")
        with sc2:
            st.metric("Sold Rate %", _pct_fmt(sold_rate_pct), help=f"(Occupied + Sold + Churning + Vacant with Opportunity Name) ÷ Total. **{vacant_approved_deal}** Vacant kitchens with Opportunity Name filled are included.")
        with sc3:
            st.metric("Occupancy % (Ops)", _pct_fmt(occ_pct), help="(Occupied + Churning) / Total")
        with sc4:
            st.metric("Vacancy %", _pct_fmt(vac_pct), help="Vacant / Total")
        with sc5:
            st.metric("Churn %", _pct_fmt(churn_pct), help="Churning / Total")
        with sc6:
            st.metric("Sold", f"{sold:,}", help="Closed Won, future access")
        # —— Value: MRR only (no ARR toggle) ——
        mult = 1
        value_label = "MRR"
        if has_cost:
            st.subheader(f"Value — {value_label} ({DASHBOARD_CURRENCY})")
            st.caption(
                "**Vacant** = potential revenue if we fill empty kitchens (List price). "
                "**Scheduled Churn** = revenue we could lose from kitchens that are leaving. "
                "**Occupied** = revenue we have today from filled kitchens. All values use **List price** only."
            )
            vac_display = _curr(sum_vacant_val * mult)
            churn_display = _curr(sum_churning_val * mult)
            occ_display = _curr(sum_occupied_val * mult)
            st.markdown(
                f'<div class="dashboard-value-row">'
                f'<div class="dashboard-value-card vacant" title="Potential monthly revenue if all vacant kitchens were filled (List price only).">'
                f'<div class="label">Vacant {value_label} (opportunity)</div><div class="value">{vac_display}</div><div class="currency-hint">{DASHBOARD_CURRENCY}</div></div>'
                f'<div class="dashboard-value-card churning" title="Monthly revenue from kitchens that are still paying but have a future churn date — revenue at risk.">'
                f'<div class="label">Scheduled Churn RRL</div><div class="value">{churn_display}</div><div class="currency-hint">{DASHBOARD_CURRENCY}</div></div>'
                f'<div class="dashboard-value-card occupied" title="Current monthly revenue from occupied kitchens (today\'s book of business).">'
                f'<div class="label">Occupied {value_label}</div><div class="value">{occ_display}</div><div class="currency-hint">{DASHBOARD_CURRENCY}</div></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            missing_parts = []
            if n_vacant_missing:
                missing_parts.append(f"{n_vacant_missing} Vacant")
            if n_occupied_missing:
                missing_parts.append(f"{n_occupied_missing} Occupied")
            if n_churn_missing:
                missing_parts.append(f"{n_churn_missing} Scheduled Churn")
            if missing_parts:
                st.caption(f"**Data quality:** {', '.join(missing_parts)} kitchen(s) have no List price (included as $0). Review in Kitchen Master Data or source sheet.")
            with st.expander("Value — data quality (QA)", expanded=False):
                st.markdown(
                    f"- **Vacant:** {len(vacant_rows) - n_vacant_missing} of {len(vacant_rows)} have List price; **{n_vacant_missing}** missing."
                )
                st.markdown(
                    f"- **Occupied:** {len(occupied_rows) - n_occupied_missing} of {len(occupied_rows)} have List price; **{n_occupied_missing}** missing."
                )
                st.markdown(
                    f"- **Scheduled Churn:** {len(churning_rows_for_val) - n_churn_missing} of {len(churning_rows_for_val)} have List price; **{n_churn_missing}** missing."
                )
                st.caption("All value calculations use **List price** only.")
        st.markdown("---")
        # —— Facility leaderboard (where to focus: by Vacant MRR or Scheduled Churn RRL) ——
        fac_stats = {}
        for r in rows_kitchens:
            f = _facility(r) or "(No facility)"
            if f not in fac_stats:
                fac_stats[f] = {"vacant": 0, "churning": 0, "occupied": 0, "sold": 0, "vacant_approved_deal": 0, "vacant_mrr": 0.0, "churn_mrr": 0.0}
            s = _status_normalized(r)
            if s == "Vacant":
                fac_stats[f]["vacant"] += 1
                if _is_vacant_approved_deal(r):
                    fac_stats[f]["vacant_approved_deal"] += 1
                fac_stats[f]["vacant_mrr"] += _price_for_value(r, "Vacant") or 0
            elif s == "Churning":
                fac_stats[f]["churning"] += 1
                fac_stats[f]["churn_mrr"] += _price_for_value(r, "Churning") or 0
            elif s == "Occupied":
                fac_stats[f]["occupied"] += 1
            elif s == "Sold":
                fac_stats[f]["sold"] += 1
        if fac_stats:
            with st.expander("**Facilities by opportunity and at-risk revenue** — sort by Vacant MRR or Scheduled Churn RRL, view full table and inventory by facility", expanded=True):
                fac_rows = []
                for f, counts in fac_stats.items():
                    t = counts["vacant"] + counts["churning"] + counts["occupied"] + counts["sold"]
                    if t == 0:
                        continue
                    occ_p = ((counts["occupied"] + counts["churning"]) / t * 100)
                    sold_rate_p = ((counts["occupied"] + counts["sold"] + counts["churning"] + counts.get("vacant_approved_deal", 0)) / t * 100)
                    vac_p = (counts["vacant"] / t * 100)
                    churn_p = (counts["churning"] / t * 100)
                    fac_rows.append({
                        "Facility": f, "Total": t, "Sold Rate %": round(sold_rate_p, 1), "Occupancy %": round(occ_p, 1),
                        "Vacancy %": round(vac_p, 1), "In churn %": round(churn_p, 1),
                        "Vacant": counts["vacant"], "Vacant MRR": round(counts["vacant_mrr"], 0),
                        "Churning": counts["churning"], "Churn RRL": round(counts["churn_mrr"], 0),
                        "Occupied": counts["occupied"], "Sold": counts["sold"],
                    })
                sort_by = st.radio("Sort facilities by", ["Vacant MRR (opportunity)", "Scheduled Churn RRL"], key="facility_sort", horizontal=True)
                if "Churn" in sort_by:
                    fac_rows.sort(key=lambda x: (-x["Churn RRL"], -x["Total"]))
                else:
                    fac_rows.sort(key=lambda x: (-x["Vacant MRR"], -x["Total"]))
                if fac_rows:
                    n_fac = len(fac_rows)
                    top = fac_rows[0]
                    summary_line = f"<strong>{n_fac}</strong> facilities · Top: <strong>{html.escape(top['Facility'])}</strong> — Vacant MRR {_curr(top['Vacant MRR'])} · Scheduled Churn RRL {_curr(top['Churn RRL'])}"
                    st.markdown(f'<div class="dashboard-facility-summary">{summary_line}</div>', unsafe_allow_html=True)
                    # Sortable table (clean, eye-catching)
                    display_cols = ["Facility", "Total", "Sold Rate %", "Occupancy %", "Vacant", "Vacant MRR", "Churning", "Churn RRL"]
                    df_fac = pd.DataFrame(fac_rows)[[c for c in display_cols if c in (fac_rows[0].keys() if fac_rows else [])]]
                    st.dataframe(
                        df_fac,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Vacant MRR": st.column_config.NumberColumn(format="$%.0f"),
                            "Churn RRL": st.column_config.NumberColumn(format="$%.0f"),
                        },
                    )
                    facility_options = ["(Select a facility)"] + [r["Facility"] for r in fac_rows]
                    selected_facility = st.selectbox("Select facility for inventory detail", facility_options, key="dashboard_selected_facility")
                    # —— Inventory to sell: kitchen-level view for selected facility ——
                    if selected_facility and selected_facility != "(Select a facility)":
                        st.subheader(f"Inventory — {selected_facility}")
                        facility_rows = [r for r in rows_kitchens if (_facility(r) or "(No facility)") == selected_facility]
                        status_filter = st.multiselect("Status", ["Vacant", "Churning", "Sold", "Occupied"], default=["Vacant", "Churning"], key="inv_status")
                        if status_filter:
                            facility_rows = [r for r in facility_rows if _status_normalized(r) in status_filter]
                        floor_prices = [(_price(r) or 0) for r in facility_rows]
                        if floor_prices:
                            p33 = sorted(floor_prices)[max(0, len(floor_prices) // 3 - 1)] if len(floor_prices) >= 3 else 0
                            p66 = sorted(floor_prices)[max(0, 2 * len(floor_prices) // 3 - 1)] if len(floor_prices) >= 3 else max(floor_prices)
                        else:
                            p33 = p66 = 0
                        price_band = st.radio("Price band", ["All", "Low", "Mid", "High"], key="inv_price_band", horizontal=True)
                        def _band(r):
                            p = _price(r) or 0
                            if p <= p33: return "Low"
                            if p <= p66: return "Mid"
                            return "High"
                        if price_band != "All":
                            facility_rows = [r for r in facility_rows if _band(r) == price_band]
                        if facility_rows:
                            inv_data = []
                            for r in facility_rows:
                                st_val = _status_normalized(r) or "Vacant"
                                floor_val = _price_for_value(r, "Occupied") or _price(r) or 0
                                list_val = _price_for_value(r, "Vacant") or _price(r) or 0
                                row_inv = {
                                    "Kitchen": _kitchen_name(r) or "—",
                                    "Status": st_val or "—",
                                    "Floor (MRR)": floor_val,
                                    "List (MRR)": list_val,
                                    "Facility": _facility(r) or "—",
                                    "_has_opportunity": _row_has_opportunity_name(r),
                                }
                                if has_go_live:
                                    row_inv["Is Live"] = "Yes" if r.get("Is Live") is True else ("No" if r.get("Is Live") is False else "—")
                                    row_inv["Go Live Date"] = (r.get("Go Live Date") or "").strip() or "—"
                                inv_data.append(row_inv)
                            df_inv = pd.DataFrame(inv_data)
                            # Status color coding (same as Kitchen Master Data): Vacant=green, Churning=amber, Occupied/Sold=red, no status/Blocked=dark red
                            _status_colors = {"Occupied": "#FEE2E2", "Sold": "#FEE2E2", "Vacant": "#D1FAE5", "Churning": "#FDE68A"}
                            _no_status_bg = "#B22222"
                            if "Status" in df_inv.columns and not df_inv.empty:
                                def _inv_row_bg(row):
                                    v = (str(row["Status"]) if row["Status"] is not None else "").strip()
                                    low = v.lower()
                                    if not v or low in ("no status", "n/a", "na", "—", "-", "blocked"):
                                        return [f"background-color: {_no_status_bg}; color: white"] * len(row)
                                    key = "Vacant" if (low == "vacant" or (low.startswith("vacant") and "occupied" not in low and "sold" not in low and "churning" not in low)) else "Churning" if low == "churning" else "Occupied" if low == "occupied" else "Sold" if low == "sold" else None
                                    bg = _status_colors.get(key, "") if key else _status_colors.get(v, "")
                                    if key == "Vacant" and bg:
                                        has_opp = row.get("_has_opportunity", False)
                                        if has_opp:
                                            bg = _status_colors.get("Occupied", bg)
                                    return [f"background-color: {bg}" if bg else ""] * len(row)
                                df_inv = df_inv.style.apply(_inv_row_bg, axis=1)
                            st.dataframe(df_inv, use_container_width=True, hide_index=True, column_config={"Floor (MRR)": st.column_config.NumberColumn(format="%.0f"), "List (MRR)": st.column_config.NumberColumn(format="%.0f"), "_has_opportunity": None})
                        else:
                            st.caption("No kitchens match the filters.")
                    # Bar chart and focus list
                    try:
                        import plotly.express as px
                        top_for_bar = fac_rows[:15]
                        if top_for_bar:
                            df_bar = pd.DataFrame(top_for_bar)
                            if "Churn" in sort_by:
                                y_col, y_label, title = "Churn RRL", "Scheduled Churn RRL", "Scheduled Churn RRL by facility (top 15)"
                                color_scale = ["#FFEDD5", "#FED7AA", "#EA580C", "#C2410C"]  # amber for Churn
                            else:
                                y_col, y_label, title = "Vacant MRR", "Vacant MRR", "Vacant MRR by facility (top 15)"
                                color_scale = ["#D1FAE5", "#A7F3D0", "#059669", "#047857"]  # green for Vacant
                            fig_bar = px.bar(df_bar, x="Facility", y=y_col, title=title, color=y_col, color_continuous_scale=color_scale)
                            fig_bar.update_layout(
                                xaxis_title="Facility", yaxis_title=y_label, xaxis_tickangle=-45, height=380,
                                template="plotly_white", margin=dict(t=50, b=100), font=dict(size=12),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                coloraxis=dict(colorbar=dict(title=y_label)),
                            )
                            st.plotly_chart(fig_bar, use_container_width=True)
                    except Exception:
                        pass
                    with st.expander("Focus: top facilities by vacant kitchens", expanded=False):
                        for r in fac_rows[:5]:
                            if r["Vacant"] > 0:
                                st.markdown(f"- **{r['Facility']}**: {r['Vacant']} vacant · {_curr(r['Vacant MRR'])} MRR · {r['Occupancy %']}% occupancy")
        # —— Churn & at-risk block (expandable) ——
        churning_rows = [r for r in rows_kitchens if _status_normalized(r) == "Churning"]
        if churning_rows:
            def _churn_date_sort_key(r):
                s = _churn_date(r)
                if not s:
                    return "9999-99-99"
                return s
            churning_rows = sorted(churning_rows, key=_churn_date_sort_key)
            churn_mrr_total = sum((_price_for_value(r, "Churning") or 0) for r in churning_rows)
            st.markdown("---")
            with st.expander("**Churn & at-risk — kitchens with a future churn date (revenue to save)** — monthly revenue we could lose; list sorted by churn date soonest first", expanded=True):
                st.caption("These kitchens are still active (paying) today but have a **future churn date** (notice given). The total is **monthly revenue at risk** if we don’t renew or backfill. Table: each kitchen, MRR at risk, churn date (soonest first).")
                st.markdown(
                    f'<div class="dashboard-churn-metric" title="Total monthly revenue at risk from all kitchens with status Churning (future churn date).">'
                    f'<div class="label">Scheduled Churn RRL</div><div class="value">{_curr(churn_mrr_total)}</div><div class="currency-hint" style="font-size:0.75rem;color:#9a3412;margin-top:4px;">Monthly revenue at risk</div></div>',
                    unsafe_allow_html=True,
                )
                def _churn_date_display(iso_date: str) -> str:
                    """Format YYYY-MM-DD as DD/MM/YYYY for display."""
                    if not iso_date or iso_date == "—":
                        return iso_date or "—"
                    try:
                        d = datetime.strptime(iso_date[:10], "%Y-%m-%d")
                        return d.strftime("%d/%m/%Y")
                    except Exception:
                        return iso_date
                # Monthly view: group by churn month (YYYY-MM) and compute count + RRL per month
                month_to_rows: dict[str, list] = {}
                for r in churning_rows:
                    iso = _churn_date(r)
                    if iso and len(iso) >= 7:
                        ym = iso[:7]  # YYYY-MM
                        month_to_rows.setdefault(ym, []).append(r)
                month_labels = []
                for ym in sorted(month_to_rows.keys()):
                    try:
                        d = datetime.strptime(ym + "-01", "%Y-%m-%d")
                        month_labels.append((ym, d.strftime("%b %Y")))  # e.g. Feb 2026
                    except Exception:
                        month_labels.append((ym, ym))
                st.markdown('<div class="churn-section-panel">', unsafe_allow_html=True)
                # Monthly filter
                filter_options = ["All"] + [label for _, label in month_labels]
                selected_month_label = st.selectbox("Filter by churn month", options=filter_options, key="churn_month_filter", help="Show only kitchens churning in the selected month, or All.")
                if selected_month_label and selected_month_label != "All":
                    ym_selected = next((ym for ym, label in month_labels if label == selected_month_label), None)
                    if ym_selected:
                        churning_rows_filtered = month_to_rows.get(ym_selected, [])
                    else:
                        churning_rows_filtered = churning_rows
                else:
                    churning_rows_filtered = churning_rows
                # Monthly view: cards + table
                st.subheader("By month")
                monthly_summary = []
                for ym, label in month_labels:
                    rows_m = month_to_rows.get(ym, [])
                    mrr = sum((_price_for_value(r, "Churning") or _price(r) or 0) for r in rows_m)
                    monthly_summary.append({"Month": label, "Kitchens": len(rows_m), "Scheduled Churn RRL (USD)": round(mrr, 0)})
                if monthly_summary:
                    # Month cards row (eye-catching)
                    n_cards = len(monthly_summary)
                    n_cols = min(n_cards, 6)
                    cols = st.columns(n_cols)
                    for i, row in enumerate(monthly_summary[:12]):  # cap at 12 months
                        if i > 0 and i % 6 == 0:
                            cols = st.columns(n_cols)
                        with cols[i % n_cols]:
                            st.markdown(
                                f'<div class="churn-month-card">'
                                f'<div class="month-name">{html.escape(row["Month"])}</div>'
                                f'<div class="month-stats">{row["Kitchens"]} kitchens · {_curr(row["Scheduled Churn RRL (USD)"])} RRL</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                    if n_cards > 6:
                        st.caption(f"All {n_cards} months in table below.")
                    st.markdown("")
                    df_monthly = pd.DataFrame(monthly_summary)
                    st.dataframe(
                        df_monthly,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Scheduled Churn RRL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                        },
                    )
                st.markdown("---")
                st.caption("**Table:** Kitchen · Account/Facility · Churn date · Scheduled Churn RRL (USD) · Status = Churning. Click column headers to sort.")
                churn_table_rows = [
                    {
                        "Kitchen": _kitchen_name(r) or "—",
                        "Account / Facility": _facility(r) or "—",
                        "Churn date": _churn_date_display(_churn_date(r)),
                        "Scheduled Churn RRL (USD)": _price_for_value(r, "Churning") or _price(r) or 0,
                        "Status": "Churning",
                    }
                    for r in churning_rows_filtered
                ]
                df_churn = pd.DataFrame(churn_table_rows)
                st.dataframe(
                    df_churn,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Scheduled Churn RRL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                    },
                )
                st.markdown('</div>', unsafe_allow_html=True)
        # —— How these numbers are calculated ——
        st.markdown("---")
        with st.expander("How these numbers are calculated", expanded=False):
            st.markdown("""
**Status (what each kitchen state means)**  
- **Vacant** — No occupancy; available to sell.  
- **Sold** — Closed Won, access date in the future.  
- **Occupied** — Closed Won, access date in the past (paying kitchen).  
- **Churning** — Closed Won with a future churn date (still operating, can resell).

---

**Counts (whole numbers)**  
- **Total kitchens** = Vacant + Occupied + Sold + Churning (only rows with one of these four statuses are included; other statuses are excluded).  
- **Vacant** = count of kitchens with status Vacant  
- **Occupied** = count of kitchens with status Occupied  
- **Sold** = count of kitchens with status Sold  
- **Churning** = count of kitchens with status Churning  

---

**Rates (percentages)**  
- **Sold Rate %** = (Occupied + Sold + Churning + Vacant with Opportunity Name) ÷ Total × 100. **Vacant with Opportunity Name** = Vacant kitchens that have any value in the Opportunity Name column (counted in Sold Rate only).  
- **Occupancy %** = (Occupied + Churning) ÷ Total × 100  
- **Vacancy %** = Vacant ÷ Total × 100  
- **Churn %** = Churning ÷ Total × 100  

---

**Value (MRR)**  
- **MRR** = monthly recurring revenue (per kitchen price, summed).  
- Values are shown as MRR only.“Annualized (ARR)” on).

**Which price is used**  
- All value calculations (Vacant MRR, Scheduled Churn RRL, Occupied MRR, facility leaderboard, churn table) use **List price** only (List Price / Sell_Price__c). If List price is missing → $0 and counted in QA.

**Data quality**  
- Under the value cards we show how many kitchens have no List price (included as $0).  
- Use **Value — data quality (QA)** expander for counts per metric.
            """)
        return

    # Discussions: app-wide comments and questions (with replies)
    if section == "Discussions":
        st.caption("Ask questions or add comments. You can reply to any post and use **@name** to mention someone.")
        slack_url = _get_slack_discussion_url()
        if slack_url:
            st.markdown(f"Continue the conversation in Slack: [Open channel]({slack_url})")
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
                    reply_message = st.text_area("Your reply", key="reply_message", placeholder="Type your reply… Use @name to mention someone.", height=80)
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
            message = st.text_area("Comment or question", key="discussion_message", placeholder="Type your message… Use @name to mention someone (e.g. @Jane).", height=120)
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
                    st.markdown(_render_discussion_message(p.get("message", "")))
                    if st.button("Reply", key=f"reply_btn_{p.get('id')}"):
                        st.session_state["discussion_reply_to_id"] = p.get("id")
                        _rerun()
                    for r in replies_by_parent.get(p.get("id"), []):
                        st.markdown(
                            f"↳ **{r.get('author') or 'Anonymous'}** · {r.get('created_at', '')[:19].replace('T', ' ')}"
                        )
                        st.markdown(_render_discussion_message(r.get("message", "")))
                    st.divider()
        return

    # —— Super-user tools (Prompt 7, 8, 9) ——
    if section == "Currency Converter":
        st.title("Currency Converter")
        st.caption("Convert amounts between SAR and USD. Rates stored in app.")
        if fx_mod:
            fx_mod.ensure_default_rates()
            amount = st.number_input("Amount", value=1.0, min_value=0.0, step=0.01, key="fx_amount")
            from_c = st.selectbox("From", ["SAR", "USD"], key="fx_from")
            to_c = st.selectbox("To", ["SAR", "USD"], key="fx_to")
            result = fx_mod.convert(amount, from_c, to_c)
            if result is not None:
                st.metric("Result", f"{result:,.2f} {to_c}")
            else:
                st.caption("Rate not found. Add rates in fx_rates table.")
        else:
            st.info("FX module not loaded (app/fx.py).")
        return

    if section == "Inflation Calculator":
        st.title("Inflation Calculator")
        st.caption("Recommendation only — does not write to pricing tables.")
        go_live = st.date_input("Facility go-live date", value=None, key="infl_go_live")
        base_price = st.number_input("Base price", value=1000.0, min_value=0.0, step=50.0, key="infl_base")
        inflation_pct = st.number_input("Annual inflation %", value=3.0, min_value=0.0, max_value=20.0, step=0.5, key="infl_pct") / 100.0
        if go_live:
            years = (date.today() - go_live).days / 365.25
            factor = (1 + inflation_pct) ** years
            recommended = round(base_price * factor, 2)
            st.metric("Years since go-live", f"{years:.1f}")
            st.metric("Inflation factor", f"{factor:.2f}")
            st.metric("Recommended adjusted price", f"{recommended:,.2f}")
        else:
            st.caption("Select go-live date to see recommendation.")
        return

    if section == "Price Multipliers":
        st.title("Price Multipliers")
        st.caption("By facility. Suggested multiplier editable (0.5–3.0).")
        if multipliers_mod:
            rows_m = multipliers_mod.list_multipliers()
            if not rows_m:
                st.info("No facility multipliers yet. Add rows in the table below or seed from Kitchens facilities.")
                facility_id = st.text_input("Facility ID", key="pm_fid")
                facility_name = st.text_input("Facility name", key="pm_fname")
                current_m = st.number_input("Current multiplier", value=1.0, min_value=0.5, max_value=3.0, step=0.1, key="pm_cur")
                suggested_m = st.number_input("Suggested multiplier", value=1.0, min_value=0.5, max_value=3.0, step=0.1, key="pm_sug")
                if st.button("Add row", key="pm_add"):
                    if multipliers_mod.upsert_multiplier(facility_id, facility_name, current_m, suggested_m, current_user):
                        st.success("Added.")
                        _rerun()
                    else:
                        st.error("Invalid (e.g. multiplier out of range).")
            else:
                if HAS_EXCEL:
                    st.dataframe(pd.DataFrame(rows_m), use_container_width=True, hide_index=True)
                for r in rows_m:
                    with st.expander(f"{r.get('facility_id')} — {r.get('facility_name') or ''}"):
                        sug = st.number_input("Suggested multiplier", value=float(r.get("suggested_multiplier") or 1.0), min_value=0.5, max_value=3.0, step=0.1, key=f"pm_edit_{r.get('facility_id')}")
                        if st.button("Save", key=f"pm_save_{r.get('facility_id')}"):
                            if multipliers_mod.upsert_multiplier(r["facility_id"], r.get("facility_name"), r.get("current_multiplier"), sug, current_user):
                                st.success("Saved.")
                                _rerun()
                buf = io.StringIO()
                w = csv.DictWriter(buf, fieldnames=["facility_id", "facility_name", "current_multiplier", "suggested_multiplier", "updated_by", "updated_at"], extrasaction="ignore")
                w.writeheader()
                w.writerows(rows_m)
                # CSV download disabled app-wide
                # st.download_button("Export CSV", data=buf.getvalue(), file_name="facility_multipliers.csv", mime="text/csv", key="pm_export")
        else:
            st.info("Multipliers module not loaded (app/multipliers.py).")
        return

if __name__ == "__main__":
    main()
