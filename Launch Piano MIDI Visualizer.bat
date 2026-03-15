@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
	".venv\Scripts\pip.exe" install -r requirements.txt --quiet || (echo Failed to install requirements. Run ".venv\Scripts\pip.exe install -r requirements.txt" for details. && pause && exit /b 1)
	".venv\Scripts\python.exe" main.py
) else (
	pip install -r requirements.txt --quiet || (echo Failed to install requirements. Run "pip install -r requirements.txt" for details. && pause && exit /b 1)
	python main.py
)
