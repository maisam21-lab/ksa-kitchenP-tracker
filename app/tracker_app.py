"""
Kitchens Tracker — web app. Run: streamlit run app/tracker_app.py
All sheet tabs in tool form: view, filter, add/edit, export. Single source of truth.
Refreshes from the online Google Sheet (and scheduled jobs) — not from local file upload.
"""
import base64
import csv
import html
import io
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as st_components

try:
    from app import auth
except ImportError:
    try:
        import auth
    except Exception:
        auth = None
except Exception:
    auth = None
try:
    from app import snapshot as snapshot_mod
except ImportError:
    try:
        import snapshot as snapshot_mod
    except Exception:
        snapshot_mod = None
except Exception:
    snapshot_mod = None
try:
    from app import fx as fx_mod
except ImportError:
    try:
        import fx as fx_mod
    except Exception:
        fx_mod = None
except Exception:
    fx_mod = None
try:
    from app import multipliers as multipliers_mod
except ImportError:
    try:
        import multipliers as multipliers_mod
    except Exception:
        multipliers_mod = None
except Exception:
    multipliers_mod = None
try:
    from app import data_store as data_store_mod
except ImportError:
    try:
        import data_store as data_store_mod
    except Exception:
        data_store_mod = None
except Exception:
    data_store_mod = None

try:
    import pandas as pd
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, DataReturnMode

    _HAS_AGGRI = True
except ImportError:
    try:
        from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

        DataReturnMode = None
        _HAS_AGGRI = True
    except ImportError:
        AgGrid = None  # type: ignore[misc, assignment]
        GridOptionsBuilder = None  # type: ignore[misc, assignment]
        JsCode = None  # type: ignore[misc, assignment]
        DataReturnMode = None
        _HAS_AGGRI = False

# Online sheet: same ID as the workbook (docs.google.com/.../d/SHEET_ID/edit?gid=...)
# Same logic as the sheet: country merge (SA/regions → Saudi Arabia, BH → Bahrain), status color coding.
SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"

# Preview-only regional kitchen master workbooks (same service account as KSA; share Viewer with SA).
KUWAIT_KITCHEN_SHEET_ID = "1N_Ar-KoFWGTHjbz-p_r1y8VeWGLNI4ZQUAbKZpAI99o"
KUWAIT_KITCHEN_WORKSHEET_GID = 1841714979
# New facility tab missing? Add its worksheet gid via secrets/env KUWAIT_KITCHEN_EXTRA_FACILITY_GIDS (comma list; gid is in the sheet URL ?gid=...).
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
    2025526748,
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
# Stored in SQLite under separate sources so KSA tabs are unchanged.
GSOURCE_KITCHEN_KW = "gsheet_kw"
GSOURCE_KITCHEN_AE = "gsheet_ae"
GSOURCE_KITCHEN_BH = "gsheet_bh"
# Main KSA workbook + regional facility DB sources — all contribute to header "last refreshed".
_GSHEET_FAMILY_REFRESH_SOURCES: tuple[str, ...] = (
    "gsheet",
    GSOURCE_KITCHEN_KW,
    GSOURCE_KITCHEN_AE,
    GSOURCE_KITCHEN_BH,
)
TAB_ID_KITCHEN_KW = "Kuwait Kitchen Master"
TAB_ID_KITCHEN_AE = "UAE Kitchen Master"
TAB_ID_KITCHEN_BH = "Bahrain Kitchen Master"
# Main nav: **KSA** is the Master Kitchen area (replaces legacy label "Kitchen Master Data").
SECTION_KSA = "KSA"
_LEGACY_SECTION_KITCHEN_MASTER = "Kitchen Master Data"
# Sub-nav inside **KSA**: regional workbooks only; main KSA sheet is the default (no extra chip).
KITCHEN_MASTER_SUBVIEW_MAIN = "main"
KITCHEN_MASTER_REGION_ROW: tuple[tuple[str, str], ...] = (
    ("Kuwait", "Kuwait"),
    ("UAE", "UAE"),
    ("Bahrain", "Bahrain"),
)
SESSION_KEY_KITCHEN_MASTER_REGION = "kitchen_master_region_pick"
# Users who may open Kitchen Master regional views (Kuwait / UAE / Bahrain), not only KSA.
# Union with PREVIEW_ONLY_IDS / BAHRAIN_KITCHEN_PREVIEW_IDS in Streamlit secrets or env.
PREVIEW_ONLY_IDS = (
    "maysam.abukashabeh@cloudkitchens.com,"
    "jad.hajjar@cloudkitchens.com,"
    "tala.zeineddine@cloudkitchens.com"
)
# Optional market-scoped visibility (secrets/env):
# - MARKET_VIEW_KSA_IDS
# - MARKET_VIEW_UAE_IDS
# - MARKET_VIEW_KUWAIT_IDS
# - MARKET_VIEW_BAHRAIN_IDS
# Comma/newline/semicolon-separated emails. When a user is in one of these lists,
# Kitchen Master and Dashboard views are restricted to that market.
MARKET_VIEW_KSA_IDS = ""
MARKET_VIEW_UAE_IDS = ""
MARKET_VIEW_KUWAIT_IDS = ""
MARKET_VIEW_BAHRAIN_IDS = ""
# CSV export allowlist (merged with EXPORT_ALLOWED_IDS in Streamlit secrets or env).
EXPORT_ALLOWED_IDS = (
    "maysam.abukashabeh@cloudkitchens.com,"
    "jad.hajjar@cloudkitchens.com,"
    "tala.zeineddine@cloudkitchens.com,"
    "bassem.ghossaini@cloudkitchens.com,"
    "michelle.kossaifi@cloudkitchens.com"
)
# Sign-in allowlist (merged with ALLOWLIST_IDS in secrets/env). Deduplicated emails; order not significant.
ALLOWLIST_IDS = (
    "masa.barhoumeh@cloudkitchens.com,"
    "yousif.almohammedali@cloudkitchens.com,"
    "osama.eliewa@cloudkitchens.com,"
    "bassel.miri@cloudkitchens.com,"
    "ahmad.elbasst@cloudkitchens.com,"
    "riyad.ali@cloudkitchens.com,"
    "muhammad.ali@cloudkitchens.com,"
    "mohammad.bezzi@cloudkitchens.com,"
    "sara.alabbasi@cloudkitchens.com,"
    "maher.bouramia@cloudkitchens.com,"
    "jad.alajouz@cloudkitchens.com,"
    "abdelrahman.matar@cloudkitchens.com,"
    "jad.hajjar@cloudkitchens.com,"
    "tala.zeineddine@cloudkitchens.com,"
    "yazan.saeed@cloudkitchens.com,"
    "maysam.abukashabeh@cloudkitchens.com,"
    "tarek.trad@cloudkitchens.com,"
    "toufic.daher@cloudkitchens.com,"
    "rafik.boudiaf@cloudkitchens.com,"
    "hamza.alzaim@cloudkitchens.com,"
    "hossam.metwally@cloudkitchens.com,"
    "bassem.ghossaini@cloudkitchens.com,"
    "nouf.alshammri@cloudkitchens.com,"
    "michelle.kossaifi@cloudkitchens.com,"
    "mohammed.masri@cloudkitchens.com,"
    "gadah.saud@cloudkitchens.com,"
    "lamees.aljamie@cloudkitchens.com,"
    "abdullah.abohaymid@cloudkitchens.com,"
    "mark.grehan@cloudkitchens.com"
)
# Product team IDs (merged with DEVELOPER_IDS in secrets). These emails get super_user → Dashboard + Kitchen Master + Discussions.
DEVELOPER_IDS = (
    "maysam.abukashabeh@cloudkitchens.com,"
    "jad.hajjar@cloudkitchens.com,"
    "tala.zeineddine@cloudkitchens.com,"
    "yazan.saeed@cloudkitchens.com"
)
# Bahrain facilities live in the main workbook; only these worksheets (gids) load into gsheet_bh.
# Share sheet with service account; restrict who sees regional tabs via PREVIEW_ONLY_IDS / secrets.
BAHRAIN_KITCHEN_SHEET_ID = SHEET_ID
BAHRAIN_KITCHEN_WORKSHEET_GID = 2128153042
BAHRAIN_KITCHEN_FACILITY_GIDS = [
    2128153042,
    782567541,
]

# Rerun works in Streamlit 1.27+; fallback for older versions
def _rerun():
    if hasattr(st, "rerun"): 
        st.rerun()
    else:
        st.experimental_rerun()


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent


def _resolve_db_path() -> Path:
    """SQLite file path. Streamlit Cloud often has a read-only repo; fall back to /tmp when app/data is not writable.

    Override with env ``TRACKER_DB_PATH`` or ``SQLITE_DB_PATH`` (absolute path recommended on Cloud).
    """
    env = (os.environ.get("TRACKER_DB_PATH") or os.environ.get("SQLITE_DB_PATH") or "").strip()
    if env:
        return Path(env)
    primary = APP_DIR / "data" / "tracker.db"
    for p in (primary, Path(tempfile.gettempdir()) / "ksa_kitchen_tracker.db"):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            t = p.parent / ".ksa_tracker_write_probe"
            t.write_text("ok", encoding="utf-8")
            t.unlink(missing_ok=True)
            return p
        except OSError:
            continue
    return Path(tempfile.gettempdir()) / "ksa_kitchen_tracker.db"


DB_PATH = _resolve_db_path()
STATIC_DIR = APP_DIR / "static"
APP_DISPLAY_TITLE = "Kitchens Tracker"


def _logo_path():
    """Path to KitchenPark logo if present."""
    for name in ("kitchenpark_logo.png", "logo.png", "kitchenpark_logo.svg", "logo.svg"):
        p = STATIC_DIR / name
        if p.exists():
            return p
    return None


def _strip_salesforce_picklist_prefix(val) -> str:
    """Strip leading ``(n) `` / ``n.`` from picklist labels (Status, Stage, etc.)."""
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    s = re.sub(r"^\(\s*\d+\s*\)\s*", "", s, flags=re.IGNORECASE).strip() or s
    s = re.sub(r"^\d+\s*[.)]\s*", "", s, flags=re.IGNORECASE).strip() or s
    return s


def _row_has_opportunity_name(row) -> bool:
    """True when a kitchen row has non-empty Opportunity Name-style value.

    Used for coloring only: Vacant + opportunity -> pink; Vacant without opportunity stays green.
    """
    if row is None:
        return False
    # Same keys as Dashboard _opportunity_name (SF / GSheet / BigQuery)
    for k in ("Opportunity Name", "Opportunity__r.Name", "Opportunity_Name__c", "Opportunity Name__c", "Opportunity name", "opportunity_name", "opportunity name", "Opportunity_Name"):
        v = row.get(k) if hasattr(row, "get") else (row[k] if k in (row.index if hasattr(row, "index") else []) else None)
        if v is not None and str(v).strip() and str(v).strip().lower() not in ("nan", "none"):
            return True
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

# Injected for grid row styling only — never include in user CSV downloads.
_INTERNAL_CSV_EXPORT_KEYS = frozenset({"_has_opportunity"})

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
    try:
        upload.seek(0)
    except Exception:
        pass
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
    try:
        upload.seek(0)
    except Exception:
        pass
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
    """Open SQLite with settings suited to Streamlit (reruns, possible multi-worker contention)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=60.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.Error:
        pass
    try:
        # Better concurrent read/write than default rollback journal (reduces "database is locked").
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
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


def _init_db_schema():
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


def _init_db_schema_with_retries() -> None:
    """Run schema init; retry when SQLite reports a transient lock (common on Cloud)."""
    last: sqlite3.OperationalError | None = None
    for i in range(35):
        try:
            _init_db_schema()
            return
        except sqlite3.OperationalError as e:
            last = e
            if "locked" not in str(e).lower():
                raise
            time.sleep(min(2.0, 0.06 * (1.3**min(i, 30))))
    if last:
        raise last


def init_db():
    """Create tables. Retries on lock; falls back to /tmp if the primary path fails (Streamlit Cloud)."""
    global DB_PATH
    try:
        _init_db_schema_with_retries()
    except sqlite3.OperationalError:
        alt = Path(tempfile.gettempdir()) / "ksa_kitchen_tracker.db"
        if alt.resolve() == Path(DB_PATH).resolve():
            raise
        DB_PATH = alt
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _init_db_schema_with_retries()


def _get_allowlist_ids_from_config() -> list[str]:
    """Return allowlisted identifiers from ALLOWLIST_IDS (secrets/env + built-in ALLOWLIST_IDS)."""
    try:
        ids = st.secrets.get("ALLOWLIST_IDS") or os.environ.get("ALLOWLIST_IDS", "")
    except Exception:
        ids = os.environ.get("ALLOWLIST_IDS", "")
    parts: list[str] = []
    if isinstance(ids, list):
        parts = [str(s).strip() for s in ids if s and str(s).strip()]
    else:
        parts = [s.strip() for s in str(ids).split(",") if s.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for bucket in (parts, [s.strip() for s in str(ALLOWLIST_IDS or "").split(",") if s.strip()]):
        for s in bucket:
            k = (s or "").strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append((s or "").strip())
    return out


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
_TRACKER_PARAM_REMEMBER = "r"
_TRACKER_PARAM_SIGNED_OUT = "so"


def _restore_session_from_params() -> bool:
    """If URL has valid tracker session params, restore user_display_name and return True."""
    if st.session_state.get("_force_signed_out"):
        return False
    try:
        q = getattr(st, "query_params", None) or getattr(st, "experimental_get_query_params", lambda: {})()
        if callable(q):
            q = q()
        if not q:
            return False
        u = q.get(_TRACKER_PARAM_USER)
        e = q.get(_TRACKER_PARAM_EXPIRY)
        r = q.get(_TRACKER_PARAM_REMEMBER)
        # Always prefill remembered email for convenience (does not imply verified sign-in).
        if r and "remembered_email" not in st.session_state:
            r = r[0] if isinstance(r, list) else r
            try:
                rem = base64.b64decode(str(r).encode()).decode()
            except Exception:
                rem = ""
            if rem and "@" in rem:
                st.session_state["remembered_email"] = rem
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
        if st.session_state.get("_force_signed_out"):
            return
        import time
        expiry_ts = int(time.time()) + (SESSION_PERSISTENCE_HOURS * 3600)
        u = base64.b64encode((user or "").strip().encode()).decode()
        qp = getattr(st, "query_params", None)
        if qp is not None:
            qp[_TRACKER_PARAM_USER] = u
            qp[_TRACKER_PARAM_EXPIRY] = str(expiry_ts)
            qp[_TRACKER_PARAM_REMEMBER] = u
    except Exception:
        pass


def _clear_session_params() -> None:
    """Remove session params from URL."""
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None:
            remember = qp.get(_TRACKER_PARAM_REMEMBER)
            qp.clear()
            if remember:
                qp[_TRACKER_PARAM_REMEMBER] = remember[0] if isinstance(remember, list) else remember
    except Exception:
        pass


def _signed_out_gate_active() -> bool:
    if st.session_state.get("_force_signed_out"):
        return True
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None:
            so = qp.get(_TRACKER_PARAM_SIGNED_OUT)
            if isinstance(so, list):
                so = so[0] if so else ""
            if str(so or "").strip() in ("1", "true", "yes"):
                st.session_state["_force_signed_out"] = True
                return True
    except Exception:
        pass
    return False


def _render_signed_out_gate() -> None:
    # Apply on landing/signed-out screen too (main style block is below and won't run after st.stop()).
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"] {
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
            position: sticky !important;
            top: 0 !important;
            z-index: 10000 !important;
        }
        div[data-testid="stToolbar"] {
            display: flex !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            z-index: 10001 !important;
        }
        div[data-testid="stDecoration"] {
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _remembered = (st.session_state.get("remembered_email") or "").strip()
    st.text_input(
        "Your email",
        key="user_display_name",
        value=_remembered,
        placeholder="e.g. jane@company.com",
        help="Prefilled for convenience. Tap Continue to enter the app again.",
    )
    st.info("You are signed out.")
    if st.button("Continue", key="signed_out_continue_global", type="primary"):
        st.session_state.pop("_force_signed_out", None)
        try:
            qp = getattr(st, "query_params", None)
            if qp is not None:
                qp.pop(_TRACKER_PARAM_SIGNED_OUT, None)
        except Exception:
            pass
        _rerun()
    st.stop()


def _do_sign_out() -> None:
    """Sign out current session while keeping remembered email for sign-in form prefill."""
    st.session_state["_force_signed_out"] = True
    if "user_display_name" in st.session_state:
        del st.session_state["user_display_name"]
    st.session_state["developer_unlocked"] = False
    _clear_session_params()
    _clear_remember_me_cookie()
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None:
            qp[_TRACKER_PARAM_SIGNED_OUT] = "1"
    except Exception:
        pass
    _rerun()


# Remember-me cookie (mobile-safe verified-sign-in persistence).
#
# Streamlit Cloud's OIDC cookie is cleared aggressively on iOS Safari (ITP) and on link
# previewers / "Add to Home Screen" flows, so users get bounced to "Sign in with Google"
# even though they signed in recently. To bridge that, after a successful OIDC sign-in
# we mint a signed token containing (email, expiry) and store it in an HTTP cookie via
# extra-streamlit-components.CookieManager. On subsequent loads, if the cookie verifies
# and the email is still on the allowlist, we treat the user as verified without the
# OIDC round-trip. Cookie is cleared on explicit Sign out. If REMEMBER_ME_SECRET is not
# configured the feature stays dormant and the app falls back to current behavior.
_REMEMBER_ME_COOKIE = "ktracker_rm"
_REMEMBER_ME_TOKEN_VERSION = "v1"
_REMEMBER_ME_TTL_DAYS = 30


def _get_remember_me_secret() -> str:
    """HMAC signing key for remember-me tokens; from secrets or env."""
    try:
        v = (getattr(st, "secrets", None) or {}).get("REMEMBER_ME_SECRET") or ""
    except Exception:
        v = ""
    if not v:
        v = os.environ.get("REMEMBER_ME_SECRET", "") or ""
    return str(v).strip()


def _mint_remember_me_token(email: str, expiry_ts: int) -> str:
    """Return base64url(payload).hex(hmac) where payload = 'v1|email|expiry'."""
    import hmac, hashlib
    secret = _get_remember_me_secret()
    if not secret:
        return ""
    payload = f"{_REMEMBER_ME_TOKEN_VERSION}|{(email or '').strip()}|{int(expiry_ts)}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{body}.{sig}"


def _verify_remember_me_token(token: str) -> str | None:
    """Return verified email if token is well-formed, signature is valid, and expiry is in the future."""
    if not token or "." not in token:
        return None
    secret = _get_remember_me_secret()
    if not secret:
        return None
    import hmac, hashlib
    try:
        body_b64, sig = token.split(".", 1)
        pad = "=" * (-len(body_b64) % 4)
        payload = base64.urlsafe_b64decode((body_b64 + pad).encode()).decode()
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        parts = payload.split("|")
        if len(parts) != 3 or parts[0] != _REMEMBER_ME_TOKEN_VERSION:
            return None
        email, expiry_str = parts[1], parts[2]
        if int(expiry_str) < int(time.time()):
            return None
        if not email or "@" not in email:
            return None
        return email
    except Exception:
        return None


def _get_cookie_manager():
    """Lazily import + cache an extra-streamlit-components CookieManager.
    Returns None if the package is not installed (feature stays dormant)."""
    if "_cookie_manager" in st.session_state:
        return st.session_state["_cookie_manager"]
    try:
        import extra_streamlit_components as stx
    except Exception:
        st.session_state["_cookie_manager"] = None
        return None
    try:
        cm = stx.CookieManager(key="ktracker_cookies")
    except Exception:
        cm = None
    st.session_state["_cookie_manager"] = cm
    return cm


def _set_remember_me_cookie(email: str) -> None:
    """Issue a fresh signed cookie for this email (30-day TTL)."""
    if not email or not _get_remember_me_secret():
        return
    cm = _get_cookie_manager()
    if cm is None:
        return
    expiry_ts = int(time.time()) + (_REMEMBER_ME_TTL_DAYS * 24 * 3600)
    token = _mint_remember_me_token(email, expiry_ts)
    if not token:
        return
    try:
        expires_at = datetime.now(timezone.utc) + timedelta(days=_REMEMBER_ME_TTL_DAYS)
        cm.set(_REMEMBER_ME_COOKIE, token, expires_at=expires_at, key=f"set_rm_{int(time.time())}")
    except Exception:
        pass


def _clear_remember_me_cookie() -> None:
    cm = st.session_state.get("_cookie_manager")
    if cm is None:
        return
    try:
        cm.delete(_REMEMBER_ME_COOKIE, key=f"del_rm_{int(time.time())}")
    except Exception:
        pass


def _try_restore_from_remember_me_cookie() -> str | None:
    """Return verified email if a valid remember-me cookie is present, else None.
    Allowlist re-check is the caller's job."""
    if st.session_state.get("_force_signed_out"):
        return None
    if not _get_remember_me_secret():
        return None
    cm = _get_cookie_manager()
    if cm is None:
        return None
    try:
        token = cm.get(cookie=_REMEMBER_ME_COOKIE)
    except Exception:
        token = None
    if not token:
        return None
    return _verify_remember_me_token(str(token))


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
    """IDs (emails/names) allowed to enter the app, lowercased.

    Includes:
    - ALLOWLIST_IDS (secrets/env + built-in)
    - All MARKET_VIEW_* IDs so market-scoped users can sign in without duplicating entries.
    """
    try:
        raw = st.secrets.get("ALLOWLIST_IDS") or os.environ.get("ALLOWLIST_IDS", "")
    except Exception:
        raw = os.environ.get("ALLOWLIST_IDS", "")
    ids: set[str] = set()
    for part in re.split(r"[,\n;\s]+", str(raw or "").strip()):
        s = part.strip()
        if s:
            ids.add(s.lower())
    for part in re.split(r"[,\n;\s]+", str(ALLOWLIST_IDS or "").strip()):
        s = part.strip()
        if s:
            ids.add(s.lower())
    for market in ("ksa", "uae", "kuwait", "bahrain"):
        try:
            ids.update(_market_view_ids_from_secrets(market))
        except Exception:
            pass
    return ids


def _developer_ids_merged_list() -> list[str]:
    """Lowercased emails from DEVELOPER_IDS (built-in + secrets/env), deduplicated."""
    try:
        raw = st.secrets.get("DEVELOPER_IDS") or os.environ.get("DEVELOPER_IDS", "")
    except Exception:
        raw = os.environ.get("DEVELOPER_IDS", "")
    seen: set[str] = set()
    out: list[str] = []
    for bucket in (str(DEVELOPER_IDS or ""), str(raw or "")):
        for part in re.split(r"[,\n;\s]+", bucket.strip()):
            s = (part or "").strip().lower()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


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


def _latest_refresh_among_gsheet_family() -> str | None:
    """Most recent refreshed_at across main workbook (gsheet) and regional gsheet_kw / gsheet_ae / gsheet_bh."""
    from datetime import datetime, timezone

    best_dt: datetime | None = None
    best_ts: str | None = None
    for src in _GSHEET_FAMILY_REFRESH_SOURCES:
        ts = get_last_refresh(src)
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.min.replace(tzinfo=timezone.utc)
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best_ts = ts
    return best_ts


def _backfill_gsheet_family_refresh_metadata() -> None:
    """If tab data exists for a gsheet* source but refresh_metadata row is missing, record now (fixes empty DB upgrades)."""
    try:
        with get_conn() as c:
            rows = c.execute(
                f"SELECT DISTINCT source FROM generic_tab_data WHERE source IN ({','.join('?' * len(_GSHEET_FAMILY_REFRESH_SOURCES))})",
                _GSHEET_FAMILY_REFRESH_SOURCES,
            ).fetchall()
        for (src,) in rows:
            if src and not get_last_refresh(src):
                set_last_refresh(src)
    except Exception:
        pass


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
    """Return human-readable relative time for status pill, e.g. 'Refreshed 2 min ago'."""
    if not last_ts:
        return "Never refreshed"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_sec = (now - dt).total_seconds()
        if age_sec < 60:
            return "Refreshed just now"
        if age_sec < 3600:
            m = int(age_sec / 60)
            return f"Refreshed {m} min ago"
        if age_sec < 86400:
            h = int(age_sec / 3600)
            return f"Refreshed {h} hour ago" if h == 1 else f"Refreshed {h} hours ago"
        d = int(age_sec / 86400)
        return f"Refreshed {d} day ago" if d == 1 else f"Refreshed {d} days ago"
    except Exception:
        return "Refreshed —"


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


def _source_refresh_is_stale(source: str, minutes: int = 15) -> bool:
    """True if no refresh recorded for `source` or last refresh older than `minutes`."""
    ts = get_last_refresh(source)
    if not ts:
        return True
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
        return age_sec > minutes * 60
    except Exception:
        return True


def _mobile_mode_enabled() -> bool:
    """Auto-detect mobile/tablet clients to enable compact rendering."""
    if "_mobile_detected" in st.session_state:
        return bool(st.session_state.get("_mobile_detected"))
    enabled = False
    try:
        # Explicit query override if needed: ?mobile=1 or ?mobile=0
        q = getattr(st, "query_params", None)
        if q is not None:
            raw = q.get("mobile")
            if isinstance(raw, list):
                raw = raw[0] if raw else ""
            raw_s = str(raw or "").strip().lower()
            if raw_s in ("1", "true", "yes", "y", "on"):
                enabled = True
            elif raw_s in ("0", "false", "no", "n", "off"):
                enabled = False
            else:
                ctx = getattr(st, "context", None)
                headers = getattr(ctx, "headers", {}) if ctx is not None else {}
                ua = str((headers or {}).get("user-agent", "")).lower()
                enabled = any(tok in ua for tok in ("iphone", "android", "mobile", "ipad", "tablet"))
    except Exception:
        enabled = False
    st.session_state["_mobile_detected"] = enabled
    return enabled


def _compact_layout_enabled() -> bool:
    """Global compact layout mode for phones/small screens."""
    return bool(_mobile_mode_enabled())


def _kitchen_master_region_selector_ui(allowed_regions: set[str] | None = None) -> str:
    """Kuwait / UAE / Bahrain chips; main KSA workbook is default. **Main** only when returning from a region.

    ``allowed_regions`` can restrict visible markets for market-scoped users.
    """
    _regional = {v for _, v in KITCHEN_MASTER_REGION_ROW}
    if allowed_regions:
        _regional = {r for r in _regional if r in allowed_regions}
    _allowed = _regional | {KITCHEN_MASTER_SUBVIEW_MAIN}
    if SESSION_KEY_KITCHEN_MASTER_REGION not in st.session_state:
        st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION] = KITCHEN_MASTER_SUBVIEW_MAIN
    cur = st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION]
    if cur == "KSA":
        cur = KITCHEN_MASTER_SUBVIEW_MAIN
        st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION] = cur
    if cur not in _allowed:
        cur = KITCHEN_MASTER_SUBVIEW_MAIN
        st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION] = cur
    _pairs = [(lbl, val) for lbl, val in KITCHEN_MASTER_REGION_ROW if val in _regional]
    if not _pairs:
        return KITCHEN_MASTER_SUBVIEW_MAIN
    label_to_val = dict(_pairs)
    val_to_label = {v: lbl for lbl, v in _pairs}
    _row_labels = [lbl for lbl, _ in _pairs]
    _mobile_opts = ["Main"] + _row_labels
    if _compact_layout_enabled():
        _cur_label = "Main" if cur == KITCHEN_MASTER_SUBVIEW_MAIN else val_to_label[cur]
        _sel_label = st.selectbox(
            "Market",
            options=_mobile_opts,
            index=_mobile_opts.index(_cur_label) if _cur_label in _mobile_opts else 0,
            key="kitchen_master_region_mobile_selector",
        )
        _next = (
            KITCHEN_MASTER_SUBVIEW_MAIN
            if _sel_label == "Main"
            else label_to_val[_sel_label]
        )
        if _next != cur:
            st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION] = _next
            _rerun()
        return str(st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION])
    if cur != KITCHEN_MASTER_SUBVIEW_MAIN:
        if st.button("Main", key="km_region_back_main", use_container_width=True):
            st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION] = KITCHEN_MASTER_SUBVIEW_MAIN
            _rerun()
    r_cols = st.columns(len(_pairs))
    for i, (lbl, val) in enumerate(_pairs):
        with r_cols[i]:
            if st.button(
                lbl,
                key=f"km_region_tab_{i}_{val}",
                type="primary" if cur == val else "secondary",
                use_container_width=True,
            ):
                st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION] = val
                _rerun()
    return str(st.session_state[SESSION_KEY_KITCHEN_MASTER_REGION])


def _use_compact_tables() -> bool:
    """Whether to use lightweight dataframe tables (vs AgGrid) for current client."""
    # User requested same web-style table/filter behavior on all devices.
    return False


def _facility_pill_picker(labels: list, *, key: str, label: str = "Facility") -> str:
    """Tab-like horizontal picker that mounts only one item's content at a time.

    Uses st.segmented_control when available (looks like tabs natively, Streamlit >=1.39);
    falls back to st.radio(horizontal=True) on older Streamlit. Importantly this returns
    the chosen label instead of rendering all options' contents in parallel like st.tabs,
    so mobile Safari does not OOM-crash when many facilities are selected.
    """
    labels = [str(l) for l in (labels or [])]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    _seg = getattr(st, "segmented_control", None)
    if callable(_seg):
        try:
            picked = _seg(
                label,
                options=labels,
                default=labels[0],
                key=key,
                label_visibility="collapsed",
            )
            return picked if picked in labels else labels[0]
        except Exception:
            pass
    picked = st.radio(
        label,
        options=labels,
        horizontal=True,
        key=key,
        label_visibility="collapsed",
    )
    return picked if picked in labels else labels[0]


def _table_height_px(default: int = 700) -> int:
    """Adaptive table height; supports expanded table view on mobile."""
    return default


def _kitchen_master_viewport_height_px(n_rows: int) -> int:
    """Native ``st.dataframe`` / fallback height from row count."""
    cap = max(280, int(_table_height_px()))
    n = max(0, int(n_rows))
    if n <= 8:
        overhead, per_row = 52, 28
    elif n <= 40:
        overhead, per_row = 72, 30
    else:
        overhead, per_row = 110, 34
    h = overhead + max(1, min(n, 800)) * per_row
    return max(110, min(cap, h))


def _kitchen_master_aggrid_iframe_height_px(n_rows: int, *, auto_height_layout: bool) -> int:
    """Streamlit-aggrid iframe height. When Ag Grid uses ``domLayout: autoHeight``, keep the iframe tight so the blank band disappears.

    Minimum height must cover toolbar + header + floating-filter row; otherwise the iframe clips to ~0 body
    and the grid looks empty on Streamlit Cloud.
    """
    n = max(0, int(n_rows))
    cap = max(280, int(_table_height_px()))
    if auto_height_layout:
        # autoHeight: grid body matches row count; wrapper height only needs chrome + rows
        h = 58 + max(1, min(n, 500)) * 30 + 24
        return max(220, min(cap, h))
    base = _kitchen_master_viewport_height_px(n)
    # normal layout: viewport math can dip to ~110px — too small once toolbar + floating filters are on
    return max(380, min(cap, base))


def _is_pandas_styler(x) -> bool:
    """True if ``x`` is a pandas Styler (used to avoid column_config that would strip row colors)."""
    return type(x).__name__ == "Styler" and hasattr(x, "data")


def _kitchen_master_row_count_caption(placeholder, text: str) -> None:
    """Row count line below (or in) the grid — avoid ``st.empty()`` above the table (extra vertical gap)."""
    if placeholder is not None:
        placeholder.caption(text)
    else:
        st.caption(text)


def _secrets_or_env_str(*names: str) -> str:
    """Read a string from ``st.secrets`` (Streamlit Cloud) and/or ``os.environ``.

    Cloud app secrets are **not** always mirrored into the process environment; check both.
    """
    for name in names:
        try:
            if hasattr(st, "secrets") and st.secrets is not None:
                v = st.secrets.get(name)
                if v is not None and str(v).strip() != "":
                    return str(v).strip()
        except Exception:
            pass
    for name in names:
        v = os.environ.get(name, "")
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def _production_safe_mode_enabled() -> bool:
    """Production safety guardrail (default ON).

    Set ``PRODUCTION_SAFE_MODE=0`` only in non-production environments when you
    intentionally want to allow experimental behavior.

    This flag does **not** change Kitchen Master row colors, filters, or data refresh —
    only future opt-in experimental UI (see ``_experimental_changes_allowed``).
    """
    raw = (_secrets_or_env_str("PRODUCTION_SAFE_MODE", "production_safe_mode") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _experimental_changes_allowed() -> bool:
    """Experimental behavior is opt-in and blocked by production-safe mode.

    Requires BOTH:
    - ``PRODUCTION_SAFE_MODE=0``
    - ``ALLOW_EXPERIMENTAL_UI=1`` (or true/yes/on)
    """
    if _production_safe_mode_enabled():
        return False
    raw = (
        _secrets_or_env_str("ALLOW_EXPERIMENTAL_UI", "allow_experimental_ui")
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _kitchen_master_plain_tables() -> bool:
    """When True, native ``st.dataframe`` skips Pandas Styler (no row colors).

    **Default False** — status row colors apply (Vacant / Occupied / Churning / no status / Vacant+opp) in Ag Grid and in the dataframe fallback.

    Remove ``KITCHEN_MASTER_PLAIN_TABLES`` from secrets (or set ``0``) if colors disappeared. Set ``KITCHEN_MASTER_PLAIN_TABLES=1`` only if Styler breaks rendering on your browser.
    Legacy: ``KITCHEN_MASTER_STYLED_ROWS=0`` also forces plain (no colors).
    """
    plain = (
        _secrets_or_env_str(
            "KITCHEN_MASTER_PLAIN_TABLES",
            "kitchen_master_plain_tables",
            "KITCHEN_MASTER_NO_ROW_COLORS",
        )
        or ""
    ).strip().lower()
    if plain in ("1", "true", "yes", "on"):
        return True
    legacy = (
        _secrets_or_env_str("KITCHEN_MASTER_STYLED_ROWS", "kitchen_master_styled_rows") or ""
    ).strip().lower()
    if legacy in ("0", "false", "no", "off"):
        return True
    return False


def _kitchen_master_use_aggrid() -> bool:
    """Kitchen Master uses Ag Grid (sheet-style filters + row colors) by default. Set ``KITCHEN_MASTER_AGGRID=0`` in secrets/env only if the iframe fails on your host."""
    v = (
        _secrets_or_env_str("KITCHEN_MASTER_AGGRID", "kitchen_master_aggrid")
        or "1"
    ).strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _aggrid_enterprise_license_key() -> str | None:
    """Paid AG Grid Enterprise key (removes the evaluation watermark). Optional if trial mode is on."""
    for name in ("AG_GRID_LICENSE_KEY", "ag_grid_license_key", "AGGRID_LICENSE_KEY"):
        try:
            sec = getattr(st, "secrets", None)
            if sec:
                v = sec.get(name)
                if v is not None and str(v).strip():
                    return str(v).strip()
        except Exception:
            pass
    try:
        v = (os.environ.get("AG_GRID_LICENSE_KEY") or os.environ.get("AGGRID_LICENSE_KEY") or "").strip()
        return v or None
    except Exception:
        return None


def _aggrid_use_enterprise_modules() -> bool:
    """Load AG Grid Enterprise in the iframe (Set Filter = checkbox value lists).

    streamlit-aggrid ships Enterprise; **without** ``AG_GRID_LICENSE_KEY`` AG Grid runs in evaluation mode
    (watermark) but Set Filter still works — same as many local “no licence” setups.

    Set ``AG_GRID_ENTERPRISE_TRIAL=0`` (secrets/env) to use **Community** filters only + optional Streamlit multiselect.
    """
    if _aggrid_enterprise_license_key():
        return True
    v = (_secrets_or_env_str("AG_GRID_ENTERPRISE_TRIAL", "ag_grid_enterprise_trial") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _kitchen_master_streamlit_value_list_filters() -> bool:
    """When True, show multiselect value lists above the grid (Status). Off when Enterprise modules load (trial or licensed)."""
    if _aggrid_use_enterprise_modules():
        return False
    v = (_secrets_or_env_str("KITCHEN_MASTER_VALUE_FILTERS", "kitchen_master_value_filters") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _apply_streamlit_status_value_filter(
    df_ag: pd.DataFrame,
    rows_shown: list | None,
    *,
    status_col: str | None,
    grid_key: str,
) -> tuple[pd.DataFrame, list | None]:
    """Excel-style value list for Status: pick which distinct cell values to keep (Community Ag Grid cannot show Set Filter)."""
    if df_ag is None or df_ag.empty or not status_col:
        return df_ag, rows_shown
    sc = str(status_col)
    if sc not in df_ag.columns:
        return df_ag, rows_shown

    def _lab(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "(blank)"
        s = str(v).strip()
        return "(blank)" if s == "" else s

    labels = df_ag[sc].map(_lab)
    uniques = sorted(set(labels.tolist()))
    if len(uniques) <= 1 or len(uniques) > 250:
        return df_ag, rows_shown

    sel = st.multiselect(
        f"{sc} — show rows with",
        options=uniques,
        default=uniques,
        key=f"{grid_key}_st_status_value_pick",
        help="Choose which values to keep. Or leave Enterprise trial on (default) for checkbox lists inside the grid; set AG_GRID_ENTERPRISE_TRIAL=0 for Community-only.",
    )
    if not sel:
        st.warning("Select at least one value above, or reset the widget.")
        return df_ag.iloc[0:0].copy(), []
    m = labels.isin(sel)
    out_df = df_ag.loc[m].reset_index(drop=True)
    out_rows = rows_shown
    if rows_shown is not None and len(rows_shown) == len(m):
        out_rows = [r for r, ok in zip(rows_shown, m.tolist()) if ok]
    return out_df, out_rows


def _kitchen_master_status_row_style_from_class(cls_name: str) -> tuple[str, str | None]:
    """(background hex, optional color) aligned with Ag Grid ``_aggrid_kitchen_master_status_custom_css``."""
    m = {
        "status-no-status": ("#B22222", "white"),
        "status-vacant": ("#D1FAE5", None),
        "status-vacant-opp": ("#FEE2E2", None),
        "status-churning": ("#FDE68A", None),
        "status-occupied": ("#FEE2E2", None),
    }
    return m.get(cls_name, ("#B22222", "white"))


def _style_df_status_rows(df: pd.DataFrame, status_col: str | None):
    """Apply row status colors in non-AgGrid paths (mobile/tablet fallback)."""
    if df is None or df.empty or not status_col:
        return df

    def _row_bg(row):
        v = row.get(status_col)
        hop = bool(row.get("_has_opportunity", False))
        cls_name = _kitchen_master_row_css_class_from_values(v, hop)
        bg, fg = _kitchen_master_status_row_style_from_class(cls_name)
        if fg:
            return [f"background-color: {bg}; color: {fg}"] * len(row)
        return [f"background-color: {bg}"] * len(row)

    return df.style.apply(_row_bg, axis=1)


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
    keys = [k for k in rows[0].keys() if k not in _INTERNAL_CSV_EXPORT_KEYS]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in keys})
    return buf.getvalue()


def _secrets_get_export_allowed_raw():
    """Resolve EXPORT_* from top-level secrets or nested TOML tables (e.g. [export] EXPORT_ALLOWED_IDS = ...)."""

    def _nonempty(v):
        if v is None:
            return False
        if isinstance(v, str):
            return bool(v.strip())
        if isinstance(v, (list, dict)):
            return len(v) > 0
        return True

    names = (
        "EXPORT_ALLOWED_IDS",
        "export_allowed_ids",
        "EXPORT_ALLOWED_USERS",
        "export_allowed_users",
        "ALLOWED_EXPORT_IDS",
        "allowed_export_ids",
    )
    try:
        sec = getattr(st, "secrets", None)
        if sec:
            for name in names:
                v = sec.get(name)
                if _nonempty(v):
                    return v
            for val in sec.values():
                if isinstance(val, dict):
                    for name in names:
                        v = val.get(name)
                        if _nonempty(v):
                            return v
    except Exception:
        pass
    return None


def _export_allowed_ids_from_secrets() -> set[str]:
    """IDs (emails) allowed to export. Merges EXPORT_ALLOWED_IDS (code) with secrets/env."""
    try:
        raw = (
            _secrets_get_export_allowed_raw()
            or os.environ.get("EXPORT_ALLOWED_IDS", "")
            or os.environ.get("EXPORT_ALLOWED_USERS", "")
            or os.environ.get("ALLOWED_EXPORT_IDS", "")
        )
    except Exception:
        raw = (
            os.environ.get("EXPORT_ALLOWED_IDS", "")
            or os.environ.get("EXPORT_ALLOWED_USERS", "")
            or os.environ.get("ALLOWED_EXPORT_IDS", "")
        )
    out: set[str] = set()
    if isinstance(raw, dict):
        # Accept {"email@x.com": true, ...}
        for k, v in raw.items():
            try:
                allowed = bool(v) if not isinstance(v, str) else v.strip().lower() in ("1", "true", "yes", "y")
            except Exception:
                allowed = False
            s = (str(k).strip() or "").lower()
            if s and allowed:
                out.add(s)
    elif isinstance(raw, list):
        for item in raw:
            s = (str(item).strip() or "").lower()
            if s:
                out.add(s)
    else:
        parts = re.split(r"[,\n;\s]+", str(raw or ""))
        for part in parts:
            s = (part or "").strip().lower()
            if s:
                out.add(s)
    for part in re.split(r"[,\n;\s]+", str(EXPORT_ALLOWED_IDS or "").strip()):
        s = (part or "").strip().lower()
        if s:
            out.add(s)
    return out


def _secrets_preview_value_nonempty(v) -> bool:
    """True if this secret value should be used (skip empty list/dict/string so a later key like PREVIEW_ONLY_IDS is read)."""
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) > 0
    return True


def _secrets_get_bahrain_preview_raw():
    """BAHRAIN_KITCHEN_PREVIEW_IDS from secrets (or nested tables); comma list or list of emails."""
    names = (
        "BAHRAIN_KITCHEN_PREVIEW_IDS",
        "bahrain_kitchen_preview_ids",
        "preview_only_IDs",
        "preview_only_ids",
        "PREVIEW_ONLY_IDS",
        "BAHRAIN_PREVIEW_USER_IDS",
        "bahrain_preview_user_ids",
    )
    try:
        sec = getattr(st, "secrets", None)
        if sec:
            for name in names:
                v = sec.get(name)
                if _secrets_preview_value_nonempty(v):
                    return v
            for val in sec.values():
                if isinstance(val, dict):
                    for name in names:
                        v = val.get(name)
                        if _secrets_preview_value_nonempty(v):
                            return v
    except Exception:
        pass
    env = (
        os.environ.get("BAHRAIN_KITCHEN_PREVIEW_IDS", "")
        or os.environ.get("PREVIEW_ONLY_IDS", "")
        or os.environ.get("BAHRAIN_PREVIEW_USER_IDS", "")
    )
    return env if env.strip() else ""


def _merge_ids_from_preview_raw_into(out: set[str], raw) -> None:
    """Parse one secrets blob (dict / list / string) into ``out``."""
    if raw is None:
        return
    if isinstance(raw, dict):
        _list_keys = frozenset(
            {
                "emails",
                "ids",
                "users",
                "list",
                "items",
                "preview_only_ids",
                "preview_only_ids_list",
            }
        )

        def _value_allows_entry(v) -> bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return v != 0
            if isinstance(v, str):
                t = v.strip().lower()
                return bool(t) and t not in ("0", "false", "no", "n", "off", "disabled")
            return bool(v)

        for k, v in raw.items():
            lk = str(k).strip().lower()
            if lk in _list_keys or lk.endswith("_ids") or lk.endswith("_emails"):
                if isinstance(v, (list, tuple)):
                    for item in v:
                        s = (str(item).strip() or "").lower()
                        if s:
                            out.add(s)
                    continue
            if isinstance(v, (list, tuple)):
                strip_items = [(str(item).strip() or "").lower() for item in v if str(item).strip()]
                if strip_items and all("@" in x for x in strip_items):
                    for s in strip_items:
                        out.add(s)
                continue
            sk = str(k).strip()
            if not sk:
                continue
            if "@" in sk and _value_allows_entry(v):
                out.add(sk.lower())
                continue
            if isinstance(v, str) and "@" in v.strip() and _value_allows_entry(v):
                out.add(v.strip().lower())
    elif isinstance(raw, list):
        for item in raw:
            s = (str(item).strip() or "").lower()
            if s:
                out.add(s)
    else:
        for part in re.split(r"[,\n;\s]+", str(raw or "")):
            s = (part or "").strip().lower()
            if s:
                out.add(s)


def _iter_all_bahrain_preview_secret_blobs():
    """Yield every non-empty PREVIEW / BAHRAIN preview blob (top-level + nested TOML tables) — not only the first key."""
    names = (
        "BAHRAIN_KITCHEN_PREVIEW_IDS",
        "bahrain_kitchen_preview_ids",
        "preview_only_IDs",
        "preview_only_ids",
        "PREVIEW_ONLY_IDS",
        "BAHRAIN_PREVIEW_USER_IDS",
        "bahrain_preview_user_ids",
    )
    try:
        sec = getattr(st, "secrets", None)
        if sec:
            for name in names:
                v = sec.get(name)
                if _secrets_preview_value_nonempty(v):
                    yield v
            for val in sec.values():
                if isinstance(val, dict):
                    for name in names:
                        v = val.get(name)
                        if _secrets_preview_value_nonempty(v):
                            yield v
    except Exception:
        pass
    env = (
        os.environ.get("BAHRAIN_KITCHEN_PREVIEW_IDS", "")
        or os.environ.get("PREVIEW_ONLY_IDS", "")
        or os.environ.get("BAHRAIN_PREVIEW_USER_IDS", "")
    )
    if env.strip():
        yield env.strip()


def _email_set_with_local_parts(ids: set[str]) -> set[str]:
    """For each ``user@domain`` entry, also allow matching the local part alone (helps SSO / display quirks)."""
    out: set[str] = set()
    for x in ids or ():
        s = (x or "").strip().lower()
        if not s:
            continue
        out.add(s)
        if "@" in s:
            out.add(s.split("@", 1)[0])
    return out


def _market_view_ids_from_secrets(market: str) -> set[str]:
    """Emails scoped to a single market view (KSA/UAE/Kuwait/Bahrain), lowercased."""
    m = (market or "").strip().lower()
    if m == "ksa":
        keys = ("MARKET_VIEW_KSA_IDS", "market_view_ksa_ids")
        built_in = MARKET_VIEW_KSA_IDS
    elif m == "uae":
        keys = ("MARKET_VIEW_UAE_IDS", "market_view_uae_ids")
        built_in = MARKET_VIEW_UAE_IDS
    elif m == "kuwait":
        keys = ("MARKET_VIEW_KUWAIT_IDS", "market_view_kuwait_ids", "MARKET_VIEW_KW_IDS", "market_view_kw_ids")
        built_in = MARKET_VIEW_KUWAIT_IDS
    elif m == "bahrain":
        keys = ("MARKET_VIEW_BAHRAIN_IDS", "market_view_bahrain_ids")
        built_in = MARKET_VIEW_BAHRAIN_IDS
    else:
        return set()
    out: set[str] = set()

    def _merge_blob(raw_blob: object) -> None:
        for part in re.split(r"[,\n;\s]+", str(raw_blob or "").strip()):
            s = (part or "").strip().lower()
            if s:
                out.add(s)

    for key in keys:
        try:
            raw = st.secrets.get(key)
        except Exception:
            raw = None
        # Support nested secrets tables (e.g. keys accidentally placed under another TOML section).
        try:
            sec = getattr(st, "secrets", None)
            if sec:
                for val in sec.values():
                    if isinstance(val, dict) and key in val:
                        _merge_blob(val.get(key))
        except Exception:
            pass
        if raw is None:
            raw = os.environ.get(key, "")
        _merge_blob(raw)
    _merge_blob(built_in)
    return out


def _market_scope_for_user(current_user: str | None, user_role: str | None) -> str | None:
    """Return user market scope: 'Saudi Arabia' / 'UAE' / 'Kuwait' / 'Bahrain', else None (=all countries).

    Market list membership takes precedence over RBAC role so users mapped to a market
    are consistently scoped even if they also have elevated role labels.
    """
    if _is_developer():
        return None
    u = (current_user or "").strip().lower()
    if not u:
        return None
    local = u.split("@", 1)[0] if "@" in u else u
    checks = (
        ("Saudi Arabia", _market_view_ids_from_secrets("ksa")),
        ("UAE", _market_view_ids_from_secrets("uae")),
        ("Kuwait", _market_view_ids_from_secrets("kuwait")),
        ("Bahrain", _market_view_ids_from_secrets("bahrain")),
    )
    for label, ids in checks:
        expanded = _email_set_with_local_parts(ids)
        if expanded and (u in expanded or local in expanded):
            return label
    return None


def _market_matches_for_user(current_user: str | None) -> list[str]:
    """Return all market labels matched by current_user using MARKET_VIEW_* lists."""
    u = (current_user or "").strip().lower()
    if not u:
        return []
    local = u.split("@", 1)[0] if "@" in u else u
    checks = (
        ("Saudi Arabia", _market_view_ids_from_secrets("ksa")),
        ("UAE", _market_view_ids_from_secrets("uae")),
        ("Kuwait", _market_view_ids_from_secrets("kuwait")),
        ("Bahrain", _market_view_ids_from_secrets("bahrain")),
    )
    out: list[str] = []
    for label, ids in checks:
        expanded = _email_set_with_local_parts(ids)
        if expanded and (u in expanded or local in expanded):
            out.append(label)
    return out


def _market_membership_debug(current_user: str | None) -> list[tuple[str, bool, int]]:
    """Return per-market debug tuples: (label, matches_user, configured_ids_count)."""
    u = (current_user or "").strip().lower()
    local = u.split("@", 1)[0] if "@" in u else u
    checks = (
        ("Saudi Arabia", _market_view_ids_from_secrets("ksa")),
        ("UAE", _market_view_ids_from_secrets("uae")),
        ("Kuwait", _market_view_ids_from_secrets("kuwait")),
        ("Bahrain", _market_view_ids_from_secrets("bahrain")),
    )
    out: list[tuple[str, bool, int]] = []
    for label, ids in checks:
        expanded = _email_set_with_local_parts(ids)
        matched = bool(expanded and u and (u in expanded or local in expanded))
        out.append((label, matched, len(ids)))
    return out


def _bahrain_preview_ids_from_secrets() -> set[str]:
    """Emails allowed for Kitchen Master regional previews (Kuwait, UAE, Bahrain). Merges all PREVIEW_* secrets + built-in tuple."""
    out: set[str] = set()
    for blob in _iter_all_bahrain_preview_secret_blobs():
        _merge_ids_from_preview_raw_into(out, blob)
    for part in re.split(r"[,\n;\s]+", str(PREVIEW_ONLY_IDS or "").strip()):
        s = (part or "").strip().lower()
        if s:
            out.add(s)
    return out


def _user_can_see_bahrain_kitchen_preview(current_user: str) -> bool:
    """True if user may see Kitchen Master Kuwait/UAE/Bahrain (not only KSA).

    Developer always; else PREVIEW_ONLY_IDS + secrets; and EXPORT_ALLOWED_IDS users
    also get regional access so they can export from any sheet/country.
    """
    if _is_developer():
        return True
    u = (current_user or "").strip().lower()
    if not u:
        return False
    # Export allowlist should work across all regional sheets, not only KSA.
    if _can_user_export(u):
        return True
    preview_norm = _email_set_with_local_parts(_bahrain_preview_ids_from_secrets())
    if not preview_norm:
        return False
    local = u.split("@", 1)[0] if "@" in u else u
    return u in preview_norm or local in preview_norm


def _email_has_dashboard_country_allowlist(current_user: str) -> bool:
    """True if email is on DEVELOPER_IDS or SUPER_USER_* secrets — same grants as RBAC, for when session role lags DB/secrets."""
    u = (current_user or "").strip().lower()
    if not u:
        return False
    local = u.split("@", 1)[0] if "@" in u else u
    try:
        dev_exp = _email_set_with_local_parts(set(_developer_ids_merged_list()))
        if u in dev_exp or local in dev_exp:
            return True
        sup_exp = _email_set_with_local_parts(set(_get_super_user_emails()))
        if u in sup_exp or local in sup_exp:
            return True
    except Exception:
        pass
    return False


def _user_sees_dashboard_all_countries(current_user: str | None, user_role: str | None) -> bool:
    """Dashboard: show all country filter options (Saudi Arabia, Bahrain, Kuwait, UAE), merge Bahrain rows, regional facility tabs.

    - Emails in ``PREVIEW_ONLY_IDS`` / ``BAHRAIN_KITCHEN_PREVIEW_IDS`` (Streamlit secrets or env) and the built-in
      ``PREVIEW_ONLY_IDS`` tuple — same set as :func:`_user_can_see_bahrain_kitchen_preview`.
    - ``super_user`` and ``manager_viewer`` always (they already have Dashboard access).
    - ``DEVELOPER_IDS`` / ``SUPER_USER_EMAILS`` match even if :func:`auth.get_user_role` returned associate (defense in depth).
    """
    if _is_developer():
        return True
    if _email_has_dashboard_country_allowlist(current_user or ""):
        return True
    if _user_can_see_bahrain_kitchen_preview(current_user or ""):
        return True
    r = (user_role or "").strip().lower()
    return r in ("super_user", "manager_viewer")


def _can_user_export(current_user: str) -> bool:
    """True only when current_user matches EXPORT_ALLOWED_IDS (or alias keys: export_allowed_ids, etc.).

    Developer / super_user roles do not grant export — add the email to EXPORT_ALLOWED_IDS if they should export.
    If the export list is empty, nobody may export.
    """
    u = (current_user or "").strip().lower()
    if not u:
        return False
    export_set = _export_allowed_ids_from_secrets()
    export_norm = {(a or "").strip().lower() for a in export_set if (a or "").strip()}
    if not export_norm:
        return False
    if "@" in u:
        local = u.split("@", 1)[0]
    else:
        local = u
    return u in export_norm or local in export_norm


def _render_export_button(rows: list[dict], file_stem: str, key: str):
    """Render CSV download button when rows exist."""
    if rows is None:
        return
    # grid_response["data"] can be a pandas DataFrame in some st_aggrid versions.
    if hasattr(rows, "to_dict"):
        try:
            rows = rows.to_dict("records")
        except Exception:
            rows = []
    if not isinstance(rows, list) or len(rows) == 0:
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


# Tab IDs hidden from Kitchen Master Data facility multiselect for EVERY signed-in user (same list for all — not RBAC).
# Product invariant: KSA Kitchen Master must expose every other refreshed workbook tab as a selectable facility.
# Do not filter this list by user/email/role without explicit product sign-off and a separate opt-in flag.
# Hidden tabs: Auto Refresh Execution Log, SF Kitchen Data, SF Churn Data, KSA Facility details, Pivot Table 11, etc.
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
    """All KSA workbook facility tabs for Kitchen Master (ordered like the Google Sheet).

    Same tab IDs for every user. Only ``MASTER_KITCHENS_HIDDEN_TABS`` is subtracted — never filter by
    ``current_user`` or allowlist here; that would break the main KSA tracker audience.
    """
    _hidden_lower = {s.strip().lower() for s in MASTER_KITCHENS_HIDDEN_TABS}
    # Match workbook tab order when available (same order as the Google Sheet); then any extra tabs with data.
    ordered = list_gsheet_tab_ids_in_sheet_order()
    if not ordered:
        ordered = list_tab_ids_for_source("gsheet")
    return [t for t in ordered if (t or "").strip().lower() not in _hidden_lower]


def _master_kitchens_sources() -> list[tuple[str, str]]:
    """(display_name, source_id) for the Kitchen Master facility multiselect — full KSA sheet list, identical for all users."""
    return [(tab_id, tab_id) for tab_id in _master_kitchens_other_sheet_ids()]


def _dashboard_load_gsheet_rows_with_sheet_stamp() -> list[dict]:
    """Load KSA master-kitchen tabs with Sheet = worksheet title (same facility names as Kitchen Master Data)."""
    out: list[dict] = []
    for tab_id in _master_kitchens_other_sheet_ids():
        for r in list_generic_tab(tab_id, source="gsheet") or []:
            if not isinstance(r, dict) or _is_empty_record(r):
                continue
            row = dict(r)
            row["Sheet"] = tab_id
            out.append(row)
    return _filter_junk_kitchen_records(out)


def _dashboard_facility_from_row(row) -> str:
    """Facility label aligned with Kitchen Master: prefer worksheet tab (Sheet), then Account / Facility columns."""
    if not row or not isinstance(row, dict):
        return ""
    for k in ("Sheet", "sheet"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    for k in ("Account Name", "Account__r.Name", "facility", "Facility"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _dashboard_load_source(source_id: str) -> list[dict]:
    """Load rows for the given dashboard source_id."""
    if source_id == "main_tracker":
        return list_rows()
    if source_id == "exec_log":
        return list_exec_log()  # already list of dicts
    return _filter_junk_kitchen_records(list_generic_tab(source_id))


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
            out[tab_id] = _filter_junk_kitchen_records(matches)

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
    _clear_list_generic_tab_cache()


def _regional_sheet_rows_for_sqlite(ws_rows: list[dict]) -> list[dict]:
    """Persist at least one row so empty worksheets still appear in facility/tab pickers."""
    return ws_rows if ws_rows else [{}]


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
    worksheets = list(spreadsheet.worksheets())
    # Parallelize the per-worksheet get_all_values() calls. gspread is safe for concurrent
    # reads against distinct worksheet objects; the serial loop dominated refresh time
    # (one HTTPS round-trip per tab) and was the main reason cold-start refreshes felt slow.
    from concurrent.futures import ThreadPoolExecutor

    def _load(ws):
        try:
            return ws.title, ws.get_all_values()
        except Exception:
            return ws.title, []

    out: dict[str, list[dict]] = {}
    if worksheets:
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(worksheets)))) as pool:
            for title, rows in pool.map(_load, worksheets):
                if not rows:
                    out[title] = []
                    continue
                headers = [str(h).strip() or f"_col{i}" for i, h in enumerate(rows[0])]
                data = []
                for row in rows[1:]:
                    r = list(row) + [""] * (len(headers) - len(row))
                    data.append(dict(zip(headers, r[: len(headers)])))
                out[title] = data
    return out


def _regional_kitchen_workbook_settings(region: str) -> tuple[str | None, int | None, str, str]:
    """Return (spreadsheet_id, worksheet_gid_default, legacy_tab_id, sqlite source) for Kuwait, UAE, or Bahrain."""
    secrets = getattr(st, "secrets", None) or {}

    def _as_int(v, default: int) -> int:
        try:
            return int(str(v).strip())
        except Exception:
            return default

    if region == "Kuwait":
        sid = (
            (secrets.get("kuwait_kitchen_sheet_id") or secrets.get("KUWAIT_KITCHEN_SHEET_ID") or "")
            or os.environ.get("KUWAIT_KITCHEN_SHEET_ID", "")
            or KUWAIT_KITCHEN_SHEET_ID
        ).strip()
        gid = _as_int(
            secrets.get("kuwait_kitchen_worksheet_gid") or secrets.get("KUWAIT_KITCHEN_WORKSHEET_GID") or os.environ.get("KUWAIT_KITCHEN_WORKSHEET_GID"),
            KUWAIT_KITCHEN_WORKSHEET_GID,
        )
        return (sid or None, gid, TAB_ID_KITCHEN_KW, GSOURCE_KITCHEN_KW)
    if region == "UAE":
        sid = (
            (secrets.get("uae_kitchen_sheet_id") or secrets.get("UAE_KITCHEN_SHEET_ID") or "")
            or os.environ.get("UAE_KITCHEN_SHEET_ID", "")
            or UAE_KITCHEN_SHEET_ID
        ).strip()
        gid = _as_int(
            secrets.get("uae_kitchen_worksheet_gid") or secrets.get("UAE_KITCHEN_WORKSHEET_GID") or os.environ.get("UAE_KITCHEN_WORKSHEET_GID"),
            UAE_KITCHEN_WORKSHEET_GID,
        )
        return (sid or None, gid, TAB_ID_KITCHEN_AE, GSOURCE_KITCHEN_AE)
    if region == "Bahrain":
        sid = (
            (secrets.get("bahrain_kitchen_sheet_id") or secrets.get("BAHRAIN_KITCHEN_SHEET_ID") or "")
            or os.environ.get("BAHRAIN_KITCHEN_SHEET_ID", "")
            or BAHRAIN_KITCHEN_SHEET_ID
        ).strip()
        gid = _as_int(
            secrets.get("bahrain_kitchen_worksheet_gid") or secrets.get("BAHRAIN_KITCHEN_WORKSHEET_GID") or os.environ.get("BAHRAIN_KITCHEN_WORKSHEET_GID"),
            BAHRAIN_KITCHEN_WORKSHEET_GID,
        )
        return (sid or None, gid, TAB_ID_KITCHEN_BH, GSOURCE_KITCHEN_BH)
    return None, None, "", ""


def _fetch_gsheet_worksheet_by_gid(sheet_id: str, worksheet_gid: int, credentials_path: str) -> list[dict]:
    """Read a single worksheet by its gid (sheetId from the URL). Same auth as _fetch_online_sheet."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Install: pip install gspread google-auth") from None

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if credentials_path == "__FROM_SECRETS__":
        info = dict(st.secrets["gsheet_service_account"])
        info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
        info.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)

    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    ws = spreadsheet.get_worksheet_by_id(int(worksheet_gid))
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


def _regional_kitchen_target_gids(region: str) -> list[int] | None:
    """Optional gid filter per region; None means load all worksheets from workbook."""
    secrets = getattr(st, "secrets", None) or {}

    def _parse_gid_list(raw) -> list[int]:
        if not raw:
            return []
        out = []
        for token in str(raw).replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                out.append(int(token))
            except Exception:
                continue
        return out

    if region == "Kuwait":
        raw = (
            secrets.get("KUWAIT_KITCHEN_FACILITY_GIDS")
            or secrets.get("kuwait_kitchen_facility_gids")
            or os.environ.get("KUWAIT_KITCHEN_FACILITY_GIDS", "")
        )
        parsed = _parse_gid_list(raw)
        # Union with in-code defaults so new facilities ship without editing Streamlit secrets.
        code_gids = list(KUWAIT_KITCHEN_FACILITY_GIDS)
        if not parsed:
            base = code_gids
        else:
            seen: set[int] = set()
            base = []
            for g in code_gids + parsed:
                if g not in seen:
                    seen.add(g)
                    base.append(g)
        extra_raw = (
            secrets.get("KUWAIT_KITCHEN_EXTRA_FACILITY_GIDS")
            or secrets.get("kuwait_kitchen_extra_facility_gids")
            or os.environ.get("KUWAIT_KITCHEN_EXTRA_FACILITY_GIDS", "")
        )
        extra = _parse_gid_list(extra_raw)
        merge_seen: set[int] = set()
        merged: list[int] = []
        for g in base + extra:
            if g not in merge_seen:
                merge_seen.add(g)
                merged.append(g)
        return merged
    if region == "UAE":
        raw = (
            secrets.get("UAE_KITCHEN_FACILITY_GIDS")
            or secrets.get("uae_kitchen_facility_gids")
            or os.environ.get("UAE_KITCHEN_FACILITY_GIDS", "")
        )
        parsed = _parse_gid_list(raw)
        return parsed if parsed else list(UAE_KITCHEN_FACILITY_GIDS)
    if region == "Bahrain":
        raw = (
            secrets.get("BAHRAIN_KITCHEN_FACILITY_GIDS")
            or secrets.get("bahrain_kitchen_facility_gids")
            or os.environ.get("BAHRAIN_KITCHEN_FACILITY_GIDS", "")
        )
        parsed = _parse_gid_list(raw)
        return parsed if parsed else list(BAHRAIN_KITCHEN_FACILITY_GIDS)
    return None


def _fetch_regional_workbook_data(region: str, sheet_id: str, credentials_path: str) -> dict[str, list[dict]]:
    """Load selected worksheets by gid (if configured), otherwise full workbook."""
    target_gids = _regional_kitchen_target_gids(region)
    if not target_gids:
        return _fetch_online_sheet(sheet_id, credentials_path) or {}

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Install: pip install gspread google-auth") from None

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if credentials_path == "__FROM_SECRETS__":
        info = dict(st.secrets["gsheet_service_account"])
        info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
        info.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)

    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    # Resolve gid -> worksheet up front (cheap), then fetch values in parallel — same reason
    # as _fetch_online_sheet: the serial per-tab round-trip dominated refresh time.
    targets: list = []
    for gid in target_gids:
        try:
            ws = spreadsheet.get_worksheet_by_id(int(gid))
        except Exception:
            ws = None
        if ws is not None:
            targets.append((gid, ws))

    from concurrent.futures import ThreadPoolExecutor

    def _load(item):
        gid, ws = item
        title = str(ws.title).strip() or f"gid_{gid}"
        try:
            return title, ws.get_all_values()
        except Exception:
            return title, []

    out: dict[str, list[dict]] = {}
    if targets:
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as pool:
            for title, rows in pool.map(_load, targets):
                if not rows:
                    out[title] = []
                    continue
                headers = [str(h).strip() or f"_col{i}" for i, h in enumerate(rows[0])]
                ws_data = []
                for row in rows[1:]:
                    r = list(row) + [""] * (len(headers) - len(row))
                    ws_data.append(dict(zip(headers, r[: len(headers)])))
                out[title] = ws_data
    # Stale GID lists (e.g. after workbook rebuild) yield no tabs — load every worksheet instead.
    if not out:
        return _fetch_online_sheet(sheet_id, credentials_path) or {}
    return out


def _regional_preview_hidden_tab_names_lower() -> set[str]:
    """Tab titles to hide from regional facility pickers (legacy combined-tab names)."""
    return {
        (TAB_ID_KITCHEN_KW or "").strip().lower(),
        (TAB_ID_KITCHEN_AE or "").strip().lower(),
        (TAB_ID_KITCHEN_BH or "").strip().lower(),
        "standard master kitchen",
        "ksa master kitchen data",
    }


def _dashboard_kitchen_master_tab_names_for_country(
    ui_country: str, *, current_user: str | None = None, user_role: str | None = None
) -> list[str] | None:
    """Worksheet/facility names shown in Kitchen Master for this country (Dashboard facility filter). None = derive from rows only."""
    if not ui_country or ui_country in ("All", "(No country)"):
        return None
    s = (ui_country or "").strip()
    _reg = _user_sees_dashboard_all_countries(current_user, user_role)
    if s == "Kuwait":
        if not _reg:
            return None
        hidden = _regional_preview_hidden_tab_names_lower()
        return [t for t in list_tab_ids_for_source(GSOURCE_KITCHEN_KW) if (t or "").strip().lower() not in hidden]
    if s == "UAE":
        if not _reg:
            return None
        hidden = _regional_preview_hidden_tab_names_lower()
        return [t for t in list_tab_ids_for_source(GSOURCE_KITCHEN_AE) if (t or "").strip().lower() not in hidden]
    if s == "Bahrain":
        if _reg:
            hidden = _regional_preview_hidden_tab_names_lower()
            bh_tabs = [t for t in list_tab_ids_for_source(GSOURCE_KITCHEN_BH) if (t or "").strip().lower() not in hidden]
            if bh_tabs:
                return bh_tabs
        return None
    if s == "Saudi Arabia":
        return list(_master_kitchens_other_sheet_ids())
    return None


@st.cache_data(ttl=300, show_spinner=False)
def _list_generic_tab_cached(tab_id: str, *, source: str | None = None) -> list[dict]:
    """Read cache so facility switches and filter clicks don't re-query SQLite.
    Any write/refresh path goes through save_generic_tab, which clears this cache
    via _clear_list_generic_tab_cache — so stale reads aren't possible."""
    rows = list_generic_tab(tab_id, source=source) if source else list_generic_tab(tab_id)
    return rows or []


def _clear_list_generic_tab_cache() -> None:
    """Invalidate cached tab rows after any refresh/write path."""
    try:
        _list_generic_tab_cached.clear()
    except Exception:
        pass


def _refresh_kuwait_workbook_from_sheets(*, silent: bool = True) -> bool:
    """Fetch Kuwait facility sheets and persist under gsheet_kw. Returns True on success."""
    sid, _, _, gsource = _regional_kitchen_workbook_settings("Kuwait")
    creds_path = _get_google_credentials_path()
    if not creds_path or not sid:
        return False
    try:
        data = _fetch_regional_workbook_data("Kuwait", sid, creds_path) or {}
        if not data:
            if not silent:
                st.warning(
                    "No worksheets loaded for Kuwait. Share the workbook with the service account (Viewer) "
                    "and check KUWAIT_KITCHEN_SHEET_ID / facility GIDs in secrets."
                )
            return False
        with get_conn() as c:
            c.execute("DELETE FROM generic_tab_data WHERE source = ?", (gsource,))
        for ws_title, ws_rows in data.items():
            save_generic_tab(
                str(ws_title).strip() or ws_title,
                _regional_sheet_rows_for_sqlite(ws_rows or []),
                source=gsource,
            )
        _clear_list_generic_tab_cache()
        set_last_refresh(gsource)
        return True
    except Exception as e:
        if not silent:
            st.warning(f"Could not refresh Kuwait sheet: {type(e).__name__}: {e}")
        return False


def _load_kuwait_dashboard_rows() -> list[dict]:
    """All Kuwait facility-sheet rows from gsheet_kw, tagged with Account Country = Kuwait for dashboard filters."""
    hidden = _regional_preview_hidden_tab_names_lower()
    out: list[dict] = []
    for tab_id in list_tab_ids_for_source(GSOURCE_KITCHEN_KW):
        if (tab_id or "").strip().lower() in hidden:
            continue
        for r in _list_generic_tab_cached(tab_id, source=GSOURCE_KITCHEN_KW):
            if not isinstance(r, dict) or _is_empty_record(r):
                continue
            row = dict(r)
            row["Account Country"] = "Kuwait"
            row["Sheet"] = tab_id
            out.append(row)
    return out


def _refresh_uae_workbook_from_sheets(*, silent: bool = True) -> bool:
    """Fetch UAE facility sheets and persist under gsheet_ae. Returns True on success."""
    sid, _, _, gsource = _regional_kitchen_workbook_settings("UAE")
    creds_path = _get_google_credentials_path()
    if not creds_path or not sid:
        return False
    try:
        data = _fetch_regional_workbook_data("UAE", sid, creds_path) or {}
        if not data:
            if not silent:
                st.warning(
                    "No worksheets loaded for UAE. Share the workbook with the service account (Viewer) "
                    "and check UAE_KITCHEN_SHEET_ID / facility GIDs in secrets. "
                    "If the workbook was recreated, GIDs may be outdated — the app will load all tabs when none match."
                )
            return False
        with get_conn() as c:
            c.execute("DELETE FROM generic_tab_data WHERE source = ?", (gsource,))
        for ws_title, ws_rows in data.items():
            save_generic_tab(
                str(ws_title).strip() or ws_title,
                _regional_sheet_rows_for_sqlite(ws_rows or []),
                source=gsource,
            )
        _clear_list_generic_tab_cache()
        set_last_refresh(gsource)
        return True
    except Exception as e:
        if not silent:
            st.warning(f"Could not refresh UAE sheet: {type(e).__name__}: {e}")
        return False


def _load_uae_dashboard_rows() -> list[dict]:
    """All UAE facility-sheet rows from gsheet_ae, tagged with Account Country = UAE for dashboard filters."""
    hidden = _regional_preview_hidden_tab_names_lower()
    out: list[dict] = []
    for tab_id in list_tab_ids_for_source(GSOURCE_KITCHEN_AE):
        if (tab_id or "").strip().lower() in hidden:
            continue
        for r in _list_generic_tab_cached(tab_id, source=GSOURCE_KITCHEN_AE):
            if not isinstance(r, dict) or _is_empty_record(r):
                continue
            row = dict(r)
            row["Account Country"] = "UAE"
            row["Sheet"] = tab_id
            out.append(row)
    return out


def _refresh_bahrain_workbook_from_sheets(*, silent: bool = True) -> bool:
    """Fetch Bahrain facility sheets (by gid) and persist under gsheet_bh. Returns True on success."""
    sid, _, _, gsource = _regional_kitchen_workbook_settings("Bahrain")
    creds_path = _get_google_credentials_path()
    if not creds_path or not sid:
        return False
    try:
        data = _fetch_regional_workbook_data("Bahrain", sid, creds_path) or {}
        if not data:
            if not silent:
                st.warning(
                    "No worksheets loaded for Bahrain. Share the workbook with the service account (Viewer) "
                    "and check BAHRAIN_KITCHEN_SHEET_ID / BAHRAIN_KITCHEN_FACILITY_GIDS in secrets."
                )
            return False
        with get_conn() as c:
            c.execute("DELETE FROM generic_tab_data WHERE source = ?", (gsource,))
        for ws_title, ws_rows in data.items():
            save_generic_tab(
                str(ws_title).strip() or ws_title,
                _regional_sheet_rows_for_sqlite(ws_rows or []),
                source=gsource,
            )
        _clear_list_generic_tab_cache()
        set_last_refresh(gsource)
        return True
    except Exception as e:
        if not silent:
            st.warning(f"Could not refresh Bahrain sheet: {type(e).__name__}: {e}")
        return False


def _load_bahrain_dashboard_rows() -> list[dict]:
    """Bahrain facility-sheet rows from gsheet_bh, tagged with Account Country = Bahrain."""
    hidden = _regional_preview_hidden_tab_names_lower()
    out: list[dict] = []
    for tab_id in list_tab_ids_for_source(GSOURCE_KITCHEN_BH):
        if (tab_id or "").strip().lower() in hidden:
            continue
        for r in _list_generic_tab_cached(tab_id, source=GSOURCE_KITCHEN_BH):
            if not isinstance(r, dict) or _is_empty_record(r):
                continue
            row = dict(r)
            row["Account Country"] = "Bahrain"
            row["Sheet"] = tab_id
            out.append(row)
    return out


def _refresh_regional_kitchen_workbooks() -> None:
    """Load Kuwait/UAE/Bahrain preview workbooks into SQLite by source. Non-fatal on error."""
    creds_path = _get_google_credentials_path()
    if not creds_path:
        return
    for region in ("Kuwait", "UAE", "Bahrain"):
        sid, _gid, _legacy_tab_id, gsource = _regional_kitchen_workbook_settings(region)
        if not sid:
            continue
        try:
            data = _fetch_regional_workbook_data(region, sid, creds_path) or {}
            if not data:
                continue
            with get_conn() as c:
                c.execute("DELETE FROM generic_tab_data WHERE source = ?", (gsource,))
            for ws_title, ws_rows in data.items():
                save_generic_tab(
                    str(ws_title).strip() or ws_title,
                    _regional_sheet_rows_for_sqlite(ws_rows or []),
                    source=gsource,
                )
            set_last_refresh(gsource)
        except Exception:
            continue


def _render_kitchen_master_ksa_main(*, can_export: bool, is_developer: bool) -> None:
    """Saudi Arabia (KSA) Kitchen Master — Superset, BigQuery, or Google Sheet sources + tables."""
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
            # Always prefer the live Google Sheet when tabs exist (no source toggle — same as working in the workbook).
            if both_sources_available:
                st.session_state[_src_key] = "gsheet"
                use_bq = False
            else:
                st.session_state[_src_key] = "bigquery"
                use_bq = True
            if use_bq:
                st.caption(f"Filter kitchen details and view your report. **BigQuery source** — refreshes every 3 min. Last refresh: {_mins_ago:.1f} min ago.")
                chosen_label = "Master Kitchens (BigQuery)"
                source_id = "bigquery"
                rows = bq_rows
                source_options = []
                is_other_sheet = False
            else:
                # Live Google Sheet when workbook tabs exist; facility multiselect (one or multiple sheets)
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
                rows = _list_generic_tab_cached(source_id, source="gsheet")
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
            # Performance: never block a normal rerun (e.g. switching facility) on a Google Sheets refresh.
            # The full-workbook fetch can take minutes; on a widget change Streamlit reruns and would freeze the UI.
            # Inline refresh only on COLD START (no data in local DB yet). Routine freshness comes from the scheduler
            # and the explicit "Refresh from Google Sheet" button under Admin / Data Health.
            import time
            now_sec = time.time()
            _never_gsheet = not last_refresh
            _has_any_gsheet_tabs = bool(list_tab_ids_for_source("gsheet"))
            _refresh_inflight_key = "gsheet_refresh_inflight"
            _creds_ok = bool(_get_google_credentials_path())
            _cold_start = _never_gsheet and not _has_any_gsheet_tabs
            if (
                _creds_ok
                and _cold_start
                and not st.session_state.get(_refresh_inflight_key)
                and not st.session_state.get("gsheet_initial_fetch_failed")
            ):
                st.session_state[_refresh_inflight_key] = now_sec
                try:
                    with st.spinner("Loading Google Sheet data for the first time…"):
                        ok, msg = _refresh_from_online_sheet()
                finally:
                    st.session_state.pop(_refresh_inflight_key, None)
                if not ok:
                    st.session_state["gsheet_initial_fetch_failed"] = True
                else:
                    st.session_state.pop("gsheet_initial_fetch_failed", None)
                    set_last_refresh("gsheet")
                    st.session_state["data_source"] = "gsheet"
                    _rerun()
                last_refresh = get_last_refresh("gsheet")
            # Per-session auto-refresh: once per browser tab, if data is older than 30 min,
            # refresh from Google Sheets so users don't end up looking at days-old data. We
            # guard with a session_state flag so this fires AT MOST once per session — switching
            # facilities or filtering does NOT re-trigger it (which is what was causing the
            # 6-minute hang before). Stale check uses the last gsheet refresh timestamp from
            # the DB, so concurrent users coordinate too: first one through pays the cost,
            # others see the refreshed data on their next page load.
            _session_refresh_done_key = "gsheet_session_refresh_done"
            if (
                _creds_ok
                and not _cold_start
                and not st.session_state.get(_session_refresh_done_key)
                and not st.session_state.get(_refresh_inflight_key)
                and _gsheet_refresh_is_stale(30)
            ):
                st.session_state[_refresh_inflight_key] = now_sec
                st.session_state[_session_refresh_done_key] = True
                try:
                    with st.spinner("Refreshing latest data from Google Sheets… (one-time per session)"):
                        ok, _msg = _refresh_from_online_sheet()
                finally:
                    st.session_state.pop(_refresh_inflight_key, None)
                if ok:
                    set_last_refresh("gsheet")
                    _clear_list_generic_tab_cache()
                    _rerun()
                last_refresh = get_last_refresh("gsheet")
            # Refresh from Google Sheet moved to Admin / Data Health
            sources = _master_kitchens_sources()
            source_options = [s[0] for s in sources]
            source_ids = {s[0]: s[1] for s in sources}
            if not source_options:
                rows = (
                    list_generic_tab("Kitchens", source="salesforce")
                    or list_generic_tab("SF Kitchen Data", source="salesforce")
                    or []
                )
                if rows:
                    st.info("Live sheet data is temporarily unavailable. Showing latest Salesforce snapshot.")
                    source_id = "salesforce_kitchens"
                    chosen_label = "Salesforce snapshot"
                    is_other_sheet = False
                else:
                    st.info("No sheet data yet. Data is refreshed every 15 minutes by the scheduler.")
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
                rows = _list_generic_tab_cached(source_id, source="gsheet")
                is_other_sheet = True
    # Render: 1 facility = single view; 2+ = one Streamlit tab per selected facility.
    if is_other_sheet and chosen_labels:
        # Trust the live widget return value only — do NOT also read session_state for
        # the same key. The two should always agree, but if they ever diverge (which can
        # happen across deploys when an old session has a stale selection cached) we end
        # up rendering data for facilities the user didn't pick.
        _labels_to_use = [t for t in (chosen_labels or []) if t in (source_options or [])]
        if not _labels_to_use:
            _labels_to_use = chosen_labels[:1]
        if len(_labels_to_use) == 1:
            _render_generic_tab(
                source_ids.get(_labels_to_use[0], _labels_to_use[0]),
                key_suffix="master_other",
                is_developer=is_developer,
                source="gsheet",
                allow_download=can_export,
                hide_account_country=True,
            )
        else:
            # Master-detail: tab-like picker at top, single content pane below. Only one
            # facility's AgGrid is mounted at a time, regardless of how many are selected,
            # so mobile Safari can't OOM-crash. _facility_pill_picker uses st.segmented_control
            # when available (looks like tabs) and falls back to st.radio(horizontal=True).
            _picked = _facility_pill_picker(
                _labels_to_use,
                key="master_other_facility_picker",
            )
            _tab_id = source_ids.get(_picked, _picked)
            _rows = _list_generic_tab_cached(_tab_id, source="gsheet")
            _rows = _filter_empty_records([r for r in _rows if isinstance(r, dict)])
            _rows = _filter_junk_kitchen_records(_rows)
            _slug = re.sub(r"\W+", "_", str(_picked).strip().lower()) or "tab"
            _render_generic_tab(
                _tab_id,
                key_suffix=f"master_other_{_slug}",
                is_developer=is_developer,
                source="gsheet",
                allow_download=can_export,
                hide_account_country=True,
                rows_override=_rows,
            )
    if not rows and not is_other_sheet and chosen_label:
        st.info(f"No rows in **{chosen_label}** yet. Data refreshes automatically every 15 minutes — try again shortly or check the source sheet.")
    elif not is_other_sheet and source_id:
        total = len(rows)
        is_tracker = source_id == "main_tracker"
        # No filter bar: single table like Excel sheet (filter via column filters below)
        use_facility_tabs = False
        rows_filtered = _filter_empty_records([r for r in (rows or []) if isinstance(r, dict)])
        rows_filtered = _filter_junk_kitchen_records(rows_filtered)
        rows_display = rows_filtered  # used for table; updated by column filters when applied
        if total > 0 and len(rows_filtered) == 0 and not use_facility_tabs:
            st.info("No data in this source.")
        cols_to_show: list = []
        if rows_filtered and not use_facility_tabs:
            all_cols = list(rows_filtered[0].keys()) if rows_filtered else []
            # Master Kitchens: hide Account Country and Sheet from the sheet
            all_cols = [c for c in all_cols if not _is_account_country_column(c) and str(c).strip().lower() != "sheet"]
            cols_to_show = all_cols
        display_df = None
        if HAS_EXCEL and rows_filtered and not use_facility_tabs:
            display_df = pd.DataFrame(rows_display)[cols_to_show] if cols_to_show else pd.DataFrame(rows_display)
            display_df = display_df.copy()
            display_df["_has_opportunity"] = [_row_has_opportunity_name(r) for r in rows_display]
        if display_df is not None and not display_df.empty:
            status_col_ag = _status_column_from_dataframe(display_df)
            _render_master_table_aggrid_or_df(
                display_df,
                rows_display,
                grid_key="master_kitchens_grid_single",
                status_col=status_col_ag,
                allow_download=can_export,
                export_file_stem="master_kitchens_filtered",
                export_button_key="export_master_kitchens_single_master",
            )
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


def _render_preview_regional_kitchen_master(region: str, *, can_export: bool, is_developer: bool) -> None:
    """Kitchen Master Data view for Kuwait/UAE/Bahrain regional workbooks (Google Sheets)."""
    sid, gid, _legacy_tab_id, gsource = _regional_kitchen_workbook_settings(region)
    st.caption(f"**{region} kitchen master**")
    # Performance: never block a normal rerun (e.g. switching facility) on a Google Sheets refresh.
    # Inline refresh only on COLD START (no data in local DB yet) and only if no other rerun is mid-refresh.
    # Routine freshness comes from the scheduler and the explicit "Refresh {region} sheet now" button below.
    _has_any_loaded_tabs = bool(list_tab_ids_for_source(gsource))
    _refresh_inflight_key = f"regional_refresh_inflight_{gsource}"
    if not _has_any_loaded_tabs and not st.session_state.get(_refresh_inflight_key):
        st.session_state[_refresh_inflight_key] = True
        try:
            with st.spinner(f"Loading {region} Google Sheet data for the first time…"):
                if region == "Kuwait":
                    _refresh_kuwait_workbook_from_sheets(silent=False)
                elif region == "UAE":
                    _refresh_uae_workbook_from_sheets(silent=False)
                elif region == "Bahrain":
                    _refresh_bahrain_workbook_from_sheets(silent=False)
        finally:
            st.session_state.pop(_refresh_inflight_key, None)

    _legacy_hidden = _regional_preview_hidden_tab_names_lower()
    source_options = [
        t
        for t in list_tab_ids_for_source(gsource)
        if (t or "").strip() and (t or "").strip().lower() not in _legacy_hidden
    ]
    source_ids = {t: t for t in source_options}
    if not source_options:
        st.info(
            f"No {region} data loaded yet. Share the Google Sheet with the **service account** email (Viewer), "
            f"then click **Refresh {region} sheet now** below (or wait for the scheduled GSheet job)."
        )
        if sid:
            if st.button(f"Refresh {region} sheet now", key=f"btn_refresh_regional_{gsource}"):
                creds = _get_google_credentials_path()
                if creds:
                    try:
                        data = _fetch_regional_workbook_data(region, sid, creds) or {}
                        if not data:
                            st.warning(
                                f"No worksheets loaded for {region}. Check sheet ID, facility GIDs, and service account access."
                            )
                            return
                        with get_conn() as c:
                            c.execute("DELETE FROM generic_tab_data WHERE source = ?", (gsource,))
                        _loaded_rows = 0
                        _loaded_tabs = 0
                        for ws_title, ws_rows in data.items():
                            save_generic_tab(
                                str(ws_title).strip() or ws_title,
                                _regional_sheet_rows_for_sqlite(ws_rows or []),
                                source=gsource,
                            )
                            _loaded_tabs += 1
                            _loaded_rows += len(ws_rows or [])
                        set_last_refresh(gsource)
                        st.success(f"Loaded {_loaded_rows:,} rows from {_loaded_tabs} sheets.")
                        _rerun()
                    except Exception as e:
                        st.error(str(e))
        return

    _sel_key = f"regional_sheets_selection_{gsource}"
    _first_tab = source_options[0]
    _initial = st.session_state.get(_sel_key) if _sel_key in st.session_state else [_first_tab]
    if not isinstance(_initial, list):
        _initial = [_initial] if _initial else [_first_tab]
    _default = _initial if set(_initial) <= set(source_options) else [_first_tab]
    chosen_labels = st.multiselect(
        f"**{region} Facility** — select one or multiple facilities (sheets) to view",
        options=source_options,
        default=_default,
        key=_sel_key,
        placeholder="Select facilities",
    )
    if not chosen_labels:
        chosen_labels = [_first_tab]
    _labels_to_use = [t for t in chosen_labels if t in source_options] or [_first_tab]
    if len(_labels_to_use) == 1:
        _single_tab_id = source_ids.get(_labels_to_use[0], _labels_to_use[0])
        _single_rows = _list_generic_tab_cached(_single_tab_id, source=gsource)
        _single_rows = _filter_empty_records([r for r in _single_rows if isinstance(r, dict)])
        _render_generic_tab(
            _single_tab_id,
            key_suffix=f"preview_{gsource}_{_single_tab_id}",
            is_developer=is_developer,
            source=gsource,
            allow_download=can_export,
            hide_account_country=True,
            rows_override=_single_rows,
            drop_facility_name_column=(region == "Kuwait"),
            regional_display=region if region in ("Kuwait", "UAE") else None,
        )
        return
    # Master-detail: same pattern as KSA. Pill-style picker, one AgGrid mounted at a time.
    _picked = _facility_pill_picker(
        _labels_to_use,
        key=f"regional_facility_picker_{gsource}",
    )
    _tab_id = source_ids.get(_picked, _picked)
    _rows = _list_generic_tab_cached(_tab_id, source=gsource)
    _rows = _filter_empty_records([r for r in _rows if isinstance(r, dict)])
    _slug = re.sub(r"\W+", "_", str(_picked).strip().lower()) or "tab"
    _render_generic_tab(
        _tab_id,
        key_suffix=f"preview_{gsource}_{_slug}",
        is_developer=is_developer,
        source=gsource,
        allow_download=can_export,
        hide_account_country=True,
        rows_override=_rows,
        drop_facility_name_column=(region == "Kuwait"),
        regional_display=region if region in ("Kuwait", "UAE") else None,
    )


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
    """Pull all tabs from the online sheet and load into app DB. Returns (success, message).

    KSA facility parity: generic (facility) worksheets persist even when empty (placeholder row) so every tab
    stays visible in Kitchen Master — do not skip empty sheets here.
    """
    creds_path = _get_google_credentials_path()
    if not creds_path:
        return False, "Google Sheet refresh is not configured."
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
        rows = list(rows or [])
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
            if not rows:
                continue
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
            if not rows:
                continue
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
            _n_src = len(rows)
            rows = _ensure_account_country_in_kitchens(rows)
            # Persist at least one row so empty worksheets still appear in Kitchen Master facility pickers (matches regional workbooks).
            to_save = _regional_sheet_rows_for_sqlite(rows)
            save_generic_tab(tab_id, to_save, source="gsheet")
            loaded.append(f"{tab_id} ({_n_src} rows)" if _n_src else f"{tab_id} (empty)")
        # Record tab order (skip exec log so Data tabs match sheet tabs)
        if tab_id != "Auto Refresh Execution Log" and not _is_main_tracker_tab(tab_id):
            tab_order.append((len(tab_order), tab_id))
    # Persist worksheet order so Data section tabs match the Google Sheet
    if tab_order:
        with get_conn() as c:
            c.execute("DELETE FROM gsheet_tab_order")
            for i, tid in tab_order:
                c.execute("INSERT OR REPLACE INTO gsheet_tab_order (tab_index, tab_id) VALUES (?, ?)", (i, tid))
    _refresh_regional_kitchen_workbooks()
    base_msg = "Loaded: " + "; ".join(loaded) if loaded else "No data in sheet."
    return True, base_msg + " (Kuwait/UAE/Bahrain preview sheets refreshed if configured.)"


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


def _raw_country_means_bahrain(val: str) -> bool:
    """True if country/county text is Bahrain: BH, BHR, Bahrain, or anything starting with BH (e.g. BH - Site)."""
    v = (val or "").strip().lower()
    if not v:
        return False
    if v in ("bh", "bhr", "bahrain"):
        return True
    return v.startswith("bh")


# Kitchen id / name columns (SF labels and API names) — used when Country/County are blank.
_KITCHEN_NUMBER_NAME_KEYS = (
    "Kitchen Number",
    "Kitchen_Number_ID_18__c",
    "Name",
    "Kitchen Number Name",
    "Kitchen_Number__c.Name",
)


def _kitchen_number_name_blob(row: dict) -> str:
    """Single string of kitchen identifiers for country inference."""
    parts: list[str] = []
    for k in _KITCHEN_NUMBER_NAME_KEYS:
        v = row.get(k)
        if v is not None and str(v).strip():
            parts.append(str(v).strip())
    return " ".join(parts)


def _country_from_kitchen_number_or_name(text: str) -> str | None:
    """Infer country from kitchen number / name when sheet country fields are empty: SA/KSA→KSA, BH→Bahrain, KWT→Kuwait, UAE→UAE."""
    if not text or not str(text).strip():
        return None
    u = str(text).strip().upper()
    if "UAE" in u:
        return "UAE"
    if "KWT" in u or "KUWAIT" in u:
        return "Kuwait"
    if "KSA" in u:
        return "Saudi Arabia"
    if "BH" in u:
        return "Bahrain"
    if "SA" in u:
        return "Saudi Arabia"
    return None


# Dashboard Country dropdown: always show KSA + Bahrain + regional pilots (even when row data has no kitchens there yet).
DASHBOARD_COUNTRY_FILTER_CORE = ("Saudi Arabia", "Bahrain", "Kuwait", "UAE")


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
    # Merge all with Saudi Arabia except Bahrain (North, South, SA, Last, etc. → Saudi Arabia; BH* → Bahrain)
    def _normalize_country_value(val: str) -> str:
        v = (val or "").strip()
        if not v:
            return v
        if _raw_country_means_bahrain(v):
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
                if _raw_country_means_bahrain(prefix):
                    row["Account Country"] = "Bahrain"
                else:
                    row["Account Country"] = _COUNTRY_FROM_PREFIX.get(prefix, "Saudi Arabia")
            else:
                raw = row.get("Account Country", "") or ""
                row["Account Country"] = _normalize_country_value(str(raw)) if raw else ""
        else:
            raw = row.get("Account Country", "") or ""
            row["Account Country"] = _normalize_country_value(str(raw)) if raw else ""
        ac = (row.get("Account Country") or "").strip()
        if not ac:
            inferred = _country_from_kitchen_number_or_name(_kitchen_number_name_blob(row))
            if inferred:
                row["Account Country"] = inferred
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


def _apply_kitchen_labels_to_combined_facility_rows(combined_rows: list[dict]) -> list[dict]:
    """When multiple sheets are merged, unify API vs display column names into one column each.

    Without this, ``Sell_Price__c`` on one facility and ``List Price`` on another become two
    columns; pandas infers object dtypes and Ag Grid shows 6400.00000-style noise.
    """
    if not combined_rows:
        return combined_rows
    cols = sorted(set().union(*(r.keys() for r in combined_rows if isinstance(r, dict))))
    rows2, _ = _apply_kitchen_labels(combined_rows, cols)
    return rows2


def _normalize_export_rows_for_download(rows: list | None) -> list | None:
    """Re-run cell sanitization on rows Ag Grid returns (JSON can reintroduce float formatting)."""
    if not rows:
        return rows
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(_sanitize_kitchen_row_dict(dict(r)))
        else:
            out.append(r)
    return out


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


def _is_facility_name_aggrid_column(col: str | None) -> bool:
    """True for sheet column 'Facility Name' — suppress AgGrid filter UI (set filter / floating row)."""
    if col is None:
        return False
    s = re.sub(r"\s+", " ", str(col).strip()).lower()
    s = s.replace("_", " ")
    return s in ("facility name", "facilityname")


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
        # Lower threshold so mixed text columns (e.g. UAE) still become numeric when mostly numbers
        if non_null >= max(1, int(len(df) * 0.28)):
            df[col] = ser
    return df


_NUMERIC_STRING_ONLY_RE = re.compile(r"^-?[\d,]+(?:\.[\d]*)?$")
# Kitchen Size / Hood Size often arrive as "25.00000 m²" or "25.00000 sqm" — strip float noise from the number part.
_SIZE_UNIT_SUFFIX_OK_RE = re.compile(
    r"^(m²|m\u00b2|m2|sqm|sq\.?\s*m|square\s*meters?|sq\s*meters?|meters?\s*sq|sq\.?\s*meters?)$",
    re.IGNORECASE,
)


def _prettify_numeric_string_plain_or_with_size_unit(raw: str):
    """Compact plain numeric strings and number+area-unit strings (Kitchen/Hood Size columns). Returns None if not matched."""
    if raw is None:
        return None
    t = str(raw).strip()
    if not t:
        return None
    m = re.match(r"^\s*(-?[\d,]+(?:\.[\d]*))\s*(.*?)\s*$", t)
    if not m:
        return None
    num_s, rest = m.group(1), m.group(2).strip()
    try:
        xf = float(num_s.replace(",", ""))
    except ValueError:
        return None
    if not math.isfinite(xf):
        return None
    pv = _prettify_numeric_scalar_for_display(xf)
    if not rest:
        t0 = num_s.replace(",", "").replace(" ", "")
        if _NUMERIC_STRING_ONLY_RE.match(t0):
            return pv
        return None
    if not _SIZE_UNIT_SUFFIX_OK_RE.match(rest):
        return None
    return f"{pv} {rest.strip()}"


def _sanitize_cell_value_for_kitchen(v):
    """Normalize sheet/JSON noise: literal 'None'/'null' → None; '5192.000000' → int 5192."""
    if v is None:
        return v
    if isinstance(v, Decimal):
        try:
            return _prettify_numeric_scalar_for_display(float(v))
        except Exception:
            return v
    if isinstance(v, str):
        t = v.strip()
        if not t or t.lower() in ("none", "null", "nan", "n/a", "na", "#n/a", "undefined", "<na>"):
            return None
        t0 = t.replace(",", "").replace(" ", "")
        if _NUMERIC_STRING_ONLY_RE.match(t0):
            try:
                return _prettify_numeric_scalar_for_display(float(t0))
            except ValueError:
                return v
        pv_size = _prettify_numeric_string_plain_or_with_size_unit(t)
        if pv_size is not None:
            return pv_size
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return _prettify_numeric_scalar_for_display(v)
    # numpy / pandas scalar types are not isinstance(..., float) but still print as 6400.00000 in grids
    try:
        if HAS_EXCEL and not isinstance(v, bool) and not pd.api.types.is_bool(v) and pd.api.types.is_number(v):
            return _prettify_numeric_scalar_for_display(v)
    except Exception:
        pass
    return v


def _sanitize_kitchen_row_dict(r: dict) -> dict:
    if not isinstance(r, dict):
        return r
    out = {k: _sanitize_cell_value_for_kitchen(v) for k, v in r.items()}
    # Regional sheets can expose kitchen type under variant headers.
    # Keep a canonical ``Type`` value for filtering and row-quality rules.
    tk = _find_kitchen_type_column_key(out)
    if tk:
        tv = out.get(tk)
        if not _is_missing_kitchen_type_for_junk_filter(tv):
            cur = out.get("Type")
            if _is_missing_kitchen_type_for_junk_filter(cur):
                out["Type"] = tv
    # Last-resort fallback for regional sheets: infer type from kitchen name like
    # "K4 (Hot) - KWT - Jahra ...", when explicit Type columns are blank.
    cur_type = out.get("Type")
    if _is_missing_kitchen_type_for_junk_filter(cur_type):
        nk = _find_kitchen_number_name_column_key(out)
        if nk:
            name_blob = str(out.get(nk) or "").strip()
            if name_blob:
                m = re.search(r"\(([^)]+)\)", name_blob)
                if m:
                    guess = (m.group(1) or "").strip()
                    # Avoid writing numeric/noisy parenthesis tokens as a "Type".
                    if guess and not re.fullmatch(r"[-\d\W_]+", guess):
                        out["Type"] = guess
    return out


def _integerize_whole_number_float_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Float columns where every value is a whole number → pandas Int64 (cleaner in Streamlit/Arrow)."""
    if df is None or df.empty:
        return df
    df = df.copy()
    for col in df.columns:
        if col == "_has_opportunity":
            continue
        if not pd.api.types.is_float_dtype(df[col]):
            continue
        s = df[col].dropna()
        if len(s) == 0:
            continue
        ok = True
        for x in s:
            try:
                xf = float(x)
            except (TypeError, ValueError):
                ok = False
                break
            if not math.isfinite(xf):
                ok = False
                break
            if abs(xf - round(xf)) > 1e-9 * max(1.0, abs(xf)):
                ok = False
                break
        if not ok:
            continue

        def _to_int_or_na(x):
            if pd.isna(x):
                return pd.NA
            try:
                return int(round(float(x)))
            except (TypeError, ValueError):
                return pd.NA

        try:
            df[col] = df[col].map(_to_int_or_na).astype("Int64")
        except Exception:
            continue
    return df


def _cell_lock_numeric_for_display(v):
    """Normalize any numeric-like cell for UI + Ag Grid; keeps dates/bools/text intact."""
    if v is None:
        return v
    try:
        if v is pd.NA:
            return v
    except Exception:
        pass
    try:
        if pd.isna(v):
            return v
    except Exception:
        pass
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return v
    if isinstance(v, str):
        return _sanitize_cell_value_for_kitchen(v)
    if isinstance(v, bool):
        return v
    try:
        if HAS_EXCEL and pd.api.types.is_bool(v):
            return v
    except Exception:
        pass
    return _sanitize_cell_value_for_kitchen(v)


def _dataframe_lock_numeric_display(df: pd.DataFrame) -> pd.DataFrame:
    """Final mandatory pass: every non-datetime cell through the sanitizer, then re-coerce dtypes.

    streamlit-aggrid serializes the DataFrame to JSON; mixed object columns or numpy floats often
    re-display as 6400.00000 unless values are plain int / compact float with stable dtypes.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    skip = {"_has_opportunity"}
    for col in out.columns:
        if col in skip:
            continue
        try:
            if pd.api.types.is_datetime64_any_dtype(out[col]):
                continue
        except Exception:
            pass
        try:
            if pd.api.types.is_bool_dtype(out[col]):
                continue
        except Exception:
            pass
        out[col] = out[col].map(_cell_lock_numeric_for_display)
    out = _coerce_numeric_columns(out)
    out = _integerize_whole_number_float_columns(out)
    return out


def _is_size_like_measurement_column(col) -> bool:
    """Columns for area/dimensions (Size, Kitchen Size, …) that Ag Grid otherwise shows as 9.140000."""
    if col is None or str(col) == "_has_opportunity":
        return False
    n = str(col).strip().lower()
    if n == "size":
        return True
    if "kitchen size" in n or "hood size" in n:
        return True
    if n.endswith(" size") or n.endswith("_size"):
        return True
    return False


def _scalar_to_compact_dimension_display_str(x):
    """Render measurements as compact text so JSON/Ag Grid never apply six-decimal float formatting."""
    if x is None:
        return x
    try:
        if pd.isna(x):
            return x
    except Exception:
        pass
    if isinstance(x, str):
        t = x.strip()
        if not t:
            return x
        pv = _prettify_numeric_string_plain_or_with_size_unit(t)
        if pv is not None and isinstance(pv, str) and any(c.isalpha() for c in pv):
            return pv
        try:
            xf = float(t.replace(",", "").split()[0]) if t else float("nan")
        except ValueError:
            return x
    elif isinstance(x, (int, float)) and not isinstance(x, bool):
        try:
            xf = float(x)
        except (TypeError, ValueError):
            return x
    else:
        try:
            if HAS_EXCEL and not pd.api.types.is_bool(x) and pd.api.types.is_number(x):
                xf = float(x)
            else:
                return x
        except Exception:
            return x
    if not math.isfinite(xf):
        return x
    if abs(xf - round(xf)) < 1e-9 * max(1.0, abs(xf)):
        return str(int(round(xf)))
    r = round(xf, 8)
    s = f"{r:.10f}".rstrip("0").rstrip(".")
    return s


def _format_size_like_columns_compact_string(df: pd.DataFrame) -> pd.DataFrame:
    """Ag Grid renders float cells with fixed decimals; store Size columns as compact strings."""
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if not _is_size_like_measurement_column(col):
            continue
        out[col] = out[col].map(_scalar_to_compact_dimension_display_str)
    return out


def _sync_rows_shown_from_display_df(df: pd.DataFrame, rows_shown: list | None) -> None:
    """Align row dicts with the DataFrame actually rendered (export + grid filtered data stay consistent)."""
    if not rows_shown or df is None or df.empty:
        return
    try:
        if len(rows_shown) != len(df.index):
            return
    except Exception:
        return
    ncols = len(df.columns)
    for i in range(len(rows_shown)):
        r = rows_shown[i]
        if not isinstance(r, dict):
            continue
        for j in range(ncols):
            c = df.columns[j]
            try:
                r[c] = df.iat[i, j]
            except Exception:
                pass


def _streamlit_number_column_config_for_df(df: pd.DataFrame) -> dict:
    """Compact numeric display for native ``st.dataframe`` (avoids long float strings in the UI)."""
    if df is None or df.empty:
        return {}
    out: dict = {}
    for col in df.columns:
        if str(col) == "_has_opportunity":
            continue
        try:
            if pd.api.types.is_bool_dtype(df[col]):
                continue
        except Exception:
            pass
        try:
            dname = getattr(df[col].dtype, "name", "")
            if pd.api.types.is_integer_dtype(df[col]) or dname in ("Int64", "Int32", "UInt64"):
                out[col] = st.column_config.NumberColumn(str(col), format="%d")
            elif pd.api.types.is_float_dtype(df[col]):
                out[col] = st.column_config.NumberColumn(str(col), format="%.8g")
        except Exception:
            continue
    return out


def _prepare_kitchen_master_dataframe_for_display(df: pd.DataFrame, rows_shown: list | None) -> pd.DataFrame:
    """Sanitize row dicts in place when aligned with df, then coerce → integerize → prettify → integerize.

    Integerize runs before prettify so whole-number float columns become Int64; otherwise prettify maps
    cells to mixed int/float, the column becomes object, and integerize is skipped — Ag Grid then shows
    6400.000000-style floats.
    """
    if df is None or df.empty:
        return df
    cols = list(df.columns)
    if rows_shown is not None and len(rows_shown) == len(df.index):
        for i in range(len(rows_shown)):
            rows_shown[i] = _sanitize_kitchen_row_dict(rows_shown[i])
        df = pd.DataFrame(rows_shown)
        for c in cols:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[cols]
    df = _coerce_numeric_columns(df)
    df = _integerize_whole_number_float_columns(df)
    df = _prettify_numeric_columns_for_display_deep(df)
    df = _dataframe_lock_numeric_display(df)
    df = _format_size_like_columns_compact_string(df)
    if rows_shown is not None and len(rows_shown) == len(df.index):
        _sync_rows_shown_from_display_df(df, rows_shown)
    return df


def _prettify_numeric_scalar_for_display(x):
    """Drop trailing fractional noise (10930.0 → int; 17.35 stays compact) for table display."""
    if x is None:
        return x
    try:
        if pd.isna(x):
            return x
    except TypeError:
        pass
    if isinstance(x, Decimal):
        try:
            x = float(x)
        except Exception:
            return x
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if not math.isfinite(xf):
        return x
    # Whole numbers as int (avoids 5192.0 / 5192.000000 in many renderers)
    if abs(xf - round(xf)) < 1e-9 * max(1.0, abs(xf)):
        return int(round(xf))
    # General format: up to 6 significant figures, no long trailing zeros
    try:
        return float(f"{xf:.8g}")
    except Exception:
        return round(xf, 4)


def _prettify_numeric_columns_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Integer-like values as int; other floats compact — avoids 10930.000000 in the UI."""
    if df is None or df.empty:
        return df
    df = df.copy()
    skip = {"_has_opportunity"}
    for col in df.columns:
        if col in skip:
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        df[col] = df[col].map(_prettify_numeric_scalar_for_display)
    return df


def _prettify_numeric_object_series(ser):
    """Coerce object columns of numeric strings to prettified numbers (e.g. '5192.000000' → 5192)."""
    if ser is None or len(ser) == 0:
        return ser
    out = []
    for v in ser:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            out.append(v)
            continue
        try:
            if pd.isna(v):
                out.append(v)
                continue
        except Exception:
            pass
        if isinstance(v, str):
            t_full = str(v).strip()
            if not t_full or t_full.lower() in ("nan", "none", "null", "n/a", "na"):
                out.append(v)
                continue
            pv_sz = _prettify_numeric_string_plain_or_with_size_unit(t_full)
            if pv_sz is not None:
                out.append(pv_sz)
                continue
            t = t_full.replace(",", "")
            try:
                xf = float(t)
            except ValueError:
                out.append(v)
                continue
            out.append(_prettify_numeric_scalar_for_display(xf))
        else:
            out.append(_prettify_numeric_scalar_for_display(v))
    return pd.Series(out, index=ser.index, dtype=object)


def _prettify_numeric_columns_for_display_deep(df: pd.DataFrame) -> pd.DataFrame:
    """Like _prettify_numeric_columns_for_display but also fixes object columns that are numeric strings."""
    df = _prettify_numeric_columns_for_display(df)
    if df is None or df.empty:
        return df
    skip = {"_has_opportunity"}
    for col in df.columns:
        if col in skip:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        ser = df[col]
        non_null = ser.dropna()
        if len(non_null) == 0:
            continue
        sample = non_null.head(min(80, len(non_null))).astype(str).str.strip()
        num_like = 0
        for s in sample:
            if not s or s.lower() in ("nan", "none", "null", "n/a", "na"):
                continue
            try:
                float(s.replace(",", ""))
                num_like += 1
            except ValueError:
                if _prettify_numeric_string_plain_or_with_size_unit(s) is not None:
                    num_like += 1
        quick = non_null.head(min(24, len(non_null)))
        any_plain_num_str = False
        any_size_unit_str = False
        for v in quick:
            if isinstance(v, str):
                t0 = v.strip().replace(",", "").replace(" ", "")
                if _NUMERIC_STRING_ONLY_RE.match(t0):
                    any_plain_num_str = True
                    break
                if _prettify_numeric_string_plain_or_with_size_unit(v.strip()) is not None:
                    any_size_unit_str = True
                    break
        _force_size_col = "size" in str(col).lower()
        if (
            any_plain_num_str
            or any_size_unit_str
            or _force_size_col
            or num_like >= max(2, int(len(sample) * 0.2))
        ):
            df[col] = _prettify_numeric_object_series(ser)
    return df


def _is_account_country_column(col_name: str) -> bool:
    """True if this column is Account Country, standalone County, or facility_country (any casing/spacing/dots). Hide in Master Kitchens."""
    if not col_name:
        return False
    n = str(col_name).strip().lower().replace(".", "_")
    n = re.sub(r"[\s_]+", "_", n).strip("_")
    # Strip trailing __c (Salesforce convention)
    if n.endswith("__c"):
        n = re.sub(r"_+c$", "", n)
    # Match exact, suffix, or name containing both "account" and "country" / facility_country; also hide plain "County"
    return (
        n == "accountcountry"
        or n == "county"
        or n in ("account_country", "facility_country")
        or n.endswith("account_country")
        or n.endswith("facility_country")
        or ("account" in n and "country" in n)
    )


def _status_cell_raw_from_row(r: dict) -> str:
    """Raw status string from a kitchen row (Status / status__c / status keys)."""
    if not r or not isinstance(r, dict):
        return ""
    for k in ("Status", "status__c", "status"):
        if k in r and r.get(k) is not None:
            return str(r.get(k)).strip()
    for k, val in r.items():
        lk = str(k).strip().lower()
        if lk in ("status", "status__c") and val is not None:
            return str(val).strip()
    return ""


def _status_normalized_from_row(r: dict) -> str:
    """Same normalization as row colors and filters (Vacant, Churning, Occupied, Sold, No status, or raw)."""
    return _normalize_status_label(_status_cell_raw_from_row(r))


def _normalize_status_label(val) -> str:
    """Normalize status value for filter: Vacant, Churning, Occupied, Sold, or raw. Used for Status filter and row count."""
    if val is None:
        return ""
    s = _strip_salesforce_picklist_prefix(val)
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


def _cell_is_empty_for_empty_row_check(v) -> bool:
    """True if a cell counts as empty when deciding whether a whole row is blank."""
    if v is None:
        return True
    try:
        if v is pd.NA:
            return True
    except Exception:
        pass
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    if isinstance(v, float) and math.isnan(v):
        return True
    s = str(v).strip()
    if not s:
        return True
    sl = s.lower()
    if sl in ("nan", "none", "n/a", "na", "—", "-", "<na>", "#n/a", "null", "undefined"):
        return True
    return False


def _row_is_overwhelmingly_none_like(row: dict) -> bool:
    """True when most cells are None / 'None' / blank (wide sheet padding rows)."""
    if not row or not isinstance(row, dict):
        return False
    skip = {"_has_opportunity", "Sheet"}
    keys = [k for k in row if k not in skip]
    if len(keys) < 4:
        return False
    n_empty = sum(1 for k in keys if _cell_is_empty_for_empty_row_check(row.get(k)))
    if n_empty >= len(keys):
        return True
    # Hide padding rows: almost all cells None/blank
    if n_empty >= max(len(keys) - 1, int(math.ceil(len(keys) * 0.72))):
        return True
    return False


def _is_empty_record(row) -> bool:
    """True if the row has no meaningful data (all values empty, null, whitespace, NA-like, or mostly None)."""
    if not row or not isinstance(row, dict):
        return True
    if _row_is_overwhelmingly_none_like(row):
        return True
    for k, v in row.items():
        if k == "_has_opportunity":
            continue
        if not _cell_is_empty_for_empty_row_check(v):
            return False
    return True


def _filter_empty_records(rows: list) -> list:
    """Drop entirely empty dict rows (used before displaying tables)."""
    if not rows:
        return rows
    return [r for r in rows if isinstance(r, dict) and not _is_empty_record(r)]


# Hide incomplete kitchen rows: no Type + no Floor + no List with odd or missing status; sparse
# "No status" rows; sparse KPIs;
# rows with no Type, no Floor price, and no Kitchen number/name together;
# rows where the only populated fields are List price + Kitchen name (+ optional Status / Stage).
_STANDARD_KITCHEN_STATUS_NORMALIZED = frozenset(
    {"Vacant", "Churning", "Occupied", "Sold", "No status"}
)
_KITCHEN_TYPE_COL_KEYS = (
    "Type",
    "Kitchen Type",
    "Type__c",
    "Kitchen_Type",
    "Type of Kitchen",
    "Unit Type",
    "Kitchen Unit Type",
)
_KITCHEN_FLOOR_PRICE_KEYS = (
    "Floor Price",
    "Floor_Price__c",
    "floor_price",
    "Floor_Price",
    "Floor MRR",
    "Floor (MRR)",
)
_KITCHEN_LIST_PRICE_KEYS = (
    "List Price",
    "Sell_Price__c",
    "List_Price__c",
    "sell_price",
    "List_Price",
    "List (MRR)",
    "Kitchen_Number__c.Sell_Price__c",
)
_KITCHEN_NUMBER_NAME_KEYS = (
    "Kitchen Number Name",
    "Kitchen Number",
    "Kitchen_Number_ID_18__c",
    "Kitchen_Number__c",
    "Name",
)


def _find_kitchen_column_key(r: dict, candidates: tuple[str, ...]) -> str | None:
    if not r:
        return None
    for c in candidates:
        if c in r:
            return c
    norm_map = {re.sub(r"[\s_]+", "", str(k).lower()): k for k in r}
    for c in candidates:
        needle = re.sub(r"[\s_]+", "", c.lower())
        if needle in norm_map:
            return norm_map[needle]
    return None


def _find_floor_price_column_key(r: dict) -> str | None:
    k = _find_kitchen_column_key(r, _KITCHEN_FLOOR_PRICE_KEYS)
    if k:
        return k
    for key in r:
        if key in ("_has_opportunity", "Sheet"):
            continue
        ks = re.sub(r"[\s_]+", " ", str(key).lower()).strip()
        if "floor" in ks and "price" in ks:
            return key
        if "floor" in ks and "mrr" in ks:
            return key
    return None


def _find_list_price_column_key(r: dict) -> str | None:
    k = _find_kitchen_column_key(r, _KITCHEN_LIST_PRICE_KEYS)
    if k:
        return k
    for key in r:
        if key in ("_has_opportunity", "Sheet"):
            continue
        ks = re.sub(r"[\s_]+", " ", str(key).lower()).strip()
        if ("list" in ks or "sell" in ks) and ("price" in ks or "mrr" in ks):
            return key
    return None


def _find_kitchen_number_name_column_key(r: dict) -> str | None:
    k = _find_kitchen_column_key(r, _KITCHEN_NUMBER_NAME_KEYS)
    if k:
        return k
    for key in r:
        if key in ("_has_opportunity", "Sheet"):
            continue
        ks = re.sub(r"[\s_]+", " ", str(key).lower()).strip()
        if "kitchen" in ks and "number" in ks and "name" in ks:
            return key
    return None


def _find_kitchen_type_column_key(r: dict) -> str | None:
    k = _find_kitchen_column_key(r, _KITCHEN_TYPE_COL_KEYS)
    if k:
        return k
    for key in r:
        if key in ("_has_opportunity", "Sheet"):
            continue
        ks = re.sub(r"[^a-z0-9]+", "", str(key).lower())
        # Keep this strict enough to avoid accidental matches (e.g. "type of issue")
        # while covering common regional-sheet variants.
        if ks in ("type", "kitchentype", "kitchenunittype", "unittype", "typeofkitchen"):
            return key
        if "kitchen" in ks and "type" in ks:
            return key
    return None


def _is_missing_kitchen_type_for_junk_filter(v) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "null", "n/a", "na", "—", "-"):
        return True
    return False


def _is_missing_price_for_junk_filter(v) -> bool:
    """Blank, NaN, non-numeric, or zero = no price for junk-row rule."""
    if v is None:
        return True
    if isinstance(v, str) and not str(v).strip():
        return True
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    try:
        f = float(v)
    except (TypeError, ValueError):
        return True
    if not math.isfinite(f):
        return True
    if abs(f) < 1e-12:
        return True
    return False


def _is_odd_kitchen_status_normalized(norm: str) -> bool:
    n = (norm or "").strip()
    if not n:
        return False
    return n not in _STANDARD_KITCHEN_STATUS_NORMALIZED


def _should_hide_junk_kitchen_row(r: dict) -> bool:
    """True when Type + Floor + List are all missing and status is odd OR 'No status' (incomplete junk)."""
    if not isinstance(r, dict):
        return False
    tk = _find_kitchen_type_column_key(r)
    fk = _find_floor_price_column_key(r)
    lk = _find_list_price_column_key(r)
    # Need at least one kitchen price/type column in the row so we do not hide unrelated tabs.
    if tk is None and fk is None and lk is None:
        return False
    type_missing = tk is None or _is_missing_kitchen_type_for_junk_filter(r.get(tk))
    floor_missing = fk is None or _is_missing_price_for_junk_filter(r.get(fk))
    list_missing = lk is None or _is_missing_price_for_junk_filter(r.get(lk))
    if not (type_missing and floor_missing and list_missing):
        return False
    norm = _status_normalized_from_row(r)
    return _is_odd_kitchen_status_normalized(norm) or norm == "No status"


def _meaningful_kitchen_cell_count(r: dict) -> int:
    """Non-empty values excluding internal / sheet label columns."""
    if not isinstance(r, dict):
        return 0
    skip = {"_has_opportunity", "Sheet"}
    n = 0
    for k, v in r.items():
        if k in skip:
            continue
        if not _cell_is_empty_for_empty_row_check(v):
            n += 1
    return n


def _sold_rate_metric_columns_all_empty(r: dict) -> bool:
    """True when the sheet has Sold rate / %-style columns and every one is empty (UAE-style sparse junk)."""
    if not isinstance(r, dict):
        return False
    matched: list[str] = []
    for k in r:
        if k in ("_has_opportunity", "Sheet"):
            continue
        ks = str(k).lower()
        if "sold" in ks and "rate" in ks:
            matched.append(k)
            continue
        if "occupancy" in ks and "%" in ks:
            matched.append(k)
            continue
        if any(x in ks for x in ("ops occupancy", "occupancy %", "occupancy%")):
            matched.append(k)
    if not matched:
        return False
    for k in matched:
        if not _cell_is_empty_for_empty_row_check(r.get(k)):
            return False
    return True


def _should_hide_no_status_sparse_kitchen_row(r: dict) -> bool:
    """Hide 'No status' rows that are mostly empty (red row styling) or missing Sold rate / % KPIs when those columns exist."""
    if not isinstance(r, dict):
        return False
    if _status_normalized_from_row(r) != "No status":
        return False
    mc = _meaningful_kitchen_cell_count(r)
    # Do not require a minimum key count — sparse dict rows (only non-null cells stored) used to skip this rule.
    if mc <= 2:
        return True
    if mc <= 4 and _sold_rate_metric_columns_all_empty(r):
        return True
    return False


def _is_kitchen_status_column_key(k) -> bool:
    """True if this dict key is the kitchen Status field (SF, GSheet, BigQuery, or report exports)."""
    if k is None:
        return False
    n = re.sub(r"[\s_.]+", "", str(k).strip().lower())
    _exact = {
        "status",
        "statusc",
        "kitchenstatus",
        "kitchenstatusc",
        "kitchennumberstatus",
        "kitchennumberstatusc",
        "operationalstatus",
        "operationalstatusc",
        "inventorystatus",
        "inventorystatusc",
        "kitchenoperationalstatus",
        "kitchenoperationalstatusc",
        "opsstatus",
        "opsstatusc",
        "salestatus",
        "salestatusc",
        "salesstatus",
        "salesstatusc",
        "unitstatus",
        "unitstatusc",
    }
    if n in _exact:
        return True
    # Broader: …Status / …Status__c style headers once normalized (e.g. "Kitchen_Status__c")
    if len(n) <= 48 and (n.endswith("status") or n.endswith("statusc")):
        if n in ("poststatus", "substatus", "accountstatus", "paymentstatus"):
            return False
        return True
    return False


def _is_kitchen_stage_column_key(k) -> bool:
    """True if this dict key is a pipeline / sales Stage field (sheet exports)."""
    if k is None:
        return False
    ks = re.sub(r"[\s_]+", " ", str(k).strip().lower())
    if "stage" not in ks:
        return False
    # Avoid matching unrelated headers (unlikely in kitchen sheets).
    if ks in ("postage", "postagec", "substage override"):
        return False
    return True


def _is_kitchen_inventory_kpi_column_key(k) -> bool:
    """UAE-style sheet columns for sold rate / occupancy % (values may sit under Status/Stage or their own header)."""
    if k is None:
        return False
    ks = str(k).lower()
    if "sold" in ks and "rate" in ks:
        return True
    if "occupancy" in ks and "%" in ks:
        return True
    if any(x in ks for x in ("ops occupancy", "occupancy %", "occupancy%")):
        return True
    return False


def _scalar_counts_as_sheet_padding_zero(v) -> bool:
    """True for 0 / 0.0 / False / \"0\" — exported rows often pad numeric columns with zeros instead of blanks."""
    if v is None:
        return False
    if isinstance(v, bool):
        return v is False
    try:
        if v is pd.NA:
            return False
    except Exception:
        pass
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            f = float(v)
            return math.isfinite(f) and abs(f) < 1e-12
        except (TypeError, ValueError):
            return False
    s = str(v).strip().lower()
    if s in ("0", "0.0", "0.00", "0.000", "false"):
        return True
    s2 = s.replace(",", "").replace("%", "").strip()
    try:
        f = float(s2)
        return math.isfinite(f) and abs(f) < 1e-12
    except ValueError:
        return False


def _status_column_from_dataframe(df: pd.DataFrame) -> str | None:
    """Resolve the Status column for Kitchen Master row colors (Ag Grid rowClassRules + Styler fallback)."""
    if df is None or df.empty:
        return None
    matches: list[str] = []
    for c in df.columns:
        if c == "_has_opportunity":
            continue
        if _is_kitchen_status_column_key(c):
            matches.append(str(c))
    if not matches:
        return None
    for prefer in ("Status", "status", "Status__c", "status__c"):
        if prefer in matches:
            return prefer
    return matches[0]


def _kitchen_master_row_css_class_from_values(status_val, has_opportunity: bool) -> str:
    """Map status cell → row CSS class. Uses ``_normalize_status_label`` (same as filters); only standard buckets are colored — legacy sheet palette (Sold = Occupied pink)."""
    try:
        if status_val is not None and pd.isna(status_val):
            status_val = None
    except Exception:
        pass
    norm = _normalize_status_label(status_val)
    if not norm or norm == "No status":
        return "status-no-status"
    if norm == "Vacant":
        return "status-vacant-opp" if has_opportunity else "status-vacant"
    if norm == "Churning":
        return "status-churning"
    if norm in ("Occupied", "Sold"):
        return "status-occupied"
    return "status-no-status"


def _compute_km_row_cls_series(df: pd.DataFrame, status_col: str | None) -> pd.Series:
    """Per-row CSS class for Kitchen Master Ag Grid (computed in Python — reliable vs JS IIFE rowClassRules)."""
    if df is None or df.empty:
        return pd.Series(dtype=object)
    n = len(df.index)
    if not status_col or str(status_col) not in df.columns:
        return pd.Series(["status-no-status"] * n, index=df.index)
    if "_has_opportunity" in df.columns:
        ho = df["_has_opportunity"].fillna(False)
        try:
            ho = ho.astype(bool)
        except Exception:
            ho = ho.map(lambda x: bool(x) if pd.notna(x) else False)
    else:
        ho = pd.Series([False] * n, index=df.index)
    out: list[str] = []
    for i in df.index:
        row = df.loc[i]
        try:
            sv = row[status_col] if status_col in row.index else None
        except Exception:
            sv = None
        try:
            hop = bool(ho.loc[i]) if i in ho.index else False
        except Exception:
            hop = False
        out.append(_kitchen_master_row_css_class_from_values(sv, hop))
    return pd.Series(out, index=df.index)


def _aggrid_kitchen_master_row_class_rules_simple() -> dict:
    """Row class rules using precomputed ``km_row_cls`` (AG Grid simple expressions)."""
    _cls = (
        "status-no-status",
        "status-vacant-opp",
        "status-vacant",
        "status-churning",
        "status-occupied",
    )
    # Use ``==`` (simple-expression mode); ``===`` can fail depending on AG Grid / streamlit-aggrid version.
    return {c: f"data.km_row_cls == '{c}'" for c in _cls}


def _aggrid_kitchen_master_status_custom_css() -> dict:
    """Selector → style dict for streamlit-aggrid (theme-aware selectors for stronger override)."""
    _red_dark = {"background-color": "#B22222 !important", "color": "white !important"}
    _red_cell = {"background-color": "#FEE2E2 !important"}
    _green = {"background-color": "#D1FAE5 !important"}
    _yellow = {"background-color": "#FDE68A !important"}
    rows: dict[str, dict] = {
        ".ag-row.status-no-status": dict(_red_dark),
        ".ag-row.status-no-status .ag-cell": dict(_red_dark),
        ".ag-row.status-vacant-opp": dict(_red_cell),
        ".ag-row.status-vacant-opp .ag-cell": dict(_red_cell),
        ".ag-row.status-vacant": dict(_green),
        ".ag-row.status-vacant .ag-cell": dict(_green),
        ".ag-row.status-churning": dict(_yellow),
        ".ag-row.status-churning .ag-cell": dict(_yellow),
        ".ag-row.status-occupied": dict(_red_cell),
        ".ag-row.status-occupied .ag-cell": dict(_red_cell),
    }
    # Duplicate under common AG Grid theme roots so row colors win over Streamlit / Quartz defaults.
    out: dict[str, dict] = {}
    for sel, stl in rows.items():
        out[sel] = stl
        for root in (".ag-theme-streamlit", ".ag-theme-quartz", ".ag-theme-alpine", ".ag-theme-balham"):
            out[f"{root} {sel}"] = dict(stl)
    return out


def _should_hide_missing_type_floor_and_kitchen_name_row(r: dict) -> bool:
    """Hide when Type, Floor price, and Kitchen number/name are all absent or empty (no usable kitchen row)."""
    if not isinstance(r, dict):
        return False
    tk = _find_kitchen_type_column_key(r)
    fk = _find_floor_price_column_key(r)
    nk = _find_kitchen_number_name_column_key(r)
    # Sheet must expose at least one of these fields so we do not hide unrelated tabs/rows.
    if tk is None and fk is None and nk is None:
        return False
    type_missing = tk is None or _is_missing_kitchen_type_for_junk_filter(r.get(tk))
    floor_missing = fk is None or _is_missing_price_for_junk_filter(r.get(fk))
    name_missing = nk is None or _cell_is_empty_for_empty_row_check(r.get(nk))
    return type_missing and floor_missing and name_missing


def _should_hide_list_price_name_status_stage_sparse_row(r: dict) -> bool:
    """Hide padding rows: only List price + Kitchen name, optionally Status / Stage / inventory KPIs — nothing else meaningful."""
    if not isinstance(r, dict):
        return False
    skip = {"_has_opportunity", "Sheet", "km_row_cls"}
    lk = _find_list_price_column_key(r)
    nk = _find_kitchen_number_name_column_key(r)
    if lk is None or nk is None or lk == nk:
        return False
    if _cell_is_empty_for_empty_row_check(r.get(lk)) or _cell_is_empty_for_empty_row_check(r.get(nk)):
        return False

    def _allowed_sparse_key(k) -> bool:
        if k == lk or k == nk:
            return True
        if _is_kitchen_status_column_key(k):
            return True
        if _is_kitchen_stage_column_key(k):
            return True
        if _is_kitchen_inventory_kpi_column_key(k):
            return True
        return False

    for k, v in r.items():
        if k in skip:
            continue
        if _allowed_sparse_key(k):
            continue
        if _cell_is_empty_for_empty_row_check(v):
            continue
        if _scalar_counts_as_sheet_padding_zero(v):
            continue
        return False
    return True


def _should_hide_incomplete_kitchen_row(r: dict) -> bool:
    return (
        _should_hide_junk_kitchen_row(r)
        or _should_hide_no_status_sparse_kitchen_row(r)
        or _should_hide_missing_type_floor_and_kitchen_name_row(r)
        or _should_hide_list_price_name_status_stage_sparse_row(r)
    )


def _is_nonsense_kitchen_row(r: dict) -> bool:
    """True when a row matches sparse/junk patterns (any country / source)."""
    if not isinstance(r, dict):
        return True
    norm = _status_normalized_from_row(r)
    if not norm or norm == "No status" or _is_odd_kitchen_status_normalized(norm):
        return True
    if _should_hide_incomplete_kitchen_row(r):
        return True
    return False


def _filter_junk_kitchen_records(rows: list) -> list:
    """Drop incomplete / padding kitchen rows everywhere (Kitchen Master, Dashboard KSA+regional+Superset, search)."""
    if not rows:
        return rows
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if _is_nonsense_kitchen_row(r):
            continue
        out.append(r)
    return out


def _kuwait_regional_hidden_column(name: str) -> bool:
    n = (name or "").strip().lower()
    alnum = re.sub(r"[^a-z0-9]", "", n)
    if n == "_col9" or alnum == "col9":
        return True
    if alnum in ("salescomments", "amcsmcomments"):
        return True
    if "comment" in n and "sales" in n:
        return True
    if "comment" in n and ("am" in n or "csm" in n):
        return True
    return False


def _uae_regional_hidden_column(name: str, series) -> bool:
    n = (name or "").strip()
    if re.search(r"comment", n, re.I):
        return True
    if not re.match(r"^_col\d+$", n, re.I):
        return False
    try:
        ser = series.dropna().astype(str).str.strip()
    except Exception:
        return False
    ser = ser[ser != ""]
    if len(ser) == 0:
        return True
    sample = ser.head(min(120, len(ser)))

    def _numlike(x: str) -> bool:
        t = x.replace(",", "").replace("%", "").strip()
        return bool(re.match(r"^-?\d+\.?\d*$", t))

    num_ct = sum(1 for x in sample if _numlike(str(x)))
    return (num_ct / len(sample)) < 0.45


def _filter_regional_inventory_columns(region: str, cols: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    """Drop comment / junk columns for Kuwait/UAE regional Kitchen Master views."""
    if region not in ("Kuwait", "UAE") or not rows:
        return cols, rows
    tdf = pd.DataFrame(rows)
    drop: set[str] = set()
    for c in list(tdf.columns):
        cn = str(c)
        if region == "Kuwait" and _kuwait_regional_hidden_column(cn):
            drop.add(c)
        elif region == "UAE" and c in tdf.columns and _uae_regional_hidden_column(cn, tdf[c]):
            drop.add(c)
    cols2 = [c for c in cols if c not in drop]
    rows2 = [{k: v for k, v in (r or {}).items() if k not in drop} for r in rows]
    return cols2, rows2


def _build_aggrid_community_grid_options(df: pd.DataFrame, status_col: str | None) -> tuple[dict, dict, bool, str | None]:
    """Build grid options + optional custom CSS for row colors.

    Row colors use a Python-computed ``km_row_cls`` column plus simple ``rowClassRules`` (reliable on Streamlit Cloud).
    ``km_row_cls`` and ``_has_opportunity`` are omitted from column defs but remain in row data. JsCode/getRowStyle is not used.
    For modest row counts, ``domLayout: autoHeight`` removes the large empty band inside the grid.

    With Enterprise modules (default **trial** without a key, or with ``AG_GRID_LICENSE_KEY``), text columns use **Set Filter**
    (checkbox list of distinct values), plus **cell selection** so users can drag a range and **Ctrl+C** (with headers)
    like Excel. ``enableCellTextSelection`` stays off in that mode so it does not block range clipboard copy.
    With ``AG_GRID_ENTERPRISE_TRIAL=0`` (Community only), Set Filter is replaced by text filters and only in-cell text selection is enabled.

    Returns ``(grid_options, custom_css_dict, use_auto_height, enterprise_license_or_none)``.
    """
    if not GridOptionsBuilder:
        return {}, {}, False, None
    _ent_lic = _aggrid_enterprise_license_key()
    _use_set = _aggrid_use_enterprise_modules()
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        filter=True,
        sortable=True,
        resizable=True,
        floatingFilter=True,
        suppressHeaderMenuButton=False,
        suppressHeaderFilterButton=False,
        menuTabs=["filterMenuTab", "generalMenuTab", "columnsMenuTab"],
    )
    for col in df.columns:
        if _is_facility_name_aggrid_column(col):
            gb.configure_column(col, filter=False, floatingFilter=False, suppressHeaderFilterButton=True)
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            gb.configure_column(col, filter="agNumberColumnFilter", floatingFilter=True)
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            gb.configure_column(col, filter="agDateColumnFilter", floatingFilter=True)
        elif _use_set:
            gb.configure_column(
                col,
                filter="agSetColumnFilter",
                floatingFilter=True,
                filterParams={
                    "excelMode": "windows",
                    "buttons": ["reset", "apply"],
                },
            )
        else:
            gb.configure_column(
                col,
                filter="agTextColumnFilter",
                floatingFilter=True,
                filterParams={
                    "filterOptions": ["contains", "notContains", "equals", "notEqual", "startsWith", "endsWith"],
                    "buttons": ["apply", "reset"],
                    "maxNumConditions": 2,
                },
            )
    _n = len(df.index)
    _auto_h = _n <= 100
    gb.configure_grid_options(
        domLayout="autoHeight" if _auto_h else "normal",
        suppressMenuHide=False,
        columnMenu="legacy",
    )
    gb.configure_side_bar(filters_panel=False, columns_panel=False)
    go = gb.build()
    go["suppressCsvExport"] = True
    if "defaultColDef" not in go:
        go["defaultColDef"] = {}
    go["defaultColDef"]["filter"] = True
    go["defaultColDef"]["floatingFilter"] = True
    go["defaultColDef"]["minWidth"] = 140
    go["defaultColDef"]["suppressHeaderMenuButton"] = False
    go["defaultColDef"]["suppressHeaderFilterButton"] = False
    go["defaultColDef"]["wrapHeaderText"] = True
    go["defaultColDef"]["autoHeaderHeight"] = True
    go["defaultColDef"]["cellStyle"] = {"textAlign": "left"}
    # Clipboard: with Enterprise (default trial), ``enableCellTextSelection`` makes Ctrl+C copy only
    # highlighted in-cell text — not ranges. Cell selection + clipboard needs it off (AG Grid docs).
    if _use_set:
        go["cellSelection"] = {"enableColumnSelection": True}
        go["copyHeadersToClipboard"] = True
        go["defaultColDef"]["enableCellTextSelection"] = False
    else:
        go["defaultColDef"]["enableCellTextSelection"] = True
        go["ensureDomOrder"] = True
    if "floatingFiltersHeight" in go:
        del go["floatingFiltersHeight"]
    _hidden_fields = {"_has_opportunity", "km_row_cls"}
    _column_defs = [c for c in (go.get("columnDefs") or []) if c.get("field") not in _hidden_fields]
    go["columnDefs"] = _column_defs
    for cdef in _column_defs:
        _fn = cdef.get("field")
        if _is_facility_name_aggrid_column(_fn):
            cdef["filter"] = False
            cdef["floatingFilter"] = False
            cdef["suppressHeaderFilterButton"] = True
        else:
            # Preserve explicit filter types from GridOptionsBuilder (agSetColumnFilter / agTextColumnFilter / …).
            # Overwriting with ``True`` breaks column filters and removes the value list UI for Set Filter.
            _ft = cdef.get("filter")
            if not isinstance(_ft, str):
                if _fn and _fn in df.columns:
                    if pd.api.types.is_numeric_dtype(df[_fn]):
                        cdef["filter"] = "agNumberColumnFilter"
                    elif pd.api.types.is_datetime64_any_dtype(df[_fn]):
                        cdef["filter"] = "agDateColumnFilter"
                    elif _use_set:
                        cdef["filter"] = "agSetColumnFilter"
                        cdef["filterParams"] = {
                            "excelMode": "windows",
                            "buttons": ["reset", "apply"],
                        }
                    else:
                        cdef["filter"] = "agTextColumnFilter"
                        cdef["filterParams"] = {
                            "filterOptions": ["contains", "notContains", "equals", "notEqual", "startsWith", "endsWith"],
                            "buttons": ["apply", "reset"],
                            "maxNumConditions": 2,
                        }
                else:
                    cdef["filter"] = "agTextColumnFilter" if not _use_set else "agSetColumnFilter"
                    if not _use_set and isinstance(cdef.get("filter"), str) and cdef["filter"] == "agTextColumnFilter":
                        cdef["filterParams"] = {
                            "filterOptions": ["contains", "notContains", "equals", "notEqual", "startsWith", "endsWith"],
                            "buttons": ["apply", "reset"],
                            "maxNumConditions": 2,
                        }
            cdef["floatingFilter"] = True
            cdef["suppressHeaderFilterButton"] = False
        if cdef.get("type") == []:
            cdef.pop("type", None)
    custom_css: dict = {}
    if "km_row_cls" in df.columns:
        go["rowClassRules"] = _aggrid_kitchen_master_row_class_rules_simple()
        custom_css = _aggrid_kitchen_master_status_custom_css()
    return go, custom_css, _auto_h, _ent_lic


def _render_master_table_aggrid_or_df(
    df: pd.DataFrame,
    rows_shown: list,
    *,
    grid_key: str,
    status_col: str | None,
    allow_download: bool,
    export_file_stem: str,
    export_button_key: str,
    row_count_placeholder=None,
) -> None:
    """Kitchen Master table: AgGrid Community (rowClassRules + custom_css colors) or native dataframe fallback."""
    if df is None or df.empty:
        if rows_shown:
            st.warning(
                "The table is empty after preparing rows (unexpected). Try **Refresh** in the sidebar, or switch "
                "**Kitchen Master data source** to **Google Sheet** if you expect live sheet data."
            )
        else:
            st.info("No rows to show in this view.")
        return
    df = _prepare_kitchen_master_dataframe_for_display(df, rows_shown)
    # Column prep can change dtypes/names; re-resolve Status for Ag Grid rowClassRules + Styler.
    status_col = _status_column_from_dataframe(df) or status_col
    _n_rows = len(df.index)
    _viewport_h = _kitchen_master_viewport_height_px(_n_rows)
    _cc = {"_has_opportunity": None}
    try:
        _cc.update(_streamlit_number_column_config_for_df(df))
    except Exception:
        pass
    want_grid = bool(
        _HAS_AGGRI
        and AgGrid
        and GridOptionsBuilder
        and _kitchen_master_use_aggrid()
        and not _use_compact_tables()
    )
    df_ag = df
    if status_col and str(status_col) in df.columns:
        df_ag = df.copy()
        _hop_from_rows: list[bool] | None = None
        if rows_shown is not None and len(rows_shown) == len(df_ag.index):
            try:
                _hop_from_rows = [bool(_row_has_opportunity_name(r)) for r in rows_shown]
            except Exception:
                _hop_from_rows = None
        if _hop_from_rows is None:
            # Fallback to dataframe rows so "Vacant + opportunity" color still applies
            # even when rows_shown length diverges from df_ag (filters/transforms).
            _hop_from_rows = [bool(_row_has_opportunity_name(r)) for r in df_ag.to_dict(orient="records")]
        if "_has_opportunity" in df_ag.columns:
            try:
                _existing = df_ag["_has_opportunity"].fillna(False).astype(bool).tolist()
            except Exception:
                _existing = [bool(v) for v in df_ag["_has_opportunity"].tolist()]
            df_ag["_has_opportunity"] = [bool(a or b) for a, b in zip(_existing, _hop_from_rows)]
        else:
            df_ag["_has_opportunity"] = _hop_from_rows
        df_ag["km_row_cls"] = _compute_km_row_cls_series(df_ag, status_col)
    if want_grid and _kitchen_master_streamlit_value_list_filters():
        df_ag, rows_shown = _apply_streamlit_status_value_filter(
            df_ag, rows_shown, status_col=status_col, grid_key=grid_key
        )
        _n_rows = len(df_ag.index)
        if df_ag.empty:
            st.info("No rows match the Status filter above. Select more values in the multiselect.")
            return
        if status_col and str(status_col) in df_ag.columns:
            df_ag["km_row_cls"] = _compute_km_row_cls_series(df_ag, status_col)
    if want_grid:
        try:
            go, ag_custom_css, _use_ag_auto_height, _ag_lic = _build_aggrid_community_grid_options(df_ag, status_col)
        except Exception:
            go = None
            _ag_lic = None
        # On mobile the AgGrid sidebar tab ("Columns" vertical strip on the right edge)
        # gets clipped off-screen. Hide just the sidebar; keep the floating toolbar so
        # the expand/fullscreen button stays accessible and column header filters work.
        _is_mobile_view = _mobile_mode_enabled()
        if go and _is_mobile_view:
            go["sideBar"] = False
            _dcd = go.setdefault("defaultColDef", {})
            _dcd["suppressHeaderMenuButton"] = True
        if go:
            if not _aggrid_use_enterprise_modules():
                st.caption(
                    "Block copy (**click-drag** or **Shift+click**, then **Ctrl+C**) needs AG Grid Enterprise features. "
                    "This app loads them by default; if you set **AG_GRID_ENTERPRISE_TRIAL=0**, only single-cell text "
                    "selection is available."
                )
            _ag_iframe_h = _kitchen_master_aggrid_iframe_height_px(_n_rows, auto_height_layout=_use_ag_auto_height)
            _kwargs = dict(
                gridOptions=go,
                fit_columns_on_grid_load=False,
                height=_ag_iframe_h,
                theme="streamlit",
                show_toolbar=True,
                # Quick search persists client-side and has caused blank / "No rows" grids; column filters stay on.
                show_search=False,
                show_download_button=False,
                enable_enterprise_modules=_aggrid_use_enterprise_modules(),
                license_key=_ag_lic,
                allow_unsafe_jscode=False,
                key=grid_key,
                # Fewer moving parts on first paint vs filtered/sorted round-trips from an empty client grid.
                use_json_serialization=True,
            )
            if DataReturnMode is not None:
                try:
                    _kwargs["data_return_mode"] = DataReturnMode.AS_INPUT
                except Exception:
                    pass
            if isinstance(ag_custom_css, dict) and ag_custom_css:
                _kwargs["custom_css"] = ag_custom_css
            grid_response = None
            try:
                grid_response = AgGrid(df_ag, **_kwargs)
            except Exception:
                grid_response = None
            if grid_response is not None:
                _total = len(rows_shown) if rows_shown else 0
                _cnt = _total
                try:
                    _gd = grid_response.get("data") if hasattr(grid_response, "get") else None
                    if _gd is not None:
                        _cnt = len(_gd)
                except Exception:
                    pass
                if rows_shown:
                    try:
                        _kitchen_master_row_count_caption(
                            row_count_placeholder,
                            f"**{_cnt}** rows shown (out of **{_total}** total)",
                        )
                    except Exception:
                        pass
                    if allow_download:
                        try:
                            _rows_to_export = rows_shown
                            _gd2 = grid_response.get("data") if hasattr(grid_response, "get") else None
                            if _gd2 is not None:
                                _rows_to_export = _gd2
                            _render_export_button(
                                _normalize_export_rows_for_download(_rows_to_export),
                                export_file_stem,
                                key=export_button_key,
                            )
                        except Exception:
                            pass
                return
    if not _kitchen_master_plain_tables() and status_col:
        _df_show = _style_df_status_rows(df, status_col)
    else:
        _df_show = df
    # Pandas Styler: ``st.dataframe`` often drops row background colors in recent Streamlit; embed HTML instead.
    if _is_pandas_styler(_df_show):
        _html_sty = _df_show
        try:
            if hasattr(_df_show, "data") and "_has_opportunity" in _df_show.data.columns:
                _html_sty = _df_show.hide(axis="columns", subset=["_has_opportunity"])
        except Exception:
            pass
        try:
            # Taller minimum so Cloud layouts don’t clip the HTML table (iframe height is explicit).
            _ch = min(1200, max(360, _viewport_h + 48))
            st_components.html(
                f'<div style="width:100%;overflow:auto;font-family:system-ui,sans-serif;font-size:13px;'
                f'-webkit-user-select:text;user-select:text;">{_html_sty.to_html()}</div>',
                height=_ch,
                scrolling=True,
            )
        except Exception:
            try:
                st.dataframe(
                    _df_show,
                    use_container_width=True,
                    hide_index=True,
                    height=_viewport_h,
                    column_config={"_has_opportunity": None},
                )
            except Exception:
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    height=_viewport_h,
                    column_config=_cc,
                )
    else:
        try:
            st.dataframe(
                _df_show,
                use_container_width=True,
                hide_index=True,
                height=_viewport_h,
                column_config=_cc,
            )
        except Exception:
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                height=_viewport_h,
                column_config=_cc,
            )
    if rows_shown:
        _total_count = len(rows_shown)
        _kitchen_master_row_count_caption(
            row_count_placeholder,
            f"**{_total_count}** rows shown (out of **{_total_count}** total)",
        )
        if allow_download:
            _render_export_button(
                _normalize_export_rows_for_download(rows_shown),
                export_file_stem,
                key=export_button_key,
            )


def _render_generic_tab(
    tab_id,
    key_suffix="",
    is_developer=False,
    source=None,
    allow_download=False,
    hide_account_country=False,
    rows_override=None,
    drop_facility_name_column=False,
    regional_display: str | None = None,
):
    """View/filter for a generic tab. When source is set (e.g. 'gsheet'), read only from that source; else use session data_source. hide_account_country: when True (e.g. single facility in Master Kitchens), hide Account Country column. drop_facility_name_column: remove Facility Name column (Kuwait tab — avoids redundant filter UI). regional_display: Kuwait/UAE — hide comment columns for regional inventory view."""
    rows = rows_override if rows_override is not None else _list_generic_tab_cached(tab_id, source=source)
    # Kitchens: fallback to legacy SF Kitchen Data (before rename)
    if rows_override is None and not rows and tab_id == "Kitchens":
        rows = list_generic_tab("SF Kitchen Data", source=source) if source else list_generic_tab("SF Kitchen Data")
    # Master Kitchens list: fallback to Kitchens if empty
    if rows_override is None and not rows and tab_id == "Master Kitchens list":
        rows = (list_generic_tab("Kitchens", source=source) or list_generic_tab("SF Kitchen Data", source=source)) if source else (list_generic_tab("Kitchens") or list_generic_tab("SF Kitchen Data"))
    if not rows:
        st.info("No data yet. Data is refreshed every 15 minutes by the scheduler.")
        return
    rows = _filter_empty_records([r for r in (rows or []) if isinstance(r, dict)])
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
    if drop_facility_name_column:
        cols = [c for c in cols if not _is_facility_name_aggrid_column(c)]
        rows_shown = [{k: v for k, v in (r or {}).items() if not _is_facility_name_aggrid_column(k)} for r in rows]
    else:
        rows_shown = rows
    if regional_display in ("Kuwait", "UAE"):
        cols, rows_shown = _filter_regional_inventory_columns(regional_display, cols, rows_shown)
    rows_shown = _filter_junk_kitchen_records(rows_shown)
    _compact_tables = _use_compact_tables()
    if _compact_tables:
        _flt = st.container()
        with _flt:
            c_search, c_status = st.columns([2, 1])
            with c_search:
                _q = st.text_input(
                    "Search rows",
                    key=f"mobile_search_{key_suffix}_{tab_id}",
                    placeholder="Type to filter rows...",
                ).strip().lower()
            with c_status:
                _status_opts = ["All"]
                _status_vals = sorted({
                    str(r.get("Status") if "Status" in r else r.get("status__c") if "status__c" in r else r.get("status") or "").strip()
                    for r in rows_shown if isinstance(r, dict)
                })
                _status_vals = [s for s in _status_vals if s]
                if _status_vals:
                    _status_opts += _status_vals
                _status_pick = st.selectbox("Status", _status_opts, key=f"mobile_status_{key_suffix}_{tab_id}")
            with st.expander("More filters", expanded=False):
                _filterable_cols = [c for c in cols if rows_shown and c in rows_shown[0]]
                _mf_col = st.selectbox(
                    "Filter column",
                    options=["None"] + _filterable_cols,
                    key=f"mobile_filter_col_{key_suffix}_{tab_id}",
                )
                _mf_values = []
                if _mf_col != "None":
                    _raw_vals = sorted({
                        str((r or {}).get(_mf_col, "")).strip()
                        for r in rows_shown if isinstance(r, dict)
                    })
                    _raw_vals = [v for v in _raw_vals if v]
                    _mf_values = st.multiselect(
                        f"{_mf_col} values",
                        options=_raw_vals[:500],
                        key=f"mobile_filter_vals_{key_suffix}_{tab_id}",
                    )
        if _q:
            rows_shown = [
                r for r in rows_shown
                if any(_q in str(v).lower() for v in (r or {}).values() if v is not None)
            ]
        if _status_pick and _status_pick != "All":
            _pick = _status_pick.strip().lower()
            rows_shown = [
                r for r in rows_shown
                if str((r.get("Status") if "Status" in r else r.get("status__c") if "status__c" in r else r.get("status") or "")).strip().lower() == _pick
            ]
        if "_mf_col" in locals() and _mf_col != "None" and _mf_values:
            _mf_set = {str(v).strip() for v in _mf_values}
            rows_shown = [
                r for r in rows_shown
                if str((r or {}).get(_mf_col, "")).strip() in _mf_set
            ]
    rows_shown = _filter_empty_records(rows_shown)
    # Build display dataframe with selected columns only (Master list excludes Account Country)
    display_cols = [c for c in cols if rows_shown and c in (rows_shown[0].keys() if rows_shown else [])] or (list(rows_shown[0].keys()) if rows_shown else [])
    df_display = pd.DataFrame(rows_shown)[display_cols] if display_cols and rows_shown else pd.DataFrame(rows_shown)
    status_col = _status_column_from_dataframe(df_display)
    # Kitchen Master: AgGrid Community (filters + rowClassRules colors) or native dataframe fallback.
    if HAS_EXCEL and not df_display.empty:
        _df_show = df_display.copy()
        if status_col:
            if "_has_opportunity" not in _df_show.columns:
                _df_show["_has_opportunity"] = [_row_has_opportunity_name(r) for r in rows_shown]
        _tab_part = re.sub(r"[^0-9a-zA-Z]+", "_", str(tab_id))[:72].strip("_") or "tab"
        _render_master_table_aggrid_or_df(
            _df_show,
            rows_shown,
            grid_key=f"master_kitchens_grid_{key_suffix}_{_tab_part}",
            status_col=status_col,
            allow_download=allow_download,
            export_file_stem=f"{tab_id}_filtered",
            export_button_key=f"export_{key_suffix}_{tab_id}_master",
        )
    elif not HAS_EXCEL:
        st.warning("Cannot show the data grid: pandas is not available in this environment.")
    elif not rows_shown:
        st.info("No rows match the current filters.")
    elif df_display.empty:
        st.info("No rows to display in this view.")
    # CSV download disabled app-wide (no Download CSV button)


def main():
    st.set_page_config(page_title=APP_DISPLAY_TITLE, layout="wide", initial_sidebar_state="collapsed")
    # Session-level guardrail marker for any future feature toggles.
    st.session_state["_production_safe_mode"] = _production_safe_mode_enabled()
    init_db()
    _backfill_gsheet_family_refresh_metadata()
    # Initialize the cookie manager early so its component iframe renders before any
    # cookie read happens below; subsequent reads will return cached values.
    _get_cookie_manager()

    if _signed_out_gate_active():
        _render_signed_out_gate()

    # Identity: prefer verified email. Two platforms are supported with one code path:
    #   1) CSS data-apps (internal Notebooks): Okta SSO at the platform level. The
    #      streamlit_utils.auth helper is only importable inside that environment and
    #      returns the verified Okta email. Same code on Streamlit Cloud just hits the
    #      ImportError fallback and never touches this branch.
    #   2) Streamlit Cloud: st.user.is_logged_in from Streamlit's own OIDC, plus the
    #      remember-me cookie shim further down for mobile-Safari cookie clears.
    # Never trust URL params for access in either case.
    _verified_email = None
    _oidc_verified = False
    _streamlit_user = getattr(st, "user", None)
    try:
        from streamlit_utils import auth as _css_auth
        _css_email = (_css_auth.get_user_email() or "").strip()
        if _css_email and "@" in _css_email and not st.session_state.get("_force_signed_out"):
            _verified_email = _css_email
            _oidc_verified = True
            st.session_state["user_display_name"] = _css_email
    except Exception:
        # streamlit_utils not installed (Streamlit Cloud) or transient failure — fall through
        # to the Streamlit Cloud OIDC path below.
        pass
    if not _verified_email and _streamlit_user and getattr(_streamlit_user, "is_logged_in", False) and getattr(_streamlit_user, "email", None):
        _verified_email = (_streamlit_user.email or "").strip()
        _oidc_verified = bool(_verified_email)
        if _verified_email and not st.session_state.get("_force_signed_out"):
            st.session_state["user_display_name"] = _verified_email
    # After clicking Sign out, ignore st.user until user explicitly identifies again.
    if st.session_state.get("_force_signed_out"):
        _verified_email = None
        _oidc_verified = False
        st.session_state.pop("user_display_name", None)
    # Remember-me cookie fallback: when Streamlit's OIDC cookie has been cleared by the
    # mobile browser (iOS Safari ITP, link previewers, "Add to Home Screen" reopen), but
    # a valid signed remember-me cookie exists, treat the user as verified. Allowlist is
    # re-checked below, so a user removed from the allowlist still loses access on next load.
    if not _verified_email and not st.session_state.get("_force_signed_out"):
        _cookie_email = _try_restore_from_remember_me_cookie()
        if _cookie_email:
            _verified_email = _cookie_email
            st.session_state["user_display_name"] = _cookie_email
    # Refresh the remember-me cookie whenever we have a fresh OIDC verification, so each
    # successful sign-in extends the 30-day window. (No-op when the secret is unset.)
    if _oidc_verified and _verified_email:
        _set_remember_me_cookie(_verified_email)
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
        /* Do not use header * { color } — it breaks Streamlit's top toolbar icons on some builds. */
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
        .stDataFrame { border-radius: 8px; border: 1px solid #475569; background: #1E293B !important; -webkit-user-select: text !important; user-select: text !important; }
        .stDataFrame thead th { background: #334155 !important; color: #F1F5F9 !important; border-bottom: 2px solid #0F766E !important; }
        .stDataFrame tbody td { background: #1E293B !important; color: #E2E8F0 !important; -webkit-user-select: text !important; user-select: text !important; }
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
        header[data-testid="stHeader"] { background: #FFFFFF !important; border-bottom: 1px solid #E2E8F0; }
        /* Do not use header * { color } — it breaks Streamlit's top toolbar icons on some builds. */
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
        .stDataFrame { border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #E2E8F0; -webkit-user-select: text !important; user-select: text !important; }
        .stDataFrame thead th { background: #F1F5F9 !important; color: #1E293B !important; font-weight: 600 !important; padding: 10px 12px !important; border-bottom: 2px solid #0F766E !important; }
        .stDataFrame tbody td { padding: 8px 12px !important; -webkit-user-select: text !important; user-select: text !important; }
        [data-testid="stMetricValue"] { color: #1E293B !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] { font-size: 0.8rem !important; }
        section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
        .stCaption { color: #64748B !important; }
        div[data-testid="stVerticalBlock"] > div { padding-top: 0.25rem; }
        </style>
        """, unsafe_allow_html=True)

    # Section nav: tabs only (no dots) — bold text, active tab with teal underline
    st.markdown(
        """
    <style>
    /* Keep dataframe toolbar visible (Search + Fullscreen); hide only built-in CSV download */
    [data-testid="stElementToolbar"] { display: flex !important; visibility: visible !important; }
    [data-testid="stElementToolbar"] > *:nth-child(2) { display: none !important; visibility: hidden !important; pointer-events: none !important; }
    [data-testid="stElementToolbar"] button:nth-of-type(2) { display: none !important; visibility: hidden !important; pointer-events: none !important; }
    [data-testid="stElementToolbar"] [aria-label*="ownload"],
    [data-testid="stElementToolbar"] [aria-label*=" CSV"],
    [data-testid="stElementToolbar"] [title*="ownload"],
    [data-testid="stElementToolbar"] [title*=" CSV"],
    [data-testid="stElementToolbar"] button[title="Download as CSV"] { display: none !important; visibility: hidden !important; pointer-events: none !important; }
    /* AgGrid toolbar: hide Download as CSV (we use our own export gating) */
    [title="Download as CSV"],
    button[title="Download as CSV"],
    .ag-toolbar [title*="Download"],
    .ag-toolbar button[title*="CSV"],
    [class*="ag-"] [title="Download as CSV"] { display: none !important; visibility: hidden !important; pointer-events: none !important; }
    /* streamlit-aggrid: avoid extra blank strip under the iframe */
    iframe[title="st_aggrid"] { vertical-align: top !important; }
    /* Mobile Safari fallback for fullscreen button on dataframe toolbar:
       if native fullscreen fails, JS toggles this class on the table wrapper. */
    .mobile-fullscreen-fallback {
        position: fixed !important;
        inset: 0 !important;
        z-index: 1000000 !important;
        background: #ffffff !important;
        margin: 0 !important;
        padding: 8px !important;
        overflow: auto !important;
        width: 100vw !important;
        height: 100vh !important;
        max-width: 100vw !important;
        max-height: 100vh !important;
    }
    .mobile-fullscreen-fallback [data-testid="stDataFrame"] {
        height: calc(100vh - 24px) !important;
        min-height: calc(100vh - 24px) !important;
    }
    /* Shift main block only — padding stAppViewContainer can clip the Streamlit header on some builds. */
    [data-testid="stAppViewContainer"] > div { padding-top: unset !important; margin-top: unset !important; }
    [data-testid="stAppViewContainer"] { padding-top: unset !important; }
    .block-container { padding-top: 8px !important; }
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
    /* Keep Streamlit top chrome visible; offset content inside main only. */
    header[data-testid="stHeader"] {
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
        position: relative !important;
        z-index: 100000 !important;
    }
    div[data-testid="stToolbar"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        z-index: 100001 !important;
    }
    [data-testid="stMain"] { padding-top: unset !important; }
    [data-testid="stMain"] > div { padding-top: unset !important; margin-top: unset !important; }
    .stMainBlockContainer { padding-top: unset !important; }
    .stMain .block-container { padding-top: 8px !important; }
    /* ========== Header: Tailwind-style single row (px-6 py-3, border-gray-100, shadow-sm) ========== */
    .header-top-bar + div {
        position: relative !important;
        z-index: 1 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        height: 72px !important;
        min-height: 72px !important;
        max-width: 1600px !important;
        width: 100% !important;
        margin: 12px auto 0 auto !important;
        padding: clamp(12px, 2vw, 24px) clamp(16px, 3vw, 24px) !important;
        border-bottom: 1px solid #f3f4f6 !important;
        background: #ffffff !important;
        box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05) !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
        box-sizing: border-box !important;
    }
    @media (max-width: 768px) {
        .header-top-bar + div { margin-top: 10px !important; padding: 12px 16px !important; min-height: auto !important; height: auto !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; height: auto !important; min-height: 56px !important; gap: 12px !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"] { height: auto !important; min-height: 44px !important; }
        .header-top-bar + div [data-testid="stVerticalBlock"] { height: auto !important; }
        .header-top-bar + div [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child { min-width: 0 !important; }
        .header-brand-title { font-size: 1.125rem !important; }
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
        font-size: 1.75rem !important;
        font-weight: 700 !important;
        margin: 0 !important;
        letter-spacing: -0.025em !important;
        line-height: 1.2 !important;
        display: inline-block !important;
        max-width: min(58vw, 720px) !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        vertical-align: middle !important;
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
    """,
        unsafe_allow_html=True,
    )

    # Keep only a tiny spacer before custom header row.
    st.markdown('<div style="height: 6px;"></div>', unsafe_allow_html=True)

    # Top bar (replaces sidebar): compact two-row layout
    last_gsheet = _latest_refresh_among_gsheet_family()
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
                _remembered = (st.session_state.get("remembered_email") or "").strip()
                st.text_input(
                    "Your email",
                    key="user_display_name",
                    value=_remembered,
                    placeholder="e.g. jane@company.com",
                    help="Used for access check and comments. Must be on the allowed list.",
                )
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
                _remembered = (st.session_state.get("remembered_email") or "").strip()
                st.text_input(
                    "Your name or email",
                    key="user_display_name",
                    value=_remembered,
                    placeholder="e.g. jane@company.com",
                    help="Shown on comments and discussions. Not used for access when allowlist is off.",
                )
            current_user = (st.session_state.get("user_display_name") or "").strip()

    # User has identified again; clear one-shot sign-out guard.
    if current_user:
        st.session_state.pop("_force_signed_out", None)
        try:
            qp = getattr(st, "query_params", None)
            if qp is not None:
                qp.pop(_TRACKER_PARAM_SIGNED_OUT, None)
        except Exception:
            pass

    # Persist session to URL params so refresh keeps user for SESSION_PERSISTENCE_HOURS
    if current_user:
        _persist_session_to_params(current_user)
        # Also mint/refresh the 30-day remember-me cookie. This covers both the OIDC
        # path (where _verified_email was set earlier) and the typed-email gate, so
        # users who just type their email keep their session across mobile-Safari
        # cookie clears too. Only persist when the value is an email (skips the
        # developer-key path where current_user can be a display name). Allowlist
        # is still rechecked on every restore, so a removed user loses access on
        # next load even if their cookie is still valid.
        if "@" in current_user and "." in current_user.split("@")[-1]:
            _set_remember_me_cookie(current_user)

    def _developer_section_visible(user: str) -> bool:
        ids_list = _developer_ids_merged_list()
        if not ids_list:
            return False
        if _is_developer():
            return True
        return (user or "").strip().lower() in ids_list

    # Do NOT set developer_unlocked from DEVELOPER_IDS. RBAC grants Dashboard for DEVELOPER_IDS via super_user; developer key is separate.

    # Single-row top bar: logo + title/status (left) | help, avatar, sign out (right)
    status_label, status_color, status_ts = _data_status_from_pulse(last_gsheet)
    status_class = "live" if "Live" in status_label else ("delayed" if "Delayed" in status_label else "stale")
    updated_ago = _format_updated_ago(last_gsheet)
    _compact_ui = _compact_layout_enabled()
    # Keep native Streamlit header/toolbar behavior untouched.
    with st.container():
        if _compact_ui:
            c_logo, c_main = st.columns([1, 3])
            with c_logo:
                logo_path = _logo_path()
                if logo_path:
                    st.image(str(logo_path), width=84)
                else:
                    st.markdown('<div class="header-logo-box">K</div>', unsafe_allow_html=True)
            with c_main:
                _hdr_full = APP_DISPLAY_TITLE
                st.markdown(
                    f'<div class="header-brand-status">'
                    f'<div class="header-title-block">'
                    f'<h1 class="header-brand-title" style="font-size:1.6rem;margin-bottom:2px;" title="{html.escape(_hdr_full, quote=True)}">{html.escape(_hdr_full)}</h1>'
                    f'<div class="header-status-row">'
                    f'<span class="header-status-pill {status_class}">'
                    f'<span class="header-status-dot"></span> {status_label.replace(" ", " ")}</span>'
                    f'<span class="header-updated-muted">{updated_ago}</span>'
                    f'</div></div></div>',
                    unsafe_allow_html=True,
                )
            c_help, c_sign = st.columns([1, 2])
            with c_help:
                st.markdown(
                    '<a href="mailto:maysam.abukashabeh@cloudkitchens.com" class="header-icon-btn header-help-btn" title="Help">?</a>',
                    unsafe_allow_html=True,
                )
            with c_sign:
                if st.button("Sign out", key="header_sign_out_mobile", help="Sign out", use_container_width=True):
                    _do_sign_out()
        else:
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
                    _hdr_full = APP_DISPLAY_TITLE
                    st.markdown(
                        f'<div class="header-brand-status">'
                        f'<div class="header-divider"></div>'
                        f'<div class="header-title-block">'
                        f'<h1 class="header-brand-title" title="{html.escape(_hdr_full, quote=True)}">{html.escape(_hdr_full)}</h1>'
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
                        _do_sign_out()
    st.markdown(
        '<div class="header-bottom-line" style="height:1px;background:rgba(0,0,0,0.06);margin:0 16px;max-width:1600px;margin-left:auto;margin-right:auto;"></div>',
        unsafe_allow_html=True,
    )
    # No mobile toggles: keep behavior consistent across devices.
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
        # 1) SUPER_USER_EMAILS in secrets = grant Dashboard
        # 2) DEVELOPER_IDS (built-in + secrets) = same super_user access (Dashboard + Kitchen Master + Discussions)
        super_emails = _get_super_user_emails()
        try:
            dev_ids_set = set(_developer_ids_merged_list())
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
    can_export = _can_user_export(current_user)
    st.session_state["can_export"] = can_export
    _is_market_admin = _is_developer() or user_role in ("super_user", "manager_viewer")
    _market_matches = _market_matches_for_user(current_user)
    if _allowlist_enabled() and not _is_market_admin:
        if not _market_matches:
            st.error("Access restricted. Your account is approved, but no market access is configured.")
            st.caption(
                "Please ask the admin to add your email to at least one MARKET_VIEW list "
                "(KSA, UAE, Kuwait, or Bahrain)."
            )
            _seen_email = (current_user or "").strip()
            if _seen_email:
                st.caption(f"Signed-in email detected: `{_seen_email}`")
            _dbg = _market_membership_debug(current_user)
            if _dbg:
                _parts = [f"{label}: match={'yes' if matched else 'no'}, ids={count}" for (label, matched, count) in _dbg]
                st.caption("Market debug: " + " | ".join(_parts))
            st.stop()
    _market_scope = _market_scope_for_user(current_user, user_role)
    _scoped_markets = [m for m in ("Saudi Arabia", "UAE", "Kuwait", "Bahrain") if m in set(_market_matches)]

    def _dashboard_access_allowed(user_email: str | None) -> bool:
        if _is_developer():
            return True
        u = (user_email or "").strip().lower()
        if not u:
            return False
        local = u.split("@", 1)[0] if "@" in u else u
        dev_expanded = _email_set_with_local_parts(set(_developer_ids_merged_list()))
        return u in dev_expanded or local in dev_expanded

    _can_open_dashboard = _dashboard_access_allowed(current_user)

    def _section_display_name(opt: str) -> str:
        if (
            opt == SECTION_KSA
            and not _is_market_admin
            and _scoped_markets
        ):
            if len(_scoped_markets) == 1:
                return "KSA" if _scoped_markets[0] == "Saudi Arabia" else _scoped_markets[0]
            return "Markets"
        return opt
    # Product shape: section navigation by role (Admin tab removed).
    # PREVIEW_ONLY_IDS / regional preview secrets: same users who see KW/UAE/BH in Kitchen Master get Dashboard (all countries UX).
    _preview_regional = _user_can_see_bahrain_kitchen_preview(current_user or "")
    if _can_open_dashboard:
        section_options = [SECTION_KSA, "Dashboard", "Discussions"]
    else:
        section_options = [SECTION_KSA, "Discussions"]
    # Ensure Admin never appears (defensive)
    section_options = [s for s in section_options if s != "Admin / Data Health"]
    if not section_options:
        section_options = [SECTION_KSA, "Discussions"]
    # Website-style layout: section navigation as tabs
    if "section_radio" not in st.session_state:
        st.session_state["section_radio"] = section_options[0]
    section = st.session_state["section_radio"]
    # Ensure current value is in options (e.g. after role change or Search tab removed)
    if section not in section_options:
        section = section_options[0]
        st.session_state["section_radio"] = section
    if section == _LEGACY_SECTION_KITCHEN_MASTER:
        section = SECTION_KSA
        st.session_state["section_radio"] = SECTION_KSA

    # Tab row: desktop buttons; compact mode uses a single segmented control.
    if _compact_layout_enabled():
        _sel = st.selectbox(
            "Section",
            options=section_options,
            index=section_options.index(section) if section in section_options else 0,
            key="section_mobile_selector",
            format_func=_section_display_name,
        )
        if _sel and _sel != section:
            st.session_state["section_radio"] = _sel
            _rerun()
    else:
        tab_cols = st.columns(len(section_options))
        for i, opt in enumerate(section_options):
            with tab_cols[i]:
                is_selected = opt == section
                if st.button(
                    _section_display_name(opt),
                    key=f"section_tab_{i}_{opt.replace(' ', '_')}",
                    type="primary" if is_selected else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["section_radio"] = opt
                    _rerun()

    # Master Kitchens: prefer persisted Superset store; else legacy Kitchens/generic_tab
    if section == SECTION_KSA:
        st.session_state.pop("preview_kitchen_region", None)
        if not _is_market_admin and _scoped_markets:
            if len(_scoped_markets) == 1:
                _single = _scoped_markets[0]
                if _single in ("Kuwait", "UAE", "Bahrain"):
                    st.caption(f"Market-scoped view: **{_single}**")
                    _render_preview_regional_kitchen_master(
                        _single, can_export=can_export, is_developer=is_developer
                    )
                    return
                st.caption("Market-scoped view: **Saudi Arabia (KSA)**")
                _render_kitchen_master_ksa_main(can_export=can_export, is_developer=is_developer)
                return
            _market_pick = st.selectbox(
                "Market view",
                options=_scoped_markets,
                key="market_scoped_kitchen_picker",
                format_func=lambda x: "Saudi Arabia (KSA)" if x == "Saudi Arabia" else x,
            )
            st.caption(f"Market-scoped view: **{'Saudi Arabia (KSA)' if _market_pick == 'Saudi Arabia' else _market_pick}**")
            if _market_pick == "Saudi Arabia":
                _render_kitchen_master_ksa_main(can_export=can_export, is_developer=is_developer)
            else:
                _render_preview_regional_kitchen_master(
                    _market_pick, can_export=can_export, is_developer=is_developer
                )
            return
        # PREVIEW_ONLY_IDS / super_user / manager_viewer: KSA master + optional Kuwait / UAE / Bahrain workbooks.
        if _user_sees_dashboard_all_countries(current_user, user_role):
            st.caption(
                "The **KSA** tab shows the main kitchen workbook by default. "
                "Use **Kuwait / UAE / Bahrain** (preview testers) for regional workbooks — then **Main** to return."
            )
            _km_region = _kitchen_master_region_selector_ui()
            if _km_region == KITCHEN_MASTER_SUBVIEW_MAIN:
                _render_kitchen_master_ksa_main(can_export=can_export, is_developer=is_developer)
            elif _km_region == "Kuwait":
                _render_preview_regional_kitchen_master(
                    "Kuwait", can_export=can_export, is_developer=is_developer
                )
            elif _km_region == "UAE":
                _render_preview_regional_kitchen_master(
                    "UAE", can_export=can_export, is_developer=is_developer
                )
            else:
                _render_preview_regional_kitchen_master(
                    "Bahrain", can_export=can_export, is_developer=is_developer
                )
        else:
            _render_kitchen_master_ksa_main(can_export=can_export, is_developer=is_developer)


    # Dashboard: management view (section_options already restricts who sees the button)
    elif section == "Dashboard":
        if not _can_open_dashboard:
            st.error("Access restricted. Dashboard is available only for DEVELOPER_IDS users.")
            st.stop()
        superset_rows, superset_meta = _get_superset_master_kitchens()
        dashboard_from_superset = superset_rows is not None
        if dashboard_from_superset:
            if _superset_stale_warning(superset_meta or {}):
                st.warning("Last refresh is older than 30 minutes or last run failed.")
            rows_kitchens = superset_rows
        else:
            # Prefer per-facility tabs with Sheet = tab name (same as Kitchen Master); fallback to consolidated Kitchens tab.
            _tabbed = _dashboard_load_gsheet_rows_with_sheet_stamp()
            if _tabbed:
                rows_kitchens = _tabbed
            else:
                rows_kitchens = list_generic_tab("Kitchens", source="gsheet") or list_generic_tab("Master Kitchens list", source="gsheet") or []
        # Kuwait + UAE facility sheets: merge for all Dashboard users. Bahrain merge + country filter extras when
        # ``_user_sees_dashboard_all_countries`` (PREVIEW_ONLY_IDS / secrets, developer, or super_user / manager_viewer).
        # Refresh from Google Sheets when stale (15 min) to avoid fetching both workbooks every rerun.
        _kuwait_dashboard_rows: list[dict] = []
        _uae_dashboard_rows: list[dict] = []
        _bahrain_dashboard_rows: list[dict] = []
        _creds_dash = _get_google_credentials_path()
        if _creds_dash:
            _sid_kw, _, _, _gkw = _regional_kitchen_workbook_settings("Kuwait")
            _sid_ae, _, _, _gae = _regional_kitchen_workbook_settings("UAE")
            _sid_bh, _, _, _gbh = _regional_kitchen_workbook_settings("Bahrain")
            if _sid_kw and _source_refresh_is_stale(_gkw, 15):
                _refresh_kuwait_workbook_from_sheets(silent=True)
            if _sid_kw:
                _kuwait_dashboard_rows = _load_kuwait_dashboard_rows()
            if _sid_ae and _source_refresh_is_stale(_gae, 15):
                _refresh_uae_workbook_from_sheets(silent=True)
            if _sid_ae:
                _uae_dashboard_rows = _load_uae_dashboard_rows()
            if _sid_bh and (
                _user_sees_dashboard_all_countries(current_user, user_role)
                or _market_scope == "Bahrain"
            ):
                if _source_refresh_is_stale(_gbh, 15):
                    _refresh_bahrain_workbook_from_sheets(silent=True)
                _bahrain_dashboard_rows = _load_bahrain_dashboard_rows()
        # Ensure Account Country for filtering (Kitchens / Master list may use County or other keys)
        rows_kitchens = _ensure_account_country_in_kitchens(rows_kitchens)
        if _kuwait_dashboard_rows or _uae_dashboard_rows or _bahrain_dashboard_rows:
            rows_kitchens = (rows_kitchens or []) + _kuwait_dashboard_rows + _uae_dashboard_rows + _bahrain_dashboard_rows
        # Enrich with go-live / is_live: facility CSV (data/sa_bh_facility_go_live.csv) + optional BigQuery
        bq_go_live = _fetch_bigquery_go_live()
        csv_go_live = _fetch_facility_go_live_csv()
        go_live_rows = (csv_go_live or []) + (bq_go_live or [])
        if go_live_rows:
            rows_kitchens = _merge_go_live_into_kitchens(rows_kitchens, go_live_rows)
        # Same junk/sparse-row rules as Kitchen Master (KSA + Kuwait/UAE/Bahrain + Superset).
        rows_kitchens = _filter_junk_kitchen_records(rows_kitchens or [])
        today_str = date.today().isoformat()
        if snapshot_mod and rows_kitchens:
            if not snapshot_mod.snapshot_exists_for_date(today_str):
                try:
                    snapshot_mod.write_daily_snapshot(rows_kitchens, today_str)
                except Exception:
                    pass
        has_go_live = bool(go_live_rows)

        def _country_label(raw: str) -> str:
            """Normalize labels so UAE/Kuwait/BH… regional and KSA exports group in one filter bucket."""
            s = (raw or "").strip()
            if not s:
                return ""
            if _raw_country_means_bahrain(s):
                return "Bahrain"
            low = s.lower().replace(".", "").replace(" ", "")
            if low in ("uae", "ae", "unitedarabemirates"):
                return "UAE"
            if low in ("kw", "kuwait"):
                return "Kuwait"
            return s

        def _country(r):
            """Country for a row (Account Country, County, or other country header)."""
            for k in ("Account Country", "County", "Account__r.Country__c", "Country__c", "Country", "account country", "county"):
                v = r.get(k)
                if v is not None and str(v).strip():
                    return _country_label(str(v).strip())
            return ""

        def _dashboard_row_country(r):
            """Country for dashboard: sheet columns first; else infer from kitchen number/name (SA/KSA, BH, KWT, UAE); else Saudi Arabia."""
            c = _country(r)
            if c:
                return c
            inferred = _country_from_kitchen_number_or_name(_kitchen_number_name_blob(r))
            if inferred:
                return _country_label(inferred)
            return "Saudi Arabia"

        if _scoped_markets:
            rows_kitchens = [
                r for r in (rows_kitchens or [])
                if _dashboard_row_country(r) in set(_scoped_markets)
            ]

        def _facility_select_options(sel_country: str, rows_subset: list) -> list[str]:
            """Facility dropdown: same tab names as Kitchen Master for that country, union any row-derived names.

            When Country is **All**, list every KSA worksheet plus regional facility tabs (if user sees all countries),
            not only facilities that already have rows — so empty sheets still appear like the workbook.
            """
            row_facs = {_dashboard_facility_from_row(r) for r in rows_subset}
            row_facs = {f for f in row_facs if f}
            if sel_country and sel_country not in ("All", "(No country)") and not dashboard_from_superset:
                tabs = _dashboard_kitchen_master_tab_names_for_country(
                    sel_country, current_user=current_user, user_role=user_role
                )
                if tabs is not None:
                    opts = sorted(set(tabs) | row_facs, key=str.casefold)
                else:
                    opts = sorted(row_facs, key=str.casefold)
                return opts if opts else ["(No facility)"]
            if dashboard_from_superset:
                opts = sorted(row_facs, key=str.casefold)
                return opts if opts else ["(No facility)"]
            tab_union: set[str] = set(row_facs)
            for t in _master_kitchens_other_sheet_ids() or []:
                if t:
                    tab_union.add(t)
            if _user_sees_dashboard_all_countries(current_user, user_role):
                hidden = _regional_preview_hidden_tab_names_lower()
                for src_tabs in (
                    list_tab_ids_for_source(GSOURCE_KITCHEN_KW),
                    list_tab_ids_for_source(GSOURCE_KITCHEN_AE),
                    list_tab_ids_for_source(GSOURCE_KITCHEN_BH),
                ):
                    for t in src_tabs:
                        if (t or "").strip().lower() not in hidden:
                            tab_union.add(t)
            opts = sorted(tab_union, key=str.casefold)
            return opts if opts else ["(No facility)"]

        # —— Country, Facility, and Live status filters (drive all dashboard data) ——
        _from_rows = {_dashboard_row_country(r) for r in rows_kitchens}
        _extras = sorted(
            {c for c in _from_rows if c not in set(DASHBOARD_COUNTRY_FILTER_CORE)},
            key=str.casefold,
        )
        _regional_preview_dash = _user_sees_dashboard_all_countries(current_user, user_role)
        _core_countries = list(DASHBOARD_COUNTRY_FILTER_CORE)
        if _scoped_markets:
            _core_countries = list(_scoped_markets)
            _extras = []
        elif not _regional_preview_dash:
            _core_countries = [c for c in _core_countries if c == "Saudi Arabia"]
            _extras = [
                c
                for c in _extras
                if (c or "").strip() not in ("Bahrain", "Kuwait", "UAE")
            ]
        unique_countries = _core_countries + _extras
        n_filter_cols = 3 if has_go_live else 2
        selected_live = "All"
        if _compact_layout_enabled():
            selected_country = st.selectbox(
                "Country",
                options=["All"] + unique_countries,
                key="dashboard_country",
                help="Filter by country. If Country/County are blank, the app uses kitchen number/name (e.g. UAE, KWT, BH, SA/KSA). Otherwise defaults to Saudi Arabia.",
            )
            if selected_country and selected_country != "All":
                rows_for_facilities = [r for r in rows_kitchens if _dashboard_row_country(r) == selected_country]
            else:
                rows_for_facilities = rows_kitchens
            facility_set = _facility_select_options(selected_country or "All", rows_for_facilities)
            selected_facility = st.selectbox(
                "Facility",
                options=["All"] + facility_set,
                key="dashboard_facility",
                help="Facilities match Kitchen Master worksheet names for this country (tab / Sheet).",
            )
            if has_go_live:
                selected_live = st.selectbox(
                    "Live status",
                    options=["All", "Live", "Not live"],
                    key="dashboard_live",
                    help="Filter by kitchens marked live vs not live (from BigQuery go-live data).",
                )
        else:
            filter_cols = st.columns(n_filter_cols)
            with filter_cols[0]:
                selected_country = st.selectbox(
                    "Country",
                    options=["All"] + unique_countries,
                    key="dashboard_country",
                    help="Filter by country. If Country/County are blank, the app uses kitchen number/name (e.g. UAE, KWT, BH, SA/KSA). Otherwise defaults to Saudi Arabia.",
                )
            with filter_cols[1]:
                # Facilities depend on selected country
                if selected_country and selected_country != "All":
                    rows_for_facilities = [r for r in rows_kitchens if _dashboard_row_country(r) == selected_country]
                else:
                    rows_for_facilities = rows_kitchens
                facility_set = _facility_select_options(selected_country or "All", rows_for_facilities)
                selected_facility = st.selectbox(
                    "Facility",
                    options=["All"] + facility_set,
                    key="dashboard_facility",
                    help="Facilities match Kitchen Master worksheet names for this country (tab / Sheet).",
                )
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
            rows_kitchens = [r for r in rows_kitchens if _dashboard_row_country(r) == selected_country]
        if selected_facility and selected_facility != "All":
            rows_kitchens = [
                r for r in rows_kitchens
                if (_dashboard_facility_from_row(r) or "(No facility)") == selected_facility
            ]
        if selected_live == "Live":
            rows_kitchens = [r for r in rows_kitchens if r.get("Is Live") is True]
        elif selected_live == "Not live":
            rows_kitchens = [r for r in rows_kitchens if r.get("Is Live") is False]
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
    <script>
    (function() {
      if (window.__mobileFullscreenPatched) return;
      window.__mobileFullscreenPatched = true;
      function closestDataframeWrap(el) {
        var n = el;
        while (n && n !== document.body) {
          if (n.querySelector && n.querySelector('[data-testid="stDataFrame"]')) return n;
          n = n.parentElement;
        }
        return null;
      }
      document.addEventListener('click', function(ev) {
        var btn = ev.target && ev.target.closest ? ev.target.closest('button,[role="button"]') : null;
        if (!btn) return;
        var label = ((btn.getAttribute('aria-label') || '') + ' ' + (btn.getAttribute('title') || '')).toLowerCase();
        if (!(label.includes('full') || label.includes('expand'))) return;
        var wrap = closestDataframeWrap(btn);
        if (!wrap) return;
        // Let native fullscreen run first; if it fails on mobile Safari, apply fallback.
        setTimeout(function() {
          var inNative = !!document.fullscreenElement;
          if (!inNative) {
            wrap.classList.toggle('mobile-fullscreen-fallback');
          }
        }, 80);
      }, true);
    })();
    </script>
        """, unsafe_allow_html=True)
        glance_label = f"{selected_country or 'All'} at a glance" if (selected_country and selected_country != "All") else "All countries at a glance"
        st.markdown(
            f'<div class="dashboard-summary"><strong>{glance_label}</strong> · {total:,} kitchens · {vacant:,} vacant · {occupied:,} occupied · {sold:,} sold · {vacant_approved_deal:,} approved deal{"s" if vacant_approved_deal != 1 else ""}</div>',
            unsafe_allow_html=True,
        )
        # —— Scorecard (Sales-first: Sold Rate + Ops Occupancy) ——
        st.subheader("Scorecard")
        _score_metrics = [
            ("Total kitchens", f"{total:,}", "Sellable only (Vacant+Sold+Occupied+Churning)"),
            ("Sold Rate %", _pct_fmt(sold_rate_pct), f"(Occupied + Sold + Churning + Vacant with Opportunity Name) ÷ Total. **{vacant_approved_deal}** Vacant kitchens with Opportunity Name filled are included."),
            ("Occupancy % (Ops)", _pct_fmt(occ_pct), "(Occupied + Churning) / Total"),
            ("Vacancy %", _pct_fmt(vac_pct), "Vacant / Total"),
            ("Churn %", _pct_fmt(churn_pct), "Churning / Total"),
            ("Sold", f"{sold:,}", "Closed Won, future access"),
        ]
        _score_cols = st.columns(2 if _compact_layout_enabled() else 6)
        for _i, (_label, _val, _help) in enumerate(_score_metrics):
            with _score_cols[_i % len(_score_cols)]:
                st.metric(_label, _val, help=_help)
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
                st.caption(f"**Data quality:** {', '.join(missing_parts)} kitchen(s) have no List price (included as $0). Review in **{SECTION_KSA}** or the source sheet.")
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
            f = _dashboard_facility_from_row(r) or "(No facility)"
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
                        facility_rows = [
                            r for r in rows_kitchens
                            if (_dashboard_facility_from_row(r) or "(No facility)") == selected_facility
                        ]
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
                                    "Facility": _dashboard_facility_from_row(r) or "—",
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
                    n_cols = min(n_cards, 2 if _compact_layout_enabled() else 6)
                    cols = st.columns(n_cols)
                    for i, row in enumerate(monthly_summary[:12]):  # cap at 12 months
                        if i > 0 and i % n_cols == 0:
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
                        "Account / Facility": _dashboard_facility_from_row(r) or "—",
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
                    if _compact_layout_enabled():
                        post_clicked = st.form_submit_button("Post reply", use_container_width=True)
                        cancel_clicked = st.form_submit_button("Cancel", use_container_width=True)
                    else:
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
