# SF Kitchen Data (all kitchens) — API names from your org

From your SF Kitchen Data - KSA report and screenshots. Use this order in the app and in SOQL.

| # | Label | API name (SOQL from Kitchen_Number__c) |
|---|-------|--------------------------------------|
| 1 | Account Name | `Account__r.Name` |
| 2 | Type | `Type__c` — **if 400, check Object Manager for Kitchen Number → Type field API name** |
| 3 | Category | `Category__c` — **if 400, check Object Manager for Kitchen Number → Category field API name** |
| 4 | Kitchen Number | `Kitchen_Number_ID_18__c` |
| 5 | Kitchen Number Name | `Name` |
| 6 | Status | `Status__c` |
| 7 | Kitchen Size | `Kitchen_Size_Sq_Meters__c` |
| 8 | Hood Size | `Hood_Size__c` |
| 9 | Floor Price | `Floor_Price__c` |
| 10 | List Price | `Sell_Price__c` |
| 11 | Activation Fee | `Activation_Fee__c` |
| 12 | Opportunity (ID) | `Opportunity__r.Id` or `Opportunity__r.Opportunity_ID_18__c` |
| 13 | Opportunity Name | `Opportunity__r.Name` |
| 14 | Opportunity Owner | `Opportunity__r.Owner.Name` |
| 15 | Floor | `Floor__c` |
| 16 | County | `Account__r.Country__c` |
| 17 | Churn Date | `Opportunity__r.Churn_Date__c` |

**Object:** `Kitchen_Number__c`. Account: `Account__r`. Opportunity: `Opportunity__r`.

**Note:** In your report, "List Price" is mapped to `Kitchen_Number__c.Sell_Price__c`; "Floor" is `Kitchen_Number__c.Floor__c`. County = Account country (`Account__r.Country__c`).

---

## If you get 400 Bad Request

Salesforce returns 400 when a **field or relationship name is wrong** for your org. The app shows the exact error (e.g. "No such column 'Account__r.Name' on entity 'Kitchen_Number__c'").

**1. Try a minimal query first** (no Opportunity, only kitchen + account fields). In secrets set:

```toml
"SF Kitchen Data" = "SELECT Account__r.Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Name, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, Sell_Price__c, Activation_Fee__c, Floor__c, Account__r.Country__c FROM Kitchen_Number__c WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

If that works, the issue is with **Opportunity** fields. In that case the lookup from `Kitchen_Number__c` to Opportunity may have a different name (e.g. not `Opportunity__r`). In Setup → Object Manager → Kitchen Number → Fields & Relationships, find the lookup to Opportunity and use its **Relationship Name** (e.g. `Opportunity__r` or `Primary_Opportunity__r`).

**2. If minimal still fails**, read the error: it will name the bad column. Then:
- **Account__r** → try **Account** (standard relationship).
- **Sell_Price__c** → try **MSRP__c** or **List_Price__c** if your org uses different names.
- **Floor__c** → might be on Opportunity in your org; remove it from this query or use the correct object.

**3. Try standard Account relationship:** If the error mentions `Account__r`, your org may use the standard relationship. Use `Account` instead of `Account__r`:

```toml
"SF Kitchen Data" = "SELECT Account.Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Name, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, Sell_Price__c, Activation_Fee__c, Floor__c, Account.Country__c FROM Kitchen_Number__c WHERE Account.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account.Country__c, Account.Name, Name"
```

**4. Smallest test (object only):** If even `Account__r.Name` fails, test the object alone:

```toml
"SF Kitchen Data" = "SELECT Id, Name FROM Kitchen_Number__c LIMIT 10"
```

- If this **works**, the object exists; the issue is the Account relationship. Try next: `Account.Name` (standard) instead of `Account__r.Name`.
- If this **fails**, the object API name may differ in your sandbox (e.g. `Kitchen_Number__c` vs `KitchenNumber__c`). In Setup → Object Manager, open the kitchen object and check **API Name**.

**5. Standard Account:** If your kitchen object uses the standard Account lookup, use `Account` not `Account__r`:

```toml
"SF Kitchen Data" = "SELECT Id, Name, Account.Name FROM Kitchen_Number__c LIMIT 10"
```

**6. Step-by-step: find the bad field**  
You know `Id, Name, Account__r.Name` work. Add fields in steps. Use each line below as your `"SF Kitchen Data"` value and refresh until one returns 400.

**Step A** (core + country):

```toml
"SF Kitchen Data" = "SELECT Account__r.Name, Name, Type__c, Category__c, Account__r.Country__c FROM Kitchen_Number__c WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

If Step A works, try **Step B** (add kitchen ID + status + size):

```toml
"SF Kitchen Data" = "SELECT Account__r.Name, Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Account__r.Country__c FROM Kitchen_Number__c WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

If Step B works, try **Step C** (add price fields; often one of these has a different API name):

```toml
"SF Kitchen Data" = "SELECT Account__r.Name, Name, Type__c, Category__c, Kitchen_Number_ID_18__c, Status__c, Kitchen_Size_Sq_Meters__c, Hood_Size__c, Floor_Price__c, Sell_Price__c, Activation_Fee__c, Floor__c, Account__r.Country__c FROM Kitchen_Number__c WHERE Account__r.Country__c IN ('Saudi Arabia', 'UAE', 'Kuwait', 'Bahrain', 'Qatar') ORDER BY Account__r.Country__c, Account__r.Name, Name"
```

- If **Step A** fails → one of `Type__c`, `Category__c`, or `Account__r.Country__c` is wrong; check Object Manager.
- If **Step B** fails → one of `Kitchen_Number_ID_18__c`, `Status__c`, `Kitchen_Size_Sq_Meters__c`, `Hood_Size__c` is wrong.
- If **Step C** fails → one of `Floor_Price__c`, `Sell_Price__c`, `Activation_Fee__c`, or `Floor__c` is wrong. Try without `Sell_Price__c` (use `MSRP__c` or `List_Price__c` if your org has it), or without `Floor__c`.

**7. Get the exact error in Salesforce:** **Developer Console** → **Query Editor**. Run the same SOQL; Salesforce will show e.g. "No such column 'Sell_Price__c' on entity 'Kitchen_Number__c'". Fix or remove that field in your secrets.

**8. If Type__c or Category__c return 400:** In your sandbox those fields have different API names. In **Setup → Object Manager → Kitchen Number → Fields & Relationships**, find the **Type** and **Category** fields and use their **API Name** (e.g. `Kitchen_Type__c`, `Category_Code__c`). Put the working query in secrets without Type/Category until you have the correct names, then add them back.
