# Internal App Marketplace

A single page that lists your org's apps so people use **one link** instead of many.

## Run locally

```bash
streamlit run marketplace_app.py
```

## Deploy on Streamlit Cloud

1. In Streamlit Cloud, click **New app**.
2. Choose the same repo as your KSA tracker (`ksa-kitchenP-tracker`).
3. **Main file path:** `marketplace_app.py`
4. **Branch:** `main`
5. Deploy. Share the new app URL (e.g. `https://your-org-marketplace.streamlit.app/`) as the "marketplace" link.

## Add or edit apps

Edit **`marketplace_config.yaml`** in the repo:

```yaml
title: "Our apps"
subtitle: "Internal tools and dashboards."

apps:
  - name: "KSA Kitchen Tracker"
    description: "Master Kitchens, Dashboard, and Discussions."
    url: "https://ksa-kitchenp-tracker-xxx.streamlit.app/"
    owner: "Operations"
  - name: "Another app"
    description: "What it does."
    url: "https://another-app.streamlit.app/"
    owner: "Team name"
```

Push to the repo and **reboot the marketplace app** on Streamlit Cloud to refresh.
