# Try the Google Sheets API

Steps to run the ETL using the **Google Sheets API** (read from a Google Sheet, no CSV export).

---

## 1. Credentials

You need a **service account JSON** key for the Google Sheets API.

- **If you already have one** (e.g. `gsheet-service.json` from another project): copy it into this repo as **`.secrets/gsheet-service.json`**.
  - Create the folder if needed: `bi-etl-foundation\.secrets\`
  - Put the file there. (`.secrets/` is in `.gitignore` so it won’t be committed.)
- **If you don’t:** follow [docs/GOOGLE_API_SETUP.md](GOOGLE_API_SETUP.md) to create a service account and download the JSON, then save it as **`.secrets/gsheet-service.json`**.

---

## 2. Share the Sheet

Open your Google Sheet and **Share** it with the **service account email** (from the JSON: `"client_email": "xxx@xxx.iam.gserviceaccount.com"`). Give it **Viewer** (read-only) so the ETL can read the sheet.

---

## 3. Config

Open **`config/sources_gsheet_try.yaml`** and set:

- **`sheet_id`** — From the Sheet URL: `https://docs.google.com/spreadsheets/d/SHEET_ID/edit` → use `SHEET_ID`.
  - A pre-filled example is `15yjrjG0w_caal_ONp7MJeRkNDDNen76YSvgrxKPLds`; change it to your sheet if different.
- **`table_name_or_gid`** — Either:
  - The **tab name** (e.g. `"KSA Kitchen Tracker"`), or
  - The **tab gid** (open the tab, copy from URL: `#gid=1234567890` → use `"1234567890"`). First sheet is often `"0"`.
- **`credentials_path`** — Must point to your JSON key. Default is **`.secrets/gsheet-service.json`**. You can use **`scripts/credentials.json`** instead if you put the key there.

---

## 4. Run

From the repo root:

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
py run_gsheet_try.py
```

Or with the main ETL script but using this config:

```bash
py -c "import sys; sys.path.insert(0,'src'); from etl.pipeline import run_pipeline; run_pipeline('config/sources_gsheet_try.yaml')"
```

Output is written to **`data/output/ksa_kitchen_tracker.csv`**. Invalid rows (if any) go to **`data/quarantine/ksa_kitchen_tracker_invalid.csv`**.

---

## 5. Multiple tabs

To read **multiple sheets** from the same workbook, use **`config/sources_google_sheets_multi.yaml`** (one source per tab) and run **`py run_google_sheets_multi.py`**. See [docs/MULTIPLE_SHEETS_NO_CSV.md](MULTIPLE_SHEETS_NO_CSV.md).

---

## Summary

| Step | What you do |
|------|-------------|
| 1 | Put service account JSON at **`.secrets/gsheet-service.json`** (or set `credentials_path` in config to another path). |
| 2 | Share the Google Sheet with the service account email (Viewer). |
| 3 | Set **`sheet_id`** and **`table_name_or_gid`** in **`config/sources_gsheet_try.yaml`**. |
| 4 | Run **`py run_gsheet_try.py`**. |
| 5 | Use **`data/output/ksa_kitchen_tracker.csv`** for Looker Studio or further ETL. |

That’s the flow for trying the Google Sheets API with this project.
