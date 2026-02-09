# How users work on the tracker

**Agreed:** The tracker is **web-based**. Everyone can **filter** the view and **add data** without affecting existing records. Filters only change what you see; add only creates new records.

This doc describes **how people use the tracker** day to day and how that connects to the ETL and Looker Studio.

---

## Web-based tracker (agreed)

| Principle | How it works |
|-----------|----------------|
| **Web-based** | Users work in the browser (Streamlit app). |
| **Everyone can filter** | Filter by report date, site, region, metric. Filters **only change what is displayed** — they do **not** change or delete stored data. |
| **Add without affecting existing records** | "Add data" **only inserts new rows**. Existing records stay as they are. |

---

## Two ways the tracker can run (Sheet vs app)

| Tracker | Where users work | How they work |
|--------|-------------------|----------------|
| **Google Sheet** | In the Sheet (browser) | Same as today: open the Sheet, edit cells, add/delete rows. |
| **Your web app** (Streamlit) | In the app (browser) | Open the app URL, use “Add entry” and “List / Edit / Delete” tabs. |

In both cases **only the tracker** is editable by users. Looker Studio **only reads** from the ETL output (read-only); users do not edit the reporting data.

---

## Option A: Tracker = Google Sheet

### How users work

1. **Open** the Google Sheet (same link you use today).
2. **Add** — New row at the bottom; fill the columns (e.g. record_id, report_date, site_id, region, metric_name, value, status, notes).
3. **Edit** — Click a cell and change the value.
4. **Remove** — Delete the row (right-click row number → Delete row, or clear the row and leave it, depending on your rules).

No new tool: they keep working in the Sheet. Permissions stay in Google (who can view vs edit the Sheet).

### How it reaches Looker Studio

- Someone (or a scheduled job) runs the ETL so it **reads** the Sheet (e.g. `py run_google_sheets_multi.py` if you use the multi-sheet config).
- The ETL validates and writes **`data/output/ksa_kitchen_tracker.csv`** (and one file per tab if you use multiple sheets).
- That output is loaded into BigQuery (or used as a file source), and **Looker Studio** uses that as its data source (read-only).

So: **users work only in the Sheet**; they never touch the ETL or Looker Studio. The ETL is the bridge from Sheet → output → Looker Studio.

---

## Option B: Tracker = your web app (Streamlit)

### How users work

1. **Open** the app in the browser:
   - **Local:** Run `py -m streamlit run app/tracker_app.py` (or `install_and_run.bat`), then go to **http://localhost:8501**.
   - **Deployed:** Open the URL you get from Streamlit Cloud / your server (e.g. `https://your-app.streamlit.app`).

2. **Filter** — In **"List / Filter / Edit"**, use the filter dropdowns (Report date, Site, Region, Metric). Filters **only change what you see**; they do **not** change existing records.

3. **Add** — Open the **“Add entry”** tab, fill the fields (record_id, report_date, site_id, region, metric_name, value, status, notes), click **Add**.

4. **Edit** (optional) — Open **“List / Edit / Delete”**, expand the row, change values in the table, click **Update**.

5. **Remove** (optional) — In **“List / Edit / Delete”**, expand the row, click **Delete**.

All edits are saved in the app’s database (SQLite file: `app/data/tracker.db`). You control who can open the app (e.g. who can reach the URL, or add login later).

### How it reaches Looker Studio

- Someone (or a scheduled job) runs the ETL so it **reads** the app’s database (e.g. `py run_sqlite_ksa.py`).
- The ETL validates and writes **`data/output/ksa_kitchen_tracker.csv`**.
- That output is loaded into BigQuery (or used as a file source), and **Looker Studio** uses that (read-only).

So: **users work only in the web app**; they never touch the ETL or Looker Studio. The ETL is the bridge from app DB → output → Looker Studio.

---

## Summary: who does what

| Who | Where they work | What they do |
|-----|------------------|--------------|
| **Everyone** | In the **web-based tracker** (Streamlit app) | **Filter** the view (filters don't change data). **Add** new records (add doesn't affect existing records). Optionally edit or delete if allowed. |
| **You / BI / automation** | Run the **ETL** (e.g. `py run_sqlite_ksa.py`) | Run on a schedule or on demand so the output file is up to date for Looker Studio. |
| **Everyone / stakeholders** | **Looker Studio** (dashboards) | View reports only (read-only). Data comes from the ETL output. |

**Agreed:** Web-based tracker; everyone can filter and add data without affecting existing records. The ETL reads the tracker and feeds Looker Studio.
