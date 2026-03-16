@echo off
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
    echo [Setup] Installing dependencies from requirements.txt...
    ".venv\Scripts\pip.exe" install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Dependency installation failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo [Setup] Done!
)

rem ── Launch ───────────────────────────────────────────────────────────────
".venv\Scripts\python.exe" main.py

