@echo off
:: Start CHIM Proxy inside the DwemerAI4Skyrim3 WSL distro
setlocal

set "DISTRO=DwemerAI4Skyrim3"

echo Starting CHIM Proxy in WSL (%DISTRO%)...
echo Press Ctrl+C to stop.
echo.

wsl -d %DISTRO% -- bash -c "cd /chim_proxy && python3 chim_proxy_v1.py"
pause
