# BigQuery in the app — step-by-step

Follow these steps to make **Kitchen Master Data** load from BigQuery.

---

## Where to put your service account JSON key

**What you have:** A file from Google Cloud (or your admin) that looks like a **.json** file. When you open it in a text editor, it has lines like `"type": "service_account"`, `"project_id": "..."`, `"private_key_id": "..."`, `"client_email": "..."`. That file is your **service account JSON key**.

**What to do:** Put that **exact file** in your app project so the app can find it.

1. Open **File Explorer** and go to your project folder:
   ```
   C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker
   ```

2. Inside that folder, open or create a folder named **`scripts`**.  
   So you have:
   ```
   C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker\scripts
   ```

3. **Copy** your service account JSON file (the one from Google/admin) into the **`scripts`** folder.

4. **Rename** the copied file to **`credentials.json`** (if it has another name like `my-key.json` or `project-12345-abc.json`).  
   The full path should be:
   ```
   C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker\scripts\credentials.json
   ```

**Summary:** Your key file lives at **`ksa-kitchenp-tracker\scripts\credentials.json`**. Don’t rename the folder or put the file in a different folder unless you change the path in the next steps.

---

## Step 1: Get a BigQuery key file (if you don’t have one)

You need a **service account JSON key** that can run queries on the `css-operations` project.

1. Ask your Google Cloud admin for:
   - A **service account JSON key** that has **BigQuery Data Viewer** (or similar) on `css-operations`,  
   **or**
   - Confirmation that you can use an existing key (e.g. the one you use for Google Sheets).

2. Save the JSON file somewhere safe, e.g.:
   - `C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker\scripts\credentials.json`  
   Do **not** commit this file to git.

If you already have a key file (e.g. for Sheets or BigQuery), use that and go to Step 2.

---

## Step 2: Create the secrets file

1. Open the **ksa-kitchenp-tracker** folder in File Explorer or in Cursor.

2. Go into the **`.streamlit`** folder.  
   If it doesn’t exist, create it.

3. Copy the file **`secrets.toml.example`** and paste it in the same `.streamlit` folder.

4. Rename the copy to **`secrets.toml`** (remove `.example`).  
   You should have:
   - `.streamlit/secrets.toml.example`
   - `.streamlit/secrets.toml`

---

## Step 3: Add the BigQuery config to secrets.toml

1. Open **`.streamlit/secrets.toml`** in an editor.

2. Find the commented block that starts with `# [bigquery_master_kitchens]`.

3. Replace that whole block with this (no `#` at the start of the three lines):

```toml
[bigquery_master_kitchens]
project_id = "css-operations"
query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql"
```

4. Save the file.

---

## Step 4: Tell the app where the key file is

Use **one** of these.

### Option A — Environment variable (easiest)

1. Put your JSON key file in the project, e.g.:  
   `ksa-kitchenp-tracker\scripts\credentials.json`

2. Before running the app, set the environment variable.  
   In **PowerShell** (replace the path if yours is different):

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker\scripts\credentials.json"
```

3. In the **same** PowerShell window, run the app:

```powershell
cd C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker
streamlit run app/tracker_app.py
```

### Option B — Use the same key as Google Sheet

If you already have **`[gsheet_service_account]`** in `secrets.toml` with the full JSON (type, project_id, private_key, client_email, etc.), the app will use that for BigQuery too. You don’t need to set `GOOGLE_APPLICATION_CREDENTIALS`.  
Just make sure that service account has **BigQuery Data Viewer** on `css-operations`.

---

## Step 5: Run the app and open Kitchen Master Data

1. From the **ksa-kitchenp-tracker** folder, run:

```powershell
streamlit run app/tracker_app.py
```

2. In the browser, open the **Kitchen Master Data** section (sidebar).

3. If everything is set correctly, you should see **Master Kitchens (BigQuery)** and about 999 rows. Data refreshes every 3 minutes; you can click **Refresh now** to reload from BigQuery.

---

## If it doesn’t work

- **“No data” / still seeing Google Sheet:**  
  - Check that `.streamlit/secrets.toml` contains exactly:
    - `[bigquery_master_kitchens]`
    - `project_id = "css-operations"`
    - `query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql"`
  - No `#` in front of these three lines.  
  - Run the app from the **ksa-kitchenp-tracker** folder so the path `docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql` is correct.

- **Permission / authentication error:**  
  - The key file must have access to the **css-operations** project and BigQuery.  
  - If using Option A, run the app from the **same** PowerShell window where you set `GOOGLE_APPLICATION_CREDENTIALS`.

- **“Table not found”:**  
  - Your BigQuery project must have access to the `css-operations.sales` dataset and the tables used in the query (e.g. `sf_kitchens`, `sf_opportunities`). Ask your admin if you’re not sure.

---

## Quick checklist

- [ ] Service account JSON key file exists (e.g. `scripts/credentials.json`)
- [ ] `.streamlit/secrets.toml` exists and has `[bigquery_master_kitchens]` with `project_id` and `query_file`
- [ ] `GOOGLE_APPLICATION_CREDENTIALS` set to the key path (Option A) or `gsheet_service_account` in secrets (Option B)
- [ ] App run with `streamlit run app/tracker_app.py` from **ksa-kitchenp-tracker**
- [ ] Opened **Kitchen Master Data** in the app
