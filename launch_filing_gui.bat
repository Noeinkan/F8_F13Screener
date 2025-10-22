@echo off
title 13F Filing Processor GUI
echo ================================
echo  13F Filing Processor - GUI
echo ================================
echo.
echo Avvio interfaccia grafica...
echo.

python filing_processor_gui.py

if errorlevel 1 (
    echo.
    echo ERRORE durante l'avvio della GUI!
    echo.
    pause
)
