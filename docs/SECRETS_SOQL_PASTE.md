# Paste SOQL into secrets (no Report ID / no Run Reports permission)

Use this when you get **403 Forbidden** on Report IDs. Copy one of the blocks below into your **Streamlit secrets** (Cloud: app → Settings → Secrets; local: `.streamlit/secrets.toml`). Keep your existing Salesforce auth (e.g. `SF_USERNAME`, `SF_PASSWORD`, or `SF_ACCESS_TOKEN`).

**Main objective:** Navigate all kitchens under accounts in all countries with all related details. The **SF Kitchen Data** query below is the primary one for that; see **docs/OBJECTIVE_AND_MAIN_QUERY.md**.

---

## Option A: Minimal (SF Kitchen Data + SF Churn Data only)

**SF Kitchen Data** = all kitchens, all countries. If you get **400 Bad Request**, try the **minimal** query below (no Opportunity fields); see **docs/SF_KITCHEN_DATA_API_NAMES.md** for troubleshooting.

**Kitchens** — use your report (all columns, no SOQL/field-name issues). Data appears in the **Kitchens** tab.

```toml
[sf_tab_queries]
"Kitchens" = "00OVO00000PMnq92AD"
"SF Churn Data" = "SELECT Account__r.Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Name, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, MSRP__c, Activation_Fee__c, Opportunity__r.Id, Opportunity__r.Name, Opportunity__r.Owner.Name, Opportunity__r.Floor__c, Opportunity__r.Churn_Date__c FROM Kitchen_Number__c WHERE Status__c = 'Churning' AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

**If you still get 400:** the app will now show Salesforce’s exact error (which field is invalid). Try replacing `Account__r` with `Account` in the query, or remove one field at a time to find the bad one. Full query with Opportunity (use only after confirming the lookup name in Setup):

```toml
"SF Kitchen Data" = "SELECT Account__r.Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Name, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, Sell_Price__c, Activation_Fee__c, Opportunity__r.Id, Opportunity__r.Name, Opportunity__r.Owner.Name, Floor__c, Account__r.Country__c, Opportunity__r.Churn_Date__c FROM Kitchen_Number__c WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

---

## Option B: Add Price Multipliers (Account-level)

Add this line inside the same `[sf_tab_queries]` block (same as above, plus Price Multipliers). Use the correct object and fields for your org (e.g. `Account` or `Account__c`).

```toml
"Price Multipliers" = "SELECT Id, Name, Account_ID_18__c, Country__c, Floor_Price_Multiplier__c, Total_Kitchen_Numbers__c FROM Account WHERE Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Country__c, Name"
```

If your field names differ (e.g. `BillingCountry` instead of `Country__c`), edit the query in Setup → Object Manager → Account to see API names.

---

## Option C: Add Sellable No Status & All no status kitchens

These use the same object as SF Kitchen Data with different filters. Add to `[sf_tab_queries]`:

```toml
"Sellable No Status" = "SELECT Id, Name, Kitchen_Number_ID_18__c, Type__c, Category__c, Status__c, Account__r.Name, Account__r.Country__c FROM Kitchen_Number__c WHERE (Status__c = null OR Status__c = '' OR LOWER(TRIM(Status__c)) IN ('no status', 'n/a', 'na')) AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
"All no status kitchens" = "SELECT Id, Name, Kitchen_Number_ID_18__c, Type__c, Category__c, Status__c, Account__r.Name, Account__r.Country__c FROM Kitchen_Number__c WHERE (Status__c = null OR Status__c = '' OR LOWER(TRIM(Status__c)) IN ('no status', 'n/a', 'na')) AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

You can change the status filter to match how your org marks “no status” (e.g. a specific picklist value).

---

## Full example (all of the above in one block)

Kitchens uses your report ID so you get all columns without SOQL field-name issues. Data appears in the **Kitchens** tab. Use **production** credentials if the report lives in prod.

```toml
[sf_tab_queries]
"Kitchens" = "00OVO00000PMnq92AD"
"SF Churn Data" = "SELECT Account__r.Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Name, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, MSRP__c, Activation_Fee__c, Opportunity__r.Id, Opportunity__r.Name, Opportunity__r.Owner.Name, Opportunity__r.Floor__c, Opportunity__r.Churn_Date__c FROM Kitchen_Number__c WHERE Status__c = 'Churning' AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
"Price Multipliers" = "SELECT Id, Name, Account_ID_18__c, Country__c, Floor_Price_Multiplier__c, Total_Kitchen_Numbers__c FROM Account WHERE Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Country__c, Name"
"Sellable No Status" = "SELECT Id, Name, Kitchen_Number_ID_18__c, Type__c, Category__c, Status__c, Account__r.Name, Account__r.Country__c FROM Kitchen_Number__c WHERE (Status__c = null OR Status__c = '' OR LOWER(TRIM(Status__c)) IN ('no status', 'n/a', 'na')) AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
"All no status kitchens" = "SELECT Id, Name, Kitchen_Number_ID_18__c, Type__c, Category__c, Status__c, Account__r.Name, Account__r.Country__c FROM Kitchen_Number__c WHERE (Status__c = null OR Status__c = '' OR LOWER(TRIM(Status__c)) IN ('no status', 'n/a', 'na')) AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

**Area Data** and other report-only tabs (Inflation FPx, LF Comp, etc.): if you don’t have SOQL for them, use **Refresh from online sheet** for those; the sheet sync will fill them if they’re in the workbook.

---

## After pasting

1. Save secrets (Cloud: Save; local: save `secrets.toml`).
2. In the app: **Data** → **Refresh from Salesforce**.
3. If a query fails (e.g. “No such column”), your org’s API names may differ. Fix that line using Setup → Object Manager or **docs/SOQL_KITCHENS_ALL_COUNTRIES.md** / **docs/SOQL_SF_INSPECTOR_CHURN.md**.
