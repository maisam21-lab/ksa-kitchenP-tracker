-- BigQuery examples — sales.sf_opportunities + sales.global_countries
-- Reference schema for churn, facility, and region. Use for KSA/Listco or CSS.
-- (Source: internal dbt_sales-style queries.)

-- =============================================================================
-- Schema reference
-- =============================================================================
-- sales.sf_opportunities: churn_date, closed_won, closed_won_date, kitchen_type,
--   kitchen_type_cleaned, transfer_churn, opp_team, facility_id, facility_country, ...
-- sales.sf_kitchens: kitchen-level data; join to global_countries on facility_country = country.country
-- sales.global_countries: country, megaregion, company, region_sales_reporting
-- Canonical place for SA/BH kitchen data: css-operations.sales (sf_kitchens + global_countries).
--
-- Join: opps.facility_country = country.country
-- company: 'CSS' | 'Listco' (etc.)
-- KSA/EMEA: facility_country in ('Saudi Arabia', 'Bahrain', 'UAE', ...)

-- =============================================================================
-- SA/BH only — SELECT * from sf_opportunities (facility name starts with SA or BH)
-- =============================================================================
SELECT *
FROM `css-operations.sales.sf_opportunities` opps
WHERE opps.facility_name LIKE 'SA%' OR opps.facility_name LIKE 'BH%';
-- If the column is facility_id (e.g. "SA - RUH - Qurtoba"), use:
-- WHERE opps.facility_id LIKE 'SA%' OR opps.facility_id LIKE 'BH%'

-- =============================================================================
-- SA/BH — SELECT * from sf_kitchens (filter by country_code; this is working)
-- =============================================================================
select *
from `css-operations.sales.sf_kitchens` Kitch
left join
	sales.global_countries country
on
	Kitch.facility_country = country.country
where
	country.country in ('Saudi Arabia', 'Bahrain');

-- =============================================================================
-- SA/BH — SELECT * from sf_kitchens (working)
-- =============================================================================
select *
from `css-operations.sales.sf_kitchens` Kitch
left join
	sales.global_countries country
on
	Kitch.facility_country = country.country
where
	country.country in ('Saudi Arabia', 'Bahrain');

-- =============================================================================
-- SA/BH — Kitchens + facility + account + opportunity churn only (one row per facility)
-- =============================================================================
select *
from `css-operations.sales.sf_kitchens` Kitch
left join
	sales.global_countries country
on
	Kitch.facility_country = country.country
left join
	`css-operations.sales.sf_facilities` Fac
on
	Fac.facility_country = Kitch.facility_country
left join
	`css-operations.sales.sf_accounts` Acc
on
	Acc.account_name = Fac.facility_name
left join
	(
		select facility_id, churn_date, closed_won, closed_won_date,
		       date_trunc(churn_date, month) as churn_month
		from `css-operations.sales.sf_opportunities`
		where facility_country in ('Saudi Arabia', 'Bahrain')
		qualify row_number() over (partition by facility_id order by churn_date desc nulls last) = 1
	) Opp
on
	Opp.facility_id = Fac.facility_id
where
	country.country in ('Saudi Arabia', 'Bahrain');
-- If Acc.Id fails, get sf_accounts columns: SELECT column_name FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = 'sf_accounts';

-- =============================================================================
-- Find where SF, retail, SF_update columns live (run in BigQuery)
-- =============================================================================
-- Run each query below; check the column_name results to see which table has SF, retail, SF_update.

-- (1) sf_kitchens
SELECT 'sf_kitchens' AS table_name, column_name, data_type
FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'sf_kitchens'
  AND LOWER(column_name) IN ('sf', 'retail', 'sf_update')
ORDER BY column_name;

-- (2) sf_facilities
SELECT 'sf_facilities' AS table_name, column_name, data_type
FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'sf_facilities'
  AND LOWER(column_name) IN ('sf', 'retail', 'sf_update')
ORDER BY column_name;

-- (3) sf_accounts
SELECT 'sf_accounts' AS table_name, column_name, data_type
FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'sf_accounts'
  AND LOWER(column_name) IN ('sf', 'retail', 'sf_update')
ORDER BY column_name;

-- (4) sf_opportunities
SELECT 'sf_opportunities' AS table_name, column_name, data_type
FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'sf_opportunities'
  AND LOWER(column_name) IN ('sf', 'retail', 'sf_update')
ORDER BY column_name;

-- (5) All tables in sales: list every column that contains 'sf', 'retail', or 'update'
SELECT table_name, column_name, data_type
FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS`
WHERE LOWER(column_name) LIKE '%sf%'
   OR LOWER(column_name) LIKE '%retail%'
   OR LOWER(column_name) LIKE '%update%'
ORDER BY table_name, column_name;

-- =============================================================================
-- DIAGNOSTIC: Why did SF Churn Data return no rows? Run these to see actual values.
-- =============================================================================
-- (A) Distinct status values in sf_kitchens for Saudi Arabia & Bahrain (use exact values in the main query):
-- SELECT Kitch.status, COUNT(*) AS cnt
-- FROM `css-operations.sales.sf_kitchens` Kitch
-- LEFT JOIN sales.global_countries country ON Kitch.facility_country = country.country
-- WHERE country.country IN ('Saudi Arabia', 'Bahrain')
-- GROUP BY 1 ORDER BY 2 DESC;

-- (B) Do we have any SA/BH kitchens at all? (no status or name filter):
-- SELECT COUNT(*) FROM `css-operations.sales.sf_kitchens` Kitch
-- LEFT JOIN sales.global_countries country ON Kitch.facility_country = country.country
-- WHERE country.country IN ('Saudi Arabia', 'Bahrain');

-- (C) First character of kitchen_full_name (do names start with K or something else?):
-- SELECT LEFT(TRIM(Kitch.kitchen_full_name), 1) AS first_char, COUNT(*) AS cnt
-- FROM `css-operations.sales.sf_kitchens` Kitch
-- LEFT JOIN sales.global_countries country ON Kitch.facility_country = country.country
-- WHERE country.country IN ('Saudi Arabia', 'Bahrain') AND TRIM(Kitch.kitchen_full_name) <> ''
-- GROUP BY 1 ORDER BY 2 DESC;

-- =============================================================================
-- SA/BH — SF Churn Data (filters 1–8; Account type = Facility and Churn Date = empty removed — data not matching)
-- 1. Country = Bahrain, Saudi Arabia
-- 6. Stage (Opportunity) = Approved, Closed Won
-- (CloudRetail not excluded: Type and Deal_Type can show CloudRetail)
-- sf_kitchens columns used: kitchen_id_18, kitchen_full_name, kitchen_type, kitchen_category, ...
-- If column names differ (e.g. account_type for Facility, stage_name/deal_type on sf_opportunities), adjust below.
-- =============================================================================
select
	coalesce(Acc.account_name, Fac.facility_name)        as Account_Name,
	Kitch.facility_country                             as Facility_Country,
	Kitch.kitchen_type                  as Kitchen_Type,
	lower(trim(coalesce(Kitch.kitchen_type, ''))) like '%cloud retail%' as Is_Cloud_Retail_Type,
	Opp.kitchen_type                  as Kitchen_Type_1,
	Kitch.kitchen_type_detail          as Kitchen_Type_Detail,
	Kitch.kitchen_category              as Category,
	Kitch.kitchen_id_18                 as Kitchen_Number_ID_18,
	Kitch.kitchen_full_name             as Kitchen_Number_Name,
	Kitch.status                        as Status,
	Acc.account_status                  as Account_Status,
	Kitch.kitchen_size_sqm              as Kitchen_Size_Sq_Meters,
	Kitch.kitchen_hood_size             as Hood_Size,
	Kitch.kichen_floor_price_local_currency as Floor_Price,
	Kitch.msrp                          as MSRP,
	Kitch.kitchen_activation_fee        as Activation_Fee,
	Opp.opportunity_id_18               as Opportunity_ID_18,
	Opp.opportunity_name                as Opportunity_Name,
	Opp.opportunity_owner               as Opportunity_Owner_Full_Name,
	Opp.stage_name                      as Opportunity_Stage,
	Opp.deal_type                       as Deal_Type,
	cast(null as string)                as Floor,
	Opp.churn_date                      as Churn_Date,
	Opp.facility_go_live_date           as Go_Live_Date,
	Opp.facility_go_live_at_cw          as Go_Live_At_CW,
	case when Opp.facility_go_live_date is not null and Opp.facility_go_live_date <= current_date() then true else false end as Is_Live
from `css-operations.sales.sf_kitchens` Kitch
left join sales.global_countries country on Kitch.facility_country = country.country
left join `css-operations.sales.sf_facilities` Fac on Fac.facility_id = Kitch.facility_id_18
left join `css-operations.sales.sf_accounts` Acc on Acc.account_name = Fac.facility_name
left join
	(
		select facility_id, churn_date, opportunity_id_18, opportunity_name, opportunity_owner,
		       facility_go_live_date, facility_go_live_at_cw, stage_name, deal_type, kitchen_type
		from `css-operations.sales.sf_opportunities`
		where facility_country in ('Saudi Arabia', 'Bahrain')
		  and lower(trim(coalesce(stage_name, ''))) in ('approved', 'closed won')
		  and lower(trim(coalesce(kitchen_type_cleaned, ''))) = 'delivery'
		  and lower(trim(coalesce(kitchen_type, ''))) = 'delivery'
		qualify row_number() over (partition by facility_id order by churn_date desc nulls last) = 1
	) Opp
on Opp.facility_id = Fac.facility_id
where Kitch.facility_country in ('Saudi Arabia', 'Bahrain')
  and trim(upper(coalesce(Kitch.kitchen_full_name, ''))) like 'K%'
  and (coalesce(trim(Kitch.kitchen_full_name), '') = '' or lower(trim(Kitch.kitchen_full_name)) not like '%deprecated%')
  and (Kitch.kitchen_type is null or lower(trim(coalesce(Kitch.kitchen_type, ''))) not like '%cloud retail%')
  and (Kitch.kitchen_type is null or lower(trim(coalesce(Kitch.kitchen_type, ''))) not like '%commissary%')
  and (Kitch.kitchen_type_detail is null or lower(trim(coalesce(Kitch.kitchen_type_detail, ''))) not like '%cloudkitchen%');
-- Excludes Deprecated in kitchen name; kitchen_type excluding Cloud Retail and Commissary; kitchen_type_detail excluding cloudkitchen.
-- Only Delivery: kitchen_type_cleaned and kitchen_type (output as Kitchen_Type_1) both = 'delivery' in Opp subquery.
-- To list sf_opportunities columns: SELECT column_name FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = 'sf_opportunities' AND LOWER(column_name) LIKE '%kitchen%type%';
-- Verify row count as needed. To align with SF export, see "Discrepancy" section below for diff/IN list options.
-- SELECT COUNT(*) AS row_count FROM ( ... paste the SELECT from above, closing with ) t;

-- =============================================================================
-- SA/BH — SF Churn Data WITHOUT status or "starts with K" filter (use to get rows and inspect Status / names)
-- =============================================================================
-- If the query above returns 0 rows, run this one (same SELECT, only country filter). Then check Status and
-- Kitchen_Number_Name in the result; update the main query's IN list and LIKE to match your data.
/*
select
	Acc.account_name                    as Account_Name,
	Kitch.kitchen_type                  as Type,
	Kitch.kitchen_category              as Category,
	Kitch.kitchen_id_18                 as Kitchen_Number_ID_18,
	Kitch.kitchen_full_name             as Kitchen_Number_Name,
	Kitch.status                        as Status,
	Kitch.kitchen_size_sqm              as Kitchen_Size_Sq_Meters,
	Kitch.kitchen_hood_size             as Hood_Size,
	Kitch.kichen_floor_price_local_currency as Floor_Price,
	Kitch.msrp                          as MSRP,
	Kitch.kitchen_activation_fee        as Activation_Fee,
	cast(null as string)                as Opportunity_ID_18,
	cast(null as string)                as Opportunity_Name,
	cast(null as string)                as Opportunity_Owner_Full_Name,
	cast(null as string)                as Floor,
	Opp.churn_date                      as Churn_Date
from `css-operations.sales.sf_kitchens` Kitch
left join sales.global_countries country on Kitch.facility_country = country.country
left join `css-operations.sales.sf_facilities` Fac on Fac.facility_id = Kitch.facility_id_18
left join `css-operations.sales.sf_accounts` Acc on Acc.account_name = Fac.facility_name
left join ( select facility_id, churn_date from `css-operations.sales.sf_opportunities` where facility_country in ('Saudi Arabia', 'Bahrain') qualify row_number() over (partition by facility_id order by churn_date desc nulls last) = 1 ) Opp on Opp.facility_id = Fac.facility_id
where country.country in ('Saudi Arabia', 'Bahrain');
*/
-- Verify row count (expected ~1,002):
-- SELECT COUNT(*) AS row_count FROM ( ... paste the SELECT from above, closing with ) t;
-- Optional: add SF/retail/SF_update filter from the table that has them (run the "Find where SF, retail, SF_update" queries above):
-- e.g. AND (Fac.SF is true or Fac.retail is false) and Fac.SF_update is true
-- If the column is named differently, list with:
-- SELECT column_name FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = 'sf_kitchens'
-- then replace Kitch.status above (e.g. Kitch.kitchen_status or Kitch.kitchen_number_status).
-- To add Opportunity ID/Name/Owner/Floor: list columns with
-- SELECT column_name FROM `css-operations.sales.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = 'sf_opportunities'
-- then add them to the Opp subquery and use Opp.opportunity_id_18 etc. in the SELECT above.

-- =============================================================================
-- Discrepancy: BQ vs Salesforce — compare both sets to find extra/missing kitchens
-- =============================================================================
-- Diff run 2026-02-26: BQ export (bquxjob_*.csv) vs SF export (SF Kitchen Data - KSA-*.xlsx, sheet "SF Kitchen Data - KSA", header row 16).
-- Compare on Kitchen_Number_ID_18 (BQ) / "Kitchen Number ID 18" (SF). Result: 8 in BQ not in SF (excluded via NOT IN above); 1 in SF not in BQ (a1LVO000005MsV72AK).
-- To refresh: export both, then in Python: read BQ CSV and SF Excel (header=16), diff sets of kitchen IDs, update the NOT IN list in the main query.
-- When you have both exports:
-- 1. BQ: run the main SF Churn query and export Kitchen_Number_ID_18 (or kitchen_id_18) and Kitchen_Number_Name.
-- 2. SF: export the same identifiers from the Salesforce churn report (Excel header row 16; column "Kitchen Number ID 18").
-- 3. Compare:
--    - In BQ but not in SF = extra kitchens. Add: AND Kitch.kitchen_id_18 NOT IN ('id1',...)
--    - In SF but not in BQ = missing kitchens; check if they fail our filters (country, K%, deprecated, cloud retail, opp stage).
-- 4. Optional: load SF list into a temp table or use a CASE/IN list to restrict BQ to only kitchen_id_18 that exist in SF.
-- Example (after you have the SF kitchen IDs in a table or list):
--   AND Kitch.kitchen_id_18 IN (SELECT kitchen_id FROM temp_salesforce_churn_kitchens)
--   or AND Kitch.kitchen_id_18 NOT IN ('extra1','extra2',...)
-- =============================================================================

-- =============================================================================
-- TEST: All records and all columns for the 8 kitchen IDs (in BQ but not in SF export)
-- =============================================================================
-- Run in BigQuery to inspect every column from kitchens, facility, account, and opportunity.
-- Replace the project/dataset if your sales dataset lives elsewhere.

SELECT
  Kitch.*,
  Fac.* EXCEPT (facility_country),
  Acc.* EXCEPT (account_name),
  Opp.*
FROM `css-operations.sales.sf_kitchens` Kitch
LEFT JOIN `css-operations.sales.sf_facilities` Fac
  ON Fac.facility_id = Kitch.facility_id_18
LEFT JOIN `css-operations.sales.sf_accounts` Acc
  ON Acc.account_name = Fac.facility_name
LEFT JOIN (
  SELECT *
  FROM `css-operations.sales.sf_opportunities`
  WHERE facility_country IN ('Saudi Arabia', 'Bahrain')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY facility_id ORDER BY churn_date DESC NULLS LAST) = 1
) Opp
  ON Opp.facility_id = Fac.facility_id
WHERE Kitch.kitchen_id_18 IN (
  'a1L5G000004NedAUAS', 'a1L5G000004O0LgUAK', 'a1L5G000004Tzk6UAC', 'a1L5G000004TzlsUAC',
  'a1L6T00000iJdvVUAS', 'a1L6T00000jqkp8UAA', 'a1L6T00000jr3ncUAA', 'a1L6T00000nGqVMUA0'
);

-- If EXCEPT causes errors (duplicate names across tables), use this version to get all columns
-- as separate result sets (run each block separately), or use SELECT * from each table below.

-- (A) All columns from sf_kitchens only (8 rows):
-- SELECT * FROM `css-operations.sales.sf_kitchens`
-- WHERE kitchen_id_18 IN (
--   'a1L5G000004NedAUAS', 'a1L5G000004O0LgUAK', 'a1L5G000004Tzk6UAC', 'a1L5G000004TzlsUAC',
--   'a1L6T00000iJdvVUAS', 'a1L6T00000jqkp8UAA', 'a1L6T00000jr3ncUAA', 'a1L6T00000nGqVMUA0'
-- );

-- (B) All columns from sf_facilities for those kitchens' facilities:
-- SELECT Fac.* FROM `css-operations.sales.sf_kitchens` Kitch
-- JOIN `css-operations.sales.sf_facilities` Fac ON Fac.facility_id = Kitch.facility_id_18
-- WHERE Kitch.kitchen_id_18 IN (
--   'a1L5G000004NedAUAS', 'a1L5G000004O0LgUAK', 'a1L5G000004Tzk6UAC', 'a1L5G000004TzlsUAC',
--   'a1L6T00000iJdvVUAS', 'a1L6T00000jqkp8UAA', 'a1L6T00000jr3ncUAA', 'a1L6T00000nGqVMUA0'
-- );

-- (C) All columns from sf_accounts for those facilities' accounts:
-- SELECT Acc.* FROM `css-operations.sales.sf_kitchens` Kitch
-- JOIN `css-operations.sales.sf_facilities` Fac ON Fac.facility_id = Kitch.facility_id_18
-- JOIN `css-operations.sales.sf_accounts` Acc ON Acc.account_name = Fac.facility_name
-- WHERE Kitch.kitchen_id_18 IN (
--   'a1L5G000004NedAUAS', 'a1L5G000004O0LgUAK', 'a1L5G000004Tzk6UAC', 'a1L5G000004TzlsUAC',
--   'a1L6T00000iJdvVUAS', 'a1L6T00000jqkp8UAA', 'a1L6T00000jr3ncUAA', 'a1L6T00000nGqVMUA0'
-- );

-- (D) All columns from sf_opportunities (latest opp per facility) for those facilities:
-- SELECT Opp.* FROM `css-operations.sales.sf_kitchens` Kitch
-- JOIN `css-operations.sales.sf_facilities` Fac ON Fac.facility_id = Kitch.facility_id_18
-- JOIN (
--   SELECT * FROM `css-operations.sales.sf_opportunities`
--   WHERE facility_country IN ('Saudi Arabia', 'Bahrain')
--   QUALIFY ROW_NUMBER() OVER (PARTITION BY facility_id ORDER BY churn_date DESC NULLS LAST) = 1
-- ) Opp ON Opp.facility_id = Fac.facility_id
-- WHERE Kitch.kitchen_id_18 IN (
--   'a1L5G000004NedAUAS', 'a1L5G000004O0LgUAK', 'a1L5G000004Tzk6UAC', 'a1L5G000004TzlsUAC',
--   'a1L6T00000iJdvVUAS', 'a1L6T00000jqkp8UAA', 'a1L6T00000jr3ncUAA', 'a1L6T00000nGqVMUA0'
-- );

-- =============================================================================
-- Which account column has 'Facility'? (run to see distinct values)
-- =============================================================================
-- SELECT Acc.account_type, Acc.account_segment_type, Acc.account_segment_type_short, COUNT(*) AS cnt
-- FROM `css-operations.sales.sf_kitchens` Kitch
-- LEFT JOIN `css-operations.sales.sf_facilities` Fac ON Fac.facility_id = Kitch.facility_id_18
-- LEFT JOIN `css-operations.sales.sf_accounts` Acc ON Acc.account_name = Fac.facility_name
-- WHERE Kitch.facility_country IN ('Saudi Arabia', 'Bahrain')
-- GROUP BY 1, 2, 3 ORDER BY 4 DESC;

-- =============================================================================
-- SA/BH — Facility details only (sf_facilities + global_countries)
-- =============================================================================
select *
from `css-operations.sales.sf_facilities` Fac
left join
	sales.global_countries country
on
	Fac.facility_country = country.country
where
	country.country in ('Saudi Arabia', 'Bahrain');

-- =============================================================================
-- Example 1: CSS — churn view (all closed-won Delivery, active regions)
-- =============================================================================
/*
SELECT
  *,
  CAST(DATE_TRUNC(churn_date, MONTH) AS DATE) AS churn_month,
  country.megaregion AS facility_megaregion
FROM sales.sf_opportunities opps
LEFT JOIN sales.global_countries country
  ON opps.facility_country = country.country
WHERE opps.closed_won
  AND kitchen_type_cleaned = 'Delivery'
  AND NOT transfer_churn
  AND (kitchen_type NOT LIKE '%daily/weekly rental%' OR kitchen_type IS NULL)
  AND facility_id IS NOT NULL
  AND country.company = 'CSS'
  AND country.region_sales_reporting <> 'Inactive';
*/

-- =============================================================================
-- Example 1b: Same as above — SA and Bahrain only (facility name starts with SA or BH)
-- =============================================================================
/*
SELECT
  *,
  CAST(DATE_TRUNC(churn_date, MONTH) AS DATE) AS churn_month,
  country.megaregion AS facility_megaregion
FROM sales.sf_opportunities opps
LEFT JOIN sales.global_countries country
  ON opps.facility_country = country.country
WHERE opps.closed_won
  AND kitchen_type_cleaned = 'Delivery'
  AND NOT transfer_churn
  AND (kitchen_type NOT LIKE '%daily/weekly rental%' OR kitchen_type IS NULL)
  AND facility_id IS NOT NULL
  AND country.company = 'CSS'
  AND country.region_sales_reporting <> 'Inactive'
  AND (opps.facility_name LIKE 'SA%' OR opps.facility_name LIKE 'BH%');
*/

-- =============================================================================
-- "No data" for SA/BH? Run these to see what exists, then fix the filter.
-- =============================================================================
-- (1) What facility_country values look like SA/BH?
-- SELECT DISTINCT opps.facility_country
-- FROM sales.sf_opportunities opps
-- WHERE LOWER(opps.facility_country) LIKE '%saudi%'
--    OR LOWER(opps.facility_country) LIKE '%bahrain%'
--    OR LOWER(opps.facility_country) LIKE 'sa %'
--    OR opps.facility_country IN ('SA', 'BH', 'KSA');
--
-- (2) For those countries, what is company and region_sales_reporting?
-- SELECT country.country, country.company, country.region_sales_reporting
-- FROM sales.global_countries country
-- WHERE country.country IN ('Saudi Arabia', 'Bahrain', 'SA', 'BH', 'KSA');
--
-- (3) Relaxed SA/BH: filter by facility name starting with SA or BH (no country/company)
/*
SELECT
  *,
  CAST(DATE_TRUNC(churn_date, MONTH) AS DATE) AS churn_month,
  country.megaregion AS facility_megaregion
FROM sales.sf_opportunities opps
LEFT JOIN sales.global_countries country
  ON opps.facility_country = country.country
WHERE opps.closed_won
  AND kitchen_type_cleaned = 'Delivery'
  AND NOT transfer_churn
  AND (kitchen_type NOT LIKE '%daily/weekly rental%' OR kitchen_type IS NULL)
  AND facility_id IS NOT NULL
  AND (opps.facility_name LIKE 'SA%' OR opps.facility_name LIKE 'BH%');
*/
-- If no facility_name column: use (opps.facility_id LIKE 'SA%' OR opps.facility_id LIKE 'BH%')

-- =============================================================================
-- Example 2: Listco — churn by month and country (e.g. UAE, Jan 2026)
-- =============================================================================
/*
SELECT
  kitchen_type,
  *,
  CAST(DATE_TRUNC(churn_date, MONTH) AS DATE) AS churn_month,
  country.megaregion AS facility_megaregion
FROM sales.sf_opportunities opps
LEFT JOIN sales.global_countries country
  ON opps.facility_country = country.country
WHERE opps.closed_won
  AND kitchen_type_cleaned = 'Delivery'
  AND NOT transfer_churn
  AND (kitchen_type NOT LIKE '%daily/weekly rental%' OR kitchen_type IS NULL)
  AND facility_id IS NOT NULL
  AND country.company = 'Listco'
  AND country.region_sales_reporting <> 'Inactive'
  AND CAST(DATE_TRUNC(churn_date, MONTH) AS DATE) = DATE(2026, 1, 1)
  AND facility_country = 'UAE';
*/

-- =============================================================================
-- KSA / Bahrain — same pattern, filter by facility_country
-- =============================================================================
-- For KSA Kitchens Tracker, restrict to Saudi Arabia and/or Bahrain:
--   AND facility_country IN ('Saudi Arabia', 'Bahrain')
-- and use company = 'Listco' (or the value that corresponds to your region).
--
-- To get "live" vs "not live": if your warehouse has a facility/account table
-- with a go-live date, join that (see BIGQUERY_KITCHEN_GO_LIVE.sql).
-- If "live" is defined by closed_won opportunities, you can derive it from
-- sf_opportunities (e.g. facility_id has at least one closed_won = live).

-- =============================================================================
-- SA + BH — All kitchens with go-live date (for tracker go-live merge)
-- =============================================================================
-- One row per facility in Saudi Arabia and Bahrain with go_live_date and is_live.
-- Output columns: kitchen_number, account_name, go_live_date, is_live (required by app).
-- go_live_date = earliest closed_won_date for that facility. If your table has
-- facility_name or account_name, add them to SELECT/GROUP BY and use for account_name.

SELECT
  opps.facility_id AS kitchen_number,
  opps.facility_id AS account_name,
  MIN(CASE WHEN opps.closed_won THEN opps.closed_won_date END) AS go_live_date,
  (MIN(CASE WHEN opps.closed_won THEN opps.closed_won_date END) IS NOT NULL
   AND MIN(CASE WHEN opps.closed_won THEN opps.closed_won_date END) <= CURRENT_DATE()) AS is_live
FROM `css-operations.sales.sf_opportunities` opps
LEFT JOIN `css-operations.sales.global_countries` country
  ON opps.facility_country = country.country
WHERE opps.facility_id IS NOT NULL
  AND (opps.facility_name LIKE 'SA%' OR opps.facility_name LIKE 'BH%')
  AND (country.region_sales_reporting IS NULL OR country.region_sales_reporting <> 'Inactive')
GROUP BY opps.facility_id
ORDER BY opps.facility_id;

-- =============================================================================
-- Kitchen-level go-live (one row per kitchen: Account Name, Kitchen Number ID, Go Live Date)
-- =============================================================================
-- Use when your source has one row per kitchen with columns like:
--   Account Name (e.g. "SA - RUH - Malga (2)"), Kitchen Number ID 18, Go Live Date.
-- The app expects: kitchen_number, account_name, go_live_date (is_live is derived: go_live_date <= today).
-- Replace PROJECT_ID.DATASET_ID.table with your Kitchen_Number__c / staging kitchen table.
--
-- Example (alias columns to match app; BQ column names may differ):
/*
SELECT
  Kitchen_Number_ID_18__c  AS kitchen_number,
  Account_Name__c          AS account_name,
  FORMAT_DATE('%Y-%m-%d', DATE(Go_Live_Date__c)) AS go_live_date
FROM `PROJECT_ID.DATASET_ID.your_kitchen_table`
WHERE Account_Country__c IN ('Saudi Arabia', 'Bahrain')
   OR Account_Name__c LIKE 'SA - %'
   OR Account_Name__c LIKE 'BH - %'
ORDER BY account_name, kitchen_number;
*/
-- If your table already has headers "Account Name", "Kitchen Number ID 18", "Go Live Date",
-- the app will accept those names too (no need to alias).
