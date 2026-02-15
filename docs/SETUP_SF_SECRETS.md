# Setup Salesforce Secrets — Include All Online Tracker Tabs

To load **all** tabs from the online tracker (Inflation FPx, LF Comp, Pivot Table 10, Occupancy, etc.) into the kitchen tracker, add their Report IDs to `[sf_tab_queries]`.

## Tabs in the Online Tracker

| Tab | Add to sf_tab_queries |
|-----|------------------------|
| SF Kitchen Data | ✅ |
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

```toml
[sf_tab_queries]
"SF Kitchen Data" = "00O6T000006Y0l6UAC"
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

Replace `00Oxxxxxxxxxxxxxx` with your actual Salesforce Report IDs. Get them from Salesforce → Reports → open the report → copy the ID from the URL.

## Fallback: Refresh from Online Sheet

Tabs that don't have SF Report IDs can still be loaded via **Refresh from online sheet**. The Sheet refresh loads **all** worksheets from the online tracker, including Inflation FPx, LF Comp, etc.
