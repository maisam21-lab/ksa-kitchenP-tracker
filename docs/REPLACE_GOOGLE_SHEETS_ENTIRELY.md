# Replace Google Sheets Entirely

This doc describes a **full replacement** for Google Sheets: a **database + app** where designated users add, edit, and remove entries, and the **ETL** (this project) reads from that source and feeds Looker Studio. No Sheets in the path.

---

## Target Architecture (No Sheets)

```
┌─────────────────────────────────────┐     ┌──────────────────────────────────┐     ┌─────────────────┐
│  Tracker app + database             │────▶│  ETL (this project)                │────▶│  Looker Studio  │
│  • Designated users: add, edit,      │     │  • Extract from DB/API              │     │  Read-only      │
│    remove entries                   │     │  • Validate → Transform → Load     │     │  (output only)  │
│  • Schema enforced at write time    │     │  • Output: BigQuery / CSV           │     └─────────────────┘
│  • No filters, no per-user view     │     └──────────────────────────────────┘
└─────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Database (single source of truth)   │
│  e.g. BigQuery, Postgres, Firestore │
│  • Tables for KSA Kitchen Tracker,   │
│    execution log, etc.               │
└─────────────────────────────────────┘
```

---

## Options to Replace Sheets

### Option A: AppSheet (Google, no code)

- **What:** Build an app on top of a data source (BigQuery, Cloud SQL, or Google Sheets as backend — you can start with Sheets and later switch the backend to BigQuery/Cloud SQL).
- **Users:** Add, edit, remove rows via the app; permissions by role.
- **ETL:** If the backend is **BigQuery** or **Cloud SQL**, this project’s ETL reads directly from that database (no Sheet). If you keep Sheets as AppSheet’s backend temporarily, ETL still reads from the Sheet until you migrate the backend.
- **Pros:** No code, Google ecosystem, mobile-friendly. **Cons:** Backend can still be a Sheet until you migrate; vendor lock-in.

### Option B: Airtable (implemented)

- **What:** Database + UI (tables, forms, views). Designated users edit in Airtable; no “sheet” filters affecting the stored data.
- **Users:** Add, edit, remove records; permissions per base/table.
- **ETL:** This project’s ETL reads from **Airtable API** (or Airtable → export/sync to BigQuery if you prefer). Add an “extract_airtable” step; validate and load as today.
- **Pros:** Fast to set up, good UX. **Cons:** Cost at scale; you depend on Airtable API.
- **Setup:** See [AIRTABLE_SETUP.md](AIRTABLE_SETUP.md). Config: `config/sources_airtable_ksa.yaml`; run `python run_airtable_ksa.py`.

### Option C: Retool / low-code internal app

- **What:** Internal app (forms, tables) backed by **Postgres** or **BigQuery**. Users do CRUD in the app; data lives only in the database.
- **Users:** Add, edit, remove via app; access controlled in Retool.
- **ETL:** This project’s ETL reads from **Postgres/BigQuery** (same schema as your current KSA tracker); validate and load to the reporting output (e.g. BigQuery dataset for Looker).
- **Pros:** Full control, schema in your DB, no Sheets. **Cons:** Requires hosting DB + Retool (or similar).

### Option D: Custom app + database

- **What:** Simple web app (e.g. React/Vue + API) or script + **Postgres** or **BigQuery**. Designated users use the app to add, edit, remove entries; all data in the DB.
- **Users:** CRUD via the app; auth and roles in your app.
- **ETL:** This project’s ETL reads from **Postgres/BigQuery** (e.g. `config/sources.yaml` points to DB; extract step runs a query or reads a table), then validate and load to the reporting output.
- **Pros:** Full control, no vendor dependency for data. **Cons:** Build and maintain the app and DB.

### Option E: BigQuery + scheduled export / simple UI

- **What:** Store tracker data in **BigQuery** tables. Users edit via a **scheduled export** (e.g. CSV they fill) that you load into BigQuery, or a **very simple UI** (e.g. Cloud Functions + HTML form, or Colab/Streamlit) that writes to BigQuery.
- **ETL:** This project’s ETL reads from those BigQuery tables, validates (and optionally transforms), and writes to the **reporting dataset** (e.g. `bi_modeled`) that Looker Studio uses. So: one BigQuery dataset for “tracker” (editable by app/process), one for “reporting” (read-only, ETL output).
- **Pros:** Single platform (GCP), Looker Studio native. **Cons:** You still need a minimal “editor” (form or process) unless you use something like AppSheet/Retool on top.

---

## What This Project Does in a “No Sheets” Setup

1. **Config** — `config/sources.yaml` (or equivalent) points to the **database or API** (e.g. BigQuery table, Postgres connection, Airtable API), not to a Sheet or CSV.
2. **Extract** — New or updated extract step:
   - **BigQuery:** Query the tracker table(s) and read results.
   - **Postgres:** Same via `psycopg2` or SQLAlchemy.
   - **Airtable:** HTTP client for Airtable API, map to rows.
3. **Validate** — Unchanged: same schemas (e.g. `config/schemas/ksa_kitchen_tracker.json`), validate rows, quarantine invalid.
4. **Transform / Load** — Unchanged: transform and write to the reporting output (e.g. `data/output/` or BigQuery `bi_modeled`).
5. **Looker Studio** — Connects only to the **ETL output** (BigQuery or published CSV). No Sheets.

So: **the ETL layer stays; only the source changes from “Sheet/CSV” to “database or API”.**

---

## Suggested Path (Replace Sheets Entirely)

1. **Choose the new “tracker” source:**
   - **Fastest:** AppSheet (backend = BigQuery or Cloud SQL) or Airtable → ETL reads from API/DB.
   - **Most control:** Retool or custom app + Postgres/BigQuery → ETL reads from DB.
2. **Define the schema** in the DB (or Airtable base) to match your current KSA tracker (e.g. same columns as `config/schemas/ksa_kitchen_tracker.json`).
3. **Migrate data:** One-time export from Sheets → load into the new DB/app (e.g. CSV import into Airtable, or script into BigQuery/Postgres).
4. **Point this project’s ETL** at the new source (add extract step for that DB/API in `pipeline.py` and `config/sources.yaml`).
5. **Switch Looker Studio** to the ETL output only (already read-only); stop using any Sheet as a data source.
6. **Retire the Sheet** once the new app is the only place users edit.

---

## Summary

| Goal | Approach |
|------|----------|
| **Replace Google Sheets entirely** | Use a **database + app** (AppSheet, Airtable, Retool, or custom) for add/edit/remove; **ETL reads from that DB/API** and writes the reporting output; **Looker Studio reads only the ETL output**. |
| **This project** | Same validate/transform/load; only **extract** changes from Sheet/CSV to **DB or API**. |
| **Result** | No Sheets in the path; single source of truth in your DB; reporting from ETL output only. |
