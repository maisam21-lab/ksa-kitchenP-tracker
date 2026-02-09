@echo off
REM Run the web-based Trackers app.
REM Double-click this file, or run from Command Prompt.
cd /d "%~dp0.."
echo Starting tracker app...
echo.
echo If the browser does not open, go to:  http://localhost:8501
echo.
py -m streamlit run app/tracker_app.py --server.headless true
pause
