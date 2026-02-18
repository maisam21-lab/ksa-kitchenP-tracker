"""
Persisted dataset store for Superset refresh pipeline.
Read-only for the Streamlit app: read_dataset(name) -> DataFrame, read_metadata(name) -> dict.
Storage: Supabase (preferred) or parquet files in a persistent directory.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    pd = None

# Dataset names used by refresh job
MASTER_KITCHENS_LIVE = "master_kitchens_live"
FACILITY_KPI_SUMMARY = "facility_kpi_summary"

METADATA_KEYS = ("dataset_name", "last_refresh_ts_utc", "row_count", "status", "error_message", "uploaded_by", "uploaded_at_utc")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _storage_dir() -> Path:
    """Persistent directory for parquet + metadata when not using Supabase."""
    raw = _env("DATA_STORE_DIR")
    if raw and Path(raw).is_dir():
        return Path(raw)
    # Default relative to app/data
    app_dir = Path(__file__).resolve().parent
    d = app_dir / "data" / "superset_store"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _use_supabase() -> bool:
    return bool(_env("SUPABASE_URL") and _env("SUPABASE_KEY"))


def read_metadata(name: str) -> dict:
    """
    Read refresh metadata for a dataset.
    Returns dict with dataset_name, last_refresh_ts_utc, row_count, status, error_message, etc.
    """
    if _use_supabase():
        try:
            from supabase import create_client
            url = _env("SUPABASE_URL")
            key = _env("SUPABASE_KEY")
            client = create_client(url, key)
            table = "refresh_metadata"
            r = client.table(table).select("*").eq("dataset_name", name).limit(1).execute()
            if r.data and len(r.data) > 0:
                row = r.data[0]
                return {k: row.get(k) for k in METADATA_KEYS if k in row}
        except Exception as e:
            logger.exception("Supabase read_metadata failed: %s", e)
        return {}

    path = _storage_dir() / f"{name}.metadata.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("Read metadata failed: %s", e)
        return {}


def read_dataset(name: str):
    """
    Read persisted dataset as pandas DataFrame.
    Returns None if not found or on error. App should use last successful stored data.
    """
    if pd is None:
        return None

    if _use_supabase():
        try:
            from supabase import create_client
            url = _env("SUPABASE_URL")
            key = _env("SUPABASE_KEY")
            client = create_client(url, key)
            r = client.table("superset_dataset_rows").select("data").eq("dataset_name", name).order("row_index").execute()
            if r.data:
                rows = [row["data"] for row in r.data]
                return pd.DataFrame(rows)
            return pd.DataFrame()
        except Exception as e:
            logger.exception("Supabase read_dataset failed: %s", e)
            return None

    path = _storage_dir() / f"{name}.parquet"
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        logger.exception("Parquet read failed: %s", e)
        return None


def write_dataset_and_metadata(
    name: str,
    df: pd.DataFrame,
    status: str = "success",
    error_message: Optional[str] = None,
    uploaded_by: Optional[str] = None,
) -> bool:
    """
    Write dataset and metadata. Used by refresh job and CSV upload.
    On failure, do not overwrite dataset; only metadata can be updated separately.
    """
    if pd is None:
        return False
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row_count = len(df) if df is not None else 0

    meta = {
        "dataset_name": name,
        "last_refresh_ts_utc": ts,
        "row_count": row_count,
        "status": status,
        "error_message": error_message or "",
        "uploaded_by": uploaded_by or "",
        "uploaded_at_utc": ts if uploaded_by else "",
    }

    if _use_supabase():
        try:
            from supabase import create_client
            url = _env("SUPABASE_URL")
            key = _env("SUPABASE_KEY")
            client = create_client(url, key)
            data_table = "superset_dataset_rows"
            meta_table = "refresh_metadata"
            if status == "success" and df is not None and not df.empty:
                rows = df.to_dict("records")
                client.table(data_table).delete().eq("dataset_name", name).execute()
                batch = [{"dataset_name": name, "row_index": i, "data": r} for i, r in enumerate(rows)]
                if batch:
                    client.table(data_table).insert(batch).execute()
            client.table(meta_table).upsert(meta, on_conflict="dataset_name").execute()
            return True
        except Exception as e:
            logger.exception("Supabase write failed: %s", e)
            return False

    dir_ = _storage_dir()
    if status == "success" and df is not None:
        try:
            df.to_parquet(dir_ / f"{name}.parquet", index=False)
        except Exception as e:
            logger.exception("Parquet write failed: %s", e)
            return False
    try:
        with open(dir_ / f"{name}.metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logger.exception("Metadata write failed: %s", e)
        return False
    return True


def write_metadata_only(name: str, status: str, error_message: Optional[str] = None) -> bool:
    """Update only metadata (e.g. on refresh failure without overwriting last good data)."""
    meta = read_metadata(name)
    meta["dataset_name"] = name
    meta["last_refresh_ts_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["status"] = status
    meta["error_message"] = error_message or ""
    if _use_supabase():
        try:
            from supabase import create_client
            client = create_client(_env("SUPABASE_URL"), _env("SUPABASE_KEY"))
            client.table("refresh_metadata").upsert(meta, on_conflict="dataset_name").execute()
            return True
        except Exception as e:
            logger.exception("Supabase metadata update failed: %s", e)
            return False
    try:
        with open(_storage_dir() / f"{name}.metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return True
    except Exception as e:
        logger.exception("Metadata write failed: %s", e)
        return False
