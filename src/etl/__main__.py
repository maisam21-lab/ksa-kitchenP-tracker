"""Run ETL from command line: python -m etl"""
import json
import sys
from pathlib import Path

# Allow running as python -m etl from repo root when src is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    summary = run_pipeline()
    print(json.dumps(summary, indent=2))
