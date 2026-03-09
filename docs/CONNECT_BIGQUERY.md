# Connect the app to BigQuery

Use this to connect **Kitchen Master Data** (and optional SF Churn / go-live) to your BigQuery project. You can use **BigQuery and Google Sheet together**: when both are configured, the app lets you choose the data source in Kitchen Master Data.

---

## 1. Add BigQuery config to secrets

Create or edit **`.streamlit/secrets.toml`** in the project root and add:

```toml
[bigquery_master_kitchens]
project_id = "css-operations"
query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql"
```

- **project_id** — Your BigQuery project (e.g. `css-operations`) that can query the `sales` dataset.
- **query_file** — Path to the SQL file (relative to repo root). The app runs the `SELECT` from this file. The query in that file returns Master Kitchens SA/BH from `css-operations.sales` (sf_kitchens, sf_facilities, sf_accounts, sf_opportunities) with `is_live` and `stage_name`.

To use an inline query instead of a file:

```toml
[bigquery_master_kitchens]
project_id = "css-operations"
query = "SELECT ... FROM `css-operations.sales.sf_kitchens` ..."
```

---

## 2. Add credentials

Use **one** of these.

### Option A — Same as Google Sheets (recommended on Streamlit Cloud)

If you already have **`[gsheet_service_account]`** in secrets with the full JSON (type, project_id, private_key, client_email, etc.), the app uses it for BigQuery. No extra config.

Ensure that service account has **BigQuery Data Viewer** (or equivalent) on the project/datasets you query.

### Option B — Key file (local runs)

1. Put your service account JSON key at **`scripts/credentials.json`** (do not commit it).
2. Before starting the app, set:

   **PowerShell:**
   ```powershell
   $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker\scripts\credentials.json"
   ```

   **Bash:**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/scripts/credentials.json"
   ```

3. In the **same** terminal, run:
   ```bash
   streamlit run app/tracker_app.py
   ```

---

## 3. Streamlit Cloud (deployed app)

For the app deployed at e.g. `https://ksa-kitchenp-tracker-*.streamlit.app`:

1. Open your app on Streamlit Cloud → **Settings** (or **Manage app** → **Secrets**).
2. Add secrets in TOML format. You need **both** BigQuery and (if you use Google Sheet) the Sheets service account:

   ```toml
   [bigquery_master_kitchens]
   project_id = "css-operations"
   query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql"

   [gsheet_service_account]
   type = "service_account"
   project_id = "your-project"
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "your-sa@your-project.iam.gserviceaccount.com"
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."
   ```

3. **Redeploy** the app after saving secrets so the new config is applied.
4. Ensure the service account has **BigQuery Data Viewer** on `css-operations` (or the project you use) and that the Google Sheet is shared with the service account email (Viewer).

---

## 4. Verify

1. Open **Kitchen Master Data** in the app sidebar.
2. If BigQuery is connected, you’ll see **Master Kitchens (BigQuery)** and the table will load (data refreshes every 3 min; use **Refresh now** to refetch).
3. If both BigQuery and Google Sheet have data, a **Data source** radio appears: choose **BigQuery (SA/BH)** for fresh data from `css-operations.sales`, or **Google Sheet** for data from the last sheet refresh. Use **Refresh from Google Sheet** to pull the latest sheet data.
4. If you see **Connect Kitchen Master Data to BigQuery**, secrets or credentials are missing — check steps 1 and 2.

---

## Optional: SF Churn Data and go-live from BigQuery

- **SF Churn Data from BigQuery** — In secrets, add `[bigquery_sf_churn_data]` with `project_id` and `query`. Then “Refresh from Salesforce” will load that tab from BigQuery. See `.streamlit/secrets.toml.example`.
- **Go-live / Is Live** — Add `[bigquery_go_live]` with `project_id` and `query` (or `dataset_id` + `table_id`) so the dashboard can filter by live vs not live. See `docs/BIGQUERY_KITCHEN_GO_LIVE.sql` and `docs/MASTER_KITCHENS_QUERIES_README.md`.

---

## Troubleshooting

| Issue | Check |
|-------|--------|
| Still seeing “Connect to BigQuery” or GSheet only | `.streamlit/secrets.toml` has `[bigquery_master_kitchens]` with `project_id` and `query_file` (or `query`). No `#` in front of those lines. |
| “Permission denied” / auth error | Service account has BigQuery access. If using a key file, `GOOGLE_APPLICATION_CREDENTIALS` is set in the same shell where you run Streamlit. |
| “Table not found” | Project has access to the dataset and tables used in the query (e.g. `css-operations.sales`). |
| Query file not found | Run the app from the **repo root** so `docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql` exists. |

More detail: **docs/BIGQUERY_INGEST_STEP_BY_STEP.md** and **docs/SETUP_BIGQUERY_MASTER_KITCHENS.md**.
