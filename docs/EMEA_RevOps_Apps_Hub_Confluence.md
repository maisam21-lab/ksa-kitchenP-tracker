# EMEA RevOps Apps Hub

Central hub for all EMEA RevOps team applications, ownership, access, SLAs, and support information.

---

## 1. App Catalog Overview

This section provides a catalog of all EMEA RevOps applications, including a short description, primary use case, and lifecycle status.

| App Name | Description | Primary Use Case | Lifecycle Status |
|----------|-------------|------------------|------------------|
| **EMEA RevOps App Marketplace** | Single entry point listing all EMEA RevOps apps. Team members open one link to find and launch any app (KSA Tracker, etc.) without managing separate URLs. | Central discovery and access to all RevOps tools; onboarding and self-service. | Active |
| **KSA Kitchen Tracker** | Master Kitchens data, Dashboard (metrics, churn, occupancy), and Discussions. View and filter kitchen data, track KPIs, and collaborate on operations for KSA. | Pipeline hygiene, kitchen/territory visibility, operational reporting, team discussions. | Active |

---

## 2. Ownership & Responsibilities

| App Name | Business Owner Role | Technical Owner Role | Key Responsibilities |
|----------|---------------------|----------------------|------------------------|
| **EMEA RevOps App Marketplace** | EMEA RevOps Lead / GTM Operations Manager | [Technical owner name, e.g. Business Systems Engineer] | Business: approves which apps are listed and who has access. Technical: maintains marketplace deployment, adds/removes apps in config, coordinates with Streamlit Cloud. |
| **KSA Kitchen Tracker** | EMEA RevOps Lead / Operations Manager | [Technical owner name, e.g. Maysam or RevOps Systems] | Business: approves feature requests, data scope, and deprecation. Technical: manages allowlist, roles (normal vs super user), data refresh (Sheets/BigQuery/Salesforce), and Streamlit deployment. |

---

## 3. Access & Environments

| App Name | Access Request Process | Primary Login / Portal |
|----------|------------------------|-------------------------|
| **EMEA RevOps App Marketplace** | Open to all EMEA RevOps team members. No approval needed; link is shared via Confluence/Slack. | [Add marketplace URL after deploy, e.g. https://your-marketplace.streamlit.app/] |
| **KSA Kitchen Tracker** | Request access from [Business Owner / Maysam]. User email is added to allowlist (Streamlit secrets or Admin). Roles: Normal (Master Kitchens + Discussions) or Super user (+ Dashboard). Sign in with Google or developer key (admin only). | https://ksa-kitchenp-tracker-dcl4vvscpgpgeamjbmpnyj.streamlit.app/ |

---

## 4. SLAs & Support Expectations

| App Name | Support Hours | Target Response / Resolution |
|----------|---------------|-----------------------------|
| **EMEA RevOps App Marketplace** | EMEA working hours (e.g. 09:00–17:00 local). No on-call unless agreed. | Best effort: link/config issues within 1–2 business days. Critical (marketplace down): same-day response. |
| **KSA Kitchen Tracker** | EMEA working hours. Data refresh runs on schedule (e.g. every 15 min from Sheet; BigQuery cache ~3 min). | Best effort: access or data issues within 1–2 business days. Critical (app down or data stale): same-day response. Resolution depends on upstream (Sheets, BigQuery, Salesforce). |

---

## 5. Support & Escalation Contacts

| App Name | Primary Support Channel | Escalation Path |
|----------|-------------------------|-----------------|
| **EMEA RevOps App Marketplace** | [Add channel, e.g. Slack #revops-apps or Confluence comments]. For “app missing” or “wrong link”: contact Technical Owner. | If not resolved in 1–2 days → EMEA RevOps Lead → IT/Business Systems if platform issue. |
| **KSA Kitchen Tracker** | [Add channel, e.g. Slack #ksa-tracker or Maysam]. Access requests: Business Owner. Technical (login, data, roles): Technical Owner. | Unresolved access or data issues → EMEA RevOps Lead. Security or data residency concerns → Security/Legal per company process. |

---

## 6. Change Management & Governance

**Recommended elements to capture:**

- **App intake and evaluation:** New apps for EMEA RevOps are evaluated for fit with existing processes (forecasting, territory planning, pipeline hygiene). Alignment with global RevOps standards and tooling is confirmed before listing in the marketplace.
- **Security, privacy, and data residency:** Before onboarding a new app, complete security and privacy review. For cloud apps (e.g. Streamlit Cloud), confirm data handling and region. Data residency requirements for EMEA are checked (e.g. EU data in EU where required).
- **Approval workflow:** New app or marketplace listing: RevOps Lead approves use case; Business Systems/IT approves technical and security; Finance approves if there is cost. Renewals follow the same path where applicable.
- **Decommissioning:** When an app is deprecated: (1) Communicate timeline to users via Confluence and Slack. (2) Export or archive data as needed. (3) Remove from marketplace and revoke access. (4) Document in this hub and archive any runbooks.

---

*Replace bracketed placeholders (e.g. [Technical owner name], [Add marketplace URL], [Add channel]) with your actual values before publishing.*
