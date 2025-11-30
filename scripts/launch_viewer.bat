@echo off
REM Launcher per Telegram Viewer - Avvia in finestra separata

REM Change to project root directory
cd /d "%~dp0\.."

start "Telegram Message Viewer" python.exe telegram_viewer.py
