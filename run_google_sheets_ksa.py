"""Run ETL for KSA Kitchen Tracker from Google Sheets API. Usage: python run_google_sheets_ksa.py"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    config_path = root / "config" / "sources_google_sheets_ksa.yaml"
    summary = run_pipeline(config_path=config_path)
    print("KSA Kitchen Tracker (Google Sheets API) — run summary:", summary)
