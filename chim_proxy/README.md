# CHIM Proxy v1

An OpenAI-compatible API proxy that routes requests through a Claude subscription via the Claude Code CLI. Designed for use with [CHIM](https://github.com/MinLL/SkyrimNet-GamePlugin) to power AI-driven NPC conversations in Skyrim.

## How It Works

```
CHIM (game) --> POST /v1/chat/completions --> Proxy (port 8000) --> claude -p --> Anthropic API
```

1. **Per-request**: The proxy spawns a `claude -p` subprocess with context-minimization flags, writes the NPC's system prompt as a `CLAUDE.md` file in an isolated temp directory, and pipes the conversation to stdin.
2. **CLAUDE.md injection**: Claude Code auto-loads `CLAUDE.md` as a `<system-reminder>` with authority framing, giving it stronger weight than plain text in stdin.
3. **Response**: Translates Claude's output into OpenAI-compatible format (`chat.completion` or SSE `chat.completion.chunk`) that CHIM expects.

### Context Minimization

Each subprocess is launched with flags that strip unnecessary context:

| Flag | Effect |
|------|--------|
| `--tools=` | Removes all tool descriptions (~10-16K tokens saved) |
| `--disable-slash-commands` | Removes skill descriptions |
| `--max-turns 1` | Single response, no tool loops |
| `--system-prompt "..."` | Short roleplay directive (API system blocks) |
| `--no-session-persistence` | Don't save session to disk |
| `CLAUDE.md` in temp dir | Full NPC system prompt with authority framing |
| stdin | Conversation messages only |

Irreducible Claude Code overhead is ~105 tokens (billing notice + agent identity).

### Content Format Modes

Selectable at startup:

- **Array mode** (default): Preserves CHIM's native block structure as JSON arrays in both `CLAUDE.md` and stdin. Each message retains its `role` and `content` block array, matching the format CHIM itself uses.
- **Flat mode**: Flattens all content to plain text. Simpler but loses block boundaries.

### NPC Name Labeling

The proxy auto-detects the NPC name from the system prompt (patterns like "You are Brelyna Maryon") and prepends it to assistant messages for consistent speaker labeling. All speakers — player, NPCs, narrator, and the roleplayed character — are explicitly labeled in every conversation turn.

Can be overridden via an `npc_name` field in the request body.

## Requirements

- **Git for Windows** (required by Claude Code)
- **Python 3.10+**
- **Claude Code CLI** installed and authenticated with a Claude Pro, Max, or Teams subscription
- **Python packages**: `pip install -r requirements.txt`

## Quick Start

1. Right-click `setup.bat` → **Run as administrator** (installs everything + authenticates)
2. Double-click `start_chim_proxy.bat`
3. Select content format (Array recommended)
4. Configure your CHIM connector to point at `http://172.17.144.1:8000/v1/chat/completions`

See [INSTALLATION.md](INSTALLATION.md) for the full setup guide including CHIM connector configuration.

### Dashboard

Open `http://127.0.0.1:8000` in a browser to see the status dashboard with a quick test form.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions (streaming + non-streaming) |
| `/v1/models` | GET | List available models |
| `/health` | GET | Health check + current config |
| `/debug/system-prompt` | GET | View captured Claude Code system prompt |
| `/debug/requests` | GET | View recent request/response logs |
| `/` | GET | Web dashboard |

### Supported Models

The model is specified per-request by CHIM — no need to restart the proxy to switch models.

| Model ID | Name | Notes |
|----------|------|-------|
| `claude-opus-4-6` | Opus 4.6 | Most capable, highest latency |
| `claude-sonnet-4-6` | Sonnet 4.6 | Best balance of speed and quality |
| `claude-sonnet-4-5-20250929` | Sonnet 4.5 | Previous gen, fast |
| `claude-haiku-4-5-20251001` | Haiku 4.5 | Fastest, least capable |

## Files

| File | Description |
|------|-------------|
| `chim_proxy_v1.py` | Proxy server |
| `start_chim_proxy.bat` | Windows launch script |
| `setup.bat` | One-time setup (dependencies, Claude Code install, login, firewall, port forwarding) |
| `requirements.txt` | Python dependencies |
| `INSTALLATION.md` | Full setup guide with CHIM connector configuration |
| `logs/` | Created at runtime — contains `requests.log` and `system_prompt.log` |

## Troubleshooting

### Proxy won't start / "claude CLI not found"

- Ensure Claude Code is installed: `claude --version`
- Reopen your terminal after running `setup.bat` so PATH updates
- Reinstall manually: `irm https://claude.ai/install.ps1 | iex` (PowerShell)

### CHIM can't connect / timeout

- Make sure the proxy terminal is still running
- Run `setup.bat` as administrator if CHIM is in WSL
- Test: `curl http://172.17.144.1:8000/health` from inside WSL

### Empty or broken responses

- Check `logs/requests.log` for the full request/response dump
- Visit `/debug/requests` in your browser for recent logs
- Check the proxy terminal for error messages

### Slow responses with Opus

- Expected — Opus is the most capable but takes 5-15 seconds vs 2-5 for Sonnet
- Switch to Sonnet in your CHIM connector if speed matters more

## License

MIT
