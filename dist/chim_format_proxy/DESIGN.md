# CHIM Format Proxy — Design Document

## Purpose

A lightweight Python proxy that sits between CHIM 3.0.0's `openrouterjson` connector
and the upstream LLM endpoint (OpenRouter, Claude subscription proxy, or any
OpenAI-compatible API). It performs two independent transformations:

1. **Input rewriting**: Converts JSON-formatted assistant messages in dialogue
   history into clean natural-language text, improving LLM response quality.
2. **Cache optimization**: Restructures the system prompt by separating static
   content (character bio, rules) from dynamic content (environment, equipment,
   combat status), ensuring the message prefix is stable across requests for
   automatic provider caching.

Optionally:

3. **Output format**: Replaces the JSON response instruction with a lightweight
   `(mood)(listener)(action)(target) message` format, and converts the LLM's
   simple-format response back to JSON before CHIM sees it.

## Architecture

```
CHIM 3.0.0 (openrouterjsonreformat driver, which IS openrouterjson)
  |  POST /v1/chat/completions
  |  Body includes x_* settings from CHIM UI (via extra_parameters)
  v
Format Proxy (Python/FastAPI, port from config)
  |  1. Extract & strip x_* settings from request body
  |  2. System prompt: split static/dynamic (config-driven patterns)
  |  2b. Append custom system instruction (if x_custom_system_instruction set)
  |  3. Assistant messages: JSON -> clean text (if x_input_format=clean_text)
  |  4. Relocate dynamic content to end of message sequence
  |  4b. Insert custom last instruction (if x_custom_last_instruction set)
  |  5. Output instruction: replace JSON template with simple format (if x_output_format=simple)
  |  6. Cache control placement (if x_upstream_type=direct)
  |  6b. Reasoning config: strip CHIM's, apply x_toggle_thinking/tokens/effort
  |  7. Forward cleaned request to upstream
  |  8. Stream response back; convert simple->JSON if needed
  v
Upstream (one of):
  - OpenRouter API (https://openrouter.ai/api/v1/chat/completions)
  - Claude subscription proxy (http://127.0.0.1:38700/v1/chat/completions)
  - Any OpenAI-compatible endpoint
```

## Why Not a Connector Fork

CHIM 3.0.0's `openrouterjson.php` is 1472 lines. All its properties are `private`,
making class extension impractical. Forking would duplicate all 1472 lines and
create a maintenance burden when upstream CHIM updates.

Instead, the new connector is a 25-line PHP class that extends `openrouterjson`,
changing only `$this->name` (for config isolation) and adding a proxy health check.
All transformation logic lives in the proxy.

## Components

### 1. CHIM Connector Registration (PHP, ~25 lines)

**File**: `connector/openrouterjsonreformat.php`

```php
class openrouterjsonreformat extends openrouterjson {
    public function __construct() {
        parent::__construct();
        $this->name = "openrouterjsonreformat";
        // Health-check and auto-start proxy if installed
    }
}
```

- Inherits ALL behavior from `openrouterjson` (open, process, processActions, etc.)
- `$this->name = "openrouterjsonreformat"` makes it read config from
  `$GLOBALS["CONNECTOR"]["openrouterjsonreformat"]` instead of
  `$GLOBALS["CONNECTOR"]["openrouterjson"]`, providing config isolation
- Auto-start logic: checks PID file, pings /health, spawns proxy if needed

### 2. Settings Bridge (PHP, ~45 lines in setOldGlobals)

**File**: `lib/core/llm_connector.class.php` (upstream edit)

A new `elseif` block in `setOldGlobals()` that:
1. Maps DB columns to `$GLOBALS["CONNECTOR"]["openrouterjsonreformat"]`
   (identical to the openrouterjson block)
2. Decodes `metadata` JSON and overlays onto globals
3. Injects `x_*` format settings from metadata into `extra_parameters`
   so that `openrouterjson`'s `open()` includes them in the HTTP request body
   via `chimGetEnabledConnectorExtraParameters()`

This is how CHIM UI settings reach the proxy: they travel as fields in the
request body, and the proxy strips them before forwarding upstream.

### 3. UI Registration (2 upstream edits)

**File**: `ui/core/llm_connectors.php` — add one `<option>` to the driver
dropdown for "Custom" service mode.

**File**: `conf/conf_schema.json` — add `"openrouterjsonreformat"` to the
`CONNECTORS.values` array, and add a new connector section with:
- All standard openrouterjson fields (url, model, API_KEY, temperature, etc.)
- Additional format proxy fields (x_input_format, x_output_format, etc.)

### 4. Format Proxy (Python, ~900 lines)

**File**: `proxy/chim_format_proxy.py`

Single-file FastAPI application. Stateless — all per-request configuration
comes from `x_*` fields in the request body.

## Data Flow: Request Lifecycle

### Step 1: CHIM sends request

CHIM's `openrouterjson.open()` builds a standard OpenAI chat completion request.
The `chimGetEnabledConnectorExtraParameters()` call adds the `x_*` settings
to the request body. The URL points to the format proxy.

Request body (simplified):
```json
{
  "model": "anthropic/claude-sonnet-4-20250514",
  "messages": [
    {"role": "system", "content": "You are Lydia...\n# Environmental Context\n..."},
    {"role": "user", "content": "Player: What do you think?"},
    {"role": "assistant", "content": "{\"character\":\"Lydia\",\"mood\":\"\",\"action\":\"Talk\",\"target\":\"\",\"message\":\"I think we should be careful.\"}"},
    {"role": "user", "content": "Player: Let's go then."},
    {"role": "user", "content": "Use ONLY this JSON object... {\"character\":\"Lydia\",...}"}
  ],
  "stream": true,
  "x_input_format": "clean_text",
  "x_input_include_name": true,
  "x_input_include_action": true,
  "x_input_include_mood": false,
  "x_output_format": "simple",
  "x_output_include_mood": true,
  "x_output_include_action": true,
  "x_output_include_target": true,
  "x_output_include_listener": true,
  "x_upstream_type": "direct"
}
```

### Step 2: Proxy extracts config

The proxy pops all `x_*` keys from the request body. They never reach
the upstream API.

### Step 3: System prompt restructuring

The proxy parses the system message content and splits it into static
and dynamic sections using configurable patterns.

**Split logic** (config-driven, not hardcoded):

The proxy config file defines a `dynamic_split_pattern` regex.
Default: `^#+ *(Environmental Context|Additional Information|Current Status)`

Everything from the first match of this pattern to the end of the system
message is "dynamic." Additionally, a `dynamic_subsections` list defines
subsection patterns (e.g., `^### Equipment`, `^### Combat Vitals`) that
should be extracted even if they appear within the static portion.

Adding new CHIM sections = one line in config. No proxy code changes.

After extraction:
- System message contains only static content (bio, rules, actions)
- Dynamic content is held aside for reinsertion later

### Step 4: Assistant message rewriting (input format)

If `x_input_format` is `clean_text`, each assistant message whose content
is valid CHIM JSON (`{"character":"...","message":"..."}`) is rewritten:

Before:
```json
{"role": "assistant", "content": "{\"character\":\"Lydia\",\"listener\":\"Player\",\"mood\":\"concerned\",\"action\":\"Follow\",\"target\":\"Player\",\"message\":\"I think we should be careful.\"}"}
```

After (with x_input_include_name=true, x_input_include_action=true, x_input_include_mood=false):
```json
{"role": "assistant", "content": "Lydia: I think we should be careful. [Follow > Player]"}
```

Format patterns based on settings:
- Name always: `"Lydia: message"`
- With mood: `"Lydia (concerned): message"`
- With action: `"Lydia: message [Follow > Player]"`
- With mood+action: `"Lydia (concerned): message [Follow > Player]"`
- Dialogue only: `"Lydia: message"`

### Step 5: Dynamic content reinsertion

The extracted dynamic content is inserted as a user message near the end
of the message sequence, before the final instruction message:

```
system: [static bio + actions]              <- STABLE (cacheable)
user: old dialogue                          <- STABLE
assistant: old dialogue (now clean text)    <- STABLE
...more turns...                            <- STABLE
user: recent dialogue                       <- changes each request
user: [dynamic context block]              <- changes each request
user: [format instruction]                 <- stable (or replaced for simple format)
```

### Step 6: Output instruction rewriting (optional)

If `x_output_format` is `simple`, the proxy finds the last user message
(the JSON template instruction from CHIM) and replaces it with a
simple format instruction:

Before:
```
Use ONLY this JSON object to give your answer: {"character":"Lydia","listener":"specify who...","mood":"choose exactly one mood...","action":"Talk|Attack|Follow|...","target":"action target actor...","message":"lines of dialogue"}
```

After:
```
Begin your response by noting your emotional state, who you're speaking to,
intended action, action target in parentheses like this: (mood)(listener)(action)(target),
then provide your dialogue. Valid moods: neutral,happy,sad,...
Example: (neutral)(Player)(Talk)(Player) I'm worried about that cave we passed.
```

The proxy also removes `"response_format": {"type": "json_object"}` from
the request body (since the model should NOT be constrained to JSON output).

### Step 7: Forward to upstream

The cleaned request is forwarded to the upstream URL. The upstream is
determined by:
1. The URL in the original request's destination (the proxy just forwards)
2. OR a configured upstream_url in proxy config (for fixed routing)

Headers are passed through. The `Authorization` header from CHIM is
preserved for upstream authentication.

### Step 8: Response streaming

**If `x_output_format` is `vanilla`**: SSE chunks pass through unchanged.
CHIM's `openrouterjson.process()` handles them normally.

**If `x_output_format` is `simple`**: The proxy intercepts the SSE stream:
1. Accumulates text deltas from `choices[0].delta.content`
2. Detects the metadata prefix: `(mood)(listener)(action)(target)`
3. Extracts the fields
4. Reconstructs a JSON response: `{"character":"Lydia","listener":"Player","mood":"concerned","action":"Talk","target":"Player","message":"I think we should be careful."}`
5. Emits it as OpenAI-format SSE chunks with the JSON in `delta.content`
6. CHIM's `openrouterjson.process()` receives valid JSON as usual

## Cache Optimization Details

### Why automatic caching needs help

Provider automatic caching (Anthropic, OpenAI, Gemini) caches identical
message prefixes. But CHIM's system prompt mixes static and dynamic
content, so the prefix changes every request. Result: 0% cache hits.

### What the proxy does

By moving dynamic content out of the system prompt and into a late user
message, the system prompt becomes stable. Combined with stable old
dialogue (which doesn't change between requests), the message prefix
grows monotonically and stays identical across requests.

Expected cache hit pattern:
- Request 1: cache MISS (cold start)
- Request 2+: cache HIT on system prompt + old dialogue prefix
- Only the recent tail (last N messages + dynamic context) is uncached

### Claude subscription proxy compatibility

When `x_upstream_type` is `claude_proxy`:
- The format proxy does NOT add `cache_control` markers
- The Claude proxy's existing position-based caching handles marker placement
- The format proxy's restructuring makes the Claude proxy's caching MORE
  effective (because the prefix is now actually stable)
- No temp files are needed (the Claude proxy uses position-based caching
  for multi-message requests, which is what the format proxy produces)

When `x_upstream_type` is `direct`:
- The format proxy can optionally add `cache_control` markers itself
- Placed at: end of system message, and at `len(messages) - uncached_count - 1`

## Configuration

### CHIM UI Settings (stored in connector metadata, sent as extra_parameters)

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `x_input_format` | select | `clean_text` | `vanilla` (pass through) or `clean_text` (rewrite assistant msgs) |
| `x_input_include_name` | boolean | `true` | Prefix NPC name: `"Lydia: message"` |
| `x_input_include_mood` | boolean | `false` | Include mood: `"Lydia (concerned): message"` |
| `x_input_include_action` | boolean | `true` | Include action: `"message [Follow > Player]"` |
| `x_input_include_listener` | boolean | `false` | Include listener: `"(to Player) message"` |
| `x_output_format` | select | `vanilla` | `vanilla` (JSON pass-through) or `simple` (parenthetical format) |
| `x_output_include_mood` | boolean | `true` | Include `(mood)` in simple output |
| `x_output_include_action` | boolean | `true` | Include `(action)` in simple output |
| `x_output_include_target` | boolean | `true` | Include `(target)` in simple output |
| `x_output_include_listener` | boolean | `true` | Include `(listener)` in simple output |
| `x_custom_system_instruction` | string | `""` | Appended to system prompt (after bio/actions, before dynamic context) |
| `x_custom_last_instruction` | string | `""` | Inserted as user message before format instruction (strongest recency position) |
| `x_toggle_thinking` | boolean | `false` | Enable extended thinking/reasoning. Replaces CHIM's reasoning_model settings. |
| `x_thinking_tokens` | integer | `1024` | Thinking token budget. Per-model minimums enforced (e.g. Claude ≥ 1024). |
| `x_effort_level` | select | `"low"` | Reasoning effort: `minimal`, `low`, `medium`, `high`, `max`. Both effort and token budget are sent; model uses what it supports. |
| `x_upstream_type` | select | `direct` | `direct` (proxy handles caching) or `claude_proxy` (defer caching to Claude proxy) |
| `x_proxy_port` | integer | `38800` | Port the format proxy listens on |

### Proxy Config File (proxy_config.yaml)

```yaml
# Pattern that marks where static content ends and dynamic content begins
# in the system prompt. First match = split point.
dynamic_split_pattern: "^#+ *(Environmental Context|Additional Information|Current Status)"

# Additional subsection patterns to extract even if they appear
# in the static region (e.g., Equipment inside a character bio block)
dynamic_subsections:
  - "^### Equipment"
  - "^### Combat Vitals"
  - "^### Arousal Status"
  - "^### Cleanliness"

# Number of recent messages to leave outside the cache prefix
# Only used when x_upstream_type=direct
uncached_count: 5

# Default upstream URL (can be overridden per-request by CHIM's URL field)
# Not usually needed — the proxy forwards to whatever URL CHIM targeted
# upstream_url: https://openrouter.ai/api/v1/chat/completions

# Logging
log_level: INFO
log_file: logs/format_proxy.log
```

Adding a new CHIM system prompt section = one line in `dynamic_subsections`.

### How Config Reloads Work

The proxy re-reads `proxy_config.yaml` on SIGHUP or via a `/api/config/reload`
endpoint. No restart needed.

## Auto-Start Mechanism

### Primary: Connector health-check-and-spawn (automatic)

The proxy runs inside WSL alongside CHIM. In
`openrouterjsonreformat.__construct()`:

1. Check if `proxy/chim_format_proxy.py` exists (not installed = no-op)
2. Ping `http://127.0.0.1:{port}/health` with 500ms timeout
3. If healthy, return immediately
4. Read PID from `temp/format_proxy.pid`, check if alive
5. If not running, try `exec("nohup python3 ... &")`
6. If spawn fails, log warning (graceful degradation)

Since both the PHP connector and the proxy run inside the same WSL
instance, `exec()` from PHP works reliably and the process persists.

### Manual control from Windows

- `start.bat` — starts the proxy in WSL via `wsl -d {distro} nohup ...`
- `stop.bat` — kills the proxy via PID file
- `install.bat` — copies files into WSL, installs Python deps

### Graceful degradation

If the proxy is down, the connector is still `openrouterjson`. If the URL
points to the dead proxy, CHIM's existing fallback connector logic handles
it (error → try fallback connector if configured).

## File Inventory

### New files

| File | Lines | Description |
|------|-------|-------------|
| `connector/openrouterjsonreformat.php` | ~85 | Thin connector extending openrouterjson + auto-start |
| `proxy/chim_format_proxy.py` | ~830 | The format proxy |
| `proxy/proxy_config.yaml` | ~34 | Configurable section patterns |
| `proxy/requirements.txt` | ~4 | Python dependencies |
| `install.bat` | — | Windows: copies files into WSL, installs deps |
| `start.bat` | — | Windows: starts proxy in WSL background |
| `stop.bat` | — | Windows: stops proxy |

### Upstream edits (CHIM 3.0.0)

| File | Change | Lines |
|------|--------|-------|
| `lib/core/llm_connector.class.php` | Add `elseif` in `setOldGlobals()` | +45 |
| `ui/core/llm_connectors.php` | Add `<option>` to driver dropdown | +1 |
| `conf/conf_schema.json` | Add to CONNECTORS + new connector section | +70 |

### Files NOT modified

- `connector/openrouterjson.php` — inherited, not forked
- `lib/data_functions.php` — no changes needed
- `lib/chat_helper_functions.php` — no changes needed
- `prompts/dialogue_prompt.php` — no changes needed
- `main.php` — no changes needed
- `functions/json_response.php` — no changes needed

## Response Stream Conversion (simple -> JSON)

When `x_output_format=simple`, the proxy must convert the model's
simple-format response back to JSON that `openrouterjson.process()` expects.

### Accumulation strategy

The proxy accumulates SSE text deltas into a buffer. It watches for
the metadata prefix pattern: `(value)(value)(value)(value) message text`

State machine:
1. **ACCUMULATING_METADATA**: Collecting `(...)` groups from start of response
2. **STREAMING_MESSAGE**: Metadata parsed; now streaming message text

Once metadata is parsed, the proxy constructs a JSON object and begins
emitting it as SSE chunks:

```
# Model outputs:  (concerned)(Player)(Talk)(Player) I think we should be careful.
# Proxy emits SSE chunks:
data: {"choices":[{"delta":{"content":"{\"character\":"}}]}
data: {"choices":[{"delta":{"content":"\"Lydia\",\"listener\":\"Player\","}}]}
data: {"choices":[{"delta":{"content":"\"mood\":\"concerned\",\"action\":\"Talk\","}}]}
data: {"choices":[{"delta":{"content":"\"target\":\"Player\",\"message\":\""}}]}
data: {"choices":[{"delta":{"content":"I think we should"}}]}
data: {"choices":[{"delta":{"content":" be careful.\"}"}}]}
data: [DONE]
```

The metadata fields are emitted as a JSON prefix, then the message text
streams through in real-time, and the closing `"}` is appended at stream end.

### Extracting character name

The proxy needs the NPC name for the `"character"` JSON field. Sources:
1. The system prompt (first message, role=system) usually starts with the NPC name
2. CHIM sets `$GLOBALS["HERIKA_NAME"]` but this isn't in the HTTP request
3. The proxy can extract it from the system prompt or from a `x_character_name`
   field (added automatically by the setOldGlobals bridge)

## Testing Strategy

### Manual testing
1. Configure CHIM with `openrouterjsonreformat` driver pointing at proxy
2. Start a conversation with an NPC
3. Check `logs/format_proxy.log` for request/response transformation
4. Verify NPC responds naturally (input rewriting working)
5. Toggle between vanilla and simple output format
6. Check `context_sent_to_llm.log` on CHIM side for what was sent

### Proxy standalone testing
The proxy can be tested without CHIM by sending curl requests:
```bash
curl -X POST http://127.0.0.1:38800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"anthropic/claude-sonnet-4-20250514","messages":[...],"x_input_format":"clean_text"}'
```

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Proxy adds latency | Minimal — just string processing, no LLM calls. <5ms overhead. |
| Proxy crashes mid-stream | Connector falls back; CHIM retries or uses fallback connector. |
| CHIM adds new system prompt sections | Config-driven patterns — add one line to yaml, no code change. |
| Claude proxy interferes with restructuring | `x_upstream_type=claude_proxy` skips cache marker placement. |
| Simple format parsing fails | Proxy falls through to raw text; CHIM gets non-JSON and errors gracefully. |
| openrouterjson.php changes in CHIM update | Connector extends it, doesn't fork. Only `setOldGlobals()` block needs review. |
