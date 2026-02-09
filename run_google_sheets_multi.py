"""Run ETL for multiple sheets (tabs) from the same Google Sheet. Usage: py run_google_sheets_multi.py"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    config_path = root / "config" / "sources_google_sheets_multi.yaml"
    summary = run_pipeline(config_path=config_path)
    print("Google Sheet (multiple tabs) — run summary:", summary)
