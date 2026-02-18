#!/usr/bin/env python3
"""
Test BigQuery access to the two projects mentioned in access requests:
  - css-operations (AAC - Operations - Employee: full admin)
  - ck_emea_apac_marketing (Sales Operations only; you may need team access)

Uses Application Default Credentials (run: gcloud auth application-default login).
Or set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON key.

Run from repo root: python scripts/test_bigquery_access.py
"""

from __future__ import annotations

import sys


def main() -> None:
    try:
        from google.cloud import bigquery
    except ImportError:
        print("Install: pip install google-cloud-bigquery")
        sys.exit(1)

    client = bigquery.Client()

    projects = [
        "css-operations",
        "ck_emea_apac_marketing",
    ]

    for project_id in projects:
        print(f"\n--- {project_id} ---")
        try:
            datasets = list(client.list_datasets(project=project_id))
            if not datasets:
                print("  OK (no datasets or empty project)")
            else:
                for ds in datasets[:20]:
                    print(f"  - {ds.dataset_id}")
                if len(datasets) > 20:
                    print(f"  ... and {len(datasets) - 20} more")
                print(f"  Total: {len(datasets)} dataset(s) — access OK")
        except Exception as e:
            err = str(e).strip()
            if "403" in err or "Permission" in err or "Forbidden" in err or "Access Denied" in err:
                print("  ACCESS DENIED — you do not have access to this project.")
            else:
                print(f"  Error: {err}")

    print("\nDone. If css-operations works and ck_emea_apac_marketing is denied, request access for AAC - Operations - Business Operations - Employee.")


if __name__ == "__main__":
    main()
