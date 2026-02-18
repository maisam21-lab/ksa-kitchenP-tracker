-- Master Kitchens List — raw JSON schema (Postgres / dbt-style)
-- Matches the pattern from your examples: salesforce_raw.* with data_json ->> 'FieldName'.
-- Use this if your Master Kitchens source is raw tables (kitchen_number_raw, account_raw,
-- opportunity_raw, recordtype_raw) instead of flattened staging tables.
--
-- Same filters: Bahrain/Saudi Arabia, Facility record type, Kitchen name starts with K,
-- not Deprecated, Account name not SA - JED, churn blank, stage Approved/Closed Won, type <> CloudRetail.
--
-- Schema: salesforce_raw.kitchen_number_raw, account_raw, opportunity_raw, recordtype_raw.
-- Replace schema name (salesforce_raw) if yours differs. For BigQuery raw JSON use
-- JSON_EXTRACT_SCALAR(data_json, '$.FieldName') instead of data_json ->> 'FieldName'.

WITH kitchen_latest AS (
  SELECT
    data_json ->> 'Id' AS id,
    data_json ->> 'Account__c' AS account__c,
    data_json ->> 'Opportunity__c' AS opportunity__c,
    data_json ->> 'Name' AS kitchen_name,
    data_json ->> 'Kitchen_Number_ID_18__c' AS kitchen_number_id_18__c,
    data_json ->> 'Type__c' AS kitchen_type,
    data_json ->> 'Category__c' AS category__c,
    data_json ->> 'Status__c' AS status__c,
    (data_json ->> 'Kitchen_Size_Sq_Meters__c')::decimal AS kitchen_size_sq_meters__c,
    data_json ->> 'Hood_Size__c' AS hood_size__c,
    (data_json ->> 'Floor_Price__c')::decimal AS floor_price__c,
    (data_json ->> 'Sell_Price__c')::decimal AS sell_price__c,
    (data_json ->> 'Activation_Fee__c')::decimal AS activation_fee__c,
    data_json ->> 'Floor__c' AS floor__c,
    row_number() OVER (PARTITION BY data_json ->> 'Id' ORDER BY etl_timestamp DESC NULLS LAST) AS rn
  FROM salesforce_raw.kitchen_number_raw
  WHERE data_json ->> 'Name' IS NOT NULL AND TRIM(data_json ->> 'Name') <> ''
    AND (data_json ->> 'Name') LIKE 'K%'
    AND (UPPER(data_json ->> 'Name') NOT LIKE '%DEPRECATED%')
),
k AS (
  SELECT id, account__c, opportunity__c, kitchen_name, kitchen_number_id_18__c, kitchen_type,
         category__c, status__c, kitchen_size_sq_meters__c, hood_size__c, floor_price__c,
         sell_price__c, activation_fee__c, floor__c
  FROM kitchen_latest WHERE rn = 1
),
account_facility AS (
  SELECT
    a.data_json ->> 'Id' AS account_id,
    a.data_json ->> 'Name' AS account_name,
    a.data_json ->> 'Country__c' AS country__c
  FROM salesforce_raw.account_raw a
  JOIN salesforce_raw.recordtype_raw rt
    ON rt.data_json ->> 'Id' = a.data_json ->> 'RecordTypeId'
   AND rt.data_json ->> 'SobjectType' = 'Account'
   AND rt.data_json ->> 'DeveloperName' = 'Facility'
  WHERE a.data_json ->> 'Country__c' IN ('Bahrain', 'Saudi Arabia')
    AND (a.data_json ->> 'Name' IS NULL OR UPPER(a.data_json ->> 'Name') NOT LIKE '%SA - JED%')
),
opp AS (
  SELECT
    data_json ->> 'Id' AS opportunity_id,
    data_json ->> 'Name' AS opportunity_name,
    (data_json ->> 'Churn_Date__c')::date AS churn_date__c,
    data_json ->> 'StageName' AS stagename,
    data_json ->> 'Type' AS type
  FROM salesforce_raw.opportunity_raw
)
SELECT
  a.account_name              AS Account_Name,
  k.kitchen_type              AS Type,
  k.category__c               AS Category,
  k.kitchen_number_id_18__c   AS Kitchen_Number_ID_18,
  k.kitchen_name              AS Kitchen_Number_Name,
  k.status__c                 AS Status,
  k.kitchen_size_sq_meters__c AS Kitchen_Size_Sq_Meters,
  k.hood_size__c              AS Hood_Size,
  k.floor_price__c            AS Floor_Price,
  k.sell_price__c             AS List_Price,
  k.activation_fee__c        AS Activation_Fee,
  o.opportunity_id            AS Opportunity_ID_18,
  o.opportunity_name         AS Opportunity_Name,
  CAST(NULL AS text)          AS Opportunity_Owner_Full_Name,
  k.floor__c                  AS Floor,
  a.country__c                AS County,
  o.churn_date__c             AS Churn_Date
FROM k
JOIN account_facility a ON a.account_id = k.account__c
LEFT JOIN opp o ON o.opportunity_id = k.opportunity__c
WHERE (o.opportunity_id IS NULL OR (o.churn_date__c IS NULL AND o.stagename IN ('Approved', 'Closed Won') AND (o.type IS NULL OR o.type <> 'CloudRetail')))
ORDER BY a.account_name, k.kitchen_name;
