@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
	".venv\Scripts\pip.exe" install -r requirements.txt --quiet
	".venv\Scripts\python.exe" main.py
) else (
	pip install -r requirements.txt --quiet
	python main.py
)
