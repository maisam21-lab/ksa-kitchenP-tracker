-- Discover BigQuery datasets and tables (e.g. sales.sf_opportunities, global_countries)
-- Run in BigQuery. Replace YOUR_PROJECT and optionally YOUR_DATASET.

-- =============================================================================
-- Step 1: List all datasets in the project
-- =============================================================================
-- Run this first to see available datasets (e.g. sales, raw, staging).
SELECT schema_name AS dataset_id
FROM `YOUR_PROJECT.INFORMATION_SCHEMA.SCHEMATA`
ORDER BY schema_name;

-- =============================================================================
-- Step 2: List all tables in a specific dataset (e.g. sales)
-- =============================================================================
-- Replace YOUR_PROJECT and YOUR_DATASET (e.g. sales).
SELECT table_name, table_type
FROM `YOUR_PROJECT.YOUR_DATASET.INFORMATION_SCHEMA.TABLES`
ORDER BY table_name;

-- =============================================================================
-- Step 3: Search for tables by name (across one dataset)
-- =============================================================================
-- Find tables containing 'opportunit', 'country', 'account', 'kitchen', 'facility', 'churn'
SELECT table_name
FROM `YOUR_PROJECT.YOUR_DATASET.INFORMATION_SCHEMA.TABLES`
WHERE LOWER(table_name) LIKE '%opportunit%'
   OR LOWER(table_name) LIKE '%country%'
   OR LOWER(table_name) LIKE '%account%'
   OR LOWER(table_name) LIKE '%kitchen%'
   OR LOWER(table_name) LIKE '%facility%'
   OR LOWER(table_name) LIKE '%churn%'
   OR LOWER(table_name) LIKE '%sales%'
ORDER BY table_name;

-- =============================================================================
-- Step 4: List columns for a table (e.g. sf_opportunities)
-- =============================================================================
-- Replace with your project, dataset, and table name.
SELECT column_name, data_type
FROM `YOUR_PROJECT.YOUR_DATASET.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'sf_opportunities'
ORDER BY ordinal_position;

-- Same for global_countries (if it exists)
-- SELECT column_name, data_type
-- FROM `YOUR_PROJECT.YOUR_DATASET.INFORMATION_SCHEMA.COLUMNS`
-- WHERE table_name = 'global_countries'
-- ORDER BY ordinal_position;
