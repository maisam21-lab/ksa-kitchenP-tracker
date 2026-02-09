# Using Google APIs (Sheets API + BigQuery)

This project can use **Google APIs** as the source: **Google Sheets API** (read from Sheets without the Download button) or **Google BigQuery** (read from a BigQuery table). Both are configured in YAML and run through the same ETL pipeline (validate → transform → load).

---

## Option 1: Google Sheets API (read from Sheets)

Use the **Google Sheets API** so the ETL reads directly from your Google Sheet. No Download button needed. Designated users keep editing the Sheet; the ETL pulls the current state and writes validated output for Looker Studio.

### 1. Enable Google Sheets API and get credentials

**If you have Google Cloud access:**

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and select (or create) a project.
2. Enable **Google Sheets API**: APIs & Services → Library → search "Google Sheets API" → Enable.
3. Create a **service account**: APIs & Services → Credentials → Create credentials → Service account. Create the account, then add a **JSON key** (Keys → Add key → JSON) and download it.
4. **Share your Google Sheet** with the **service account email** (e.g. `xxx@project.iam.gserviceaccount.com`) as **Viewer**.

**If you don’t have permission to create service accounts** (e.g. in `css-operations`):

- Ask your GCP admin to create a service account with a JSON key and grant you the key file, or
- Ask the admin to run the ETL (e.g. in Cloud Shell) and share the output with you.

### 2. Configure the ETL

1. Put the **service account JSON key** in the project, e.g. **`scripts/credentials.json`** (do not commit it; add to `.gitignore`).  
   Or set **`GOOGLE_APPLICATION_CREDENTIALS`** to the full path of that file.
2. Open **`config/sources_google_sheets_ksa.yaml`** and set:
   - **`sheet_id`**: From the Sheet URL `https://docs.google.com/spreadsheets/d/SHEET_ID/edit` → use `SHEET_ID`.
   - **`table_name_or_gid`**: Either the **tab name** (e.g. `KSA Kitchen Tracker`) or the **gid** from the URL when that tab is open (`#gid=1341293927` → use `1341293927`).
   - **`credentials_path`**: e.g. `scripts/credentials.json` (or leave unset if using `GOOGLE_APPLICATION_CREDENTIALS`).

### 3. Install and run

```bash
cd bi-etl-foundation
pip install -r requirements.txt
# Optional if not using credentials_path in config:
# set GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\credentials.json
python run_google_sheets_ksa.py
```

Output: **`data/output/ksa_kitchen_tracker.csv`**. Invalid rows: **`data/quarantine/ksa_kitchen_tracker_invalid.csv`**.

---

## Option 2: Google BigQuery (read from a table)

Use **BigQuery** as the source. Data lives in a BigQuery table (e.g. filled by an app, another ETL, or a one-time import from Sheets). The ETL reads from that table, validates, and writes to the reporting output (file or another BigQuery dataset).

### 1. BigQuery table

- Create a dataset and table (e.g. `raw.ksa_kitchen_tracker`) with columns that match your schema (e.g. `record_id`, `report_date`, `site_id`, `region`, `metric_name`, etc.).
- Load data (e.g. from Sheets export, or from an app that writes to BigQuery).

### 2. Credentials

- Use a **service account** with BigQuery Data Viewer (or similar) and put its JSON key in **`GOOGLE_APPLICATION_CREDENTIALS`** or in a path you set in config.
- Or run where Google credentials are already available (e.g. Cloud Shell, same project).

### 3. Configure the ETL

Add a source in **`config/sources.yaml`** (or a new file, e.g. `sources_bigquery_ksa.yaml`):

```yaml
sources:
  - id: ksa_kitchen_tracker
    type: bigquery
    project_id: your-project-id
    dataset_id: raw
    table_id: ksa_kitchen_tracker
    schema_ref: ksa_kitchen_tracker
    # Optional: credentials_path: path/to/credentials.json
output:
  type: file
  path: data/output
```

Or use a **query** instead of a table:

```yaml
  - id: ksa_kitchen_tracker
    type: bigquery
    project_id: your-project-id
    dataset_id: raw
    query: "SELECT * FROM `your-project.raw.ksa_kitchen_tracker` WHERE region = 'KSA'"
    schema_ref: ksa_kitchen_tracker
```

### 4. Install and run

```bash
pip install -r requirements.txt
# set GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json  if needed
set PYTHONPATH=src
python -m etl
# Or with a custom config file: run_pipeline(config_path="config/sources_bigquery_ksa.yaml")
```

---

## Summary (Google API)

| Source type       | Config key           | Use case |
|-------------------|----------------------|----------|
| **google_sheets** | `sheet_id`, `table_name_or_gid`, `credentials_path` | Read from a Google Sheet via Sheets API (no Download). |
| **bigquery**      | `project_id`, `dataset_id`, `table_id` or `query`, optional `credentials_path` | Read from a BigQuery table or query. |

- **Google Sheets API**: ETL reads from the Sheet; designated users keep editing the Sheet; output is validated and used for Looker Studio.
- **BigQuery**: ETL reads from a BigQuery table/query; output is written to file (or BigQuery) for Looker Studio.

Both use **Google APIs** only; no Airtable or other vendors required for the source.
