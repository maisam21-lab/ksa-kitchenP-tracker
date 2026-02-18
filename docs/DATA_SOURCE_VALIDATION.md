# Data source validation: SF vs GSheet (no mix)

## How it works

1. **Single storage**  
   Both **Salesforce** and **Google Sheet** write into the **same** SQLite table `generic_tab_data` under the **same** tab IDs (e.g. `Kitchens`, `Master Kitchens list`, `SF Churn Data`).  
   So at any time the app holds data from **one** source only: whichever was last refreshed. There is no mixing of SF and GSheet in one tab.

2. **Who writes what**  
   - **Data → “Refresh from selected source” (Salesforce)**  
     Calls `_refresh_from_salesforce()` → overwrites those tab IDs with SF report/query results.  
   - **Data → “Refresh from selected source” (Google Sheet)**  
     Calls `_refresh_from_online_sheet()` → overwrites tab IDs with sheet data (by worksheet name).  
   So each refresh **replaces** the data for those tabs; no blending.

3. **Who reads**  
   - **Kitchen Master Data** (when not using Superset): reads `list_generic_tab("Kitchens")` or `list_generic_tab("Master Kitchens list")` — i.e. whatever is **currently** in the DB (from the last SF or GSheet refresh).  
   - **Data section**: same DB; when `data_source == "gsheet"` it only shows the Kitchens tab; otherwise it shows all tabs.  
   - **Dashboard**: same again, `list_generic_tab("Kitchens")` or `Master Kitchens list`.

4. **Label (SF vs GSheet)**  
   `st.session_state["data_source"]` is set to `"salesforce"` or `"gsheet"` when:  
   - The app does the one-time auto-refresh (SF first, then GSheet if SF fails), or  
   - The user clicks **“Refresh from selected source”** in the Data section.  
   Captions that say “Data reflects the source selected in **Data** (Salesforce or Google Sheet)” use this value, so the **label** matches the **last refresh**, not a mix.

## Naming fix (no confusion)

- **Data section**  
  “Data source” = **Salesforce (SF)** vs **Google Sheet (GSheet)** → which system to pull from. This is correct and unchanged.

- **Kitchen Master Data** (manager/super_user)  
  There was a second control also called “Data source” with options **Kitchens** / **Master Kitchens list** → that is “which **tab** to show”, not SF vs GSheet.  
  That control is renamed to **“Tab”** (or “View”) in the app so it’s clear we’re not choosing between SF and GSheet there.

## Summary

- **No mix**: One refresh source at a time; one set of tab data in the DB; all sections read from that same set.  
- **Clear labelling**: SF vs GSheet is only chosen in **Data**; Kitchen Master Data only shows which **tab** (Kitchens vs Master Kitchens list) and a caption that reflects the source selected in Data.
