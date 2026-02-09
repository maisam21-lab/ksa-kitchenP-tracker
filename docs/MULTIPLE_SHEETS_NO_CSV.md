# My Google Sheet has multiple sheets — I can't use CSV

When your workbook has **multiple tabs**, exporting to CSV only gives you **one tab** per file. So CSV is a bad fit.

**Use the Google Sheets API instead:** the ETL can read **each tab by name or by gid** and write one output file per tab. No CSV export needed.

---

## 1. One config, multiple tabs

Use **`config/sources_google_sheets_multi.yaml`**. Each **source** = one tab in the same workbook:

- **Same `sheet_id`** for all (your workbook).
- **Different `table_name_or_gid`** per source = the tab name (e.g. `"KSA Kitchen Tracker"`) or the tab **gid** (e.g. `"1341293927"` from the URL when that tab is open).
- **`schema_ref`** — use `ksa_kitchen_tracker` for the KSA tab (validated); use **`raw_sheet`** for other tabs (any columns, first row = headers).

Example (two tabs):

```yaml
sources:
  - id: ksa_kitchen_tracker
    type: google_sheets
    sheet_id: "YOUR_SHEET_ID"
    table_name_or_gid: "KSA Kitchen Tracker"   # or gid "1341293927"
    schema_ref: ksa_kitchen_tracker
    credentials_path: scripts/credentials.json

  - id: price_multipliers
    type: google_sheets
    sheet_id: "YOUR_SHEET_ID"
    table_name_or_gid: "Price Multipliers"
    schema_ref: raw_sheet
    credentials_path: scripts/credentials.json
```

Output: **`data/output/ksa_kitchen_tracker.csv`** and **`data/output/price_multipliers.csv`**.

---

## 2. Get tab name or gid

- **Tab name:** The label on the tab at the bottom of the Sheet (e.g. "KSA Kitchen Tracker", "Price Multipliers"). Use that exact string in `table_name_or_gid`.
- **Tab gid:** Open the tab, look at the URL: `...edit#gid=1341293927`. The number after `gid=` is the gid (e.g. `"1341293927"`). Use that in `table_name_or_gid` if you prefer.

---

## 3. Credentials (once per workbook)

Share the **whole workbook** with the **service account email** (Viewer). One share covers all tabs. Put the service account JSON at **`scripts/credentials.json`** or set **`GOOGLE_APPLICATION_CREDENTIALS`**.

---

## 4. Run

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
py run_google_sheets_multi.py
```

Or run the main ETL with that config:

```bash
py -c "import sys; sys.path.insert(0,'src'); from etl.pipeline import run_pipeline; run_pipeline('config/sources_google_sheets_multi.yaml')"
```

Each tab in `sources` becomes one file in **`data/output/<source_id>.csv`**.

---

## 5. Add more tabs

Copy a source block in **`config/sources_google_sheets_multi.yaml`**, set **`id`** (e.g. `sf_churn_data`), **`table_name_or_gid`** (tab name or gid), and **`schema_ref`** (`raw_sheet` if you don't have a specific schema). Run again.

---

**Summary:** Don't use CSV when you have multiple sheets. Use **Google Sheets API** with **`sources_google_sheets_multi.yaml`** — one source per tab, one output file per tab.
