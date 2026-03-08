-- =============================================================================
-- Master Kitchens — SA/BH from css-operations.sales
-- Output: kitchen master columns only + is_live + stage_name
-- =============================================================================
-- Same joins as full query; Opp subquery returns only facility_id, stage_name,
-- and facility_go_live_date (used to compute is_live). No Opp.* so only
-- stage_name and is_live from opportunity side.
-- Use: Run in BigQuery; or set app secrets bigquery_master_kitchens with
--      query_file = "docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql".
-- =============================================================================

SELECT
  Kitch.*,
  Fac.* EXCEPT (facility_country),
  Acc.* EXCEPT (account_name),
  Opp.stage_name,
  -- is_live: facility is live when go-live date is on or before today (use closed_won_date if facility_go_live_date not in sf_opportunities)
  (Opp.facility_go_live_date IS NOT NULL AND Opp.facility_go_live_date <= CURRENT_DATE()) AS is_live
FROM `css-operations.sales.sf_kitchens` Kitch
LEFT JOIN `css-operations.sales.sf_facilities` Fac
  ON Fac.facility_id = Kitch.facility_id_18
LEFT JOIN `css-operations.sales.sf_accounts` Acc
  ON Acc.account_name = Fac.facility_name
LEFT JOIN (
  SELECT
    facility_id,
    stage_name,
    facility_go_live_date
  FROM `css-operations.sales.sf_opportunities`
  WHERE facility_country IN ('Saudi Arabia', 'Bahrain')
    AND LOWER(TRIM(COALESCE(stage_name, ''))) IN ('approved', 'closed won')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY facility_id
    ORDER BY
      CASE WHEN LOWER(TRIM(COALESCE(stage_name, ''))) = 'approved' THEN 0 ELSE 1 END,
      churn_date ASC NULLS LAST
  ) = 1
) Opp ON Opp.facility_id = Fac.facility_id
WHERE Kitch.facility_country IN ('Saudi Arabia', 'Bahrain')
  AND TRIM(UPPER(COALESCE(Kitch.kitchen_full_name, ''))) LIKE 'K%'
  AND (COALESCE(TRIM(Kitch.kitchen_full_name), '') = '' OR LOWER(TRIM(Kitch.kitchen_full_name)) NOT LIKE '%deprecated%')
  AND LOWER(TRIM(COALESCE(Kitch.kitchen_type_detail, ''))) != 'cloudretail';
