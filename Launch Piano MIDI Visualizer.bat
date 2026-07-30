@echo off
cd /d "%~dp0"

REM Create virtual environment if it doesn't exist
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Install/update dependencies
echo Checking dependencies...
".venv\Scripts\pip.exe" install -r requirements.txt --quiet

REM Launch the app
".venv\Scripts\python.exe" main.py

