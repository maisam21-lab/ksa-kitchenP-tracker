"""Run ETL for KSA Kitchen Tracker from Airtable. Usage: python run_airtable_ksa.py"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    config_path = root / "config" / "sources_airtable_ksa.yaml"
    summary = run_pipeline(config_path=config_path)
    print("KSA Kitchen Tracker (Airtable) — run summary:", summary)
