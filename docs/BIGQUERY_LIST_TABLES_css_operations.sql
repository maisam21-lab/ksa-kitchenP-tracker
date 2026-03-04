-- List tables in candidate datasets (sales/opportunities/kitchen)
-- Run in BigQuery (project: css-operations). Uses region-us.

-- Tables in SalesOpsCK_DS, emea_ops, customer_operations, css_data
SELECT
  table_schema AS dataset_id,
  table_name,
  CONCAT('FROM `css-operations.', table_schema, '.', table_name, '`') AS from_clause
FROM `css-operations.region-us.INFORMATION_SCHEMA.TABLES`
WHERE table_schema IN (
  'SalesOpsCK_DS',
  'emea_ops',
  'customer_operations',
  'css_data'
)
ORDER BY table_schema, table_name;
