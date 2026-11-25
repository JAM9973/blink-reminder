@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python virtual environment is missing. See README.md.
    exit /b 1
)
".venv\Scripts\python.exe" "blink_app.py" --desktop %*
