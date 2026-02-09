"""Run ETL from Google Sheets API using config/sources_gsheet_try.yaml. Usage: py run_gsheet_try.py"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    config_path = root / "config" / "sources_gsheet_try.yaml"
    summary = run_pipeline(config_path=config_path)
    print("Google Sheets API — run summary:", summary)
