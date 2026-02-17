"""
FX rates and conversion for Currency Converter and optional Master Kitchens display currency.
Rates stored in app/data/tracker.db fx_rates table.
"""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "tracker.db"


def _get_conn():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_rates() -> list[dict]:
    """Return list of {from_currency, to_currency, rate, updated_at}."""
    conn = _get_conn()
    try:
        r = conn.execute(
            "SELECT from_currency, to_currency, rate, updated_at FROM fx_rates ORDER BY from_currency, to_currency"
        )
        return [dict(row) for row in r]
    finally:
        conn.close()


def get_rate(from_currency: str, to_currency: str) -> float | None:
    """Return rate from_currency -> to_currency, or None if not found."""
    if (from_currency or "").strip().upper() == (to_currency or "").strip().upper():
        return 1.0
    conn = _get_conn()
    try:
        r = conn.execute(
            "SELECT rate FROM fx_rates WHERE from_currency = ? AND to_currency = ?",
            (from_currency.strip().upper(), to_currency.strip().upper()),
        )
        row = r.fetchone()
        return float(row["rate"]) if row else None
    finally:
        conn.close()


def convert(amount: float, from_currency: str, to_currency: str) -> float | None:
    """Convert amount from from_currency to to_currency. Returns None if rate missing."""
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return None
    rate = get_rate(from_currency, to_currency)
    if rate is None:
        return None
    return round(amt * rate, 2)


def ensure_default_rates() -> None:
    """Insert default SAR/USD and USD/SAR if fx_rates table is empty."""
    conn = _get_conn()
    try:
        r = conn.execute("SELECT 1 FROM fx_rates LIMIT 1")
        if r.fetchone() is not None:
            return
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Default: 1 USD = 3.75 SAR (approximate)
        conn.execute(
            "INSERT OR IGNORE INTO fx_rates (from_currency, to_currency, rate, updated_at) VALUES (?, ?, ?, ?)",
            ("USD", "SAR", 3.75, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fx_rates (from_currency, to_currency, rate, updated_at) VALUES (?, ?, ?, ?)",
            ("SAR", "USD", 1.0 / 3.75, now),
        )
        conn.commit()
    finally:
        conn.close()
