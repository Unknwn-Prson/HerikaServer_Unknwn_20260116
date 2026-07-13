# CHIM Format Proxy — Reading List for Next Session

Read these files in this order to get full context.

## 1. Continuation Notes (start here)
- `dist/chim_format_proxy/CONTINUATION_NOTES.md`
  - Project status, what works, prioritized TODO list

## 2. Architecture
- `dist/chim_format_proxy/DESIGN.md`
  - Full architecture: data flow, components, cache optimization, Claude proxy compatibility

## 3. The Proxy (core logic)
- `dist/chim_format_proxy/proxy/dialogue_cache.py` (~160 lines)
  - Per-character JSONL dialogue accumulator (hash dedup, trim, age expiry)
  - `accumulate_and_expand()` — main entry point, replaces rolling window with full cache
  - `clear_cache()` — per-character cache clear
- `dist/chim_format_proxy/proxy/chim_format_proxy.py` (~1050 lines)
  - The FastAPI proxy. Key sections:
    - `extract_settings()` — x_* config extraction from request body
    - `split_system_prompt()` — static/dynamic content split
    - `rewrite_assistant_message()` — JSON to clean text conversion
    - `build_simple_format_instruction()` / `get_enabled_output_fields()` — output format
    - `apply_custom_system_instruction()` / `insert_custom_last_instruction()` — custom prompts
    - `apply_reasoning_config()` / `_is_openai_reasoning()` — thinking/reasoning control
    - `convert_simple_stream_to_json()` — SSE stream conversion (simple→JSON)
    - `_build_json_prefix()` / `FIELD_DEFAULTS` — JSON reconstruction with defaults
    - `chat_completions()` — main request handler (the full pipeline)
    - `_log_request()` / `_logging_stream_wrapper()` — 4-type request logging
- `dist/chim_format_proxy/proxy/proxy_config.yaml`
  - Config-driven section extraction patterns (dynamic_split_pattern, dynamic_subsections)

## 4. CHIM Integration (PHP side)
- `dist/chim_format_proxy/connector/openrouterjsonreformat.php` (~78 lines)
  - Thin connector extending openrouterjson + auto-start health check
- `dist/chim_format_proxy/proxy/apply_patches.py` (~400 lines)
  - Auto-patcher for 3 CHIM files. Key sections:
    - `CONNECTOR_PATCH_BLOCK` — the setOldGlobals() PHP block (URL construction, x_* bridge)
    - `FORMAT_PROXY_UI` — the HTML settings panel injected into connector editor
    - `FORMAT_PROXY_METADATA_KEYS` — metadata save handler additions
    - `FORMAT_PROXY_JS` — show/hide JS for the settings panel

## 5. CHIM 3.0.0 Reference (in WSL, read via `powershell -Command "wsl -d DwemerAI4Skyrim3 ..."`)
These are the upstream files the proxy interacts with:
- `/var/www/html/HerikaServer/connector/openrouterjson.php` — the parent connector class (1472 lines)
  - `open()` (line ~288) — how context is assembled and sent
  - `process()` (line ~923) — how responses are parsed (JSON extraction, LAST_LLM_RESPONSE)
  - `processActions()` (line ~1098) — how actions are extracted
- `/var/www/html/HerikaServer/lib/core/llm_connector.class.php` — setOldGlobals() and getConnector()
- `/var/www/html/HerikaServer/functions/json_response.php` — the JSON response template (all fields)
- `/var/www/html/HerikaServer/lib/chat_helper_functions.php` — unmoodSentence(), asterisk handling
- `/var/www/html/HerikaServer/prompts/dialogue_prompt.php` — TEMPLATE_DIALOG prompt construction

## 6. Distribution / Installation
- `dist/chim_format_proxy/install.bat` — Windows installer (copies to WSL, installs deps, runs patcher)
- `dist/chim_format_proxy/start.bat` / `stop.bat` — Manual proxy control

## 7. Legacy Reference (the old cached connector, for understanding lineage)
- `dist/openrouterjsoncached_v1.7.8/openrouterjsoncached_v1.7.8_CHIM2.4.3/CHANGELOG.txt`
- `dist/openrouterjsoncached_v1.7.8/openrouterjsoncached_v1.7.8_CHIM2.4.3/connector/openrouterjsoncached.php`
  - The features we're porting: custom prompts, thinking toggle, asterisk preservation
  - `_openPart2()` — custom_system_instruction and custom_last_instruction injection
  - `_openPart4()` — toggle_thinking, thinking_tokens, effort_level reasoning config

## 8. Claude Subscription Proxy (for compatibility context)
- `C:\Users\Jean\Desktop\Skyrim CHIM\chim_proxy_v0.16.4\README.md`
- `C:\Users\Jean\Desktop\Skyrim CHIM\chim_proxy_v0.16.4\chim_proxy_v1.py`
  - How it does MITM rewriting, caching, turn splitting
  - Understanding needed for x_upstream_type=claude_proxy compatibility

## 9. Related deliverable — separate CHIM core bug (not proxy code)
- `C:\GitHub\HerikaServer_Unknwn_20260116\dist\chim_npc_bio_leak_fix\BUG_REPORT.md`
  - The NPC biography leak in `lib/core/npc_master.class.php` `setOldGlobalsFromCurrentNpcData()`
  - Seven `HERIKA_*` globals leak intra-request (isset-without-else); The Narrator's values
    contaminate NPCs whose columns are NULL. minAI is the messenger, not the cause.
- `C:\GitHub\HerikaServer_Unknwn_20260116\dist\chim_npc_bio_leak_fix\apply_npc_bio_leak_fix.py`
- `C:\GitHub\HerikaServer_Unknwn_20260116\dist\chim_npc_bio_leak_fix\apply_npc_bio_leak_fix.bat`
  - Idempotent standalone patcher — dry-run verified, not yet applied to live CHIM.
