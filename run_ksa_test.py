"""Run ETL for KSA Kitchen Tracker only. Usage: python run_ksa_test.py"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from etl.pipeline import run_pipeline

if __name__ == "__main__":
    config_path = root / "config" / "sources_ksa.yaml"
    summary = run_pipeline(config_path=config_path)
    print("KSA Kitchen Tracker — run summary:")
    print(f"  Valid rows:   {summary['valid']}")
    print(f"  Invalid rows: {summary['invalid']} (see data/quarantine/ if any)")
    print(f"  Loaded:      {summary['loaded']}")
    for s in summary.get("sources", []):
        print(f"  Source '{s['id']}': extracted={s['extracted']}, valid={s['valid']}, invalid={s['invalid']}")
    out_dir = root / "data" / "output"
    out_file = out_dir / "ksa_kitchen_tracker.csv"
    if out_file.exists():
        print(f"\nOutput: {out_file}")
    print("\nDone. Use data/output/ksa_kitchen_tracker.csv for Looker Studio or read-only sheets.")
