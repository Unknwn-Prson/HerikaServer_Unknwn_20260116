"""
OpenAI-compatible proxy using Claude Code CLI legitimately.

Architecture:
  Per-request: spawns `claude -p` subprocess with minimal context flags.
  No MITM, no auth interception, no direct API calls — just the CLI as intended.

  Each request creates an isolated temp directory containing a CLAUDE.md file
  with the NPC's full system prompt.  Claude Code auto-loads this as a
  <system-reminder> with authority framing, giving it stronger weight than
  plain text in stdin.  The temp dir is cleaned up after each response.

Context minimization (applied per request):
  --tools=                    → removes ALL built-in tool descriptions (~10-16K tokens saved)
  --disable-slash-commands    → removes skill/slash-command descriptions from context
  --system-prompt "..."       → short roleplay directive (controls API system blocks)
  --max-turns 1               → single response, no tool loops
  CLAUDE.md in temp dir       → full NPC system prompt with authority framing
  stdin                       → conversation messages only (dialogue history)

  Environment variables:
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1  → skip telemetry/update checks
    DISABLE_NON_ESSENTIAL_MODEL_CALLS=1         → skip warmup/background model calls

Performance notes:
  Each request spawns a subprocess (~1-3s overhead for CLI init + API call).
  Concurrency is limited by MAX_CONCURRENT semaphore.
  No persistent connection reuse — each subprocess opens its own connection.

Content format (selectable at startup):
  Array mode  → preserves CHIM's block structure as JSON arrays in CLAUDE.md and stdin
  Flat mode   → flattens content to plain text (original behavior)

Effort level (selectable at startup, overridable per-request):
  Startup default → sets --effort flag on every CLI invocation
  Per-request     → CHIM connector sends "reasoning" field with effort/thinking settings
  Priority: per-request reasoning.effort > startup default > none
  Mapping: CHIM "minimal" → CLI "low", "low"/"medium"/"high" pass through directly

NPC name handling:
  Auto-detected from system prompt ("You are [Name]" / "Name: [Name]")
  Can be overridden via "npc_name" field in the request body
  Prepended to assistant messages for consistent speaker labeling

Usage:
  pip install fastapi uvicorn pydantic
  python chim_proxy_v1.py
  # Then point any OpenAI-compatible client at http://127.0.0.1:8000/v1/chat/completions
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

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_CONCURRENT = 4

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

# Effort level: "low", "medium", "high", or None (let model decide)
# Set interactively at startup via __main__; can be overridden per-request via reasoning field
EFFORT_LEVEL = None


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

    for pattern in [
        r'(?:You are|Your name is|you are|your name is)\s+([A-Z][a-zA-Z\'-]+(?:\s+[A-Z][a-zA-Z\'-]+)*)',
        r'(?:Name|CHARACTER)\s*:\s*([A-Z][a-zA-Z\'-]+(?:\s+[A-Z][a-zA-Z\'-]+)*)',
    ]:
        match = re.search(pattern, all_text)
        if match:
            name = match.group(1).strip()
            logger.info(f"Detected NPC name: {name}")
            return name
    return None


def _extract_messages(
    raw_messages: list, npc_name_override: Optional[str] = None,
) -> tuple[Optional[str], list[dict], Optional[str]]:
    """Split OpenAI messages into (system_prompt, conversation, npc_name).

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

    # Format system prompt for CLAUDE.md
    if not system_contents:
        system_prompt = None
    elif CONTENT_FORMAT == "array":
        all_blocks = []
        for content in system_contents:
            all_blocks.extend(_content_to_blocks(content))
        system_prompt = json.dumps(all_blocks, indent=2, ensure_ascii=False)
    else:
        system_prompt = "\n\n".join(_flatten_content(c) for c in system_contents)

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

    return system_prompt, conversation, npc_name


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

BASE_SYSTEM_PROMPT = (
    "You are roleplaying a character in Skyrim. "
    "Follow the character definition provided in your context exactly. "
    "Stay in character at all times. Respond only as the character. "
    "Do not break character or reference being an AI."
)

# File where the captured real system prompt is written
# Log dir next to this .py file (visible from Windows desktop)
_SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = _SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
SYSTEM_PROMPT_LOG = LOG_DIR / "system_prompt.log"
REQUEST_LOG = LOG_DIR / "requests.log"


# ---------------------------------------------------------------------------
# Local intercepting proxy — captures the real API request body
# ---------------------------------------------------------------------------

_ANTHROPIC_API_HOST = "api.anthropic.com"


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    """Tiny HTTP proxy that captures the POST body and forwards to Anthropic."""
    captured_body: bytes = b""

    def log_message(self, *args):
        pass  # suppress default http.server logging

    def _forward(self, method: str):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        if method == "POST":
            _CaptureHandler.captured_body = body

        # Rebuild headers for the real API
        fwd = {}
        for key, val in self.headers.items():
            if key.lower() != "host":
                fwd[key] = val
        fwd["Host"] = _ANTHROPIC_API_HOST

        try:
            conn = http.client.HTTPSConnection(_ANTHROPIC_API_HOST)
            conn.request(method, self.path, body or None, fwd)
            resp = conn.getresponse()
            resp_body = resp.read()

            self.send_response(resp.status)
            for key, val in resp.getheaders():
                if key.lower() not in ("transfer-encoding", "content-length"):
                    self.send_header(key, val)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
            conn.close()
        except Exception as e:
            err = f"Proxy forward error: {e}".encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def do_POST(self):
        self._forward("POST")

    def do_GET(self):
        self._forward("GET")


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
    """
    _CaptureHandler.captured_body = b""

    # Start local proxy on a random port
    proxy = http.server.HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    port = proxy.server_address[1]
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    logger.info(f"Capture proxy listening on 127.0.0.1:{port}")

    # Run claude CLI with our proxy as the API endpoint
    env = _ENV.copy()
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"

    cmd = _build_cmd(model)
    req_dir = tempfile.mkdtemp(prefix="claude-capture-")
    try:
        # Write a generic test CLAUDE.md — no specific NPC, just verifies
        # the injection path so the log shows where CLAUDE.md content lands
        test_bio = (
            "You are a guard in Whiterun.\n"
            "Respond briefly and in character.\n"
            "[CAPTURE TEST — this text verifies the CLAUDE.md injection path]"
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
    if not _CaptureHandler.captured_body:
        msg = "No API request was captured — the proxy may not have been reached."
        logger.warning(msg)
        SYSTEM_PROMPT_LOG.write_text(msg, encoding="utf-8")
        return msg

    try:
        api_body = json.loads(_CaptureHandler.captured_body)
    except json.JSONDecodeError:
        raw = _CaptureHandler.captured_body.decode(errors="replace")
        result = f"RAW CAPTURED BODY (not valid JSON):\n\n{raw}"
        SYSTEM_PROMPT_LOG.write_text(result, encoding="utf-8")
        logger.warning("Captured body was not valid JSON")
        return result

    result = _format_api_body(api_body)
    SYSTEM_PROMPT_LOG.write_text(result, encoding="utf-8")
    n_sys = len(api_body.get("system", []))
    n_msg = len(api_body.get("messages", []))
    logger.info(f"Full API body captured ({n_sys} system blocks, {n_msg} messages) "
                f"-> {SYSTEM_PROMPT_LOG}")
    return result


def _log_request(request_id: str, model: str, claude_md: Optional[str],
                  stdin: str, response: str, elapsed: float):
    """Append a full request/response record to logs/requests.log."""
    sep = "=" * 72
    entry = (
        f"\n{sep}\n"
        f"REQUEST {request_id}  |  {time.strftime('%Y-%m-%d %H:%M:%S')}  |  "
        f"{model}  |  {elapsed:.1f}s\n"
        f"{sep}\n"
        f"\n--- CLAUDE.MD (system prompt written to temp dir) ---\n"
        f"{claude_md or '(none)'}\n"
        f"\n--- STDIN (conversation piped to claude -p) ---\n"
        f"{stdin}\n"
        f"\n--- RESPONSE ---\n"
        f"{response}\n"
        f"\n{sep}\n"
    )
    try:
        with open(REQUEST_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning(f"[{request_id}] Failed to write request log: {e}")


def _build_cmd(model: str, effort: Optional[str] = None) -> list[str]:
    """Build claude CLI command with all context-minimization flags."""
    cmd = [
        CLAUDE_PATH, "-p",
        "--tools=",                          # No tools → no tool descriptions in context
        "--disable-slash-commands",          # No skill descriptions in context
        "--system-prompt", BASE_SYSTEM_PROMPT,  # Short directive (fits Windows 32K limit)
        "--model", model,
        "--output-format", "json",           # Single JSON result — reliable on all platforms
        "--max-turns", "1",                  # Single response, no tool loops
        "--no-session-persistence",          # Don't save session to disk
    ]
    if effort and effort in ("low", "medium", "high"):
        cmd.extend(["--effort", effort])
    return cmd


def _resolve_effort(reasoning: Optional[dict]) -> Optional[str]:
    """Resolve effort level: per-request reasoning field > startup default > None.

    The CHIM connector sends a reasoning object like:
      {"enabled": true, "effort": "medium", "exclude": true}
    or for Anthropic-style:
      {"enabled": true, "max_tokens": 1024, "exclude": true}

    For Claude CLI, we map to --effort (low/medium/high).
    CHIM's "minimal" maps to "low" since Claude CLI doesn't have "minimal".
    """
    effort = None

    # Extract from per-request reasoning field
    if reasoning and isinstance(reasoning, dict):
        if reasoning.get("enabled", False):
            raw = reasoning.get("effort")
            if raw:
                raw = str(raw).lower()
                # CHIM uses "minimal" which Claude CLI doesn't support → map to "low"
                effort = {"minimal": "low", "low": "low", "medium": "medium", "high": "high"}.get(raw)

    # Fall back to startup default
    if not effort and EFFORT_LEVEL:
        effort = EFFORT_LEVEL

    return effort


async def call_claude(system_prompt: Optional[str], conversation: list[dict], model: str, effort: Optional[str] = None) -> str:
    """
    Spawn claude -p in a per-request temp dir with CLAUDE.md for the system prompt.

    Architecture:
      - system_prompt (from CHIM) → written as CLAUDE.md in an isolated temp dir
        → Claude Code auto-loads it as a <system-reminder> with authority framing
      - conversation messages → piped to stdin (just the dialogue, no system prompt)
      - --system-prompt flag → short roleplay directive only (controls API system blocks)
    """
    prompt = _format_prompt(conversation)
    cmd = _build_cmd(model, effort)

    request_id = uuid.uuid4().hex[:8]
    sys_len = len(system_prompt) if system_prompt else 0
    effort_str = f", effort={effort}" if effort else ""
    logger.info(f"[{request_id}] -> {model} ({len(conversation)} msgs, "
                f"{sys_len} chars system, {len(prompt)} chars dialogue{effort_str})")
    start = time.time()

    # Per-request isolation: each NPC gets its own temp dir + CLAUDE.md
    req_dir = tempfile.mkdtemp(prefix=f"claude-req-{request_id}-")
    try:
        if system_prompt:
            claude_md = Path(req_dir) / "CLAUDE.md"
            claude_md.write_text(system_prompt, encoding="utf-8")

        async with _semaphore:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_ENV,
                cwd=req_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=300,
            )
    finally:
        shutil.rmtree(req_dir, ignore_errors=True)

    elapsed = time.time() - start
    raw = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()

    if err:
        logger.debug(f"[{request_id}] stderr: {err[:500]}")

    if proc.returncode != 0:
        logger.error(f"[{request_id}] exit {proc.returncode}: {err[:500]}")
        raise HTTPException(status_code=502, detail=f"Claude CLI error: {err[:200]}")

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

    # --- Per-request prompt log ---
    _log_request(request_id, model, system_prompt, prompt, text, elapsed)

    return text


async def call_claude_streaming(system_prompt: Optional[str], conversation: list[dict], model: str, effort: Optional[str] = None):
    """Streaming wrapper: get full response then emit as OpenAI SSE chunks."""
    request_id = uuid.uuid4().hex[:8]
    cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())

    effort_str = f", effort={effort}" if effort else ""
    logger.info(f"[{request_id}] -> {model} ({len(conversation)} msgs, stream{effort_str})")
    start = time.time()

    # Get complete response (reliable across platforms)
    response = await call_claude(system_prompt, conversation, model, effort)

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
    logger.info(f"[{request_id}] <- {len(response)} chars ({elapsed:.1f}s, streamed)")


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
    model_config = {"extra": "allow"}


@asynccontextmanager
async def lifespan(app):
    logger.info("Proxy ready — use /debug/system-prompt?refresh=true to capture system prompt on demand")
    yield


app = FastAPI(title="Claude SkyrimNet Proxy", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    model = req.model or DEFAULT_MODEL
    system_prompt, conversation, npc_name = _extract_messages(req.messages, req.npc_name)

    # Resolve effort level: per-request reasoning field > startup default
    # The CHIM connector sends reasoning as: {"enabled": true, "effort": "medium", ...}
    reasoning = getattr(req, "reasoning", None)
    effort = _resolve_effort(reasoning)

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

    if req.stream:
        return StreamingResponse(
            call_claude_streaming(system_prompt, merged, model, effort),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response = await call_claude(system_prompt, merged, model, effort)
    if not response:
        raise HTTPException(status_code=500, detail="Empty response from Claude")

    # Rough token estimates (chars / 4)
    if CONTENT_FORMAT == "array":
        prompt_text = (system_prompt or "") + " ".join(
            " ".join(b["text"] for b in m["content"]) for m in merged
        )
    else:
        prompt_text = (system_prompt or "") + " ".join(m["content"] for m in merged)
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
        "effort_level": EFFORT_LEVEL or "auto (per-request)",
        "claude_path": CLAUDE_PATH,
        "work_dir": "per-request temp dirs",
        "max_concurrent": MAX_CONCURRENT,
        "system_prompt_log": str(SYSTEM_PROMPT_LOG),
    }


@app.get("/debug/system-prompt")
async def debug_system_prompt(refresh: bool = False):
    """
    Return the real system prompt that Claude Code sends to the API.
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


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    models = [
        ("claude-opus-4-6", "Opus 4.6", "Most capable"),
        ("claude-sonnet-4-6", "Sonnet 4.6", "Best balance (default)"),
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
        <div class="endpoint">http://127.0.0.1:8000/v1/chat/completions</div></div>
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
      <div><span class="label">Effort Level</span><br>
        <span class="value" style="color:#67e8f9">{EFFORT_LEVEL or "auto (per-request)"}</span></div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px">
      <div><span class="label">NPC Name</span><br>
        <span class="value" style="color:#67e8f9">auto-detect (or npc_name field)</span></div>
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
      <tr><td class="label">--system-prompt</td>
        <td class="value" style="color:#4ade80">short roleplay directive (API system blocks)</td></tr>
      <tr><td class="label">--effort</td>
        <td class="value" style="color:#4ade80">thinking depth (from connector or startup default)</td></tr>
      <tr><td class="label">CLAUDE.md per request</td>
        <td class="value" style="color:#4ade80">NPC bio &rarr; &lt;system-reminder&gt; with authority framing</td></tr>
      <tr><td class="label">stdin</td>
        <td class="value" style="color:#4ade80">conversation messages only (dialogue)</td></tr>
      <tr><td class="label">irreducible overhead</td>
        <td class="value" style="color:#facc15">~105 tokens (billing + agent identity + directive)</td></tr>
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

<script>
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
</script>
</body></html>"""


if __name__ == "__main__":
    print("\n  CHIM Proxy v1 — Startup Configuration\n")
    print("  Content format for system prompt and conversation:")
    print("    [1] Array  — preserve CHIM block structure (JSON arrays in CLAUDE.md and stdin)")
    print("    [2] Flat   — flatten to plain text (original behavior)")
    choice = input("\n  Select format [1/2] (default: 1): ").strip()
    CONTENT_FORMAT = "flat" if choice == "2" else "array"
    logger.info(f"Content format: {CONTENT_FORMAT}")

    print("\n  Effort level (controls thinking depth via --effort flag):")
    print("    [1] Low    — minimal reasoning, fastest responses")
    print("    [2] Medium — balanced reasoning (recommended)")
    print("    [3] High   — thorough reasoning, slower responses")
    print("    [4] Auto   — no default; use per-request reasoning from connector")
    effort_choice = input("\n  Select effort [1/2/3/4] (default: 4): ").strip()
    EFFORT_LEVEL = {"1": "low", "2": "medium", "3": "high"}.get(effort_choice)
    if EFFORT_LEVEL:
        logger.info(f"Default effort level: {EFFORT_LEVEL}")
    else:
        logger.info("Default effort level: auto (per-request from connector, or none)")

    host = "0.0.0.0"
    port = 8000

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
    print(f"  Effort level:  {EFFORT_LEVEL or 'auto (per-request)'}")
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
