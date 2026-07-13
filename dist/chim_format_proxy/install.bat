@echo off
setlocal EnableDelayedExpansion
:: ============================================================
:: CHIM Format Proxy - Installation
:: Copies files into WSL HerikaServer and installs dependencies.
:: ============================================================

cd /d "%~dp0"

echo ============================================================
echo  CHIM Format Proxy - Installation
echo ============================================================
echo.

:: --- Build /mnt/ path for this directory ---
:: Convert "C:\Users\Jean\Downloads\chim_format_proxy\" to "/mnt/c/Users/Jean/Downloads/chim_format_proxy/"
set "WINDIR_RAW=%~dp0"
:: Get drive letter, lowercase it
set "DRIVE_LETTER=%WINDIR_RAW:~0,1%"
:: Lowercase the drive letter
for %%A in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do (
    if /i "!DRIVE_LETTER!"=="%%A" set "DRIVE_LOWER=%%A"
)
:: Build the /mnt/ path: strip "C:\", replace \ with /, prepend /mnt/c/
set "PATH_PART=%WINDIR_RAW:~3%"
set "PATH_PART=%PATH_PART:\=/%"
set "WSL_SRC=/mnt/%DRIVE_LOWER%/%PATH_PART%"

:: --- Detect WSL distribution ---
set "WSL_DISTRO="
for %%D in (DwemerAI4Skyrim3 DwemerAI4Skyrim DwemerDistro Ubuntu) do (
    wsl -d %%D -- echo ok >nul 2>&1
    if !errorlevel! equ 0 (
        set "WSL_DISTRO=%%D"
        goto :found_distro
    )
)

echo [ERROR] Could not find a CHIM WSL distribution.
echo         Please edit this script and set WSL_DISTRO manually.
pause
exit /b 1

:found_distro
echo [1/5] Found WSL distribution: %WSL_DISTRO%
echo.

:: --- Detect HerikaServer path ---
set "HERIKA_PATH=/var/www/html/HerikaServer"
wsl -d %WSL_DISTRO% -- test -d %HERIKA_PATH%
if %errorlevel% neq 0 (
    echo [ERROR] HerikaServer not found at %HERIKA_PATH%
    echo         Please edit this script and set HERIKA_PATH manually.
    pause
    exit /b 1
)
echo [2/6] Found HerikaServer at %HERIKA_PATH%
echo.

:: --- Copy files ---
echo [3/6] Copying files to WSL...

:: Create directories
wsl -d %WSL_DISTRO% -- mkdir -p %HERIKA_PATH%/proxy/logs %HERIKA_PATH%/proxy/cache %HERIKA_PATH%/temp

:: Copy each file using /mnt/ path (reliable cross-filesystem copy)
call :wsl_copy "proxy/chim_format_proxy.py"    "%HERIKA_PATH%/proxy/chim_format_proxy.py"
call :wsl_copy "proxy/dialogue_cache.py"       "%HERIKA_PATH%/proxy/dialogue_cache.py"
call :wsl_copy "proxy/proxy_config.yaml"       "%HERIKA_PATH%/proxy/proxy_config.yaml"
call :wsl_copy "proxy/requirements.txt"        "%HERIKA_PATH%/proxy/requirements.txt"
call :wsl_copy "connector/openrouterjsonreformat.php" "%HERIKA_PATH%/connector/openrouterjsonreformat.php"
call :wsl_copy "proxy/apply_patches.py"            "%HERIKA_PATH%/proxy/apply_patches.py"

echo       Done!
echo.

:: --- Install Python dependencies ---
echo [4/6] Installing Python dependencies in WSL...
:: Use apt (preferred on Debian 12+ which enforces PEP 668)
wsl -d %WSL_DISTRO% -- bash -c "apt-get install -y -qq python3-httpx python3-yaml 2>&1 | tail -1"
:: Verify
wsl -d %WSL_DISTRO% -- python3 -c "import httpx, yaml" >nul 2>&1
if %errorlevel% neq 0 (
    echo   apt install incomplete, trying pip with --break-system-packages...
    wsl -d %WSL_DISTRO% -- pip3 install --break-system-packages -q httpx pyyaml 2>&1
)
echo       Done!
echo.

:: --- Set permissions ---
echo [5/6] Setting permissions...
wsl -d %WSL_DISTRO% -- chown -R www-data:www-data %HERIKA_PATH%/proxy 2>nul
wsl -d %WSL_DISTRO% -- chmod +x %HERIKA_PATH%/proxy/chim_format_proxy.py 2>nul
echo       Done!
echo.

:: --- Apply CHIM patches ---
echo [6/6] Applying CHIM patches...
echo.
wsl -d %WSL_DISTRO% -- python3 %HERIKA_PATH%/proxy/apply_patches.py %HERIKA_PATH%
echo.

echo ============================================================
echo  Installation complete!
echo.
echo  NEXT STEPS:
echo.
echo  1. Start the proxy:
echo     Run start.bat (or it auto-starts on first use)
echo.
echo  2. In CHIM UI, create a new LLM Connector:
echo     - Service: Custom
echo     - Driver: openrouterjsonreformat
echo     - URL: http://127.0.0.1:38800/v1/chat/completions?upstream=https://openrouter.ai/api/v1/chat/completions
echo     - Configure Input/Output format settings
echo.
echo  Dashboard: http://localhost:38800/ (from Windows browser)
echo ============================================================
pause
exit /b 0

:: ---------------------------------------------------------------
:: Helper: copy a file from this directory into WSL via /mnt/ path
:: Usage: call :wsl_copy "relative/source" "/absolute/dest"
:: ---------------------------------------------------------------
:wsl_copy
set "REL_SRC=%~1"
set "DEST=%~2"
:: Convert backslashes to forward slashes in source
set "REL_SRC=%REL_SRC:\=/%"
echo   %REL_SRC%
wsl -d %WSL_DISTRO% -- cp "%WSL_SRC%%REL_SRC%" "%DEST%"
if %errorlevel% neq 0 (
    echo   [WARN] Failed to copy %REL_SRC%
)
exit /b 0
