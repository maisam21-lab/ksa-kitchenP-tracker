# Agent handoff — KSA Kitchen Tracker (Streamlit)

This document orients the **next agent** on the **ksa-kitchenp-tracker** repo: what the app is, where logic lives, what changed recently, and how to work safely.

## Repo & remote

- **Primary app:** `app/tracker_app.py` (large single-file Streamlit app; most product logic lives here).
- **Python deps:** `requirements.txt` (Streamlit ≥ 1.33, streamlit-aggrid, pandas, etc.).
- **Git remote:** pushes may report that the repo moved to `https://github.com/maisam21-lab/ksa-kitchenP-tracker.git` (capital **P**). If pushes warn, align `origin` with that URL when convenient.

## How to run locally

```bash
cd ksa-kitchenp-tracker
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app/tracker_app.py
```

Sanity check after editing `tracker_app.py`:

```bash
python -m py_compile app/tracker_app.py
```

## Product surface (high level)

- **Sections (nav):** Built from `section_options` in `tracker_app.py` (role-based). Main kitchen workbook area is labeled **`KSA`** (constant `SECTION_KSA`), not the legacy string `"Kitchen Master Data"` (still migrated from session state if present).
- **Multi-country users** (`_user_sees_dashboard_all_countries`): Inside **KSA**, a **second row** of full-width buttons: **Kuwait | UAE | Bahrain** (plus **Main** when a regional workbook is selected on desktop; compact layout uses a **Market** selectbox). Default view is the **main KSA workbook** (no duplicate “KSA” chip in that sub-row).
- **Dashboard:** Merges KSA sources with optional Kuwait/UAE/Bahrain rows, go-live enrichment, filters, KPIs, inventory views.
- **Ag Grid:** Kitchen Master tables default to Ag Grid; row colors via Python-computed `km_row_cls` + `rowClassRules` + `custom_css` (not JsCode row styling). Enterprise modules may be on for Set Filter (watermark OK per product).

## RBAC, preview, and export (important)

- **Export gating:** `_can_user_export(current_user)` — only users in **`EXPORT_ALLOWED_IDS`** (code tuple merged with secrets/env via `_export_allowed_ids_from_secrets`) may export. **Developer / super_user does not imply export** unless listed.
- **Regional Kitchen Master (Kuwait/UAE/Bahrain):** `_user_can_see_bahrain_kitchen_preview` gates preview-style regional access. **`EXPORT_ALLOWED_IDS` users are treated as allowed for regional sheets too** so they can export **any** regional workbook they can open, not only KSA.
- **Dashboard “all countries” UX:** `_user_sees_dashboard_all_countries` — preview IDs, super_user, manager_viewer, developer paths (see function docstring).

## Data loading & SQLite

- **`list_generic_tab(tab_id, source=...)`** reads generic sheet tabs from SQLite (`generic_tab_data`) keyed by `source` (e.g. `gsheet`, `gsheet_kw`, `gsheet_ae`, `gsheet_bh`).
- **Kitchen Master KSA** path is refactored into **`_render_kitchen_master_ksa_main(*, can_export, is_developer)`** (Superset → BigQuery → Google Sheet fallbacks, combined facilities, pivot).
- **Regional preview:** **`_render_preview_regional_kitchen_master(region, ...)`** — Kuwait/UAE/Bahrain workbooks.

## Row filtering (“junk” / padding rows) — applies broadly

Central function: **`_filter_junk_kitchen_records`** → **`_should_hide_incomplete_kitchen_row`**.

Recent rules (verify against git history if needed):

1. **`_should_hide_missing_type_floor_and_kitchen_name_row`** — hide when **Type**, **Floor price**, and **Kitchen number/name** are all missing/empty (guarded so unrelated tabs are not wiped).
2. **`_should_hide_list_price_name_status_stage_sparse_row`** — hide rows where the only meaningful populated fields are **List price + Kitchen name** (+ optional **Status**, **Stage**, and **inventory KPI**-style columns). Treats **numeric zeros** in other columns as sheet padding; skips **`km_row_cls`** in the scan.
3. Other legacy rules: junk status combo, sparse “No status” rows, etc.

**Where filtering is applied (intentionally “everywhere” for kitchen-shaped data):**

- **`_render_generic_tab`** — after regional column trim, before render/export.
- **`_render_kitchen_master_ksa_main`** — table paths.
- **Dashboard pipeline** — after regional merge + go-live merge, **before** daily snapshot write (so snapshots match dashboard).
- **`_dashboard_load_gsheet_rows_with_sheet_stamp`** — returns filtered rows.
- **`_search_all_tabs`** — filters generic-tab matches.
- **`_dashboard_load_source`** — filters generic-tab loads.

**Not done:** Filtering inside **`list_generic_tab`** globally (would risk touching non-kitchen tabs).

## UI / Streamlit pitfalls

- **`tracker_app.py` “Kitchen Master Data” block** historically suffered **IndentationError** when the `if superset_rows` / `else` / render sections were mis-nested. After edits in that region, always run **`py_compile`**.
- **Streamlit reruns:** All script paths run each rerun; regional refresh helpers use stale checks to avoid hammering Sheets.

## Snapshot / rollback workflow

- **Manual snapshot (already on remote):** branch `snapshot/2026-04-09-app-stable` and tag `snapshot-2026-04-09-app-stable` (see `git tag -l`, `git branch -a`).
- **Routine before risky edits:** `scripts/pre_change_snapshot.ps1` + doc `scripts/PRE_CHANGE_SNAPSHOT.md` — creates timestamped **branch + tag** and pushes by default.

## Recent commits (context anchors)

Recent `main` history includes (non-exhaustive):

- `7e03cd5` — Export allowlist + regional access; pre-change snapshot script/docs.
- `5db106c` — Junk filter wired into Dashboard, snapshots, GSheet tab load, search.
- `9e964bc` / `28ff52c` / `9d344d2` — Sparse-row and missing-field hide rules.

Use `git log --oneline -20` for the exact sequence after this handoff is committed.

## Files the next agent will touch most

| Area | Location |
|------|-----------|
| All product logic | `app/tracker_app.py` |
| Row filters / export / nav | Same file: search `_filter_junk_kitchen_records`, `_can_user_export`, `SECTION_KSA`, `_user_sees_dashboard_all_countries` |
| Pre-change snapshots | `scripts/pre_change_snapshot.ps1`, `scripts/PRE_CHANGE_SNAPSHOT.md` |
| Secrets examples | `.streamlit/secrets.toml.example` |

## Suggested first steps for the next task

1. Read the user’s new request in full; grep `tracker_app.py` for keywords before large reads.
2. Run `python -m py_compile app/tracker_app.py` after substantive edits.
3. If changing Kitchen Master / Dashboard merge order, re-check **snapshot** placement and **filter** order (comments in Dashboard section explain intent).
4. Prefer small, focused diffs; avoid editing unrelated markdown unless asked.

## Contact / product

- Tracker is an internal **Kitchen Master** + **Dashboard** style app; allowlists and export lists are security-sensitive — do not broaden without explicit product sign-off.

---

*End of handoff. Commit this file so future agents can `git show docs/AGENT_HANDOFF.md`.*
