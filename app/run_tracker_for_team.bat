@echo off
REM Run Trackers so the TEAM can reach it (same network or via tunnel).
REM From repo root: app/run_tracker_for_team.bat
cd /d "%~dp0.."

echo.
echo  Trackers - Team access
echo ==================================
echo.
echo  Starting app on port 8501 (reachable on this machine's IP)...
echo.
echo  OPEN IN BROWSER:         http://localhost:8501
echo  (Do NOT use 0.0.0.0 - use localhost or 127.0.0.1)
echo.
echo  Others on SAME NETWORK:  http://YOUR_IP:8501
echo  (Find YOUR_IP: run 'ipconfig' and look for IPv4 Address)
echo.
echo  To get a public URL (tunnel): use ngrok or cloudflared - see docs/DEPLOY_TRACKER_FOR_TEAM.md
echo.
echo  Press Ctrl+C to stop the app.
echo.

py -m streamlit run app/tracker_app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
pause
