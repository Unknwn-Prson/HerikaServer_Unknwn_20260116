@echo off
:: ============================================================
:: CHIM Proxy v0.13.0 - One-Time Setup
:: Self-elevates to Administrator if needed.
:: ============================================================

:: Anchor working directory FIRST — UAC elevation starts in System32
:: and paths with spaces or special chars (like @) break without this.
cd /d "%~dp0"

:: Check for admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    :: Self-elevate: launch a new elevated cmd that cd's to our dir first,
    :: then runs this script. This avoids path-quoting issues with special
    :: characters (spaces, @) in the folder path during UAC elevation.
    powershell -Command "Start-Process cmd.exe -ArgumentList '/K cd /d \"%CD%\" && call \"%~nx0\"' -Verb RunAs"
    exit /b 0
)

echo ============================================================
echo  CHIM Proxy v0.13.0 - Setup
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
pause
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

:: 6. Windows Firewall - remove Python Block rules and add Allow rules
echo [6/9] Fixing Python firewall rules...
::    Windows often creates Block rules for Python on Public profile (which WSL uses)
::    These Block rules override any Allow rules, so we must remove them first
echo       Removing any Python Block rules on Public profile...
powershell -Command "Get-NetFirewallRule | Where-Object { $_.DisplayName -like '*python*' -and $_.Action -eq 'Block' } | Remove-NetFirewallRule" >nul 2>&1
powershell -Command "Get-NetFirewallRule | Where-Object { $_.DisplayName -like '*Python*' -and $_.Action -eq 'Block' } | Remove-NetFirewallRule" >nul 2>&1
netsh advfirewall firewall delete rule name="python.exe" profile=public >nul 2>&1
echo       Adding Python Allow rule for all profiles...
netsh advfirewall firewall delete rule name="Python (CHIM)" >nul 2>&1
netsh advfirewall firewall add rule name="Python (CHIM)" dir=in action=allow program="%LOCALAPPDATA%\Programs\Python\Python311\python.exe" profile=any enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="Python (CHIM)" dir=in action=allow program="%LOCALAPPDATA%\Programs\Python\Python312\python.exe" profile=any enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="Python (CHIM)" dir=in action=allow program="%LOCALAPPDATA%\Programs\Python\Python313\python.exe" profile=any enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="Python (CHIM)" dir=in action=allow program="%LOCALAPPDATA%\python\pythoncore-3.14-64\python.exe" profile=any enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="Python (CHIM)" dir=in action=allow program="%LOCALAPPDATA%\python\bin\python.exe" profile=any enable=yes >nul 2>&1
echo       Done!
echo.

:: 7. Windows Firewall rule (allow inbound on port 38700 for ALL profiles)
echo [7/9] Adding Windows Firewall rule for port 38700...
::    Always delete+recreate — previous installs may have a rule for a different port
netsh advfirewall firewall delete rule name="CHIM Proxy" >nul 2>&1
netsh advfirewall firewall add rule name="CHIM Proxy" dir=in action=allow protocol=TCP localport=38700 profile=any >nul 2>&1
if %errorlevel% equ 0 (
    echo       Done! (Enabled for Domain/Private/Public profiles)
) else (
    echo [WARN] Failed to add firewall rule.
    echo        You can add it manually in Windows Firewall settings
    echo        or run: netsh advfirewall firewall add rule name="CHIM Proxy" dir=in action=allow protocol=TCP localport=38700 profile=any
)
:firewall_done
echo.

:: 8. Clean up old port forwarding rules (no longer needed - proxy binds to WSL IP directly)
echo [8/9] Cleaning up old portproxy rules...
::    v0.11.0+ binds directly to WSL interface IP, so portproxy is not needed
::    Clean up any stale rules from previous versions
netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=172.17.144.1 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=38700 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=38700 listenaddress=172.17.144.1 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=38742 listenaddress=0.0.0.0 >nul 2>&1
echo       Cleaned up stale rules (portproxy no longer needed).
echo.

:: 8. Claude Code login (last — opens interactive TUI that blocks the script)
echo [9/9] Claude Code authentication...
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
echo    http://172.17.144.1:38700/v1/chat/completions
echo ============================================================
pause
