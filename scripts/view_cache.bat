@echo off
title 13F Cache Viewer
echo ================================
echo  13F Cache Viewer
echo ================================
echo.
echo Visualizzazione filing in cache...
echo.

REM Change to project root directory
cd /d "%~dp0\.."

REM Set PYTHONPATH to project root
set PYTHONPATH=%cd%

python src\cli\view_cached_filings.py %*

if errorlevel 1 (
    echo.
    echo ERRORE durante la visualizzazione!
    echo.
)

pause
