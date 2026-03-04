# Master Kitchens queries — where they live and when to use them

## 1. BigQuery staging tables (css-operations)

**File:** `BIGQUERY_MASTER_KITCHENS.sql`

- **Project / dataset:** `css-operations.us_ck_central_ops_bi`
- **Tables:** `tbl_salesforce_staging_account`, `tbl_salesforce_staging_kitchen_number`, `tbl_salesforce_staging_record_type`, `tbl_salesforce_cw_delivery_opportunity`
- **Use when:** You run Master Kitchens in BigQuery and your source is these flattened staging tables (lowercase column names).

## 2. Raw JSON schema (Postgres / dbt-style)

**File:** `MASTER_KITCHENS_RAW_JSON_EXAMPLE.sql`

- **Schema / tables:** `salesforce_raw.kitchen_number_raw`, `account_raw`, `opportunity_raw`, `recordtype_raw` with a **data_json** (JSON/JSONB) column.
- **Pattern:** Same as your internal examples — `data_json ->> 'FieldName'`, `::date`, `::decimal`, `row_number() OVER (PARTITION BY ... ORDER BY etl_timestamp DESC)` for dedupe.
- **Use when:** Your warehouse has raw Salesforce tables with one JSON column per row; you can run this in Postgres (or adapt `->>` to BigQuery `JSON_EXTRACT_SCALAR(data_json, '$.FieldName')` if the raw layer is in BigQuery).

## 3. Your internal examples (reference)

The long examples you shared (kitchen_number_raw with `data_json ->> 'Id'`, accounts CTE with `inverse_rank`, facilities with `RecordTypeId = '012f4000000RcZ2AAK'`, opp_fields and opp_data_ranked with `{{ref('sf_...')}}`) are the same pattern:

- **Kitchen:** `salesforce_raw.kitchen_number_raw`, extract from `data_json`.
- **Account:** `salesforce_raw.account_raw`, dedupe by `row_number() ... order by etl_timestamp desc`, filter by RecordTypeId.
- **Facility:** Account where `RecordTypeId = '012f4000000RcZ2AAK'` (replace with your EMEA/APAC Facility RecordTypeId if different).
- **Opportunity:** `salesforce_raw.opportunity_raw`, many fields from `data_json`, plus refs to field history and users for closed_won_owner.

The raw-json Master Kitchens query in `MASTER_KITCHENS_RAW_JSON_EXAMPLE.sql` follows this style and applies the same KSA filters (Bahrain/Saudi Arabia, Facility, K%, not Deprecated, no SA - JED, churn blank, stage Approved/Closed Won, type ≠ CloudRetail).

## 4. Kitchen Live vs Not live (go-live from BigQuery)

**File:** `BIGQUERY_KITCHEN_GO_LIVE.sql`

- **Purpose:** The tracker sheet has no go-live column. This query returns one row per kitchen with `kitchen_number`, `account_name`, `go_live_date`, and `is_live` so the app can distinguish live vs not live kitchens.
- **Use when:** You want the Dashboard to filter by "Live" / "Not live" and show Is Live / Go Live Date. Configure Streamlit secrets `bigquery_go_live.project_id` and `bigquery_go_live.query` (or `dataset_id` + `table_id`). See the SQL file for templates (raw JSON vs flattened staging) and replace `PROJECT_ID`, `DATASET_ID`, and the Account go-live field name (e.g. `Go_Live_Date__c`).

## Summary

| Source layer        | File to use                          |
|---------------------|--------------------------------------|
| BQ staging (css-operations) | `BIGQUERY_MASTER_KITCHENS.sql`       |
| Raw JSON (salesforce_raw.*) | `MASTER_KITCHENS_RAW_JSON_EXAMPLE.sql` |
| Go-live / is_live (any BQ) | `BIGQUERY_KITCHEN_GO_LIVE.sql`       |
| sales schema (sf_opportunities) | `BIGQUERY_SALES_EXAMPLES.sql` (churn, Listco/CSS, facility_country) |
