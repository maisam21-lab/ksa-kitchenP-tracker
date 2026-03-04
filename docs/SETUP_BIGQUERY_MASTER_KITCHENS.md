# Use BigQuery as Kitchen Master Data source

The **Kitchen Master Data** section can read from BigQuery instead of (or before) Google Sheet when the Superset store is empty.

---

## Deployed app (push and use secrets — no local key file)

If you **push the app** to Streamlit Cloud (or another host), you don’t run anything locally and you don’t use `GOOGLE_APPLICATION_CREDENTIALS`. You configure everything in the **host’s Secrets**.

1. **Push your code** (e.g. to GitHub). `.streamlit/secrets.toml` and `scripts/credentials.json` are in `.gitignore`, so they are **not** pushed (which is correct).

2. **In the deployment** (e.g. Streamlit Cloud → your app → **Settings** → **Secrets**), paste a **secrets** config that includes:

   - **BigQuery config** so the app knows which project and query to use.
   - **Service account JSON** so the app can call BigQuery (no key file on the server).

**Example for Streamlit Cloud Secrets** (paste the whole block):

```toml
[bigquery_master_kitchens]
project_id = "css-operations"
query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql"

[gsheet_service_account]
type = "service_account"
project_id = "your-gcp-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_KEY_LINES\n-----END PRIVATE KEY-----\n"
client_email = "your-sa@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

Replace the `gsheet_service_account` values with the **exact** content from your `credentials.json` (the same key file you have in `scripts/credentials.json`). The app uses this for BigQuery when there is no local file.

3. **Redeploy / restart** the app if needed. Open **Kitchen Master Data** on the deployed URL; it should load from BigQuery with no local setup.

---

## Local run (optional)

If you run the app **on your machine**, you can either use the same secrets in `.streamlit/secrets.toml` (including `[gsheet_service_account]` with the full JSON) or use a key file and `GOOGLE_APPLICATION_CREDENTIALS` as in the rest of this doc.

---

## 1. Query file

The app uses the query in **`docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql`** (SA/BH from `css-operations.sales`: sf_kitchens, sf_facilities, sf_accounts, sf_opportunities). One row per kitchen (~999), with All_Opportunity_Names and All_Opportunity_IDs in one cell per record.

## 2. Configure secrets

Create or edit **`.streamlit/secrets.toml`** (copy from `.streamlit/secrets.toml.example`). Add:

```toml
[bigquery_master_kitchens]
project_id = "css-operations"
query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql"
```

- **project_id** — BigQuery project that can query `css-operations.sales` (e.g. `css-operations`).
- **query_file** — Path relative to the repo root. The app reads the file and runs the last `SELECT ... ;` (comments and other statements are ignored).

Alternatively you can paste the full query inline:

```toml
[bigquery_master_kitchens]
project_id = "css-operations"
query = "SELECT COALESCE(Acc.account_name, Fac.facility_name) AS Account_Name, ..."
```

## 3. Credentials

BigQuery uses the same credentials as the rest of the app:

- **Option A:** Set **`gsheet_service_account`** in secrets (full JSON). The app uses it for BigQuery too.
- **Option B:** Set **`GOOGLE_APPLICATION_CREDENTIALS`** to the path of a service account JSON key file (e.g. `scripts/credentials.json`). Ensure the key has **BigQuery Data Viewer** (or similar) on `css-operations`.
- **Option C:** If running on GCP (e.g. Cloud Run), default application credentials are used.

## 4. Run the app

From the repo root:

```bash
streamlit run app/tracker_app.py
```

Open **Kitchen Master Data**. If Superset has no data and `bigquery_master_kitchens` is set, the app will show **Master Kitchens (BigQuery)** and load the ~999 rows from the query.

**Refresh every 3 minutes:** The app caches BigQuery results in session state. When the cache is older than 3 minutes, the **next** time the page runs (e.g. you click, filter, or navigate), it refetches from BigQuery automatically. Use the **Refresh now** button to force an immediate refetch without waiting.

## 5. Troubleshooting

- **No data / section uses GSheet:** Check that `project_id` and `query_file` (or `query`) are set and that the path `docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql` exists relative to where you run Streamlit.
- **Permission denied:** Ensure the service account can run queries on `css-operations` (e.g. `css-operations.sales.sf_kitchens`).
- **Table not found:** Confirm the dataset is `sales` under project `css-operations` and table names are `sf_kitchens`, `sf_facilities`, `sf_accounts`, `sf_opportunities`.
