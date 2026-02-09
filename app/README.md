# Internal Tools — web-based app (Goal 5)

One app: **Home** | **Tracker** (Smart Tracker + all sheet tabs) | **Exports** | **About**.  
Deploy once; give the team one URL so everyone uses the same internal tool.

## If `pip` or `python` is not recognized

On Windows, use **`py`** (Python launcher) instead:

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
py -m pip install -r requirements.txt
py -m streamlit run app/tracker_app.py
```

**Or double-click:** **`install_and_run.bat`** in the repo root — it uses `py` to install and run.

If `py` is also not recognized, install Python from [python.org](https://www.python.org/downloads/) and during setup **check "Add Python to PATH"**. Then open a new Command Prompt and try again.

---

## Run the app

**From the repo root** (`bi-etl-foundation`):

```bash
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
pip install -r requirements.txt
python -m streamlit run app/tracker_app.py
```

Use **`python -m streamlit`** (not `streamlit`) so it works when the `streamlit` command is not on your PATH.

**Or double-click:** `app/run_tracker_app.bat` (from the repo root or from inside `app/` — the script goes up one level to the repo root).

---

## If the app doesn't open

1. **Run from the correct folder**  
   You must be in **`bi-etl-foundation`** (the repo root), not inside `app/`. Then run:
   ```bash
   python -m streamlit run app/tracker_app.py
   ```

2. **Open the URL yourself**  
   Streamlit prints a URL in the terminal, e.g.:
   ```
   Local URL: http://localhost:8501
   ```
   If the browser doesn’t open automatically, copy that URL and paste it into your browser.

3. **Install dependencies**  
   If you see `ModuleNotFoundError: streamlit`:
   ```bash
   pip install -r requirements.txt
   ```
   or:
   ```bash
   pip install streamlit
   ```

4. **Port 8501 in use**  
   If something else is using port 8501, run:
   ```bash
   python -m streamlit run app/tracker_app.py --server.port 8502
   ```
   Then open: **http://localhost:8502**

5. **Python path**  
   If `python` isn’t found, try:
   ```bash
   py -m streamlit run app/tracker_app.py
   ```
   (Use `py` if `python` is not recognized.)
