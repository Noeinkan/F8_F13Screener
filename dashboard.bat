@echo off
REM Root shortcut for restarting the dashboard and opening it in the browser.

cd /d "%~dp0"
python -m src.main dashboard %*