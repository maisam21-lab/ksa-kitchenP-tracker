# Salesforce data provider (mock / sandbox / prod)

The app can load Salesforce-backed data from three sources. Choose one via **SFDC_PROVIDER**.

## Set the provider

- **Streamlit secrets** (recommended): add `SFDC_PROVIDER = "mock"` (or `sandbox` / `prod`) under `[default]` or as a top-level key.
- **Environment**: `SFDC_PROVIDER=mock` (or `sandbox`, `prod`).

Default if unset: **prod**.

## Providers

| Provider | Use case |
|----------|----------|
| **mock** | No Salesforce access. Data is read from local JSON/CSV files. |
| **sandbox** | Use Salesforce sandbox (e.g. yazandev). Forces `SF_USE_SANDBOX=true` when getting the token. |
| **prod** | Use production Salesforce. Forces prod login when credentials support both. |

## Mock provider: local data

When `SFDC_PROVIDER=mock`, **Refresh from Salesforce** reads from `app/data/mock/` instead of calling the API.

- One file per tab. File name = tab name with spaces replaced by underscores.
- **Kitchens** tab → `Kitchens.json` or `Kitchens.csv`
- **SF Churn Data** → `SF_Churn_Data.json` or `SF_Churn_Data.csv`
- JSON: array of objects, e.g. `[{"Account Name": "X", "Status": "Active"}, ...]`
- CSV: first row = headers, same column names as the app expects.

Example: `app/data/mock/Kitchens.json` with a few rows is included so you can test the **Kitchens** tab without Salesforce.

**Keeping mock in sync with GSheet:** Export the relevant sheet(s) from your Google Sheet to CSV, rename to match the tab (e.g. `Kitchens.csv`), and place in `app/data/mock/`. Optionally commit to the repo so the team shares the same mock data.

## Sandbox / prod

- **sandbox**: Same credentials as prod, but the app forces sandbox login (`test.salesforce.com`). Use when you want to test against sandbox reports/data.
- **prod**: Forces production login. Use when your credentials can hit both and you want prod.

Your existing `sf_tab_queries` (Report IDs or SOQL) are used as-is; only the org (sandbox vs prod) is switched by the provider.
