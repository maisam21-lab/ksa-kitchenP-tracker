# Get Google Sheets data without the Download option

## Option 1: Copy and paste (no setup)

1. Open your KSA Kitchen Tracker in Google Sheets.
2. Select all data: click the top-left corner (triangle between row 1 and column A) or press **Ctrl+A** (or Cmd+A on Mac).
3. Copy: **Ctrl+C** (or Cmd+C).
4. Open **Notepad** (or any plain text editor).
5. Paste: **Ctrl+V**.
6. Save: **File → Save As**.
   - Go to folder: `bi-etl-foundation\data\input\`
   - **File name:** `ksa_kitchen_tracker.csv`
   - **Save as type:** **All Files (*.*)** (important — do not save as .txt).
   - Click Save.
7. Run: `python validate_ksa_csv.py`

Pasted data will be tab-separated. If validation fails (e.g. "Missing required"), run Option 2 instead — the script can handle tabs and convert to CSV.

---

## Option 2: Python script (Google Sheets API)

If you can enable the Google Sheets API and use a credential, the script `fetch_sheet_to_csv.py` will read the sheet and write `data/input/ksa_kitchen_tracker.csv` for you. No Download button needed.

### One-time setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick one) and enable **Google Sheets API** (APIs & Services → Library → search "Google Sheets API" → Enable).
3. Create credentials:
   - **APIs & Services → Credentials → Create credentials → Service account.**
   - Create the account, then open it → **Keys → Add key → JSON**. Download the JSON file.
   - Put the JSON file in `bi-etl-foundation\scripts\` and name it something like `credentials.json` (do not commit it to git).
4. Share the Google Sheet with the **service account email** (e.g. `xxx@xxx.iam.gserviceaccount.com`) — give it **Viewer** access.
5. Install: `pip install gspread google-auth-oauth2` (or use the requirements in scripts folder).

### Run

Edit `fetch_sheet_to_csv.py`: set `SHEET_ID` and optionally `GID` (tab index). Then:

```bash
cd bi-etl-foundation\scripts
python fetch_sheet_to_csv.py
```

Output is written to `../data/input/ksa_kitchen_tracker.csv`. Then run `python validate_ksa_csv.py` from the repo root.
