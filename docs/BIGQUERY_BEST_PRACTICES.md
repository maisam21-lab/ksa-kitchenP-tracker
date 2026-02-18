# BigQuery usage — best practices

## On-demand cost control

When using **on-demand pricing**, it is a best practice to:

- **Set and monitor daily query quotas** to manage resources and prevent cost overruns from large, unexpected data scans.

Configure quotas in Google Cloud Console: **Billing** → **Budgets & alerts**, and/or **BigQuery** → **Quotas** (query usage per day / per project). Use alerts so you’re notified before hitting limits.

## In this project

- **Master Kitchens query** (`docs/BIGQUERY_MASTER_KITCHENS.sql`) and **access test** (`scripts/test_bigquery_access.py`) run against `css-operations` (and optionally `ck_emea_apac_marketing`). Keep filters (e.g. country, Facility, `LIMIT` in ad‑hoc exploration) to reduce bytes scanned.
- For one-off exploration, prefer `SELECT * FROM ... LIMIT 10` or `SELECT COUNT(*)` over full table scans when possible.
