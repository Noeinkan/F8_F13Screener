@echo off
title 13F Filing Processor GUI
echo ================================
echo  13F Filing Processor - GUI
echo ================================
echo.
echo Avvio interfaccia grafica...
echo.

REM Change to project root directory
cd /d "%~dp0\.."

python filing_processor_gui.py

if errorlevel 1 (
    echo.
    echo ERRORE durante l'avvio della GUI!
    echo.
    pause
)
