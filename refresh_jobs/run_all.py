"""
Scheduled refresh every 15 minutes: fetch Superset chart data and persist.
Run: python refresh_jobs/run_all.py (or from repo root: python -m refresh_jobs.run_all)
Uses SUPERSET_URL, SUPERSET_USERNAME, SUPERSET_PASSWORD (or SUPERSET_ACCESS_TOKEN).
Chart IDs: SUPERSET_CHART_ID_MASTER_KITCHENS, SUPERSET_CHART_ID_FACILITY_KPI (optional).
Storage: Supabase (SUPABASE_URL, SUPABASE_KEY) or parquet in DATA_STORE_DIR.
"""
import logging
import os
import sys
from pathlib import Path

# Repo root on path so "from app.xxx" works
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

try:
    from app.superset_client import SupersetClient
    from app.data_store import (
        MASTER_KITCHENS_LIVE,
        FACILITY_KPI_SUMMARY,
        write_dataset_and_metadata,
        write_metadata_only,
    )
    import pandas as pd
except ImportError as e:
    logger.error("Import failed: %s", e)
    sys.exit(1)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _chart_id_master_kitchens() -> int:
    raw = _env("SUPERSET_CHART_ID_MASTER_KITCHENS") or _env("SUPERSET_CHART_ID_MASTER_KITCHENS_LIVE")
    if not raw:
        return 0
    try:
        return int(raw.strip())
    except ValueError:
        return 0


def _chart_id_facility_kpi() -> int:
    raw = _env("SUPERSET_CHART_ID_FACILITY_KPI") or _env("SUPERSET_CHART_ID_FACILITY_KPI_SUMMARY")
    if not raw:
        return 0
    try:
        return int(raw.strip())
    except ValueError:
        return 0


def _saved_query_id_master_kitchens() -> int:
    raw = _env("SUPERSET_SAVED_QUERY_ID_MASTER_KITCHENS")
    if not raw:
        return 0
    try:
        return int(raw.strip())
    except ValueError:
        return 0


def _fetch_and_persist(client: SupersetClient, chart_id: int, dataset_name: str, saved_query_id: int = 0) -> bool:
    if chart_id <= 0 and saved_query_id <= 0:
        logger.info("Skipping %s: chart_id and saved_query_id not set", dataset_name)
        return True
    df = None
    if chart_id > 0:
        df = client.fetch_chart_data(chart_id)
    if df is None and saved_query_id > 0:
        logger.info("Chart API failed or not set; trying SQL Lab saved query %s", saved_query_id)
        df = client.fetch_saved_query_results(saved_query_id)
    if df is None:
        write_metadata_only(dataset_name, "fail", "fetch_chart_data and saved_query fallback returned None")
        logger.error("Fetch failed for %s (chart_id=%s, query_id=%s)", dataset_name, chart_id, saved_query_id)
        return False
    if not write_dataset_and_metadata(dataset_name, df, status="success"):
        logger.error("Persist failed for %s", dataset_name)
        return False
    logger.info("Persisted %s: %s rows", dataset_name, len(df))
    return True


def main() -> int:
    base_url = _env("SUPERSET_URL") or _env("SUPSERSET_URL")
    if not base_url:
        logger.error("Set SUPERSET_URL (or SUPSERSET_URL)")
        return 1

    client = SupersetClient()
    if not client.login():
        logger.error("Superset login failed")
        return 1

    ok = True
    c1 = _chart_id_master_kitchens()
    q1 = _saved_query_id_master_kitchens()
    if c1 or q1:
        if not _fetch_and_persist(client, c1, MASTER_KITCHENS_LIVE, saved_query_id=q1):
            ok = False
    else:
        logger.warning("SUPERSET_CHART_ID_MASTER_KITCHENS and SUPERSET_SAVED_QUERY_ID_MASTER_KITCHENS not set; skipping Master Kitchens (Live)")

    c2 = _chart_id_facility_kpi()
    if c2:
        if not _fetch_and_persist(client, c2, FACILITY_KPI_SUMMARY):
            ok = False
    else:
        logger.info("SUPERSET_CHART_ID_FACILITY_KPI not set; skipping Facility KPI Summary")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
