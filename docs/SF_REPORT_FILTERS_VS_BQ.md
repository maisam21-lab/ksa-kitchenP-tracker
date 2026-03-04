# SF Report 00O6T000006Y0l6UAC — Filters vs BigQuery Master Kitchens

Report: **SF Kitchen Data - KSA**  
URL: `https://cloudkitchens.lightning.force.com/lightning/r/Report/00O6T000006Y0l6UAC/view`

## SF report filters (INCLUDE ROWS MATCHING 1–8)

| # | SF filter | BigQuery Master Kitchens (SA/BH) |
|---|-----------|----------------------------------|
| 1 | **Country** equals Bahrain, Saudi Arabia | ✓ `facility_country IN ('Saudi Arabia', 'Bahrain')` (kitchens + opportunities) |
| 2 | **Account Record Type** equals Facility | ⚠ Not applied in BQ. If `sf_accounts` has `record_type` or `record_type_developer_name`, add e.g. `AND Acc.record_type = 'Facility'` (or the correct value) in `base_kitchens`. |
| 3 | **Kitchen Number Name** starts with K | ✓ `TRIM(UPPER(COALESCE(Kitch.kitchen_full_name, ''))) LIKE 'K%'` |
| 4 | **Churn Date** equals "" | ⚠ In SF this usually means “Churn Date is empty”. In the query this is **not** applied by default (so we include all Approved/Closed Won opps). To match SF exactly, in `opp_base` uncomment: `AND (churn_date IS NULL OR TRIM(CAST(churn_date AS STRING)) = '')`. Note: your earlier SF export had non-empty Churn Date values; if the report really shows only empty Churn Date, that export may be from a different view. |
| 5 | **Kitchen Number Name** not equal to "" | ✓ Handled by COALESCE/TRIM and the “starts with K” / “not deprecated” logic (non-empty names only). |
| 6 | **Stage** equals Approved, Closed Won | ✓ `LOWER(TRIM(COALESCE(stage_name, ''))) IN ('approved', 'closed won')` in `opp_base` |
| 7 | **Type** not equal to CloudRetail | ✓ `LOWER(TRIM(COALESCE(Kitch.kitchen_type_detail, ''))) != 'cloudretail'` in `base_kitchens` |
| 8 | **Kitchen Number Name** does not contain Deprecated | ✓ `LOWER(TRIM(Kitch.kitchen_full_name)) NOT LIKE '%deprecated%'` in `base_kitchens` |

## Summary

- **Already aligned:** 1, 3, 5, 6, 7, 8.
- **Optional / confirm in SF:** 2 (Account Record Type), 4 (Churn Date empty).

After you confirm how “Churn Date equals ""” and “Account Record Type = Facility” should behave, the query can be updated to match exactly.
