@echo off
:: ============================================================
:: Ensure HTTP_TIMEOUT in HerikaServer conf.php is at least 30s.
:: Called from setup.bat.  Uses Python (already installed) and
:: the UNC path to read/write the file — no WSL shell needed.
:: ============================================================

set "CONF=\\wsl.localhost\DwemerAI4Skyrim3\var\www\html\HerikaServer\conf\conf.php"

if not exist "%CONF%" (
    echo       conf.php not found — skipping.
    exit /b 0
)

python "%~dp0ensure_timeout.py" "%CONF%"
exit /b 0
