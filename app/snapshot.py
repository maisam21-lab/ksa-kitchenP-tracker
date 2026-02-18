"""
Daily kitchen snapshots for "what changed today" and trend charts.
Grain: one row per kitchen per day. Uses app/data/tracker.db kitchen_daily_snapshot table.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# DB_PATH from tracker_app
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "tracker.db"


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_key(row: dict, *candidates: str) -> str:
    """First non-empty value (case-insensitive key match) from row."""
    keys_lower = {str(k).strip().lower(): k for k in (row or {}).keys()}
    for c in candidates:
        c_lower = c.strip().lower()
        if c_lower in keys_lower:
            v = row.get(keys_lower[c_lower])
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


def _kitchen_key_from_row(row: dict) -> str:
    """Stable key for a kitchen: facility + kitchen id/name."""
    facility = _row_key(row, "Account Name", "Account Name__c", "facility", "Facility", "Account__r.Name")
    kid = _row_key(row, "Kitchen Number", "Kitchen_Number_ID_18__c", "Kitchen Number Name", "Name", "kitchen_id", "Kitchen Number Name")
    if not kid:
        kid = _row_key(row, "Name", "Kitchen Number Name")
    return f"{facility or 'Unknown'}|{kid or id(row)}"


def write_daily_snapshot(rows: list[dict], snapshot_date: str | None = None) -> int:
    """
    Write a daily snapshot from Kitchens-style rows.
    snapshot_date: YYYY-MM-DD; default today.
    Returns number of rows written.
    """
    if snapshot_date is None:
        snapshot_date = date.today().isoformat()
    conn = _get_conn()
    try:
        c = conn
        c.execute("DELETE FROM kitchen_daily_snapshot WHERE snapshot_date = ?", (snapshot_date,))
        # Build one row per kitchen_key (last occurrence wins) to avoid PRIMARY KEY duplicate
        seen = {}
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                row = dict(row)
            key = _kitchen_key_from_row(row)
            if not key.strip():
                key = f"_no_key_{i}"
            facility = _row_key(row, "Account Name", "Account Name__c", "facility", "Facility", "Account__r.Name")
            kitchen_name = _row_key(row, "Kitchen Number Name", "Name", "Kitchen Number", "Kitchen_Number_ID_18__c")
            status = _row_key(row, "Status", "Status__c", "status")
            churn_date = _row_key(row, "Churn Date", "Churn_Date__c", "Opportunity__r.Churn_Date__c")
            floor_price = _row_key(row, "Floor Price", "Floor_Price__c", "floor_price")
            data_json = json.dumps(row, ensure_ascii=False)
            seen[key] = (snapshot_date, key, facility, kitchen_name, status, churn_date, floor_price, data_json)
        for key, vals in seen.items():
            c.execute(
                """INSERT OR REPLACE INTO kitchen_daily_snapshot
                   (snapshot_date, kitchen_key, facility, kitchen_name, status, churn_date, floor_price, data_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                vals,
            )
        conn.commit()
        return len(seen)
    finally:
        conn.close()


def load_snapshots(last_n_days: int = 30) -> list[dict]:
    """Load snapshot rows for the last N days. Returns list of dicts with snapshot_date, kitchen_key, facility, kitchen_name, status, etc."""
    since = (date.today() - timedelta(days=last_n_days)).isoformat()
    conn = _get_conn()
    try:
        r = conn.execute(
            """SELECT snapshot_date, kitchen_key, facility, kitchen_name, status, churn_date, floor_price
               FROM kitchen_daily_snapshot WHERE snapshot_date >= ? ORDER BY snapshot_date, kitchen_key""",
            (since,),
        )
        return [dict(row) for row in r]
    finally:
        conn.close()


def snapshot_exists_for_date(snapshot_date: str) -> bool:
    """True if we have at least one row for that date."""
    conn = _get_conn()
    try:
        r = conn.execute("SELECT 1 FROM kitchen_daily_snapshot WHERE snapshot_date = ? LIMIT 1", (snapshot_date,))
        return r.fetchone() is not None
    finally:
        conn.close()


def compute_daily_changes(today_rows: list[dict], yesterday_rows: list[dict]) -> list[dict]:
    """
    Compare today vs yesterday kitchen state. today_rows/yesterday_rows are list of dicts
    with at least keys for kitchen identity and status (e.g. from load_snapshots or Kitchens tab).
    Returns list of {facility, kitchen_name, yesterday_status, today_status}.
    """
    def key(r):
        if not isinstance(r, dict):
            return ""
        if r.get("kitchen_key"):
            return str(r["kitchen_key"])
        return _kitchen_key_from_row(r)

    def status(r):
        if not isinstance(r, dict):
            return ""
        return (r.get("status") or "").strip() or _row_key(r, "Status", "Status__c", "status")

    def facility(r):
        if not isinstance(r, dict):
            return ""
        return (r.get("facility") or "").strip() or _row_key(r, "Account Name", "facility", "Facility", "Account__r.Name")

    def kitchen_name(r):
        if not isinstance(r, dict):
            return ""
        return (r.get("kitchen_name") or "").strip() or _row_key(r, "Kitchen Number Name", "Name", "Kitchen Number")

    yesterday_by_key = {key(r): r for r in yesterday_rows if key(r)}
    out = []
    for r in today_rows:
        k = key(r)
        if not k:
            continue
        prev = yesterday_by_key.get(k)
        if prev is None:
            continue
        ys, ts = status(prev), status(r)
        if ys == ts:
            continue
        out.append({
            "facility": facility(r) or facility(prev),
            "kitchen_name": kitchen_name(r) or kitchen_name(prev),
            "yesterday_status": ys,
            "today_status": ts,
        })
    return out
