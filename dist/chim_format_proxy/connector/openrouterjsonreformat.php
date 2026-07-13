<?php
/**
 * CHIM Format Proxy Connector v0.1.2
 *
 * Thin wrapper around openrouterjson that:
 * 1. Reads config from its own globals namespace ("openrouterjsonreformat")
 * 2. Auto-starts the format proxy if installed but not running
 *
 * All transformation logic lives in the Python format proxy.
 * This connector inherits ALL behavior from openrouterjson — open(), process(),
 * processActions(), close(), fast_request(), etc. — unchanged.
 *
 * See proxy/DESIGN.md for architecture documentation.
 */

require_once(__DIR__ . "/openrouterjson.php");

class openrouterjsonreformat extends openrouterjson
{
    public function __construct()
    {
        parent::__construct();
        // Override name so config reads from $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]
        // instead of $GLOBALS["CONNECTOR"]["openrouterjson"]
        $this->name = "openrouterjsonreformat";

        $this->_ensureProxy();
    }

    /**
     * Check if the format proxy is running; start it if installed but down.
     * No-op if proxy files are not installed.
     */
    private function _ensureProxy()
    {
        $proxyScript = __DIR__ . "/../proxy/chim_format_proxy.py";
        if (!file_exists($proxyScript)) {
            return; // Proxy not installed — nothing to do
        }

        // Read configured port (default 38800)
        $port = 38800;
        if (isset($GLOBALS["CONNECTOR"][$this->name]["x_proxy_port"])) {
            $port = intval($GLOBALS["CONNECTOR"][$this->name]["x_proxy_port"]);
        }

        // Quick health check (500ms timeout)
        $ctx = stream_context_create(['http' => ['timeout' => 0.5, 'ignore_errors' => true]]);
        $health = @file_get_contents("http://127.0.0.1:{$port}/health", false, $ctx);
        if ($health !== false) {
            return; // Proxy is running
        }

        // Try PID file check before spawning
        $pidFile = __DIR__ . "/../temp/format_proxy.pid";
        if (file_exists($pidFile)) {
            $pid = intval(trim(@file_get_contents($pidFile)));
            if ($pid > 0 && function_exists('posix_kill') && @posix_kill($pid, 0)) {
                // Process exists but health check failed — give it a moment
                usleep(200000);
                return;
            }
        }

        // Spawn the proxy as a background process inside WSL
        // Both PHP and the proxy run in the same WSL instance, so exec() works
        $logFile = __DIR__ . "/../proxy/logs/format_proxy.log";
        $logDir = dirname($logFile);
        if (!is_dir($logDir)) {
            @mkdir($logDir, 0755, true);
        }
        @exec("nohup python3 " . escapeshellarg($proxyScript) . " " . intval($port)
              . " >> " . escapeshellarg($logFile) . " 2>&1 &");
        usleep(500000); // 500ms for startup

        error_log("[openrouterjsonreformat] Started format proxy via direct spawn on port {$port}");
    }
}
