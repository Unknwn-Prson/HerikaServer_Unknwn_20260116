@echo off
:: ============================================================
:: CHIM Proxy v1 - WSL Setup (DwemerAI4Skyrim3)
:: Double-click on Windows to install the proxy into WSL.
:: No admin rights needed.
:: ============================================================

:: Keep the window open no matter what — even on crash.
:: The first launch (no args) re-invokes itself with cmd /k.
if "%~1"=="" (
    cmd /k "%~f0" run
    exit /b
)

setlocal
set "DISTRO=DwemerAI4Skyrim3"
set "WSL_UNC=\\wsl.localhost\%DISTRO%"
set "TARGET=%WSL_UNC%\chim_proxy"
set "SRC=%~dp0"

echo ============================================================
echo  CHIM Proxy v1 - WSL Setup
echo ============================================================
echo.

:: ---- 1. Verify the distro exists ----
echo [1/5] Checking for WSL distro "%DISTRO%"...
if not exist "%WSL_UNC%\." (
    echo [ERROR] Distro "%DISTRO%" not found at %WSL_UNC%
    echo         Make sure WSL is running: wsl -d %DISTRO%
    goto :done
)
echo       Found.
echo.

:: ---- 2. Copy proxy files via UNC path ----
echo [2/5] Copying proxy files to %TARGET%\...
if not exist "%TARGET%\." mkdir "%TARGET%"

copy /y "%SRC%chim_proxy_v1.py"      "%TARGET%\" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy chim_proxy_v1.py
    goto :done
)
copy /y "%SRC%requirements.txt"      "%TARGET%\" >nul 2>&1
copy /y "%SRC%start_chim_proxy.sh"   "%TARGET%\" >nul 2>&1
copy /y "%SRC%setup_wsl.sh"          "%TARGET%\" >nul 2>&1

echo       Copied files. Setting permissions...
wsl -d %DISTRO% -- chmod +x /chim_proxy/start_chim_proxy.sh /chim_proxy/setup_wsl.sh 2>&1
echo       Done.
echo.

:: ---- 3. Install dependencies inside WSL ----
echo [3/5] Installing dependencies inside WSL...
echo       (You may be prompted for your WSL sudo password)
echo.

echo   [a] Python...
wsl -d %DISTRO% -- bash -c "command -v python3 >/dev/null && echo '       Found: '$(python3 --version) || (sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv && echo '       Installed.')"
echo.

echo   [b] Pip dependencies...
wsl -d %DISTRO% -- bash -c "cd /chim_proxy && (python3 -m pip install --quiet -r requirements.txt 2>/dev/null || python3 -m pip install --quiet --break-system-packages -r requirements.txt) && echo '       Done.'"
echo.

echo   [c] Node.js...
wsl -d %DISTRO% -- bash -c "command -v node >/dev/null && echo '       Found: '$(node --version) || (curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - >/dev/null 2>&1 && sudo apt-get install -y -qq nodejs && echo '       Installed.')"
echo.

echo   [d] Claude Code CLI...
wsl -d %DISTRO% -- bash -c "command -v claude >/dev/null && echo '       Found.' || (sudo npm install -g @anthropic-ai/claude-code 2>&1 && echo '       Installed.')"
echo.

:: ---- 4. Claude Code login ----
echo [4/5] Claude Code authentication...
echo       A browser window should open. Sign in with your Anthropic account.
echo       (You need a Claude Pro, Max, or Teams subscription.)
echo       After login, type /exit or press Ctrl+C to continue.
echo.

wsl -d %DISTRO% -- bash -c "command -v claude >/dev/null && claude login || echo '[WARN] claude not found - restart terminal and run: claude login'"
echo.

:: ---- 5. Verify ----
echo [5/5] Verifying installation...
wsl -d %DISTRO% -- bash -c "echo '  Python:      '$(python3 --version 2>/dev/null || echo 'NOT FOUND')"
wsl -d %DISTRO% -- bash -c "echo '  Claude Code: '$(claude --version 2>/dev/null || echo 'NOT FOUND')"
wsl -d %DISTRO% -- bash -c "test -f /chim_proxy/chim_proxy_v1.py && echo '  Proxy files: OK' || echo '  Proxy files: MISSING'"
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

:done
echo.
pause
