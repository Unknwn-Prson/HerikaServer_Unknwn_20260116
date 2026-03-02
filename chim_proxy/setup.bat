@echo off
setlocal
:: ============================================================
:: CHIM Proxy v0.9.5 - One-Time Setup
:: Must be run as Administrator!
:: ============================================================
:: Wrap in :main so pause ALWAYS runs, even on unexpected errors
call :main
echo.
pause
exit /b

:main
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script must be run as Administrator!
    echo Right-click setup.bat and select "Run as administrator"
    exit /b 1
)

echo ============================================================
echo  CHIM Proxy v0.9.5 - Setup
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
    exit /b 1
)
echo       Found Git.
echo.

:: 2. Check for Python
echo [2/8] Checking for Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed!
    echo        Download it from: https://www.python.org/downloads/
    echo        Make sure to check "Add Python to PATH" during install.
    exit /b 1
)
echo       Found Python.
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
    goto :claude_ensure_path
)

echo       Downloading and running Claude Code installer...
curl -fsSL https://claude.ai/install.cmd -o "%TEMP%\claude_install.cmd"
if %errorlevel% equ 0 goto :claude_curl_ok

echo [WARN] curl download failed. Trying winget ^(this may take a minute^)...
winget install Anthropic.ClaudeCode --accept-source-agreements --accept-package-agreements
if %errorlevel% equ 0 (
    echo       Installed via winget.
    goto :claude_ensure_path
)

echo [ERROR] Both curl and winget failed to install Claude Code.
echo        Try installing manually:
echo          Option A: Open PowerShell and run: irm https://claude.ai/install.ps1 ^| iex
echo          Option B: winget install Anthropic.ClaudeCode
exit /b 1

:claude_curl_ok
:: Run installer in a child process so its exit cannot kill this script
cmd /c call "%TEMP%\claude_install.cmd"
del "%TEMP%\claude_install.cmd" >nul 2>&1
echo       Done!

:: Ensure Claude Code is on PATH (the native installer sometimes forgets)
:claude_ensure_path
where claude >nul 2>&1
if %errorlevel% equ 0 goto :claude_path_ok

:: Check common install locations and add to PATH if found
set "CLAUDE_BIN="
if exist "%USERPROFILE%\.local\bin\claude.exe" set "CLAUDE_BIN=%USERPROFILE%\.local\bin"
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe" set "CLAUDE_BIN=%LOCALAPPDATA%\Microsoft\WinGet\Links"
if exist "%LOCALAPPDATA%\Programs\claude-code\claude.exe" set "CLAUDE_BIN=%LOCALAPPDATA%\Programs\claude-code"

if not defined CLAUDE_BIN (
    echo [WARN] Could not locate claude.exe after install.
    echo        You may need to install manually and restart your terminal.
    goto :claude_path_done
)

echo       Adding %CLAUDE_BIN% to user PATH...
:: Add to persistent user PATH via registry
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USER_PATH=%%B"
if not defined USER_PATH set "USER_PATH="
echo %USER_PATH% | findstr /I /C:"%CLAUDE_BIN%" >nul 2>&1
if %errorlevel% neq 0 (
    if "%USER_PATH%"=="" (
        setx PATH "%CLAUDE_BIN%" >nul 2>&1
    ) else (
        setx PATH "%USER_PATH%;%CLAUDE_BIN%" >nul 2>&1
    )
    echo       Persisted to user PATH.
)
:: Also add to current session so the rest of setup works
set "PATH=%PATH%;%CLAUDE_BIN%"

:claude_path_ok
echo       Claude Code is on PATH.
:claude_path_done
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
    goto :firewall_done
)
netsh advfirewall firewall add rule name="CHIM Proxy" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
if %errorlevel% equ 0 (
    echo       Done!
) else (
    echo [WARN] Failed to add firewall rule.
    echo        You can add it manually in Windows Firewall settings
    echo        or run: netsh advfirewall firewall add rule name="CHIM Proxy" dir=in action=allow protocol=TCP localport=8000
)
:firewall_done
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
    goto :login_done
)
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
:login_done
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
exit /b 0
