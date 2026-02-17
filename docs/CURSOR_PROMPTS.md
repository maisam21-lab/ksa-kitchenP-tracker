# Cursor prompts — KSA Kitchen Tracker (agreed requirements)

Copy one prompt block below into Cursor when you want to implement that feature. The app lives in `app/tracker_app.py`; DB in `app/data/tracker.db`. Sidebar currently uses `st.sidebar.radio("Section", ["Master Kitchens", "Dashboard", "Discussions", "Data", "Search"])`. There is already an allowed list (`_allowlist_enabled`, `is_user_allowed`) and developer unlock.

---

## Prompt 1 — RBAC + roles (allowed list → role)

```
We have a Streamlit app (KSA Kitchen Tracker) in app/tracker_app.py.
Implement role-based access control using the existing allowed list.

Requirements:
- Use the email/name from the sidebar (st.session_state["user_display_name"] or query param email) as the user identifier.
- Extend the allowed list to map: email -> role (not just allowed/denied).
- Roles: associate_viewer (only "Master Kitchens"), manager_viewer ("Master Kitchens" + "Live Dashboard"), super_user (all pages including tools).
- If user is not in allowed list, keep current behavior (access restricted message) or show "Access denied" with contact.
- Sidebar must ONLY show sections the user's role allows (no disabled items).
- Store role in st.session_state (e.g. "user_role") after resolving from allowed list.

Deliverable:
- A small auth helper (e.g. in app/auth.py or at top of tracker_app.py): get_user_role(email) -> "associate_viewer" | "manager_viewer" | "super_user" | None, and require_role(min_role) if needed.
- Allowed list format: support email -> role in secrets or DB (e.g. allowed_users table or TOML [allowed_users] "email@x.com" = "manager_viewer").
- Main app: build the sidebar section list dynamically from role (associate sees only Master Kitchens; manager sees Master Kitchens + Live Dashboard; super_user sees everything).
```

---

## Prompt 2 — Sidebar layout (Master Kitchens, Dashboard, Tools, Admin)

```
Update the Streamlit sidebar in app/tracker_app.py to match this structure by role:

- Everyone (associate_viewer+): Master Kitchens
- manager_viewer and super_user: Master Kitchens, Live Dashboard
- super_user only: add these under a "TOOLS" section — Currency Converter, Inflation Calculator, Price Multipliers — and "ADMIN" — Admin / Data Health

Use section headers in the sidebar for "TOOLS" and "ADMIN" (e.g. st.sidebar.markdown("**TOOLS**")) so super users see a clear grouping.
Associates must see only "Master Kitchens" in the Section radio (no other options). Managers see "Master Kitchens" and "Live Dashboard". Super users see all sections including Tools and Admin.
Base visibility on st.session_state.get("user_role") from the RBAC implementation.
```

---

## Prompt 3 — Data source: Salesforce default, GSheet backup

```
In app/tracker_app.py we have two data sources: Salesforce (real-time) and Google Sheet (refresh from online sheet). st.session_state["data_source"] is already set to "salesforce" or "gsheet" after refresh.

Requirements:
- Treat Salesforce as the default for live data (already done on first load: try _refresh_from_salesforce first).
- Data source selector (which source to display) should be visible only to manager_viewer and super_user. Associates always use Salesforce data (do not show them the selector).
- Show "Last refresh" timestamp for the active source (store last_refresh_salesforce and last_refresh_gsheet in session state or a small table when refresh runs).
- If Salesforce refresh fails, automatically fall back to Google Sheets and show a warning banner (e.g. "Salesforce unavailable; showing data from Google Sheet backup").
```

---

## Prompt 4 — Master Kitchens page improvements (filters, status pills)

```
Improve the Master Kitchens section in app/tracker_app.py to be sales-friendly:

- Add quick status filter pills/buttons at the top: All | Vacant | Churning | Occupied | Sold (filter the table by status column).
- Add a facility filter dropdown (distinct from Account Name or facility column in the data).
- Keep global search, column selector, and export as they are.
- Add a "Last refresh: <timestamp>" label at the top of the page (use the last refresh time for the current data source).
- Ensure the page stays fast (keep using _dashboard_load_source and existing caching).
- The data comes from Kitchens or Master Kitchens list; ensure status and facility columns exist or are derived for filtering.
```

---

## Prompt 5 — Daily snapshot table (for "what changed today")

```
We need daily change tracking (vacant/churning changes vs yesterday) for the Live Dashboard.
Implement a daily snapshot system in the KSA Kitchen Tracker app.

Requirements:
- Create a storage layer: a new table in app/data/tracker.db (e.g. kitchen_daily_snapshot) or a CSV/file under app/data/.
- Snapshot grain: one row per kitchen per day. Columns: snapshot_date, kitchen_id (or facility_id + kitchen_name), facility, kitchen_name, status, churn_date (if available), floor_price (optional).
- When the app loads (for manager_viewer or super_user), if today's snapshot does not exist, create it from the current Kitchens/Master Kitchens data (list_generic_tab("Kitchens") or equivalent).
- Provide helper functions: write_daily_snapshot(rows), load_snapshots(last_n_days), compute_daily_changes(today_df, yesterday_df) returning e.g. list of dicts with facility, kitchen_name, yesterday_status, today_status.
- Use the same schema as the Kitchens tab where possible (kitchen id, facility, status, etc.) so we can join.
- Document the new table in docs or in code comments.
```

---

## Prompt 6 — Live Dashboard page (Managers)

```
Build a "Live Dashboard" section in app/tracker_app.py, visible only to manager_viewer and super_user.

Requirements:
- KPI cards: Vacant today, Churning today, Occupied today, Sold today (counts from current Kitchens data).
- Add "Change vs yesterday" for Vacant and Churning (use the daily snapshot and compute_daily_changes).
- Trend chart (last 30 days): vacant count and churning count per day (use load_snapshots(30) and aggregate by date).
- Table: "What changed today" — kitchens where status changed vs yesterday; columns: facility, kitchen_name, yesterday_status, today_status.
- Use the snapshot module (write_daily_snapshot, load_snapshots, compute_daily_changes). Ensure dashboard uses caching so it loads fast.
- Add "Live Dashboard" to the sidebar Section radio for manager and super_user roles only.
```

---

## Prompt 7 — Super User tool: Currency Converter

```
Create a "Currency Converter" page in the KSA Kitchen Tracker app, visible only to super_user (in the TOOLS section of the sidebar).

Requirements:
- Simple UI: Amount (number input), From currency (dropdown, e.g. SAR, USD), To currency (dropdown). Show converted value using a stored FX table.
- Store FX rates in app/data/tracker.db (e.g. table fx_rates: from_currency, to_currency, rate, updated_at) or a small JSON/TOML config; use static rates for now (e.g. SAR/USD).
- Optional: add a "Display currency" toggle for the Master Kitchens page (SAR vs USD) for manager_viewer and super_user only; associates see SAR only. If you add this, ensure Master Kitchens table can show converted floor_price/list_price when USD is selected (use the same fx_rates).
- Implement in a small module (e.g. app/fx.py) with get_rates() and convert(amount, from_c, to_c).
```

---

## Prompt 8 — Super User tool: Inflation Calculator

```
Create an "Inflation Calculator" page in the KSA Kitchen Tracker app, visible only to super_user (TOOLS section).

Requirements:
- Inputs: facility go-live date (date picker), base price (number). Optional: inflation rate or CPI factor (configurable).
- Outputs: years since go-live, inflation factor, recommended adjusted price (base * inflation factor). This is a recommendation only; do not write to any pricing table.
- Create a table or schema for future use: facility_inflation_model (facility_id, go_live_date, inflation_index, recommended_multiplier) if we want to persist recommendations later; for now a read-only calculator is enough.
```

---

## Prompt 9 — Super User tool: Price Multipliers Manager

```
Create a "Price Multipliers" page in the KSA Kitchen Tracker app, visible only to super_user (TOOLS section).

Requirements:
- Table view by facility: facility_id / facility_name, current_multiplier, suggested_multiplier (editable in the UI), last_updated_by, last_updated_at.
- Persist suggested_multiplier (e.g. in app/data/tracker.db table facility_multipliers: facility_id, current_multiplier, suggested_multiplier, updated_by, updated_at).
- Validation: multiplier must be numeric and between 0.5 and 3.0.
- Export button to download the table as CSV.
- Implement CRUD in a small module (e.g. app/multipliers.py) and call it from the Price Multipliers section.
```

---

## Prompt 10 — Admin / Data Health page (Super user only)

```
Create an "Admin / Data Health" section in app/tracker_app.py, visible only to super_user (ADMIN section in sidebar).

Requirements:
- Show: current user email and role, data source health (Salesforce OK / error, last refresh time; Google Sheet last refresh time), snapshot status (e.g. "Today's snapshot: written" or "Not yet written").
- Manual refresh button: trigger _refresh_from_salesforce() or _refresh_from_online_sheet() and update last refresh timestamps (safe refresh of data only).
- Section to view the allowed list (read-only): list of emails and their roles from the allowed list config/DB.
- Keep the page minimal and professional (no sensitive secrets in UI).
```

---

## Implementation order (suggested)

1. **Prompt 1** — RBAC + roles (allowed list → role).  
2. **Prompt 2** — Sidebar layout by role.  
3. **Prompt 4** — Master Kitchens improvements (status pills, facility filter, last refresh).  
4. **Prompt 3** — Data source default + selector visibility by role.  
5. **Prompt 5** — Daily snapshot table.  
6. **Prompt 6** — Live Dashboard.  
7. **Prompts 7–10** — Tools and Admin (Currency, Inflation, Multipliers, Data Health).

Use one prompt at a time in Cursor for focused changes.
