# Step-by-step: Deploy Salesforce Report IDs

Follow these steps in order.

---

## Step 1: Open a terminal in your project folder

- Open PowerShell or Command Prompt.
- Go to the project:
  ```text
  cd C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker
  ```

---

## Step 2: Commit your changes

Run:

```text
git add -A
git status
```

Check that `app/tracker_app.py` (and any other changed files) are listed. Then:

```text
git commit -m "Use Salesforce Report API for report IDs in sf_tab_queries"
```

---

## Step 3: Push to GitHub

If your app is on GitHub (e.g. `maisam21-lab/ksa-kitchenP-tracker`):

```text
git push origin main
```

(Use your branch name instead of `main` if different, e.g. `master`.)

---

## Step 4: Let Streamlit Cloud redeploy

- Go to [share.streamlit.io](https://share.streamlit.io) and sign in.
- Open your **KSA Kitchens Tracker** app.
- After the push, Streamlit usually redeploys automatically. Wait until the status is **Running** (or click **Reboot app** if needed).

---

## Step 5: Check Streamlit secrets

- In the app page, go to **Settings** (or **Manage app**) → **Secrets**.
- Make sure you have **at the top** (no section header above these):

  ```toml
  SF_INSTANCE_URL = "https://cloudkitchens--yazandev.sandbox.my.salesforce.com"
  SF_ACCESS_TOKEN = "your_access_token_here"
  ```

- And either **Option A** or **Option B**:

  **Option A – Section**

  ```toml
  [sf_tab_queries]
  "All no status kitchens" = "00O6T000006DPigUAG"
  "Area Data" = "00O6T000006Y0l6UAC"
  "Price Multipliers" = "00OVO000003z2O92AI"
  "SF Churn Data" = "00O6T000006Y5DiUAK"
  "SF Kitchen Data" = "00O6T000006Y0l6UAC"
  "Sellable No Status" = "00O6T000006DXT0UAO"
  ```

  **Option B – One line (JSON)**

  ```toml
  SF_TAB_QUERIES = "{\"All no status kitchens\": \"00O6T000006DPigUAG\", \"Area Data\": \"00O6T000006Y0l6UAC\", \"Price Multipliers\": \"00OVO000003z2O92AI\", \"SF Churn Data\": \"00O6T000006Y5DiUAK\", \"SF Kitchen Data\": \"00O6T000006Y0l6UAC\", \"Sellable No Status\": \"00O6T000006DXT0UAO\"}"
  ```

- Save. If you changed secrets, **Reboot app** again.

---

## Step 6: Refresh the app and test

- Open your app in the browser (or refresh the page).
- In the sidebar, click **Data**.
- Expand **Refresh data (Google Sheet & Salesforce only)**.
- Click **Refresh from Salesforce**.

You should see a success message like:  
**Real-time Salesforce: All no status kitchens (N rows); Area Data (N rows); …**

If you see an error, copy the **full error message** and the **URL** it shows (if any) and use that to debug (e.g. wrong Report ID, expired token, or missing permission).

---

## Quick reference

| Step | What to do |
|------|------------|
| 1 | `cd C:\Users\MaysamAbuKashabeh\ksa-kitchenp-tracker` |
| 2 | `git add -A` then `git commit -m "Use Salesforce Report API for report IDs"` |
| 3 | `git push origin main` (or your branch) |
| 4 | Wait for Streamlit Cloud to finish redeploying (or Reboot app) |
| 5 | Check Secrets: `SF_INSTANCE_URL`, `SF_ACCESS_TOKEN`, and `[sf_tab_queries]` or `SF_TAB_QUERIES` |
| 6 | Open app → Data → **Refresh from Salesforce** |
