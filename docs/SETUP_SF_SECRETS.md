# Setup Salesforce Secrets — Include All Online Tracker Tabs

To load **all** tabs from the online tracker (Inflation FPx, LF Comp, Pivot Table 10, Occupancy, etc.) into the kitchen tracker, add their Report IDs to `[sf_tab_queries]`.

## Tabs in the Online Tracker

| Tab | Add to sf_tab_queries |
|-----|------------------------|
| Kitchens | ✅ (main view; use "Kitchens" or "SF Kitchen Data" in sf_tab_queries) |
| Master Kitchens list | ✅ (same report ID as Kitchens or a dedicated report) |
| SF Churn Data | ✅ |
| Sellable No Status | ✅ |
| All no status kitchens | ✅ |
| Price Multipliers | ✅ |
| Area Data | ✅ |
| Inflation FPx | Add Report ID when available |
| LF Comp | Add Report ID when available |
| Pivot Table 10 | Add Report ID when available |
| Pivot Table 4 | Add Report ID when available |
| Occupancy | Add Report ID when available |
| KSA Facility details | Add Report ID when available |
| UAE Facility details | Add Report ID when available |
| Kuwait Facility details | Add Report ID when available |
| Bahrain Facility details | Add Report ID when available |
| Qatar Facility details | Add Report ID when available |
| Qurtoba - Old, Jarir - Old, etc. | Add Report IDs when available |

## Example: Full sf_tab_queries

Use **Report IDs** when you have a report with all the right columns (no SOQL field-name mismatches across orgs). Example — Kitchens and Master Kitchens list from your report:

```toml
[sf_tab_queries]
"Kitchens" = "00OVO00000PMnq92AD"
"Master Kitchens list" = "00OVO00000PMnq92AD"
"SF Churn Data" = "00O6T000006Y5DiUAK"
"Sellable No Status" = "00O6T000006DXT0UAO"
"All no status kitchens" = "00O6T000006DPigUAG"
"Price Multipliers" = "00OVO000003z2O92AI"
"Area Data" = "00O6T000006Y0l6UAC"
"Inflation FPx" = "00Oxxxxxxxxxxxxxx"
"LF Comp" = "00Oxxxxxxxxxxxxxx"
"Pivot Table 10" = "00Oxxxxxxxxxxxxxx"
"Occupancy" = "00Oxxxxxxxxxxxxxx"
"KSA Facility details" = "00Oxxxxxxxxxxxxxx"
```

## How to get each Report ID (and feed them into the app)

Use the **same Salesforce org** where your SF Kitchen Data report lives (e.g. production). For every tab you want from reports:

1. In Salesforce, go to **Reports** (App Launcher → Reports, or the Reports tab).
2. Open the **folder** that has your tracker reports (e.g. “Kitchen Tracker” or “Sales”).
3. For each report you need (SF Churn Data, Sellable No Status, Area Data, Price Multipliers, Inflation FPx, etc.):
   - **Open the report** (click the report name).
   - Look at the **browser URL**. It will look like:  
     `https://yourdomain.my.salesforce.com/00OXXXXXXXXXXXXXX?param=...`  
     or  
     `.../lightning/r/Report/00OXXXXXXXXXXXXXX/view`
   - Copy the **15- or 18-character ID** that starts with `00O` (e.g. `00O6T000006Y5DiUAK`). That is the Report ID.
4. In the app’s **secrets** (Streamlit Cloud: app → Settings → Secrets; local: `.streamlit/secrets.toml`), add one line per report inside `[sf_tab_queries]`. The **key** must match the tab name exactly (e.g. `"SF Churn Data"`, `"Area Data"`). Example:

```toml
[sf_tab_queries]
"Kitchens" = "00OVO00000PMnq92AD"
"SF Churn Data" = "00O6T000006Y5DiUAK"
"Sellable No Status" = "00O6T000006DXT0UAO"
"All no status kitchens" = "00O6T000006DPigUAG"
"Price Multipliers" = "00OVO000003z2O92AI"
"Area Data" = "00O6T000006Y0l6UAC"
"Inflation FPx" = "00O..."
"LF Comp" = "00O..."
```

5. Replace each `00O...` with the ID you copied from that report’s URL. You don’t have to add all tabs at once — add only the reports you have; the app will load those. Tabs without a Report ID can still be filled via **Refresh from online sheet** (synced from Salesforce every 4 hours).

**Tab name in secrets** must match exactly (including spaces and casing), e.g. `"SF Churn Data"` not `"SF Churn"`. Use the names from the table in the “Tabs in the Online Tracker” section above.

## Share a report with the dev account (or integration user)

So the user whose credentials the app uses (e.g. dev/integration user) can run the report via the API:

**1. Grant Run Reports**

- **Setup** → **Users** → **Profiles** (or **Permission Sets**) → open the profile/permission set for the dev user.
- Enable **Run Reports** (and **View Reports** if needed) → Save.

**2. Share the report folder**

The dev user must have access to the **folder** that contains the report (e.g. the report `00OVO00000PMnq92AD`).

- Go to **Reports** → open the report → click the **▼** next to the report name → **Edit Folder** (or **Manage Folder**).  
  Or: **Setup** → **Reports** → **Report Folders** → open the folder that contains your report.
- In the folder, open **Sharing** (or **Manage Sharing**).
- **Add** → choose **Users** (or **Roles**) → select the **dev user** (or a role they’re in) → set access to at least **View** (or **Run Reports** if listed) → Save.

After that, the dev user can run the report in the browser and the app (using that user’s credentials) can load it via the API. If you still get 403, the user needs **Run Reports** (step 1) and the folder must be shared (step 2).

## 404 Not Found when using Report IDs

If you see **404 Client Error: Not Found** for `.../analytics/reports/00O...`, the report **does not exist in the org** the app is connected to. The URL in the error shows which org was called (e.g. `cloudkitchens--yazandev.sandbox.my.salesforce.com` = yazandev sandbox).

- **Report was created in production** → Use **production** Salesforce credentials in the app so the API calls production, where the report exists.
- **Report was created in a sandbox** → Use that sandbox’s credentials, and use the report ID from that sandbox (report IDs are different in each org).
- If you must use a sandbox but the report is only in prod, create or copy the report in the sandbox and put the **sandbox** report ID in `sf_tab_queries`.

## 403 Forbidden when using Report IDs

If you see **403 Client Error: Forbidden** for `.../analytics/reports/00O...`, the user that authenticates (integration user or the user whose token you use) does **not** have permission to run those reports via the API.

### How to grant the integration user Run Reports

1. **Identify the integration user**  
   This is the user whose credentials you use: the one in `SF_USERNAME` (with `SF_PASSWORD` / `SF_SECURITY_TOKEN`), or the user who generated the `SF_ACCESS_TOKEN`. Note their username or User ID.

2. **Grant “Run Reports” (via Profile or Permission Set)**  
   - In Salesforce, go to **Setup** (gear icon).  
   - **Option A — Profile:**  
     - **Users** → **Profiles** → open the profile assigned to the integration user.  
     - Find **Administrative Permissions** (or **General User Permissions**).  
     - Enable **Run Reports** (and, if you want them to open report folders, **View Reports**).  
     - Save.  
   - **Option B — Permission Set (recommended for one user):**  
     - **Users** → **Permission Sets** → open a set (or create one, e.g. “Kitchen Tracker API”).  
     - **System Permissions** → Edit → enable **Run Reports** (and **View Reports** if needed).  
     - Save.  
     - **Manage Assignments** → add the integration user → Save.

3. **Give access to the report folder**  
   The user must be able to see the folder that contains the reports (e.g. “Kitchen Tracker”, “Sales”, “Unfiled Public Reports”).  
   - Go to **Reports** tab → find one of the reports that failed (e.g. SF Kitchen Data).  
   - Open the report, then click the **▼** next to the report name → **Edit Folder** (or go to **Setup** → **Reports** → **Report Folders**).  
   - Open the folder that contains the report.  
   - **Sharing** (or **Manage Sharing**) → **Add** → choose **Users** or **Roles** → add the integration user (or a role they’re in) with at least **View** access.  
   - Save.

4. **Confirm**  
   Log in as the integration user (or use a test token for that user), open **Reports**, and run one of the reports in the browser. If they can run it in the UI, the API can run it too (after you retry **Refresh from Salesforce** in the app).

**Fix one of these:**

1. **Grant the integration user Run Reports** — follow the step-by-step above.
2. **Use SOQL instead of Report ID** — If you can’t change permissions, use SOQL in `sf_tab_queries` instead of Report IDs. **Copy-paste ready:** see **docs/SECRETS_SOQL_PASTE.md** (SOQL for SF Kitchen Data, SF Churn Data, Price Multipliers, Sellable No Status, All no status). Also **docs/SOQL_SF_INSPECTOR_CHURN.md** and **docs/SOQL_KITCHENS_ALL_COUNTRIES.md**. SOQL uses object/field read permissions, which are often already granted.
3. **Sandbox vs production** — In a sandbox (e.g. `cloudkitchens--yazandev.sandbox.my.salesforce.com`), report folders and sharing may differ from production. Confirm the integration user can open and run the report in the browser in that same org; if they can’t, fix folder access or use SOQL.

## Why does SF Churn Data not match the live Kitchen Tracker?

The app shows **exactly** what your data source returns. If the **SF Churn Data** tab in the app has different or fewer columns than the live tracker, it’s because:

1. **Different Report ID** — In secrets, `"SF Churn Data"` must use the **same** Salesforce Report ID as the report that feeds the live Kitchen Tracker. If you use another report (or SOQL that selects fewer fields), the columns won’t match.
2. **SOQL instead of Report** — If you use a SOQL query instead of a Report ID, the query must `SELECT` all the same fields as the live churn report; otherwise some columns will be missing.

**Fix:** Set `"SF Churn Data"` in `[sf_tab_queries]` to the **Report ID** of the live Kitchen Tracker’s churn report (Salesforce → Reports → open that report → copy the 15- or 18-character ID from the URL). Then click **Refresh from Salesforce** in the app.

To **query churn data in Salesforce Inspector** (SOQL that matches the live columns), see **docs/SOQL_SF_INSPECTOR_CHURN.md**.

### Live Kitchen Tracker — SF Churn Data columns (reference)

Use this list to check that your app’s SF Churn Data tab has the same columns:

| Column |
|--------|
| Account Name |
| Type |
| Category |
| Kitchen Number ID 18 |
| Kitchen Number Name |
| Status |
| Kitchen Size (Sq. Meters) |
| Hood Size |
| Floor Price |
| MSRP |
| Activation Fee |
| Opportunity ID 18 |
| Opportunity Name |
| Opportunity Owner: Full Name |
| Floor |
| Electric Load (kW) |
| Gas Load (kW) |
| Churn Date |

If your app is missing any of these, switch to the correct Report ID (or add the missing fields to your SOQL) and refresh.

## Fallback: Refresh from Online Sheet

Tabs that don't have SF Report IDs can still be loaded via **Refresh from online sheet**. The Sheet refresh loads **all** worksheets from the online tracker, including Inflation FPx, LF Comp, etc.
