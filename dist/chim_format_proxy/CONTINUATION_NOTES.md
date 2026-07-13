---
name: chim-format-proxy-v0.1.2
description: CHIM Format Proxy project status and continuation notes
type: project
originSessionId: eb9dd7bb-fd2a-4dc6-b2da-e032e25f2ebd
---
# CHIM Format Proxy — Continuation Notes

## Location
- Source repo: `C:\GitHub\HerikaServer_Unknwn_20260116\dist\chim_format_proxy\`
- Installed to WSL (DwemerAI4Skyrim3): `/var/www/html/HerikaServer/proxy/`
- Design doc: `dist/chim_format_proxy/DESIGN.md`
- Reading list: `dist/chim_format_proxy/READING_LIST.md`
- Separate deliverable this session: `dist/chim_npc_bio_leak_fix/` (unrelated CHIM core bug patcher)

## Status: Working prototype, iterating

## Deployment state (important for next session)
- **Repo version:** `v0.1.2` (`VERSION` const, line 15 of `chim_format_proxy.py`)
- **Deployed version:** `v0.1.0` (header/const only — code body is otherwise identical to repo after this session's edit)
- Confirmed by `diff` at end of session: **only** lines 2 and 15 differ (version string).
- Consider bumping the deployed header to match, or re-installing at some point.

### Change applied to BOTH files but proxy **not yet restarted**
- `_log_request` at line ~837 now sanitizes preview content:
  ```python
  content = str(content).replace("\r", "").replace("\n", "⏎")
  ```
- Purpose: make `requests.log` previews single-line and unambiguous (see "Log artifact" investigation below).
- **Requires a proxy restart to take effect** (Python long-running process — unlike PHP under apache2, code is loaded once). Run `stop.bat` then `start.bat`.
- Deployed file already `py_compile`d clean.

## What works
- Proxy starts, receives requests, forwards to upstream
- Install.bat copies files to WSL, installs deps, auto-patches CHIM
- CHIM UI shows Format Proxy Settings panel when `driver=openrouterjsonreformat`
- URL split: user enters upstream URL, `setOldGlobals` constructs proxy URL
- 4-type request logging (RAW_INPUT, TRANSFORMED_INPUT, RAW_OUTPUT, TRANSFORMED_OUTPUT)
- System prompt static/dynamic split (config-driven patterns in `proxy_config.yaml`)
- Assistant message rewriting (JSON → clean text)
- Custom prompts: `x_custom_system_instruction` (appended to system) and `x_custom_last_instruction` (before format instruction)
- Reasoning/thinking: `x_toggle_thinking`, `x_thinking_tokens` (Anthropic), `x_effort_level` (OpenAI). Proxy strips CHIM's reasoning and applies its own. CHIM's `reasoning_model` is set from `x_toggle_thinking` for timeout handling only.
- Priority 1 transforms verified functional
- **Content preservation verified this session**: reproduced deployed `split_system_prompt` on real 22,274-char input → static 20,261 + dynamic 2,009, only 4 whitespace chars trimmed at boundaries. Full content forwarded upstream.

## Session accomplishments

### 1. Asterisk stripping (was Priority 4) — RESOLVED as configuration
The prior note framed this as a proxy/connector fix. Investigation showed **CHIM 3 already has a complete Narrator subsystem** that handles this properly. Not a proxy problem, not a code problem.

- **Global settings** (`conf_schema.json`, `userlvl: basic`, all in CHIM's config UI):
  - `INLINE_NARRATION_MODE`: `disabled` / `narrator` / `npc`
    - `narrator` → separate "The Narrator" TTS voice speaks the `*asterisked*` parts (`chat_helper_functions.php` `returnLines()` splits them out via `extractNarrationAndDialogue()`, calls `callConfiguredTts`, emits `The Narrator|ScriptQueue|...`)
    - `npc` → NPC keeps the whole line
    - `disabled` → strip asterisks from TTS (old lossy behavior; default)
  - `REMOVE_ASTERISKS_FROM_NPC_OUTPUT` — filter `*narration*` from NPC speech + subtitles
  - `REMOVE_ASTERISKS_FROM_PLAYER_INPUT` — same for player
- **`PRESERVE_ASTERISKS_IN_CONTEXT`** — keep asterisks in context buffer fed back to LLM (`data_functions.php:5013`, `chat_helper_functions.php:914`). NOT in `conf_schema.json`; managed via Narrator management UI + per-profile/per-NPC metadata.
- **Multi-layer, single owner:** these settings are managed by (a) global config UI, (b) `core_profiles.class.php:289`, (c) `npc_master.class.php:821`, (d) `narrator.class.php:316` + `ui/core/narrator_management.php`. Both `core_profiles` and `npc_master` have a `$narratorManagedKeys` exclusion list — they explicitly `continue` (skip) these keys when applying profile/NPC metadata to globals. CHIM deliberately fences them.
- **Verified by unit tests** (`unittests/tests/AsteriskParsingTest.php`):
  - filter=true: `*smiles* Hello there` → TTS `Hello there`, subtitle `Hello there`
  - filter=false: `*smiles* Hello there` → TTS `smiles Hello there`, subtitle `*smiles* Hello there` (preserved)

**Proxy-side audit** (also completed this session — no code changes needed):
- `convert_simple_stream_to_json` (line ~661): metadata regex `^\s*\(([^)]*)\)...\s*` only matches leading `(field)(field)...` groups; everything after (including any `*narration*`) streams verbatim into the JSON `message` field.
- `_json_escape` (line ~796): escapes only `\ " \n \r \t`. Asterisks untouched.
- `rewrite_assistant_message` (line ~275): copies `data["message"]` verbatim into the clean-text line.
- Vanilla path: pure SSE pass-through.
- **Conclusion:** proxy preserves narration end-to-end. Any loss is entirely CHIM-side, resolved by user config.

**Follow-up for user (documentation only, not code):** to preserve narration when using the format proxy, set `INLINE_NARRATION_MODE=narrator` (or `npc`) + `REMOVE_ASTERISKS_FROM_NPC_OUTPUT=false` at whichever CHIM layer you prefer (global config UI is easiest).

### 2. NPC biography leak — new bug, patcher delivered, NOT YET APPLIED
User found hidden "Behavioral patterns" and "Speech style" injected into Brelyna Maryon's prompt (didn't match Brelyna's DB record or `combined_bio_templates`; text nowhere in the DB except log tables).

**Root cause** (CHIM core, `lib/core/npc_master.class.php` → `setOldGlobalsFromCurrentNpcData()`, ~line 745):
```php
if (isset($currentNpcData['personality'])) {
    $GLOBALS['HERIKA_PERSONALITY'] = $currentNpcData['personality'];
}
// no else — global not cleared when field is NULL
```
`isset(NULL) === false` → when an NPC's column is NULL, the global is neither set nor cleared. The **Narrator's** value (set earlier in the same request by `narrator.class.php:387` `loadCharacterIntoGlobals()`) persists into the NPC's prompt, where minAI's `ext/minai_plugin/contextbuilders/context_modules/core_context.php` `BuildPersonalityContext()` emits it under `#### Behavioral patterns` / `#### Speech style`.

**Mechanism is intra-request.** CHIM runs PHP per-request under apache2/mod_php (verified: no persistent PHP process). No cross-request "ghost." Original diagnosis mentioning "resident-process ghost" corrected mid-session. The old DB-vs-log mismatch (log showed a longer version of the leaked text than the current `core_narrator.personality`) is explained simply by the user editing `core_narrator` *after* the last logged session.

**Consistency point:** the same function *does* unconditionally clear `HERIKA_RELATIONSHIPS` (`unset()`) and the `PATCH_OVERRIDE_VOICE` / `TTS_NPC_*` globals (explicit `else { unset() }`). Seven biography fields were missed:
`HERIKA_BACKGROUND, HERIKA_PERSONALITY, HERIKA_OCCUPATION, HERIKA_APPEARANCE, HERIKA_SKILLS, HERIKA_SPEECHSTYLE, HERIKA_GOALS`.

**minAI's role:** consumer only. `core_context.php` faithfully renders whatever core hands it. Fixing minAI would be the wrong layer — every reader of those globals is exposed.

**Deliberately NOT patched:** `PROMPT_HEAD`, `OGHMA_KNOWLEDGE`. Same pattern, but clearing them risks removing required prompt structure rather than an optional bio section. Flagged in the bug report as related-but-out-of-scope.

**Deliverables (`dist/chim_npc_bio_leak_fix/`):**
- `apply_npc_bio_leak_fix.py` — idempotent patcher; regex-based, tolerant of whitespace; per-field replacement with a `NPC_BIO_LEAK_FIX` marker for skip-detection; makes its own `.npcbiofix.bak` backup; aborts without writing if a critical field (personality/speechstyle) isn't found (drift safety).
- `apply_npc_bio_leak_fix.bat` — Windows launcher (mirrors `install.bat`'s WSL distro detection).
- `BUG_REPORT.md` — dense, upstream-ready.

**Verification done** (against a `/tmp/npctest/` copy — **NOT on live CHIM**):
- 7/7 fields patched cleanly.
- `php -l` passes on the result.
- Re-run → `[SKIP] Already patched`.
- Idempotency confirmed.

**Status: awaiting user decision to apply.** Original recommendation was `1 + 2`:
1. Immediate DB mitigation: `UPDATE core_npc_master SET personality='', speechstyle='', occupation='', appearance='', skills='', goals='', npc_static_bio=COALESCE(npc_static_bio,'') WHERE personality IS NULL OR ...` — because `isset('') === true` sets the global to `''`, which `core_context` skips (empty check on `trim(...)`).
2. Durable code fix via `apply_npc_bio_leak_fix.bat`.
Neither has been executed. User has not yet approved application.

**Live evidence for the next session** (recorded during investigation):
- `core_npc_master.personality` and `.speechstyle` for Brelyna Maryon (id=130) are `NULL`.
- `core_narrator.personality` currently reads `Detached, descriptive, witty, helpful.` (short; the log had the longer variant from before the user's edit).
- Global text/varchar/jsonb search across all `public` schema columns found the injected string ONLY in `log.prompt` and `audit_request.request` (prompt logs — output surfaces, not sources).

### 3. Prompt-drop investigation — CONFIRMED not a bug (log artifact fixed)
User flagged `TRANSFORMED_INPUT [0]` in `requests.log` ending at "**Voice and " with no `... [N chars total]` suffix (implying the content was genuinely ~197 chars, not 500-char preview-truncated).

**Content is preserved.** Proof chain:
- Pulled the real 22,274-char raw system prompt from the latest `audit_request` and ran the *deployed* `split_system_prompt` against it (with the deployed `proxy_config.yaml`): static = **20,261**, dynamic = **2,009**. Sum = 22,270 vs input 22,274 → **only 4 whitespace chars** trimmed at boundaries (`.rstrip()`/`.strip()`).
- Simulated the exact `_log_request` truncation on that same static — output correctly contains `**Voice and Format**\r\n\r\nRespond using inline third-per...` at the expected offset. Code + content produce the correct 500-char preview.
- Model outputs are richly in-character and context-aware — only possible if the full system prompt reached upstream.
- All 12 recent `audit_request` rows measured have `sys_len` in 22,114–22,400 (full).

**Then why does the log entry look cut?** Not fully diagnosed — the file bytes really do end at "**Voice and \n" for that specific entry (confirmed by `xxd`), even though the same content head is written correctly for `RAW_INPUT`. Most likely a concurrent-write / `\r`-adjacent write anomaly in async logging. Given content is provably intact, deferred as low-priority; sanitization change below makes future previews unambiguous regardless.

### 4. Log artifact fix (applied)
- `_log_request` sanitizes newlines/CRs in each message preview before length-check:
  ```python
  content = str(content).replace("\r", "").replace("\n", "⏎")
  ```
- One-line, one-place change at ~line 837 of `chim_format_proxy.py`.
- Applied to **both** repo and deployed. Only the version-string diff remains.
- **Restart the proxy** to activate on the deployed side.

## Open items / observations for next session

### Priority: apply the NPC bio leak fix
- User approved creation of the deliverable but has not yet run it.
- Suggested sequence: DB mitigation (data-level, survives CHIM updates), then run `apply_npc_bio_leak_fix.bat` (durable code fix, idempotent, safe to re-run after CHIM updates).
- Recommend upstreaming the bug report at some point — permanent fix, zero maintenance.

### Priority: restart the format proxy
- To activate the `_log_request` sanitization on the deployed side. Not urgent; purely cosmetic. `stop.bat` + `start.bat`.

### Potential output-side bug (noticed but not investigated)
- While reading the `requests.log` tail I saw a `TRANSFORMED_OUTPUT` block ending with **three** trailing `"}` sequences:
  ```
  ...cold cheese.\"}\"}\"}"}
  ```
  Expected: one `"}` (close `message` string + close JSON object) + the outer wrapper's `"}`. Three suggests the SSE stream converter is emitting the closing `"}` chunk more than once.
- Suspect: `convert_simple_stream_to_json` yields `_make_sse_chunk('"}')` on **both** finish_reason (line ~716) **and** `[DONE]` (line ~697), and possibly re-enters via non-content chunks. Worth checking that only one closing chunk is emitted per stream.
- **Not confirmed to affect CHIM's parsing** — CHIM likely tolerates trailing garbage after JSON, but this is an easy win and produces a cleaner log.

### Version bump / redeploy
- Deployed header says `v0.1.0` but the deployed code is functionally the repo's `v0.1.2` (plus this session's `_log_request` edit). Consider either (a) bumping the deployed header for accuracy, or (b) tagging the repo `v0.1.3` to reflect the sanitization change and re-installing.

### Someday: smarter output format
- All CHIM JSON fields are available as `()` toggles but only 4 enabled by default.
- Item/amount only matter for non-Talk actions.
- A smarter format could use conditional fields based on action type. For now, all-parenthetical works.

## Architecture summary (unchanged this session)
- `connector/openrouterjsonreformat.php` extends `openrouterjson`, changes `$this->name`, auto-starts proxy via health check + `nohup`.
- `setOldGlobals()` patch: constructs proxy URL from upstream URL + port, injects `x_*` settings into `extra_parameters`.
- `apply_patches.py`: idempotent patcher that modifies 3 CHIM files (`llm_connector.class.php`, `llm_connectors.php`, `conf_schema.json`).
- Proxy is stateless — all config per-request from `x_*` fields in body.
- `start.bat` uses `start /min wsl` to keep proxy alive in minimized window.

## Corrections to earlier session's notes
- Prior note claimed asterisk stripping strips text between asterisks entirely, losing narration from TTS. That framing was from CHIM 2.4.3. In CHIM 3 the behavior is per-`INLINE_NARRATION_MODE`, and even `disabled` mode's `formatNpcSpeechText` keeps the words (drops only the asterisks) — a subtly different failure mode than described.
- Prior priority label "Priority 4" for asterisks is closed as configuration.

## CHIM version
- Target: CHIM 3.0.0 (aiagent branch, DwemerAI4Skyrim3 WSL)
- The old cached connector was for CHIM 2.4.3 — priority mapping / behavior claims from that era should not be trusted without verification against CHIM 3.

## Key file paths for next session
- Deployed proxy: `/var/www/html/HerikaServer/proxy/chim_format_proxy.py`
- Deployed config: `/var/www/html/HerikaServer/proxy/proxy_config.yaml`
- CHIM DB (Postgres): `host=localhost dbname=dwemer user=dwemer password=dwemer` (from `lib/postgresql.class.php:8`)
- CHIM narrator personality data: `core_narrator` table (key-value: `id`, `value`)
- Per-NPC data: `core_npc_master` table
- Character bio templates (bundled defaults): `combined_bio_templates`
- Proxy request log (debug preview): `/var/www/html/HerikaServer/proxy/logs/requests.log`
- CHIM's own prompt log (with `<br />` HTML formatting — not byte-faithful for reproduction): `log.prompt` (DB)
- Wire-faithful raw CHIM→proxy request (double-JSON-encoded string): `audit_request.request` (DB)

## Investigation tooling gotchas encountered
- The `mcp__ccw__bash` wrapper runs commands via `bash -c`, which interacts with PowerShell quoting. When invoking `wsl` from PowerShell, complex quoting/regex/pipes/parentheses in inner commands frequently break. Reliable patterns:
  - Write short scripts to a Windows-side file (repo dir), then run via `wsl -- python3 /mnt/c/...` or `wsl -- bash /mnt/c/...`.
  - Use `grep -F` (fixed strings) with a pattern file (`grep -f patterns.txt`) instead of alternation in-line.
  - For SQL, write to a `.sql` file and run `psql -f /mnt/c/...`.
  - Avoid `2>/dev/null` on the PowerShell side — PowerShell interprets `/dev/null` as a path.
  - Set `PGPASSWORD` inside a `bash -c '...'` wrapper; don't try to export it from PowerShell.
- For log inspection: use `sed -n L1,L2p | xxd` to see raw bytes including `\r` and control characters. `cat -A` shows `^M` for `\r` and `$` for `\n`.
