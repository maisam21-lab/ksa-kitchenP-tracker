# Deploy KSA Kitchens Tracker on Streamlit Community Cloud (Option 1)

Team members get **one link** and use the tracker in their browser. No install on their side.

---

## Step 1: Push the project to GitHub

1. Create a repo at [github.com/new](https://github.com/new) (e.g. `bi-etl-foundation` or `ksa-kitchens-tracker`).
2. In your project folder (where `app/tracker_app.py` and `requirements.txt` are), run:

   ```bash
   git init
   git add .
   git commit -m "KSA Kitchens Tracker app"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

   Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your GitHub username and repo name.

---

## Step 2: Deploy on Streamlit Community Cloud

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with **GitHub**.
2. Click **"New app"**.
3. Fill in:
   - **Repository:** `YOUR_USERNAME/YOUR_REPO_NAME` (e.g. `mycompany/bi-etl-foundation`).
   - **Branch:** `main`.
   - **Main file path:** `app/tracker_app.py`.
   - **App URL:** pick a short name (e.g. `ksa-kitchens-tracker`). Your app will be at `https://ksa-kitchens-tracker.streamlit.app`.
4. Click **"Deploy"**.
5. Wait 1–3 minutes for the build to finish.

---

## Step 3: (Optional) Add secrets

In the Streamlit Cloud app dashboard, go to **Settings → Secrets** and add (optional):

```toml
# Required if you want to unlock "Developer access" (import, refresh, edit data)
DEVELOPER_KEY = "your-secret-key"

# Optional: limit access to specific users (see docs/DEPLOY_TRACKER_FOR_TEAM.md)
# ALLOWLIST_ENABLED = true
```

Save. The app will restart with the new secrets.

---

## Step 4: Share the link with your team

- Copy the app URL (e.g. `https://ksa-kitchens-tracker.streamlit.app`).
- Send it to your team (email, Slack, etc.).

**Team members:** open the link in any browser. No install needed.

- If you **did not** set `ALLOWLIST_ENABLED`: everyone with the link can use the app.
- If you **did** set `ALLOWLIST_ENABLED = true`: they must enter their name or email in the sidebar (same as in the allowlist you manage under Developer access).

---

## Step 5: Load data (first time)

- In the app, go to **Data** in the sidebar.
- Use **Import workbook** (developer only) or **Import from CSV/Excel** to load your data.
- After that, the team can view, filter, and (if allowed) edit from the same link.

---

## Summary

| You do | Team does |
|--------|-----------|
| Push code to GitHub | — |
| Deploy at share.streamlit.io (New app → set main file `app/tracker_app.py`) | — |
| (Optional) Add DEVELOPER_KEY and/or ALLOWLIST_ENABLED in Secrets | — |
| Share the `https://….streamlit.app` link | Open the link in a browser |

**Note:** On the free tier, app data (SQLite) can be reset on redeploy. For long-term data, consider an internal server or a cloud database later.

---

## "Repository not found" on Streamlit Cloud

If Streamlit shows **Repository not found** when you deploy or open the app:

1. **Repo must be accessible to Streamlit**
   - Go to [github.com](https://github.com) → your repo → **Settings**.
   - If the repo is **Private**, either:
     - Make it **Public** (Settings → Danger zone → Change visibility), or  
     - Grant Streamlit access: [share.streamlit.io](https://share.streamlit.io) → **Settings** (your profile) → **Linked GitHub account** and ensure the org/repo is allowed for private repos.

2. **Repository name must be exact**
   - In Streamlit "New app", **Repository** must be exactly: `username/repo-name` (no spaces, no `.git`).
   - Example: `johndoe/bi-etl-foundation` (check the repo URL on GitHub and copy the part after `github.com/`).

3. **Sign in with the right GitHub account**
   - At [share.streamlit.io](https://share.streamlit.io) you must be signed in with the GitHub account that **owns** the repo (or that has access to the org repo).

4. **Reconnect GitHub (if needed)**
   - Streamlit Cloud → **Settings** → **Connections** → disconnect and reconnect GitHub, then try creating the app again.
