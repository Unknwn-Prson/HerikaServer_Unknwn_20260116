@echo off
:: ============================================================
:: CHIM Format Proxy — Stop
:: ============================================================

setlocal EnableDelayedExpansion

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
set "PID_FILE=/var/www/html/HerikaServer/temp/format_proxy.pid"

wsl -d %WSL_DISTRO% -- bash -c "if [ -f %PID_FILE% ]; then kill $(cat %PID_FILE%) 2>/dev/null && rm -f %PID_FILE% && echo STOPPED; else echo NOT_RUNNING; fi"

echo.
echo Format proxy stopped.
pause
