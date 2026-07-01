@echo off
REM Root shortcut for restarting the dashboard.
REM
REM Behavior:
REM   1. Pre-flight: free the dashboard ports (5173, 9001, 8501, 8502, 3000) from
REM      any stale listener so a previous process never wins the race.
REM   2. Delegate to dev.ps1 (the canonical React+FastAPI launcher).
REM
REM Pass `-Streamlit` to launch the legacy Streamlit dashboard instead of
REM dev.ps1 (kept for the explicit opt-in only).

setlocal

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\_free_ports.ps1"
if errorlevel 1 (
  echo [dashboard.bat] Port cleanup failed; aborting.
  exit /b 1
)

if /I "%~1"=="-Streamlit" (
  python -m src.main dashboard-streamlit %2 %3 %4 %5 %6 %7 %8 %9
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %1 %2 %3 %4 %5 %6 %7 %8 %9
)