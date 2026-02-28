@echo off
:: Self-elevate to admin if not already (needed for firewall rules)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges for firewall access...
    powershell -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
    exit /b
)

cd /d "%~dp0"

:: Ensure firewall rule exists for the proxy port
netsh advfirewall firewall delete rule name="CHIM Proxy" >nul 2>&1
netsh advfirewall firewall add rule name="CHIM Proxy" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
echo Firewall rule set for port 8000.

python chim_proxy_v1.py
pause
