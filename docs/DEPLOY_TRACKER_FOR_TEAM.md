# Deploy the tracker so any team member can use it (no setup)

**Goal:** Team members open **one link in the browser** and use the tracker. No Python, no install, no config on their side.

---

## Can I deploy to Streamlit Community Cloud?

**Yes.** If your code is in a GitHub (or GitLab/Bitbucket) repo, you can deploy in a few minutes.

### Quick steps

1. **Push this project to GitHub** (if it’s not already).
   - Create a repo at [github.com](https://github.com/new) (e.g. `bi-etl-foundation`).
   - From your project folder:  
     `git init` (if needed) → `git add .` → `git commit -m "Add Internal Tools app"` → `git remote add origin https://github.com/YOUR_USERNAME/bi-etl-foundation.git` → `git push -u origin main`.

2. **Go to [share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.

3. **Click “New app”.**
   - **Repository:** `YOUR_USERNAME/bi-etl-foundation` (or your org/repo).
   - **Branch:** `main`.
   - **Main file path:** `app/tracker_app.py`.
   - **App URL:** leave default or choose a name (e.g. `ksa-kitchen-tracker`).

4. **Click “Deploy”.** Wait for the build to finish (1–3 minutes).

5. **Open the link** (e.g. `https://ksa-kitchen-tracker.streamlit.app`) and share it with your team.

6. **One-time: add your data.** In the app, open **About** → **Import from CSV**, then upload a CSV exported from your Google Sheet (File → Download → CSV). After that, the team uses the app instead of the sheet.

**Note:** On the free tier, app data (SQLite) can be reset on redeploy or restart. For a permanent single source of truth, use an internal server (Option 2 below) or later connect the app to a cloud database.

---

## How it works

| Today (local) | After deploy |
|---------------|--------------|
| Someone runs `py -m streamlit run app/tracker_app.py` on their machine | App runs on a **hosted** server |
| Only that person (and same network) can open it | **Everyone** opens the same URL in a browser |
| Requires Python + Streamlit installed | **Zero install** for team — just the link |

---

## Option 1: Streamlit Community Cloud (easiest, free)

1. **Put your app in a Git repo** (GitHub, GitLab, or Bitbucket).  
   - Your project already has `app/tracker_app.py` and `requirements.txt` at the repo root.  
   - Make sure `requirements.txt` includes `streamlit>=1.28` (it does).

2. **Sign in at [share.streamlit.io](https://share.streamlit.io)** with GitHub/GitLab/Bitbucket.

3. **New app:**
   - **Repository:** `your-org/bi-etl-foundation` (or your repo URL).  
   - **Branch:** `main` (or your default).  
   - **Main file path:** `app/tracker_app.py`.  
   - **App URL:** e.g. `https://your-app-name.streamlit.app`.

4. **Deploy.** Wait for the first run to finish.

5. **Share the link** with your team.  
   - Example: `https://your-app-name.streamlit.app`  
   - Anyone with the link can open it in a browser — no setup.

6. **(Optional) Restrict who can open it**  
   - In the Streamlit Cloud dashboard you can set the app to **Private** and manage access (e.g. by email) so only your team can open it.
   - **Or use the built-in allowlist:** see [Limit access to specific users](#limit-access-to-specific-users-allowlist) below.

**Data persistence:** On Streamlit Community Cloud, the app’s disk can be reset on redeploy or restart. For a **long‑term** single source of truth, consider later moving the DB off the free tier (e.g. run the app on an internal server with a persistent disk, or switch the app to a cloud database and keep using the same URL).

---

## Option 2: Run on an internal server (your own URL)

If you prefer everything to stay inside your network:

1. **Pick a server** (e.g. a Windows/Linux machine or VM that everyone can reach).

2. **On that machine:**  
   - Install Python 3.  
   - Clone the repo and run:  
     `py -m streamlit run app/tracker_app.py --server.port 8501 --server.address 0.0.0.0`  
   - Optionally run it as a service so it restarts on reboot.

3. **Share the URL** with the team, e.g. `http://your-server:8501`.  
   - Only people who can reach that server (e.g. on company network or VPN) can open it.  
   - No install for them — they just use the link.

4. **Data:** The SQLite file lives on that server (`app/data/tracker.db`), so it persists as long as you don’t delete it.

---

## Limit access to specific users (allowlist)

You can restrict the tracker so **only people you add to an allowlist** can use it. Everyone else sees “Access restricted” until an admin adds them.

### How it works

1. **Turn on the allowlist**  
   Set one of these so the app checks the allowlist:
   - **Streamlit Cloud:** In your app’s **Settings → Secrets**, add:
     ```toml
     ALLOWLIST_ENABLED = true
     ```
   - **Local or your own server:** set an environment variable before running the app:
     ```bash
     set ALLOWLIST_ENABLED=1
     py -m streamlit run app/tracker_app.py
     ```
     (On Linux/Mac use `export ALLOWLIST_ENABLED=1`.)

2. **Add allowed users**  
   - Unlock **Developer access** in the sidebar (using your developer key).
   - In the same expander you’ll see **Allowed users**.
   - Enter a **name or email** (e.g. `jane@company.com` or `Jane`) and click **Add**.
   - Repeat for each team member who should have access. Only these identifiers can use the app when the allowlist is enabled.

3. **How users sign in**  
   - Each user opens the app link and enters **their name or email** in the sidebar (“Your name (comments & history)”).
   - If that value matches an entry in the allowlist (case-insensitive), they can use the app.
   - If not, they see “Access restricted” and cannot see data until an admin adds them.

4. **Developers**  
   - Anyone who unlocks **Developer access** with the developer key can always use the app and manage the allowlist, even if their name is not in the list.

### Summary

- **Allowlist off** (default): anyone with the link can use the app.
- **Allowlist on** (`ALLOWLIST_ENABLED=1` or `true`): only users in the allowlist (or developers with the key) can use the app.
- Manage the list under **Developer access → Allowed users** (add/remove by name or email).

---

## Summary

- **“Any team member can use the tracker with no pre-setup”** = **host the app** and give them **one link**.  
- **Streamlit Community Cloud:** no server to manage; team uses the `*.streamlit.app` link.  
- **Internal server:** you control where data lives; team uses your internal URL.  
- In both cases, team members only need a browser — no Python or local setup.
