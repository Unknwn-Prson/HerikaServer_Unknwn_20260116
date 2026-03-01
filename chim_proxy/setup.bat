@echo off
:: ============================================================
:: CHIM Proxy v0.9.1 - One-Time Setup
:: Must be run as Administrator!
:: ============================================================
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script must be run as Administrator!
    echo Right-click setup.bat and select "Run as administrator"
    pause
    exit /b 1
)

echo ============================================================
echo  CHIM Proxy v0.9.1 - Setup
echo ============================================================
echo.

:: 1. Check for Git (required by Claude Code)
echo [1/8] Checking for Git...
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed!
    echo        Claude Code requires Git for Windows.
    echo        Download it from: https://git-scm.com/downloads/win
    echo        Install Git first, then re-run this setup.
    pause
    exit /b 1
) else (
    echo       Found Git.
)
echo.

:: 2. Check for Python
echo [2/8] Checking for Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed!
    echo        Download it from: https://www.python.org/downloads/
    echo        Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
) else (
    echo       Found Python.
)
echo.

:: 3. Install Python dependencies
echo [3/8] Installing Python dependencies...
cd /d "%~dp0"
python -c "import ensurepip; ensurepip._main()" >nul 2>&1
python -c "import subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt']))"
if %errorlevel% neq 0 (
    echo [WARN] Package install had issues - you may need to fix manually
) else (
    echo       Done!
)
echo.

:: 4. Install Claude Code
echo [4/8] Installing Claude Code...
where claude >nul 2>&1
if %errorlevel% equ 0 (
    echo       Claude Code is already installed.
) else (
    echo       Downloading and running Claude Code installer...
    curl -fsSL https://claude.ai/install.cmd -o "%TEMP%\claude_install.cmd"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to download Claude Code installer.
        echo        Try installing manually:
        echo          Open PowerShell and run: irm https://claude.ai/install.ps1 ^| iex
        pause
        exit /b 1
    )
    call "%TEMP%\claude_install.cmd"
    del "%TEMP%\claude_install.cmd" >nul 2>&1
    echo       Done!
    echo.
    echo       NOTE: You may need to restart this terminal for 'claude'
    echo       to appear on your PATH. If step 5 fails, close this window,
    echo       re-open as Administrator, and re-run setup.bat.
)
echo.

:: 5. Ensure HTTP_TIMEOUT in HerikaServer conf.php is at least 30s
echo [5/8] Checking HerikaServer HTTP_TIMEOUT...
python "%~dp0ensure_timeout.py"
echo.

:: 6. Windows Firewall rule (allow inbound on port 8000)
echo [6/8] Adding Windows Firewall rule for port 8000...
netsh advfirewall firewall show rule name="CHIM Proxy" >nul 2>&1
if %errorlevel% equ 0 (
    echo       Rule already exists, skipping.
) else (
    netsh advfirewall firewall add rule name="CHIM Proxy" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
    if %errorlevel% equ 0 (
        echo       Done!
    ) else (
        echo [WARN] Failed to add firewall rule.
        echo        You can add it manually in Windows Firewall settings
        echo        or run: netsh advfirewall firewall add rule name="CHIM Proxy" dir=in action=allow protocol=TCP localport=8000
    )
)
echo.

:: 7. Port proxy so WSL can reach the proxy on Windows
echo [7/8] Setting up port forwarding (WSL to Windows)...
netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy add v4tov4 ^
    listenport=8000 listenaddress=0.0.0.0 ^
    connectport=8000 connectaddress=127.0.0.1
if %errorlevel% equ 0 (
    echo       Done!
) else (
    echo [WARN] Failed to add port proxy rule
)
echo.

:: 8. Claude Code login (last — opens interactive TUI that blocks the script)
echo [8/8] Claude Code authentication...
where claude >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] 'claude' not found on PATH yet.
    echo        Restart your terminal and run: claude login
    echo        You need a Claude Pro, Max, or Teams subscription.
) else (
    echo       Launching Claude Code login...
    echo       A browser window should open. Sign in with your Anthropic account.
    echo       (You need a Claude Pro, Max, or Teams subscription.)
    echo.
    echo       NOTE: This opens an interactive session. Once you are logged in,
    echo       type /exit or press Ctrl+C to return to setup.
    echo.
    claude login
    if %errorlevel% neq 0 (
        echo [WARN] Login may not have completed. You can retry with: claude login
    ) else (
        echo       Authenticated!
    )
)
echo.

echo ============================================================
echo  Setup complete!
echo.
echo  To start the proxy, run:
echo    start_chim_proxy.bat
echo.
echo  Your endpoint (from WSL/HerikaServer):
echo    http://172.17.144.1:8000/v1/chat/completions
echo ============================================================
pause
