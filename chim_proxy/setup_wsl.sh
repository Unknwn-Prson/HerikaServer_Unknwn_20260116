#!/usr/bin/env bash
# ============================================================
# CHIM Proxy v1 - WSL Setup
# Run this inside your WSL distro (e.g. DwemerAI4Skyrim3)
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo " CHIM Proxy v1 - WSL Setup"
echo "============================================================"
echo

# 1. Python
echo "[1/4] Checking for Python..."
if command -v python3 &>/dev/null; then
    echo "       Found: $(python3 --version)"
else
    echo "       Installing Python..."
    sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv
    echo "       Done."
fi
echo

# 2. pip dependencies
echo "[2/4] Installing Python dependencies..."
python3 -m pip install --quiet -r requirements.txt 2>/dev/null \
    || python3 -m pip install --quiet --break-system-packages -r requirements.txt
echo "       Done."
echo

# 3. Claude Code CLI
echo "[3/4] Checking for Claude Code CLI..."
if command -v claude &>/dev/null; then
    echo "       Found: $(claude --version 2>/dev/null || echo 'installed')"
else
    echo "       Installing Claude Code..."
    # Node.js is required — install if missing
    if ! command -v node &>/dev/null; then
        echo "       Installing Node.js first..."
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - 2>/dev/null
        sudo apt-get install -y -qq nodejs
    fi
    npm install -g @anthropic-ai/claude-code
    echo "       Done."
fi
echo

# 4. Claude Code login
echo "[4/4] Claude Code authentication..."
if command -v claude &>/dev/null; then
    echo "       Launching Claude Code login..."
    echo "       Sign in with your Anthropic account (Pro/Max/Teams required)."
    echo "       After login, type /exit or press Ctrl+C to continue."
    echo
    claude login
else
    echo "[WARN] 'claude' not found on PATH."
    echo "       Close this terminal, reopen, and run: claude login"
fi
echo

echo "============================================================"
echo " Setup complete!"
echo
echo " To start the proxy:"
echo "   ./start_chim_proxy.sh"
echo
echo " Your endpoint (from HerikaServer in WSL):"
echo "   http://127.0.0.1:8000/v1/chat/completions"
echo "============================================================"
