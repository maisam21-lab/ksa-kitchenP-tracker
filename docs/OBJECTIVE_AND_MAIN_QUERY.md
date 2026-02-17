# Tracker objective and main query

## Major objective

**Navigate all kitchens under accounts in all countries with all related details.**

- **All kitchens** — Kitchen-level rows (one row per kitchen), not just account summaries.
- **Under accounts** — Each kitchen is linked to an account (Account Name, Account Country, Account ID).
- **All countries** — Saudi Arabia, UAE, Kuwait, Bahrain, Qatar (and any other Gulf countries you add).
- **All related details** — Type, Category, Status, Kitchen Size, Hood Size, Floor Price, MSRP, Activation Fee, Opportunity (ID, Name, Owner, Floor, Churn Date), and Electric/Gas Load when available.

## Where in the app

- **Data** → **Kitchens** tab is the **main view** for this.
- That tab is fed by the **Kitchens** (or **SF Kitchen Data**) entry in `sf_tab_queries` (Report ID or SOQL).
- Use the **search** box and **Filter by one column** (e.g. Account Country) to navigate.
- **Account Country** is shown first so you can filter by country quickly.

## One SOQL for “all kitchens, all countries, all details”

Column order matches your report: **Account Name → Type → Category → Kitchen Number → Kitchen Number Name → Status → Kitchen Size → Hood Size → Floor Price → List Price → Activation Fee → Opportunity → Opportunity Name → Opportunity Owner → Floor → County → Churn Date**. API names from your org: see **docs/SF_KITCHEN_DATA_API_NAMES.md**.

```sql
SELECT
    Account__r.Name,
    Type__c,
    Category__c,
    Kitchen_Number_ID_18__c,
    Name,
    Status__c,
    Kitchen_Size_Sq_Meters__c,
    Hood_Size__c,
    Floor_Price__c,
    Sell_Price__c,
    Activation_Fee__c,
    Opportunity__r.Id,
    Opportunity__r.Name,
    Opportunity__r.Owner.Name,
    Floor__c,
    Account__r.Country__c,
    Opportunity__r.Churn_Date__c
FROM Kitchen_Number__c
WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar')
ORDER BY Account__r.Country__c, Account__r.Name, Name
```

**One-line version for secrets** (paste into `[sf_tab_queries]` → `"SF Kitchen Data"`):

```
SELECT Account__r.Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Name, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, Sell_Price__c, Activation_Fee__c, Opportunity__r.Id, Opportunity__r.Name, Opportunity__r.Owner.Name, Floor__c, Account__r.Country__c, Opportunity__r.Churn_Date__c FROM Kitchen_Number__c WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name
```

## Other tabs

- **SF Churn Data** — Subset of kitchens with Status = Churning and opportunity/churn details.
- **Price Multipliers** — Account-level (Floor Price Multiplier, Total Kitchens).
- **Sellable No Status / All no status kitchens** — Kitchen-level with status filters.

For the main objective, **SF Kitchen Data** with the query above is the single source; the rest are focused views or account-level data.
