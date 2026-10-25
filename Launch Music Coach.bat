@echo off
cd /d "%~dp0"

rem ── Already running? Just show the page (a second copy would fight it for the keyboard) ──
curl.exe -s -o nul --max-time 2 http://127.0.0.1:8765/ && (
    start "" http://127.0.0.1:8765/
    exit /b 0
)

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

rem ── Launch the practice page (close this window to quit) ────────────────────
rem Don't run it while Claude Desktop's midi-coach is open: both want the keyboard.
".venv\Scripts\python.exe" -m midi_coach.practice %*
if errorlevel 1 pause
