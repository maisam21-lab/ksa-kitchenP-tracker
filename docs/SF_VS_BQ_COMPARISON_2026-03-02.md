# SF Kitchen Data vs BigQuery Master Kitchens — Comparison

**Date:** 2026-03-02  
**SF source:** `SF Kitchen Data - KSA-2026-03-02-15-54-21.xlsx` (online tracker export)  
**BQ source:** `bquxjob_11618b3b_19cae403abd.csv` (Master Kitchens SA/BH query export)

---

## Row counts

| Source | Rows (with Kitchen ID) |
|--------|------------------------|
| SF (online tracker) | 1,000 |
| BQ query (one opp per facility) | 999 |

**Difference:** 1 row.

---

## Kitchen with 2 opportunities in SF: `a1LVO000004Kx6T2AS`

**Kitchen:** K36 (Cold) - BH - MAN - UAH

### SF (online tracker) — 2 rows (one per opportunity)

| Opportunity ID 18   | Opportunity Name            |
|---------------------|-----------------------------|
| 006VO00000QaaE9YAJ  | DN Gulf (UAH K36)           |
| 006VO00000ckPvCYAU  | D'PEARL CAFÉ HOUSE OF BOBA |

### BQ query (current export) — 1 row

| Opportunity ID 18   | Opportunity Name   |
|---------------------|---------------------|
| 006VO00000Oy13RYAR  | Wolly's Italian UAH |

So in BQ the query’s “one opportunity per facility” (by latest churn_date) picked **Wolly's Italian UAH**. The two opportunities shown in SF (**DN Gulf** and **D'PEARL CAFÉ**) are different; they may be other approved/closed-won opportunities for the same facility that are not chosen as the single row in BQ.

---

## Why the discrepancy?

1. **One row per facility in BQ**  
   The query uses `QUALIFY ROW_NUMBER() ... = 1` so it returns **one** opportunity per facility (the one with latest churn_date). So kitchen `a1LVO000004Kx6T2AS` appears **once** in the BQ export.

2. **SF report shows one row per opportunity**  
   The SF report can show the same kitchen multiple times when it has multiple opportunities, so you get **two** rows for this kitchen in the Excel.

3. **Different opportunity chosen**  
   BQ’s single row shows “Wolly's Italian UAH”; SF’s two rows show “DN Gulf” and “D'PEARL CAFÉ”. So either:
   - SF and BQ data/sync differ (e.g. stage, churn_date, or which opps are in BQ), or  
   - The “primary” opp in BQ (by churn_date) is a third opportunity not shown in the SF export you used.

---

## What you can do

### Option A — Keep ~999 rows and see all opp names in one cell

Use the **current** BigQuery Master Kitchens query that has:

- **Opp** join: one row per facility (QUALIFY, primary opp by latest churn_date).
- **OppAll** join: `All_Opportunity_Names` = `STRING_AGG(opportunity_name, ' | ')` for that facility.

Re-run the query and export again. The CSV will have a column **All_Opportunity_Names**. For kitchen `a1LVO000004Kx6T2AS` that column should list all approved/closed-won opportunity names for the facility (e.g. `Wolly's Italian UAH | DN Gulf (UAH K36) | D'PEARL CAFÉ HOUSE OF BOBA` or similar, depending on what’s in BQ). You still get one row per kitchen (~999 rows).

**Note:** The CSV you shared does **not** contain `All_Opportunity_Names`, so it was likely exported from an older version of the query. Re-export using the latest query in `docs/BIGQUERY_MASTER_KITCHENS_SALES_SA_BH.sql`.

### Option B — Match SF: two rows for this kitchen (one per opportunity)

Remove the `QUALIFY ROW_NUMBER() ... = 1` from the opportunities subquery so the query returns **all** approved/closed-won opportunities per facility. Then the same kitchen will appear **multiple rows** when it has multiple opportunities (like in SF). Total rows will increase (e.g. from ~999 to ~1000+). If you want this, we can change the saved query to this “all opportunities” version.

---

## Summary

- **SF:** 1,000 rows; kitchen `a1LVO000004Kx6T2AS` has 2 rows (DN Gulf, D'PEARL CAFÉ).  
- **BQ (current export):** 999 rows; same kitchen has 1 row (Wolly's Italian UAH).  
- To see **all** opportunities for that kitchen in BQ without changing row count: use the **current** query and check **All_Opportunity_Names** in the new export.  
- To get **two rows** for that kitchen (like SF): use the “all opportunities” query (no QUALIFY).
