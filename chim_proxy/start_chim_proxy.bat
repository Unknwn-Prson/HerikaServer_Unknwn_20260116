@echo off
setlocal

:: Read the WSL distro name saved by setup_wsl.bat
set "DISTRO_FILE=%~dp0wsl_distro.txt"
if not exist "%DISTRO_FILE%" (
    echo [ERROR] WSL distro not configured.
    echo         Run setup_wsl.bat first.
    pause
    exit /b 1
)
set /p WSL_DISTRO=<"%DISTRO_FILE%"

echo Starting CHIM Proxy in WSL (%WSL_DISTRO%)...
echo Press Ctrl+C to stop.
echo.

wsl -d %WSL_DISTRO% -- bash -c "cd ~/chim_proxy && python3 chim_proxy_v1.py"
pause
