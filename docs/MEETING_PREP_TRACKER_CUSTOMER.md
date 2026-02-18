# Tracker customer call — progress, blockers, and product-shape questions

**Purpose:** Align on where we stand, unblock with the team, and understand each tab/use case so we can finalize the final product shape.

---

## 1. Where we stand (progress)

| Area | Status |
|------|--------|
| **App** | KSA Kitchen Tracker (Streamlit) is live with RBAC, Master Kitchens, Live Dashboard, Tools, Admin. |
| **Access** | Role-based: associates see Master Kitchens only; managers add Live Dashboard; super users see all (Tools, Admin, Data, Search). |
| **Master Kitchens** | Primary view: filters (status pills, facility, search), column picker, export. Data source selector for managers/super users. |
| **Data source (today)** | **Salesforce report by ID** (and Google Sheet backup) feeds the app. Report IDs configured for Kitchens, Master Kitchens list, SF Churn Data, and other tabs. |
| **Scheduled refresh** | Pipeline and GitHub Actions (every 15 min) are in place for a **Superset/Trino** path; app can read from persisted store when that path is populated. |
| **Warehouse (Trino / BigQuery)** | **Parked.** We built Trino and BigQuery queries for “Master Kitchens” (accounts + kitchen data), but we are **not reading from the right tables** for KSA (see Blockers). |

---

## 2. Blockers and what the team can do to assist

| Blocker | Detail | Who can help / what’s needed |
|--------|--------|------------------------------|
| **No KSA data in BigQuery staging** | `css-operations.us_ck_central_ops_bi` has **no Bahrain or Saudi Arabia** in account country. Data is Americas/UK. So BigQuery Master Kitchens returns 0 rows for KSA. | **Data/analytics:** Confirm where EMEA/APAC (KSA, Bahrain) Salesforce data lives in BigQuery (e.g. `ck_emea_apac_marketing` or another project/dataset). If it exists, we need project + dataset + table names to point the query there. |
| **Trino/Hudi kitchen link empty** | In Trino (`hudi_ingest.salesforce_cloudkitchens`), `opportunity.kitchen_number__c` is NULL for all rows, so we can’t join to kitchen dimension. Kitchen-level fields (Status, Size, etc.) all come back NULL. | **Data engineering / pipeline owner:** Ensure the Hudi sync populates **Opportunity → Kitchen_Number__c** (or that **Kitchen_Number__c** is the main table and is synced with Account/Opportunity). Until then, we can’t reliably serve Master Kitchens from Trino. |
| **Single source for KSA Master Kitchens** | Today the only reliable source for KSA (Bahrain, Saudi Arabia) Master Kitchens is **Salesforce report by ID** (or Google Sheet). Warehouse path is not ready. | **Product / customer:** Confirm that staying on **Salesforce report (and/or Sheet)** for KSA is acceptable until the right warehouse tables are available; or prioritize access to the correct BQ/Trino dataset. |

---

## 3. Questions to understand each tab and finalize product shape

Use these on the call to clarify **who uses what** and **for what**, so we can lock the final product (tabs to keep, rename, or drop; and which data source each should use).

### 3.1 Master Kitchens (main view)

- Who uses **Master Kitchens** day to day (e.g. sales, ops, leadership)?
- What do they do with it (e.g. list of live kitchens, status checks, export for reports)?
- Is the current **Salesforce report** (or Sheet) the source of truth they trust? Any pain points (freshness, filters, export)?

### 3.2 Kitchens vs Master Kitchens list

- **Kitchens** and **Master Kitchens list** both use the same Salesforce report today. Do we need **two** tabs, or one unified “Master Kitchens” view?
- If two: what should be different (e.g. filters, columns, audience)?

### 3.3 Data section — tabs and usage

For each tab below, ask: **Who uses it? For what? Can we keep / rename / remove?**

| Tab name | Suggested question |
|----------|--------------------|
| Auto Refresh Execution Log | Who looks at this? Ops only? Can it live only in Admin? |
| Sellable No Status | Which role uses it? What decision does it support? |
| All no status kitchens | Same as above; overlap with Sellable No Status? |
| LF Comp | Who uses it and for what? |
| Pivot Table 10 | Same. |
| Area Data | Same. |
| **SF Churn Data** | Who owns churn reporting? Should this be visible only to managers/super users? |
| KSA Facility details | Who uses it and for what? |
| Inflation FPx | Same. |
| Price Multipliers | Tied to super-user tool? Who else needs the tab? |
| Occupancy | Who uses it and for what? |
| Pivot Table 4 | Same. |
| Qurtoba / Jarir / Salam / Narjis / Aqrabiya / Zuhur / Hofuf (Old) | Are these legacy? Can we archive or remove to simplify the product? |

### 3.4 Live Dashboard

- Who uses the **Live Dashboard** (KPIs, trends, “what changed today”)?
- Is the current design (Vacant/Churning/Occupied/Sold, trend chart, change table) what they need, or should we add/remove metrics or views?

### 3.5 Tools (super user)

- **Currency Converter / Inflation Calculator / Price Multipliers:** Who uses each? Are these must-haves for the final product?
- Any other tools they expect (e.g. bulk export, approvals)?

### 3.6 Admin / Data Health

- Who should see **Admin / Data Health** (source status, last refresh, allowed list)?
- Do they need a **manual refresh** button, or is “data refreshed every 15 minutes” enough?

### 3.7 Search

- Who uses **Search** across tabs? Do they need it for all roles or only managers/super users?

### 3.8 Final product shape (to close the call)

- Which **tabs** do we **keep**, **rename**, or **remove** for v1?
- Which **sections** (Master Kitchens, Live Dashboard, Data, Search, Tools, Admin) are **must-have** for which **role**?
- For **Master Kitchens**, confirm: **Salesforce report (and/or Sheet) as primary** until warehouse (Trino/BQ) has the right KSA tables; then we can add a “Warehouse” source option.

---

## 4. Outcome from call (Feb 18) — target product shape

**See [CUSTOMER_REQUIREMENTS_FEB18.md](CUSTOMER_REQUIREMENTS_FEB18.md) for full detail.**

- **Tabs = facilities:** Each tab is one facility; every facility with kitchens shows on the tracker; each facility shown by itself.
- **Data:** SF Kitchen Data + SF Churn Data (pivot tables connected).
- **Access:** Every AE has the same access to view the kitchens.

---

## 5. One-line summary for the call

**Progress:** App is live with RBAC, Master Kitchens, Dashboard, and Tools; data today comes from Salesforce reports (and Sheet). **Blockers:** KSA data is not in the BigQuery tables we tried; Trino kitchen link is empty — need the right warehouse tables or stay on Salesforce/Sheet for KSA. **Goal of this call:** Understand who uses each tab and for what, so we can finalize which tabs and sections stay, and confirm data source strategy for Master Kitchens.
