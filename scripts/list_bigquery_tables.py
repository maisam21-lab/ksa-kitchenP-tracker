#!/usr/bin/env python3
"""
Discover BigQuery datasets and tables so you can find the right FROM clause.
Uses your default credentials (gcloud auth application-default login)
or GOOGLE_APPLICATION_CREDENTIALS.

Usage:
  python scripts/list_bigquery_tables.py
  python scripts/list_bigquery_tables.py --project css-operations
  python scripts/list_bigquery_tables.py --project css-operations --dataset sales
  python scripts/list_bigquery_tables.py --search opportunity
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    try:
        from google.cloud import bigquery
    except ImportError:
        print("Install: pip install google-cloud-bigquery")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="List BigQuery datasets and tables")
    parser.add_argument("--project", "-p", help="Project ID (default: try css-operations, ck_emea_apac_marketing)")
    parser.add_argument("--dataset", "-d", help="If set, only list tables in this dataset")
    parser.add_argument("--search", "-s", help="Only show tables whose name contains this string (case-insensitive)")
    args = parser.parse_args()

    client = bigquery.Client()

    projects = [args.project] if args.project else ["css-operations", "ck_emea_apac_marketing"]
    if not args.project:
        # Default project from ADC might be different; list it first
        try:
            default_project = client.project
            if default_project and default_project not in projects:
                projects = [default_project] + projects
        except Exception:
            pass

    for project_id in projects:
        if not project_id:
            continue
        print(f"\n=== Project: {project_id} ===")
        try:
            datasets = list(client.list_datasets(project=project_id))
        except Exception as e:
            err = str(e).strip()
            if "403" in err or "Permission" in err or "Forbidden" in err:
                print("  (No access to this project)\n")
                continue
            print(f"  Error: {err}\n")
            continue

        if not datasets:
            print("  No datasets\n")
            continue

        # If --dataset given, only that dataset
        if args.dataset:
            datasets = [d for d in datasets if d.dataset_id == args.dataset]
            if not datasets:
                print(f"  Dataset '{args.dataset}' not found\n")
                continue

        for ds in datasets:
            full_id = f"{project_id}.{ds.dataset_id}"
            print(f"\n  Dataset: {full_id}")
            try:
                tables = list(client.list_tables(full_id))
            except Exception as e:
                print(f"    Error listing tables: {e}")
                continue
            for t in tables:
                name = t.table_id
                if args.search and args.search.lower() not in name.lower():
                    continue
                print(f"    - {name}   -> FROM `{project_id}.{ds.dataset_id}.{name}`")

    print("\nDone. Use the FROM `project.dataset.table` lines in your queries.\n")


if __name__ == "__main__":
    main()
