# Testing KSA Kitchen Tracker

## What’s in place

- **Schema:** `config/schemas/ksa_kitchen_tracker.json` — defines required fields and types for KSA kitchen tracker rows.
- **Sample data:** `data/input/ksa_kitchen_tracker.csv` — sample rows (Riyadh, Jeddah, Dammam) for testing.
- **Config:** `config/sources_ksa.yaml` — ETL config that only runs the KSA tracker source.
- **Run script:** `run_ksa_test.py` — runs the ETL for KSA only and prints a summary.

## How to run the test

### 1. Install dependencies

From the repo root:

```bash
cd bi-etl-foundation
pip install -r requirements.txt
```

(or `python -m pip install -r requirements.txt` if `pip` isn’t on your PATH).

### 2. Run the KSA Kitchen Tracker ETL

```bash
python run_ksa_test.py
```

You should see:

- **Valid rows:** 8 (all sample rows)
- **Invalid rows:** 0
- **Output:** `data/output/ksa_kitchen_tracker.csv`

### 3. Check the output

- Open `data/output/ksa_kitchen_tracker.csv` — it should match the input (passthrough transform), with only schema-valid rows.
- If any row fails validation, it’s written to `data/quarantine/ksa_kitchen_tracker_invalid.csv` with `_error` and `_row_index` columns.

### 4. Validate without ETL (no pip install)

To only check that the CSV matches the schema (required columns, `region` = KSA), run:

```bash
python validate_ksa_csv.py
```

Optional: pass another CSV path, e.g. `python validate_ksa_csv.py path/to/export.csv`.

### 5. Test with bad data (optional)

Edit `data/input/ksa_kitchen_tracker.csv` and:

- Remove `report_date` from one row, or
- Set `region` to `UAE` instead of `KSA`,

then run `python run_ksa_test.py` again. You should see invalid count > 0 and rows in `data/quarantine/`.

## Using your real KSA tracker

1. **Export from Google Sheets:** Download the current KSA Kitchen Tracker as CSV (File → Download → CSV).
2. **Replace the sample file:** Put it at `data/input/ksa_kitchen_tracker.csv` (or add a new source in `config/sources_ksa.yaml` with a different path).
3. **Align columns:** Ensure the CSV has columns that match the schema (or update `config/schemas/ksa_kitchen_tracker.json` to match your column names and types).
4. **Run:** `python run_ksa_test.py` — valid rows go to `data/output/`; invalid rows to `data/quarantine/` for fix.

## Next steps

- **Connect Looker Studio:** Load `data/output/ksa_kitchen_tracker.csv` into BigQuery (or another warehouse), then add it as a data source in Looker Studio so the tracker is read-only and fed by this ETL.
- **Schedule:** Run `run_ksa_test.py` on a schedule (e.g. daily) so the output always reflects the latest validated data.
