-- Kitchen "Live" vs "Not live" — BigQuery query for KSA Kitchens Tracker
--
-- Purpose: The tracker sheet does not have a go-live column. This query returns one row per
-- kitchen with identifiers to join to the app (Kitchen Number + Account Name) and an
-- is_live flag (and optional go_live_date) so the app can distinguish live vs not live.
--
-- Join in app: match on (Kitchen_Number_ID_18__c or "Kitchen Number" or "Name") and
-- (Account__r.Name or "Account Name" / "Facility").
--
-- Replace before running:
--   - PROJECT_ID, DATASET_ID, and table names with your Salesforce sync (e.g. EMEA/APAC).
--   - Go_Live_Date__c with your actual Account (Facility) go-live field API name if different.
--     (Common: Go_Live_Date__c, Live_Date__c, Operational_Date__c — check Setup > Account > Fields.)
--
-- Option A: Raw JSON tables (BigQuery: use JSON_EXTRACT_SCALAR)
-- Option B: Flattened staging tables (lowercase column names)

-- =============================================================================
-- OPTION A: Raw JSON schema (salesforce_raw or similar)
-- =============================================================================
-- Uncomment and replace PROJECT_ID, DATASET_ID, and field paths.

/*
WITH account_latest AS (
  SELECT
    JSON_EXTRACT_SCALAR(data_json, '$.Id') AS account_id,
    JSON_EXTRACT_SCALAR(data_json, '$.Name') AS account_name,
    SAFE.PARSE_DATE('%Y-%m-%d', JSON_EXTRACT_SCALAR(data_json, '$.Go_Live_Date__c')) AS go_live_date
  FROM `PROJECT_ID.DATASET_ID.account_raw`
  WHERE JSON_EXTRACT_SCALAR(data_json, '$.Name') IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_EXTRACT_SCALAR(data_json, '$.Id') ORDER BY etl_timestamp DESC) = 1
),
kitchen_latest AS (
  SELECT
    JSON_EXTRACT_SCALAR(data_json, '$.Id') AS kitchen_id,
    JSON_EXTRACT_SCALAR(data_json, '$.Account__c') AS account__c,
    JSON_EXTRACT_SCALAR(data_json, '$.Name') AS kitchen_name,
    JSON_EXTRACT_SCALAR(data_json, '$.Kitchen_Number_ID_18__c') AS kitchen_number_id_18
  FROM `PROJECT_ID.DATASET_ID.kitchen_number_raw`
  WHERE JSON_EXTRACT_SCALAR(data_json, '$.Name') IS NOT NULL
    AND STARTS_WITH(JSON_EXTRACT_SCALAR(data_json, '$.Name'), 'K')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY JSON_EXTRACT_SCALAR(data_json, '$.Id') ORDER BY etl_timestamp DESC) = 1
)
SELECT
  COALESCE(k.kitchen_number_id_18, k.kitchen_name) AS kitchen_number,
  a.account_name AS account_name,
  a.go_live_date AS go_live_date,
  (a.go_live_date IS NOT NULL AND a.go_live_date <= CURRENT_DATE()) AS is_live
FROM kitchen_latest k
JOIN account_latest a ON a.account_id = k.account__c
ORDER BY a.account_name, k.kitchen_name;
*/

-- =============================================================================
-- OPTION B: Flattened staging tables (e.g. tbl_salesforce_staging_*)
-- =============================================================================
-- Use when your BQ project has flattened Account + Kitchen tables with columns
-- like account_id, name, go_live_date__c (or similar). Adjust column names to match.

/*
SELECT
  COALESCE(k.kitchen_number_id_18__c, k.name) AS kitchen_number,
  a.name AS account_name,
  SAFE.PARSE_DATE('%Y-%m-%d', a.go_live_date__c) AS go_live_date,
  (SAFE.PARSE_DATE('%Y-%m-%d', a.go_live_date__c) IS NOT NULL
   AND SAFE.PARSE_DATE('%Y-%m-%d', a.go_live_date__c) <= CURRENT_DATE()) AS is_live
FROM `PROJECT_ID.DATASET_ID.tbl_salesforce_staging_kitchen_number` k
JOIN `PROJECT_ID.DATASET_ID.tbl_salesforce_staging_account` a
  ON a.id = k.account__c
WHERE a.record_type_developer_name = 'Facility'
  AND (UPPER(COALESCE(a.country__c, '')) IN ('SAUDI ARABIA', 'BAHRAIN', 'BH', 'SA'))
ORDER BY a.name, k.name;
*/

-- =============================================================================
-- Minimal template (paste into BigQuery, replace PROJECT_ID, DATASET_ID, table names, Go_Live_Date__c)
-- =============================================================================
-- Output columns required by the app: kitchen_number, account_name, go_live_date, is_live.
-- is_live = TRUE when the facility's go-live date is set and in the past.
-- App joins on: kitchen_number ↔ Kitchen Number / Kitchen_Number_ID_18__c / Name;
--               account_name  ↔ Account Name / Account__r.Name / Facility.

/*
SELECT
  COALESCE(k.Kitchen_Number_ID_18__c, k.Name) AS kitchen_number,
  a.Name AS account_name,
  SAFE.PARSE_DATE('%Y-%m-%d', a.Go_Live_Date__c) AS go_live_date,
  (SAFE.PARSE_DATE('%Y-%m-%d', a.Go_Live_Date__c) IS NOT NULL
   AND SAFE.PARSE_DATE('%Y-%m-%d', a.Go_Live_Date__c) <= CURRENT_DATE()) AS is_live
FROM `PROJECT_ID.DATASET_ID.kitchen_number` k
JOIN `PROJECT_ID.DATASET_ID.account` a ON a.Id = k.Account__c
WHERE 1=1
  AND (UPPER(COALESCE(a.Country__c, '')) IN ('SAUDI ARABIA', 'BAHRAIN', 'BH', 'SA')
       OR a.Country__c IN ('Saudi Arabia', 'Bahrain'))
ORDER BY a.Name, k.Name;
*/

-- See MASTER_KITCHENS_QUERIES_README.md for where KSA/EMEA data may live (e.g. ck_emea_apac_marketing).
-- After you run the query and have the table or saved view, configure the app: Streamlit secrets
-- bigquery_go_live.project_id, bigquery_go_live.dataset_id, and bigquery_go_live.query (or table_id).
