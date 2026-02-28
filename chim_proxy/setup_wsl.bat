@echo off
:: ============================================================
:: CHIM Proxy v1 - WSL Setup (DwemerAI4Skyrim3)
:: Double-click on Windows to install the proxy into WSL.
:: No admin rights needed.
:: ============================================================
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
if not exist "%WSL_UNC%\" (
    echo [ERROR] Distro "%DISTRO%" not found at %WSL_UNC%
    echo         Make sure WSL is running: wsl -d %DISTRO%
    pause
    exit /b 1
)
echo       Found.
echo.

:: ---- 2. Copy proxy files via UNC path ----
echo [2/5] Copying proxy files to %TARGET%\...
if not exist "%TARGET%\" mkdir "%TARGET%"
copy /y "%SRC%chim_proxy_v1.py"      "%TARGET%\" >nul
copy /y "%SRC%requirements.txt"      "%TARGET%\" >nul
copy /y "%SRC%start_chim_proxy.sh"   "%TARGET%\" >nul
copy /y "%SRC%setup_wsl.sh"          "%TARGET%\" >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy files.
    pause
    exit /b 1
)
:: Fix permissions (Windows copy doesn't set +x)
wsl -d %DISTRO% -- chmod +x /chim_proxy/start_chim_proxy.sh /chim_proxy/setup_wsl.sh
echo       Done.
echo.

:: ---- 3. Install Python, pip deps, Node, Claude Code inside WSL ----
echo [3/5] Installing dependencies inside WSL...
echo       (You may be prompted for your WSL sudo password)
echo.

wsl -d %DISTRO% -- bash -c ^
"cd /chim_proxy && ^
echo '  [a] Python...' && ^
(command -v python3 >/dev/null && echo '       Found: '$(python3 --version) || ^
 (sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv && echo '       Installed.')) && ^
echo && ^
echo '  [b] Pip dependencies...' && ^
(python3 -m pip install --quiet -r requirements.txt 2>/dev/null || ^
 python3 -m pip install --quiet --break-system-packages -r requirements.txt) && ^
echo '       Done.' && ^
echo && ^
echo '  [c] Node.js...' && ^
(command -v node >/dev/null && echo '       Found: '$(node --version) || ^
 (curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - >/dev/null 2>&1 && ^
  sudo apt-get install -y -qq nodejs && echo '       Installed.')) && ^
echo && ^
echo '  [d] Claude Code CLI...' && ^
(command -v claude >/dev/null && echo '       Found.' || ^
 (sudo npm install -g @anthropic-ai/claude-code >/dev/null 2>&1 && echo '       Installed.'))"

if %errorlevel% neq 0 (
    echo.
    echo [WARN] Some dependencies may not have installed correctly.
    echo        You can retry by running setup_wsl.sh inside WSL manually:
    echo          wsl -d %DISTRO% -- bash /chim_proxy/setup_wsl.sh
)
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
wsl -d %DISTRO% -- bash -c "echo '  Python:      '$(python3 --version 2>/dev/null || echo 'NOT FOUND') && echo '  Claude Code: '$(claude --version 2>/dev/null || echo 'NOT FOUND') && echo '  Proxy files: '$(test -f /chim_proxy/chim_proxy_v1.py && echo 'OK' || echo 'MISSING')"
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
