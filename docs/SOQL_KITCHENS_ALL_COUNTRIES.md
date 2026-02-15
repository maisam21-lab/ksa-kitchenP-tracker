# SOQL: All Countries Kitchens Data

Use these SOQL queries in `sf_tab_queries` to pull kitchen data for SA, UAE, Kuwait, Bahrain, and Qatar.

## 1. SF Kitchen Data (all countries)

```sql
SELECT 
    Id,
    Name,
    Kitchen_Number_ID_18__c,
    Type__c,
    Category__c,
    Status__c,
    Kitchen_Size_Sq_Meters__c,
    Hood_Size__c,
    Floor__c,
    MSRP__c,
    List_Price__c,
    Sell_Price__c,
    Account__r.Name,
    Account__r.Country__c,
    Account__r.Account_ID_18__c,
    Account__r.Floor_Price_Multiplier__c,
    (SELECT Name, Churn_Date__c, Opportunity_ID_18__c, Owner.Name 
     FROM Opportunities__r 
     WHERE IsClosed = false 
     LIMIT 1)
FROM Kitchen_Number__c
WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar')
ORDER BY Account__r.Country__c, Account__r.Name, Name
```

If your lookup field is `Account` (not `Account__r`), use:

```sql
SELECT Id, Name, Kitchen_Number_ID_18__c, Type__c, Category__c, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor__c, MSRP__c, List_Price__c, Sell_Price__c, Account.Name, Account.Country__c, Account.Account_ID_18__c, Account.Floor_Price_Multiplier__c FROM Kitchen_Number__c WHERE Account.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account.Country__c, Account.Name, Name
```

## 2. Add to Streamlit secrets

In `.streamlit/secrets.toml` (or Streamlit Cloud Secrets), add:

**Option A — Use a Report ID (simplest, valid TOML):**
```toml
[sf_tab_queries]
"SF Kitchen Data" = "00O6T000006Y0l6UAC"
```

**Option B — Use SF_TAB_QUERIES as JSON** (avoids TOML quoting issues with long SOQL):
```toml
SF_TAB_QUERIES = "{\"SF Kitchen Data\": \"SELECT Id, Name, Type__c, Status__c, Account__r.Name, Account__r.Country__c FROM Kitchen_Number__c WHERE Account__r.Country__c IN ('Saudi Arabia','UAE','Kuwait','Bahrain','Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name\"}"
```

If you get "Invalid format: please enter valid TOML", use Option A (Report ID) or Option B (JSON). Avoid special characters or smart quotes when pasting.

## 3. Adjust for your schema

- Replace `Account__r` with `Account` if that’s your relationship name.
- Replace `Opportunities__r` with your Opportunity child relationship name.
- Add/remove fields to match your `Kitchen_Number__c` and `Account` objects.
- Ensure `Account.Country__c` (or equivalent) exists and is populated.
