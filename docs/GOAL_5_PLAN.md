# Goal 5: Revamp Kitchen Trackers & Document Generators

**Weight:** 20%  
**Horizon:** Next 3 months (Core) + Stretch

---

## Goal Summary

| Type | Deliverables |
|------|--------------|
| **Core** | 1) Revamp all Kitchen Trackers (structure, visibility) · 2) Trackers reflect latest data and business logic · 3) Standardize tracker outputs for stakeholders |
| **Stretch** | 1) Integrate document generators (Contracts, KA, Proposals) · 2) Reduce manual document creation · 3) Improve turnaround for commercial documentation |

---

## How This Connects to the ETL Foundation

The **BI ETL Foundation** in this repo directly supports Goal 5:

- **Trackers reflect latest data** → Use the ETL pipeline as the single source of truth; trackers/dashboards consume **read-only** outputs instead of editable sheets.
- **Standardize tracker outputs** → Schema and validation in `config/schemas/` plus a single output format (e.g. BigQuery tables or standardized CSVs) so every tracker uses the same structure.
- **Reduce manual effort** → Automated refreshes and, for stretch, document generators that pull from the same validated data.

**Recommendation:** Treat “Kitchen Trackers” as **consumers** of the ETL layer (e.g. Looker Studio or read-only sheets fed by ETL), not as the place where data is edited or filtered.

---

## Core Deliverables — Checklist

### 1) Revamp all Kitchen Trackers (structure and visibility)

- [ ] **Inventory** — List every Kitchen Tracker (name, owner, current data source, refresh method).
- [ ] **Structure** — Define a common structure: same key columns (e.g. date, category, metric, owner), naming, and sheet/tab layout.
- [ ] **Visibility** — Decide what “improved visibility” means (e.g. dashboards, shared links, role-based views) and implement.
- [ ] **Revamp** — Apply the new structure to each tracker; retire or merge duplicates.

### 2) Trackers reflect latest data and business logic

- [ ] **Source of truth** — For each tracker, identify the canonical source (system, table, or ETL output); remove ad-hoc edits in sheets.
- [ ] **Refresh** — Ensure data is updated on a schedule (e.g. ETL run → BigQuery → Looker Studio or read-only sheet export).
- [ ] **Business logic** — Document rules (formulas, thresholds, status logic) and, where possible, move them into ETL or a single config so they’re consistent and auditable.

### 3) Standardize tracker outputs for stakeholders

- [ ] **Output contract** — Define one standard format (columns, types, grain) for “tracker output” used by stakeholders.
- [ ] **Single pipeline** — Where possible, produce these outputs from the ETL layer (e.g. `data/output/` or BigQuery views) so all stakeholders use the same dataset.
- [ ] **Docs** — Publish a short guide: where to find tracker data, how often it’s updated, and who to contact for changes.

---

## Stretch Deliverables — Checklist

### 1) Integrate document generators (Contracts, KA, Proposals)

- [ ] **List templates** — Contracts, KA (Knowledge Articles?), Proposals: list templates and required data fields.
- [ ] **Data source** — Feed generators from ETL/output layer (e.g. product list, pricing, terms) so documents use the same data as trackers.
- [ ] **Integration** — Wire templates to data (e.g. script or low-code tool that fills templates from CSV/API/BigQuery).

### 2) Reduce manual document creation effort

- [ ] **Automate** — Where possible, trigger document generation from the same pipeline or a scheduled job.
- [ ] **Reuse** — Standardize clauses, tables, and snippets so one change propagates to all document types.

### 3) Improve turnaround time for commercial documentation

- [ ] **SLA** — Define target turnaround (e.g. “Proposal within X hours”).
- [ ] **Bottlenecks** — Identify delays (data gathering, review, formatting) and address via automation or clearer handoffs.
- [ ] **Measure** — Track time-to-delivery and tie it to the same reporting/tracker layer where useful.

---

## Suggested Order of Work

1. **Inventory + structure** (Core 1) — Know what exists and what “good” looks like.
2. **Wire one tracker to ETL** (Core 2) — Prove “latest data” with one Kitchen Tracker fed from this repo’s pipeline (or your warehouse).
3. **Standardize output** (Core 3) — Lock the output schema and document it.
4. **Roll out** to remaining trackers (Core 1–3).
5. **Stretch** — Document generators and turnaround (Stretch 1–3).

---

## Tracker Progress (for your sheet or local use)

| Deliverable | Status | Notes |
|-------------|--------|--------|
| Core 1: Revamp Kitchen Trackers | Not started | |
| Core 2: Latest data & business logic | Not started | |
| Core 3: Standardize outputs | Not started | |
| Stretch 1: Document generators | Not started | |
| Stretch 2: Reduce manual doc effort | Not started | |
| Stretch 3: Turnaround time | Not started | |

Copy this table into your [goal tracker](https://docs.google.com/spreadsheets/d/1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8/edit?gid=1341293927#gid=1341293927) or use the CSV below for a quick import.
