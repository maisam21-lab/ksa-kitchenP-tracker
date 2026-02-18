# Master Kitchens from Trino — Fix for “all NULL” columns

## Why columns were NULL

- The app (and earlier Trino query) used **Opportunity** as the main table and joined **Kitchen_Number__c** on `opportunity.kitchen_number__c = kitchen_number__c.id`.
- In your Hudi sync, **`opportunity.kitchen_number__c` is empty (NULL)** for all rows, so that join never matched and every column coming from the kitchen table was NULL (Status, Kitchen Size, Hood Size, List Price, etc.).

## Fix: use Kitchen_Number__c as the main table

- In Salesforce, the Master Kitchens report is based on the **Kitchen_Number__c** object (with lookups to Account and Opportunity).
- The Trino query in **`TRINO_MASTER_KITCHENS_FROM_KITCHEN_NUMBER.sql`** does the same: it uses **Kitchen_Number__c** as the main table and joins **Account** and **Opportunity**.
- Then Status, Kitchen Size, Hood Size, List Price, etc. come **from the kitchen row**, so they are only NULL when the source field is actually empty, not because the join failed.

## What you need to do

1. **Check that Kitchen_Number__c is synced in Hudi**  
   In Trino/Superset run:
   ```sql
   SELECT COUNT(*) FROM hudi_ingest.salesforce_cloudkitchens.kitchen_number__c;
   ```
   If this returns a positive number, the fix can work.

2. **Use the new query in Superset**
   - Open **SQL Lab** in Superset.
   - Paste the contents of **`docs/TRINO_MASTER_KITCHENS_FROM_KITCHEN_NUMBER.sql`** (you can remove the comments at the top if Superset complains).
   - Run it. If you get `COLUMN_NOT_FOUND`, run:
     ```sql
     DESCRIBE hudi_ingest.salesforce_cloudkitchens.kitchen_number__c;
     ```
     and fix column names in the query (e.g. `account__c` → `accountid` if that’s what Hudi has).
   - **Save** the query as a Superset “Saved query” and note its ID.

3. **Point the refresh job at the saved query**
   - Set `SUPERSET_SAVED_QUERY_ID_MASTER_KITCHENS` to that saved query ID (e.g. in GitHub Actions secrets or your env).
   - The refresh job will then pull Master Kitchens from this Trino query instead of the old one, and the app will show Status, Kitchen Size, Hood Size, List Price, etc. from the kitchen table.

4. **If Kitchen_Number__c is empty or missing in Hudi**
   - Then the pipeline does not sync that object. Use **Salesforce report by ID** or **Google Sheets** as the Master Kitchens source until the Hudi sync includes Kitchen_Number__c (and the right columns).
