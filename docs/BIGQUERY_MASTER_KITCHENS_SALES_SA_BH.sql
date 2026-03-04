-- =============================================================================
-- Master Kitchens — SA/BH from css-operations.sales (working query)
-- =============================================================================
-- Source: sf_kitchens + sf_facilities + sf_accounts + sf_opportunities (one opportunity per facility, by latest churn_date).
-- One row per kitchen (~999). All_Opportunity_Names and All_Opportunity_IDs list all opps for facility (pipe-separated).
-- Excludes: kitchen_type_detail = 'cloudretail'. Stage: Approved + Closed Won.
-- Use: Run in BigQuery; or set app secrets bigquery_master_kitchens with project_id + query (or query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql").
-- =============================================================================

SELECT
  COALESCE(Acc.account_name, Fac.facility_name)         AS Account_Name,
  Kitch.facility_country                               AS Facility_Country,
  Kitch.kitchen_type                                   AS Type,
  Kitch.kitchen_category                               AS Category,
  Kitch.kitchen_id_18                                  AS Kitchen_Number_ID_18,
  Kitch.kitchen_full_name                              AS Kitchen_Number_Name,
  Kitch.status                                         AS Status,
  Acc.account_status                                   AS Account_Status,
  Kitch.kitchen_size_sqm                               AS Kitchen_Size_Sq_Meters,
  Kitch.kitchen_hood_size                              AS Hood_Size,
  Kitch.kichen_floor_price_local_currency              AS Floor_Price,
  Kitch.msrp                                           AS MSRP,
  Kitch.kitchen_activation_fee                         AS Activation_Fee,
  Opp.opportunity_id_18                                AS Opportunity_ID_18,
  Opp.opportunity_name                                 AS Opportunity_Name,
  Opp.opportunity_owner                                AS Opportunity_Owner_Full_Name,
  Opp.stage_name                                       AS Opportunity_Stage,
  Opp.deal_type                                        AS Deal_Type,
  CAST(NULL AS STRING)                                 AS Floor,
  Opp.churn_date                                       AS Churn_Date,
  Opp.facility_go_live_date                            AS Go_Live_Date,
  Opp.facility_go_live_at_cw                           AS Go_Live_At_CW,
  CASE WHEN Opp.facility_go_live_date IS NOT NULL AND Opp.facility_go_live_date <= CURRENT_DATE() THEN TRUE ELSE FALSE END AS Is_Live,
  OppAll.All_Opportunity_Names                         AS All_Opportunity_Names,
  OppAll.All_Opportunity_IDs                           AS All_Opportunity_IDs
FROM `css-operations.sales.sf_kitchens` Kitch
LEFT JOIN sales.global_countries country ON Kitch.facility_country = country.country
LEFT JOIN `css-operations.sales.sf_facilities` Fac ON Fac.facility_id = Kitch.facility_id_18
LEFT JOIN `css-operations.sales.sf_accounts` Acc ON Acc.account_name = Fac.facility_name
LEFT JOIN (
  SELECT facility_id, churn_date, opportunity_id_18, opportunity_name, opportunity_owner,
         facility_go_live_date, facility_go_live_at_cw, stage_name, deal_type
  FROM `css-operations.sales.sf_opportunities`
  WHERE facility_country IN ('Saudi Arabia', 'Bahrain')
    AND LOWER(TRIM(COALESCE(stage_name, ''))) IN ('approved', 'closed won')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY facility_id ORDER BY churn_date DESC NULLS LAST) = 1
) Opp ON Opp.facility_id = Fac.facility_id
LEFT JOIN (
  SELECT
    facility_id,
    REGEXP_REPLACE(STRING_AGG(TRIM(COALESCE(opportunity_name, '')), ' | ' ORDER BY churn_date DESC NULLS LAST), r' \| $', '') AS All_Opportunity_Names,
    REGEXP_REPLACE(STRING_AGG(TRIM(COALESCE(opportunity_id_18, '')), ' | ' ORDER BY churn_date DESC NULLS LAST), r' \| $', '') AS All_Opportunity_IDs
  FROM `css-operations.sales.sf_opportunities`
  WHERE facility_country IN ('Saudi Arabia', 'Bahrain')
    AND LOWER(TRIM(COALESCE(stage_name, ''))) IN ('approved', 'closed won')
  GROUP BY facility_id
) OppAll ON OppAll.facility_id = Fac.facility_id
WHERE Kitch.facility_country IN ('Saudi Arabia', 'Bahrain')
  AND TRIM(UPPER(COALESCE(Kitch.kitchen_full_name, ''))) LIKE 'K%'
  AND (COALESCE(TRIM(Kitch.kitchen_full_name), '') = '' OR LOWER(TRIM(Kitch.kitchen_full_name)) NOT LIKE '%deprecated%')
  AND LOWER(TRIM(COALESCE(Kitch.kitchen_type_detail, ''))) != 'cloudretail';
