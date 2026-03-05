"""
OpenAI-compatible proxy using Claude Code CLI legitimately.  v0.13.0

Architecture:
  Per-request: spawns `claude -p` subprocess routed through a local MITM
  HTTP proxy that intercepts the Claude Code → Anthropic API call.

  System prompt delivery (MITM rewrite):
    The MITM proxy intercepts POST requests to api.anthropic.com and:
      1. Strips Claude Code's injected system blocks (agent/coding prompts)
      2. Injects CHIM content directly into API system blocks with
         cache_control: {'type': 'ephemeral'} for prompt caching
      3. Strips <system-reminder> context injections from user messages
      4. Applies dialogue caching based on HerikaServer temp files
    This bypasses CLAUDE.md entirely — no <system-reminder> wrapper overhead.

Context minimization (applied per request):
  --tools=                    → removes ALL built-in tool descriptions (~10-16K tokens saved)
  --disable-slash-commands    → removes skill/slash-command descriptions from context
  --max-turns 1               → single response, no tool loops
  --effort <level>            → reasoning effort: low, medium, high (when enabled)
  stdin                       → conversation messages only (dialogue history)

  Environment variables:
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1  → skip telemetry/update checks
    DISABLE_NON_ESSENTIAL_MODEL_CALLS=1         → skip warmup/background model calls

Performance notes:
  Each request spawns a subprocess (~1-3s overhead for CLI init + API call).
  Concurrency is limited by MAX_CONCURRENT semaphore.
  No persistent connection reuse — each subprocess opens its own connection.

Content format (selectable at startup):
  Array mode  → preserves CHIM's block structure as JSON arrays in stdin
  Flat mode   → flattens content to plain text (original behavior)

NPC name handling:
  Auto-detected from system prompt ("You are [Name]" / "Name: [Name]")
  Can be overridden via "npc_name" field in the request body
  Prepended to assistant messages for consistent speaker labeling

Usage:
  pip install fastapi uvicorn pydantic
  python chim_proxy_v1.py
  # Then point any OpenAI-compatible client at http://127.0.0.1:38700/v1/chat/completions
"""
import asyncio
import http.client
import http.server
import json
import logging
import os
import re
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Union

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("proxy")

DEFAULT_MODEL = "claude-opus-4-5-20251101"

# ---------------------------------------------------------------------------
# Dialogue Caching Configuration
# ---------------------------------------------------------------------------
# Path to HerikaServer temp directory (where dialogue cache files are stored)
# Default assumes WSL path; can be overridden via environment variable
DIALOGUE_CACHE_PATH = os.environ.get(
    "CHIM_DIALOGUE_CACHE_PATH",
    r"\\wsl.localhost\DwemerAI4Skyrim3\var\www\html\HerikaServer\temp"
)

# Number of recent dialogue messages to leave uncached (for freshness)
# This should match dialogue_cache_uncached_count in HerikaServer connector config
DIALOGUE_CACHE_UNCACHED_COUNT = int(os.environ.get("CHIM_DIALOGUE_UNCACHED_COUNT", "5"))

# NPC cache state file (stores reroll counters and last access times)
_SCRIPT_DIR_EARLY = Path(__file__).resolve().parent
NPC_CACHE_STATE_FILE = _SCRIPT_DIR_EARLY / "logs" / "npc_cache_state.json"

# Cache state expiry (1 hour of no requests = state cleared)
CACHE_STATE_EXPIRY_SECONDS = 3600

# Known provider prefixes to strip from model names (e.g. "anthropic/claude-sonnet-4-6" → "claude-sonnet-4-6")
_PROVIDER_PREFIXES = ("anthropic/", "openrouter/", "openai/")


def _normalize_model(model: str) -> str:
    """Strip provider prefixes from model names so the Claude CLI receives a bare model ID."""
    for prefix in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix):]
    return model

MAX_CONCURRENT = 4

# ---------------------------------------------------------------------------
# Request History (in-memory, doesn't persist)
# ---------------------------------------------------------------------------
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional
import threading

@dataclass
class RequestHistoryEntry:
    """Single request entry for the dashboard history."""
    request_id: str
    timestamp: str
    npc_name: Optional[str]
    model: str
    input_chars: int
    output_chars: int
    elapsed_seconds: float
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    input_tokens: int = 0
    cache_hit_pct: float = 0.0

# Thread-safe request history storage
_request_history: deque = deque(maxlen=50)  # Keep last 50 requests
_history_lock = threading.Lock()


def _record_request_history(request_id: str, npc_name: Optional[str], model: str,
                            input_chars: int, output_chars: int, elapsed: float,
                            cache_stats: Optional[dict] = None):
    """Record a completed request to the history deque."""
    cache_read = cache_stats.get("cache_read", 0) if cache_stats else 0
    cache_write = cache_stats.get("cache_creation", 0) if cache_stats else 0
    input_tokens = cache_stats.get("input_tokens", 0) if cache_stats else 0
    
    # Calculate cache hit percentage
    total = input_tokens + cache_read + cache_write
    cache_hit_pct = (cache_read / total * 100) if total > 0 else 0.0
    
    entry = RequestHistoryEntry(
        request_id=request_id,
        timestamp=time.strftime("%H:%M:%S"),
        npc_name=npc_name,
        model=model.split("-")[1] if "-" in model else model,  # Shorten model name
        input_chars=input_chars,
        output_chars=output_chars,
        elapsed_seconds=round(elapsed, 1),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        input_tokens=input_tokens,
        cache_hit_pct=round(cache_hit_pct, 1)
    )
    
    with _history_lock:
        _request_history.append(entry)

# Extended thinking / reasoning settings (configurable at startup)
# Maps to Claude CLI --effort flag (low / medium / high)
THINKING_ENABLED = False
THINKING_EFFORT = "medium"  # Default effort level when thinking is on

# Valid effort levels for Claude models
_VALID_EFFORTS = ("low", "medium", "high")


CLAUDE_PATH = shutil.which("claude")
if not CLAUDE_PATH:
    raise RuntimeError("claude CLI not found on PATH")
logger.info(f"Using Claude CLI: {CLAUDE_PATH}")

# Per-request temp dirs are created in call_claude() — no shared WORK_DIR needed

_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# Subprocess environment — disable non-essential traffic and allow nesting
_ENV = os.environ.copy()
_ENV["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
_ENV["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
_ENV.pop("CLAUDECODE", None)  # Allow spawning claude from within a Claude Code terminal

# Content format: "array" (CHIM-style JSON block arrays) or "flat" (plain text)
# Set interactively at startup via __main__
CONTENT_FORMAT = "flat"

# Streaming mode: "real" (token-by-token via --output-format stream-json) or "fake" (collect then chunk)
# Set interactively at startup via __main__
STREAMING_MODE = "fake"


# ---------------------------------------------------------------------------
# Message conversion helpers
# ---------------------------------------------------------------------------

def _flatten_content(content) -> str:
    """Normalize OpenAI content (string or array-of-blocks) to plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _content_to_blocks(content) -> list[dict]:
    """Normalize content to CHIM-style array of {"type": "text", "text": ...} blocks."""
    if isinstance(content, list):
        blocks = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                blocks.append({"type": "text", "text": block.get("text", "")})
            elif isinstance(block, str):
                blocks.append({"type": "text", "text": block})
        return blocks
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [{"type": "text", "text": str(content)}]


def _detect_npc_name(system_contents: list) -> Optional[str]:
    """Try to extract the roleplayed NPC's name from system message content.

    Looks for common CHIM patterns like 'You are Brelyna Maryon' or
    'Name: Brelyna Maryon' across all system blocks.
    Handles markdown formatting like **bold** around names.
    """
    all_text = ""
    for content in system_contents:
        if isinstance(content, str):
            all_text += content + "\n"
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    all_text += block.get("text", "") + "\n"
                elif isinstance(block, str):
                    all_text += block + "\n"

    # Strip markdown bold markers for matching
    clean_text = all_text.replace("**", "")
    
    for pattern in [
        r'(?:You are|Your name is|you are|your name is)\s+([A-Z][a-zA-Z\'-]+(?:\s+[A-Z][a-zA-Z\'-]+)*)',
        r'(?:Name|CHARACTER)\s*:\s*([A-Z][a-zA-Z\'-]+(?:\s+[A-Z][a-zA-Z\'-]+)*)',
        r'(?:Roleplay as|roleplay as)\s+([A-Z][a-zA-Z\'-]+(?:\s+[A-Z][a-zA-Z\'-]+)*)',
    ]:
        match = re.search(pattern, clean_text)
        if match:
            name = match.group(1).strip()
            logger.info(f"Detected NPC name: {name}")
            return name
    return None


def _extract_messages(
    raw_messages: list, npc_name_override: Optional[str] = None,
) -> tuple[str, Optional[str], list[dict], Optional[str]]:
    """Split OpenAI messages into (prompt_head, claude_md, conversation, npc_name).

    Returns:
      prompt_head  — content from <roleplay_instructions> (used as --system-prompt)
      claude_md    — remainder of system message (written to CLAUDE.md)
      conversation — formatted dialogue messages
      npc_name     — detected or overridden NPC name

    Respects the global CONTENT_FORMAT:
      'flat'  — system prompt is plain text, conversation content is plain text
      'array' — system prompt is a JSON array of CHIM-style blocks,
                conversation content is plain text (each turn becomes one block
                in _format_prompt)

    NPC name is detected from system content (or overridden) and prepended to
    assistant messages for consistent speaker labeling.
    """
    system_contents = []   # raw content values (str or list-of-blocks)
    conversation_raw = []  # (role, raw_content)

    for msg in raw_messages:
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")

        if role == "system":
            system_contents.append(content)
        elif role in ("user", "assistant"):
            conversation_raw.append((role, content))

    # Detect or use override NPC name
    npc_name = npc_name_override or _detect_npc_name(system_contents)

    # Flatten all system content to extract PROMPT_HEAD
    prompt_head = ""
    if not system_contents:
        claude_md = None
    elif CONTENT_FORMAT == "array":
        # In array mode, flatten first to find <roleplay_instructions>, then
        # rebuild the remainder as a JSON block array for CLAUDE.md
        flat_system = "\n\n".join(_flatten_content(c) for c in system_contents)
        prompt_head, remainder = _split_prompt_head(flat_system)
        if remainder:
            # Re-encode remainder as CHIM-style block array
            claude_md = json.dumps(
                [{"type": "text", "text": remainder}], indent=2, ensure_ascii=False,
            )
        else:
            claude_md = None
    else:
        flat_system = "\n\n".join(_flatten_content(c) for c in system_contents)
        prompt_head, remainder = _split_prompt_head(flat_system)
        claude_md = remainder if remainder else None

    # Format conversation
    conversation = []
    for role, content in conversation_raw:
        if CONTENT_FORMAT == "array":
            # Preserve block structure — each message keeps its content array
            blocks = _content_to_blocks(content)
            if role == "assistant" and npc_name:
                for block in blocks:
                    if not block["text"].lstrip().startswith(npc_name):
                        block["text"] = f"{npc_name}: {block['text']}"
            conversation.append({"role": role, "content": blocks})
        else:
            # Flat mode — flatten to plain text
            text = _flatten_content(content)
            if role == "assistant" and npc_name and not text.lstrip().startswith(npc_name):
                text = f"{npc_name}: {text}"
            conversation.append({"role": role, "content": text})

    return prompt_head, claude_md, conversation, npc_name


def _format_prompt(conversation: list[dict]) -> str:
    """Format conversation for stdin piped to claude -p.

    In 'array' mode: JSON array of one block per turn (CHIM structure).
    In 'flat' mode: labeled transcript (original behavior).
    """
    if not conversation:
        return "Hello."

    if CONTENT_FORMAT == "array":
        # Conversation is already in CHIM structure: [{role, content: [blocks]}, ...]
        return json.dumps(conversation, indent=2, ensure_ascii=False)

    # Flat mode
    if len(conversation) == 1:
        return conversation[0]["content"]

    parts = []
    for msg in conversation:
        label = "Human" if msg["role"] == "user" else "Assistant"
        parts.append(f"{label}: {msg['content']}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Claude CLI subprocess interface
# ---------------------------------------------------------------------------

# Regex to extract <roleplay_instructions>…</roleplay_instructions> (PROMPT_HEAD) from CHIM system messages
_PROMPT_HEAD_RE = re.compile(
    r"<roleplay_instructions>\n?([\s\S]*?)\n?</roleplay_instructions>\n*",
)


def _split_prompt_head(system_text: str) -> tuple[str, str]:
    """Split PROMPT_HEAD out of a CHIM system message.

    Returns (prompt_head, remainder) where:
      - prompt_head: the content inside <roleplay_instructions>…</roleplay_instructions>
      - remainder:   everything else (for CLAUDE.md)
    If no <roleplay_instructions> block is found, returns ("", original) so
    the full system text goes to CLAUDE.md (safe for any size on Windows).
    """
    match = _PROMPT_HEAD_RE.search(system_text)
    if not match:
        return "", system_text
    prompt_head = match.group(1).strip()
    remainder = _PROMPT_HEAD_RE.sub("", system_text).strip()
    return prompt_head, remainder

# File where the captured real system prompt is written
# Log dir next to this .py file (visible from Windows desktop)
_SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = _SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
SYSTEM_PROMPT_LOG = LOG_DIR / "system_prompt.log"
REQUEST_LOG = LOG_DIR / "requests.log"


# ---------------------------------------------------------------------------
# NPC Cache State Management (reroll counters, last access tracking)
# ---------------------------------------------------------------------------

def _load_npc_cache_state() -> dict:
    """Load NPC cache state from file, cleaning expired entries."""
    if not NPC_CACHE_STATE_FILE.exists():
        return {}
    try:
        with open(NPC_CACHE_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        # Clean expired entries
        now = time.time()
        cleaned = {}
        for npc, data in state.items():
            if now - data.get("last_access", 0) < CACHE_STATE_EXPIRY_SECONDS:
                cleaned[npc] = data
        if len(cleaned) != len(state):
            _save_npc_cache_state(cleaned)
        return cleaned
    except Exception as e:
        logger.warning(f"Failed to load NPC cache state: {e}")
        return {}


def _save_npc_cache_state(state: dict) -> None:
    """Save NPC cache state to file."""
    try:
        NPC_CACHE_STATE_FILE.parent.mkdir(exist_ok=True)
        with open(NPC_CACHE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save NPC cache state: {e}")


def _get_npc_reroll_count(npc_name: str) -> int:
    """Get the reroll counter for an NPC (0 = no reroll)."""
    state = _load_npc_cache_state()
    return state.get(npc_name, {}).get("reroll_count", 0)


def _increment_npc_reroll(npc_name: str) -> int:
    """Increment the reroll counter for an NPC. Returns new count."""
    state = _load_npc_cache_state()
    if npc_name not in state:
        state[npc_name] = {"reroll_count": 0, "last_access": time.time()}
    state[npc_name]["reroll_count"] = state[npc_name].get("reroll_count", 0) + 1
    state[npc_name]["last_access"] = time.time()
    _save_npc_cache_state(state)
    return state[npc_name]["reroll_count"]


def _touch_npc_cache(npc_name: str) -> None:
    """Update last access time for an NPC."""
    state = _load_npc_cache_state()
    if npc_name not in state:
        state[npc_name] = {"reroll_count": 0, "last_access": time.time()}
    else:
        state[npc_name]["last_access"] = time.time()
    _save_npc_cache_state(state)


def _clear_npc_reroll(npc_name: str) -> None:
    """Clear the reroll counter for an NPC."""
    state = _load_npc_cache_state()
    if npc_name in state:
        state[npc_name]["reroll_count"] = 0
        state[npc_name]["last_access"] = time.time()
        _save_npc_cache_state(state)


def _list_cached_npcs() -> list[dict]:
    """List all NPCs with dialogue cache files."""
    npcs = []
    cache_path = Path(DIALOGUE_CACHE_PATH)
    if not cache_path.exists():
        return npcs
    
    state = _load_npc_cache_state()
    
    # Find dialogue cache files
    for f in cache_path.glob("combined_dialogue_cache_*.tmp"):
        # Extract NPC name from filename: combined_dialogue_cache_simple_Brelyna Maryon.tmp
        name_match = re.search(r"combined_dialogue_cache_\w+_(.+)\.tmp$", f.name)
        if name_match:
            npc_name = name_match.group(1)
            npc_state = state.get(npc_name, {})
            try:
                stat = f.stat()
                npcs.append({
                    "name": npc_name,
                    "dialogue_cache_size": stat.st_size,
                    "last_modified": stat.st_mtime,
                    "reroll_count": npc_state.get("reroll_count", 0),
                    "last_access": npc_state.get("last_access", 0),
                })
            except Exception:
                pass
    
    return sorted(npcs, key=lambda x: x.get("last_access", 0), reverse=True)


# ---------------------------------------------------------------------------
# Dialogue Cache Reading
# ---------------------------------------------------------------------------

def _load_dialogue_cache(npc_name: str) -> Optional[list[dict]]:
    """Load dialogue cache for an NPC from temp file.
    
    Returns list of {type: "text", text: "..."} blocks, or None if not found.
    """
    cache_path = Path(DIALOGUE_CACHE_PATH)
    
    if not cache_path.exists():
        logger.warning(f"Dialogue cache path does not exist: {DIALOGUE_CACHE_PATH}")
        return None
    
    # Try both simple and json format filenames
    for fmt in ["simple", "json"]:
        cache_file = cache_path / f"combined_dialogue_cache_{fmt}_{npc_name}.tmp"
        logger.info(f"Looking for dialogue cache: {cache_file}")
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    blocks = json.loads(content)
                    if isinstance(blocks, list):
                        logger.info(f"Loaded dialogue cache for {npc_name}: {len(blocks)} blocks from {fmt} format")
                        return blocks
            except Exception as e:
                logger.warning(f"Failed to load dialogue cache for {npc_name}: {e}")
    
    logger.info(f"No dialogue cache file found for {npc_name}")
    return None


def _get_last_cached_message_text(dialogue_cache: list[dict]) -> Optional[str]:
    """Get the text of the last message that SHOULD be cached.
    
    The cutoff is calculated as: len(blocks) - DIALOGUE_CACHE_UNCACHED_COUNT - 1
    Everything up to and including this index should have cache_control.
    """
    if not dialogue_cache:
        return None
    
    # Calculate cutoff index (last message to cache)
    # If uncached_count is 5 and we have 10 messages, cutoff is at index 4 (5th message)
    # Messages 0-4 get cached, messages 5-9 stay uncached
    cutoff_index = len(dialogue_cache) - DIALOGUE_CACHE_UNCACHED_COUNT - 1
    
    if cutoff_index < 0:
        # Not enough messages to have any cached - everything is uncached
        logger.info(f"Dialogue cache too small ({len(dialogue_cache)} blocks) "
                   f"for uncached count ({DIALOGUE_CACHE_UNCACHED_COUNT})")
        return None
    
    # Get the text at the cutoff index
    block = dialogue_cache[cutoff_index]
    if isinstance(block, dict) and block.get("type") == "text":
        text = block.get("text", "").strip()
        if text:
            logger.info(f"Cache cutoff at index {cutoff_index}/{len(dialogue_cache)-1}: "
                       f"{text[:60]}...")
            return text
    
    return None


def _find_cache_cutoff_index(messages: list[dict], last_cached_text: str) -> int:
    """Find the index in messages content where the last cached text appears.
    
    Returns the index of the block containing last_cached_text, or -1 if not found.
    Messages are expected to be in Anthropic format with content arrays.
    """
    if not last_cached_text:
        return -1
    
    # Normalize the text for matching (strip whitespace, normalize newlines)
    normalized_cached = last_cached_text.strip().replace("\r\n", "\n")
    
    for msg in messages:
        content = msg.get("content", [])
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    block_text = block.get("text", "").strip().replace("\r\n", "\n")
                    if block_text == normalized_cached:
                        logger.info(f"Found cache cutoff at block index {i}")
                        return i
    
    return -1


# ---------------------------------------------------------------------------
# Local intercepting proxy — captures the real API request body
# ---------------------------------------------------------------------------

_ANTHROPIC_API_HOST = "api.anthropic.com"

# SSL context for MITM → Anthropic connections.
# Uses system CA certs; falls back to unverified if certs are missing (common in WSL).
try:
    _SSL_CTX = ssl.create_default_context()
except Exception:
    _SSL_CTX = ssl._create_unverified_context()
    logger.warning("SSL certificate verification disabled — system CA certs not found")


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    """Tiny HTTP proxy that captures the POST body and forwards to Anthropic.

    Captured body is stored on self.server.captured_body so each HTTPServer
    instance is isolated (safe for concurrent per-request MITM proxies).

    CRITICAL: The response is streamed through in real-time using HTTP
    chunked transfer encoding.  Anthropic sends SSE via chunked TE —
    buffering the entire response before forwarding causes Claude CLI's
    Node.js/libuv runtime to crash (UV_HANDLE_CLOSING assertion on Windows).
    """

    def log_message(self, *args):
        pass  # suppress default http.server logging

    def handle_one_request(self):
        """Override to suppress ConnectionResetError from keep-alive probes."""
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self.close_connection = True

    # Regex to match <system-reminder>...</system-reminder> blocks injected
    # by Claude Code into user messages (e.g. currentDate context).
    # DOTALL so . matches newlines within the tag.
    _SYSTEM_REMINDER_RE = re.compile(
        r'<system-reminder>.*?</system-reminder>\s*', re.DOTALL
    )

    def _strip_system_reminders(self, api_body: dict) -> None:
        """Remove <system-reminder> tags from user message content blocks.

        Claude Code injects context like currentDate into the first user
        message as <system-reminder>...</system-reminder>.  This wastes
        tokens and is irrelevant to the actual conversation.  We strip it
        at the network layer so the model never sees it.

        Safety: never leaves a message with empty content — the Anthropic
        API would reject it with 400, causing the CLI to error out.
        """
        for msg in api_body.get("messages", []):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                cleaned = self._SYSTEM_REMINDER_RE.sub("", content)
                if cleaned.strip():
                    msg["content"] = cleaned
                # else: stripping would empty the message — leave it as-is
            elif isinstance(content, list):
                new_blocks = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        cleaned = self._SYSTEM_REMINDER_RE.sub("", text)
                        if cleaned.strip():
                            block["text"] = cleaned
                            new_blocks.append(block)
                        # else: entire block was a system-reminder — drop it
                    else:
                        new_blocks.append(block)
                # Safety: never set empty content — keep original if all blocks stripped
                if new_blocks:
                    msg["content"] = new_blocks

    def _rewrite_system_blocks(self, body: bytes) -> bytes:
        """Replace Claude Code's system blocks with our own content,
        strip <system-reminder> tags from user messages, and add dialogue caching.

        System block rewrite:
          Block 0: billing metadata (no cache_control) — KEEP
          Block 1+: Claude Code agent/coding prompts — STRIP
          Replaced with our PROMPT_HEAD and CHIM content blocks.

        User message cleanup:
          <system-reminder>...</system-reminder> context injections — STRIP

        Dialogue caching (if npc_name is set):
          - Loads dialogue cache from temp file
          - Finds last cached message in the messages
          - Adds cache_control to all content blocks up to that point
          
        Reroll support:
          - If reroll counter > 0, adds trailing whitespace to last system block
            to invalidate cache (invisible to Claude, changes hash)
        """
        replacement = getattr(self.server, "system_replacement", None)
        npc_name = getattr(self.server, "npc_name", None)
        
        if not replacement:
            return body
        try:
            api_body = json.loads(body)
            old_system = api_body.get("system", [])
            new_system = []

            # Keep block 0 (billing/metadata — identified by lack of cache_control)
            if old_system and isinstance(old_system[0], dict) and not old_system[0].get("cache_control"):
                new_system.append(old_system[0])

            # Get reroll count for this NPC
            reroll_count = 0
            if npc_name:
                reroll_count = _get_npc_reroll_count(npc_name)
                _touch_npc_cache(npc_name)

            # Inject our content blocks with ephemeral caching
            for i, text in enumerate(replacement):
                block = {
                    "type": "text",
                    "text": text,
                    "cache_control": {"type": "ephemeral"},
                }
                # Apply reroll suffix to the LAST system block if reroll is active
                if reroll_count > 0 and i == len(replacement) - 1:
                    # Unique invisible suffix per reroll count — never repeats
                    suffix = f" <!-- reroll {reroll_count} -->"
                    block["text"] = text + suffix
                    logger.info(f"[MITM] Applied reroll suffix (count={reroll_count}) for {npc_name}")
                new_system.append(block)

            api_body["system"] = new_system

            # Strip <system-reminder> injections from user messages
            self._strip_system_reminders(api_body)

            # Apply dialogue caching if NPC name is available
            if npc_name:
                self._apply_dialogue_caching(api_body, npc_name)

            rewritten = json.dumps(api_body, ensure_ascii=False).encode("utf-8")

            # Update captured body so logs reflect what the model actually receives
            self.server.captured_body = rewritten
            return rewritten
        except Exception as e:
            logger.warning(f"[MITM] system block rewrite failed: {e}")
            return body  # Fall through with original on any error

    def _apply_dialogue_caching(self, api_body: dict, npc_name: str) -> bool:
        """Add cache_control markers to dialogue messages based on temp file cache.
        
        The dialogue cache temp file contains individual message blocks, but Claude Code
        often sends them as one large text block. We need to:
        1. Find the cutoff text from the temp file
        2. Locate it within the request content (either as exact block match or substring)
        3. If it's a single large block, split it at the cutoff point and add cache marker
        
        Returns True if caching was applied, False otherwise.
        """
        dialogue_cache = _load_dialogue_cache(npc_name)
        if not dialogue_cache:
            logger.info(f"[MITM] No dialogue cache found for {npc_name}")
            return False
        
        last_cached_text = _get_last_cached_message_text(dialogue_cache)
        if not last_cached_text:
            logger.info(f"[MITM] Dialogue cache for {npc_name} is empty or cutoff invalid")
            return False
        
        # Normalize the cached text for matching
        normalized_cached = last_cached_text.strip().replace("\r\n", "\n").replace("\r", "\n")
        logger.info(f"[MITM] Looking for cutoff text ({len(normalized_cached)} chars): {normalized_cached[:80]}...")
        
        messages = api_body.get("messages", [])
        
        for msg_idx, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            
            # Handle string content (convert to list format)
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
                msg["content"] = content
                api_body["messages"][msg_idx]["content"] = content  # Explicit update
            
            if not isinstance(content, list):
                continue
            
            logger.info(f"[MITM] Searching through {len(content)} content blocks")
            
            # Strategy 1: Try exact block match first
            cutoff_index = -1
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    block_text = block.get("text", "").strip().replace("\r\n", "\n").replace("\r", "\n")
                    if block_text == normalized_cached:
                        cutoff_index = i
                        logger.info(f"[MITM] Found exact block match at index {i}")
                        break
            
            if cutoff_index >= 0:
                # Apply cache_control to blocks up to and including cutoff
                for i in range(cutoff_index + 1):
                    if isinstance(content[i], dict) and "cache_control" not in content[i]:
                        content[i]["cache_control"] = {"type": "ephemeral"}
                cached_count = cutoff_index + 1
                uncached_count = len(content) - cached_count
                logger.info(f"[MITM] Dialogue caching (exact match) for {npc_name}: "
                           f"{cached_count} blocks cached, {uncached_count} uncached")
                return True
            
            # Strategy 2: Substring search within blocks (for single large block case)
            for i, block in enumerate(content):
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                block_text = block.get("text", "")
                normalized_block = block_text.replace("\r\n", "\n").replace("\r", "\n")
                
                # Find where the cutoff text ends within this block
                cutoff_pos = normalized_block.find(normalized_cached)
                if cutoff_pos >= 0:
                    # Found it! Split the block at the end of the cached portion
                    split_point = cutoff_pos + len(normalized_cached)
                    
                    cached_part = block_text[:split_point]
                    uncached_part = block_text[split_point:].lstrip("\n")  # Remove leading newlines from uncached
                    
                    logger.info(f"[MITM] Found cutoff via substring at position {cutoff_pos}, "
                               f"splitting block (cached: {len(cached_part)} chars, uncached: {len(uncached_part)} chars)")
                    
                    if uncached_part:
                        # Replace single block with two blocks: cached + uncached
                        new_blocks = content[:i]  # Keep any blocks before this one
                        new_blocks.append({
                            "type": "text",
                            "text": cached_part,
                            "cache_control": {"type": "ephemeral"}
                        })
                        new_blocks.append({
                            "type": "text",
                            "text": uncached_part
                        })
                        new_blocks.extend(content[i+1:])  # Keep any blocks after this one
                        
                        # CRITICAL: Update both msg and api_body directly
                        msg["content"] = new_blocks
                        api_body["messages"][msg_idx]["content"] = new_blocks
                        
                        logger.info(f"[MITM] Dialogue caching (split) for {npc_name}: "
                                   f"content now has {len(new_blocks)} blocks")
                        
                        # Verify the update
                        verify = api_body["messages"][msg_idx]["content"]
                        has_cache = any(b.get("cache_control") for b in verify if isinstance(b, dict))
                        logger.info(f"[MITM] Verification: {len(verify)} blocks, has_cache_control={has_cache}")
                    else:
                        # Cutoff is at the very end - just add cache_control
                        block["cache_control"] = {"type": "ephemeral"}
                        logger.info(f"[MITM] Dialogue caching (end match) for {npc_name}: "
                                   f"entire block cached")
                    
                    return True
        
        # Debug: show what we have
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if isinstance(content, list) and len(content) > 0:
                block = content[0]
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")[:200]
                    logger.info(f"[MITM] First block preview: {text}...")
            break
        logger.warning(f"[MITM] Could not find cache cutoff for {npc_name} - "
                      f"cutoff text not found in any message content")
        return False

    def _forward(self, method: str):
        req_id = getattr(self.server, "_mitm_id", "?")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        logger.info(f"[MITM-{req_id}] {method} {self.path} ({len(body)} bytes)")
        if method == "POST":
            self.server.captured_body = body
            body = self._rewrite_system_blocks(body)
            logger.info(f"[MITM-{req_id}] rewritten body: {len(body)} bytes")

        # Rebuild headers for the real API (update Content-Length if body was rewritten)
        fwd = {}
        for key, val in self.headers.items():
            lk = key.lower()
            if lk == "host":
                continue
            if lk == "content-length":
                fwd[key] = str(len(body)) if body else "0"
                continue
            fwd[key] = val
        fwd["Host"] = _ANTHROPIC_API_HOST

        try:
            logger.info(f"[MITM-{req_id}] connecting to {_ANTHROPIC_API_HOST}...")
            conn = http.client.HTTPSConnection(_ANTHROPIC_API_HOST, timeout=300,
                                                context=_SSL_CTX)
            conn.request(method, self.path, body or None, fwd)
            resp = conn.getresponse()
            logger.info(f"[MITM-{req_id}] API responded: {resp.status}")

            if resp.status >= 400:
                # Log API errors — these often explain silent failures
                err_body = resp.read()
                logger.warning(f"[MITM-{req_id}] API error {resp.status}: "
                               f"{err_body[:500].decode(errors='replace')}")
                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    lk = key.lower()
                    if lk in ("transfer-encoding", "connection"):
                        continue
                    self.send_header(key, val)
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)
                self.wfile.flush()
                conn.close()
                return

            # Forward status + headers — use chunked TE for real-time streaming
            self.send_response(resp.status)
            for key, val in resp.getheaders():
                lk = key.lower()
                if lk in ("transfer-encoding", "content-length", "connection"):
                    continue
                self.send_header(key, val)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            # Stream response through in real-time (critical for SSE)
            # read1() returns data from the buffer or a single recv() call,
            # so it yields data as soon as it arrives — no multi-second stalls.
            total_bytes = 0
            response_buffer = b""  # Accumulate for cache telemetry extraction
            while True:
                chunk = resp.read1(16384)
                if not chunk:
                    break
                total_bytes += len(chunk)
                response_buffer += chunk  # Keep for telemetry parsing
                # HTTP chunked encoding: hex-size CRLF data CRLF
                self.wfile.write(f"{len(chunk):x}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()

            # Terminating zero-length chunk
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            conn.close()
            
            # Extract cache telemetry from SSE response
            self._log_cache_telemetry(req_id, response_buffer)
            
            logger.info(f"[MITM-{req_id}] forwarded {total_bytes} bytes response")
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            logger.info(f"[MITM-{req_id}] client disconnected (normal)")
        except Exception as e:
            logger.error(f"[MITM-{req_id}] forward error: {e}")
            try:
                err = f"Proxy forward error: {e}".encode()
                self.send_response(502)
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            except Exception:
                pass  # Connection already broken, can't send error

    def do_POST(self):
        self._forward("POST")

    def do_GET(self):
        self._forward("GET")

    def _log_cache_telemetry(self, req_id: str, response_buffer: bytes) -> None:
        """Extract and log cache telemetry from Anthropic SSE response.
        
        Anthropic includes usage stats in the message_delta event:
        - input_tokens: total input tokens
        - cache_creation_input_tokens: tokens written to cache (cache MISS)
        - cache_read_input_tokens: tokens read from cache (cache HIT)
        """
        try:
            # Check if response is gzip compressed (magic bytes: 1f 8b)
            if response_buffer[:2] == b'\x1f\x8b':
                import gzip
                try:
                    response_buffer = gzip.decompress(response_buffer)
                    logger.debug(f"[MITM-{req_id}] Decompressed gzip response")
                except Exception as e:
                    logger.warning(f"[MITM-{req_id}] Failed to decompress gzip: {e}")
                    return
            
            text = response_buffer.decode("utf-8", errors="replace")
            
            # Find all data: lines - handle both "data: " and "data:" formats
            found_usage = False
            lines_checked = 0
            for line in text.split("\n"):
                line = line.strip()
                # Try both formats: "data: {...}" and "data:{...}"
                json_str = None
                if line.startswith("data: "):
                    json_str = line[6:]
                elif line.startswith("data:"):
                    json_str = line[5:]
                else:
                    continue
                    
                lines_checked += 1
                try:
                    data = json.loads(json_str)
                    usage = data.get("usage", {})
                    if not usage:
                        continue
                    
                    found_usage = True
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cache_creation = usage.get("cache_creation_input_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    
                    # Calculate cache efficiency
                    total_input = input_tokens + cache_read + cache_creation
                    if total_input > 0:
                        cache_hit_pct = (cache_read / total_input * 100) if cache_read else 0
                        cache_miss_pct = (cache_creation / total_input * 100) if cache_creation else 0
                    else:
                        cache_hit_pct = cache_miss_pct = 0
                    
                    if cache_read > 0:
                        logger.info(f"[MITM-{req_id}] CACHE HIT: {cache_read:,} tokens ({cache_hit_pct:.1f}%)")
                    if cache_creation > 0:
                        logger.info(f"[MITM-{req_id}] CACHE WRITE: {cache_creation:,} tokens ({cache_miss_pct:.1f}%)")
                    if not cache_read and not cache_creation and input_tokens:
                        logger.info(f"[MITM-{req_id}] NO CACHE: {input_tokens:,} input tokens")
                    
                    # Store on server for logging
                    self.server.cache_stats = {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_creation": cache_creation,
                        "cache_read": cache_read,
                    }
                    return
                except json.JSONDecodeError:
                    continue
            
            if lines_checked == 0:
                logger.debug(f"[MITM-{req_id}] No SSE data lines found in response")
        except Exception as e:
            logger.warning(f"[MITM-{req_id}] cache telemetry parse error: {e}")


def _format_api_body(api_body: dict) -> str:
    """Pretty-print the full API request body for the log."""
    lines = [
        "=" * 72,
        "FULL API REQUEST CAPTURED VIA LOCAL PROXY",
        f"Captured at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Model: {api_body.get('model', '?')}",
        f"Max tokens: {api_body.get('max_tokens', '?')}",
        f"Stream: {api_body.get('stream', False)}",
        "=" * 72,
        "",
    ]

    # --- System blocks ---
    system_blocks = api_body.get("system", [])
    lines.append(f"{'=' * 72}")
    lines.append(f"SYSTEM BLOCKS ({len(system_blocks)} total)")
    lines.append(f"{'=' * 72}")
    lines.append("")
    for i, block in enumerate(system_blocks):
        if isinstance(block, dict):
            btype = block.get("type", "?")
            text = block.get("text", "")
            cache = block.get("cache_control")
            lines.append(f"--- System Block {i} (type={btype}"
                         f"{', cache=' + str(cache) if cache else ''}) ---")
            lines.append(text)
            lines.append("")
        elif isinstance(block, str):
            lines.append(f"--- System Block {i} (string) ---")
            lines.append(block)
            lines.append("")

    # --- Messages ---
    messages = api_body.get("messages", [])
    lines.append(f"{'=' * 72}")
    lines.append(f"MESSAGES ({len(messages)} total)")
    lines.append(f"{'=' * 72}")
    lines.append("")
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            lines.append(f"--- Message {i} (role={role}) ---")
            lines.append(content)
            lines.append("")
        elif isinstance(content, list):
            lines.append(f"--- Message {i} (role={role}, {len(content)} blocks) ---")
            for j, block in enumerate(content):
                if isinstance(block, dict):
                    btype = block.get("type", "?")
                    text = block.get("text", "")
                    lines.append(f"  Block {j} (type={btype}):")
                    lines.append(text)
                    lines.append("")

    # --- Other fields ---
    skip = {"system", "messages", "model", "max_tokens", "stream"}
    other = {k: v for k, v in api_body.items() if k not in skip}
    if other:
        lines.append(f"{'=' * 72}")
        lines.append("OTHER FIELDS")
        lines.append(f"{'=' * 72}")
        for key in sorted(other):
            val = other[key]
            if isinstance(val, (str, int, float, bool)):
                lines.append(f"  {key}: {val}")
            else:
                lines.append(f"  {key}: {json.dumps(val)[:500]}")
        lines.append("")

    return "\n".join(lines)


async def capture_system_prompt(model: str = "claude-haiku-4-5-20251001") -> Optional[str]:
    """
    Capture the FULL API request body by routing Claude CLI through a local
    HTTP proxy.  Sets ANTHROPIC_BASE_URL so the SDK sends the request to us
    instead of api.anthropic.com; we log it, then forward it to the real API.

    Matches real request conditions: sends --system-prompt (like PROMPT_HEAD)
    AND writes CLAUDE.md (like NPC bio/instructions), so the capture shows
    exactly what the model receives during actual gameplay.
    """
    # Start local proxy on a random port
    proxy = http.server.HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    proxy.captured_body = b""  # per-instance storage
    port = proxy.server_address[1]
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    logger.info(f"Capture proxy listening on 127.0.0.1:{port}")

    # Run claude CLI with our proxy as the API endpoint
    env = _ENV.copy()
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"

    # Use --system-prompt to match real conditions (PROMPT_HEAD goes here)
    test_system_prompt = (
        "[CAPTURE-TEST-SYSTEM-PROMPT]\n"
        "You are roleplaying as a character in The Elder Scrolls V: Skyrim.\n"
        "Stay in character at all times."
    )
    cmd = _build_cmd(model, system_prompt=test_system_prompt)
    req_dir = tempfile.mkdtemp(prefix="claude-capture-")
    try:
        # Write a test CLAUDE.md — verifies whether the CLAUDE.md injection
        # path works alongside --system-prompt (docs claim it doesn't, but
        # empirical evidence shows it does)
        test_bio = (
            "[CAPTURE-TEST-CLAUDE-MD]\n"
            "You are a guard in Whiterun.\n"
            "Respond briefly and in character.\n"
            "This text verifies whether CLAUDE.md is loaded when "
            "--system-prompt is also set."
        )
        (Path(req_dir) / "CLAUDE.md").write_text(test_bio, encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=req_dir,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=b"Hello there."), timeout=60,
        )
        if stderr:
            logger.debug(f"Capture stderr: {stderr.decode(errors='replace')[:500]}")
    except Exception as e:
        logger.warning(f"Capture CLI call failed: {e}")
    finally:
        shutil.rmtree(req_dir, ignore_errors=True)
        proxy.shutdown()
        proxy_thread.join(timeout=5)

    # Parse what we captured
    if not proxy.captured_body:
        msg = "No API request was captured — the proxy may not have been reached."
        logger.warning(msg)
        SYSTEM_PROMPT_LOG.write_text(msg, encoding="utf-8")
        return msg

    try:
        api_body = json.loads(proxy.captured_body)
    except json.JSONDecodeError:
        raw = proxy.captured_body.decode(errors="replace")
        result = f"RAW CAPTURED BODY (not valid JSON):\n\n{raw}"
        SYSTEM_PROMPT_LOG.write_text(result, encoding="utf-8")
        logger.warning("Captured body was not valid JSON")
        return result

    result = _format_api_body(api_body)

    # Append overhead analysis — helps determine what Claude Code adds
    result += _analyze_overhead(api_body, test_system_prompt, test_bio)

    SYSTEM_PROMPT_LOG.write_text(result, encoding="utf-8")
    n_sys = len(api_body.get("system", []))
    n_msg = len(api_body.get("messages", []))
    logger.info(f"Full API body captured ({n_sys} system blocks, {n_msg} messages) "
                f"-> {SYSTEM_PROMPT_LOG}")
    return result


def _analyze_overhead(api_body: dict, our_system_prompt: str, our_claude_md: str) -> str:
    """Analyze how much overhead Claude Code adds beyond our content."""
    lines = [
        "",
        "=" * 72,
        "OVERHEAD ANALYSIS",
        "=" * 72,
        "",
    ]

    # Measure system blocks
    system_blocks = api_body.get("system", [])
    total_system_chars = 0
    our_system_chars = 0
    for block in system_blocks:
        text = block.get("text", "") if isinstance(block, dict) else str(block)
        total_system_chars += len(text)
        if "[CAPTURE-TEST-SYSTEM-PROMPT]" in text:
            our_system_chars += len(our_system_prompt)

    overhead_system_chars = total_system_chars - our_system_chars
    lines.append(f"System blocks: {len(system_blocks)} total, {total_system_chars} chars")
    lines.append(f"  Our --system-prompt content: {our_system_chars} chars")
    lines.append(f"  Claude Code overhead: {overhead_system_chars} chars")
    lines.append("")

    # Check if CLAUDE.md was loaded in user messages
    messages = api_body.get("messages", [])
    claude_md_found = False
    claude_md_wrapper_chars = 0
    total_user_msg_chars = 0
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            total_user_msg_chars += len(content)
            if "[CAPTURE-TEST-CLAUDE-MD]" in content:
                claude_md_found = True
                claude_md_wrapper_chars = len(content) - len(our_claude_md)
        elif isinstance(content, list):
            for block in content:
                text = block.get("text", "") if isinstance(block, dict) else ""
                total_user_msg_chars += len(text)
                if "[CAPTURE-TEST-CLAUDE-MD]" in text:
                    claude_md_found = True
                    claude_md_wrapper_chars = len(text) - len(our_claude_md)

    lines.append(f"CLAUDE.md loaded despite --system-prompt: {'YES' if claude_md_found else 'NO'}")
    if claude_md_found:
        lines.append(f"  CLAUDE.md wrapper/framing overhead: {claude_md_wrapper_chars} chars")
    lines.append(f"  Total user message chars: {total_user_msg_chars}")
    lines.append("")

    # Summary
    total_overhead = overhead_system_chars + (claude_md_wrapper_chars if claude_md_found else 0)
    lines.append(f"TOTAL OVERHEAD (chars Claude Code adds beyond our content): {total_overhead}")
    lines.append(f"  Estimated tokens (chars / 4): ~{total_overhead // 4}")
    lines.append("")

    return "\n".join(lines)


def _log_request(request_id: str, model: str, elapsed: float,
                  api_body: Optional[dict], response_text: str):
    """Append a full request/response record to logs/requests.log.

    api_body is the REWRITTEN API request body — after the MITM proxy strips
    Claude Code's default system blocks and injects our PROMPT_HEAD + character
    content.  This reflects exactly what the model receives.
    """
    sep = "=" * 72
    entry = (
        f"\n{sep}\n"
        f"REQUEST {request_id}  |  {time.strftime('%Y-%m-%d %H:%M:%S')}  |  "
        f"{model}  |  {elapsed:.1f}s\n"
        f"{sep}\n"
    )

    if api_body:
        # --- API parameters ---
        entry += (
            f"\nModel: {api_body.get('model', '?')}  |  "
            f"Max tokens: {api_body.get('max_tokens', '?')}  |  "
            f"Stream: {api_body.get('stream', False)}\n"
        )

        # --- System blocks (the ACTUAL system prompt the model sees) ---
        system_blocks = api_body.get("system", [])
        entry += f"\n--- SYSTEM PROMPT ({len(system_blocks)} blocks) ---\n"
        for i, block in enumerate(system_blocks):
            if isinstance(block, dict):
                btype = block.get("type", "?")
                text = block.get("text", "")
                cache = block.get("cache_control")
                entry += (f"\n[Block {i} type={btype}"
                          f"{', cache=' + str(cache) if cache else ''}]\n"
                          f"{text}\n")
            elif isinstance(block, str):
                entry += f"\n[Block {i}]\n{block}\n"

        # --- Messages (the ACTUAL conversation the model sees) ---
        messages = api_body.get("messages", [])
        entry += f"\n--- MESSAGES ({len(messages)} total) ---\n"
        for i, msg in enumerate(messages):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, str):
                entry += f"\n[{role}]\n{content}\n"
            elif isinstance(content, list):
                entry += f"\n[{role}] ({len(content)} content blocks)\n"
                for j, block in enumerate(content):
                    if isinstance(block, dict):
                        btype = block.get("type", "?")
                        text = block.get("text", "")
                        cache = block.get("cache_control")
                        cache_str = " CACHED" if cache else ""
                        
                        # Show a clean preview of the text content
                        # Skip JSON structure prefix if present, show actual dialogue
                        preview_text = text
                        if preview_text.startswith('[') or preview_text.startswith('{'):
                            # Try to extract first actual text from JSON if it looks like nested structure
                            try:
                                import re
                                # Find first "text": "..." value
                                match = re.search(r'"text":\s*"([^"]{0,150})', preview_text)
                                if match:
                                    preview_text = match.group(1) + "..."
                            except:
                                pass
                        
                        preview = preview_text[:150].replace('\n', ' ').replace('\r', '') + ("..." if len(text) > 150 else "")
                        entry += f"  [Block {j}{cache_str}] {len(text):,} chars: {preview}\n"
                    else:
                        entry += f"  [Block {j}] {block}\n"
    else:
        entry += "\n(MITM capture failed — API body not available)\n"

    entry += (
        f"\n--- RESPONSE ---\n"
        f"{response_text}\n"
        f"\n{sep}\n"
    )
    try:
        with open(REQUEST_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning(f"[{request_id}] Failed to write request log: {e}")


def _build_cmd(model: str, effort: str = "", system_prompt: str = "",
               streaming: bool = False) -> list[str]:
    """Build claude CLI command with all context-minimization flags.

    system_prompt: PROMPT_HEAD extracted from CHIM's <roleplay_instructions> block.
                   Passed via --system-prompt (controls the API system block).
    streaming:     If True, use stream-json output with partial messages for
                   real-time token delivery.
    """
    if streaming:
        output_flags = ["--output-format", "stream-json", "--include-partial-messages"]
    else:
        output_flags = ["--output-format", "json"]

    cmd = [
        CLAUDE_PATH, "-p",
        "--tools=",                          # No tools → no tool descriptions in context
        "--disable-slash-commands",          # No skill descriptions in context
        "--model", model,
        *output_flags,
        "--max-turns", "1",                  # Single response, no tool loops
        "--no-session-persistence",          # Don't save session to disk
    ]
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if effort in _VALID_EFFORTS:
        cmd.extend(["--effort", effort])
    return cmd


async def call_claude(prompt_head: str, claude_md_content: Optional[str],
                      conversation: list[dict],
                      model: str, effort: str = "", thinking_tokens: int = 0,
                      npc_name: Optional[str] = None,
                      request_id: Optional[str] = None) -> str:
    """
    Spawn claude -p in a per-request temp dir.

    Each request is routed through a per-request MITM proxy that intercepts the
    actual API call from Claude Code → Anthropic.  The proxy rewrites the system
    blocks — stripping Claude Code's default agent/coding-assistant prompts and
    injecting our PROMPT_HEAD + character content with ephemeral caching.

    Architecture:
      - prompt_head + claude_md_content → MITM proxy rewrites system blocks
        (replaces Claude Code's blocks 1+ with our content, keeps billing block 0)
      - conversation → piped to stdin
      - MITM proxy captures the rewritten API body and logs it to requests.log
      - Dialogue caching: if npc_name is provided, dialogue cache is loaded
        from temp files and cache_control markers are added to messages
    """
    prompt = _format_prompt(conversation)
    cmd = _build_cmd(model, effort)

    request_id = request_id or uuid.uuid4().hex[:8]
    head_len = len(prompt_head)
    md_len = len(claude_md_content) if claude_md_content else 0
    extras = []
    if effort:
        extras.append(f"effort={effort}")
    if thinking_tokens:
        extras.append(f"thinking_tokens={thinking_tokens}")
    if npc_name:
        extras.append(f"npc={npc_name}")
    extras_str = f", {', '.join(extras)}" if extras else ""
    logger.info(f"[{request_id}] -> {model} ({len(conversation)} msgs, "
                f"{head_len} chars prompt_head, {md_len} chars claude.md, "
                f"{len(prompt)} chars dialogue{extras_str})")
    start = time.time()

    # Per-request MITM proxy: intercepts Claude Code → Anthropic API call
    # and rewrites system blocks to strip Claude Code overhead
    mitm = http.server.HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    mitm.captured_body = b""
    mitm.cache_stats = {}  # For cache telemetry
    # System block replacement: MITM strips Claude Code's agent/coding prompts
    # and injects our content with ephemeral caching
    replacement = []
    if prompt_head:
        replacement.append(prompt_head)
    if claude_md_content:
        replacement.append(claude_md_content)
    mitm.system_replacement = replacement if replacement else None
    mitm.npc_name = npc_name  # For dialogue caching
    if npc_name:
        logger.info(f"[{request_id}] NPC name for dialogue caching: {npc_name}")
    mitm._mitm_id = request_id  # Used for diagnostic logging in _CaptureHandler
    mitm_port = mitm.server_address[1]
    mitm_thread = threading.Thread(target=mitm.serve_forever, daemon=True)
    mitm_thread.start()
    logger.info(f"[{request_id}] MITM proxy on 127.0.0.1:{mitm_port}")

    # Per-request isolation: temp dir as cwd (no CLAUDE.md — content goes
    # directly into system blocks via MITM rewrite, avoiding the
    # <system-reminder> wrapper overhead Claude Code adds for CLAUDE.md)
    req_dir = tempfile.mkdtemp(prefix=f"claude-req-{request_id}-")
    try:
        # Per-request env: MITM proxy + optional thinking tokens
        env = _ENV.copy()
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{mitm_port}"
        if thinking_tokens >= 1024:
            env["MAX_THINKING_TOKENS"] = str(thinking_tokens)

        async with _semaphore:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=req_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=300,
            )
    finally:
        shutil.rmtree(req_dir, ignore_errors=True)
        mitm.shutdown()
        mitm_thread.join(timeout=5)

    elapsed = time.time() - start
    raw = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()

    if err:
        logger.debug(f"[{request_id}] stderr: {err[:500]}")

    if proc.returncode != 0:
        logger.error(f"[{request_id}] exit {proc.returncode}: {err[:500]}")
        raise HTTPException(status_code=502, detail=f"Claude CLI error: {err[:200]}")

    # Parse captured API body (the REAL request to Anthropic)
    captured_api_body = None
    if mitm.captured_body:
        try:
            captured_api_body = json.loads(mitm.captured_body)
        except json.JSONDecodeError:
            logger.warning(f"[{request_id}] MITM captured non-JSON body "
                           f"({len(mitm.captured_body)} bytes)")

    # Parse response — try single JSON first, then scan for result line
    text = ""
    try:
        data = json.loads(raw)
        text = data.get("result", "")
    except json.JSONDecodeError:
        # Might be multi-line stream-json or plain text
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "result":
                    text = event.get("result", "")
                    break
            except json.JSONDecodeError:
                continue
        if not text:
            text = raw  # Fallback: treat raw output as text

    if not text:
        logger.warning(f"[{request_id}] empty response. raw stdout ({len(raw)} bytes): {raw[:1000]}")

    logger.info(f"[{request_id}] <- {len(text)} chars ({elapsed:.1f}s)")

    # --- Log the FULL API request body (every token sent to the model) ---
    _log_request(request_id, model, elapsed, captured_api_body, text)

    # --- Record to request history for dashboard ---
    input_chars = len(claude_md_content or "") + sum(len(json.dumps(m)) for m in conversation)
    _record_request_history(
        request_id=request_id,
        npc_name=npc_name,
        model=model,
        input_chars=input_chars,
        output_chars=len(text),
        elapsed=elapsed,
        cache_stats=getattr(mitm, 'cache_stats', None)
    )

    return text


async def _call_claude_fake_streaming(prompt_head: str, claude_md_content: Optional[str],
                                      conversation: list[dict],
                                      model: str, effort: str = "", thinking_tokens: int = 0,
                                      npc_name: Optional[str] = None):
    """Fake streaming: get full response via call_claude, then chunk it as SSE."""
    request_id = uuid.uuid4().hex[:8]
    cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())

    extras = []
    if effort:
        extras.append(f"effort={effort}")
    if thinking_tokens:
        extras.append(f"thinking_tokens={thinking_tokens}")
    if npc_name:
        extras.append(f"npc={npc_name}")
    logger.info(f"[{request_id}] -> {model} ({len(conversation)} msgs, fake-stream"
                f"{', ' + ', '.join(extras) if extras else ''})")
    start = time.time()

    # Get complete response (reliable across platforms)
    response = await call_claude(prompt_head, claude_md_content, conversation, model, effort, thinking_tokens, npc_name, request_id=request_id)

    # Role chunk
    role_chunk = {
        "id": cmpl_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(role_chunk)}\n\n"

    # Content — emit in small chunks so the client sees incremental delivery
    CHUNK_SIZE = 80
    for i in range(0, max(len(response), 1), CHUNK_SIZE):
        chunk_text = response[i:i + CHUNK_SIZE]
        if chunk_text:
            chunk = {
                "id": cmpl_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

    # Stop chunk
    stop_chunk = {
        "id": cmpl_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(stop_chunk)}\n\n"
    yield "data: [DONE]\n\n"

    elapsed = time.time() - start
    logger.info(f"[{request_id}] fake-stream complete ({elapsed:.1f}s, {len(response)} chars)")


async def _call_claude_real_streaming(prompt_head: str, claude_md_content: Optional[str],
                                      conversation: list[dict],
                                      model: str, effort: str = "", thinking_tokens: int = 0,
                                      npc_name: Optional[str] = None):
    """Real streaming: spawn claude with --output-format stream-json and yield
    OpenAI SSE chunks as tokens arrive from the CLI's stdout.

    Stream-json format (one JSON object per line):
      type="stream_event", event.type="content_block_delta",
        event.delta.type="text_delta", event.delta.text="..." → text tokens
      type="result", result="..." → final complete text (used for logging)
    """
    request_id = uuid.uuid4().hex[:8]
    cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())
    prompt = _format_prompt(conversation)
    cmd = _build_cmd(model, effort, streaming=True)

    extras = []
    if effort:
        extras.append(f"effort={effort}")
    if thinking_tokens:
        extras.append(f"thinking_tokens={thinking_tokens}")
    if npc_name:
        extras.append(f"npc={npc_name}")
    logger.info(f"[{request_id}] -> {model} ({len(conversation)} msgs, real-stream"
                f"{', ' + ', '.join(extras) if extras else ''})")
    start = time.time()

    # Per-request MITM proxy (same as call_claude)
    mitm = http.server.HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    mitm.captured_body = b""
    mitm.cache_stats = {}
    replacement = []
    if prompt_head:
        replacement.append(prompt_head)
    if claude_md_content:
        replacement.append(claude_md_content)
    mitm.system_replacement = replacement if replacement else None
    mitm.npc_name = npc_name
    mitm._mitm_id = request_id
    mitm_port = mitm.server_address[1]
    mitm_thread = threading.Thread(target=mitm.serve_forever, daemon=True)
    mitm_thread.start()

    req_dir = tempfile.mkdtemp(prefix=f"claude-req-{request_id}-")
    full_response = ""
    try:
        env = _ENV.copy()
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{mitm_port}"
        if thinking_tokens >= 1024:
            env["MAX_THINKING_TOKENS"] = str(thinking_tokens)

        async with _semaphore:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=req_dir,
            )
            # Send prompt to stdin, then close to signal EOF
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

            # Emit role chunk immediately
            role_chunk = {
                "id": cmpl_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(role_chunk)}\n\n"

            # Read stdout line-by-line, parse stream-json events
            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=300)
                except asyncio.TimeoutError:
                    logger.warning(f"[{request_id}] stream timeout")
                    break
                if not line:
                    break  # EOF
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                # Real-time text deltas from stream_event
                if event_type == "stream_event":
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                chunk = {
                                    "id": cmpl_id, "object": "chat.completion.chunk",
                                    "created": created, "model": model,
                                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                                }
                                yield f"data: {json.dumps(chunk)}\n\n"
                                full_response += text

                # Also handle assistant messages (complete text, fallback)
                elif event_type == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            # Only use if we haven't been getting deltas
                            if not full_response:
                                full_response = block.get("text", "")

                # Final result
                elif event_type == "result":
                    result_text = event.get("result", "")
                    if result_text and not full_response:
                        full_response = result_text

            # Wait for process to finish
            await proc.wait()

        # Stop chunk
        stop_chunk = {
            "id": cmpl_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(stop_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    finally:
        shutil.rmtree(req_dir, ignore_errors=True)
        mitm.shutdown()
        mitm_thread.join(timeout=5)

    elapsed = time.time() - start
    logger.info(f"[{request_id}] <- {len(full_response)} chars ({elapsed:.1f}s, real-stream)")

    # Log request (captured API body from MITM)
    captured_api_body = None
    if mitm.captured_body:
        try:
            captured_api_body = json.loads(mitm.captured_body)
        except json.JSONDecodeError:
            pass
    _log_request(request_id, model, elapsed, captured_api_body, full_response)

    # Record to request history
    input_chars = len(claude_md_content or "") + sum(len(json.dumps(m)) for m in conversation)
    _record_request_history(
        request_id=request_id,
        npc_name=npc_name,
        model=model,
        input_chars=input_chars,
        output_chars=len(full_response),
        elapsed=elapsed,
        cache_stats=getattr(mitm, 'cache_stats', None)
    )


async def call_claude_streaming(prompt_head: str, claude_md_content: Optional[str],
                                conversation: list[dict],
                                model: str, effort: str = "", thinking_tokens: int = 0,
                                npc_name: Optional[str] = None):
    """Dispatch to real or fake streaming based on STREAMING_MODE setting."""
    if STREAMING_MODE == "real":
        gen = _call_claude_real_streaming(
            prompt_head, claude_md_content, conversation,
            model, effort, thinking_tokens, npc_name)
    else:
        gen = _call_claude_fake_streaming(
            prompt_head, claude_md_content, conversation,
            model, effort, thinking_tokens, npc_name)
    async for chunk in gen:
        yield chunk


# ---------------------------------------------------------------------------
# OpenAI-compatible API
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: Union[str, list]
    model_config = {"extra": "allow"}


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    max_tokens: Optional[int] = 4096
    max_completion_tokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: Optional[bool] = False
    npc_name: Optional[str] = None  # Override auto-detected NPC name
    reasoning: Optional[dict] = None  # HerikaServer-style: {enabled, max_tokens, effort, exclude}
    model_config = {"extra": "allow"}


@asynccontextmanager
async def lifespan(app):
    logger.info("Proxy ready — use /debug/system-prompt?refresh=true to capture system prompt on demand")
    yield


app = FastAPI(title="Claude SkyrimNet Proxy", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost|172\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_effort(reasoning: Optional[dict]) -> str:
    """Resolve reasoning effort from per-request reasoning param or global defaults.

    HerikaServer sends:  {enabled: bool, max_tokens: int, effort: str, exclude: bool}
      - effort: level string ("low"/"medium"/"high")
    Returns "" if effort should not be set.
    """
    if reasoning and reasoning.get("enabled"):
        effort = reasoning.get("effort", "")
        if effort in _VALID_EFFORTS:
            return effort
        # No explicit effort — use global default if thinking is enabled
        if THINKING_ENABLED:
            return THINKING_EFFORT
        return ""
    if THINKING_ENABLED:
        return THINKING_EFFORT
    return ""


def _resolve_thinking_tokens(reasoning: Optional[dict]) -> int:
    """Extract thinking token budget from per-request reasoning param.

    HerikaServer sends max_tokens via its thinking_tokens connector setting.
    Returns the value floored at 1024 (Anthropic minimum), or 0 if not set.
    """
    if reasoning and reasoning.get("enabled") and "max_tokens" in reasoning:
        return max(int(reasoning["max_tokens"]), 1024)
    return 0


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    model = _normalize_model(req.model) if req.model else DEFAULT_MODEL
    prompt_head, claude_md, conversation, npc_name = _extract_messages(req.messages, req.npc_name)

    if not conversation:
        raise HTTPException(status_code=400, detail="No user/assistant messages provided")

    # Ensure conversation starts with user
    if conversation[0]["role"] != "user":
        if CONTENT_FORMAT == "array":
            conversation.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continue."}]})
        else:
            conversation.insert(0, {"role": "user", "content": "Continue."})

    # Merge consecutive same-role messages (flat mode only — array mode preserves boundaries)
    if CONTENT_FORMAT == "array":
        merged = conversation
    else:
        merged = []
        for msg in conversation:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["content"] += "\n\n" + msg["content"]
            else:
                merged.append(msg)

    effort = _resolve_effort(req.reasoning)
    thinking_tokens = _resolve_thinking_tokens(req.reasoning)

    if req.stream:
        return StreamingResponse(
            call_claude_streaming(prompt_head, claude_md, merged, model, effort, thinking_tokens, npc_name),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response = await call_claude(prompt_head, claude_md, merged, model, effort, thinking_tokens, npc_name)
    if not response:
        raise HTTPException(status_code=500, detail="Empty response from Claude")

    # Rough token estimates (chars / 4)
    if CONTENT_FORMAT == "array":
        prompt_text = (prompt_head or "") + (claude_md or "") + " ".join(
            " ".join(b["text"] for b in m["content"]) for m in merged
        )
    else:
        prompt_text = (prompt_head or "") + (claude_md or "") + " ".join(m["content"] for m in merged)
    prompt_tokens = len(prompt_text) // 4
    completion_tokens = len(response) // 4

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "claude-opus-4-5-20251101", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-opus-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-sonnet-4-5-20250929", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-haiku-4-5-20251001", "object": "model", "owned_by": "anthropic"},
        ],
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "mode": "subprocess (legitimate)",
        "content_format": CONTENT_FORMAT,
        "thinking_enabled": THINKING_ENABLED,
        "thinking_effort": THINKING_EFFORT if THINKING_ENABLED else "off",
        "streaming_mode": STREAMING_MODE,
        "claude_path": CLAUDE_PATH,
        "work_dir": "per-request temp dirs",
        "max_concurrent": MAX_CONCURRENT,
        "system_prompt_log": str(SYSTEM_PROMPT_LOG),
    }


@app.get("/debug/system-prompt")
async def debug_system_prompt(refresh: bool = False):
    """
    Return the real API request body that Claude Code sends, captured by
    routing the CLI through a local HTTP proxy.

    Matches real request conditions: uses --system-prompt (like PROMPT_HEAD)
    AND CLAUDE.md (like NPC bio), so you see exactly what the model gets.

    Includes an OVERHEAD ANALYSIS section showing how many chars/tokens
    Claude Code adds beyond our content.

    Captured on startup; pass ?refresh=true to re-capture.
    """
    if refresh or not SYSTEM_PROMPT_LOG.exists():
        result = await capture_system_prompt()
        if not result:
            raise HTTPException(status_code=500, detail="Failed to capture system prompt — check logs")
        return HTMLResponse(f"<pre>{result}</pre>")

    content = SYSTEM_PROMPT_LOG.read_text(encoding="utf-8", errors="replace")
    return HTMLResponse(f"<pre>{content}</pre>")


@app.get("/debug/requests")
async def debug_requests(last: int = 5):
    """
    Show the last N request/response logs.
    Pass ?last=10 to see more.  Full log lives at logs/requests.log.
    """
    if not REQUEST_LOG.exists():
        return HTMLResponse("<pre>No requests logged yet.</pre>")

    content = REQUEST_LOG.read_text(encoding="utf-8", errors="replace")

    # Split into individual entries and return the last N
    sep = "=" * 72
    entries = content.split(f"\n{sep}\nREQUEST ")
    entries = [e for e in entries if e.strip()]
    tail = entries[-last:] if len(entries) > last else entries
    tail_text = "\n".join(f"{sep}\nREQUEST {e}" for e in tail)

    import html as html_mod
    return HTMLResponse(f"<pre>{html_mod.escape(tail_text)}</pre>")


# ---------------------------------------------------------------------------
# NPC Cache Management API
# ---------------------------------------------------------------------------

@app.get("/api/npcs")
async def api_list_npcs():
    """List all NPCs with dialogue cache files and their cache state."""
    npcs = _list_cached_npcs()
    return {
        "npcs": npcs,
        "config": {
            "dialogue_cache_path": DIALOGUE_CACHE_PATH,
            "uncached_count": DIALOGUE_CACHE_UNCACHED_COUNT,
            "cache_state_expiry_seconds": CACHE_STATE_EXPIRY_SECONDS,
        }
    }


@app.post("/api/npcs/{npc_name}/reroll")
async def api_reroll_npc(npc_name: str):
    """Increment the reroll counter for an NPC, invalidating their cache."""
    new_count = _increment_npc_reroll(npc_name)
    logger.info(f"Reroll triggered for {npc_name}: count now {new_count}")
    return {
        "npc_name": npc_name,
        "reroll_count": new_count,
        "message": f"Cache will be invalidated on next request (reroll count: {new_count})"
    }


@app.post("/api/npcs/{npc_name}/clear-reroll")
async def api_clear_reroll(npc_name: str):
    """Clear the reroll counter for an NPC."""
    _clear_npc_reroll(npc_name)
    logger.info(f"Reroll counter cleared for {npc_name}")
    return {
        "npc_name": npc_name,
        "reroll_count": 0,
        "message": "Reroll counter cleared"
    }


@app.post("/api/config/uncached-count")
async def api_set_uncached_count(count: int):
    """Update the dialogue cache uncached count (runtime only, not persisted)."""
    global DIALOGUE_CACHE_UNCACHED_COUNT
    if count < 0 or count > 50:
        raise HTTPException(status_code=400, detail="Uncached count must be between 0 and 50")
    old_count = DIALOGUE_CACHE_UNCACHED_COUNT
    DIALOGUE_CACHE_UNCACHED_COUNT = count
    logger.info(f"Dialogue cache uncached count changed: {old_count} -> {count}")
    return {
        "old_count": old_count,
        "new_count": count,
        "message": "Uncached count updated (runtime only)"
    }


@app.get("/api/history")
async def api_get_history():
    """Get recent request history with cache stats."""
    with _history_lock:
        entries = [asdict(e) for e in reversed(_request_history)]  # Most recent first
    
    # Calculate aggregate stats
    total_requests = len(entries)
    total_cache_read = sum(e["cache_read_tokens"] for e in entries)
    total_cache_write = sum(e["cache_write_tokens"] for e in entries)
    total_input = sum(e["input_tokens"] for e in entries)
    
    total_all = total_input + total_cache_read + total_cache_write
    overall_hit_pct = (total_cache_read / total_all * 100) if total_all > 0 else 0
    
    return {
        "requests": entries,
        "stats": {
            "total_requests": total_requests,
            "total_cache_read_tokens": total_cache_read,
            "total_cache_write_tokens": total_cache_write,
            "total_input_tokens": total_input,
            "overall_cache_hit_pct": round(overall_hit_pct, 1)
        }
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    models = [
        ("claude-opus-4-5-20251101", "Opus 4.5", "Most capable (default)"),
        ("claude-opus-4-6", "Opus 4.6", "Latest Opus"),
        ("claude-sonnet-4-6", "Sonnet 4.6", "Best balance"),
        ("claude-sonnet-4-5-20250929", "Sonnet 4.5", "Previous gen"),
        ("claude-haiku-4-5-20251001", "Haiku 4.5", "Fastest"),
    ]
    model_rows = "".join(
        f'<tr><td style="font-family:monospace;color:#93c5fd">{mid}</td>'
        f'<td>{name}</td><td style="color:#9ca3af">{desc}</td></tr>'
        for mid, name, desc in models
    )
    return f"""<!DOCTYPE html>
<html><head><title>Claude SkyrimNet Proxy</title>
<style>
  body {{ background:#0f172a; color:#e2e8f0; font-family:system-ui,sans-serif;
         max-width:700px; margin:40px auto; padding:0 20px }}
  h1 {{ color:#f8fafc; font-size:1.5rem; margin-bottom:4px }}
  .sub {{ color:#64748b; font-size:0.9rem; margin-bottom:30px }}
  .badge {{ display:inline-block; padding:4px 12px; border-radius:12px; font-size:0.85rem;
            font-weight:600; background:#4ade8020; color:#4ade80; border:1px solid #4ade8040 }}
  .card {{ background:#1e293b; border-radius:8px; padding:20px; margin:16px 0;
           border:1px solid #334155 }}
  table {{ width:100%; border-collapse:collapse }}
  th {{ text-align:left; color:#94a3b8; font-size:0.75rem; text-transform:uppercase;
       letter-spacing:0.05em; padding:8px 12px; border-bottom:1px solid #334155 }}
  td {{ padding:8px 12px; border-bottom:1px solid #1e293b }}
  .label {{ color:#94a3b8; font-size:0.85rem }}
  .value {{ color:#f1f5f9; font-family:monospace; font-size:0.85rem }}
  .endpoint {{ background:#0f172a; padding:10px 14px; border-radius:6px;
               font-family:monospace; font-size:0.85rem; color:#67e8f9;
               margin:8px 0; border:1px solid #334155 }}
  textarea {{ width:100%; background:#0f172a; color:#e2e8f0; border:1px solid #334155;
              border-radius:6px; padding:10px; font-family:monospace; font-size:0.85rem;
              resize:vertical; box-sizing:border-box }}
  button {{ background:#3b82f6; color:white; border:none; padding:8px 20px;
            border-radius:6px; cursor:pointer; font-size:0.85rem; margin-top:8px }}
  button:hover {{ background:#2563eb }}
  button:disabled {{ background:#475569; cursor:wait }}
  #response {{ margin-top:12px; padding:12px; background:#0f172a; border-radius:6px;
               border:1px solid #334155; font-size:0.9rem; min-height:40px; white-space:pre-wrap }}
  .timing {{ color:#4ade80; font-size:0.8rem; margin-top:6px }}
</style></head>
<body>
  <h1>Claude SkyrimNet Proxy</h1>
  <div class="sub">OpenAI-compatible proxy &mdash; legitimate subprocess mode</div>
  <span class="badge">Ready</span>

  <div class="card">
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px">
      <div><span class="label">Endpoint</span>
        <div class="endpoint">http://127.0.0.1:38700/v1/chat/completions</div></div>
      <div><span class="label">API Key</span>
        <div class="endpoint">not required</div></div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px">
      <div><span class="label">Mode</span><br>
        <span class="value">subprocess (claude -p)</span></div>
      <div><span class="label">Max Concurrent</span><br>
        <span class="value">{MAX_CONCURRENT}</span></div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px">
      <div><span class="label">Content Format</span><br>
        <span class="value" style="color:#67e8f9">{CONTENT_FORMAT}</span></div>
      <div><span class="label">NPC Name</span><br>
        <span class="value" style="color:#67e8f9">auto-detect (or npc_name field)</span></div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px">
      <div><span class="label">Reasoning Effort</span><br>
        <span class="value" style="color:{'#4ade80' if THINKING_ENABLED else '#f87171'}">{'enabled' if THINKING_ENABLED else 'disabled'}</span></div>
      <div><span class="label">Effort Level</span><br>
        <span class="value" style="color:#67e8f9">{THINKING_EFFORT if THINKING_ENABLED else 'n/a'}</span></div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px">
      <div><span class="label">Streaming Mode</span><br>
        <span class="value" style="color:{'#4ade80' if STREAMING_MODE == 'real' else '#67e8f9'}">{STREAMING_MODE}</span></div>
      <div><span class="label">Stream Detail</span><br>
        <span class="value" style="color:#9ca3af">{'token-by-token via stream-json' if STREAMING_MODE == 'real' else 'collect then chunk (80 chars)'}</span></div>
    </div>
  </div>

  <div class="card">
    <h3 style="margin:0 0 8px; font-size:0.85rem; color:#94a3b8; text-transform:uppercase;
               letter-spacing:0.05em">Context Minimization</h3>
    <table>
      <tr><td class="label">--tools=</td>
        <td class="value" style="color:#4ade80">all tool descriptions removed</td></tr>
      <tr><td class="label">--disable-slash-commands</td>
        <td class="value" style="color:#4ade80">skill descriptions removed</td></tr>
      <tr><td class="label">--max-turns 1</td>
        <td class="value" style="color:#4ade80">single response, no tool loops</td></tr>
      <tr><td class="label">MITM system rewrite</td>
        <td class="value" style="color:#4ade80">strips Claude Code blocks, injects PROMPT_HEAD + bio (cached)</td></tr>
      <tr><td class="label">dialogue caching</td>
        <td class="value" style="color:#4ade80">reads temp files, caches history minus last {DIALOGUE_CACHE_UNCACHED_COUNT} msgs</td></tr>
      <tr><td class="label">--effort</td>
        <td class="value" style="color:{'#4ade80' if THINKING_ENABLED else '#9ca3af'}">{THINKING_EFFORT if THINKING_ENABLED else 'disabled (per-request override still works)'}</td></tr>
      <tr><td class="label">irreducible overhead</td>
        <td class="value" style="color:#facc15">~25 tokens (billing header only)</td></tr>
    </table>
  </div>

  <div class="card">
    <h3 style="margin:0 0 12px; font-size:1rem; color:#f1f5f9">Models</h3>
    <table><thead><tr><th>Model ID</th><th>Name</th><th>Notes</th></tr></thead>
    <tbody>{model_rows}</tbody></table>
  </div>

  <div class="card">
    <h3 style="margin:0 0 8px; font-size:1rem; color:#f1f5f9">Quick Test</h3>
    <textarea id="sys" rows="2"
      placeholder="System prompt...">You are Lydia, a Nord housecarl sworn to protect the Dragonborn. Stay in character. One sentence only.</textarea>
    <textarea id="usr" rows="1" placeholder="User message" style="margin-top:6px"
      >What do you think of dragons?</textarea>
    <button onclick="testChat()" id="btn">Send</button>
    <div id="response" style="display:none"></div>
    <div id="timing" class="timing"></div>
  </div>

  <div class="card">
    <h3 style="margin:0 0 8px; font-size:0.85rem; color:#94a3b8; text-transform:uppercase;
               letter-spacing:0.05em">Dialogue Caching</h3>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px">
      <div><span class="label">Uncached Messages</span><br>
        <span class="value" style="color:#67e8f9">{DIALOGUE_CACHE_UNCACHED_COUNT}</span></div>
      <div><span class="label">Cache Path</span><br>
        <span class="value" style="color:#9ca3af; font-size:0.7rem; word-break:break-all">{DIALOGUE_CACHE_PATH[:50]}...</span></div>
    </div>
    <h4 style="margin:12px 0 8px; font-size:0.9rem; color:#f1f5f9">Cached NPCs</h4>
    <div id="npc-list" style="font-size:0.85rem">Loading...</div>
    <button onclick="loadNpcs()" style="margin-top:8px; background:#475569">Refresh</button>
  </div>

  <div class="card">
    <h3 style="margin:0 0 8px; font-size:0.85rem; color:#94a3b8; text-transform:uppercase;
               letter-spacing:0.05em">Request History</h3>
    <div id="history-stats" style="display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; margin-bottom:12px">
      <div style="text-align:center">
        <div style="font-size:1.2rem; color:#4ade80" id="stat-hit-pct">--%</div>
        <div class="label" style="font-size:0.7rem">Cache Hit</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.2rem; color:#67e8f9" id="stat-requests">0</div>
        <div class="label" style="font-size:0.7rem">Requests</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.2rem; color:#a78bfa" id="stat-cache-read">0</div>
        <div class="label" style="font-size:0.7rem">Cache Read</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.2rem; color:#facc15" id="stat-cache-write">0</div>
        <div class="label" style="font-size:0.7rem">Cache Write</div>
      </div>
    </div>
    <div style="max-height:250px; overflow-y:auto">
      <table style="font-size:0.75rem">
        <thead><tr>
          <th style="padding:4px 6px">Time</th>
          <th style="padding:4px 6px">NPC</th>
          <th style="padding:4px 6px">Cache</th>
          <th style="padding:4px 6px">Time</th>
        </tr></thead>
        <tbody id="history-body"></tbody>
      </table>
    </div>
    <button onclick="loadHistory()" style="margin-top:8px; background:#475569">Refresh</button>
  </div>

<script>
function esc(s) {{
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}}
async function testChat() {{
  const btn = document.getElementById('btn');
  const resp = document.getElementById('response');
  const timing = document.getElementById('timing');
  btn.disabled = true; btn.textContent = 'Waiting...';
  resp.style.display = 'block'; resp.textContent = '...';
  timing.textContent = '';
  const start = Date.now();
  try {{
    const r = await fetch('/v1/chat/completions', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        model: '{DEFAULT_MODEL}',
        messages: [
          {{role: 'system', content: document.getElementById('sys').value}},
          {{role: 'user', content: document.getElementById('usr').value}}
        ]
      }})
    }});
    const data = await r.json();
    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    if (data.choices) {{
      resp.textContent = data.choices[0].message.content;
      timing.textContent = elapsed + 's';
    }} else {{
      resp.textContent = JSON.stringify(data, null, 2);
    }}
  }} catch(e) {{
    resp.textContent = 'Error: ' + e.message;
  }}
  btn.disabled = false; btn.textContent = 'Send';
}}

async function loadNpcs() {{
  const container = document.getElementById('npc-list');
  try {{
    const r = await fetch('/api/npcs');
    const data = await r.json();
    if (!data.npcs || data.npcs.length === 0) {{
      container.innerHTML = '<span style="color:#9ca3af">No NPCs cached yet</span>';
      return;
    }}
    container.innerHTML = data.npcs.map(npc => {{
      const name = esc(npc.name);
      const safeName = encodeURIComponent(npc.name);
      const size = (npc.dialogue_cache_size / 1024).toFixed(1);
      const reroll = npc.reroll_count || 0;
      const lastAccess = npc.last_access ? new Date(npc.last_access * 1000).toLocaleTimeString() : 'never';
      return `
        <div style="display:flex; justify-content:space-between; align-items:center;
                    padding:8px 0; border-bottom:1px solid #334155">
          <div>
            <span style="color:#f1f5f9; font-weight:500">${{name}}</span>
            <span style="color:#9ca3af; font-size:0.75rem; margin-left:8px">${{size}}KB</span>
            ${{reroll > 0 ? `<span style="color:#facc15; font-size:0.75rem; margin-left:8px">reroll: ${{reroll}}</span>` : ''}}
          </div>
          <div>
            <button onclick="rerollNpc('${{safeName}}')"
                    style="padding:4px 12px; font-size:0.75rem; background:#f59e0b; margin:0">
              Reroll
            </button>
            ${{reroll > 0 ? `<button onclick="clearReroll('${{safeName}}')"
                    style="padding:4px 12px; font-size:0.75rem; background:#6b7280; margin:0 0 0 4px">
              Clear
            </button>` : ''}}
          </div>
        </div>
      `;
    }}).join('');
  }} catch(e) {{
    container.innerHTML = `<span style="color:#f87171">Error: ${{e.message}}</span>`;
  }}
}}

async function rerollNpc(encodedName) {{
  try {{
    const r = await fetch(`/api/npcs/${{encodedName}}/reroll`, {{method: 'POST'}});
    const data = await r.json();
    alert(`${{decodeURIComponent(encodedName)}}: ${{data.message}}`);
    loadNpcs();
  }} catch(e) {{
    alert('Error: ' + e.message);
  }}
}}

async function clearReroll(encodedName) {{
  try {{
    const r = await fetch(`/api/npcs/${{encodedName}}/clear-reroll`, {{method: 'POST'}});
    const data = await r.json();
    alert(`${{decodeURIComponent(encodedName)}}: ${{data.message}}`);
    loadNpcs();
  }} catch(e) {{
    alert('Error: ' + e.message);
  }}
}}

async function loadHistory() {{
  try {{
    const r = await fetch('/api/history');
    const data = await r.json();
    
    // Update stats
    document.getElementById('stat-hit-pct').textContent = data.stats.overall_cache_hit_pct + '%';
    document.getElementById('stat-requests').textContent = data.stats.total_requests;
    document.getElementById('stat-cache-read').textContent = (data.stats.total_cache_read_tokens / 1000).toFixed(1) + 'k';
    document.getElementById('stat-cache-write').textContent = (data.stats.total_cache_write_tokens / 1000).toFixed(1) + 'k';
    
    // Color the hit percentage based on value
    const hitPct = data.stats.overall_cache_hit_pct;
    const hitEl = document.getElementById('stat-hit-pct');
    hitEl.style.color = hitPct >= 80 ? '#4ade80' : hitPct >= 50 ? '#facc15' : '#f87171';
    
    // Update table
    const tbody = document.getElementById('history-body');
    if (!data.requests || data.requests.length === 0) {{
      tbody.innerHTML = '<tr><td colspan="4" style="color:#9ca3af; text-align:center; padding:12px">No requests yet</td></tr>';
      return;
    }}
    
    tbody.innerHTML = data.requests.map(req => {{
      const cacheColor = req.cache_hit_pct >= 80 ? '#4ade80' : req.cache_hit_pct >= 50 ? '#facc15' : '#f87171';
      const cacheText = req.cache_read_tokens > 0 ? `${{req.cache_hit_pct}}%` : (req.cache_write_tokens > 0 ? 'WRITE' : '-');
      return `
        <tr style="border-bottom:1px solid #334155">
          <td style="padding:4px 6px; color:#9ca3af">${{req.timestamp}}</td>
          <td style="padding:4px 6px; color:#f1f5f9">${{esc(req.npc_name || '-')}}</td>
          <td style="padding:4px 6px; color:${{cacheColor}}; font-weight:500">${{cacheText}}</td>
          <td style="padding:4px 6px; color:#67e8f9">${{req.elapsed_seconds}}s</td>
        </tr>
      `;
    }}).join('');
  }} catch(e) {{
    console.error('Failed to load history:', e);
  }}
}}

// Load NPCs and history on page load, refresh history every 5 seconds
document.addEventListener('DOMContentLoaded', () => {{
  loadNpcs();
  loadHistory();
  setInterval(loadHistory, 5000);
}});
</script>
</body></html>"""


if __name__ == "__main__":
    print("\n  CHIM Proxy v0.13.0 — Startup Configuration\n")
    print("  Content format for system prompt and conversation:")
    print("    [1] Array  — preserve CHIM block structure (JSON arrays in CLAUDE.md and stdin)")
    print("    [2] Flat   — flatten to plain text (original behavior)")
    try:
        choice = input("\n  Select format [1/2] (default: 1): ").strip()
    except EOFError:
        choice = ""
    CONTENT_FORMAT = "flat" if choice == "2" else "array"
    logger.info(f"Content format: {CONTENT_FORMAT}")

    print("\n  Reasoning effort (lets Claude think before responding):")
    print("    [1] Off    — no --effort flag, standard responses (default)")
    print("    [2] Low    — minimal reasoning")
    print("    [3] Medium — balanced reasoning")
    print("    [4] High   — maximum reasoning")
    print("    Note: HerikaServer can override this per-request via the 'reasoning' field.")
    try:
        t_choice = input("\n  Select effort [1/2/3/4] (default: 1): ").strip()
    except EOFError:
        t_choice = ""
    if t_choice in ("2", "3", "4"):
        THINKING_ENABLED = True
        THINKING_EFFORT = {"2": "low", "3": "medium", "4": "high"}[t_choice]
        logger.info(f"Reasoning effort: {THINKING_EFFORT}")
    else:
        logger.info("Reasoning effort: OFF (per-request override still works)")

    print("\n  Real-time streaming (for stream=true requests):")
    print("    [1] Off  — collect full response, then chunk to client (default)")
    print("    [2] On   — stream tokens in real-time via --output-format stream-json")
    try:
        s_choice = input("\n  Enable real-time streaming [1/2] (default: 1): ").strip()
    except EOFError:
        s_choice = ""
    if s_choice == "2":
        STREAMING_MODE = "real"
        logger.info("Streaming mode: REAL (token-by-token via stream-json)")
    else:
        STREAMING_MODE = "fake"
        logger.info("Streaming mode: FAKE (collect then chunk)")

    print(f"\n  Dialogue caching:")
    print(f"    Cache path: {DIALOGUE_CACHE_PATH}")
    print(f"    Uncached messages: {DIALOGUE_CACHE_UNCACHED_COUNT}")
    print(f"    (Set CHIM_DIALOGUE_CACHE_PATH and CHIM_DIALOGUE_UNCACHED_COUNT env vars to change)")

    # Detect WSL vEthernet IP - binding to 0.0.0.0 doesn't always work for WSL2
    def _detect_wsl_ip():
        """Find the vEthernet (WSL) interface IP, typically 172.17.x.x"""
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                # WSL vEthernet IPs are typically in 172.17.x.x or 172.18.x.x range
                if ip.startswith("172.17.") or ip.startswith("172.18."):
                    return ip
        except Exception:
            pass
        return None

    wsl_ip = _detect_wsl_ip()
    if wsl_ip:
        host = wsl_ip
        print(f"\n  Detected WSL interface: {wsl_ip} (binding directly for WSL2 compatibility)")
    else:
        host = "0.0.0.0"
        print("\n  No WSL interface detected, binding to 0.0.0.0")
    
    port = 38700

    # Check if port is available; if not, try the next few ports
    def _port_available(h, p):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((h, p))
                return True
            except OSError:
                return False

    if not _port_available(host, port):
        original_port = port
        for candidate in range(port + 1, port + 20):
            if _port_available(host, candidate):
                port = candidate
                break
        if port == original_port:
            print(f"\n  ERROR: Port {port} is in use and no free port found in range {port}–{port+19}.")
            print("  Close the process using the port, or try again.")
            sys.exit(1)
        print(f"\n  NOTE: Port {original_port} is in use — using port {port} instead.")

    # Detect real LAN/WSL IP addresses (not just localhost)
    local_ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                if ip not in local_ips:
                    local_ips.append(ip)
    except Exception:
        pass

    # Primary IP: first detected LAN address, fallback to localhost
    primary_ip = local_ips[0] if local_ips else "127.0.0.1"
    proxy_url = f"http://{primary_ip}:{port}/v1/chat/completions"

    print(f"\n  Content format: {CONTENT_FORMAT}")
    if THINKING_ENABLED:
        print(f"  Reasoning effort: {THINKING_EFFORT}")
    else:
        print("  Reasoning effort: OFF (per-request override via 'reasoning' field still works)")
    print(f"  Streaming: {STREAMING_MODE} ({'token-by-token' if STREAMING_MODE == 'real' else 'collect then chunk'})")
    print(f"  NPC name: auto-detected from system prompt (or pass 'npc_name' in request body)")
    print()
    print("  " + "=" * 60)
    print(f"    Proxy URL:   {proxy_url}")
    if len(local_ips) > 1:
        for ip in local_ips[1:]:
            print(f"                 http://{ip}:{port}/v1/chat/completions")
    print(f"    Localhost:   http://127.0.0.1:{port}/v1/chat/completions")
    print("  " + "-" * 60)
    print(f"    Dashboard:   http://{primary_ip}:{port}/")
    print(f"    Health:      http://{primary_ip}:{port}/health")
    print("  " + "=" * 60)
    print()

    uvicorn.run(app, host=host, port=port)
