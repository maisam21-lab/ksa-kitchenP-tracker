@echo off
REM Use 'py' (Windows Python launcher) when pip/python are not on PATH.
cd /d "%~dp0"

echo Step 1: Installing dependencies with py -m pip...
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo "py" failed. Try: python -m pip install -r requirements.txt
    echo Or install Python from https://www.python.org/downloads/ and check "Add Python to PATH"
    pause
    exit /b 1
)

echo.
echo Step 2: Starting the tracker app...
echo If the browser does not open, go to:  http://localhost:8501
echo.
py -m streamlit run app/tracker_app.py --server.headless true

pause
