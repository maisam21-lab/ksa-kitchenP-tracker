# Google Sheets API — automatic pull (step-by-step)

Follow these steps once. After that, run `python fetch_sheet_to_csv.py` whenever you want to pull the KSA Kitchen Tracker into the project.

---

## Step 1: Google Cloud project and Sheets API

1. Open **[Google Cloud Console](https://console.cloud.google.com/)** and sign in.
2. **Create a project** (or select one):
   - Top bar: click the project name → **New Project** → e.g. "BI ETL" → Create.
3. **Enable the Google Sheets API**:
   - Left menu: **APIs & Services** → **Library**.
   - Search for **Google Sheets API** → click it → **Enable**.

---

## Step 2: Service account and JSON key

1. Left menu: **APIs & Services** → **Credentials**.
2. Click **+ Create Credentials** → **Service account**.
3. **Service account name:** e.g. `bi-etl-sheets`. Click **Create and Continue** (role optional) → **Done**.
4. In the list, click the new **service account** (the email like `bi-etl-sheets@your-project.iam.gserviceaccount.com`).
5. Open the **Keys** tab → **Add key** → **Create new key** → **JSON** → **Create**.  
   A JSON file will download.
6. **Rename** the file to **`credentials.json`**.
7. **Move** it into your project folder:  
   **`bi-etl-foundation\scripts\credentials.json`**  
   (Same folder as `fetch_sheet_to_csv.py`.)

**Important:** Do not commit `credentials.json` to git or share it. Add `scripts/credentials.json` to `.gitignore` if you use git.

---

## Step 3: Share the Google Sheet with the service account

1. Open your **KSA Kitchen Tracker** (or the spreadsheet that contains it) in Google Sheets.
2. Click **Share**.
3. In **Add people and groups**, paste the **service account email** from the JSON file:
   - Open `credentials.json` in a text editor and find the line `"client_email": "xxxxx@xxxxx.iam.gserviceaccount.com"`.
   - Copy that email (e.g. `bi-etl-sheets@your-project.iam.gserviceaccount.com`).
4. Paste it into the Share dialog. Set permission to **Viewer**.
5. Uncheck **Notify people** (the service account does not read email). Click **Share**.

---

## Step 4: Set the sheet and tab in the script

1. Open **`bi-etl-foundation\scripts\fetch_sheet_to_csv.py`** in an editor.
2. **SHEET_ID:** From your sheet URL  
   `https://docs.google.com/spreadsheets/d/SHEET_ID/edit?gid=123`  
   copy the long id (e.g. `1nFtYf5USuwCfYI_HB_U3RHckJchCSmew45itnt0RDP8`). It is already set if you use the same tracker link.
3. **GID (tab):** If the KSA Kitchen Tracker is on a **specific tab**, get its id from the URL when that tab is open:  
   `...edit#gid=1341293927` → **GID** = `1341293927`.  
   Change the line `GID = "1341293927"` to your tab’s number.  
   If you only have one tab or want the first sheet, you can leave it; the script falls back to the first sheet if the GID is not found.

---

## Step 5: Install Python packages and run

In a terminal (PowerShell or Command Prompt):

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
python -m pip install gspread google-auth
cd scripts
python fetch_sheet_to_csv.py
```

You should see something like: **Fetched N rows to ...\data\input\ksa_kitchen_tracker.csv**.

Then validate and build the output:

```bash
cd ..
python validate_ksa_csv.py
```

---

## Troubleshooting

| Problem | What to do |
|--------|------------|
| **ModuleNotFoundError: gspread** | Run `python -m pip install gspread google-auth`. |
| **credentials.json not found** | Put the JSON key file in `bi-etl-foundation\scripts\` and name it exactly `credentials.json`. |
| **Permission denied / 403** | Share the Google Sheet with the **service account email** (from `client_email` in `credentials.json`) as **Viewer**. |
| **Wrong tab** | Open the correct tab in the browser, copy the `gid=...` from the URL and set **GID** in `fetch_sheet_to_csv.py`. |
| **Empty sheet** | Check SHEET_ID and GID; make sure the shared sheet has data on that tab. |

---

## Run again later

Whenever you want to refresh the data:

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation\scripts
python fetch_sheet_to_csv.py
cd ..
python validate_ksa_csv.py
```

You can also schedule this (e.g. Windows Task Scheduler) so the CSV updates automatically.
