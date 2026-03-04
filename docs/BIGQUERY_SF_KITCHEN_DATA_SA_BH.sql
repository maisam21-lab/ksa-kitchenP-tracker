-- =============================================================================
-- SF Kitchen Data — same headers as Salesforce report (SA + Bahrain)
-- =============================================================================
--
-- STEP 0 — FIND THE RIGHT PLACE (run these first)
-- We were using us_ck_central_ops_bi; your SA/BH data may be elsewhere.
--
-- (A) List all datasets in css-operations:
--     SELECT schema_name AS dataset_id
--     FROM `css-operations.region-us.INFORMATION_SCHEMA.SCHEMATA`
--     ORDER BY 1;
--
-- (B) List tables in sales (you already have SA/BH go-live from sales.sf_opportunities):
--     SELECT table_name FROM `css-operations.sales.INFORMATION_SCHEMA.TABLES` ORDER BY 1;
--
-- (C) List tables in any other dataset (replace DATASET_ID):
--     SELECT table_name FROM `css-operations.DATASET_ID.INFORMATION_SCHEMA.TABLES` ORDER BY 1;
--
-- Once you know the correct project.dataset.table for kitchens (and account/facility),
-- replace the FROM/JOIN below with those table names and column names.
--
-- =============================================================================
-- MAIN QUERY (currently points at us_ck_central_ops_bi — change if your data is elsewhere)
-- =============================================================================
-- Option A: Select all columns from both tables
SELECT k.*, a.*
FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_kitchen_number` k
LEFT JOIN `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_account` a
  ON a.facility_id = k.facility_account_id
ORDER BY a.account_name, k.kitchen_number_name;

-- Option B: Specific columns (report-style headers) — uncomment to use
/*
SELECT
  a.account_name                       AS Account_Name,
  k.kitchen_number_type                AS Type_,
  CAST(NULL AS STRING)                 AS Category,
  k.kitchen_number_id                  AS Kitchen_Number_ID_18,
  k.kitchen_number_name                AS Kitchen_Number_Name,
  k.kitchen_number_status              AS Status,
  k.size                               AS Kitchen_Size_Sq_Meters,
  CAST(NULL AS STRING)                 AS Hood_Size,
  k.floor_price                        AS Floor_Price,
  k.MSRP                               AS List_Price,
  CAST(NULL AS FLOAT64)                AS Activation_Fee,
  CAST(NULL AS STRING)                 AS Opportunity_ID_18,
  CAST(NULL AS STRING)                 AS Opportunity_Name,
  CAST(NULL AS STRING)                 AS Opportunity_Owner_Full_Name,
  CAST(NULL AS STRING)                 AS Floor,
  a.country                            AS County,
  CAST(NULL AS STRING)                 AS Go_Live_Date
FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_kitchen_number` k
LEFT JOIN `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_account` a
  ON a.facility_id = k.facility_account_id
ORDER BY 1, 6;
*/

-- =============================================================================
-- DIAGNOSTIC: Run these to see why no data is returned
-- =============================================================================
-- (1) Do you have any kitchen rows?
-- SELECT COUNT(*) AS kitchen_count FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_kitchen_number`;

-- (2) Do you have any account rows? What do country / account_name look like?
-- SELECT COUNT(*) AS account_count FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_account`;
-- SELECT DISTINCT country FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_account` ORDER BY 1;
-- SELECT account_id, account_name, country FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_account` LIMIT 20;

-- (3) Does the join key match? (kitchen.facility_account_id vs account.account_id)
-- SELECT k.facility_account_id, a.account_id, a.account_name, a.country
-- FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_kitchen_number` k
-- LEFT JOIN `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_account` a
--   ON a.account_id = k.facility_account_id
-- LIMIT 20;

-- (4) If join uses facility_id on account instead of account_id, use this version:
--     Change the ON clause to:  ON a.facility_id = k.facility_account_id
--
-- (5) If still no data: run KITCHEN-ONLY (no join) to confirm the kitchen table has rows:
-- SELECT
--   CAST(k.facility_account_id AS STRING) AS Account_Name,
--   k.kitchen_number_type AS Type_,
--   CAST(NULL AS STRING) AS Category,
--   k.kitchen_number_id AS Kitchen_Number_ID_18,
--   k.kitchen_number_name AS Kitchen_Number_Name,
--   k.kitchen_number_status AS Status,
--   k.size AS Kitchen_Size_Sq_Meters,
--   CAST(NULL AS STRING) AS Hood_Size,
--   k.floor_price AS Floor_Price,
--   k.MSRP AS List_Price,
--   CAST(NULL AS FLOAT64) AS Activation_Fee,
--   CAST(NULL AS STRING) AS Opportunity_ID_18,
--   CAST(NULL AS STRING) AS Opportunity_Name,
--   CAST(NULL AS STRING) AS Opportunity_Owner_Full_Name,
--   CAST(NULL AS STRING) AS Floor,
--   CAST(NULL AS STRING) AS County,
--   CAST(NULL AS STRING) AS Go_Live_Date
-- FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_kitchen_number` k
-- ORDER BY k.kitchen_number_name
-- LIMIT 500;
