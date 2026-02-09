# Trino setup for "Refresh from Trino"

The tracker can load sheet data via Trino (same queries as Superset). You only need this if you want to use **Refresh from Trino** instead of (or in addition to) **Refresh from online sheet**.

## Option 1: Streamlit secrets (recommended)

1. In the project root (`bi-etl-foundation`), create a folder `.streamlit` if it doesn’t exist.
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
3. Edit `.streamlit/secrets.toml` and set your Trino host:
   - **TRINO_HOST** — e.g. the host you use in Superset when connecting to Trino (ask your admin or check the Trino connection in Superset).
   - **TRINO_PORT** — usually `443` (HTTPS) or `8080` (HTTP).
   - **TRINO_CATALOG** — usually `google_spreadsheets`.
   - **TRINO_USER** — often `trino` or your username.
4. Restart the app and click **Refresh from Trino**.

## Option 2: Environment variables

Before starting the app, set (e.g. in the same command prompt):

```bat
set TRINO_HOST=your-trino-host.com
set TRINO_PORT=443
py -m streamlit run app/tracker_app.py --server.port 8502
```

Or in PowerShell:

```powershell
$env:TRINO_HOST = "your-trino-host.com"
$env:TRINO_PORT = "443"
py -m streamlit run app/tracker_app.py --server.port 8502
```

## Don’t need Trino?

Use **Refresh from online sheet** instead. You only need a Google service account JSON (e.g. in `scripts/credentials.json`) and the sheet shared with that account. No Trino config required.
