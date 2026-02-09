# BI ETL Foundation

Adds a **controlled ETL layer** between your **editable tracker** and reporting: designated users keep adding, editing, and removing entries in the tracker (e.g. Google Sheet); the ETL validates and publishes a **read-only output** for Looker Studio and dashboards.

## Why This Exists

- **Sheets are stateful** — filters/sorting/hidden rows cause partial updates and wrong metrics when reporting reads the sheet directly.
- **This project** — The **tracker stays editable** by specific users. The ETL **reads** the tracker, validates, and writes to an **output** that only reporting consumes (read-only). So: add/edit/remove in the tracker; dashboards read from the validated output.

## Quick Start

**KSA Kitchen Tracker (no install):**

```bash
cd bi-etl-foundation
python validate_ksa_csv.py
```

Reads `data/input/ksa_kitchen_tracker.csv`, validates against the schema, and writes valid rows to `data/output/ksa_kitchen_tracker.csv`. Optional: pass another CSV path as argument.

**KSA Auto Refresh Execution Log** (audit of when each sheet was refreshed):

```bash
python validate_execution_log.py "C:\Users\MaysamAbuKashabeh\Downloads\KSA Kitchen Tracker - Auto Refresh Execution Log.csv"
```

Writes validated rows to `data/output/ksa_auto_refresh_execution_log.csv`. Use any path to your execution log CSV.

**Full ETL (needs pip):**

```bash
cd bi-etl-foundation
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
set PYTHONPATH=src
python -m etl
# Or KSA only:
python run_ksa_test.py
```

Output appears under `data/output/`. Invalid rows go to `data/quarantine/` with `_error` and `_row_index`.

## Project Layout

```
bi-etl-foundation/
├── config/
│   ├── sources.yaml       # Source and output config (single source of truth)
│   └── schemas/           # JSON Schema per dataset
├── data/
│   ├── input/             # Sample or staged extract inputs
│   ├── output/            # Modeled, read-only outputs (for BI)
│   └── quarantine/        # Invalid rows (audit)
├── docs/
│   ├── ARCHITECTURE.md    # Problem, architecture, design principles
│   ├── GOAL_5_PLAN.md     # Goal 5: Revamp Kitchen Trackers
│   └── TESTING_KSA_KITCHEN_TRACKER.md
├── validate_ksa_csv.py   # KSA validate + write output (no deps)
├── run_ksa_test.py        # KSA full ETL (uses config/sources_ksa.yaml)
├── src/
│   └── etl/               # Pipeline, validation, config loader
├── requirements.txt
└── README.md
```

## Looker Studio Integration

1. **Use ETL output (not the editable sheet directly)** for production dashboards — so reporting sees a stable, validated snapshot.
2. **Load ETL outputs into a warehouse** (recommended: **BigQuery**).
   - Extend `config/sources.yaml` and `pipeline.py` to write to BigQuery (e.g. `google-cloud-bigquery`).
   - Use a dedicated dataset (e.g. `bi_modeled`) that only the ETL writes to; dashboards have read-only access.
3. **In Looker Studio**: Add data source → **BigQuery** → select the ETL dataset/tables.
4. **Refresh**: Run the ETL on a schedule (cron, Cloud Scheduler, Airflow). Looker Studio refreshes from the output; designated users keep editing the tracker.

This gives you:

- **Editable tracker** — Designated users add, edit, remove entries in the tracker (Sheet or app).
- **Read-only reporting** — Looker and dashboards read only from the ETL output (BigQuery or CSV); no filters or concurrent edits in the reporting path.
- **Standardized data** — Schema and validation in this repo; invalid rows quarantined.
- **Repeatable refreshes** — ETL reads the tracker → validates → writes output; reporting always uses that output.

## Extending the ETL

- **More sources**: Add entries in `config/sources.yaml`; implement extract in `pipeline.py` (e.g. BigQuery, HTTP).
- **Transforms**: Pass a custom `transform` function to `run_pipeline()` (aggregations, renames, lookups).
- **BigQuery load**: In `pipeline.py`, when `output.type == "bigquery"`, use the BigQuery client to create/overwrite tables in your `bi_modeled` dataset.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full design and principles.

## I don't have the Download option (Google Sheets)

- **Copy-paste:** In the sheet, select all (Ctrl+A), copy (Ctrl+C). Paste into Notepad and save as `ksa_paste.txt` in `scripts/`. Then run `python scripts/paste_to_csv.py scripts/ksa_paste.txt` — that writes `data/input/ksa_kitchen_tracker.csv`. Then run `python validate_ksa_csv.py`.
- **Google Sheets API:** Use a service account and run `python scripts/fetch_sheet_to_csv.py` to pull the sheet into `data/input/ksa_kitchen_tracker.csv`. See [scripts/sheet_to_csv_README.md](scripts/sheet_to_csv_README.md) for setup.

## Google API (Sheets API + BigQuery)

Use **Google APIs** as the source (no Airtable):

- **Google Sheets API** — ETL reads from your Google Sheet (no Download button). Designated users keep editing the Sheet; ETL pulls and validates.
- **BigQuery** — ETL reads from a BigQuery table or query; output for Looker Studio.

**Sheets API:** Set **`sheet_id`** and **`table_name_or_gid`** in **`config/sources_google_sheets_ksa.yaml`**; put the service account JSON at **`scripts/credentials.json`** (or set **`GOOGLE_APPLICATION_CREDENTIALS`**). Share the Sheet with the service account email (Viewer). Run: **`python run_google_sheets_ksa.py`** (after `pip install -r requirements.txt`).

**BigQuery:** Add a source with **`type: bigquery`**, **`project_id`**, **`dataset_id`**, **`table_id`** (or **`query`**). Run the pipeline with that config.

See **[docs/GOOGLE_API_SETUP.md](docs/GOOGLE_API_SETUP.md)** for credentials, config, and run steps.

---

## Create your own product (custom tracker app)

You can **create your own product** — a custom tracker app you own — instead of using Sheets or Airtable.

- **Starter app:** **`app/tracker_app.py`** — Streamlit + SQLite. Add, edit, and remove KSA Kitchen Tracker entries in a simple UI; data in **`app/data/tracker.db`**.
- **Run app:** `streamlit run app/tracker_app.py` (after `pip install -r requirements.txt`).
- **ETL reads from your product:** Config **`config/sources_sqlite_ksa.yaml`** (source type **`sqlite`**, path **`app/data/tracker.db`**). Run **`python run_sqlite_ksa.py`** → output **`data/output/ksa_kitchen_tracker.csv`** for Looker Studio.

See **[docs/CREATE_YOUR_OWN_PRODUCT.md](docs/CREATE_YOUR_OWN_PRODUCT.md)** for options (Streamlit + SQLite, web app + Postgres/BigQuery) and how the ETL connects.

**Sustainability and reading the tracker you already have:** See **[docs/SUSTAINABILITY_AND_READING_TRACKERS.md](docs/SUSTAINABILITY_AND_READING_TRACKERS.md)** — is this sustainable, and how to read your existing tracker (Google Sheet, Streamlit app, or execution log).

**My Google Sheet has multiple tabs (I can't use CSV):** Use the **Google Sheets API** with one source per tab. See **[docs/MULTIPLE_SHEETS_NO_CSV.md](docs/MULTIPLE_SHEETS_NO_CSV.md)** and **`config/sources_google_sheets_multi.yaml`**; run **`py run_google_sheets_multi.py`**.

**How users work on the tracker:** See **[docs/HOW_USERS_WORK_ON_THE_TRACKER.md](docs/HOW_USERS_WORK_ON_THE_TRACKER.md)** — day-to-day use (Sheet vs Streamlit app), add/edit/remove, and how the ETL and Looker Studio fit in.

**What we need from you:** See **[docs/WHAT_WE_NEED_FROM_YOU.md](docs/WHAT_WE_NEED_FROM_YOU.md)** — checklist: run the app, run the ETL, connect Looker Studio, schema/Sheet (optional).

**Try AppSheet:** See **[docs/TRY_APPSHEET.md](docs/TRY_APPSHEET.md)** — use Google AppSheet as the tracker (connect a Sheet, add view + form, share app); how the ETL reads from that Sheet (API or CSV export).

---

## Replace Google Sheets with Airtable

Use **Airtable** as the tracker (designated users add, edit, remove entries). ETL reads from Airtable and writes validated output for Looker Studio. No Sheets.

1. Create an Airtable base and table matching the KSA schema (see **[docs/AIRTABLE_SETUP.md](docs/AIRTABLE_SETUP.md)**).
2. Set **Base ID** and **table name** in **`config/sources_airtable_ksa.yaml`**; set **`AIRTABLE_API_KEY`** (env or in config).
3. Run: **`python run_airtable_ksa.py`** (after `pip install -r requirements.txt`). Output: **`data/output/ksa_kitchen_tracker.csv`**.

See **[docs/AIRTABLE_SETUP.md](docs/AIRTABLE_SETUP.md)** for full setup. Other options (AppSheet, Retool, custom DB): **[docs/REPLACE_GOOGLE_SHEETS_ENTIRELY.md](docs/REPLACE_GOOGLE_SHEETS_ENTIRELY.md)**.

---

## Continue / Next steps

1. **Use real KSA data** — Export your KSA Kitchen Tracker from Sheets as CSV, replace `data/input/ksa_kitchen_tracker.csv` (or pass its path to `validate_ksa_csv.py`). Adjust `config/schemas/ksa_kitchen_tracker.json` if column names or rules differ.
2. **More kitchen trackers** — Duplicate the KSA pattern: add a schema under `config/schemas/`, sample data under `data/input/`, and a source in `config/sources_ksa.yaml` or `sources.yaml`.
3. **Connect Looker Studio** — Load `data/output/*.csv` into BigQuery (or another warehouse), then in Looker Studio add a data source from that dataset so dashboards use read-only ETL output.
4. **Schedule runs** — Run `validate_ksa_csv.py` or `run_ksa_test.py` on a schedule (e.g. daily) so the output stays up to date.
