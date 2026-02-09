"""
Quick check: can we read the KSA Kitchen Tracker Google Sheet?
Run from repo root: python scripts/check_ksa_sheet_read.py
Requires: service account JSON at scripts/credentials.json (or set GOOGLE_APPLICATION_CREDENTIALS).
Share the sheet with the service account email (Viewer).
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"


def main():
    # Resolve credentials
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path and Path(creds_path).exists():
        pass
    else:
        for rel in ["scripts/credentials.json", ".secrets/gsheet-service.json"]:
            p = REPO_ROOT / rel
            if p.exists():
                creds_path = str(p)
                break
    if not creds_path or not Path(creds_path).exists():
        print("ERROR: No credentials. Put service account JSON at scripts/credentials.json or set GOOGLE_APPLICATION_CREDENTIALS.")
        sys.exit(1)

    sys.path.insert(0, str(REPO_ROOT))
    from src.etl.extract_google_sheets import extract_google_sheets

    print("KSA Kitchen Tracker — read check")
    print("Sheet ID:", SHEET_ID)
    print("Credentials:", creds_path)
    print()

    # List: try first tab by gid (1341293927) or by name "Kitchen Tracker"
    for tab_ref in ["1341293927", "Kitchen Tracker", "Auto Refresh Execution Log"]:
        try:
            rows = extract_google_sheets(SHEET_ID, tab_ref, credentials_path=creds_path)
            headers = list(rows[0].keys()) if rows else []
            preview = headers[:8] if len(headers) <= 8 else headers[:8] + ["..."]
            print(f"  Tab '{tab_ref}': {len(rows)} rows, columns: {preview}")
        except Exception as e:
            print(f"  Tab '{tab_ref}': FAILED — {e}")

    # Read one tab fully for a quick sample
    print()
    try:
        rows = extract_google_sheets(SHEET_ID, "1341293927", credentials_path=creds_path)
        print("OK — We can read the KSA tracker.")
        print(f"  Sample tab (gid 1341293927): {len(rows)} rows.")
        if rows:
            print("  First row keys:", list(rows[0].keys()))
        else:
            print("  (Tab is empty.)")
    except Exception as e:
        print("FAILED:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
