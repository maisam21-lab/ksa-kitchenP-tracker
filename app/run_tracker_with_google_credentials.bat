@echo off
REM Run the tracker and use Google credentials for "Refresh from online sheet".
REM 1. Put your service account JSON key at: scripts\credentials.json
REM 2. Share the sheet with that account's email (Viewer).
REM 3. Run this from repo root: app\run_tracker_with_google_credentials.bat

cd /d "%~dp0.."

set "CREDS=%~dp0..\scripts\credentials.json"
if exist "%CREDS%" (
    set GOOGLE_APPLICATION_CREDENTIALS=%CREDS%
    echo Using credentials: %CREDS%
) else (
    echo.
    echo  No credentials file at scripts\credentials.json
    echo  Put your service account JSON there, or set GOOGLE_APPLICATION_CREDENTIALS to its path.
    echo.
)

echo.
echo  Starting Trackers...
echo  Open: http://localhost:8502
echo  Then: Tracker -^> Refresh data from online sheet -^> Refresh from online sheet
echo.

py -m streamlit run app/tracker_app.py --server.port 8502
pause
