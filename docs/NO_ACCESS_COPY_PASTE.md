# No Google Cloud / API access — use copy & paste

You don’t need Google Cloud, a service account, or Download. You only need to **view** the KSA Kitchen Tracker in the browser.

---

## Steps (about 1 minute)

### 1. Copy from Google Sheets

1. Open the **KSA Kitchen Tracker** in Google Sheets (in your browser).
2. **Select all:** click the **top-left corner** of the sheet (the small square between the “1” and the “A”), or press **Ctrl+A**.
3. **Copy:** press **Ctrl+C** (or right‑click → Copy).

### 2. Paste and save on your PC

1. Open **Notepad** (Windows: Start → type “Notepad” → open).
2. **Paste:** press **Ctrl+V**.
3. **Save:** **File → Save As**.
   - **Where:** e.g. your **Desktop** or the folder **`bi-etl-foundation\scripts`**.
   - **File name:** `ksa_paste.txt`
   - **Save as type:** **All Files (*.*)**  ← important (so it’s not saved as .txt with extra encoding).
4. Click **Save**.

### 3. Convert to CSV and validate

Open **PowerShell** or **Command Prompt** and run (change the path if you saved the file somewhere else):

**If you saved `ksa_paste.txt` on your Desktop:**

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
python scripts/paste_to_csv.py C:\Users\MaysamAbuKashabeh\Desktop\ksa_paste.txt
python validate_ksa_csv.py
```

**If you saved `ksa_paste.txt` inside `bi-etl-foundation\scripts`:**

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
python scripts/paste_to_csv.py scripts/ksa_paste.txt
python validate_ksa_csv.py
```

You should see: “Wrote N rows…” then “Valid: N” and “Output: …\data\output\ksa_kitchen_tracker.csv”.

---

## When the tracker updates

1. Open the sheet again, **select all** (top-left or Ctrl+A), **copy** (Ctrl+C).
2. Open your saved **ksa_paste.txt** in Notepad, **select all**, **paste** (overwrite), **Save**.
3. Run the same two commands again:
   ```bash
   cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
   python scripts/paste_to_csv.py scripts/ksa_paste.txt
   python validate_ksa_csv.py
   ```

No Google Cloud or API access is required.
