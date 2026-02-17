"""
Salesforce data abstraction layer.
Provider selection: SFDC_PROVIDER=mock|sandbox|prod (env or Streamlit secrets).
Mock provider reads from app/data/mock/ (JSON or CSV per tab).
"""
import csv
import io
import json
import os
from pathlib import Path

# Used by tracker_app; path resolved at runtime
def _mock_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "mock"


def get_sfdc_provider() -> str:
    """Return 'mock', 'sandbox', or 'prod' from SFDC_PROVIDER (env or secrets). Default prod."""
    val = os.environ.get("SFDC_PROVIDER")
    if not val:
        try:
            import streamlit as st
            secrets = getattr(st, "secrets", None) or {}
            val = secrets.get("SFDC_PROVIDER")
        except Exception:
            pass
    if val:
        v = str(val).strip().lower()
        if v in ("mock", "sandbox", "prod"):
            return v
    return "prod"


def _tab_to_slug(tab_id: str) -> str:
    """Tab name -> safe file name (e.g. 'SF Churn Data' -> 'SF_Churn_Data')."""
    return (tab_id or "").strip().replace(" ", "_")


def mock_fetch_tab_data(tab_id: str, _soql_or_report_id: str) -> list[dict]:
    """
    Read mock data for a tab from data/mock/{slug}.json or {slug}.csv.
    Returns list of row dicts. Missing file -> empty list.
    """
    slug = _tab_to_slug(tab_id)
    if not slug:
        return []
    base = _mock_data_dir()
    # Prefer JSON, then CSV
    for ext, loader in ((".json", _load_json), (".csv", _load_csv)):
        path = base / f"{slug}{ext}"
        if path.exists():
            try:
                return loader(path)
            except Exception:
                return []
    return []


def _load_json(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [dict(r) if isinstance(r, dict) else {} for r in data]
    if isinstance(data, dict):
        return [data]
    return []


def _load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]
