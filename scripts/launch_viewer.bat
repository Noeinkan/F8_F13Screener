@echo off
REM Launcher per Telegram Viewer - Avvia in finestra separata

REM Change to project root directory
cd /d "%~dp0\.."

REM Set PYTHONPATH to project root
set PYTHONPATH=%cd%

start "Telegram Message Viewer" python.exe src\gui\telegram_viewer.py
