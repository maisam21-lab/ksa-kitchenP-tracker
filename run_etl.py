"""Run ETL from repo root. Usage: python run_etl.py"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    summary = run_pipeline()
    print("Run summary:", summary)
