# How to deploy the marketplace (step by step)

You already have the KSA tracker app on Streamlit Cloud. The marketplace is a **second app** from the same GitHub repo. Follow these steps to get it online.

---

## Step 1: Open Streamlit Cloud

1. In your browser, go to **https://share.streamlit.io**
2. Sign in with GitHub (same account that has your `ksa-kitchenP-tracker` repo).

---

## Step 2: Create a new app

1. On the Streamlit Cloud dashboard, click the **"New app"** button.
2. You’ll see a form with a few boxes.

---

## Step 3: Fill in the form (don’t mix these up)

**Repository**  
- This must be your **GitHub repo**, not a filename.  
- It usually looks like: **`username/repo-name`** or **`org-name/repo-name`**.  
- Example: **`maisam21-lab/ksa-kitchenP-tracker`**  
- Use the **dropdown** to pick the repo (same one as your KSA tracker).  
- Do **not** type `marketplace_app.py` here — that goes in **Main file path** below.

**Branch**  
- Type or select: **`main`**

**Main file path**  
- This is the **file inside the repo** that Streamlit runs.  
- Type exactly: **`marketplace_app.py`**  
- Do **not** use `streamlit_app.py` — use **`marketplace_app.py`**.

| Field            | What to put                          | Not this              |
|------------------|--------------------------------------|------------------------|
| Repository       | `maisam21-lab/ksa-kitchenP-tracker`  | ~~marketplace_app.py~~ |
| Branch           | `main`                               | —                      |
| Main file path   | `marketplace_app.py`                 | ~~streamlit_app.py~~   |

---

## Step 4: Deploy

1. Click **"Deploy"** (or "Create app").  
2. Wait 1–2 minutes. Streamlit will build and run the app.  
3. When it’s done, you’ll see a URL like:  
   **`https://ksa-kitchenp-tracker-marketplace-xxxxx.streamlit.app/`**  
   (The exact name depends on what you or Streamlit chose.)

---

## Step 5: Share with your team

- Copy that URL.
- Share it (Slack, email, intranet, etc.).
- That single link is your **marketplace**: when people open it, they see all listed apps (e.g. KSA Kitchen Tracker) and can click **View demo** to open one.

---

## If something goes wrong

**"Repository not found"**  
- Make sure the repo is under the GitHub account you’re signed in with on Streamlit Cloud, and that Streamlit has access to it (you may need to approve the app in GitHub).

**"File not found" or "main file path" error**  
- Check that you typed **`marketplace_app.py`** with no typo and no `app/` prefix.  
- The file must be in the root of the repo (same folder as the `app` folder).

**App runs but shows "No apps"**  
- The repo on GitHub must have the latest code (with `marketplace_config.yaml` and `marketplace_app.py`). Push your latest changes and then in Streamlit Cloud click **"Reboot"** for the marketplace app.

---

## Summary

| What | Value |
|------|--------|
| Where to go | https://share.streamlit.io |
| Action | New app |
| Repository | ksa-kitchenP-tracker (same as tracker) |
| Branch | main |
| Main file path | **marketplace_app.py** |

After deploy, you’ll have two apps from the same repo: one for the KSA tracker, one for the marketplace. Share only the marketplace URL with your team.
