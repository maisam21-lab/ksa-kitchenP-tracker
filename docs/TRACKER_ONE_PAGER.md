# Kitchen Tracker — One-Pager

**Single source of truth for kitchen inventory, occupancy, and revenue at risk. Built for ops and sales. Ready for multi-country rollout.**

---

## What it is

A **web app** that gives your team one place to see:

- **How many kitchens** you have by status (vacant, occupied, churning, sold) and by facility.
- **How much revenue** is in play: current book (occupied MRR), upside (vacant MRR), and **revenue at risk** (scheduled churn MRR).
- **Where to focus**: facility leaderboard by vacant MRR or churn MRR, plus kitchen-level inventory and churn dates.

Users get a **sales-first dashboard** (KSA at a glance, value cards, facility ranking, churn list) and **raw data** (Kitchen Master Data: filter by sheet, combine multiple sheets, search, download CSV). No more hunting across tabs or versions.

---

## Who it’s for

- **Ops / RevOps** — One view of occupancy, vacancy, and churn; formulas documented; data quality (missing price, Floor &gt; List) visible.
- **Sales** — Sold rate, vacant MRR, and scheduled churn MRR by facility; expandable facility and churn lists to prioritize accounts.
- **Leadership** — KSA (or country) at a glance; optional MRR/ARR toggle; same definitions everywhere.

---

## How it works (high level)

- **Data source:** Google Sheet (or Superset/Trino when configured). The app refreshes on a schedule; users can also trigger a refresh.
- **Access:** Allowlist + optional Sign in with Google; no URL-based identity. Role-based views (e.g. AEs see Dashboard + Kitchen Master Data + Discussions; developers also see Data, Search, Admin).
- **Dashboard:** Counts (kitchens, vacant, occupied, sold), value cards (Vacant / Scheduled Churn / Occupied MRR in USD), facility leaderboard (sort by vacant or churn MRR), inventory by facility, churn table (churn date, MRR at risk). Expandable sections and a “How these numbers are calculated” reference with all formulas.
- **Kitchen Master Data:** Select one or many sheets; view combined raw data with a “Sheet” column; search and download CSV. Explicit price logic (List/Floor primary–secondary) and QA (missing price counts, Floor &gt; List).

---

## Why it matters

- **One place:** Replaces scattered sheets and ad‑hoc tabs with a single, role-aware app.
- **Clear definitions:** Every rate and value has a stated formula and price rule; data quality is visible so finance knows the error margin.
- **Actionable:** Facility leaderboard and churn list tell teams where to focus; inventory and churn dates support renewal and backfill.

---

## Next launches: other countries

The same product can launch in **other countries** with minimal change:

1. **Data:** Point the app at that country’s Google Sheet (or equivalent) and, if needed, map sheet names/tabs. Same schema (status, facility, floor/list price, churn date) keeps the dashboard and formulas unchanged.
2. **Branding:** Swap “KSA” for the country or region in the at-a-glance bar and any labels (e.g. “UAE at a glance”, “Kuwait at a glance”). Optional: country selector and per-country sheets.
3. **Access:** Reuse the same allowlist/OIDC model; add country-specific roles or views if required.
4. **Deploy:** Same Stack (Streamlit Cloud or self-hosted). One codebase; config (sheet ID, optional Superset/Trino, feature flags) per country.

**Proposed rollout:** KSA (live) → UAE → Kuwait → Expand to other markets as needed. Each launch is: connect the sheet, set allowlist, flip the label to the new country, and go.

---

## Summary

| What | Detail |
|------|--------|
| **Product** | Kitchen Tracker — dashboard + raw data + discussions, one source of truth. |
| **Live today** | KSA (dashboard, Kitchen Master Data, value cards, facility/churn lists, formulas, QA). |
| **Next** | Same app for other countries; new sheet + config + label; no redesign. |
| **Ownership** | RevOps; built for ops and sales; ready for multi-country. |

---

*One-pager for internal use. For setup and deployment, see `docs/DEPLOY_TRACKER_FOR_TEAM.md` and `docs/REFRESH_FROM_ONLINE_SHEET.md`.*
