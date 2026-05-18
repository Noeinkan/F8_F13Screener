@echo off
REM Restart the local Streamlit dashboard, then open it in the browser.

cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_dashboard.ps1" %*