-- Discover tables in project: css-dw-sync
-- Copy and run each query in the BigQuery SQL editor.

-- =============================================================================
-- 1. List all datasets in css-dw-sync
-- =============================================================================
SELECT schema_name AS dataset_id
FROM `css-dw-sync.region-us.INFORMATION_SCHEMA.SCHEMATA`
ORDER BY schema_name;

-- =============================================================================
-- 2. List ALL tables in the project (every dataset) — run this to see full map
-- =============================================================================
SELECT
  table_catalog AS project,
  table_schema AS dataset_id,
  table_name,
  table_type
FROM `css-dw-sync.region-us.INFORMATION_SCHEMA.TABLES`
ORDER BY table_schema, table_name;

-- =============================================================================
-- 3. Search for tables by name (opportunity, country, sales, facility, churn, kitchen)
-- =============================================================================
SELECT
  table_schema AS dataset_id,
  table_name,
  CONCAT('FROM `css-dw-sync.', table_schema, '.', table_name, '`') AS from_clause
FROM `css-dw-sync.region-us.INFORMATION_SCHEMA.TABLES`
WHERE LOWER(table_name) LIKE '%opportunit%'
   OR LOWER(table_name) LIKE '%country%'
   OR LOWER(table_name) LIKE '%account%'
   OR LOWER(table_name) LIKE '%kitchen%'
   OR LOWER(table_name) LIKE '%facility%'
   OR LOWER(table_name) LIKE '%churn%'
   OR LOWER(table_name) LIKE '%sales%'
ORDER BY table_schema, table_name;
