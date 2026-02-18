-- Find which dataset has Salesforce Account / Kitchen_Number__c / Opportunity tables
-- Run in BigQuery. Replace css-operations with your project if different.
--
-- Best candidates from your list: SalesOpsCK_DS, emea_ops, customer_operations, css_data.
-- Run Query 1 first (SalesOpsCK_DS). If no rows, run Query 2 (emea_ops), then 3, then 4.

-- Query 1: SalesOpsCK_DS (Sales Ops Cloud Kitchens)
SELECT 'SalesOpsCK_DS' AS dataset, table_name
FROM `css-operations.SalesOpsCK_DS.INFORMATION_SCHEMA.TABLES`
WHERE LOWER(table_name) IN ('account', 'opportunity', 'kitchen_number__c', 'recordtype')
   OR LOWER(table_name) LIKE '%account%'
   OR LOWER(table_name) LIKE '%kitchen%'
   OR LOWER(table_name) LIKE '%opportunity%'
   OR LOWER(table_name) LIKE '%recordtype%'
ORDER BY table_name;

-- Query 2: emea_ops (EMEA operations)
-- SELECT 'emea_ops' AS dataset, table_name
-- FROM `css-operations.emea_ops.INFORMATION_SCHEMA.TABLES`
-- WHERE LOWER(table_name) IN ('account', 'opportunity', 'kitchen_number__c', 'recordtype')
--    OR LOWER(table_name) LIKE '%account%' OR LOWER(table_name) LIKE '%kitchen%' OR LOWER(table_name) LIKE '%opportunity%'
-- ORDER BY table_name;

-- Query 3: customer_operations
-- SELECT 'customer_operations' AS dataset, table_name
-- FROM `css-operations.customer_operations.INFORMATION_SCHEMA.TABLES`
-- WHERE LOWER(table_name) LIKE '%account%' OR LOWER(table_name) LIKE '%kitchen%' OR LOWER(table_name) LIKE '%opportunity%'
-- ORDER BY table_name;

-- Query 4: css_data
-- SELECT 'css_data' AS dataset, table_name
-- FROM `css-operations.css_data.INFORMATION_SCHEMA.TABLES`
-- WHERE LOWER(table_name) LIKE '%account%' OR LOWER(table_name) LIKE '%kitchen%' OR LOWER(table_name) LIKE '%opportunity%'
-- ORDER BY table_name;
