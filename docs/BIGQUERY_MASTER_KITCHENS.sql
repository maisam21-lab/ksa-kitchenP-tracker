-- Master Kitchens List — BigQuery (accounts + kitchen data)
-- Project: css-operations | Dataset: us_ck_central_ops_bi
--
-- IMPORTANT: This dataset has NO Bahrain or Saudi Arabia in account.country.
-- It is Americas/UK focused. For KSA Master Kitchens use:
--   - Salesforce report by ID or Google Sheet, OR
--   - A different project/dataset that has EMEA/APAC data (e.g. ck_emea_apac_marketing).
--
-- Below: KSA filter (returns 0 rows in css-operations). After the first query, an optional
-- "Americas" version is included so you can see data from this dataset.

WITH k AS (
  SELECT
    k.kitchen_number_id,
    k.facility_account_id,
    k.kitchen_number_name AS kitchen_name,
    k.kitchen_number_type AS kitchen_type,
    k.kitchen_number_status AS status_val,
    k.size AS kitchen_size_sq_meters,
    k.floor_price,
    k.MSRP AS list_price_val
  FROM `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_kitchen_number` k
  WHERE k.kitchen_number_name IS NOT NULL AND TRIM(k.kitchen_number_name) <> ''
    AND k.kitchen_number_name LIKE 'K%'
    AND (UPPER(k.kitchen_number_name) NOT LIKE '%DEPRECATED%')
),
joined AS (
  SELECT
    a.account_name,
    a.country,
    k.kitchen_type,
    k.kitchen_name,
    k.status_val,
    k.kitchen_size_sq_meters,
    k.floor_price,
    k.list_price_val,
    k.kitchen_number_id
  FROM k
  JOIN `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_account` a ON a.account_id = k.facility_account_id
  JOIN `css-operations.us_ck_central_ops_bi.tbl_salesforce_staging_record_type` rt
    ON rt.record_type_id = a.record_type_id AND rt.record_type_name = 'Facility'
  WHERE a.country IN ('Bahrain', 'Saudi Arabia')
    AND (a.account_name IS NULL OR UPPER(a.account_name) NOT LIKE '%SA - JED%')
)
SELECT
  joined.account_name              AS Account_Name,
  joined.kitchen_type              AS Type,
  CAST(NULL AS STRING)             AS Category,
  joined.kitchen_number_id         AS Kitchen_Number_ID_18,
  joined.kitchen_name              AS Kitchen_Number_Name,
  joined.status_val                AS Status,
  joined.kitchen_size_sq_meters     AS Kitchen_Size_Sq_Meters,
  CAST(NULL AS STRING)             AS Hood_Size,
  joined.floor_price               AS Floor_Price,
  joined.list_price_val            AS List_Price,
  CAST(NULL AS STRING)             AS Activation_Fee,
  CAST(NULL AS STRING)             AS Opportunity_ID_18,
  CAST(NULL AS STRING)             AS Opportunity_Name,
  CAST(NULL AS STRING)             AS Opportunity_Owner_Full_Name,
  CAST(NULL AS STRING)             AS Floor,
  joined.country                   AS County,
  CAST(NULL AS DATE)               AS Churn_Date
FROM joined
ORDER BY joined.account_name, joined.kitchen_name;

-- =============================================================================
-- OPTIONAL: Use this version to see data in THIS dataset (Americas + UK).
-- Same logic, but country IN (United States, Canada, Mexico, Brazil, ...) instead of KSA.
-- Replace the WHERE in "joined" above with the one below to run the Americas version:
--
--   WHERE a.country IN ('United States','Canada','Mexico','Brazil','Colombia','Chile','Peru','Costa Rica','Panama','Ecuador','United Kingdom')
--     AND (a.account_name IS NULL OR UPPER(a.account_name) NOT LIKE '%SA - JED%')
--
-- Or remove the country filter entirely to get all countries in this table.
-- =============================================================================
