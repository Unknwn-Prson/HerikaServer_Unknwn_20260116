# CHIM Proxy v0.9.1 — Installation Guide

Complete setup guide for using Claude models with CHIM/SkyrimNet via a local proxy.

---

## Prerequisites

- [Git for Windows](https://git-scm.com/downloads/win) (required by Claude Code)
- [Python 3.10+](https://www.python.org/downloads/) (make sure to check "Add Python to PATH" during install)
- A **Claude Pro, Max, or Teams** subscription

## Step 1: Run setup

Right-click `setup.bat` and select **Run as administrator**. This will:

1. Check that Git and Python are installed
2. Install Python dependencies (`fastapi`, `uvicorn`, `pydantic`)
3. Install the Claude Code CLI (via the official installer)
4. Open your browser to log in to your Anthropic account
5. Configure Windows Firewall to allow connections on port 8000
6. Set up port forwarding so WSL can reach the proxy on Windows

> You only need to run setup once. If you're running CHIM natively on Windows (not in WSL), steps 5-6 are still applied but won't cause issues.

## Step 2: Start the proxy

Double-click `start_chim_proxy.bat` (or run `python chim_proxy_v1.py` from a terminal).

On startup, you'll be asked to choose a content format:

```
  CHIM Proxy v0.9.1 — Startup Configuration

  Content format for system prompt and conversation:
    [1] Array  — preserve CHIM block structure (JSON arrays in CLAUDE.md and stdin)
    [2] Flat   — flatten to plain text (original behavior)

  Select format [1/2] (default: 1):
```

- **Array** (recommended): preserves CHIM's native block structure, giving the model the same context layout CHIM itself uses
- **Flat**: joins all blocks into plain text, simpler but loses structural information

The proxy will start listening on `http://127.0.0.1:8000`.

You can verify it's working by opening `http://127.0.0.1:8000` in your browser — you'll see a dashboard with a quick test button.

> **Important:** The proxy must stay running in its terminal window while you play.

---

## Step 3: Configure the CHIM connector

In the CHIM web interface, create or edit a connector with these settings:

| Setting | Value |
|---------|-------|
| **Name** | `Claude Opus 4.6` (or whichever model) |
| **Service** | `Custom` (the gear icon, rightmost option) |
| **URL** | `http://172.17.144.1:8000/v1/chat/completions` |
| **Model** | See table below |
| **Provider** | *(leave empty)* |
| **Driver** | `OpenAI JSON` |
| **API Key** | `Nano-GPT — No key` |
| **Reasoning Model** | `Off` |
| **Enforce JSON** | `On` |
| **JSON Schema** | `On` |
| **Prefill JSON** | `Off` |

### Available models

The proxy accepts any of these model IDs in the request. CHIM sends the model field with each request, so you can switch models by changing the connector setting — no need to restart the proxy.

| Model ID | Name | Speed | Quality |
|----------|------|-------|---------|
| `claude-opus-4-6` | Opus 4.6 | Slower | Best |
| `claude-sonnet-4-6` | Sonnet 4.6 | Fast | Great |
| `claude-sonnet-4-5-20250929` | Sonnet 4.5 | Fast | Good |
| `claude-haiku-4-5-20251001` | Haiku 4.5 | Fastest | Basic |

### Finding your endpoint URL

If CHIM runs in **WSL on the same machine**, use:
```
http://172.17.144.1:8000/v1/chat/completions
```

If that doesn't work, find your Windows host IP from inside WSL:
```bash
cat /etc/resolv.conf | grep nameserver
```

If CHIM runs **natively on Windows** (not in WSL), use:
```
http://127.0.0.1:8000/v1/chat/completions
```

### NPC name override (optional)

The proxy auto-detects the NPC name from the system prompt (e.g. "You are Brelyna Maryon") and prepends it to assistant messages for consistent speaker labeling. If detection fails or you want to override it, add an `npc_name` field to the request body:

```json
{
  "model": "claude-opus-4-6",
  "messages": [...],
  "npc_name": "Brelyna Maryon"
}
```

---

## Troubleshooting

### Proxy won't start / "claude CLI not found"

- Make sure Claude Code is installed: `claude --version`
- If you just ran setup, close and reopen your terminal so the PATH updates
- You can reinstall manually: open PowerShell and run `irm https://claude.ai/install.ps1 | iex`

### "claude login" didn't work / auth errors

- Run `claude login` manually in a terminal
- You need a Claude Pro, Max, or Teams subscription (free tier does not include Claude Code)
- Try `claude -p "hello"` to verify the CLI works

### CHIM can't connect / connection timeout

- Make sure the proxy terminal is still running
- If CHIM runs in WSL, make sure you ran `setup.bat` as administrator
- Check the URL in the connector uses the correct IP and port 8000
- Test from inside WSL: `curl http://172.17.144.1:8000/health`

### CHIM test button fails / NPCs don't talk

- Check the proxy terminal for error messages
- Verify the Model field exactly matches a model ID from the table above
- Check `logs/requests.log` next to the proxy script for detailed request/response dumps

### Slow responses with Opus

- This is expected — Opus models produce higher quality output but take longer (5-15 seconds vs 2-5 for Sonnet)
- If speed matters more, switch to Sonnet in your CHIM connector settings
