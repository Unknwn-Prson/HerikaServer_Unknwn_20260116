"""
CHIM Format Proxy v0.1.2

Lightweight MITM proxy between CHIM's openrouterjson connector and the upstream
LLM endpoint. Performs input rewriting (JSON assistant messages -> clean text),
cache-optimized system prompt restructuring (static/dynamic split), and optional
output format conversion (simple parenthetical format <-> JSON).

See DESIGN.md for full architecture documentation.

All per-request configuration comes from x_* fields in the request body,
which are set in the CHIM UI and injected by the connector's setOldGlobals().
"""

VERSION = "0.1.2"

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse

from dialogue_cache import accumulate_and_expand, clear_cache as clear_dialogue_cache

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "proxy_config.yaml"
_PID_PATH = Path(__file__).parent.parent / "temp" / "format_proxy.pid"
_config: dict = {}


def load_config():
    global _config
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f) or {}
    else:
        _config = {}
    # Defaults
    _config.setdefault("dynamic_split_pattern",
                       r"^#+ *(Environmental Context|Additional Information|Current Status)")
    _config.setdefault("dynamic_subsections", [])
    _config.setdefault("uncached_count", 5)
    _config.setdefault("log_level", "INFO")
    _config.setdefault("log_file", "logs/format_proxy.log")
    _config.setdefault("host", "127.0.0.1")
    _config.setdefault("port", 38800)


load_config()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, _config.get("log_level", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / _config["log_file"]),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("chim_format_proxy")

# ---------------------------------------------------------------------------
# PID file
# ---------------------------------------------------------------------------


def write_pid():
    _PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PID_PATH.write_text(str(os.getpid()))


def remove_pid():
    if _PID_PATH.exists():
        _PID_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

# Shared httpx async client (connection pooling)
_http_client: Optional[httpx.AsyncClient] = None


from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    """Startup/shutdown lifecycle for the FastAPI app."""
    global _http_client
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    write_pid()
    logger.info(f"CHIM Format Proxy v{VERSION} started on {_config['host']}:{_config['port']}")
    yield
    if _http_client:
        await _http_client.aclose()
    remove_pid()
    logger.info("CHIM Format Proxy stopped")


app = FastAPI(title="CHIM Format Proxy", version=VERSION, lifespan=_lifespan)


# Reload config on SIGHUP (Unix only)
if hasattr(signal, "SIGHUP"):
    def _sighup_handler(signum, frame):
        load_config()
        logger.info("Config reloaded via SIGHUP")
    signal.signal(signal.SIGHUP, _sighup_handler)


# ===================================================================
# CORE TRANSFORMS
# ===================================================================

# ---------------------------------------------------------------------------
# 1. Extract x_* settings from request body
# ---------------------------------------------------------------------------

# All recognized x_* keys. Anything else starting with x_ is also stripped.
X_KEYS = {
    "x_input_format", "x_input_include_name", "x_input_include_mood",
    "x_input_include_action", "x_input_include_listener",
    "x_output_format", "x_output_include_mood", "x_output_include_action",
    "x_output_include_target", "x_output_include_listener",
    "x_output_include_emotion", "x_output_include_emotion_intensity",
    "x_output_include_item", "x_output_include_amount", "x_output_include_lang",
    "x_upstream_type", "x_proxy_port", "x_character_name", "x_upstream_url",
    "x_custom_system_instruction", "x_custom_last_instruction",
    "x_toggle_thinking", "x_thinking_tokens", "x_effort_level",
    "x_dialogue_cache_enabled", "x_dialogue_cache_max_turns",
    "x_dialogue_cache_max_age", "x_dialogue_cache_fresh_threshold",
    "x_dialogue_cache_uncached_count",
}


def extract_settings(body: dict) -> dict:
    """Pop all x_* keys from request body and return them as a settings dict."""
    settings = {}
    keys_to_pop = [k for k in body if k.startswith("x_")]
    for k in keys_to_pop:
        settings[k] = body.pop(k)

    # Defaults — only mood/listener/action/target enabled by default
    settings.setdefault("x_input_format", "clean_text")
    settings.setdefault("x_input_include_name", True)
    settings.setdefault("x_input_include_mood", False)
    settings.setdefault("x_input_include_action", True)
    settings.setdefault("x_input_include_listener", False)
    settings.setdefault("x_output_format", "vanilla")
    settings.setdefault("x_output_include_mood", True)
    settings.setdefault("x_output_include_action", True)
    settings.setdefault("x_output_include_target", True)
    settings.setdefault("x_output_include_listener", True)
    settings.setdefault("x_output_include_emotion", False)
    settings.setdefault("x_output_include_emotion_intensity", False)
    settings.setdefault("x_output_include_item", False)
    settings.setdefault("x_output_include_amount", False)
    settings.setdefault("x_output_include_lang", False)
    settings.setdefault("x_upstream_type", "direct")
    settings.setdefault("x_upstream_url", "")
    settings.setdefault("x_character_name", "")
    settings.setdefault("x_custom_system_instruction", "")
    settings.setdefault("x_custom_last_instruction", "")
    settings.setdefault("x_toggle_thinking", False)
    settings.setdefault("x_thinking_tokens", 1024)
    settings.setdefault("x_effort_level", "low")
    settings.setdefault("x_dialogue_cache_enabled", True)
    settings.setdefault("x_dialogue_cache_max_turns", 200)
    settings.setdefault("x_dialogue_cache_max_age", 3600)
    settings.setdefault("x_dialogue_cache_fresh_threshold", 3)
    settings.setdefault("x_dialogue_cache_uncached_count", 5)

    # Coerce string booleans from CHIM metadata
    for k, v in settings.items():
        if isinstance(v, str) and v.lower() in ("true", "1", "on"):
            settings[k] = True
        elif isinstance(v, str) and v.lower() in ("false", "0", "off", ""):
            settings[k] = False

    return settings


# ---------------------------------------------------------------------------
# 2. System prompt restructuring (static/dynamic split)
# ---------------------------------------------------------------------------

def split_system_prompt(content: str) -> tuple[str, str]:
    """
    Split system prompt into (static_content, dynamic_content).
    Uses config-driven patterns so new CHIM sections require zero code changes.
    """
    split_pat = _config.get("dynamic_split_pattern", "")
    subsection_pats = _config.get("dynamic_subsections", [])

    dynamic_parts = []

    # First: extract named subsections from anywhere in the text
    for pat in subsection_pats:
        content, extracted = _extract_subsection(content, pat)
        if extracted:
            dynamic_parts.append(extracted)

    # Then: split on the main dynamic boundary
    if split_pat:
        match = re.search(split_pat, content, re.MULTILINE | re.IGNORECASE)
        if match:
            split_pos = match.start()
            static = content[:split_pos].rstrip()
            dynamic_tail = content[split_pos:].strip()
            if dynamic_tail:
                dynamic_parts.insert(0, dynamic_tail)
            content = static

    dynamic_combined = "\n\n".join(p for p in dynamic_parts if p.strip())
    return content.strip(), dynamic_combined.strip()


def _extract_subsection(text: str, pattern: str) -> tuple[str, str]:
    """
    Extract a subsection matching `pattern` from text.
    The subsection runs from the matched heading to the next heading of
    equal or higher level (fewer or equal #), or end of text.
    Returns (remaining_text, extracted_section).
    """
    match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return text, ""

    start = match.start()

    # Determine heading level (count leading #)
    line_start = text.rfind("\n", 0, start) + 1
    heading_line = text[line_start:text.find("\n", start) if "\n" in text[start:] else len(text)]
    level = len(heading_line) - len(heading_line.lstrip("#"))

    # Find end: next heading of same or higher level
    rest = text[match.end():]
    end_pat = re.compile(r"^#{1," + str(level) + r"}\s", re.MULTILINE)
    end_match = end_pat.search(rest)
    if end_match:
        section_end = match.end() + end_match.start()
    else:
        section_end = len(text)

    extracted = text[start:section_end].strip()
    remaining = text[:start] + text[section_end:]
    return remaining, extracted


# ---------------------------------------------------------------------------
# 3. Assistant message rewriting (JSON -> clean text)
# ---------------------------------------------------------------------------

def rewrite_assistant_message(content: str, settings: dict) -> str:
    """
    Convert a CHIM JSON assistant message to clean natural text.
    Returns original content unchanged if it's not valid CHIM JSON.
    """
    # Try to parse as CHIM JSON response
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content

    if not isinstance(data, dict) or "message" not in data:
        return content

    message = str(data.get("message", "")).strip()
    if not message:
        return content

    character = str(data.get("character", "")).strip()
    mood = str(data.get("mood", "")).strip()
    action = str(data.get("action", "")).strip()
    target = str(data.get("target", "")).strip()
    listener = str(data.get("listener", "")).strip()

    parts = []

    # Build name prefix
    if settings.get("x_input_include_name", True) and character:
        if settings.get("x_input_include_mood", False) and mood and mood.lower() not in ("", "default", "neutral"):
            parts.append(f"{character} ({mood}):")
        else:
            parts.append(f"{character}:")
    elif settings.get("x_input_include_mood", False) and mood and mood.lower() not in ("", "default", "neutral"):
        parts.append(f"({mood})")

    # Add listener prefix if enabled
    if settings.get("x_input_include_listener", False) and listener and listener.lower() not in ("", "none", "null"):
        parts.append(f"(to {listener})")

    # Message text
    parts.append(message)

    # Action suffix
    if settings.get("x_input_include_action", True) and action and action.lower() not in ("talk", ""):
        if target and target.lower() not in ("", "none", "null"):
            parts.append(f"[{action} > {target}]")
        else:
            parts.append(f"[{action}]")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# 4. Output instruction rewriting (JSON template -> simple format)
# ---------------------------------------------------------------------------

def get_enabled_output_fields(settings: dict) -> list[tuple[str, str, str]]:
    """
    Returns list of (field_key, description, example_value) for enabled output fields.
    Order matters — this is the order they appear in the parenthetical format.
    """
    all_fields = [
        ("x_output_include_mood", "emotional state", "concerned"),
        ("x_output_include_listener", "who you're speaking to", "Player"),
        ("x_output_include_action", "intended action", "Talk"),
        ("x_output_include_target", "action target", "Player"),
        ("x_output_include_emotion", "emotion", "calm"),
        ("x_output_include_emotion_intensity", "emotion intensity", "moderate"),
        ("x_output_include_item", "item name (if action needs one, otherwise empty)", ""),
        ("x_output_include_amount", "amount (if action needs one, otherwise empty)", ""),
        ("x_output_include_lang", "response language code", "en"),
    ]
    return [(key, desc, ex) for key, desc, ex in all_fields if settings.get(key, False)]


# Default values for fields when disabled — ensures CHIM gets valid JSON
FIELD_DEFAULTS = {
    "mood": "default",
    "listener": "",
    "action": "Talk",
    "target": "",
    "emotion": "",
    "emotion_intensity": "",
    "item": "",
    "amount": "",
    "lang": "",
}

# Maps output setting keys to JSON field names
FIELD_KEY_TO_JSON = {
    "x_output_include_mood": "mood",
    "x_output_include_listener": "listener",
    "x_output_include_action": "action",
    "x_output_include_target": "target",
    "x_output_include_emotion": "emotion",
    "x_output_include_emotion_intensity": "emotion_intensity",
    "x_output_include_item": "item",
    "x_output_include_amount": "amount",
    "x_output_include_lang": "lang",
}


def build_simple_format_instruction(settings: dict, character_name: str) -> str:
    """
    Build the simple format instruction that replaces the JSON template.
    Only mentions fields that are enabled — don't instruct the LLM to produce
    fields the user has disabled.
    """
    enabled = get_enabled_output_fields(settings)

    if not enabled:
        return f"Write {character_name}'s next dialogue line."

    descs = [desc for _, desc, _ in enabled]
    examples = [ex for _, _, ex in enabled]

    format_example = "(" + ")(".join(examples) + ")"
    desc = ", ".join(descs)

    instruction = (
        f"Begin your response by noting your {desc} "
        f"in parentheses like this: {format_example}, "
        f"then provide your dialogue. "
        f"Example: {format_example} I'm worried about that cave we passed."
    )

    return instruction


def find_and_replace_output_instruction(messages: list, settings: dict,
                                         character_name: str) -> None:
    """
    Find the last user message (CHIM's JSON template instruction) and
    replace it with a simple format instruction. Modifies messages in place.
    Also removes response_format from the request body if present.
    """
    # Walk backwards to find the JSON template instruction
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and "JSON" in content and "responseTemplate" not in content:
            # This looks like CHIM's "Use ONLY this JSON object..." instruction
            # Also check for the json_encode output pattern
            if "{" in content and "character" in content.lower():
                new_instruction = build_simple_format_instruction(settings, character_name)
                msg["content"] = new_instruction
                logger.debug(f"Replaced JSON instruction at message index {i}")
                return
        # Also match the exact pattern with json_encode
        if isinstance(content, str) and "Use ONLY this JSON" in content:
            new_instruction = build_simple_format_instruction(settings, character_name)
            msg["content"] = new_instruction
            logger.debug(f"Replaced JSON instruction at message index {i}")
            return


# ---------------------------------------------------------------------------
# 5. Dynamic content reinsertion
# ---------------------------------------------------------------------------

def reinsert_dynamic_content(messages: list, dynamic_content: str) -> None:
    """
    Insert extracted dynamic content as a user message before the final
    instruction message. Modifies messages in place.
    """
    if not dynamic_content.strip():
        return

    dynamic_msg = {
        "role": "user",
        "content": f"[Current context]\n{dynamic_content}"
    }

    # Insert before the last message (which is the format instruction)
    insert_pos = max(0, len(messages) - 1)
    messages.insert(insert_pos, dynamic_msg)
    logger.debug(f"Inserted dynamic content ({len(dynamic_content)} chars) at position {insert_pos}")


# ---------------------------------------------------------------------------
# 6. Cache control placement (for x_upstream_type=direct only)
# ---------------------------------------------------------------------------

def place_cache_markers(messages: list, uncached_count: int = 5) -> None:
    """
    Add Anthropic-style cache_control markers for direct upstream connections.
    Places markers at the system message and at the cache boundary in dialogue.
    """
    uncached = uncached_count

    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, str):
                # Convert to Anthropic content block format with cache_control
                msg["content"] = [{
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"}
                }]
            elif isinstance(content, list):
                # Already block format — add cache_control to last block
                if content:
                    content[-1]["cache_control"] = {"type": "ephemeral"}
            break

    # Place dialogue cache breakpoint
    # Find the boundary: uncached_count messages from the end
    non_system = [i for i, m in enumerate(messages) if m.get("role") != "system"]
    if len(non_system) > uncached + 1:
        boundary_idx = non_system[-(uncached + 1)]
        msg = messages[boundary_idx]
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = [{
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"}
            }]
        elif isinstance(content, list) and content:
            content[-1]["cache_control"] = {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# 7. Custom prompt injection
# ---------------------------------------------------------------------------

def apply_custom_system_instruction(messages: list, instruction: str) -> None:
    """
    Append custom system instruction to the end of the system message.
    Placed after static bio/actions but before dynamic content is relocated.
    """
    if not instruction.strip():
        return
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str):
                msg["content"] = content.rstrip() + "\n\n" + instruction.strip()
            elif isinstance(content, list):
                # Anthropic block format — append to last text block
                for block in reversed(content):
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["text"] = block["text"].rstrip() + "\n\n" + instruction.strip()
                        break
            logger.debug(f"Appended custom system instruction ({len(instruction)} chars)")
            break


def insert_custom_last_instruction(messages: list, instruction: str) -> None:
    """
    Insert custom last instruction as a user message before the final message.
    The final message is the format instruction — this goes right before it,
    giving it the strongest recency-bias influence on the LLM.
    """
    if not instruction.strip():
        return
    msg = {"role": "user", "content": instruction.strip()}
    insert_pos = max(0, len(messages) - 1)
    messages.insert(insert_pos, msg)
    logger.debug(f"Inserted custom last instruction ({len(instruction)} chars) at position {insert_pos}")


# ---------------------------------------------------------------------------
# 8. Reasoning / thinking configuration
# ---------------------------------------------------------------------------

# Minimum thinking tokens per model family.
# Checked in order; first matching substring wins.
# Models not listed have no enforced minimum (user value passed through).
THINKING_TOKEN_MINIMUMS = [
    ("claude", 1024),      # Anthropic Claude: minimum 1024 budget_tokens
]


def _get_min_thinking_tokens(model: str) -> int:
    """Look up the minimum thinking token budget for a model family."""
    for pattern, minimum in THINKING_TOKEN_MINIMUMS:
        if pattern in model:
            return minimum
    return 1


VALID_EFFORT_LEVELS = ("minimal", "low", "medium", "high", "max")


# Models that support effort-based reasoning control.
# Substring match against lowercased model name. Default: token-budget only.
# Add new model families here as providers adopt effort-based reasoning.
EFFORT_REASONING_PATTERNS = [
    # OpenAI
    "openai/o1", "openai/o3", "openai/o4",
    "openai/gpt-5", "openai/gpt-oss",
    # Google Gemini
    "gemini-2.5", "gemini-3", "gemini-2.0-flash-thinking",
    # xAI
    "grok-3", "grok-4",
]


def apply_reasoning_config(body: dict, settings: dict) -> None:
    """
    Strip CHIM's reasoning config and apply proxy-controlled reasoning.
    When the format proxy connector is active, the proxy is the single
    source of truth for reasoning — CHIM's reasoning_model toggle is bypassed.

    Effort and max_tokens are mutually exclusive in the reasoning object.
    Model detection picks the appropriate one; the other is omitted.
    The max_completion_tokens swap is a separate OpenAI-specific concern.
    """
    body.pop("enable_thinking", None)

    if not settings.get("x_toggle_thinking"):
        # Toggle off: ensure reasoning is explicitly disabled to suppress CoT.
        # CHIM may or may not have added reasoning (depends on model auto-detection).
        # Either way, explicitly set enabled=false so models that reason by
        # default don't produce unwanted thinking output.
        body["reasoning"] = {"exclude": True, "enabled": False}
        return

    # Toggle on: strip CHIM's reasoning and apply proxy-controlled config
    body.pop("reasoning", None)

    model = body.get("model", "").lower()

    reasoning = {"exclude": True, "enabled": True}

    if _uses_effort_reasoning(model):
        effort = str(settings.get("x_effort_level", "low"))
        if effort not in VALID_EFFORT_LEVELS:
            effort = "low"
        reasoning["effort"] = effort
        logger.debug(f"Applied reasoning config: effort={effort}")
    else:
        tokens = int(settings.get("x_thinking_tokens", 1024))
        min_tokens = _get_min_thinking_tokens(model)
        tokens = max(min_tokens, tokens)
        reasoning["max_tokens"] = tokens
        logger.debug(f"Applied reasoning config: max_tokens={tokens}")

    body["reasoning"] = reasoning

    # OpenAI-specific: these models require max_completion_tokens instead of
    # max_tokens in the top-level request body. Separate from effort support.
    if _needs_max_completion_tokens(model) and "max_tokens" in body:
        body["max_completion_tokens"] = body.pop("max_tokens")


def _uses_effort_reasoning(model: str) -> bool:
    """Check if model supports effort-based reasoning (vs token budgets)."""
    return any(p in model for p in EFFORT_REASONING_PATTERNS)


def _needs_max_completion_tokens(model: str) -> bool:
    """Detect models that require max_completion_tokens parameter swap."""
    # Only OpenAI o-series and GPT-5+; other effort models don't need this
    return bool(re.search(r'(?:^|/)o[134](-|$)', model) or
                "openai/gpt-5" in model or "openai/gpt-oss" in model)


# ===================================================================
# RESPONSE STREAM CONVERSION (simple -> JSON)
# ===================================================================

def extract_character_name(messages: list, settings: dict) -> str:
    """Get the NPC name from settings or by parsing the system prompt."""
    name = settings.get("x_character_name", "")
    if name:
        return name

    # Try to extract from system prompt
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            # Look for "You are {Name}" or "character: {Name}" patterns
            m = re.search(r"(?:You are|character[:\s]+)[\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", content)
            if m:
                return m.group(1)
            break
    return "NPC"


async def convert_simple_stream_to_json(
    response: httpx.Response,
    settings: dict,
    character_name: str,
):
    """
    Intercept an SSE stream where the model outputs simple format,
    and convert it to JSON format SSE chunks that openrouterjson.process() expects.

    The model outputs: (mood)(listener)(action)(target) dialogue text...
    We emit:           {"character":"X","listener":"Y","mood":"Z","action":"A","target":"T","message":"dialogue text..."}
    """
    buffer = ""
    raw_accumulated = ""  # Track raw upstream content for logging
    metadata_parsed = False
    metadata_fields = {}
    json_prefix_sent = False

    # Which metadata fields are expected (in order), derived from enabled settings
    enabled = get_enabled_output_fields(settings)
    expected_fields = [FIELD_KEY_TO_JSON[key] for key, _, _ in enabled]

    try:
        async for line in response.aiter_lines():
            # Pass through non-data lines
            if not line.startswith("data: "):
                if line.strip():
                    yield line + "\n\n"
                continue

            payload = line[6:].strip()
            if payload == "[DONE]":
                # Log raw upstream content before conversion
                _log_request("RAW_OUTPUT", character_name, {"raw_simple_format": raw_accumulated})
                # Close the JSON object and emit final chunk
                if json_prefix_sent:
                    yield _make_sse_chunk('"}')
                yield "data: [DONE]\n\n"
                break

            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                yield line + "\n\n"
                continue

            # Extract text delta
            delta_content = ""
            if "choices" in data and data["choices"]:
                delta = data["choices"][0].get("delta", {})
                delta_content = delta.get("content", "")

                # Check for finish_reason
                if data["choices"][0].get("finish_reason"):
                    if json_prefix_sent:
                        yield _make_sse_chunk('"}')
                    yield line + "\n\n"
                    continue

            if not delta_content:
                # Pass through usage, non-content chunks
                yield line + "\n\n"
                continue

            buffer += delta_content
            raw_accumulated += delta_content

            if not metadata_parsed:
                # Try to parse metadata from buffer
                parsed = _try_parse_metadata(buffer, expected_fields)
                if parsed is not None:
                    metadata_fields, message_start = parsed
                    metadata_parsed = True
                    # Build and emit JSON prefix
                    json_prefix = _build_json_prefix(metadata_fields, character_name)
                    yield _make_sse_chunk(json_prefix)
                    json_prefix_sent = True
                    # Emit any message text already in buffer
                    remaining = buffer[message_start:]
                    if remaining:
                        yield _make_sse_chunk(_json_escape(remaining))
                    buffer = ""  # Reset — we've consumed it
                # else: keep accumulating until we can parse metadata
            else:
                # Metadata already parsed — stream message text through
                yield _make_sse_chunk(_json_escape(delta_content))
    finally:
        await response.aclose()


def _try_parse_metadata(buffer: str, expected_fields: list) -> Optional[tuple[dict, int]]:
    """
    Try to parse (field1)(field2)... prefix from buffer.
    Returns (fields_dict, message_start_index) or None if not enough data yet.
    """
    if not expected_fields:
        return {}, 0

    # Build regex for expected number of groups
    n = len(expected_fields)
    pattern = r"^\s*" + r"\s*".join([r"\(([^)]*)\)"] * n) + r"\s*"
    match = re.match(pattern, buffer)
    if not match:
        # Not enough data yet, or format doesn't match
        # If buffer is getting long without a match, give up
        if len(buffer) > 200:
            logger.warning(f"Could not parse metadata from buffer (>200 chars), passing through")
            return {}, 0
        return None

    fields = {}
    for i, field_name in enumerate(expected_fields):
        fields[field_name] = match.group(i + 1).strip()

    return fields, match.end()


def _build_json_prefix(fields: dict, character_name: str) -> str:
    """
    Build the opening of a JSON response object from parsed metadata.
    Includes ALL fields CHIM expects, using defaults for any not parsed.
    """
    obj = {"character": character_name}
    # Merge parsed fields with defaults — every CHIM field gets a value
    for json_field, default in FIELD_DEFAULTS.items():
        obj[json_field] = fields.get(json_field, default)

    # Build partial JSON: everything up to and including "message":"
    # We'll stream the message content, then close with "}
    parts = []
    for k, v in obj.items():
        parts.append(f'"{k}":"{_json_escape(v)}"')
    return "{" + ",".join(parts) + ',"message":"'


def _json_escape(s: str) -> str:
    """Escape a string for inclusion in a JSON string value."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _make_sse_chunk(content: str) -> str:
    """Wrap content delta in an OpenAI SSE chunk."""
    chunk = {
        "choices": [{
            "index": 0,
            "delta": {"content": content},
        }]
    }
    return f"data: {json.dumps(chunk)}\n\n"


# ===================================================================
# REQUEST LOGGING
# ===================================================================

_request_log_path = Path(__file__).parent / "logs" / "requests.log"


def _log_request(label: str, character: str, data: dict, truncate_content: int = 500):
    """
    Write a labeled request/response snapshot to the request log.
    Labels: RAW_INPUT, TRANSFORMED_INPUT, RAW_OUTPUT, TRANSFORMED_OUTPUT
    """
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        separator = f"\n{'='*80}\n[{ts}] {label} | {character}\n{'='*80}\n"

        # For message arrays, show role + truncated content for readability
        if "messages" in data:
            lines = [separator]
            for i, msg in enumerate(data["messages"]):
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Anthropic block format — extract text
                    content = " ".join(b.get("text", "")[:200] for b in content if isinstance(b, dict))
                content = str(content).replace("\r", "").replace("\n", "⏎")
                if len(content) > truncate_content:
                    content = content[:truncate_content] + f"... [{len(content)} chars total]"
                lines.append(f"  [{i}] {role}: {content}\n")
            # Include non-message fields (model, stream, etc.) without messages
            meta = {k: v for k, v in data.items() if k != "messages"}
            if meta:
                lines.append(f"  [meta] {json.dumps(meta, default=str)}\n")
            with open(_request_log_path, "a", encoding="utf-8") as f:
                f.writelines(lines)
        else:
            # Raw string/dict output
            text = json.dumps(data, default=str, ensure_ascii=False)
            if len(text) > 2000:
                text = text[:2000] + f"... [{len(text)} chars total]"
            with open(_request_log_path, "a", encoding="utf-8") as f:
                f.write(separator + text + "\n")
    except Exception as e:
        logger.warning(f"Failed to write request log ({label}): {e}")


# ===================================================================
# MAIN REQUEST HANDLER
# ===================================================================

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Main proxy endpoint — receives OpenAI-format requests from CHIM."""
    raw_body = await request.json()
    # Deep copy for logging before we mutate it
    body = json.loads(json.dumps(raw_body))

    # Step 1: Extract and strip x_* settings
    settings = extract_settings(body)
    character_name_early = settings.get("x_character_name", "?")
    logger.info(f"Request: model={body.get('model', '?')}, "
                f"input={settings.get('x_input_format')}, "
                f"output={settings.get('x_output_format')}, "
                f"upstream={settings.get('x_upstream_type')}, "
                f"msgs={len(body.get('messages', []))}")

    # LOG 1: Raw input from CHIM (before any transforms, but after x_* extraction)
    _log_request("RAW_INPUT", character_name_early, raw_body)

    messages = body.get("messages", [])

    # Extract character name before any transforms
    character_name = extract_character_name(messages, settings)
    logger.debug(f"Character name: {character_name}")

    # Step 2: System prompt restructuring
    dynamic_content = ""
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                static, dynamic = split_system_prompt(content)
                msg["content"] = static
                dynamic_content = dynamic
                if dynamic:
                    logger.debug(f"Extracted {len(dynamic)} chars of dynamic content from system prompt")
            break

    # Step 2b: Custom system instruction (appended to static system content)
    custom_sys = settings.get("x_custom_system_instruction", "")
    if custom_sys:
        apply_custom_system_instruction(messages, custom_sys)

    # Step 2c: Dialogue cache — accumulate rolling window, expand to full history
    if settings.get("x_dialogue_cache_enabled", True):
        # Last message is always the format instruction — separate it
        instruction_msg = messages[-1] if messages else None
        system_msgs = [m for m in messages[:-1] if m.get("role") == "system"]
        dialogue_turns = [m for m in messages[:-1] if m.get("role") != "system"]

        full_dialogue = accumulate_and_expand(
            dialogue_turns, character_name,
            max_turns=int(settings.get("x_dialogue_cache_max_turns", 200)),
            max_age=int(settings.get("x_dialogue_cache_max_age", 3600)),
            fresh_threshold=int(settings.get("x_dialogue_cache_fresh_threshold", 3)),
        )

        messages.clear()
        messages.extend(system_msgs)
        messages.extend(full_dialogue)
        if instruction_msg:
            messages.append(instruction_msg)
        logger.debug(f"Dialogue cache: {len(dialogue_turns)} window → "
                     f"{len(full_dialogue)} cached → {len(messages)} total msgs")

    # Step 3: Assistant message rewriting (input format)
    if settings.get("x_input_format") == "clean_text":
        rewrite_count = 0
        for msg in messages:
            if msg.get("role") == "assistant":
                original = msg.get("content", "")
                rewritten = rewrite_assistant_message(original, settings)
                if rewritten != original:
                    msg["content"] = rewritten
                    rewrite_count += 1
        if rewrite_count:
            logger.debug(f"Rewrote {rewrite_count} assistant messages to clean text")

    # Step 4: Reinsert dynamic content near end
    if dynamic_content:
        reinsert_dynamic_content(messages, dynamic_content)

    # Step 4b: Custom last instruction (before format instruction, after dynamic)
    custom_last = settings.get("x_custom_last_instruction", "")
    if custom_last:
        insert_custom_last_instruction(messages, custom_last)

    # Step 5: Output format rewriting
    simple_output = settings.get("x_output_format") == "simple"
    if simple_output:
        find_and_replace_output_instruction(messages, settings, character_name)
        # Remove response_format constraint — model should NOT be forced to JSON
        body.pop("response_format", None)

    # Step 6: Cache control placement (direct upstream only)
    if settings.get("x_upstream_type") == "direct":
        place_cache_markers(messages,
                            uncached_count=int(settings.get("x_dialogue_cache_uncached_count", 5)))

    body["messages"] = messages

    # Step 6b: Reasoning configuration (replaces CHIM's reasoning logic)
    apply_reasoning_config(body, settings)

    # LOG 2: Transformed input sent to upstream
    _log_request("TRANSFORMED_INPUT", character_name, body)

    # Step 7: Forward to upstream
    upstream_url = request.query_params.get("upstream", "")
    if not upstream_url:
        upstream_url = str(settings.get("x_upstream_url", ""))
    if not upstream_url:
        upstream_url = _config.get("upstream_url", "")
    if not upstream_url:
        return JSONResponse(
            status_code=400,
            content={"error": "No upstream URL configured. Set ?upstream= query param, x_upstream_url setting, or upstream_url in proxy_config.yaml"}
        )

    # Forward headers (preserve Authorization for upstream auth)
    forward_headers = {
        "Content-Type": "application/json",
    }
    auth = request.headers.get("Authorization")
    if auth:
        forward_headers["Authorization"] = auth
    # Pass through OpenRouter-specific headers
    for hdr in ("HTTP-Referer", "X-Title"):
        val = request.headers.get(hdr)
        if val:
            forward_headers[hdr] = val

    is_streaming = body.get("stream", False)

    logger.debug(f"Forwarding to {upstream_url} (stream={is_streaming})")

    try:
        if is_streaming:
            upstream_resp = await _http_client.send(
                _http_client.build_request(
                    "POST", upstream_url,
                    json=body,
                    headers=forward_headers,
                ),
                stream=True,
            )

            if upstream_resp.status_code >= 300:
                error_body = await upstream_resp.aread()
                await upstream_resp.aclose()
                logger.error(f"Upstream error {upstream_resp.status_code}: {error_body[:500]}")
                return JSONResponse(
                    status_code=upstream_resp.status_code,
                    content=json.loads(error_body) if error_body else {"error": "Upstream error"},
                )

            if simple_output:
                # Intercept and convert simple format stream to JSON
                return StreamingResponse(
                    _logging_stream_wrapper(
                        convert_simple_stream_to_json(upstream_resp, settings, character_name),
                        character_name, is_converted=True,
                    ),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            else:
                # Pass through SSE stream unchanged
                return StreamingResponse(
                    _logging_stream_wrapper(
                        _passthrough_stream(upstream_resp),
                        character_name, is_converted=False,
                    ),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
        else:
            # Non-streaming
            resp = await _http_client.post(upstream_url, json=body, headers=forward_headers)
            resp_data = resp.json()
            # LOG 3+4: For non-streaming, raw and transformed are the same
            _log_request("RAW_OUTPUT", character_name, resp_data)
            _log_request("TRANSFORMED_OUTPUT", character_name, resp_data)
            return JSONResponse(status_code=resp.status_code, content=resp_data)

    except httpx.ConnectError as e:
        logger.error(f"Connection error to upstream {upstream_url}: {e}")
        return JSONResponse(status_code=502, content={"error": f"Cannot connect to upstream: {e}"})
    except Exception as e:
        logger.error(f"Proxy error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


async def _passthrough_stream(response: httpx.Response):
    """Pass through SSE stream unchanged."""
    try:
        async for line in response.aiter_lines():
            yield line + "\n\n" if line.strip() else ""
    finally:
        await response.aclose()


async def _logging_stream_wrapper(stream, character_name: str, is_converted: bool):
    """
    Wraps an SSE stream generator, accumulating content for logging.
    Logs RAW_OUTPUT (accumulated text deltas from upstream) and
    TRANSFORMED_OUTPUT (what CHIM actually receives) at stream end.
    """
    raw_content = []       # text deltas as received from upstream
    sent_content = []      # text deltas as sent to CHIM

    async for chunk in stream:
        # Extract content from the SSE chunk for logging
        if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
            try:
                data = json.loads(chunk[6:])
                delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    sent_content.append(delta)
            except (json.JSONDecodeError, IndexError, KeyError):
                pass
        yield chunk

    # Stream finished — log accumulated content
    sent_text = "".join(sent_content)
    if is_converted:
        # For converted streams, raw was the simple format and sent is JSON
        _log_request("RAW_OUTPUT", character_name, {"note": "simple format (accumulated in converter)", "content": "(see TRANSFORMED_OUTPUT for JSON reconstruction)"})
        _log_request("TRANSFORMED_OUTPUT", character_name, {"content": sent_text})
    else:
        # For passthrough, raw and sent are the same
        _log_request("RAW_OUTPUT", character_name, {"content": sent_text})
        _log_request("TRANSFORMED_OUTPUT", character_name, {"content": sent_text})


# ===================================================================
# UTILITY ENDPOINTS
# ===================================================================

@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "config": {
        "port": _config.get("port"),
        "dynamic_split_pattern": _config.get("dynamic_split_pattern"),
        "dynamic_subsections": _config.get("dynamic_subsections"),
        "uncached_count": _config.get("uncached_count"),
    }}


@app.post("/api/config/reload")
async def reload_config():
    load_config()
    logger.info("Config reloaded via API")
    return {"status": "reloaded"}


@app.post("/api/cache/clear/{character}")
async def cache_clear(character: str):
    """Clear dialogue cache for a character."""
    clear_dialogue_cache(character)
    return {"status": "cleared", "character": character}


@app.post("/api/cache/clear-all")
async def cache_clear_all():
    """Clear all dialogue caches."""
    from dialogue_cache import CACHE_DIR, _cache_turns, _cache_hashes, _cache_timestamps
    names = list(_cache_turns.keys())
    for name in names:
        clear_dialogue_cache(name)
    # Also remove any JSONL files not in memory
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.jsonl"):
            f.unlink(missing_ok=True)
    return {"status": "cleared", "characters": names}


@app.get("/api/logs/tail")
async def logs_tail(n: int = 100):
    """Return last N lines of the request log."""
    if not _request_log_path.exists():
        return {"lines": []}
    with open(_request_log_path, encoding="utf-8") as f:
        all_lines = f.readlines()
    return {"lines": all_lines[-n:]}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return f"""
    <html><head><title>CHIM Format Proxy</title>
    <style>body{{font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:20px}}
    h1{{color:#ffb862}}pre{{background:#16213e;padding:15px;border-radius:8px}}
    .ok{{color:#4ade80}}</style></head>
    <body>
    <h1>CHIM Format Proxy v{VERSION}</h1>
    <p class="ok">Status: Running</p>
    <h2>Configuration</h2>
    <pre>{yaml.dump(_config, default_flow_style=False)}</pre>
    <h2>Endpoints</h2>
    <pre>
POST /v1/chat/completions   — Main proxy endpoint (OpenAI-compatible)
GET  /health                — Health check
POST /api/config/reload     — Reload proxy_config.yaml
GET  /                      — This dashboard
    </pre>
    <h2>Usage</h2>
    <pre>
In CHIM, set connector URL to:
  http://127.0.0.1:{_config.get('port', 38800)}/v1/chat/completions?upstream=YOUR_UPSTREAM_URL

For OpenRouter:
  ?upstream=https://openrouter.ai/api/v1/chat/completions

For Claude subscription proxy:
  ?upstream=http://127.0.0.1:38700/v1/chat/completions
    </pre>
    </body></html>
    """


# ===================================================================
# ENTRY POINT
# ===================================================================

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else _config.get("port", 38800)
    host = _config.get("host", "127.0.0.1")
    logger.info(f"Starting on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
