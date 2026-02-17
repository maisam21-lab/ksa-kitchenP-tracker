# All Data tabs — API names / column list (your org)

When you send the tabs, we’ll fill this and build the right SOQL (or Report ID) and column order for each.

**Format you can use:** For each tab, send either:
- **Tab name** + list of **column labels** and **API names** (e.g. `Account Name → Account__r.Name`), or  
- A screenshot or export of the columns from Salesforce (report or object), and we’ll map them.

---

## Tabs (paste your column/API list under each)

### 1. SF Kitchen Data (all kitchens — main view) ✅
*Navigate all kitchens under accounts in all countries with full details.*

| Label | API name |
|-------|----------|
| Account Name | Account__r.Name |
| Type | Type__c |
| Category | Category__c |
| Kitchen Number | Kitchen_Number_ID_18__c |
| Kitchen Number Name | Name |
| Status | Status__c |
| Kitchen Size | Kitchen_Size_Sq_Meters__c |
| Hood Size | Hood_Size__c |
| Floor Price | Floor_Price__c |
| List Price | Sell_Price__c |
| Activation Fee | Activation_Fee__c |
| Opportunity | Opportunity__r.Id |
| Opportunity Name | Opportunity__r.Name |
| Opportunity Owner | Opportunity__r.Owner.Name |
| Floor | Floor__c |
| County | Account__r.Country__c |
| Churn Date | Opportunity__r.Churn_Date__c |

See **docs/SF_KITCHEN_DATA_API_NAMES.md**. SOQL and app column order updated.

---

### 2. SF Churn Data
*Kitchens with Status = Churning + opportunity/churn details.*

| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 3. Sellable No Status
*Kitchens with sellable / no-status logic.*

| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 4. All no status kitchens
*Kitchens with no status.*

| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 5. Price Multipliers
*Account-level (e.g. Floor Price Multiplier, Total Kitchens).*

| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 6. Area Data
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 7. LF Comp
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 8. Pivot Table 10
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 9. KSA Facility details
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 10. UAE Facility details
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 11. Kuwait Facility details
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 12. Bahrain Facility details
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 13. Qatar Facility details
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 14. Inflation FPx
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 15. Occupancy
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 16. Pivot Table 4
| Label | API name |
|-------|----------|
| *(you provide)* | |

---

### 17–23. Qurtoba - Old, Jarir - Old, Salam - Old, Narjis - Old, Aqrabiya - Old, Zuhur - Old, Hofuf - Old
*(Add if you use these; same format.)*

---

**Notes:**
- You don’t have to send every tab at once. Start with the ones you use most (e.g. SF Kitchen Data, SF Churn Data, Price Multipliers).
- For each tab, if it comes from a **Report**, you can send the Report ID + column labels; if from **SOQL**, send object + field API names.
- After you send the lists, we’ll update `sf_tab_queries` (SOQL/Report ID) and app column order so each tab matches your org.
