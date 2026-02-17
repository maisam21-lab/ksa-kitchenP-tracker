# SF Churn Data: Query by Report ID or SOQL

## Query by Report ID (recommended — matches live tracker)

To get the **exact same columns** as the live Kitchen Tracker, use the **Report ID** (no SOQL needed).

### 1. Get the Report ID

1. In Salesforce, open the **report** that feeds the live Kitchen Tracker’s **SF Churn Data** (the one with Account Name, Type, Category, Churn Date, etc.).
2. Look at the URL. It will look like:  
   `https://yourdomain.lightning.force.com/lightning/r/Report/00O6T000006Y5DiUAK/view`
3. Copy the **15- or 18-character ID** that starts with `00O` (e.g. `00O6T000006Y5DiUAK`). That is your Report ID.

### 2. Use the Report ID in the app

In Streamlit secrets (e.g. `.streamlit/secrets.toml` or Cloud Secrets), set:

```toml
[sf_tab_queries]
"SF Churn Data" = "00O6T000006Y5DiUAK"
```

Replace `00O6T000006Y5DiUAK` with your actual churn report ID. Then click **Refresh from Salesforce** in the app. The app will call the Salesforce Analytics API and load the report by ID, so columns match the live tracker.

### 3. Run the same report in Salesforce Inspector (by Report ID)

In **Salesforce Inspector**, you can run the report by ID via the **REST** (or **API**) tab:

1. Open Salesforce in the browser and log in.
2. Open Salesforce Inspector (Chrome/Edge extension).
3. Go to the **REST** or **API** tab (or **Export** → run a custom request).
4. Send a **GET** request:

   ```
   GET /services/data/v59.0/analytics/reports/{Report_ID}?includeDetails=true
   ```

   Example (replace with your instance and Report ID):

   ```
   https://yourdomain.my.salesforce.com/services/data/v59.0/analytics/reports/00O6T000006Y5DiUAK?includeDetails=true
   ```

5. Use your session (Inspector uses your current Salesforce session). The response is JSON; the report rows are under `factMap."T!T".rows` (each row has `dataCells` with `label` and `value`).

If your Inspector has an **“Export report”** or **“Run report”** option that accepts a Report ID, you can use that instead.

---

## Optional: SOQL for churn (when you can’t use Report ID)

If you prefer SOQL (e.g. for Salesforce Inspector’s SOQL tab or to avoid Report ID), use the queries below. Column labels may differ from the live report.

## 1. Churn data (Kitchen_Number__c + Account + Opportunity)

Use this if your **Kitchen_Number__c** has a lookup to **Opportunity** (e.g. `Opportunity__c` → `Opportunity__r`):

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
    MSRP__c,
    Activation_Fee__c,
    Opportunity__r.Id,
    Opportunity__r.Name,
    Opportunity__r.Owner.Name,
    Opportunity__r.Floor__c,
    Opportunity__r.Churn_Date__c
FROM Kitchen_Number__c
WHERE Status__c = 'Churning'
  AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar')
ORDER BY Account__r.Country__c, Account__r.Name, Name
```

**In Salesforce Inspector:** Open the extension → **SOQL** tab → paste the query → Run. Export to CSV if needed.

### If your relationship is `Account` (not `Account__r`)

Replace `Account__r` with `Account`:

```sql
SELECT
    Account.Name,
    Type__c,
    Category__c,
    Kitchen_Number_ID_18__c,
    Name,
    Status__c,
    Kitchen_Size_Sq_Meters__c,
    Hood_Size__c,
    Floor_Price__c,
    MSRP__c,
    Activation_Fee__c,
    Opportunity__r.Id,
    Opportunity__r.Name,
    Opportunity__r.Owner.Name,
    Opportunity__r.Floor__c,
    Opportunity__r.Churn_Date__c
FROM Kitchen_Number__c
WHERE Status__c = 'Churning'
  AND Account.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar')
ORDER BY Account.Country__c, Account.Name, Name
```

## 2. Electric Load & Gas Load

If your live report has **Electric Load (kW)** and **Gas Load (kW)**, they may be on `Kitchen_Number__c` or on `Opportunity`. In **Setup → Object Manager** find the object and field API names, then add them to the SELECT, for example:

- On Kitchen: `Electric_Load_kW__c`, `Gas_Load_kW__c` (or `Electric_Load__c`, `Gas_Load__c`)
- On Opportunity: `Opportunity__r.Electric_Load_kW__c`, `Opportunity__r.Gas_Load_kW__c`

Example with Kitchen fields:

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
    MSRP__c,
    Activation_Fee__c,
    Opportunity__r.Id,
    Opportunity__r.Name,
    Opportunity__r.Owner.Name,
    Opportunity__r.Floor__c,
    Opportunity__r.Churn_Date__c,
    Electric_Load_kW__c,
    Gas_Load_kW__c
FROM Kitchen_Number__c
WHERE Status__c = 'Churning'
  AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar')
ORDER BY Account__r.Country__c, Account__r.Name, Name
```

Remove or rename the last two fields if your org uses different API names.

## 3. Column labels vs API names

Salesforce Inspector returns columns with **API names** (e.g. `Account__r.Name`). The live report uses **labels** (e.g. "Account Name"). The app shows whatever the query returns, so you’ll see API names unless you use a Report ID. To match the live report exactly, use the **same Report ID** in `sf_tab_queries`; to use this SOQL in the app, paste the one-line version into secrets (see below).

## Use this SOQL in the app (alternative to Report ID)

If you prefer SOQL instead of Report ID, in Streamlit secrets put the whole SOQL on **one line**:

```toml
[sf_tab_queries]
"SF Churn Data" = "SELECT Account__r.Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Name, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, MSRP__c, Activation_Fee__c, Opportunity__r.Id, Opportunity__r.Name, Opportunity__r.Owner.Name, Opportunity__r.Floor__c, Opportunity__r.Churn_Date__c FROM Kitchen_Number__c WHERE Status__c = 'Churning' AND Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

For the same columns as the live tracker, **Report ID** is simpler; see top of this doc.
