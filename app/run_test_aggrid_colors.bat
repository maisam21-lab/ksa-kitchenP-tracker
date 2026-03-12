@echo off
REM Run the AgGrid color test (minimal app to check if row styling works).
cd /d "%~dp0.."
echo Starting AgGrid color test...
echo.
echo Open in browser:  http://localhost:8501
echo If you see one green row and one red row, styling works.
echo.
py -m streamlit run app/test_aggrid_colors.py --server.headless true
pause
