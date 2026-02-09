# Goal 5: Replace the Google Sheet with the Web Tracker

**Replace the gsheet with the web-based KSA Kitchen Tracker.** The sheet is not a good option for the team: filtering, updating, and finding data are error-prone when everyone uses different views. The web tracker fixes that.

---

## Why replace the gsheet?

| Problem with the sheet | How the web tracker helps the team |
|------------------------|------------------------------------|
| **Filtering** | Each person’s filters hide different rows → easy to edit or update the wrong thing | Filters only change what you *see*; they never change or delete data. Same logic for everyone. |
| **Updating** | Different views → some people update rows others can’t see → incorrect or duplicate updates | Single source of truth. Add and edit in one place; everyone’s view is consistent. |
| **Finding data** | Hard to be sure you’re looking at the same set of rows as others | Clear filters (date, site, region, metric); “Showing X of Y records”; same export format for everyone. |

**Use this app for all KSA Kitchen Tracker work.** Import from the sheet once (steps below), then use **Kitchen Tracker** and **Exports** here. Retire or archive the sheet so the team has one place to filter, update, and find data.

**Sheet reference (current):** Spreadsheet ID `1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8`, tab gid `1341293927`.

---

## Migrate from the Sheet to the web tracker

### 1. Export the correct tab from Google Sheets

1. Open the sheet: [link above](https://docs.google.com/spreadsheets/d/1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8/edit?gid=1341293927#gid=1341293927).
2. Select the **tab** you use for the Kitchen Tracker (the one with gid=1341293927).
3. **File → Download → Comma-separated values (.csv)**.  
   This downloads only the **current tab** as a CSV.

### 2. Align columns (if needed)

The web tracker expects these columns (any casing/spacing variants are accepted on import):

| Tracker field  | Required | Notes                          |
|----------------|----------|--------------------------------|
| record_id      | Yes      | Unique ID per row              |
| report_date    | Yes      | YYYY-MM-DD                     |
| site_id        | Yes      |                                |
| site_name      | No       |                                |
| region         | Yes      | e.g. KSA                       |
| metric_name    | Yes      | e.g. inventory_count, orders_today |
| value          | No       | Number or empty                |
| status         | No       | e.g. OK, Low                   |
| notes          | No       |                                |

If your sheet uses different headers (e.g. "Record ID", "Report Date"), the app’s import will try to map common variants. If your sheet has extra columns, they are ignored on import.

### 3. Import into the web tracker

1. Run the web tracker: from repo root  
   `python -m streamlit run app/tracker_app.py`  
   (or use `app/run_tracker_app.bat`).
2. Open the **About** tab.
3. Under **Import from CSV (e.g. from Google Sheet)**, click **Upload CSV** and choose the file you downloaded.
4. The app imports all rows that have `record_id`, `report_date`, `site_id`, `region`, and `metric_name`. Duplicates (same `record_id`) overwrite existing rows.

### 4. After migration

- **Single source of truth:** Everyone uses the web tracker; no more editing the sheet for this data.
- **ETL:** Keep running your existing ETL (e.g. `run_sqlite_ksa.py`) so it reads from the app’s database and writes `data/output/ksa_kitchen_tracker.csv` for Looker Studio.
- **Standardized export:** Use the tracker’s **Export for stakeholders** tab to download the same CSV format anytime.

---

## Goal 5 deliverables (mapping)

| Deliverable | How the web tracker helps |
|-------------|---------------------------|
| **Revamp Kitchen Trackers (structure & visibility)** | One app with clear tabs (List/Filter/Edit, Add, Export, About); summary metrics; filters are view-only. |
| **Trackers reflect latest data & business logic** | All edits in one DB; ETL reads from it; schema validation in ETL. |
| **Standardize tracker outputs** | **Export for stakeholders** and ETL both produce the same CSV format. |
| **Stretch: Document generators (Contracts, KA, Proposals)** | Planned; see “Stretch roadmap” below. |
| **Stretch: Reduce manual doc effort / faster commercial docs** | Same. |

---

## Stretch roadmap: document generators

Planned for the next phase:

1. **Integrate document generators** — Templates for Contracts, KA (Knowledge Assessment?), Proposals; fill from tracker or linked data.
2. **Reduce manual document creation** — Pre-filled drafts from tracker + project metadata.
3. **Improve turnaround for commercial documentation** — Fewer steps from tracker state → draft → final.

When you’re ready, we can add a **Document generator** tab or a separate small app that reads from the same DB (or exported CSV) and produces PDF/Docx drafts.

---

## Optional: keep the sheet in sync (read-only)

If you still want the sheet for viewing only:

- Use **Export for stakeholders** (or ETL output) and periodically re-import that CSV into a **copy** of the sheet, or use Google Sheets’ “Import from CSV” so the sheet is a read-only mirror.  
- Best long-term: treat the **web tracker as source** and the sheet as deprecated or view-only.
