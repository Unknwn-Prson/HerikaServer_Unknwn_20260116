@echo off
:: ============================================================
:: Ensure HTTP_TIMEOUT in HerikaServer conf.php is at least 30s.
:: Called from setup.bat.  Reads/writes via WSL.
:: ============================================================

set "CONF=/var/www/html/HerikaServer/conf/conf.php"

:: Check if conf.php exists in WSL
wsl -d DwemerAI4Skyrim3 -- test -f "%CONF%" 2>nul
if %errorlevel% neq 0 (
    echo       conf.php not found at %CONF% — skipping.
    exit /b 0
)

:: Use PHP inside WSL to read, check, and patch HTTP_TIMEOUT
wsl -d DwemerAI4Skyrim3 -- php -r "
$conf = '%CONF%';
$src  = file_get_contents($conf);
if ($src === false) { echo '      Could not read conf.php — skipping.' . PHP_EOL; exit(0); }

// Match $HTTP_TIMEOUT = <number>;
if (preg_match('/\\\$HTTP_TIMEOUT\s*=\s*(\d+)\s*;/', $src, $m)) {
    $val = (int)$m[1];
    if ($val >= 30) {
        echo '      HTTP_TIMEOUT is ' . $val . 's (OK).' . PHP_EOL;
        exit(0);
    }
    // Replace with 30
    $new = preg_replace('/\\\$HTTP_TIMEOUT\s*=\s*\d+\s*;/', '\$HTTP_TIMEOUT=30;', $src);
    file_put_contents($conf, $new);
    echo '      HTTP_TIMEOUT was ' . $val . 's — updated to 30s.' . PHP_EOL;
} else {
    // Not present at all — append it before closing ?>
    $tag = '?>';
    $insert = '\$HTTP_TIMEOUT=30;' . chr(9) . '//Timeout for AI requests.' . PHP_EOL;
    $pos = strrpos($src, $tag);
    if ($pos !== false) {
        $src = substr($src, 0, $pos) . $insert . $tag . PHP_EOL;
    } else {
        $src .= PHP_EOL . $insert;
    }
    file_put_contents($conf, $src);
    echo '      HTTP_TIMEOUT was not set — added as 30s.' . PHP_EOL;
}
"
