-- Master Kitchens List — Trino (Hudi) query
-- Use Kitchen_Number__c as the MAIN table (like the Salesforce report) so Status, Kitchen Size,
-- Hood Size, List Price, etc. come from k, not from a join that returns NULL when
-- opportunity.kitchen_number__c is empty in Hudi.
--
-- Save this as a Superset SQL Lab saved query and set SUPERSET_SAVED_QUERY_ID_MASTER_KITCHENS
-- to its ID so the refresh job and app use it.
--
-- If you get COLUMN_NOT_FOUND, run:
--   DESCRIBE hudi_ingest.salesforce_cloudkitchens.kitchen_number__c;
--   DESCRIBE hudi_ingest.salesforce_cloudkitchens.account;
--   DESCRIBE hudi_ingest.salesforce_cloudkitchens.opportunity;
-- and fix column names. In Hudi, FKs are often lowercase: account__c, opportunity__c.
-- If you see COLUMN_NOT_FOUND for account__c or opportunity__c, try accountid / opportunityid.

WITH k AS (
  SELECT
    k.id,
    k.account__c,
    k.opportunity__c,
    k.name AS kitchen_name,
    k.kitchen_number_id_18__c,
    k.type__c AS kitchen_type,
    k.category__c,
    k.status__c,
    k.kitchen_size_sq_meters__c,
    k.hood_size__c,
    k.floor_price__c,
    k.sell_price__c,
    k.activation_fee__c,
    k.floor__c
  FROM hudi_ingest.salesforce_cloudkitchens.kitchen_number__c k
  WHERE k.name IS NOT NULL AND TRIM(k.name) <> ''
    AND k.name LIKE 'K%'
    AND (UPPER(k.name) NOT LIKE '%DEPRECATED%')
),
joined AS (
  SELECT
    a.name AS account_name,
    a.country__c,
    k.kitchen_type,
    k.category__c,
    k.kitchen_number_id_18__c,
    k.kitchen_name,
    k.status__c,
    k.kitchen_size_sq_meters__c,
    k.hood_size__c,
    k.floor_price__c,
    k.sell_price__c,
    k.activation_fee__c,
    k.floor__c,
    o.id AS opportunity_id,
    o.name AS opportunity_name,
    o.churn_date__c
  FROM k
  JOIN hudi_ingest.salesforce_cloudkitchens.account a ON a.id = k.account__c
  JOIN hudi_ingest.salesforce_cloudkitchens.recordtype rt
    ON rt.id = a.recordtypeid AND rt.sobjecttype = 'Account' AND rt.developername = 'Facility'
  LEFT JOIN hudi_ingest.salesforce_cloudkitchens.opportunity o ON o.id = k.opportunity__c
  WHERE a.country__c IN ('Bahrain', 'Saudi Arabia')
    AND (a.name IS NULL OR UPPER(a.name) NOT LIKE '%SA - JED%')
    AND (o.id IS NULL OR (o.churn_date__c IS NULL AND o.stagename IN ('Approved', 'Closed Won') AND (o.type IS NULL OR o.type <> 'CloudRetail')))
)
SELECT
  joined.account_name              AS "Account Name",
  joined.kitchen_type               AS "Type",
  joined.category__c                AS "Category",
  joined.kitchen_number_id_18__c    AS "Kitchen Number ID 18",
  joined.kitchen_name               AS "Kitchen Number Name",
  joined.status__c                 AS "Status",
  joined.kitchen_size_sq_meters__c  AS "Kitchen Size (Sq. Meters)",
  joined.hood_size__c               AS "Hood Size",
  joined.floor_price__c            AS "Floor Price",
  joined.sell_price__c             AS "List Price",
  joined.activation_fee__c         AS "Activation Fee",
  joined.opportunity_id            AS "Opportunity ID 18",
  joined.opportunity_name          AS "Opportunity Name",
  CAST(NULL AS VARCHAR)            AS "Opportunity Owner: Full Name",
  joined.floor__c                  AS "Floor",
  joined.country__c                AS "County",
  joined.churn_date__c             AS "Churn Date"
FROM joined
ORDER BY joined.account_name, joined.kitchen_name;

-- If account__c / opportunity__c do not exist, try this variant (uncomment and use):
-- JOIN ... account a ON a.id = k.accountid
-- LEFT JOIN ... opportunity o ON o.id = k.opportunityid
-- after confirming with: DESCRIBE hudi_ingest.salesforce_cloudkitchens.kitchen_number__c;
