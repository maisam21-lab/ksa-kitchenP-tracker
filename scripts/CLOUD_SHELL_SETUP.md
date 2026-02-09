# Run Google Sheets pull from Cloud Shell (css-operations)

Your project is **css-operations**. Run these steps in Cloud Shell. The script will write the CSV to your home directory; you can download it from Cloud Shell.

---

## Step 1: Enable Google Sheets API

In Cloud Shell, run:

```bash
gcloud services enable sheets.googleapis.com --project=css-operations
```

---

## Step 2: Create a service account and key

**2a. Check your project ID** (use this in the next commands if different from `css-operations`):

```bash
gcloud config get-value project
```

**2b. Create the service account** (run this first; if it fails, you may need IAM permission or to use an existing SA):

```bash
gcloud iam service-accounts create bi-etl-sheets \
  --display-name="BI ETL Sheets" \
  --project=css-operations
```

If you see "Permission denied" or "Resource already exists", run:

```bash
gcloud iam service-accounts list --project=css-operations
```

Use one of the listed emails for the key step, or ask your admin to create the service account.

**2c. Create the JSON key** (use the **exact** project ID from step 2a if different):

```bash
gcloud iam service-accounts keys create ~/credentials.json \
  --iam-account=bi-etl-sheets@css-operations.iam.gserviceaccount.com \
  --project=css-operations
```

---

## Step 3: Share your Google Sheet with the service account

1. Get the service account email:
   ```bash
   echo "Share your Google Sheet with this email (Viewer):"
   gcloud iam service-accounts list --project=css-operations --filter="displayName:BI ETL Sheets" --format="value(email)"
   ```
   Or use: **bi-etl-sheets@css-operations.iam.gserviceaccount.com**

2. Open your KSA Kitchen Tracker in Google Sheets → **Share** → paste that email → set **Viewer** → Share.

---

## Step 4: Create and run the fetch script in Cloud Shell

1. Create the script (copy-paste the whole block into Cloud Shell):

```bash
cat > ~/fetch_sheet_to_csv.py << 'ENDOFSCRIPT'
import csv
import os
from pathlib import Path

SHEET_ID = "1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8"
GID = "1341293927"
CREDENTIALS_JSON = os.path.expanduser("~/credentials.json")
OUTPUT_CSV = os.path.expanduser("~/ksa_kitchen_tracker.csv")

def main():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(CREDENTIALS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)

    sheet = None
    for ws in spreadsheet.worksheets():
        if str(ws.id) == str(GID):
            sheet = ws
            break
    if sheet is None:
        sheet = spreadsheet.sheet1

    rows = sheet.get_all_values()
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    print(f"Fetched {len(rows)} rows to {OUTPUT_CSV}")
    print("Download: Cloud Shell menu (three dots) -> Download file -> ksa_kitchen_tracker.csv")

if __name__ == "__main__":
    main()
ENDOFSCRIPT
```

2. Install Python packages (one time):

```bash
pip install --user gspread google-auth
```

3. Run the script:

```bash
python3 ~/fetch_sheet_to_csv.py
```

---

## Step 5: Download the CSV to your PC

- In Cloud Shell, click the **three-dot menu** (top right) → **Download file**.
- Enter: **ksa_kitchen_tracker.csv** (it’s in your home directory).
- Save it on your PC, e.g. as **`bi-etl-foundation\data\input\ksa_kitchen_tracker.csv`**, then run locally:
  ```bash
  cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
  python validate_ksa_csv.py
  ```

---

## Change sheet or tab

Edit the script and set your own IDs:

```bash
nano ~/fetch_sheet_to_csv.py
```

- **SHEET_ID:** from the sheet URL: `https://docs.google.com/spreadsheets/d/SHEET_ID/edit`
- **GID:** from the tab URL: `...edit#gid=GID`

Save (Ctrl+O, Enter, Ctrl+X), then run again:

```bash
python3 ~/fetch_sheet_to_csv.py
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| **Permission denied / 403** | Share the Google Sheet with **bi-etl-sheets@css-operations.iam.gserviceaccount.com** (Viewer). |
| **credentials.json not found** | Run Step 2 again; then `ls -la ~/credentials.json`. |
| **ModuleNotFoundError: gspread** | Run `pip install --user gspread google-auth`. |
| **Wrong tab** | Change **GID** in `~/fetch_sheet_to_csv.py` to the tab id from the sheet URL when that tab is open. |
