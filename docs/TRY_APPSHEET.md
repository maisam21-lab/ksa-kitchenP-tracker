# Try AppSheet

Use **Google AppSheet** as the tracker: users add and filter data in an AppSheet app; the data lives in a Google Sheet (or in BigQuery/Cloud SQL if you set that up). This guide gets you from zero to a working AppSheet app and how the ETL fits in.

---

## 1. Create an AppSheet app and connect a Sheet

**1.1** Go to **[appsheet.com](https://www.appsheet.com)** and sign in with your Google account (e.g. maysam.abukashabeh@cloudkitchens.com).

**1.2** Click **Create new app** (or **My apps** → **New app**).

**1.3** Choose **Start with your data** and pick **Google Sheets**.

**1.4** Select the **Google Sheet** that will hold the tracker data.

- If you already have a Sheet (e.g. KSA Kitchen Tracker): select it.
- If not: create a new Sheet with columns that match our schema: **record_id**, **report_date**, **site_id**, **site_name**, **region**, **metric_name**, **value**, **status**, **notes**. Use the first row as headers. Then connect that Sheet to AppSheet.

**1.5** AppSheet will read the Sheet structure. Confirm the table and columns, then **Create app**.

---

## 2. Design the app so users can filter and add data

**2.1** In the AppSheet editor:

- Add a **Table** or **View** so users can **see** the data and **filter** (e.g. by report_date, site_id, region, metric_name). Filters in the app only change what is shown; they do not change the data in the Sheet.
- Add a **Form** (or **Add** action) so users can **add** new rows. Map form fields to: record_id, report_date, site_id, site_name, region, metric_name, value, status, notes. Use **Add new row** so each submit **inserts** a new row — existing records stay as they are.
- (Optional) Add **Edit** and **Delete** actions if you want users to change or remove rows.

**2.2** Set **Permissions** (who can open the app, who can add/edit). Save and **Publish** the app so users can open it (via link or install).

**2.3** Share the app link with your team. Everyone uses the **AppSheet app** to filter and add data — no one needs to open the raw Google Sheet.

---

## 3. How the ETL fits in

The ETL in this project reads from your **data source** and writes **data/output/ksa_kitchen_tracker.csv** (or BigQuery) for Looker Studio or any other reporting tool.

**If AppSheet uses a Google Sheet as backend:**

- The **Sheet** is the source of truth. AppSheet reads and writes that Sheet.
- **Option A — Google Sheets API (when you have a key):**  
  Use **`config/sources_google_sheets_ksa.yaml`** (or **sources_gsheet_try.yaml**). Set **sheet_id** to the Sheet that AppSheet is connected to, and **table_name_or_gid** to the tab name or gid. Put the service account JSON in **.secrets/gsheet-service.json** (or **scripts/credentials.json**). Share that Sheet with the service account email (Viewer). Run **`py run_google_sheets_ksa.py`** (or **`py run_gsheet_try.py`**). The ETL will read the same Sheet that AppSheet uses and produce the output CSV.
- **Option B — No API key (for now):**  
  Export the Sheet as CSV (File → Download → CSV) or copy the data into a file. Put the file in **data/input/** (e.g. **ksa_kitchen_tracker.csv**). Run **`py validate_ksa_csv.py`** (or **`py run_ksa_test.py`** with file source). The ETL will validate and write **data/output/ksa_kitchen_tracker.csv**.

**If AppSheet uses BigQuery or Cloud SQL as backend:**

- The **database** is the source of truth. Use **`config/sources.yaml`** (or a new config) with **type: bigquery** (or postgres when we add it). Point to the same table AppSheet uses. Run the ETL; output is still **data/output/ksa_kitchen_tracker.csv** (or load to BigQuery). Looker Studio connects to that output.

---

## 4. Checklist: Try AppSheet

| Step | What you do |
|------|-------------|
| 1 | Sign in at appsheet.com with your Google account. |
| 2 | Create a new app → Start with your data → Google Sheets → select (or create) the Sheet. |
| 3 | Add a Table/View (with filters) and a Form (Add new row) so users can filter and add data without touching the Sheet. |
| 4 | Set permissions, publish, and share the app link with your team. |
| 5 | When you have a Sheets API key: set **sheet_id** and **credentials_path** in **config/sources_google_sheets_ksa.yaml**, share the Sheet with the service account, run **`py run_google_sheets_ksa.py`**. Until then: export the Sheet to CSV and run **`py validate_ksa_csv.py`** to get **data/output/ksa_kitchen_tracker.csv** for reporting. |

---

## Summary

- **AppSheet** = the tracker (users filter and add data in the app; data in Sheet or DB).
- **ETL** = reads that source (Sheet via API or CSV export, or BigQuery) and writes **data/output/ksa_kitchen_tracker.csv** for Looker Studio or any other tool.
- You can **try AppSheet** now: create the app, connect the Sheet, add view + form, share the app. Connect the ETL once you have the API key (or use CSV export for now).
