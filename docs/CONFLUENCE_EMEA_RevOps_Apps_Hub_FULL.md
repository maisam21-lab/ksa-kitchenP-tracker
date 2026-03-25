# EMEA RevOps Apps Hub

Central hub for all EMEA RevOps team applications, ownership, access, SLAs, and support information.

---

## 1. App Catalog Overview

This section provides a catalog of all EMEA RevOps applications, including a short description, primary use case, and lifecycle status.

| App Name | Description | Primary Use Case | Lifecycle Status |
|----------|-------------|------------------|------------------|
| **EMEA RevOps App Marketplace** | Single entry point listing all EMEA RevOps apps. Team members open one link to find and launch any app (e.g. KSA Kitchen Tracker) without managing separate URLs. | Central discovery and access to all RevOps tools; onboarding and self-service. | Active |
| **KSA Kitchen Tracker** | Master Kitchens data, Dashboard (metrics, churn, occupancy), and Discussions. View and filter kitchen data, track KPIs, and collaborate on operations for KSA. | Pipeline hygiene, kitchen/territory visibility, operational reporting, team discussions. | Active |

---

## 2. Ownership & Responsibilities

| App Name | Business Owner Role | Technical Owner Role | Key Responsibilities |
|----------|---------------------|----------------------|------------------------|
| **EMEA RevOps App Marketplace** | EMEA RevOps Lead / GTM Operations Manager | Maysam Abu Kashabeh (RevOps / Business Systems) | Business: approves which apps are listed and who can access the hub. Technical: maintains marketplace deployment on Streamlit Cloud, adds/removes apps via marketplace_config.yaml, coordinates redeploys. |
| **KSA Kitchen Tracker** | EMEA RevOps Lead / Operations Manager | Maysam Abu Kashabeh (RevOps / Business Systems) | Business: approves feature requests, data scope, and deprecation. Technical: manages allowlist and roles (normal vs super user), data refresh (Google Sheets, BigQuery, Salesforce), and Streamlit deployment. |

---

## 3. Access & Environments

| App Name | Access Request Process | Primary Login / Portal |
|----------|------------------------|-------------------------|
| **EMEA RevOps App Marketplace** | Open to all EMEA RevOps team members. No approval needed; link is shared via this Confluence page and Slack. | **YOUR TURN:** Add your marketplace URL here after you deploy it (e.g. https://your-app-name.streamlit.app/) |
| **KSA Kitchen Tracker** | Request access from Maysam Abu Kashabeh or EMEA RevOps Lead. Provide your work email; it is added to the app allowlist. Roles: **Normal** (Master Kitchens + Discussions) or **Super user** (+ Dashboard). Sign in with Google (recommended) or contact Maysam for access. | https://ksa-kitchenp-tracker-dcl4vvscpgpgeamjbmpnyj.streamlit.app/ |

---

## 4. SLAs & Support Expectations

| App Name | Support Hours | Target Response / Resolution |
|----------|---------------|-----------------------------|
| **EMEA RevOps App Marketplace** | EMEA working hours (e.g. 09:00–17:00 local). No on-call unless agreed. | Best effort: link or config issues within 1–2 business days. Critical (marketplace down): same-day response. |
| **KSA Kitchen Tracker** | EMEA working hours. Data refresh runs on schedule (e.g. every 15 min from Google Sheet; BigQuery cache ~3 min). | Best effort: access or data issues within 1–2 business days. Critical (app down or data stale): same-day response. Resolution may depend on upstream (Sheets, BigQuery, Salesforce). |

---

## 5. Support & Escalation Contacts

| App Name | Primary Support Channel | Escalation Path |
|----------|-------------------------|-----------------|
| **EMEA RevOps App Marketplace** | **YOUR TURN:** Add your Slack channel (e.g. #revops-apps or #emea-revops). For “app missing” or “wrong link” contact Maysam Abu Kashabeh. | If not resolved in 1–2 days → EMEA RevOps Lead → IT/Business Systems if platform issue. |
| **KSA Kitchen Tracker** | **YOUR TURN:** Add your Slack channel (e.g. #ksa-tracker or #emea-revops). Access requests: Maysam or EMEA RevOps Lead. Technical (login, data, roles): Maysam Abu Kashabeh. | Unresolved access or data issues → EMEA RevOps Lead. Security or data residency concerns → Security/Legal per company process. |

---

## 6. Change Management & Governance

- **App intake and evaluation:** New apps for EMEA RevOps are evaluated for fit with existing processes (forecasting, territory planning, pipeline hygiene). Alignment with global RevOps standards and tooling is confirmed before listing in the marketplace.
- **Security, privacy, and data residency:** Before onboarding a new app, complete security and privacy review. For cloud apps (e.g. Streamlit Cloud), confirm data handling and region. Data residency requirements for EMEA are checked (e.g. EU data in EU where required).
- **Approval workflow:** New app or marketplace listing: RevOps Lead approves use case; Business Systems/IT approves technical and security; Finance approves if there is cost. Renewals follow the same path where applicable.
- **Decommissioning:** When an app is deprecated: (1) Communicate timeline to users via Confluence and Slack. (2) Export or archive data as needed. (3) Remove from marketplace and revoke access. (4) Document in this hub and archive any runbooks.

---

## Checklist before you publish

Replace only these:

1. **Section 3 – EMEA RevOps App Marketplace, Primary Login / Portal:** Paste your marketplace URL once it is deployed (from Streamlit Cloud).
2. **Section 5 – Primary Support Channel:** Replace **YOUR TURN** with your real Slack channel(s), e.g. `#revops-apps` or `#emea-revops`.
3. **Section 2 – Business Owner:** If “EMEA RevOps Lead / GTM Operations Manager” is a specific person in your org, replace with their name/role if you prefer.
4. **Section 2 – Technical Owner:** If someone other than Maysam owns an app, update that row.

Everything else is filled in and ready to paste into Confluence.
