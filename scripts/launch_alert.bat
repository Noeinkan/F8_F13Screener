@echo off
title 13F Real-Time Alert Monitor
echo ================================
echo  13F Real-Time Alert Monitor
echo ================================
echo.
echo Avvio monitoraggio real-time...
echo.

REM Change to project root directory
cd /d "%~dp0\.."

REM Set PYTHONPATH to project root
set PYTHONPATH=%cd%

python src\cli\main.py

if errorlevel 1 (
    echo.
    echo ERRORE durante l'avvio del monitor!
    echo.
    pause
)
