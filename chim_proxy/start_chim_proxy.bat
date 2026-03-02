@echo off
cd /d "%~dp0"

:: Check Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not on PATH. Run setup.bat first, then restart your terminal.
    pause
    exit /b 1
)

:: Check required packages
python -c "import fastapi, uvicorn, pydantic" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Missing Python packages (fastapi/uvicorn/pydantic).
    echo         Run setup.bat first, or manually:
    echo           pip install -r requirements.txt
    pause
    exit /b 1
)

:: Check Claude CLI
where claude >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Claude Code CLI is not on PATH. Run setup.bat first.
    pause
    exit /b 1
)

python chim_proxy_v1.py
pause
