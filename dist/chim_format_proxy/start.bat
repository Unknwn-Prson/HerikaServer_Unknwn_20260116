@echo off
setlocal EnableDelayedExpansion
:: ============================================================
:: CHIM Format Proxy - Start
:: Starts the proxy inside WSL via a persistent wsl process.
:: ============================================================

cd /d "%~dp0"

set "WSL_DISTRO="
for %%D in (DwemerAI4Skyrim3 DwemerAI4Skyrim DwemerDistro Ubuntu) do (
    wsl -d %%D -- echo ok >nul 2>&1
    if !errorlevel! equ 0 (
        set "WSL_DISTRO=%%D"
        goto :found
    )
)
echo [ERROR] No CHIM WSL distribution found.
pause
exit /b 1

:found
set "HERIKA_PATH=/var/www/html/HerikaServer"
set "PROXY_SCRIPT=%HERIKA_PATH%/proxy/chim_format_proxy.py"
set "LOG_FILE=%HERIKA_PATH%/proxy/logs/format_proxy.log"

:: Check if already running
wsl -d %WSL_DISTRO% -- curl -sf http://127.0.0.1:38800/health >nul 2>&1
if %errorlevel% equ 0 (
    echo Format proxy is already running.
    echo Dashboard: http://localhost:38800/
    pause
    exit /b 0
)

:: Start the proxy using a minimized window running wsl
:: The wsl.exe process stays alive, which keeps the python process alive.
:: Using "start /min" opens it in a minimized console window.
echo Starting CHIM Format Proxy...
start "CHIM Format Proxy" /min wsl -d %WSL_DISTRO% -- bash -c "cd %HERIKA_PATH%/proxy && python3 %PROXY_SCRIPT% 2>&1 | tee -a %LOG_FILE%"

:: Wait for startup
echo Waiting for proxy to initialize...
timeout /t 3 /nobreak >nul

:: Verify
wsl -d %WSL_DISTRO% -- curl -sf http://127.0.0.1:38800/health >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo Format proxy started successfully!
    echo Dashboard: http://localhost:38800/
    echo.
    echo The proxy runs in a minimized window. Close that window to stop it.
    pause
    exit /b 0
)

echo.
echo [WARN] Proxy may not have started. Check the log:
echo   wsl -d %WSL_DISTRO% -- tail -20 %LOG_FILE%
pause
exit /b 1
