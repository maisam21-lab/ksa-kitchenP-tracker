"""Run ETL for KSA Kitchen Tracker from your own product (SQLite). Usage: python run_sqlite_ksa.py"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    config_path = root / "config" / "sources_sqlite_ksa.yaml"
    summary = run_pipeline(config_path=config_path)
    print("KSA Kitchen Tracker (Your Own Product / SQLite) — run summary:", summary)
