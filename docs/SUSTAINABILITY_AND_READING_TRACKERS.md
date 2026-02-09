# Sustainability and Reading the Tracker You Already Have

## Is this sustainable?

**Yes.** The setup is sustainable if you keep a few habits:

| Practice | Why it helps |
|----------|----------------|
| **Own the code** | Everything is in this repo (app, ETL, config, schemas). No lock-in to a vendor for logic. |
| **Standard stack** | Python, Streamlit, SQLite, CSV — widely supported and easy to maintain or hand off. |
| **Config as source of truth** | `config/sources_*.yaml` and `config/schemas/*.json` define what runs; change config, not code, for new sources. |
| **Document decisions** | Use `docs/` and README so others (or you later) know how to run and extend it. |

**To make it more sustainable over time:**

1. **Back up the tracker data** — Copy `app/data/tracker.db` (or your Sheet/export) on a schedule so you can restore.
2. **Schedule the ETL** — Run the ETL (e.g. `py run_sqlite_ksa.py` or `py run_google_sheets_ksa.py`) on a schedule (Windows Task Scheduler, or a server cron) so Looker Studio always has fresh output.
3. **Optional upgrades when needed** — Move from SQLite to Postgres or BigQuery, or deploy the Streamlit app to a server/Streamlit Cloud, when you need multi-user or 24/7 access.

---

## How to read the tracker you already have

You can **read** (use as ETL source) whichever tracker you already use. Pick the one that matches your situation.

### 1. Tracker = Google Sheet (the one you already have)

**Option A — Google Sheets API (automatic)**

- **Config:** `config/sources_google_sheets_ksa.yaml` (set `sheet_id`, `table_name_or_gid`).
- **Credentials:** Service account JSON at `scripts/credentials.json` (or `GOOGLE_APPLICATION_CREDENTIALS`). Share the Sheet with the service account email (Viewer).
- **Run:** `py run_google_sheets_ksa.py`
- **Output:** `data/output/ksa_kitchen_tracker.csv` (validated rows from the Sheet).

**Option B — CSV export (no API)**

- Export the Sheet as CSV (or use copy-paste → Notepad → save as CSV), then:
  ```bash
  py scripts/paste_to_csv.py path\to\your_export.csv
  py validate_ksa_csv.py
  ```
- Or put the CSV at `data/input/ksa_kitchen_tracker.csv` and run:
  ```bash
  py validate_ksa_csv.py
  ```
- **Output:** `data/output/ksa_kitchen_tracker.csv`.

**Option C — Copy-paste (no Download)**

- Copy all cells from the Sheet, paste into Notepad, save as `ksa_paste.txt`. Then:
  ```bash
  py scripts/paste_to_csv.py scripts/ksa_paste.txt
  py validate_ksa_csv.py
  ```
- **Output:** `data/output/ksa_kitchen_tracker.csv`.

So: **to read the tracker you already have (Google Sheet)**, use one of A/B/C above; the “tracker” is the Sheet, the “read” is either the API run or the CSV/copy-paste flow into the same output file.

### 2. Tracker = Your web app (Streamlit + SQLite)

- **Config:** `config/sources_sqlite_ksa.yaml` (points to `app/data/tracker.db`).
- **Run:** `py run_sqlite_ksa.py`
- **Output:** `data/output/ksa_kitchen_tracker.csv` (validated rows from the app’s DB).

So: **to read the tracker you already have (Streamlit app)**, run `py run_sqlite_ksa.py`; the ETL reads the app’s SQLite DB.

### 3. Tracker = Execution log (Auto Refresh log CSV)

- **Run:** `py validate_execution_log.py "C:\path\to\KSA Kitchen Tracker - Auto Refresh Execution Log.csv"`
- **Output:** `data/output/ksa_auto_refresh_execution_log.csv`.

So: **to read the execution log tracker you already have**, run `validate_execution_log.py` with the path to that CSV.

---

## One-place summary: “How do I read the tracker we already have?”

| Tracker you already have | How to read it | Command | Output |
|--------------------------|----------------|--------|--------|
| **Google Sheet** (KSA Kitchen Tracker) | Sheets API | `py run_google_sheets_ksa.py` (after config + credentials) | `data/output/ksa_kitchen_tracker.csv` |
| **Google Sheet** (no API) | Export/copy-paste → CSV | `py scripts/paste_to_csv.py ...` then `py validate_ksa_csv.py` | `data/output/ksa_kitchen_tracker.csv` |
| **Streamlit app** (your own product) | SQLite DB | `py run_sqlite_ksa.py` | `data/output/ksa_kitchen_tracker.csv` |
| **Execution log CSV** | File path | `py validate_execution_log.py "path\to\log.csv"` | `data/output/ksa_auto_refresh_execution_log.csv` |

Use the row that matches the tracker you already have; that’s how you “read” it into the ETL and get the output for Looker Studio.
