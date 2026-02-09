# Create Your Own Product (Custom Tracker App)

You can **create your own product** — a custom tracker app that you own and host — instead of using Google Sheets or Airtable. Designated users add, edit, and remove entries in your app; the ETL in this project reads from your app’s database and feeds Looker Studio.

---

## What “Your Own Product” Means Here

| Piece | What you build |
|-------|-----------------|
| **Tracker app** | A web app (or internal tool) where users add, edit, and remove records. You own the code and data. |
| **Database** | Data lives in your DB (e.g. SQLite, Postgres, BigQuery). Schema matches your ETL (e.g. KSA Kitchen Tracker). |
| **ETL (this repo)** | Reads from your DB (or an export/API you provide). Same validate → transform → load; output for Looker Studio. |

So: **your product = your app + your database**; the ETL is the bridge from your product to reporting.

---

## Options to Build Your Product

### 1. Minimal starter in this repo (Streamlit + SQLite)

- **What:** A simple UI (Streamlit) and a local DB (SQLite) for KSA Kitchen Tracker–style records. No external services.
- **Where:** `app/` in this repo (see below). Run with `streamlit run app/tracker_app.py`.
- **ETL:** This project can read from the SQLite file (source type `sqlite`) or from a CSV export your app generates.
- **Pros:** Fast to run, full control, no vendor. **Cons:** You host and scale it (e.g. move to Postgres + proper hosting when needed).

### 2. Web app + Postgres (or BigQuery)

- **What:** A proper web app (e.g. Flask/FastAPI + React/Vue, or Streamlit) with Postgres or BigQuery as the database.
- **Users:** Add, edit, remove via the app; you control roles and permissions.
- **ETL:** This project already supports **BigQuery** as a source. For Postgres, add a source type `postgres` (or export to CSV/BigQuery from the app and ETL reads that).
- **Pros:** Scales, multi-user, professional. **Cons:** More build and ops.

### 3. Internal tool (e.g. Retool / low-code) on your DB

- **What:** Build the UI in Retool (or similar) on top of your Postgres/BigQuery. You still “create your own product” in the sense that the data and schema are yours; the UI is low-code.
- **ETL:** Same as above — ETL reads from your DB (BigQuery or Postgres).

---

## Starter: Minimal Tracker App (Streamlit + SQLite)

This repo includes a **minimal tracker app** in **`app/`** so you can “create your own product” and run it locally:

- **Tech:** Streamlit + SQLite.
- **Schema:** Matches KSA Kitchen Tracker (record_id, report_date, site_id, region, metric_name, value, status, notes).
- **Run:** From repo root: `pip install -r requirements.txt` then `streamlit run app/tracker_app.py`. Open the URL in the browser; add, edit, and delete rows. Data is stored in **`app/data/tracker.db`**.
- **ETL:** Use source type **`sqlite`** with path to the app’s SQLite file (**`app/data/tracker.db`**. Config: **`config/sources_sqlite_ksa.yaml`**. Run: **`python run_sqlite_ksa.py`**. Output: **`data/output/ksa_kitchen_tracker.csv`** for Looker Studio.

You own the app and the data; the ETL in this project reads from it and produces the output for Looker Studio.

---

## How the ETL Connects to Your Product

| Your product stores data in… | ETL source type | Config |
|------------------------------|------------------|--------|
| **SQLite file** (e.g. from Streamlit app) | `sqlite` | `db_path`, optional `query` or table name |
| **BigQuery** (your app writes to BQ) | `bigquery` | `project_id`, `dataset_id`, `table_id` or `query` |
| **Postgres** (your app writes to Postgres) | `postgres` (if added) or export to CSV/BigQuery | Same as in REPLACE_GOOGLE_SHEETS_ENTIRELY.md |
| **CSV/API export** (your app generates a file or API) | `file` or `http` | Path or URL in config |

Once the ETL reads from your product’s DB or export, the rest (validate → transform → load → Looker Studio) is unchanged.

---

## Summary

- **Yes, you can create your own product:** build a custom tracker app (Streamlit, Flask, or any stack) with your own database (SQLite, Postgres, BigQuery).
- **This repo** gives you a minimal starter (Streamlit + SQLite) in **`app/`** and ETL that can read from **SQLite** or **BigQuery** (and soon Postgres if you add it).
- **Your product** = your app + your data; the ETL is the pipeline from your product to Looker Studio.
