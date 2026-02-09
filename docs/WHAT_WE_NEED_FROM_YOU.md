# What we need from you

A short checklist of what you need to do on your end so the web-based tracker and ETL work end to end.

---

## 1. Run the tracker app (so users can use it)

**You do:** Start the app so people can open it in the browser.

- **Local:** From the repo folder run `py -m streamlit run app/tracker_app.py` (or double-click `install_and_run.bat`), then open **http://localhost:8501**. Share your screen or use only on your machine.
- **For everyone:** Deploy the app (e.g. [Streamlit Community Cloud](https://streamlit.io/cloud), or a server you control) and share the URL with your team. Then everyone can filter and add data from their browser.

**We need:** Nothing else for this step — the app and DB are in this repo.

---

## 2. Who can use the app

**You do:** Decide who should have access.

- If the app runs **only on your PC** (localhost), only you (or whoever is at that PC) can use it.
- If you **deploy** it (e.g. Streamlit Cloud), anyone with the URL can open it unless you add login. So: either share the URL only with the right people, or plan to add authentication later.

**We need:** Your choice: local-only vs deployed URL; and whether you want to restrict by URL only or add login later.

---

## 3. Run the ETL (so Looker Studio has data)

**You do:** Run the ETL so it reads the tracker DB and writes the output file (e.g. CSV).

- **Once:** `cd bi-etl-foundation` then `py run_sqlite_ksa.py`. That creates/updates **`data/output/ksa_kitchen_tracker.csv`**.
- **On a schedule:** Set up Windows Task Scheduler (or a server cron) to run `py run_sqlite_ksa.py` on a schedule (e.g. daily). Use the full path to `python`/`py` and the repo folder.

**We need:** Confirmation that you can run `py run_sqlite_ksa.py` from the repo folder; if you want scheduling, we only need to know the schedule (e.g. daily at 6 AM).

---

## 4. Connect Looker Studio to the output

**You do:** In Looker Studio, use the ETL output as the data source (not the tracker app directly).

- **Option A — File:** If Looker Studio allows file upload, upload **`data/output/ksa_kitchen_tracker.csv`** (after each ETL run or from a shared drive where you copy it).
- **Option B — BigQuery (recommended):** Load **`data/output/ksa_kitchen_tracker.csv`** into a BigQuery table (e.g. in a dataset like `bi_modeled`). In Looker Studio, add data source → BigQuery → select that table. Then refresh in Looker Studio when new data is loaded.

**We need:** Your choice: file upload vs BigQuery. If BigQuery: project id, dataset name, and whether you will load the CSV manually or want a script/step to load it.

---

## 5. Schema / columns (if different from current)

**You do:** If your real KSA Kitchen Tracker has **different column names or extra columns** than the app (record_id, report_date, site_id, site_name, region, metric_name, value, status, notes), tell us the exact list (or share a sample row). We’ll align the app and ETL schema.

**We need:** Either “the current schema is fine” or the list of column names (and ideally one sample row) so we can update **`config/schemas/ksa_kitchen_tracker.json`** and the app if needed.

---

## 6. Optional: reading from an existing Google Sheet (multi-sheet)

If you also want the ETL to read from an **existing Google Sheet** (with multiple tabs) instead of or in addition to the web app:

**You do:** Get a **service account JSON key** for the Google Sheets API (from your GCP project or from your admin). Put it at **`scripts/credentials.json`** (or set **`GOOGLE_APPLICATION_CREDENTIALS`**). Share the Sheet with the service account email (Viewer).

**We need:** Either “we’re only using the web app, no Sheet” or the service account JSON (or confirmation it’s in place) and the Sheet ID + tab names/gids for **`config/sources_google_sheets_multi.yaml`**.

---

## Summary checklist

| # | What we need from you | Your action |
|---|------------------------|-------------|
| 1 | Tracker app running | Run `py -m streamlit run app/tracker_app.py` (or deploy and share URL). |
| 2 | Who can use the app | Decide: local only vs deployed URL; share URL only with the right people or plan login. |
| 3 | ETL run | Run `py run_sqlite_ksa.py` (once or on a schedule). |
| 4 | Looker Studio connected | Use ETL output (file or BigQuery) as data source in Looker Studio. |
| 5 | Schema match | Confirm current columns are fine or send the exact column list (and sample row if different). |
| 6 | (Optional) Google Sheet | If you want to read a Sheet: service account JSON + Sheet ID + tab names/gids. |

Once 1–4 are done, users can work in the web-based tracker (filter + add data without affecting existing records), and Looker Studio can read from the ETL output. If anything in 5 or 6 applies, we’ll adjust the schema or config accordingly.
