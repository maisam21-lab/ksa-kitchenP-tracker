# Internal App Marketplace

**Goal:** All apps in one place, accessible for your team. Share a single link; team members open the marketplace and can find and launch any app (no more sharing individual app links).

## Run locally

```bash
streamlit run marketplace_app.py
```

## Deploy on Streamlit Cloud

**→ Step-by-step guide: [HOW_TO_DEPLOY_MARKETPLACE.md](HOW_TO_DEPLOY_MARKETPLACE.md)** — use this if you're not sure how to deploy.

Short version:
1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in. Click **"New app"**.
2. **Repository:** pick your GitHub repo (e.g. `maisam21-lab/ksa-kitchenP-tracker`). Same repo as the KSA tracker.
3. **Main file path:** This tells Streamlit which file to run for *this* app. You already have one app running from this repo (the KSA tracker, usually `app/tracker_app.py`). For the marketplace you’re adding a *second* app from the same repo. In the **"Main file path"** box, enter:  
   **`marketplace_app.py`**  
   So: one deployment runs `app/tracker_app.py` (KSA tracker), this new deployment runs `marketplace_app.py` (marketplace). The file `marketplace_app.py` sits at the root of the repo (same level as the `app` folder).
4. **Branch:** leave as `main` (or the branch you use).
5. Click **Deploy**. When it’s ready, you’ll get a URL like `https://something.streamlit.app/` — that’s your marketplace link. Share that one link; people open it and click through to the KSA tracker and any other apps you add.

## Add or edit apps

Edit **`marketplace_config.yaml`** in the repo. The layout is **sidebar + preview** (like Streamlit’s “Deploy from a template”): pick an app in the sidebar, see description and **View demo** in the main area.

Use **categories** to group apps (e.g. Data apps, Tools):

```yaml
title: "Our apps"
subtitle: "Internal tools and dashboards. Select an app to open it."

categories:
  - name: "Data apps"
    apps:
      - name: "KSA Kitchen Tracker"
        description: "Master Kitchens, Dashboard, and Discussions."
        url: "https://ksa-kitchenp-tracker-xxx.streamlit.app/"
        owner: "Operations"
  - name: "Tools"
    apps:
      - name: "Another app"
        description: "What it does."
        url: "https://another-app.streamlit.app/"
        owner: "Team name"
```

Push to the repo and **reboot the marketplace app** on Streamlit Cloud to refresh.
