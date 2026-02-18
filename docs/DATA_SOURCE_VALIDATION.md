# Data source validation: SF vs GSheet (no mix)

## How it works

1. **Separate storage per source**  
   **Salesforce** and **Google Sheet** write into the same SQLite table `generic_tab_data` but under a **source** column: `source = 'salesforce'` or `source = 'gsheet'`. Tab IDs (e.g. `Kitchens`, `Master Kitchens list`) are stored per source. So SF data is **never** overwritten by a GSheet refresh, and vice versa. The app always reads from the source currently selected in **Data** (Salesforce or Google Sheet).

2. **Who writes what**  
   - **Data → “Refresh from selected source” (Salesforce)**  
     Calls `_refresh_from_salesforce()` → writes only to `generic_tab_data` with `source = 'salesforce'` (using SF credentials).  
   - **Data → “Refresh from selected source” (Google Sheet)**  
     Calls `_refresh_from_online_sheet()` → writes only to `generic_tab_data` with `source = 'gsheet'`.  
   So each refresh updates only that source's copy of the tabs; no blending and no overwriting across sources.

3. **Who reads**  
   - **list_generic_tab(tab_id)** uses `st.session_state["data_source"]` (salesforce or gsheet) so the app always reads from the **selected** source’s data.  
   - **Kitchen Master Data** (when not using Superset): reads from the selected source’s Kitchens / Master Kitchens list.  
   - **Data section**: when `data_source == "gsheet"` it only shows the Kitchens tab; otherwise it shows all tabs for the selected source.  
   - **Dashboard**: same; data is from the selected source.

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

- **No mix**: SF data is stored under `source = 'salesforce'` and is loaded only from Salesforce credentials. GSheet data is under `source = 'gsheet'`. Refreshing one source never overwrites the other.  
- **Clear labelling**: SF vs GSheet is only chosen in **Data**; the app reads and displays only that source’s data for all tabs.
