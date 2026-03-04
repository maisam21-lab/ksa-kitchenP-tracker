-- =============================================================================
-- SA + Bahrain — All kitchens with go-live date (for tracker)
-- =============================================================================
-- App needs: kitchen_number, account_name, go_live_date.
-- Rule: go_live_date on or before today → Live; otherwise Not live (app derives this).

-- =============================================================================
-- OPTION 1: From sales (works as-is) — facility-level, one row per facility
-- =============================================================================
-- Uses css-operations.sales.sf_opportunities. No placeholders; run this directly.

SELECT
  opps.facility_id AS kitchen_number,
  opps.facility_id AS account_name,
  FORMAT_DATE('%Y-%m-%d', MIN(CASE WHEN opps.closed_won THEN opps.closed_won_date END)) AS go_live_date
FROM `css-operations.sales.sf_opportunities` opps
LEFT JOIN `css-operations.sales.global_countries` country
  ON opps.facility_country = country.country
WHERE opps.facility_country IN ('Saudi Arabia', 'Bahrain')
  AND opps.facility_id IS NOT NULL
  AND (country.region_sales_reporting IS NULL OR country.region_sales_reporting <> 'Inactive')
GROUP BY opps.facility_id
ORDER BY account_name;

-- =============================================================================
-- OPTION 2: Kitchen-level table (one row per kitchen)
-- =============================================================================
-- Use when you have a table with Account Name, Kitchen Number ID 18, Go Live Date.
-- You MUST replace YOUR_DATASET and YOUR_KITCHEN_TABLE with the real names
-- (e.g. run: SELECT schema_name FROM \`css-operations.region-us.INFORMATION_SCHEMA.SCHEMATA\` to list datasets).

/*
SELECT
  COALESCE(CAST(Kitchen_Number_ID_18__c AS STRING), Id) AS kitchen_number,
  Account_Name__c AS account_name,
  FORMAT_DATE('%Y-%m-%d', DATE(Go_Live_Date__c)) AS go_live_date
FROM `css-operations.YOUR_DATASET.YOUR_KITCHEN_TABLE`
WHERE (Account_Name__c LIKE 'SA - %' OR Account_Name__c LIKE 'BH - %')
   OR (Account_Country__c IN ('Saudi Arabia', 'Bahrain'))
ORDER BY account_name, kitchen_number;
*/
