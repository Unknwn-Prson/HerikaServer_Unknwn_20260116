@echo off
setlocal EnableDelayedExpansion
:: ============================================================
:: CHIM NPC Biography Leak Fix - Apply patch
:: Runs apply_npc_bio_leak_fix.py against the WSL HerikaServer.
:: Idempotent and safe to re-run (e.g. after a CHIM update).
:: ============================================================

cd /d "%~dp0"

echo ============================================================
echo  CHIM NPC Biography Leak Fix
echo ============================================================
echo.

:: --- Build /mnt/ path for this directory (so WSL can read the .py) ---
set "WINDIR_RAW=%~dp0"
set "DRIVE_LETTER=%WINDIR_RAW:~0,1%"
for %%A in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do (
    if /i "!DRIVE_LETTER!"=="%%A" set "DRIVE_LOWER=%%A"
)
set "PATH_PART=%WINDIR_RAW:~3%"
set "PATH_PART=%PATH_PART:\=/%"
set "WSL_SRC=/mnt/%DRIVE_LOWER%/%PATH_PART%"
set "PATCHER=%WSL_SRC%apply_npc_bio_leak_fix.py"

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
echo         Edit this script and set WSL_DISTRO manually.
pause
exit /b 1

:found_distro
echo [1/3] Found WSL distribution: %WSL_DISTRO%

:: --- Detect HerikaServer path ---
set "HERIKA_PATH=/var/www/html/HerikaServer"
wsl -d %WSL_DISTRO% -- test -d %HERIKA_PATH%
if %errorlevel% neq 0 (
    echo [ERROR] HerikaServer not found at %HERIKA_PATH%
    echo         Edit this script and set HERIKA_PATH manually.
    pause
    exit /b 1
)
echo [2/3] Found HerikaServer at %HERIKA_PATH%
echo.

:: --- Run the patcher ---
echo [3/3] Applying patch...
echo.
wsl -d %WSL_DISTRO% -- python3 "%PATCHER%" %HERIKA_PATH%
set "RC=%errorlevel%"
echo.

if %RC% neq 0 (
    echo ============================================================
    echo  Patch FAILED. No changes were written. See messages above.
    echo ============================================================
    pause
    exit /b %RC%
)

echo ============================================================
echo  Patch applied successfully.
echo  Takes effect on the next request - no restart required.
echo  A .npcbiofix.bak backup was saved next to the patched file.
echo ============================================================
pause
exit /b 0
