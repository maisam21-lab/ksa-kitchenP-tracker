# BI ETL Foundation — Architecture

## Problem Summary

| Issue | Cause |
|-------|--------|
| **Partial updates** | Writes happen on filtered/sorted views; only visible rows get updated |
| **Inconsistent state** | Filters, sorting, hidden rows are per-user; no single view of data |
| **No schema / immutability** | Sheets allow free-form edits; no validation or audit trail |
| **Data trust** | Dashboards reflect “who last touched the sheet” instead of a canonical dataset |
| **Manual rework** | BI teams debug sheets instead of building insights |

Root cause: **editable, stateful Google Sheets** used as the data layer between sources and Looker Studio.

---

## Desired Outcome

- **Single source of truth** — One canonical dataset per subject area for **reporting** (not locking the tracker).
- **Standardized, validated data** — Schema enforcement and validation before data is used for dashboards.
- **Editable tracker, read-only reporting** — Designated users can add, edit, and remove entries in the tracker (Sheet or app); dashboards and Looker Studio **only read** from the ETL output (so reporting is stable and not affected by filters or concurrent edits).
- **No manual intervention in the pipeline** — ETL runs on a schedule or on demand; no shared-state or filter-induced errors in the **output** that reporting uses.

---

## Who Can Do What

| Role | Tracker (source) | ETL output (for reporting) |
|------|------------------|----------------------------|
| **Designated users** | Add, edit, remove entries (e.g. in Google Sheet or an app) | — |
| **ETL** | Reads current state (no editing) | Writes validated snapshot |
| **Everyone / BI / Looker Studio** | — | **Read only** (dashboards consume this; no editing here) |

The tracker stays **editable** by specific users. Only the **output** that feeds dashboards is read-only, so reporting is consistent.

---

## Target Architecture

```
┌─────────────────────────────┐     ┌──────────────────────────────────────────┐     ┌─────────────────┐
│  Tracker (editable)         │────▶│  ETL Layer (this project)                 │────▶│  Looker Studio  │
│  Designated users: add,     │     │  • Extract → Validate → Transform → Load  │     │  Read-only      │
│  edit, remove entries       │     │  • Validated snapshot for reporting       │     │  (consumes      │
│  (e.g. Google Sheet or app) │     │  • Schema + business rules                │     │   output only)  │
└─────────────────────────────┘     └──────────────────────────────────────────┘     └─────────────────┘
                                                │
                                                ▼
                                   ┌──────────────────────────────────────────┐
                                   │  Output / Warehouse                        │
                                   │  (e.g. data/output/, BigQuery)             │
                                   │  Read-only for reporting; ETL writes here  │
                                   └──────────────────────────────────────────┘
```

---

## ETL Layer Responsibilities

1. **Extract** — Pull current state from the tracker (Sheet or app) on a schedule or on demand. The tracker remains editable by designated users; ETL only reads.
2. **Validate** — Enforce schema (types, nullability, allowed values) and business rules; reject or quarantine invalid rows.
3. **Transform** — Clean, standardize, aggregate; produce modeled tables (e.g. star/snowflake for BI).
4. **Load** — Write validated snapshot to output/warehouse. Reporting (Looker Studio, dashboards) reads from here only.
5. **Expose** — Looker Studio and dashboards connect to the output (read-only). Designated users continue to add/edit/remove entries in the tracker; ETL refreshes the output from the tracker.

---

## Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Single source of truth** | All reporting comes from ETL outputs in the warehouse; no parallel “live” sheets. |
| **Schema enforcement** | Declarative schemas (e.g. JSON Schema / YAML); validation on every run. |
| **Immutability** | Append or full refresh with run_id/loaded_at; no in-place edits by users. |
| **Auditability** | Log runs, row counts, validation errors; optional lineage. |
| **Repeatability** | Idempotent pipelines; same inputs → same outputs. |

---

## Tracker vs Output

- **Tracker (e.g. Google Sheet)** — Stays **editable** by designated users (add, edit, remove entries). This is the operational source that people maintain.
- **ETL output (e.g. data/output/, BigQuery)** — **Read-only** for reporting. ETL writes a validated snapshot here; Looker Studio and dashboards read from this only, so they see consistent data and are not affected by filters or concurrent edits in the sheet.
- **Looker Studio** — Connects to the output (e.g. BigQuery or exported CSV), not directly to the editable sheet, so reporting is stable. Designated users keep editing the tracker; ETL refreshes the output on a schedule or on demand.

---

## Suggested Technology Options

- **Orchestration:** Cloud Scheduler + Cloud Functions, Airflow, or scheduled jobs (cron/CI).
- **Warehouse:** BigQuery (natural fit for Looker Studio), Snowflake, or Postgres.
- **Validation:** JSON Schema + a small Python/Node layer, or dbt tests + schema in dbt.
- **Transforms:** SQL in the warehouse (dbt, Dataform) or Python (Pandas, Polars) in the ETL code.

This repo provides a **Python-based ETL scaffold** (config, schema validation, pipeline pattern) that you can point at your sources and warehouse and extend per use case.

---

## Looker Studio: Read-Only Connection

1. **Do not** use Google Sheets as the data source for production metrics.
2. Run ETL into a **BigQuery dataset** (e.g. `bi_modeled`); only the ETL job writes to it.
3. In Looker Studio: **Add data** → **BigQuery** → choose that dataset and the ETL-produced tables/views.
4. Dashboards refresh from BigQuery on a schedule; no filters, sorting, or edits in the data layer. Single source of truth, repeatable refreshes, no shared-state errors.
