@echo off
:: ============================================================
:: CHIM Proxy v1 - WSL Setup
:: Double-click this on Windows. It copies the proxy into your
:: WSL distro and installs Python, pip deps, and Claude Code
:: inside WSL — no Windows Firewall needed.
:: ============================================================
setlocal enabledelayedexpansion

echo ============================================================
echo  CHIM Proxy v1 - WSL Setup
echo ============================================================
echo.

:: ---- 1. Check WSL exists ----
wsl --status >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] WSL is not installed or not running.
    echo         Install WSL first: wsl --install
    pause
    exit /b 1
)

:: ---- 2. Detect WSL distros ----
echo [1/5] Detecting WSL distros...

:: Get list of distros (skip blank lines, strip "(Default)" tag)
set "DISTRO_COUNT=0"
for /f "usebackq tokens=*" %%A in (`wsl -l -q 2^>nul`) do (
    set "LINE=%%A"
    :: Strip null bytes that wsl -l outputs (UTF-16)
    set "LINE=!LINE: =!"
    if not "!LINE!"=="" (
        set /a DISTRO_COUNT+=1
        set "DISTRO_!DISTRO_COUNT!=%%A"
    )
)

if %DISTRO_COUNT% equ 0 (
    echo [ERROR] No WSL distros found. Install one first.
    pause
    exit /b 1
)

if %DISTRO_COUNT% equ 1 (
    set "WSL_DISTRO=!DISTRO_1!"
    echo       Found: !WSL_DISTRO!
) else (
    echo       Found multiple distros:
    for /l %%I in (1,1,%DISTRO_COUNT%) do (
        echo         %%I^) !DISTRO_%%I!
    )
    echo.
    set /p DISTRO_CHOICE="  Which distro runs HerikaServer? [1-%DISTRO_COUNT%]: "
    set "WSL_DISTRO=!DISTRO_!DISTRO_CHOICE!!"
    if "!WSL_DISTRO!"=="" (
        echo [ERROR] Invalid choice.
        pause
        exit /b 1
    )
)

:: Trim any trailing whitespace/control chars from distro name
for /f "tokens=*" %%D in ("!WSL_DISTRO!") do set "WSL_DISTRO=%%D"
echo       Using: %WSL_DISTRO%

:: Save distro name so start_chim_proxy.bat knows which one to use
echo %WSL_DISTRO%> "%~dp0wsl_distro.txt"
echo.

:: ---- 3. Copy proxy files into WSL ----
echo [2/5] Copying proxy files into WSL...

:: Convert this bat's Windows folder path to a WSL mount path
set "WIN_DIR=%~dp0"
:: Remove trailing backslash
if "%WIN_DIR:~-1%"=="\" set "WIN_DIR=%WIN_DIR:~0,-1%"

:: Create target dir and copy files
wsl -d %WSL_DISTRO% -- bash -c "mkdir -p ~/chim_proxy && cp -f \"%WIN_DIR%/chim_proxy_v1.py\" \"%WIN_DIR%/requirements.txt\" \"%WIN_DIR%/start_chim_proxy.sh\" \"%WIN_DIR%/setup_wsl.sh\" ~/chim_proxy/ 2>/dev/null" >nul 2>&1

:: If direct path didn't work, try via wslpath
if %errorlevel% neq 0 (
    wsl -d %WSL_DISTRO% -- bash -c "WIN='$(wslpath '%WIN_DIR%')' && mkdir -p ~/chim_proxy && cp -f \"$WIN/chim_proxy_v1.py\" \"$WIN/requirements.txt\" \"$WIN/start_chim_proxy.sh\" \"$WIN/setup_wsl.sh\" ~/chim_proxy/"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to copy files into WSL.
        echo         Try manually: copy the chim_proxy folder into \\wsl.localhost\%WSL_DISTRO%\home\
        pause
        exit /b 1
    )
)
wsl -d %WSL_DISTRO% -- chmod +x ~/chim_proxy/start_chim_proxy.sh ~/chim_proxy/setup_wsl.sh
echo       Done! Files are in ~/chim_proxy/ inside WSL.
echo.

:: ---- 4. Install Python, pip deps, Node, Claude Code inside WSL ----
echo [3/5] Installing dependencies inside WSL...
echo       (You may be prompted for your WSL sudo password)
echo.

wsl -d %WSL_DISTRO% -- bash -c "cd ~/chim_proxy && echo '  [a] Python...' && (command -v python3 >/dev/null && echo '       Found: '$(python3 --version) || (sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv && echo '       Installed.')) && echo && echo '  [b] Pip dependencies...' && (python3 -m pip install --quiet -r requirements.txt 2>/dev/null || python3 -m pip install --quiet --break-system-packages -r requirements.txt) && echo '       Done.' && echo && echo '  [c] Node.js...' && (command -v node >/dev/null && echo '       Found: '$(node --version) || (curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - >/dev/null 2>&1 && sudo apt-get install -y -qq nodejs && echo '       Installed.')) && echo && echo '  [d] Claude Code CLI...' && (command -v claude >/dev/null && echo '       Found.' || (sudo npm install -g @anthropic-ai/claude-code >/dev/null 2>&1 && echo '       Installed.'))"

if %errorlevel% neq 0 (
    echo.
    echo [WARN] Some dependencies may not have installed correctly.
    echo        You can retry by running setup_wsl.sh inside WSL manually.
)
echo.

:: ---- 5. Claude Code login ----
echo [4/5] Claude Code authentication...
echo       A browser window should open. Sign in with your Anthropic account.
echo       (You need a Claude Pro, Max, or Teams subscription.)
echo       After login, type /exit or press Ctrl+C to continue.
echo.

wsl -d %WSL_DISTRO% -- bash -c "command -v claude >/dev/null && claude login || echo '[WARN] claude not found - restart terminal and run: claude login'"
echo.

:: ---- 6. Done ----
echo [5/5] Verifying installation...
wsl -d %WSL_DISTRO% -- bash -c "echo '  Python:      '$(python3 --version 2>/dev/null || echo 'NOT FOUND') && echo '  Claude Code: '$(claude --version 2>/dev/null || echo 'NOT FOUND') && echo '  Proxy files: '$(ls ~/chim_proxy/chim_proxy_v1.py 2>/dev/null && echo 'OK' || echo 'MISSING')"
echo.

echo ============================================================
echo  Setup complete!
echo.
echo  To start the proxy, double-click:
echo    start_chim_proxy.bat
echo.
echo  Your endpoint (from HerikaServer in WSL):
echo    http://127.0.0.1:8000/v1/chat/completions
echo ============================================================
pause
