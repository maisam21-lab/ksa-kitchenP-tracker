# SOQL: All Headers for All Countries

Use this query to get the columns matching your tracker headers (Account Name, Type, Category, Kitchen Number, Kitchen Number Name, Status, Kitchen Size, Hood Size, Floor Price, List Price, Activation Fee, Opportunity ID, Opportunity Name, Opportunity Floor, County/Country, Churn Date) for **all countries** (SA, UAE, Kuwait, Bahrain, Qatar).

## Query

```sql
SELECT
    Account.Name,
    Kitchen_Number__c.Type__c,
    Kitchen_Number__c.Category__c,
    Kitchen_Number__c.Kitchen_Number_ID_18__c,
    Kitchen_Number__c.Name,
    Kitchen_Number__c.Status__c,
    Kitchen_Number__c.Kitchen_Size_Sq_Meters__c,
    Kitchen_Number__c.Hood_Size__c,
    Kitchen_Number__c.Floor_Price__c,
    Kitchen_Number__c.MSRP__c,
    Kitchen_Number__c.List_Price__c,
    Kitchen_Number__c.Activation_Fee__c,
    Opportunity__r.Id,
    Opportunity__r.Name,
    Opportunity__r.Floor__c,
    Account.Country__c,
    Opportunity__r.Churn_Date__c
FROM Kitchen_Number__c
WHERE Account.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar')
ORDER BY Account.Country__c, Account.Name, Kitchen_Number__c.Name
```

## If your lookup uses `Account__r` (custom lookup)

```sql
SELECT
    Account__r.Name,
    Kitchen_Number__c.Type__c,
    Kitchen_Number__c.Category__c,
    Kitchen_Number__c.Kitchen_Number_ID_18__c,
    Kitchen_Number__c.Name,
    Kitchen_Number__c.Status__c,
    Kitchen_Number__c.Kitchen_Size_Sq_Meters__c,
    Kitchen_Number__c.Hood_Size__c,
    Kitchen_Number__c.Floor_Price__c,
    Kitchen_Number__c.MSRP__c,
    Kitchen_Number__c.List_Price__c,
    Kitchen_Number__c.Activation_Fee__c,
    Opportunity__r.Id,
    Opportunity__r.Name,
    Opportunity__r.Floor__c,
    Account__r.Country__c,
    Opportunity__r.Churn_Date__c
FROM Kitchen_Number__c
WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar')
ORDER BY Account__r.Country__c, Account__r.Name, Kitchen_Number__c.Name
```

## Header → SOQL field mapping

| Header               | SOQL field |
|----------------------|------------|
| Account Name         | Account.Name (or Account__r.Name) |
| Type                 | Kitchen_Number__c.Type__c |
| Category             | Kitchen_Number__c.Category__c |
| Kitchen Number       | Kitchen_Number__c.Kitchen_Number_ID_18__c |
| Kitchen Number Name  | Kitchen_Number__c.Name |
| Status               | Kitchen_Number__c.Status__c |
| Kitchen Size (Hood Size) | Kitchen_Number__c.Kitchen_Size_Sq_Meters__c, Kitchen_Number__c.Hood_Size__c |
| Floor Price          | Kitchen_Number__c.Floor_Price__c |
| List Price           | Kitchen_Number__c.MSRP__c or Kitchen_Number__c.List_Price__c |
| Activation Fee       | Kitchen_Number__c.Activation_Fee__c |
| Opportunity IC       | Opportunity__r.Id |
| Opportunity N        | Opportunity__r.Name |
| Opportunity Floor    | Opportunity__r.Floor__c |
| County               | Account.Country__c (or Account__r.Country__c) |
| Churn Date           | Opportunity__r.Churn_Date__c |

## Use in Streamlit secrets

Put the query on **one line** under `[sf_tab_queries]`:

```toml
[sf_tab_queries]
"SF Kitchen Data" = "SELECT Account.Name, Kitchen_Number__c.Type__c, Kitchen_Number__c.Category__c, Kitchen_Number__c.Kitchen_Number_ID_18__c, Kitchen_Number__c.Name, Kitchen_Number__c.Status__c, Kitchen_Number__c.Kitchen_Size_Sq_Meters__c, Kitchen_Number__c.Hood_Size__c, Kitchen_Number__c.Floor_Price__c, Kitchen_Number__c.MSRP__c, Kitchen_Number__c.List_Price__c, Kitchen_Number__c.Activation_Fee__c, Opportunity__r.Id, Opportunity__r.Name, Opportunity__r.Floor__c, Account.Country__c, Opportunity__r.Churn_Date__c FROM Kitchen_Number__c WHERE Account.Country__c IN ('Saudi Arabia','UAE','Kuwait','Bahrain','Qatar') ORDER BY Account.Country__c, Account.Name, Kitchen_Number__c.Name"
```

Or use a **Report ID** for "SF Kitchen Data" if your report already has these columns in Salesforce.

## Adjust for your org

- Replace `Kitchen_Number__c` if your object has a different API name.
- Replace `Opportunity__r` with your actual Opportunity relationship name (e.g. `Opportunities__r` with subquery).
- Add/remove fields to match your object; some names (e.g. `Activation_Fee__c`, `Floor_Price__c`) may differ.
- If "County" is a separate field, use that instead of `Account.Country__c`.
