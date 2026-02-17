# Why "Refresh from online sheet" might not work

The app reads the Google Sheet **1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8** using the Google Sheets API. If **Refresh from online sheet** fails, check the following.

---

## 1. No Google credentials (most common)

**Error you see:**  
`No Google credentials. Add a service account JSON at scripts/credentials.json or set GOOGLE_APPLICATION_CREDENTIALS. Share the sheet with the service account email (Viewer).`

**Cause:** The app has no way to authenticate to Google (no service account key).

**Fix:**

### On Streamlit Cloud (no local files)

You **must** put the service account key in **Secrets** (app → Settings → Secrets). Use **one** of these:

**Option A — Paste the full JSON (recommended)**  
1. In Google Cloud Console: create a service account → Keys → Add key → JSON → download the file.  
2. Open the JSON file and copy the **entire** contents (one object with `type`, `project_id`, `private_key_id`, `private_key`, `client_email`, etc.).  
3. In Streamlit Cloud → Settings → Secrets, add a key named **`gsheet_service_account_json`**.  
4. Paste the **whole JSON** as the value (multiline is fine).  
   - The app will parse it and use it. You avoid "missing fields client_email, token_uri" because all fields come from the JSON.

**Option B — TOML table**  
Add a key **`gsheet_service_account`** and define every field (e.g. `type`, `project_id`, `private_key_id`, `private_key`, `client_email`, `client_id`, `auth_uri`, `token_uri`, `auth_provider_x509_cert_url`, `client_x509_cert_url`). If `token_uri` or `auth_uri` are missing, the app adds defaults.  
If you see "missing fields client_email, token_uri", use **Option A** instead (paste full JSON as `gsheet_service_account_json`).

### Running locally

- Put the **service account JSON file** in one of these places (and do **not** commit it):
  - **`scripts/credentials.json`**
  - **`.secrets/gsheet-service.json`**
  - **`app/data/credentials.json`**
- Or set the **environment variable** **`GOOGLE_APPLICATION_CREDENTIALS`** to the full path of that JSON file.

---

## 2. Sheet not shared with the service account

**Error you see:**  
Something like `APIError: 403 ... The caller does not have permission` or `Permission denied` when opening the spreadsheet.

**Cause:** The Google Sheet is not shared with the **service account email** (the `client_email` in the JSON, e.g. `xxx@project.iam.gserviceaccount.com`).

**Fix:**

1. Open the Google Sheet.
2. Click **Share**.
3. Add the **service account email** (from your JSON: `client_email`).
4. Give it **Viewer** access.
5. Save.

---

## 3. Wrong sheet or Google Sheets API not enabled

**Error you see:**  
`Spreadsheet not found` / 404, or errors about the Sheets API.

**Cause:**  
- The app is hard-coded to use sheet ID **`1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8`**. If your tracker uses a different sheet, the code (or config) must be updated to that ID.  
- Or the Google Cloud project does not have **Google Sheets API** enabled.

**Fix:**

- If you use a **different** sheet: we need to change `SHEET_ID` in the app (or make it configurable via secrets).
- In Google Cloud Console: **APIs & Services** → **Library** → search **Google Sheets API** → **Enable** for the project that owns the service account.

---

## 4. Missing Python packages

**Error you see:**  
`ImportError: Install: pip install gspread google-auth`

**Fix:**  
In the environment where the app runs (e.g. in `requirements.txt` or in Streamlit Cloud’s dependencies), ensure:

```text
gspread
google-auth
```

are installed.

---

## Quick checklist

- [ ] Service account JSON is available to the app (Secrets **`gsheet_service_account`** on Cloud, or file in `scripts/credentials.json` / `.secrets/gsheet-service.json` / `app/data/credentials.json` locally, or `GOOGLE_APPLICATION_CREDENTIALS`).
- [ ] The **Google Sheet** is **shared** with the service account email with at least **Viewer**.
- [ ] **Google Sheets API** is enabled for the project.
- [ ] `gspread` and `google-auth` are installed.

If you see a **different** error message when you click **Refresh from online sheet**, copy it and use it to search the doc or share it so we can add it here.
