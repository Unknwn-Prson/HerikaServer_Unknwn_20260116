@echo off
cd /d "%~dp0"

:: Log everything to a file so we can diagnose silent crashes
set "LOGFILE=%~dp0startup.log"
echo [%date% %time%] START >> "%LOGFILE%"

:: Prefer the real Python over the Microsoft Store stub
set "PYTHON="
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Python\bin\python.exe"
    echo [%date% %time%] Found Python: %LOCALAPPDATA%\Python\bin\python.exe >> "%LOGFILE%"
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :found_python
)
:: Fall back to PATH
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] FAIL: Python not found >> "%LOGFILE%"
    echo [ERROR] Python is not installed or not on PATH.
    pause
    exit /b 1
)
set "PYTHON=python"

:found_python
echo Using Python: %PYTHON%
echo [%date% %time%] Using Python: %PYTHON% >> "%LOGFILE%"

:: Check required packages
"%PYTHON%" -c "import fastapi, uvicorn, pydantic" 2>nul
if %errorlevel% neq 0 (
    echo [%date% %time%] FAIL: Missing packages >> "%LOGFILE%"
    echo [ERROR] Missing Python packages.
    pause
    exit /b 1
)
echo [%date% %time%] Packages OK >> "%LOGFILE%"

:: Check Claude CLI
where claude >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] FAIL: Claude CLI not found >> "%LOGFILE%"
    echo [ERROR] Claude Code CLI is not on PATH.
    pause
    exit /b 1
)
echo [%date% %time%] Claude CLI OK >> "%LOGFILE%"

:: Run the proxy
echo [%date% %time%] Launching proxy... >> "%LOGFILE%"
"%PYTHON%" chim_proxy_v1.py
echo [%date% %time%] Proxy exited with code %errorlevel% >> "%LOGFILE%"
pause
