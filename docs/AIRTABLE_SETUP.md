# Replace Google Sheets with Airtable

Use **Airtable** as the tracker where designated users add, edit, and remove entries. The ETL in this project reads from Airtable and writes a validated output for Looker Studio. No Google Sheets.

---

## 1. Create an Airtable base and table

1. Go to [airtable.com](https://airtable.com) and create a new base (e.g. **KSA Kitchen Tracker**).
2. Create a **table** (or use the default one). Name it e.g. **KSA Kitchen Tracker**.
3. Add **columns** that match the KSA Kitchen Tracker schema. Recommended names (must match schema or use `field_mapping` in config):

   | Field name   | Airtable type | Notes                    |
   |-------------|---------------|---------------------------|
   | record_id   | Single line text | Required; unique per row |
   | report_date| Date          | Required                  |
   | site_id    | Single line text | Required                |
   | site_name  | Single line text | Optional                |
   | region     | Single select  | Options: KSA (required)   |
   | metric_name| Single line text | Required                |
   | value      | Number (or text) | Optional                |
   | status     | Single line text | Optional                |
   | notes      | Long text      | Optional                  |

   If you use different names in Airtable (e.g. "Record ID" with a space), add `field_mapping` in `config/sources_airtable_ksa.yaml` to map them to the schema names above.

4. **Share the base** with designated users (Collaborator or Editor) so they can add, edit, and remove records. Do not share the base with people who should only see reports — they will use Looker Studio on the ETL output instead.

---

## 2. Get Base ID and API key

1. **Base ID**  
   Open your base. The URL is like:  
   `https://airtable.com/appXXXXXXXXXXXXXX/...`  
   The **Base ID** is the part after `/app` (e.g. `appXXXXXXXXXXXXXX`). Sometimes it’s shown in **Help → API documentation** for the base.

2. **API key**  
   - Go to [airtable.com/account](https://airtable.com/account) → **Developer**.
   - Create a **personal access token** with scopes: `data.records:read` (and `schema.bases:read` if you need to list tables).
   - Copy the token and keep it secret.

3. Put **Base ID** in `config/sources_airtable_ksa.yaml` under `base_id`.  
   Set the API key either:
   - **Env (recommended):**  
     `set AIRTABLE_API_KEY=your_token` (Windows) or `export AIRTABLE_API_KEY=your_token` (Mac/Linux), or  
   - **Config:** add `api_key: your_token` under the source (do **not** commit this file with a real key).

---

## 3. Configure the ETL

1. Open **`config/sources_airtable_ksa.yaml`**.
2. Set **`base_id`** to your Airtable base ID.
3. Set **`table_name`** to the exact table name (e.g. `KSA Kitchen Tracker`) or the table ID.
4. If your Airtable column names differ from the schema (e.g. "Record ID" instead of `record_id`), add **`field_mapping`**:

   ```yaml
   field_mapping:
     "Record ID": record_id
     "Report Date": report_date
     "Site ID": site_id
     "Region": region
     "Metric Name": metric_name
     "Value": value
     "Status": status
     "Notes": notes
   ```

5. Install deps and run:

   ```bash
   cd bi-etl-foundation
   pip install -r requirements.txt
   set AIRTABLE_API_KEY=your_token
   python run_airtable_ksa.py
   ```

   Output is written to **`data/output/ksa_kitchen_tracker.csv`**. Invalid rows go to **`data/quarantine/ksa_kitchen_tracker_invalid.csv`**.

---

## 4. Connect Looker Studio

- **Option A:** Load **`data/output/ksa_kitchen_tracker.csv`** into BigQuery (or another warehouse) and point Looker Studio at that table (read-only).
- **Option B:** Use a **Looker Studio connector** that reads from a file or BigQuery; do **not** connect Looker Studio directly to Airtable for this flow — the single source of truth for reporting is the ETL output.

Designated users keep editing in **Airtable**. You run the ETL on a schedule (e.g. daily); Looker Studio refreshes from the ETL output.

---

## 5. Schedule the ETL

Run **`python run_airtable_ksa.py`** on a schedule (e.g. Windows Task Scheduler, cron, or Cloud Scheduler) so the output and Looker Studio stay up to date with Airtable.

---

## Summary

| Layer           | Role |
|----------------|------|
| **Airtable**   | Tracker: designated users add, edit, remove records. Replaces Google Sheets. |
| **ETL**        | Reads Airtable → validates → writes `data/output/ksa_kitchen_tracker.csv` (or BigQuery). |
| **Looker Studio** | Reads only from the ETL output (read-only). |

No Google Sheets in the path.
