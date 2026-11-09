@echo off
title Music Hub
cd /d "%~dp0"

rem ── First-run setup: create venv if it doesn't exist ──────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo [Setup] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: 'python' not found. Please install Python 3.10+ and add it to PATH.
        pause
        exit /b 1
    )
    echo [Setup] Installing dependencies from midi_coach\requirements.txt...
    ".venv\Scripts\pip.exe" install -r midi_coach\requirements.txt
    if errorlevel 1 (
        echo ERROR: Dependency installation failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo [Setup] Done!
)

rem ── Open the practice page (close this window to quit) ──────────────────────
rem Already running and up to date: it just shows the page. Running but older than the code:
rem a practice copy is restarted; Claude Desktop's midi-coach gets a message instead.
".venv\Scripts\python.exe" -m midi_coach.launch %*
if errorlevel 1 pause
