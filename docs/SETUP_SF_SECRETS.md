# Setup Salesforce Secrets (fix "No SOQL or Report IDs configured")

Add these to your Streamlit secrets.

## Streamlit Cloud (share.streamlit.io)

1. Open your app → **Settings** (or **Manage app**) → **Secrets**
2. Paste this (replace Report IDs with yours):

```toml
[sf_tab_queries]
"SF Kitchen Data" = "00O6T000006Y0l6UAC"
"SF Churn Data" = "00O6T000006Y5DiUAK"
"Sellable No Status" = "00O6T000006DXT0UAO"
"All no status kitchens" = "00O6T000006DPigUAG"
"Price Multipliers" = "00OVO000003z2O92AI"
"Area Data" = "00O6T000006Y0l6UAC"
```

3. Add SF auth at the top (if not already):

```toml
SF_INSTANCE_URL = "https://your-org.my.salesforce.com"
SF_ACCESS_TOKEN = "your_token"
```

Or use refresh token flow (see DEPLOY_SALESFORCE_REPORTS.md).

4. **Save** → **Reboot app**

## Local (.streamlit/secrets.toml)

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
2. Uncomment and fill:

```toml
[sf_tab_queries]
"SF Kitchen Data" = "00O6T000006Y0l6UAC"
```

3. Add SF auth (SF_INSTANCE_URL, SF_ACCESS_TOKEN or refresh token)
4. Restart the app
