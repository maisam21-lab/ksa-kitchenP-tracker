"""
KSA Kitchens Tracker — web app. Run: streamlit run app/tracker_app.py
All sheet tabs in tool form: view, filter, add/edit, export. Single source of truth.
Accepts CSV or Excel (.xlsx) uploads. Can refresh directly from the online Google Sheet.
"""
import base64
import csv
import html
import io
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import streamlit as st

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
    "Kitchens": "All kitchen details. View, filter, and download.",
    "Master Kitchens list": "Master list of all kitchens. View, filter, and download.",
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
                out[key] = str(v).strip()
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k, v in data.items():
                    key = (str(k).strip() or "").lower()
                    if key and v:
                        out[key] = str(v).strip()
        except json.JSONDecodeError:
            pass
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


# Tab IDs hidden from Kitchen Master Data (users don't see these in the sheet dropdown)
MASTER_KITCHENS_HIDDEN_TABS = {"KSA Facility details", "SF Churn Data"}


def _master_kitchens_other_sheet_ids() -> list[str]:
    """Sheet tab IDs shown in Kitchen Master Data Tab dropdown. Only tabs loaded from GSheet; KSA Facility / SF Churn Data hidden."""
    return [t for t in list_tab_ids_for_source("gsheet") if t not in MASTER_KITCHENS_HIDDEN_TABS]


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


def _render_generic_tab(tab_id, key_suffix="", is_developer=False, source=None, allow_download=True):
    """View/filter/download for a generic tab. When source is set (e.g. 'gsheet'), read only from that source; else use session data_source. allow_download=False hides CSV download (e.g. Kitchen Master Data)."""
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
    is_kitchens_tab = tab_id in ("Kitchens", "Master Kitchens list")
    if tab_id == "Kitchens":
        st.caption("**Main view:** All kitchens under accounts in all countries. Filter by **Account Country** or search in any column to navigate.")
    if tab_id == "Master Kitchens list":
        st.caption("**Master list:** All kitchens. Filter by **Account Country** or search in any column.")
    if tab_id == "SF Churn Data":
        st.caption("To match the live Kitchen Tracker columns, set **sf_tab_queries** → \"SF Churn Data\" to the **same Report ID** as the live churn report. See **docs/SETUP_SF_SECRETS.md**.")
    # For Kitchens / Master Kitchens list: ensure Account Country, labels, column order
    if is_kitchens_tab:
        rows = _ensure_account_country_in_kitchens(rows)
    cols = list(rows[0].keys()) if rows else []
    if is_kitchens_tab:
        rows, cols = _apply_kitchen_labels(rows, cols)
        cols = _kitchens_column_order(cols)
    # Cleaner filtering: one search box + optional single-column filter in expander
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
    # Status color coding (match sheet/dashboard reference): Vacant = light green, Occupied = light red, Sold = light red, Churning = amber, no status/Blocked/NA/empty = dark red
    _status_colors = {"Vacant": "#D1FAE5", "Occupied": "#FEE2E2", "Sold": "#FEE2E2", "Churning": "#FDE68A"}
    _no_status_bg = "#B22222"  # dark red for no status, Blocked, NA, or empty
    df_display = pd.DataFrame(rows_shown)
    status_col = None
    for c in df_display.columns:
        if str(c).strip().lower() in ("status", "status__c"):
            status_col = c
            break
    if status_col and not df_display.empty:
        def _row_bg(row):
            v = (str(row[status_col]) if row[status_col] is not None else "").strip()
            low = v.lower()
            if not v or low in ("no status", "n/a", "na", "—", "-", "blocked"):
                return [f"background-color: {_no_status_bg}; color: white"] * len(row)
            # Normalize to match GSheet status labels (case-insensitive)
            key = None
            if low == "vacant": key = "Vacant"
            elif low == "churning": key = "Churning"
            elif low == "occupied": key = "Occupied"
            elif low == "sold": key = "Sold"
            bg = _status_colors.get(key, "") if key else _status_colors.get(v, "")
            style = f"background-color: {bg}" if bg else ""
            return [style] * len(row)
        styled = df_display.style.apply(_row_bg, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    if allow_download and key_suffix != "master_other":
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
        .stApp { background: #0F172A; font-family: sans-serif; }
        header[data-testid="stHeader"] { background: #1E293B !important; border-bottom: 1px solid #334155; }
        header[data-testid="stHeader"] * { color: #F1F5F9 !important; }
        section[data-testid="stSidebar"] { background: #1E293B; border-right: 4px solid #0F766E; }
        section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] .stCaption { color: #E2E8F0 !important; }
        section[data-testid="stSidebar"] input { background: #334155 !important; color: #F1F5F9 !important; border-color: #475569 !important; }
        h1 { background: #0F766E !important; color: white !important; font-weight: 700 !important; padding: 20px 28px !important; margin: 0 0 1.5rem 0 !important; border-radius: 0 10px 10px 0 !important; }
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
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] { font-size: 0.85rem !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
        [data-testid="stMetricLabel"] { color: #94A3B8 !important; }
        div[data-testid="stVerticalBlock"] > div { color: #E2E8F0; }
        .section-title-banner { background: #0f766e !important; color: white !important; }
        </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <style>
        .stApp { background: #FAFBFC; font-family: sans-serif; }
        header[data-testid="stHeader"] { background: #F1F3F4 !important; border-bottom: 1px solid #E2E8F0; }
        header[data-testid="stHeader"] * { color: #1E293B !important; }
        section[data-testid="stSidebar"] { background: #FFFFFF; border-right: 4px solid #0F766E; }
        section[data-testid="stSidebar"] .stMarkdown { color: #1E293B !important; font-weight: 600 !important; }
        h1 { background: #0F766E !important; color: white !important; font-weight: 700 !important; padding: 20px 28px !important; margin: 0 0 1.5rem 0 !important; border-radius: 0 10px 10px 0 !important; }
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
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] { font-size: 0.85rem !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
        .stCaption { color: #64748B !important; }
        div[data-testid="stVerticalBlock"] > div { padding-top: 0.25rem; }
        </style>
        """, unsafe_allow_html=True)

    # Hide dataframe toolbar (eye, download, search, fullscreen) app-wide
    # Section nav: tabs only (no dots) — bold text, active tab with teal underline
    st.markdown("""
    <style>
    [data-testid="stElementToolbar"] { display: none !important; }
    /* Section nav now uses buttons (no radio/dots). Teal banner below. */
    .section-title-banner {
        background: #0f766e !important;
        color: white !important;
        font-size: 1.75rem !important;
        font-weight: 700 !important;
        padding: 20px 28px !important;
        margin: 0 0 1.5rem 0 !important;
        border-radius: 0 0 10px 10px !important;
        box-shadow: 0 2px 4px rgba(15,118,110,0.2);
    }
    </style>
    """, unsafe_allow_html=True)

    # Sidebar (KitchenPark-style: logo + header)
    logo_path = _logo_path()
    if logo_path:
        st.sidebar.image(str(logo_path), use_container_width=True)
    else:
        st.sidebar.markdown('<span style="color: #2E7D6E; font-size: 1.4rem; font-weight: 700;">KitchenPark</span>', unsafe_allow_html=True)
    st.sidebar.markdown("**KSA Kitchens Tracker**")
    st.sidebar.checkbox("Dark mode", key="dark_mode", help="Switch to dark theme for the entire app")
    # Log this session once (for analytics); show record count — more meaningful than "traffic"
    if not st.session_state.get("traffic_logged"):
        log_traffic()
        st.session_state["traffic_logged"] = True
    # Data pulse: aligned with last GSheet refresh (scheduler runs every 15 min)
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
    st.sidebar.metric("Data pulse", pulse_display, help="Last Google Sheet refresh (scheduler every 15 min)")

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
                st.sidebar.error("Sign-in required")
                st.sidebar.markdown("Access is restricted. You must **sign in** with your company account.")
                _st_login = getattr(st, "login", None)
                if callable(_st_login):
                    if st.sidebar.button("Sign in", type="primary", key="gate_sign_in"):
                        try:
                            _st_login()
                        except Exception:
                            st.sidebar.error("Sign-in is not configured. Use **Developer access** below (key), or ask the app admin to enable Sign in with Google in Streamlit settings.")
                else:
                    st.sidebar.info("The app administrator must enable **Sign in with Google** (or OIDC) in Streamlit deployment settings. Until then, only developer key access is possible below.")
                with st.sidebar.expander("Developer access (key only)", expanded=False):
                    key_in = st.text_input("Key", type="password", key="gate_dev_key", placeholder="Enter developer key")
                    if st.button("Unlock", key="gate_dev_unlock") and key_in.strip() and key_in.strip() == _get_developer_key() and _get_developer_key():
                        st.session_state["developer_unlocked"] = True
                        _rerun()
                st.markdown("---")
                st.info("**You must sign in to use this app.** Use the **Sign in** button in the sidebar, or unlock with a developer key if you have one.")
                st.stop()
            # Fallback: Sign-in not required — allow typed email (identity not verified)
            _prefill = (st.session_state.get("user_display_name") or "").strip()
            if _prefill:
                st.sidebar.caption(f"Signed in as **{_prefill}**")
            else:
                st.sidebar.text_input("Your email", key="user_display_name", placeholder="e.g. jane@company.com", help="Used for access check and comments. Must be on the allowed list.")
            current_user = (st.session_state.get("user_display_name") or "").strip()
            if not current_user:
                st.sidebar.warning("Enter your email to continue.")
                st.stop()
            if "@" not in current_user or "." not in current_user.split("@")[-1]:
                st.sidebar.warning("Enter a valid email address (e.g. name@company.com).")
                st.stop()
        else:
            # Allowlist on and (verified or developer): identity is verified email only, or developer key
            if _verified_email:
                st.session_state["user_display_name"] = _verified_email
                current_user = _verified_email
                st.sidebar.caption(f"Signed in as **{_verified_email}**")
            else:
                st.sidebar.text_input("Your name (for comments)", key="user_display_name", placeholder="e.g. Admin", help="Developer session. Name shown on comments.")
                current_user = (st.session_state.get("user_display_name") or "Developer").strip()
                st.sidebar.caption("Developer session (key unlocked)")
    else:
        # Allowlist off: allow typed email for display only (not for access control)
        is_developer = _is_developer()
        if _verified_email:
            current_user = _verified_email
            st.sidebar.caption(f"Signed in as **{_verified_email}**")
        else:
            _prefill = (st.session_state.get("user_display_name") or "").strip()
            if _prefill:
                st.sidebar.caption(f"Signed in as **{_prefill}**")
            else:
                st.sidebar.text_input("Your name or email", key="user_display_name", placeholder="e.g. jane@company.com", help="Shown on comments and discussions. Not used for access when allowlist is off.")
            current_user = (st.session_state.get("user_display_name") or "").strip()

    # Persist session to URL params so refresh keeps user for SESSION_PERSISTENCE_HOURS
    if current_user:
        _persist_session_to_params(current_user)

    if _allowlist_enabled():
        st.sidebar.caption("Access is limited to allowed users.")
    else:
        st.sidebar.caption("Contact your admin to restrict access to this app.")
    st.sidebar.markdown("---")
    st.sidebar.caption("Developed by **RevOps** team")

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
    # Access control: when allowlist is on, identity is already verified (or developer); just check allowlist membership
    if _allowlist_enabled() and not _is_developer():
        if not current_user:
            st.warning("No identity available. Sign in or use developer key.")
            st.stop()
        if not is_user_allowed(current_user):
            st.error("Access restricted. Your account is not on the authorized list.")
            st.caption("Contact [Maysam on Slack](https://urbankitchens.slack.com/team/U0A9Q0NJ9KJ) to be added.")
            st.stop()

    # RBAC: resolve role and build sidebar sections (Prompt 1 & 2)
    if not _allowlist_enabled() or _is_developer():
        user_role = "super_user"
    elif auth:
        user_role = auth.get_user_role(
            current_user,
            is_developer=_is_developer(),
            list_allowed_with_roles=list_allowed_users,
            allowlist_ids_from_secrets=_allowlist_ids_from_secrets,
            secrets_roles=_get_secrets_roles(),
        )
        if user_role is None:
            user_role = "associate_viewer"
    else:
        user_role = "super_user"
    st.session_state["user_role"] = user_role

    # Product shape (Feb 18): AEs see only three sections. Developers/super_user also see Data (sources/tabs) and Admin.
    if _is_developer() or user_role == "super_user":
        section_options = ["Kitchen Master Data", "Dashboard", "Discussions", "Data", "Search", "Admin / Data Health"]
    else:
        section_options = ["Kitchen Master Data", "Dashboard", "Discussions"]

    # Website-style layout: section navigation as tabs (buttons, no radio dots)
    if "section_radio" not in st.session_state:
        st.session_state["section_radio"] = section_options[0]
    section = st.session_state["section_radio"]
    # Ensure current value is in options (e.g. after role change)
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
    # Teal banner with current section name
    st.markdown(f'<div class="section-title-banner">{section}</div>', unsafe_allow_html=True)

    # Master Kitchens: prefer persisted Superset store; else legacy Kitchens/generic_tab
    if section == "Kitchen Master Data":
        _show_refresh_btn = _is_developer() or user_role == "super_user"
        superset_rows, superset_meta = _get_superset_master_kitchens()
        if superset_rows is not None:
            last_refresh = (superset_meta or {}).get("last_refresh_ts_utc")
            if _superset_stale_warning(superset_meta or {}):
                st.warning("Last refresh is older than 30 minutes or last run failed. Data may be stale.")
            st.caption("Filter kitchen details and download your report.")
            chosen_label = "Master Kitchens (Live)"
            source_id = "superset"
            rows = superset_rows
            source_options = []
            is_other_sheet = False
        else:
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
            if _show_refresh_btn:
                if st.button("Refresh from Google Sheet", key="master_refresh_gsheet"):
                    ok, msg = _refresh_from_online_sheet()
                    if ok:
                        set_last_refresh("gsheet")
                        st.session_state["data_source"] = "gsheet"
                        st.success("Sheets updated. Tabs and data are now from the current Google Sheet.")
                    else:
                        st.error(msg or "Refresh failed.")
                    _rerun()
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
                first_tab = source_options[0]
                # Sheets and facilities in one filter box: Select all / Clear + multiselect for each
                # Use a dedicated key for multiselect so we never write to the widget key after it runs (avoids StreamlitAPIException on Cloud)
                _sel_key = "master_sheets_selection"
                if _sel_key not in st.session_state:
                    st.session_state[_sel_key] = [first_tab]
                _initial_sel = st.session_state.get(_sel_key) or [first_tab]
                if not isinstance(_initial_sel, list):
                    _initial_sel = [_initial_sel] if _initial_sel else [first_tab]
                source_id = source_ids.get((_initial_sel or [first_tab])[0], first_tab)
                rows = list_generic_tab(source_id, source="gsheet")
                cap_col, btn_col = st.columns([3, 1])
                with cap_col:
                    st.caption("Select **one facility** or **multiple facilities** (sheets). One selected → that facility only; multiple selected → combined table with a **Sheet** column.")
                with btn_col:
                    sel_col, clr_col = st.columns(2)
                    with sel_col:
                        if st.button("Select all", key="master_sheets_select_all"):
                            st.session_state[_sel_key] = list(source_options)
                            _rerun()
                    with clr_col:
                        if st.button("Clear", key="master_sheets_clear"):
                            st.session_state[_sel_key] = [first_tab]
                            _rerun()
                chosen_labels = st.multiselect(
                    "Facilities (sheets)",
                    options=source_options,
                    key=_sel_key,
                    help="Select a single facility or multiple facilities. Use **Select all** to add every facility, **Clear** to reset.",
                )
                if not chosen_labels:
                    chosen_labels = [first_tab]
                chosen_labels = [t for t in (chosen_labels or []) if t in source_options] or [first_tab]
                source_id = source_ids.get(chosen_labels[0], first_tab)
                rows = list_generic_tab(source_id, source="gsheet")
                is_other_sheet = True
        # Render: 1 facility = single view; 2+ = combined table (no extra View choice)
        if is_other_sheet and chosen_labels:
            _labels_to_use = [t for t in (st.session_state.get("master_sheets_selection") or chosen_labels) if t in (source_options or [])]
            if not _labels_to_use:
                _labels_to_use = chosen_labels[:1]
            _show_combined = len(_labels_to_use) > 1
            if not _show_combined:
                _render_generic_tab(source_ids.get(_labels_to_use[0], _labels_to_use[0]), key_suffix="master_other", is_developer=is_developer, source="gsheet", allow_download=False)
            else:
                # Combined view: load every selected sheet and merge into one table
                combined_rows = []
                for label in _labels_to_use:
                    tab_id = source_ids.get(label, label)
                    sheet_rows = list_generic_tab(tab_id, source="gsheet") or []
                    for r in sheet_rows:
                        combined_rows.append({"Sheet": label, **r})
                if not combined_rows:
                    st.info("No rows in the selected sheets yet. Pick sheets that have data, or check that the refresh has run.")
                else:
                    st.caption(f"**Combined view:** {len(combined_rows):,} rows from **{len(_labels_to_use)}** sheets. Column **Sheet** shows the source.")
                    st.caption("Tip: For accurate dashboard value totals, ensure **List Price** is filled in your source sheets (all calculations use List price only).")
                    cols_combined = list(combined_rows[0].keys()) if combined_rows else []
                    search_combined = st.text_input("Search in all columns", key="master_combined_search", placeholder="Type to filter rows…")
                    rows_shown = combined_rows
                    if (search_combined or "").strip():
                        term = search_combined.strip().lower()
                        rows_shown = [r for r in rows_shown if any(term in str(r.get(k) or "").lower() for k in cols_combined)]
                    st.caption(f"Showing **{len(rows_shown):,}** of **{len(combined_rows):,}** row(s).")
                    df_combined = pd.DataFrame(rows_shown)
                    status_col_combined = None
                    for c in df_combined.columns:
                        if str(c).strip().lower() in ("status", "status__c"):
                            status_col_combined = c
                            break
                    if status_col_combined and not df_combined.empty:
                        _sc = {"Occupied": "#FEE2E2", "Sold": "#FEE2E2", "Vacant": "#D1FAE5", "Churning": "#FDE68A"}
                        _ns = "#B22222"
                        def _row_bg_combined(row):
                            v = (str(row[status_col_combined]) if row[status_col_combined] is not None else "").strip()
                            low = v.lower()
                            if not v or low in ("no status", "n/a", "na", "—", "-", "blocked"):
                                return [f"background-color: {_ns}; color: white"] * len(row)
                            key = "Vacant" if low == "vacant" else "Churning" if low == "churning" else "Occupied" if low == "occupied" else "Sold" if low == "sold" else None
                            bg = _sc.get(key, "") if key else _sc.get(v, "")
                            return [f"background-color: {bg}" if bg else ""] * len(row)
                        df_combined = df_combined.style.apply(_row_bg_combined, axis=1)
                    st.dataframe(df_combined, use_container_width=True, hide_index=True)
        if not rows and not is_other_sheet and chosen_label:
            st.info(f"No rows in **{chosen_label}** yet. Data refreshes automatically every 15 minutes — try again shortly or check the source sheet.")
        elif not is_other_sheet and source_id:
            total = len(rows)
            is_tracker = source_id == "main_tracker"  # superset and Kitchens both use table-like rows
            # Status pills and facility filter for Kitchens / Master Kitchens list (Prompt 4)
            def _row_status(r):
                for k in ("Status", "Status__c", "status"):
                    v = r.get(k)
                    if v is not None and str(v).strip():
                        return str(v).strip()
                return ""
            def _row_facility(r):
                for k in ("Account Name", "Account__r.Name", "facility", "Facility"):
                    v = r.get(k)
                    if v is not None and str(v).strip():
                        return str(v).strip()
                return ""
            if not is_tracker:
                status_filter = st.radio("Status", ["All", "Vacant", "Churning", "Occupied", "Sold"], key="master_status_pill", horizontal=True)
                facility_set = sorted({_row_facility(r) for r in rows if _row_facility(r)})
                no_facility = [r for r in rows if not _row_facility(r)]
                facility_list = (["(No facility)"] if no_facility else []) + list(facility_set)
                use_facility_tabs = len(facility_list) > 0
                if not use_facility_tabs:
                    facility_filter = st.selectbox("Facility", ["All"], key="master_facility_filter")
                else:
                    facility_filter = None
            else:
                use_facility_tabs = False
                facility_list = []
                facility_filter = None
            st.markdown("---")
            st.subheader("Refine your data")
            if st.session_state.pop("master_clear_filters", False):
                for key in ("master_f_date_multi", "master_f_site_multi", "master_f_region_multi", "master_f_metric_multi", "master_search", "master_f_status_filter"):
                    st.session_state[key] = [] if "multi" in key else ("" if key == "master_search" else None)
                st.session_state["master_from_date"] = None
                st.session_state["master_to_date"] = None
                _rerun()
            view_id = st.session_state.pop("master_apply_saved_view", None)
            if view_id is not None and is_tracker:
                v = get_saved_view(view_id)
                if v and isinstance(v.get("filters_json"), dict):
                    fj = v["filters_json"]
                    st.session_state["master_f_date_multi"] = fj.get("report_date") or []
                    st.session_state["master_f_site_multi"] = fj.get("site_id") or []
                    st.session_state["master_f_region_multi"] = fj.get("region") or []
                    st.session_state["master_f_metric_multi"] = fj.get("metric_name") or []
                    st.session_state["master_search"] = fj.get("search") or ""
                    _rerun()
            search = st.text_input("Search in all columns", key="master_search", placeholder="Type to filter rows by any column…")
            if is_tracker:
                no_status = [r for r in rows if not (r.get("status") or "").strip() or str(r.get("status") or "").strip().lower() in ("no status", "n/a", "na", "—", "-", "blocked")]
                if no_status:
                    st.caption(f"**{len(no_status)}** records with no status, Blocked, or empty. ")
                    if st.button("Show only these", key="master_show_no_status"):
                        st.session_state["master_f_status_filter"] = "no_status"
                        _rerun()
                uniq = lambda k: sorted(set(r.get(k) for r in rows if r.get(k)))
                default_dates = [x for x in (st.session_state.get("master_f_date_multi") or []) if x in uniq("report_date")]
                default_sites = [x for x in (st.session_state.get("master_f_site_multi") or []) if x in uniq("site_id")]
                default_reg = [x for x in (st.session_state.get("master_f_region_multi") or []) if x in uniq("region")]
                default_met = [x for x in (st.session_state.get("master_f_metric_multi") or []) if x in uniq("metric_name")]
                with st.expander("Filter by column (optional)", expanded=False):
                    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
                    with c1:
                        st.multiselect("Report date", uniq("report_date"), default=default_dates, key="master_f_date_multi", placeholder="All", label_visibility="visible")
                    with c2:
                        st.multiselect("Site", uniq("site_id"), default=default_sites, key="master_f_site_multi", placeholder="All", label_visibility="visible")
                    with c3:
                        st.multiselect("Region", uniq("region"), default=default_reg, key="master_f_region_multi", placeholder="All", label_visibility="visible")
                    with c4:
                        st.multiselect("Metric", uniq("metric_name"), default=default_met, key="master_f_metric_multi", placeholder="All", label_visibility="visible")
                    with c5:
                        st.write("")
                        st.write("")
                        if st.button("Clear filters", key="master_btn_clear"):
                            st.session_state["master_clear_filters"] = True
                            _rerun()
                    st.caption("Optional date range (filters by report date):")
                    d1, d2 = st.columns(2)
                    with d1:
                        st.date_input("From report date", value=None, key="master_from_date")
                    with d2:
                        st.date_input("To report date", value=None, key="master_to_date")
            rows_filtered = rows
            if not is_tracker and not use_facility_tabs:
                if status_filter and status_filter != "All":
                    rows_filtered = [r for r in rows_filtered if _row_status(r) == status_filter]
                if facility_filter and facility_filter != "All":
                    rows_filtered = [r for r in rows_filtered if _row_facility(r) == facility_filter]
            if is_tracker:
                filters = {
                    "report_date": st.session_state.get("master_f_date_multi") or None,
                    "site_id": st.session_state.get("master_f_site_multi") or None,
                    "region": st.session_state.get("master_f_region_multi") or None,
                    "metric_name": st.session_state.get("master_f_metric_multi") or None,
                }
                rows_filtered = filter_rows(rows, {k: v for k, v in filters.items() if v})
                if st.session_state.get("master_f_status_filter") == "no_status":
                    rows_filtered = [r for r in rows_filtered if not (r.get("status") or "").strip() or str(r.get("status") or "").strip().lower() in ("no status", "n/a", "na", "—", "-", "blocked")]
                from_date = st.session_state.get("master_from_date")
                to_date = st.session_state.get("master_to_date")
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
            if use_facility_tabs:
                facility_tabs = st.tabs(facility_list)
                search_term = (search or "").strip().lower() if search else ""
                for tab_idx, fac_name in enumerate(facility_list):
                    with facility_tabs[tab_idx]:
                        if fac_name == "(No facility)":
                            rows_f = list(no_facility)
                        else:
                            rows_f = [r for r in rows if _row_facility(r) == fac_name]
                        if status_filter and status_filter != "All":
                            rows_f = [r for r in rows_f if _row_status(r) == status_filter]
                        if search_term:
                            rows_f = [r for r in rows_f if any(search_term in str(r.get(k) or "").lower() for k in (r.keys() if isinstance(r, dict) else []))]
                        st.caption(f"**{len(rows_f)}** kitchens · *{fac_name}*")
                        if rows_f:
                            all_cols_f = list(rows_f[0].keys()) if rows_f else []
                            default_show_f = st.session_state.get(f"master_col_f_{tab_idx}") or all_cols_f
                            default_show_f = [c for c in default_show_f if c in all_cols_f] or all_cols_f
                            cols_show_f = st.multiselect("Columns", options=all_cols_f, default=default_show_f, key=f"master_col_f_{tab_idx}", placeholder="All")
                            if not cols_show_f:
                                cols_show_f = all_cols_f
                            if HAS_EXCEL:
                                display_f = pd.DataFrame(rows_f)[cols_show_f] if cols_show_f else pd.DataFrame(rows_f)
                                _sc = {"Occupied": "#FEE2E2", "Sold": "#FEE2E2", "Vacant": "#D1FAE5", "Churning": "#FDE68A"}
                                _ns = "#B22222"
                                status_col_f = next((c for c in display_f.columns if str(c).strip().lower() in ("status", "status__c")), None)
                                if status_col_f and not display_f.empty:
                                    def _row_bg_f(row):
                                        v = (str(row[status_col_f]) if row[status_col_f] is not None else "").strip()
                                        low = v.lower()
                                        if not v or low in ("no status", "n/a", "na", "—", "-", "blocked"):
                                            return [f"background-color: {_ns}; color: white"] * len(row)
                                        key = "Vacant" if low == "vacant" else "Churning" if low == "churning" else "Occupied" if low == "occupied" else "Sold" if low == "sold" else None
                                        bg = _sc.get(key, "") if key else _sc.get(v, "")
                                        return [f"background-color: {bg}" if bg else ""] * len(row)
                                    display_f = display_f.style.apply(_row_bg_f, axis=1)
                                st.dataframe(display_f, use_container_width=True, hide_index=True)
                            else:
                                for r in rows_f[:50]:
                                    st.json(r)
                                if len(rows_f) > 50:
                                    st.caption(f"… and {len(rows_f) - 50} more.")
                        else:
                            st.info("No kitchens match filters.")
            if not use_facility_tabs:
                st.caption(f"**{len(rows_filtered)}** of **{total}** rows")
            if total > 0 and len(rows_filtered) == 0 and not use_facility_tabs:
                st.info("No rows match your filters. Try clearing or relaxing filters.")
            if rows_filtered and not use_facility_tabs:
                all_cols = list(rows_filtered[0].keys()) if rows_filtered else []
                default_show = st.session_state.get("master_columns_show") or all_cols
                default_show = [c for c in default_show if c in all_cols] or all_cols
                cols_to_show = st.multiselect("Columns to show", options=all_cols, default=default_show, key="master_columns_show", placeholder="All columns")
                if not cols_to_show:
                    cols_to_show = all_cols
            if HAS_EXCEL and rows_filtered and not use_facility_tabs:
                display_df = pd.DataFrame(rows_filtered)[cols_to_show] if cols_to_show else pd.DataFrame(rows_filtered)
                _sc = {"Occupied": "#FEE2E2", "Sold": "#FEE2E2", "Vacant": "#D1FAE5", "Churning": "#FDE68A"}
                _ns = "#B22222"
                status_col_m = next((c for c in display_df.columns if str(c).strip().lower() in ("status", "status__c")), None)
                if status_col_m and not display_df.empty:
                    def _row_bg_m(row):
                        v = (str(row[status_col_m]) if row[status_col_m] is not None else "").strip()
                        low = v.lower()
                        if not v or low in ("no status", "n/a", "na", "—", "-", "blocked"):
                            return [f"background-color: {_ns}; color: white"] * len(row)
                        key = "Vacant" if low == "vacant" else "Churning" if low == "churning" else "Occupied" if low == "occupied" else "Sold" if low == "sold" else None
                        bg = _sc.get(key, "") if key else _sc.get(v, "")
                        return [f"background-color: {bg}" if bg else ""] * len(row)
                    display_df = display_df.style.apply(_row_bg_m, axis=1)
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            elif rows_filtered and not use_facility_tabs:
                for r in rows_filtered[:100]:
                    st.json({k: r[k] for k in (cols_to_show or r.keys()) if k in r} if (cols_to_show and set(cols_to_show) != set(r.keys())) else r)
                if len(rows_filtered) > 100:
                    st.caption(f"… and {len(rows_filtered) - 100} more.")
            if HAS_EXCEL and rows_filtered and len(rows_filtered) > 0 and not use_facility_tabs:
                st.markdown("---")
                st.subheader("Pivot view")
                st.caption("Slice your data by rows and columns.")
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

    # Dashboard: management view — percentages, insights, breakdowns; no day-to-day focus
    elif section == "Dashboard":
        superset_rows, superset_meta = _get_superset_master_kitchens()
        if superset_rows is not None:
            st.caption("Data source: **Superset (Trino proxy)**. Last refresh: **" + ((superset_meta or {}).get("last_refresh_ts_utc") or "Never") + "**")
            if _superset_stale_warning(superset_meta or {}):
                st.warning("Last refresh is older than 30 minutes or last run failed.")
            rows_kitchens = superset_rows
        else:
            # Always use GSheet for Dashboard so regular users see data (session data_source may default to salesforce)
            rows_kitchens = list_generic_tab("Kitchens", source="gsheet") or list_generic_tab("Master Kitchens list", source="gsheet") or []
            st.caption("Data source: **Google Sheet (Kitchens / Master Kitchens list)**. Data refreshes every 15 minutes — use **Refresh** in the sidebar if you need the latest.")
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
            if low == "vacant":
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
            # Explicit keys first (SF / report column names)
            for k in ("Opportunity Name", "Opportunity__r.Name", "Opportunity_Name__c", "Opportunity Name__c", "Opportunity name", "opportunity_name", "opportunity name"):
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
        .dashboard-summary { background: linear-gradient(135deg, #f0fdf4 0%, #ecfeff 100%); border-radius: 12px; padding: 14px 18px; margin-bottom: 1rem; border-left: 4px solid #0F766E; font-size: 0.95rem; }
        div[data-testid="stMetric"] { background: linear-gradient(145deg, #f0fdf4 0%, #e0f2fe 100%); border-radius: 10px; padding: 12px 14px; border-left: 4px solid #0F766E; transition: transform 0.15s ease, box-shadow 0.15s ease; }
        div[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(15,118,110,0.2); }
        .dashboard-value-row { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }
        .dashboard-value-card { flex: 1; min-width: 160px; border-radius: 12px; padding: 16px 18px; transition: transform 0.2s ease, box-shadow 0.2s ease; cursor: default; }
        .dashboard-value-card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,0.12); }
        .dashboard-value-card.vacant { background: linear-gradient(145deg, #D1FAE5 0%, #A7F3D0 100%); border-left: 4px solid #059669; }
        .dashboard-value-card.churning { background: linear-gradient(145deg, #FFEDD5 0%, #FED7AA 100%); border-left: 4px solid #EA580C; }
        .dashboard-value-card.occupied { background: linear-gradient(145deg, #FEE2E2 0%, #FECACA 100%); border-left: 4px solid #DC2626; }
        .dashboard-value-card .label { font-size: 0.85rem; color: #374151; font-weight: 600; margin-bottom: 4px; }
        .dashboard-value-card .value { font-size: 1.35rem; font-weight: 700; color: #111827; }
        .dashboard-value-card .currency-hint { font-size: 0.75rem; color: #6B7280; margin-top: 4px; }
        .dashboard-facility-card { background: linear-gradient(145deg, #f0fdf4 0%, #e0f2fe 100%); border-radius: 12px; padding: 16px; margin: 1rem 0; border-left: 4px solid #0F766E; overflow-x: auto; }
        .dashboard-facility-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        .dashboard-facility-table th { background: rgba(15,118,110,0.15); color: #134e4a; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #0F766E; }
        .dashboard-facility-table td { padding: 8px 12px; border-bottom: 1px solid rgba(15,118,110,0.2); }
        .dashboard-facility-table tr:hover { background: rgba(255,255,255,0.7); }
        .dashboard-facility-table tr:nth-child(even) { background: rgba(255,255,255,0.4); }
        .dashboard-facility-table tr:nth-child(even):hover { background: rgba(255,255,255,0.8); }
        .dashboard-facility-summary { background: linear-gradient(135deg, #ecfeff 0%, #f0fdf4 100%); border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; border-left: 4px solid #0d9488; font-size: 0.9rem; }
        .dashboard-churn-card { background: linear-gradient(145deg, #FFEDD5 0%, #FED7AA 100%); border-radius: 12px; padding: 16px; margin: 1rem 0; border-left: 4px solid #EA580C; overflow-x: auto; }
        .dashboard-churn-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        .dashboard-churn-table th { background: rgba(234,88,12,0.2); color: #9a3412; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #EA580C; }
        .dashboard-churn-table td { padding: 8px 12px; border-bottom: 1px solid rgba(234,88,12,0.25); }
        .dashboard-churn-table tr:hover { background: rgba(255,255,255,0.6); }
        .dashboard-churn-table tr:nth-child(even) { background: rgba(255,255,255,0.35); }
        .dashboard-churn-table tr:nth-child(even):hover { background: rgba(255,255,255,0.75); }
        .dashboard-churn-metric { background: linear-gradient(145deg, #FFEDD5 0%, #FED7AA 100%); border-radius: 12px; padding: 16px 18px; margin-bottom: 12px; border-left: 4px solid #EA580C; display: inline-block; min-width: 200px; }
        .dashboard-churn-metric .label { font-size: 0.85rem; color: #9a3412; font-weight: 600; margin-bottom: 4px; }
        .dashboard-churn-metric .value { font-size: 1.35rem; font-weight: 700; color: #111827; }
        .churn-section-panel { background: linear-gradient(180deg, #FFFBEB 0%, #FFF7ED 50%, #FEF3C7 100%); border-radius: 12px; padding: 20px 24px; margin: 16px 0; border-left: 4px solid #EA580C; box-shadow: 0 2px 12px rgba(234,88,12,0.08); }
        .churn-month-card { background: white; border-radius: 10px; padding: 14px 18px; margin: 8px 0; border: 1px solid rgba(234,88,12,0.25); box-shadow: 0 1px 4px rgba(0,0,0,0.06); transition: box-shadow 0.2s ease; }
        .churn-month-card:hover { box-shadow: 0 4px 12px rgba(234,88,12,0.15); }
        .churn-month-card .month-name { font-weight: 700; color: #9a3412; font-size: 1rem; margin-bottom: 4px; }
        .churn-month-card .month-stats { font-size: 0.9rem; color: #374151; }
        div[data-testid="stDataFrame"] { border-radius: 10px; box-shadow: 0 2px 8px rgba(15,118,110,0.08); border: 1px solid rgba(15,118,110,0.2); overflow: hidden; }
        div[data-testid="stDataFrame"]:hover { box-shadow: 0 4px 14px rgba(15,118,110,0.12); }
        </style>
        """, unsafe_allow_html=True)
        st.markdown(
            f'<div class="dashboard-summary"><strong>KSA at a glance</strong> · {total:,} kitchens · {vacant:,} vacant · {occupied:,} occupied · {sold:,} sold · {vacant_approved_deal:,} approved deal{"s" if vacant_approved_deal != 1 else ""}</div>',
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
                                    key = "Vacant" if low == "vacant" else "Churning" if low == "churning" else "Occupied" if low == "occupied" else "Sold" if low == "sold" else None
                                    bg = _status_colors.get(key, "") if key else _status_colors.get(v, "")
                                    return [f"background-color: {bg}" if bg else ""] * len(row)
                                df_inv = df_inv.style.apply(_inv_row_bg, axis=1)
                            st.dataframe(df_inv, use_container_width=True, hide_index=True, column_config={"Floor (MRR)": st.column_config.NumberColumn(format="%.0f"), "List (MRR)": st.column_config.NumberColumn(format="%.0f")})
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

    # Search (all tabs)
    if section == "Search":
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
        st.caption("Use the **Kitchens** tab; filter or search below.")
        # Data source: Google Sheet only (Salesforce source removed from UI)
        st.session_state["data_source"] = "gsheet"
        last_refresh_gsheet = get_last_refresh("gsheet")
        # Auto-refresh when no data or stale (>15 min), no click needed (same cooldown as Kitchen Master Data)
        import time
        _now_sec = time.time()
        _last_run = st.session_state.get("gsheet_auto_refresh_last_run") or 0
        if _gsheet_refresh_is_stale(15) and (_now_sec - _last_run) >= 900:
            st.session_state["gsheet_auto_refresh_last_run"] = _now_sec
            ok, msg = _refresh_from_online_sheet()
            if ok:
                set_last_refresh("gsheet")
                _rerun()
            last_refresh_gsheet = get_last_refresh("gsheet")
        _show_refresh_btn = _is_developer() or user_role == "super_user"
        if _show_refresh_btn:
            col_cap, col_btn = st.columns([3, 1])
            with col_cap:
                st.caption(f"Current source: **Google Sheet (GSheet)**. Last refresh: **{last_refresh_gsheet or 'Never'}**. Data is refreshed every 15 minutes by the scheduler; you can use the button for an immediate update.")
            with col_btn:
                if st.button("Refresh from Google Sheet", key="data_refresh_btn"):
                    ok, msg = _refresh_from_online_sheet()
                    if ok:
                        set_last_refresh("gsheet")
                        st.success("Data loaded from Google Sheet.")
                    else:
                        st.error(msg or "Google Sheet refresh failed.")
                    if ok:
                        _rerun()
        else:
            st.caption(f"Current source: **Google Sheet (GSheet)**. Last refresh: **{last_refresh_gsheet or 'Never'}**. Data is refreshed every 15 minutes by the scheduler.")
        st.divider()
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
        st.caption("Data is refreshed every 15 minutes by the scheduler (no manual refresh).")
        st.caption("Data from **online sheet**. Tabs match your Google Sheet order (refresh to update). Scroll the tab bar to see all.")
        # Tabs in same order as worksheets in the sheet (from last refresh); fallback to stored order if empty
        all_tab_ids = [t for t in list_gsheet_tab_ids_in_sheet_order() if t != MAIN_TRACKER_TAB_ID]
        if not all_tab_ids:
            all_tab_ids = [t for t in list_tab_ids_for_source("gsheet") if t != MAIN_TRACKER_TAB_ID]
        if not all_tab_ids:
            st.info("No sheet data yet. Data is refreshed every 15 minutes by the scheduler.")
        else:
            sheet_tabs = st.tabs(all_tab_ids)
            tab_tips = [TAB_DESCRIPTIONS.get(tid, f"View and filter: {tid}") for tid in all_tab_ids]
            st.markdown(
                f'<script>(function(){{var d = {json.dumps(tab_tips)}; '
                'var tabs = document.querySelectorAll(".stTabs [data-baseweb=\\"tab\\"]"); '
                'tabs.forEach(function(tab, i){{ if(d[i]) tab.setAttribute("title", d[i]); }}); }})();</script>',
                unsafe_allow_html=True,
            )
            for tab_index, tab_id in enumerate(all_tab_ids):
                with sheet_tabs[tab_index]:
                    _render_generic_tab(tab_id, key_suffix=(tab_id or str(tab_index)).replace(" ", "_"), is_developer=is_developer, source="gsheet")

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
                st.download_button("Export CSV", data=buf.getvalue(), file_name="facility_multipliers.csv", mime="text/csv", key="pm_export")
        else:
            st.info("Multipliers module not loaded (app/multipliers.py).")
        return

    if section == "Admin / Data Health":
        st.caption("Data source health and allowed list (read-only). No manual refresh — scheduler runs every 15 minutes.")
        st.markdown(f"**User:** {current_user or '—'} · **Role:** {user_role}")
        st.subheader("Superset persisted store")
        if data_store_mod:
            name = getattr(data_store_mod, "MASTER_KITCHENS_LIVE", "master_kitchens_live")
            meta = data_store_mod.read_metadata(name)
            if meta:
                st.markdown(f"- Last refresh: **{meta.get('last_refresh_ts_utc') or 'Never'}**")
                st.markdown(f"- Status: **{meta.get('status') or '—'}**")
                st.markdown(f"- Row count: **{meta.get('row_count', '—')}**")
                if meta.get("error_message"):
                    st.markdown(f"- Error: *{meta.get('error_message')}*")
                if meta.get("uploaded_by"):
                    st.markdown(f"- Last CSV upload by: **{meta.get('uploaded_by')}** at {meta.get('uploaded_at_utc') or '—'}")
            else:
                st.caption("No metadata yet (refresh job may not have run).")
        else:
            st.caption("data_store module not loaded.")
        if user_role == "super_user" and data_store_mod:
            st.subheader("Upload CSV Backup")
            st.caption("Replace Master Kitchens (Live) with an uploaded CSV. Tracked in metadata.")
            up = st.file_uploader("CSV file", type=["csv"], key="admin_csv_backup")
            if up is not None:
                try:
                    df_up = pd.read_csv(up)
                    if not df_up.empty and st.button("Replace dataset with this CSV", key="admin_csv_confirm"):
                        if data_store_mod.write_dataset_and_metadata(
                            getattr(data_store_mod, "MASTER_KITCHENS_LIVE", "master_kitchens_live"),
                            df_up,
                            status="success",
                            uploaded_by=current_user or "unknown",
                        ):
                            st.success("Dataset replaced. Last refresh and uploaded_by updated.")
                            _rerun()
                        else:
                            st.error("Failed to persist.")
                except Exception as e:
                    st.error(str(e))
        st.subheader("Allowed list (read-only)")
        allowed = list_allowed_users()
        if not allowed:
            st.caption("No entries (or allowlist from secrets only).")
        else:
            for u in allowed:
                st.markdown(f"- **{u.get('identifier')}** — {u.get('role') or 'associate_viewer'}")
        return

if __name__ == "__main__":
    main()
