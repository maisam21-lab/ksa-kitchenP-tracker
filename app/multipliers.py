"""
Facility price multipliers for super-user Price Multipliers tool.
CRUD against app/data/tracker.db facility_multipliers table.
"""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "tracker.db"

MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 3.0


def _get_conn():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_multipliers() -> list[dict]:
    """Return list of {facility_id, facility_name, current_multiplier, suggested_multiplier, updated_by, updated_at}."""
    conn = _get_conn()
    try:
        r = conn.execute(
            """SELECT facility_id, facility_name, current_multiplier, suggested_multiplier, updated_by, updated_at
               FROM facility_multipliers ORDER BY facility_id"""
        )
        return [dict(row) for row in r]
    finally:
        conn.close()


def upsert_multiplier(
    facility_id: str,
    facility_name: str | None = None,
    current_multiplier: float | None = None,
    suggested_multiplier: float | None = None,
    updated_by: str | None = None,
) -> bool:
    """Insert or update one row. suggested_multiplier must be between MIN and MAX. Returns True on success."""
    from datetime import datetime, timezone
    fid = (facility_id or "").strip()
    if not fid:
        return False
    if suggested_multiplier is not None:
        try:
            v = float(suggested_multiplier)
            if v < MIN_MULTIPLIER or v > MAX_MULTIPLIER:
                return False
        except (TypeError, ValueError):
            return False
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO facility_multipliers (facility_id, facility_name, current_multiplier, suggested_multiplier, updated_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(facility_id) DO UPDATE SET
                 facility_name = COALESCE(excluded.facility_name, facility_name),
                 current_multiplier = COALESCE(excluded.current_multiplier, current_multiplier),
                 suggested_multiplier = COALESCE(excluded.suggested_multiplier, suggested_multiplier),
                 updated_by = excluded.updated_by,
                 updated_at = excluded.updated_at""",
            (fid, (facility_name or "").strip() or None, current_multiplier, suggested_multiplier, (updated_by or "").strip() or None, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()
