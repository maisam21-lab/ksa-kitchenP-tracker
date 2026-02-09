# Cloud Shell (css-operations) - run these in order
# Copy-paste each block into Cloud Shell and press Enter.

# --- 1. Enable Sheets API ---
gcloud services enable sheets.googleapis.com --project=css-operations

# --- 2. Create service account (skip if already exists) ---
gcloud iam service-accounts create bi-etl-sheets \
  --display-name="BI ETL Sheets" \
  --project=css-operations 2>/dev/null || true

# --- 3. Create JSON key ---
gcloud iam service-accounts keys create ~/credentials.json \
  --iam-account=bi-etl-sheets@css-operations.iam.gserviceaccount.com \
  --project=css-operations

# --- 4. Show the email to share with your Google Sheet ---
echo ""
echo ">>> Share your KSA Kitchen Tracker Google Sheet with this email (Viewer):"
echo "    bi-etl-sheets@css-operations.iam.gserviceaccount.com"
echo ""

# --- 5. Install Python packages (one time) ---
pip install --user gspread google-auth

# --- 6. Create the fetch script (SHEET_ID and GID are inside; edit with nano if needed) ---
# Then run:  python3 ~/fetch_sheet_to_csv.py
# Download the CSV: Cloud Shell menu (three dots) -> Download file -> ksa_kitchen_tracker.csv
