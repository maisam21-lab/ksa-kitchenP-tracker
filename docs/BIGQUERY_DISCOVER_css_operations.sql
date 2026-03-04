-- Discover tables in project: css-operations
-- Copy and run in the BigQuery SQL editor.
-- Uses region qualifier (region-us) so INFORMATION_SCHEMA is found. If your data is in EU, try region-eu.

-- 1. List all datasets in the project (US region)
SELECT schema_name AS dataset_id
FROM `css-operations.region-us.INFORMATION_SCHEMA.SCHEMATA`
ORDER BY schema_name;

-- 2. List all datasets and tables (US region)
SELECT
  table_catalog AS project,
  table_schema AS dataset_id,
  table_name,
  table_type
FROM `css-operations.region-us.INFORMATION_SCHEMA.TABLES`
ORDER BY table_schema, table_name;

-- 3. Search for relevant tables (opportunity, country, sales, facility, churn, kitchen)
SELECT
  table_schema AS dataset_id,
  table_name,
  CONCAT('FROM `css-operations.', table_schema, '.', table_name, '`') AS from_clause
FROM `css-operations.region-us.INFORMATION_SCHEMA.TABLES`
WHERE LOWER(table_name) LIKE '%opportunit%'
   OR LOWER(table_name) LIKE '%country%'
   OR LOWER(table_name) LIKE '%sales%'
   OR LOWER(table_name) LIKE '%facility%'
   OR LOWER(table_name) LIKE '%churn%'
   OR LOWER(table_name) LIKE '%kitchen%'
   OR LOWER(table_name) LIKE '%account%'
ORDER BY table_schema, table_name;
