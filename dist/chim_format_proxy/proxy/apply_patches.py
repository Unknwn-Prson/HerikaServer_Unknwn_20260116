#!/usr/bin/env python3
"""
CHIM Format Proxy — Auto-patcher
Applies the three CHIM patches needed to register the openrouterjsonreformat connector.
Safe to run multiple times (idempotent — skips already-patched files).

Run from WSL:  python3 apply_patches.py /var/www/html/HerikaServer
"""

import json
import re
import shutil
import sys
from pathlib import Path

MARKER = "openrouterjsonreformat"


def backup(path: Path):
    """Create a .bak backup if one doesn't already exist."""
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"  Backup: {bak.name}")


# ---------------------------------------------------------------
# Patch 1: lib/core/llm_connector.class.php
# Insert a new elseif block in setOldGlobals() for our driver
# ---------------------------------------------------------------

CONNECTOR_PATCH_BLOCK = '''
        // --- BEGIN FORMAT PROXY PATCH ---
        } else if ($currentConnectorData["driver"] == "openrouterjsonreformat") {

            $apiBadge = new ApiBadge();
            $apiKeyData = $apiBadge->getById($currentConnectorData["api_badge_id"]);

            // URL: user enters the upstream URL (e.g. https://openrouter.ai/api/v1/chat/completions)
            // We construct the proxy URL by prepending the proxy address with ?upstream=
            $upstreamUrl = $currentConnectorData["url"] ?? 'https://openrouter.ai/api/v1/chat/completions';
            $metadata_temp = json_decode($currentConnectorData['metadata'] ?? '{}', true);
            $proxyPort = $metadata_temp['x_proxy_port'] ?? '38800';
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["url"] = "http://127.0.0.1:{$proxyPort}/v1/chat/completions?upstream=" . urlencode($upstreamUrl);
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["model"] = $currentConnectorData["model"] ?? 'anthropic/claude-sonnet-4-20250514';
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["PROVIDER"] = $currentConnectorData["provider"] ?? '';
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["reasoning_model"] = $currentConnectorData["reasoning_model"] ?? false;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["max_tokens"] = $currentConnectorData["max_tokens"] ?? '1024';
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["temperature"] = $currentConnectorData["temperature"] ?? 1.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["presence_penalty"] = $currentConnectorData["presence_penalty"] ?? 0.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["frequency_penalty"] = $currentConnectorData["frequency_penalty"] ?? 0.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["repetition_penalty"] = $currentConnectorData["repetition_penalty"] ?? 1.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["top_p"] = $currentConnectorData["top_p"] ?? 1.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["top_k"] = $currentConnectorData["top_k"] ?? 0.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["min_p"] = $currentConnectorData["min_p"] ?? 0.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["top_a"] = $currentConnectorData["top_a"] ?? 0.0;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["ENFORCE_JSON"] = $currentConnectorData["enforce_json"] ?? true;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["PREFILL_JSON"] = $currentConnectorData["prefill_json"] ?? false;
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["API_KEY"] = $apiKeyData["api_key"];
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["json_schema"] = $currentConnectorData["json_schema"] ?? false;

            $metadata = json_decode($currentConnectorData['metadata'] ?? '{}', true);
            if (is_array($metadata)) {
                foreach ($metadata as $key => $value) {
                    $GLOBALS["CONNECTOR"]["openrouterjsonreformat"][$key] = $value;
                }
            }

            // Bridge: inject x_* format settings into extra_parameters so
            // openrouterjson's open() includes them in the HTTP request body
            $formatKeys = [
                'x_input_format', 'x_input_include_name', 'x_input_include_mood',
                'x_input_include_action', 'x_input_include_listener',
                'x_output_format', 'x_output_include_mood', 'x_output_include_action',
                'x_output_include_target', 'x_output_include_listener',
                'x_output_include_emotion', 'x_output_include_emotion_intensity',
                'x_output_include_item', 'x_output_include_amount', 'x_output_include_lang',
                'x_upstream_type', 'x_proxy_port', 'x_upstream_url',
                'x_custom_system_instruction', 'x_custom_last_instruction',
                'x_toggle_thinking', 'x_thinking_tokens', 'x_effort_level',
                'x_dialogue_cache_enabled', 'x_dialogue_cache_max_turns',
                'x_dialogue_cache_max_age', 'x_dialogue_cache_fresh_threshold',
                'x_dialogue_cache_uncached_count',
            ];
            $formatParams = [];
            foreach ($formatKeys as $fk) {
                if (isset($GLOBALS["CONNECTOR"]["openrouterjsonreformat"][$fk])) {
                    $formatParams[$fk] = $GLOBALS["CONNECTOR"]["openrouterjsonreformat"][$fk];
                }
            }
            if (isset($GLOBALS["HERIKA_NAME"])) {
                $formatParams["x_character_name"] = $GLOBALS["HERIKA_NAME"];
            }
            if (!empty($formatParams)) {
                $existingExtra = $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["extra_parameters"] ?? [];
                if (!is_array($existingExtra)) {
                    $existingExtra = [];
                }
                $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["extra_parameters"] = array_merge($existingExtra, $formatParams);
                $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["extra_parameters_enabled"] = true;
            }

            // Reasoning: proxy handles thinking/reasoning entirely.
            // Set reasoning_model based on x_toggle_thinking so CHIM uses
            // longer timeout (90s vs 30s) and larger buffer when thinking is on.
            // CHIM's own reasoning params are stripped by the proxy.
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["reasoning_model"] =
                !empty($GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["x_toggle_thinking"]);
            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["disable_model_reasoning"] = true;

            // WORKAROUND: openrouterjson.open() hardcodes "openrouterjson" instead of
            // $this->name for the PROVIDER lookup (lines 719, 1312). Copy our provider
            // settings into that namespace so the hardcoded lookup finds them.
            if (!empty($GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["PROVIDER"])) {
                $GLOBALS["CONNECTOR"]["openrouterjson"]["PROVIDER"] = $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["PROVIDER"];
            }
        // --- END FORMAT PROXY PATCH ---
'''


def patch_llm_connector(herika: Path) -> bool:
    path = herika / "lib" / "core" / "llm_connector.class.php"
    if not path.exists():
        print(f"  [SKIP] {path} not found")
        return False

    content = path.read_text(encoding="utf-8")
    if MARKER in content:
        print(f"  [SKIP] Already patched")
        return True

    # Find insertion point: just before the google_openaijson elseif
    anchor = '} else if ($currentConnectorData["driver"] == "google_openaijson")'
    pos = content.find(anchor)
    if pos == -1:
        print(f"  [ERROR] Could not find google_openaijson anchor in setOldGlobals()")
        return False

    # Walk back to find the start of this line (we want to insert before it)
    line_start = content.rfind("\n", 0, pos)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1  # skip the newline itself

    # The anchor line starts with "        } else if..."
    # Our patch block ends with the closing of our elseif, then the anchor
    # should follow naturally. We need to replace the "} else if" at the anchor
    # with our block which ends with its own "}" and then the original continues.

    # Insert our block before the anchor line
    backup(path)
    new_content = content[:line_start] + CONNECTOR_PATCH_BLOCK + "\n" + content[line_start:]
    path.write_text(new_content, encoding="utf-8")
    print(f"  [OK] Inserted setOldGlobals() block ({len(CONNECTOR_PATCH_BLOCK.splitlines())} lines)")
    return True


# ---------------------------------------------------------------
# Patch 2: ui/core/llm_connectors.php
# A) Add <option> to ALL driver dropdowns
# B) Add format proxy settings UI (HTML + PHP) after existing toggles
# C) Add x_* keys to the metadata save handler
# D) Add JS to show/hide settings based on driver selection
# ---------------------------------------------------------------

# HTML block for the format proxy settings panel.
# Inserted after the "Remove Action Prompt" toggle in the embedded editor.
# The div is hidden by default; JS shows it when driver=openrouterjsonreformat.
FORMAT_PROXY_UI = r'''
            <!-- BEGIN DIALOGUE CACHE SETTINGS -->
            <div class="format-proxy-settings" style="display:none; margin-top:16px; padding:12px; border:1px solid #3a5a3a; border-radius:8px; background:#1a2e1a;">
                <div style="font-weight:600; color:#4ade80; margin-bottom:10px;">Dialogue Cache</div>
                <?php
                $fpm_dc = [];
                if (isset($editItem["metadata"]) && !empty($editItem["metadata"])) {
                    $fpm_dc = is_string($editItem["metadata"]) ? json_decode($editItem["metadata"], true) : $editItem["metadata"];
                    if (!is_array($fpm_dc)) $fpm_dc = [];
                }
                ?>
                <div style="font-size:11px; color:#8b8; margin-bottom:8px;">Accumulates dialogue across requests so the message prefix stays stable for automatic provider caching. Without this, CHIM's rolling context window defeats caching entirely.</div>

                <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='Enable the persistent dialogue cache. When on, old dialogue is preserved across requests instead of being dropped from the rolling window. This is what makes provider auto-caching work.'>Enable Dialogue Cache</span>
                    <input type="hidden" name="x_dialogue_cache_enabled" value="0">
                    <input type="checkbox" name="x_dialogue_cache_enabled" value="1" <?= (!isset($fpm_dc['x_dialogue_cache_enabled']) || $fpm_dc['x_dialogue_cache_enabled']) ? 'checked' : '' ?>>
                </label>

                <div style="margin-top:8px;">
                    <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='Maximum dialogue turns to keep in cache. When exceeded, oldest turns are trimmed from the front. Higher = more context for the LLM but larger requests.'>Max Cached Turns</span></label>
                    <input type="number" name="x_dialogue_cache_max_turns" value="<?= htmlspecialchars($fpm_dc['x_dialogue_cache_max_turns'] ?? '200') ?>" min="10" max="1000" style="width:100px; margin-bottom:8px;">

                    <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='Seconds before cache is considered stale and cleared. Matches typical provider cache TTL. Default 3600 (1 hour).'>Max Cache Age (seconds)</span></label>
                    <input type="number" name="x_dialogue_cache_max_age" value="<?= htmlspecialchars($fpm_dc['x_dialogue_cache_max_age'] ?? '3600') ?>" min="60" max="86400" style="width:100px; margin-bottom:8px;">

                    <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='If CHIM sends this many or fewer dialogue turns, the cache is cleared (assumes new conversation/game session). Default 3.'>Fresh Conversation Threshold</span></label>
                    <input type="number" name="x_dialogue_cache_fresh_threshold" value="<?= htmlspecialchars($fpm_dc['x_dialogue_cache_fresh_threshold'] ?? '3') ?>" min="1" max="20" style="width:100px; margin-bottom:8px;">

                    <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='Number of recent messages left outside the cache prefix. These messages are NOT marked as cached, so regenerations and edits to recent turns cause a cache miss only on the tail, not the entire history. Default 5.'>Uncached Message Count</span></label>
                    <input type="number" name="x_dialogue_cache_uncached_count" value="<?= htmlspecialchars($fpm_dc['x_dialogue_cache_uncached_count'] ?? '5') ?>" min="1" max="20" style="width:100px;">
                </div>

                <div style="margin-top:12px; padding-top:10px; border-top:1px solid #3a5a3a;">
                    <button type="button" onclick="(function(btn){
                        var port = btn.closest('.format-proxy-settings')?.querySelector('[name=x_proxy_port]')?.value
                            || document.querySelector('[name=x_proxy_port]')?.value || '38800';
                        if(!confirm('Clear ALL dialogue caches? This cannot be undone.')) return;
                        btn.disabled=true; btn.textContent='Clearing...';
                        fetch('http://127.0.0.1:'+port+'/api/cache/clear-all',{method:'POST'})
                            .then(function(r){return r.json()})
                            .then(function(d){btn.textContent='Cleared!'; setTimeout(function(){btn.disabled=false; btn.textContent='Clear All Caches';},2000);})
                            .catch(function(e){btn.textContent='Error: '+e.message; btn.disabled=false;});
                    })(this)" style="background:#4a2020; color:#f88; border:1px solid #833; border-radius:4px; padding:5px 12px; cursor:pointer; font-size:12px;">Clear All Caches</button>
                    <span style="font-size:11px; color:#666; margin-left:8px;">Resets accumulated dialogue for all characters.</span>
                </div>
            </div>
            <!-- END DIALOGUE CACHE SETTINGS -->

            <!-- BEGIN FORMAT PROXY SETTINGS -->
            <div class="format-proxy-settings" style="display:none; margin-top:16px; padding:12px; border:1px solid #3a3a5a; border-radius:8px; background:#1a1a2e;">
                <div style="font-weight:600; color:#ffb862; margin-bottom:10px;">Format Proxy Settings</div>
                <?php
                $fpm = [];
                if (isset($editItem["metadata"]) && !empty($editItem["metadata"])) {
                    $fpm = is_string($editItem["metadata"]) ? json_decode($editItem["metadata"], true) : $editItem["metadata"];
                    if (!is_array($fpm)) $fpm = [];
                }
                ?>

                <div style="font-weight:500; color:#aab; margin:8px 0 6px;">Context History Rewriting</div>

                <label style="display:block; margin-bottom:6px;"><span class='tip-label' data-tip='How past NPC dialogue appears in context. clean_text rewrites JSON into natural text like "Lydia: message [Follow > Player]". Improves response quality.'>Input Format</span></label>
                <select name="x_input_format" style="margin-bottom:8px; width:100%;">
                    <option value="clean_text" <?= ($fpm['x_input_format'] ?? 'clean_text') === 'clean_text' ? 'selected' : '' ?>>Clean Text (Recommended)</option>
                    <option value="vanilla" <?= ($fpm['x_input_format'] ?? '') === 'vanilla' ? 'selected' : '' ?>>Vanilla (JSON pass-through)</option>
                </select>

                <div style="margin-left:8px;">
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='Prefix NPC name: "Lydia: message"'>Include NPC Name</span>
                        <input type="hidden" name="x_input_include_name" value="0">
                        <input type="checkbox" name="x_input_include_name" value="1" <?= (!isset($fpm['x_input_include_name']) || $fpm['x_input_include_name']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='Include mood: "Lydia (concerned): message"'>Include Mood</span>
                        <input type="hidden" name="x_input_include_mood" value="0">
                        <input type="checkbox" name="x_input_include_mood" value="1" <?= !empty($fpm['x_input_include_mood']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='Include non-Talk actions: "message [Follow > Player]"'>Include Actions</span>
                        <input type="hidden" name="x_input_include_action" value="0">
                        <input type="checkbox" name="x_input_include_action" value="1" <?= (!isset($fpm['x_input_include_action']) || $fpm['x_input_include_action']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='Include listener: "(to Player) message"'>Include Listener</span>
                        <input type="hidden" name="x_input_include_listener" value="0">
                        <input type="checkbox" name="x_input_include_listener" value="1" <?= !empty($fpm['x_input_include_listener']) ? 'checked' : '' ?>>
                    </label>
                </div>

                <div style="height:16px;"></div>
                <div style="font-weight:500; color:#aab; margin:0 0 6px;">LLM Output Format</div>

                <label style="display:block; margin-bottom:6px;"><span class='tip-label' data-tip='What format the LLM responds in. Simple uses (field)(field)... format with fewer tokens. The proxy converts it back to JSON for CHIM. Disabled fields get default values.'>Output Format</span></label>
                <select name="x_output_format" style="margin-bottom:8px; width:100%;">
                    <option value="vanilla" <?= ($fpm['x_output_format'] ?? 'vanilla') === 'vanilla' ? 'selected' : '' ?>>Vanilla (JSON)</option>
                    <option value="simple" <?= ($fpm['x_output_format'] ?? '') === 'simple' ? 'selected' : '' ?>>Simple (parenthetical)</option>
                </select>

                <div style="margin-left:8px; font-size:12px; color:#888; margin-bottom:6px;">Fields the LLM produces (disabled fields get defaults):</div>
                <div style="margin-left:8px;">
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(mood) — NPC emotional state for animations'>Mood</span>
                        <input type="hidden" name="x_output_include_mood" value="0">
                        <input type="checkbox" name="x_output_include_mood" value="1" <?= (!isset($fpm['x_output_include_mood']) || $fpm['x_output_include_mood']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(listener) — who the NPC is speaking to'>Listener</span>
                        <input type="hidden" name="x_output_include_listener" value="0">
                        <input type="checkbox" name="x_output_include_listener" value="1" <?= (!isset($fpm['x_output_include_listener']) || $fpm['x_output_include_listener']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(action) — Talk, Follow, Attack, etc.'>Action</span>
                        <input type="hidden" name="x_output_include_action" value="0">
                        <input type="checkbox" name="x_output_include_action" value="1" <?= (!isset($fpm['x_output_include_action']) || $fpm['x_output_include_action']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(target) — who/what the action targets'>Target</span>
                        <input type="hidden" name="x_output_include_target" value="0">
                        <input type="checkbox" name="x_output_include_target" value="1" <?= (!isset($fpm['x_output_include_target']) || $fpm['x_output_include_target']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(emotion) — TTS emotion category. Default: empty'>Emotion (TTS)</span>
                        <input type="hidden" name="x_output_include_emotion" value="0">
                        <input type="checkbox" name="x_output_include_emotion" value="1" <?= !empty($fpm['x_output_include_emotion']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(emotion_intensity) — low|moderate|strong. Default: empty'>Emotion Intensity (TTS)</span>
                        <input type="hidden" name="x_output_include_emotion_intensity" value="0">
                        <input type="checkbox" name="x_output_include_emotion_intensity" value="1" <?= !empty($fpm['x_output_include_emotion_intensity']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(item) — item name for GiveItemTo/CastSpell/etc. Default: empty'>Item</span>
                        <input type="hidden" name="x_output_include_item" value="0">
                        <input type="checkbox" name="x_output_include_item" value="1" <?= !empty($fpm['x_output_include_item']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(amount) — quantity for SpawnItem/SpawnGold/etc. Default: empty'>Amount</span>
                        <input type="hidden" name="x_output_include_amount" value="0">
                        <input type="checkbox" name="x_output_include_amount" value="1" <?= !empty($fpm['x_output_include_amount']) ? 'checked' : '' ?>>
                    </label>
                    <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='(lang) — language code for XTTS. Default: empty'>Language (XTTS)</span>
                        <input type="hidden" name="x_output_include_lang" value="0">
                        <input type="checkbox" name="x_output_include_lang" value="1" <?= !empty($fpm['x_output_include_lang']) ? 'checked' : '' ?>>
                    </label>
                </div>

                <div style="height:16px;"></div>
                <div style="font-weight:500; color:#aab; margin:0 0 6px;">Custom Prompts</div>

                <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='Appended to the end of the system prompt (after character bio/actions, before dynamic context). Use for persistent instructions, persona reinforcement, or custom rules that apply every request.'>Custom System Instruction</span></label>
                <textarea name="x_custom_system_instruction" rows="3" style="width:100%; margin-bottom:8px; font-size:12px;"><?= htmlspecialchars($fpm['x_custom_system_instruction'] ?? '') ?></textarea>

                <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='Inserted as a user message just before the response format instruction. The LLM sees this last, giving it the strongest influence on the response. Use for per-request steering, tone guidance, or scenario-specific instructions.'>Custom Last Instruction</span></label>
                <textarea name="x_custom_last_instruction" rows="3" style="width:100%; margin-bottom:8px; font-size:12px;"><?= htmlspecialchars($fpm['x_custom_last_instruction'] ?? '') ?></textarea>

                <div style="height:16px;"></div>
                <div style="font-weight:500; color:#aab; margin:0 0 6px;">Reasoning / Thinking</div>
                <div style="font-size:11px; color:#666; margin-bottom:8px;">Replaces CHIM's Reasoning Model settings. The proxy controls reasoning parameters directly.</div>

                <label class="label-with-toggle" style="display:block; margin:4px 0;"><span class='tip-label' data-tip='Enable extended thinking/reasoning. The LLM will reason internally before responding, improving quality for complex situations at the cost of latency and tokens. Only affects models that support reasoning.'>Enable Thinking</span>
                    <input type="hidden" name="x_toggle_thinking" value="0">
                    <input type="checkbox" name="x_toggle_thinking" value="1" <?= !empty($fpm['x_toggle_thinking']) ? 'checked' : '' ?>>
                </label>

                <div style="margin-left:8px; margin-top:4px;">
                    <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='Maximum thinking token budget. Models that support token-budgeted reasoning will use this value. Per-model minimums are enforced automatically (e.g. Claude requires at least 1024).'>Thinking Token Budget</span></label>
                    <input type="number" name="x_thinking_tokens" value="<?= htmlspecialchars($fpm['x_thinking_tokens'] ?? '1024') ?>" min="1" max="65536" style="width:120px; margin-bottom:8px;">

                    <label style="display:block; margin-bottom:4px;"><span class='tip-label' data-tip='Reasoning effort level. Models that support effort-based reasoning will use this value. Both effort and token budget are sent; the model uses whichever it supports.'>Effort Level</span></label>
                    <select name="x_effort_level" style="width:120px;">
                        <option value="minimal" <?= ($fpm['x_effort_level'] ?? '') === 'minimal' ? 'selected' : '' ?>>Minimal</option>
                        <option value="low" <?= ($fpm['x_effort_level'] ?? 'low') === 'low' ? 'selected' : '' ?>>Low</option>
                        <option value="medium" <?= ($fpm['x_effort_level'] ?? '') === 'medium' ? 'selected' : '' ?>>Medium</option>
                        <option value="high" <?= ($fpm['x_effort_level'] ?? '') === 'high' ? 'selected' : '' ?>>High</option>
                        <option value="max" <?= ($fpm['x_effort_level'] ?? '') === 'max' ? 'selected' : '' ?>>Max</option>
                    </select>
                </div>

                <div style="height:16px;"></div>
                <div style="font-weight:500; color:#aab; margin:0 0 6px;">Proxy Connection</div>

                <label style="display:block; margin-bottom:6px;"><span class='tip-label' data-tip='What is downstream. direct = proxy places cache markers. claude_proxy = defer caching to Claude subscription proxy.'>Upstream Type</span></label>
                <select name="x_upstream_type" style="margin-bottom:8px; width:100%;">
                    <option value="direct" <?= ($fpm['x_upstream_type'] ?? 'direct') === 'direct' ? 'selected' : '' ?>>Direct (OpenRouter/etc)</option>
                    <option value="claude_proxy" <?= ($fpm['x_upstream_type'] ?? '') === 'claude_proxy' ? 'selected' : '' ?>>Claude Subscription Proxy</option>
                </select>

                <label style="display:block; margin:4px 0;"><span class='tip-label' data-tip='Port the format proxy listens on. Default 38800.'>Proxy Port</span></label>
                <input type="number" name="x_proxy_port" value="<?= htmlspecialchars($fpm['x_proxy_port'] ?? '38800') ?>" min="1024" max="65535" style="width:100px;">

                <div style="margin-top:8px; font-size:11px; color:#666;">The URL field above should be your upstream API endpoint (e.g. https://openrouter.ai/api/v1/chat/completions). The proxy address is constructed automatically from the port.</div>
            </div>
            <!-- END FORMAT PROXY SETTINGS -->
'''

# Keys to add to the metadata save handler
FORMAT_PROXY_METADATA_KEYS = [
    ('x_input_format', 'string'),
    ('x_input_include_name', 'bool'),
    ('x_input_include_mood', 'bool'),
    ('x_input_include_action', 'bool'),
    ('x_input_include_listener', 'bool'),
    ('x_output_format', 'string'),
    ('x_output_include_mood', 'bool'),
    ('x_output_include_action', 'bool'),
    ('x_output_include_target', 'bool'),
    ('x_output_include_listener', 'bool'),
    ('x_output_include_emotion', 'bool'),
    ('x_output_include_emotion_intensity', 'bool'),
    ('x_output_include_item', 'bool'),
    ('x_output_include_amount', 'bool'),
    ('x_output_include_lang', 'bool'),
    ('x_upstream_type', 'string'),
    ('x_proxy_port', 'string'),
    ('x_custom_system_instruction', 'string'),
    ('x_custom_last_instruction', 'string'),
    ('x_toggle_thinking', 'bool'),
    ('x_thinking_tokens', 'string'),
    ('x_effort_level', 'string'),
    ('x_dialogue_cache_enabled', 'bool'),
    ('x_dialogue_cache_max_turns', 'string'),
    ('x_dialogue_cache_max_age', 'string'),
    ('x_dialogue_cache_fresh_threshold', 'string'),
    ('x_dialogue_cache_uncached_count', 'string'),
]

# JS snippet to show/hide format proxy settings based on driver.
# Appended to existing driver change handlers.
FORMAT_PROXY_JS = r'''
    // --- BEGIN FORMAT PROXY JS ---
    function updateFormatProxyVisibility() {
        // Use querySelectorAll because there are two editor forms (main + embedded)
        // each with their own driver_input and format_proxy_settings panel
        document.querySelectorAll('.format-proxy-settings').forEach(function(panel) {
            // Find the driver_input within the same form ancestor
            var form = panel.closest('form') || panel.parentElement;
            var driverInput = form ? form.querySelector('[name="driver"]') : document.getElementById('driver_input');
            if (driverInput) {
                panel.style.display = (driverInput.value === 'openrouterjsonreformat') ? '' : 'none';
            }
        });
    }
    // Hook into driver select changes
    document.querySelectorAll('#driver_select, [name="driver"]').forEach(function(el) {
        el.addEventListener('change', updateFormatProxyVisibility);
    });
    // Hook into service icon clicks
    document.querySelectorAll('.service-icon').forEach(function(icon) {
        icon.addEventListener('click', function() { setTimeout(updateFormatProxyVisibility, 50); });
    });
    // Watch for driver_input value changes via attribute mutation
    document.querySelectorAll('[name="driver"]').forEach(function(el) {
        new MutationObserver(updateFormatProxyVisibility).observe(el, {attributes:true});
    });
    // Initial state + periodic recheck (catches iframe load timing)
    setTimeout(updateFormatProxyVisibility, 100);
    setTimeout(updateFormatProxyVisibility, 500);
    setTimeout(updateFormatProxyVisibility, 1500);
    // --- END FORMAT PROXY JS ---
'''


def patch_llm_connectors_ui(herika: Path) -> bool:
    path = herika / "ui" / "core" / "llm_connectors.php"
    if not path.exists():
        print(f"  [SKIP] {path} not found")
        return False

    content = path.read_text(encoding="utf-8")
    if MARKER in content:
        print(f"  [SKIP] Already patched")
        return True

    backup(path)
    patches_applied = 0

    # --- Part A: Add <option> to ALL driver dropdowns ---
    anchor = '<option value="player2json">'
    positions = []
    start = 0
    while True:
        pos = content.find(anchor, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1

    if not positions:
        print(f"  [ERROR] Could not find player2json option")
        return False

    for pos in reversed(positions):
        line_end = content.find("\n", pos)
        if line_end == -1:
            line_end = len(content)
        line_start = content.rfind("\n", 0, pos) + 1
        anchor_line = content[line_start:line_end]
        indent = anchor_line[:len(anchor_line) - len(anchor_line.lstrip())]
        option = f'{indent}<option value="openrouterjsonreformat">OpenRouter JSON (Format Proxy)</option>'
        content = content[:line_end + 1] + option + "\n" + content[line_end + 1:]
    print(f"  [OK] Added driver option to {len(positions)} dropdown(s)")
    patches_applied += 1

    # --- Part B: Add settings UI panel after "Remove Action Prompt" toggles ---
    # Find the closing </div> of remove_action_prompt sections and insert after
    # We need to find the embedded editor's version (there may be two)
    ui_anchor = "Remove Action Prompt</span>"
    ui_positions = []
    start = 0
    while True:
        pos = content.find(ui_anchor, start)
        if pos == -1:
            break
        ui_positions.append(pos)
        start = pos + 1

    for pos in reversed(ui_positions):
        # Find the closing </div> of the remove_action_prompt container
        # Pattern: after the checkbox, there's </label>\n</div>
        search_from = pos
        # Find the parent </div> that closes the remove_action_prompt block
        # Look for "</label>\n            </div>" pattern
        close_label = content.find("</label>", search_from)
        if close_label == -1:
            continue
        close_div = content.find("</div>", close_label)
        if close_div == -1:
            continue
        insert_pos = close_div + len("</div>")
        content = content[:insert_pos] + "\n" + FORMAT_PROXY_UI + content[insert_pos:]

    if ui_positions:
        print(f"  [OK] Added settings panel to {len(ui_positions)} editor form(s)")
        patches_applied += 1
    else:
        print(f"  [WARN] Could not find Remove Action Prompt anchor for settings panel")

    # --- Part C: Add x_* keys to metadata save handler ---
    save_anchor = "return $metadata;\n}"
    save_pos = content.find(save_anchor)
    if save_pos != -1:
        insert_code = "\n    // --- BEGIN FORMAT PROXY METADATA ---\n"
        for key, typ in FORMAT_PROXY_METADATA_KEYS:
            if typ == 'bool':
                insert_code += f'    if (isset($post["{key}"])) {{\n'
                insert_code += f'        $metadata["{key}"] = ($post["{key}"] === "1" || $post["{key}"] === 1);\n'
                insert_code += f'    }} else {{\n'
                insert_code += f'        unset($metadata["{key}"]);\n'
                insert_code += f'    }}\n'
            else:
                insert_code += f'    if (isset($post["{key}"]) && $post["{key}"] !== "") {{\n'
                insert_code += f'        $metadata["{key}"] = $post["{key}"];\n'
                insert_code += f'    }} else {{\n'
                insert_code += f'        unset($metadata["{key}"]);\n'
                insert_code += f'    }}\n'
        insert_code += "    // --- END FORMAT PROXY METADATA ---\n"

        content = content[:save_pos] + insert_code + "\n    " + content[save_pos:]
        print(f"  [OK] Added {len(FORMAT_PROXY_METADATA_KEYS)} keys to metadata save handler")
        patches_applied += 1
    else:
        print(f"  [WARN] Could not find metadata save handler")

    # --- Part D: Add JS for show/hide ---
    # Append a <script> block at the very end of the file.
    # PHP files can have raw HTML after ?> — it gets output directly.
    # If file doesn't end with ?>, the JS goes inside a PHP echo.
    # But the simplest safe approach: just append after everything.
    # This works because the embedded editor partial returns HTML directly,
    # and the main page outputs a buffer then exits.
    content += '\n<script>\n' + FORMAT_PROXY_JS + '\n</script>\n'
    print(f"  [OK] Added driver-based show/hide JS")
    patches_applied += 1

    path.write_text(content, encoding="utf-8")
    return patches_applied > 0


# ---------------------------------------------------------------
# Patch 3: conf/conf_schema.json
# A) Add "openrouterjsonreformat" to CONNECTORS values array
# B) Add new connector section
# ---------------------------------------------------------------

CONNECTOR_SCHEMA = {
    "_title": "OpenRouter API (Format Proxy)",
    "url": {"type": "url", "description": "Format proxy URL. Should be: <code>http://127.0.0.1:38800/v1/chat/completions?upstream=YOUR_UPSTREAM_URL</code><br>For OpenRouter: <code>?upstream=https://openrouter.ai/api/v1/chat/completions</code><br>For Claude proxy: <code>?upstream=http://127.0.0.1:38700/v1/chat/completions</code>"},
    "model": {"type": "ormodellist", "description": "LLM model to use. Passed through to the upstream API.", "helpurl": "https://openrouter.ai/models"},
    "x_input_format": {"type": "select", "values": ["clean_text", "vanilla"], "userlvl": "basic", "description": "<strong>Input format</strong> — how past NPC dialogue appears in context history.<br><strong>clean_text:</strong> (Recommended) Rewrites JSON assistant messages into natural text like <code>Lydia: I'll follow you. [Follow > Player]</code>. Improves response quality.<br><strong>vanilla:</strong> Pass through unchanged."},
    "x_input_include_name": {"type": "boolean", "userlvl": "basic", "description": "Include NPC name prefix: <code>Lydia: message</code>. Always recommended."},
    "x_input_include_mood": {"type": "boolean", "userlvl": "basic", "description": "Include mood: <code>Lydia (concerned): message</code>."},
    "x_input_include_action": {"type": "boolean", "userlvl": "basic", "description": "Include non-Talk actions: <code>message [Follow > Player]</code>."},
    "x_input_include_listener": {"type": "boolean", "userlvl": "basic", "description": "Include listener: <code>(to Player) message</code>."},

    "x_output_format": {"type": "select", "values": ["vanilla", "simple"], "userlvl": "basic", "description": "<strong>Output format</strong> — what format the LLM responds in.<br><strong>vanilla:</strong> Standard CHIM JSON. Proxy passes through.<br><strong>simple:</strong> Lightweight <code>(mood)(listener)(action)(target) dialogue</code>. Proxy converts back to JSON for CHIM."},
    "x_output_include_mood": {"type": "boolean", "userlvl": "basic", "description": "Include <code>(mood)</code> in simple output format."},
    "x_output_include_action": {"type": "boolean", "userlvl": "basic", "description": "Include <code>(action)</code> in simple output format."},
    "x_output_include_target": {"type": "boolean", "userlvl": "basic", "description": "Include <code>(target)</code> in simple output format."},
    "x_output_include_listener": {"type": "boolean", "userlvl": "basic", "description": "Include <code>(listener)</code> in simple output format."},

    "x_custom_system_instruction": {"type": "string", "userlvl": "basic", "description": "Appended to the system prompt after character bio/actions. Use for persistent instructions, persona reinforcement, or custom rules."},
    "x_custom_last_instruction": {"type": "string", "userlvl": "basic", "description": "Inserted as a user message just before the format instruction. Strongest recency-bias position for steering the response."},

    "x_toggle_thinking": {"type": "boolean", "userlvl": "basic", "description": "Enable extended thinking/reasoning. Replaces CHIM's Reasoning Model settings. The proxy controls reasoning parameters directly."},
    "x_thinking_tokens": {"type": "integer", "userlvl": "pro", "description": "Thinking token budget. Per-model minimums enforced automatically (e.g. Claude requires 1024)."},
    "x_effort_level": {"type": "select", "values": ["minimal", "low", "medium", "high", "max"], "userlvl": "pro", "description": "Reasoning effort level. Both effort and token budget are sent; the model uses whichever it supports."},

    "x_dialogue_cache_enabled": {"type": "boolean", "userlvl": "basic", "description": "Enable dialogue cache. Accumulates dialogue across requests for stable caching prefix."},
    "x_dialogue_cache_max_turns": {"type": "integer", "userlvl": "pro", "description": "Max dialogue turns to cache. Default 200."},
    "x_dialogue_cache_max_age": {"type": "integer", "userlvl": "pro", "description": "Cache age limit in seconds. Default 3600 (1 hour)."},
    "x_dialogue_cache_fresh_threshold": {"type": "integer", "userlvl": "pro", "description": "Clear cache if CHIM sends this many or fewer turns (new conversation detection). Default 3."},
    "x_dialogue_cache_uncached_count": {"type": "integer", "userlvl": "basic", "description": "Recent messages left outside the cache prefix. Handles regenerations without invalidating the full cache. Default 5."},

    "x_upstream_type": {"type": "select", "values": ["direct", "claude_proxy"], "userlvl": "pro", "description": "What is downstream.<br><strong>direct:</strong> Proxy handles cache markers.<br><strong>claude_proxy:</strong> Defer caching to Claude proxy."},
    "x_proxy_port": {"type": "integer", "userlvl": "pro", "description": "Format proxy port. Default: 38800."},

    "fallback_models": {"type": "string", "userlvl": "wip", "description": "Fallback models (comma-separated).", "helpurl": "https://openrouter.ai/docs/features/model-routing#the-models-parameter"},
    "PROVIDER": {"type": "string", "userlvl": "pro", "description": "Manual provider selection (comma-separated, enforced).", "helpurl": "https://openrouter.ai/docs/features/provider-routing#ordering-specific-providers"},
    "providers_sort": {"type": "select", "values": ["default", "price", "throughput", "latency"], "userlvl": "wip", "description": "Provider sort strategy."},
    "providers_to_ignore": {"type": "string", "userlvl": "wip", "description": "Providers to ignore (comma-separated)."},
    "provider_quantizations": {"type": "string", "userlvl": "wip", "description": "Quantization filter (comma-separated)."},
    "provider_max_price_input": {"type": "number", "userlvl": "wip", "description": "Max input price per million tokens."},
    "provider_max_price_output": {"type": "number", "userlvl": "wip", "description": "Max output price per million tokens."},
    "max_tokens": {"type": "integer", "description": "Maximum tokens to generate."},
    "temperature": {"type": "number", "description": "Temperature [0-2]"},
    "presence_penalty": {"userlvl": "pro", "type": "number", "description": "Presence Penalty [(-2)-2]"},
    "frequency_penalty": {"userlvl": "pro", "type": "number", "description": "Frequency Penalty [(-2)-2]"},
    "repetition_penalty": {"userlvl": "pro", "type": "number", "description": "Repetition Penalty [0-2]"},
    "top_p": {"userlvl": "pro", "type": "number", "description": "Top_P [0-1]"},
    "top_k": {"userlvl": "pro", "type": "number", "description": "Top_K [0-100]"},
    "min_p": {"userlvl": "pro", "type": "number", "description": "Min_P [0-1]"},
    "top_a": {"userlvl": "pro", "type": "number", "description": "Top_A [0-1]"},
    "ENFORCE_JSON": {"type": "boolean", "description": "Enforce JSON output. Only used when Output Format is 'vanilla'."},
    "PREFILL_JSON": {"type": "boolean", "userlvl": "pro", "description": "Prefill JSON response. Only used when Output Format is 'vanilla'."},
    "MAX_TOKENS_MEMORY": {"type": "integer", "userlvl": "wip", "description": "No longer used."},
    "API_KEY": {"type": "apikey", "description": "API key for the upstream service.", "code": "OPENAI_API_KEY"},
    "xreferer": {"userlvl": "wip", "type": "string", "description": "Stub header. Keep default."},
    "xtitle": {"userlvl": "wip", "type": "string", "description": "Stub header. Keep default."},
    "json_schema": {"type": "boolean", "userlvl": "pro", "description": "Enable structured output schema. Only when Output Format is 'vanilla'."}
}


def patch_conf_schema(herika: Path) -> bool:
    path = herika / "conf" / "conf_schema.json"
    if not path.exists():
        print(f"  [SKIP] {path} not found")
        return False

    content = path.read_text(encoding="utf-8")

    # Parse JSON (conf_schema.json may have trailing commas or quirks,
    # but CHIM's is generally clean JSON)
    try:
        schema = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  [ERROR] Could not parse conf_schema.json: {e}")
        return False

    changed = False

    # Part A: Add to CONNECTORS values array
    if "CONNECTORS" in schema:
        values = schema["CONNECTORS"].get("values", [])
        if MARKER not in values:
            # Insert after "openrouterjson"
            if "openrouterjson" in values:
                idx = values.index("openrouterjson") + 1
                values.insert(idx, MARKER)
            else:
                values.append(MARKER)
            schema["CONNECTORS"]["values"] = values
            changed = True
            print(f"  [OK] Added '{MARKER}' to CONNECTORS values")
        else:
            print(f"  [SKIP] CONNECTORS values already contains '{MARKER}'")

    # Part B: Add connector section
    if "CONNECTOR" in schema:
        connector = schema["CONNECTOR"]
        if MARKER not in connector:
            connector[MARKER] = CONNECTOR_SCHEMA
            changed = True
            print(f"  [OK] Added '{MARKER}' connector section")
        else:
            print(f"  [SKIP] Connector section already exists")

    if changed:
        backup(path)
        # Write with consistent formatting
        new_content = json.dumps(schema, indent=2, ensure_ascii=False)
        path.write_text(new_content, encoding="utf-8")
        print(f"  [OK] conf_schema.json updated")

    return True


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 apply_patches.py /path/to/HerikaServer")
        sys.exit(1)

    herika = Path(sys.argv[1])
    if not herika.exists():
        print(f"[ERROR] HerikaServer directory not found: {herika}")
        sys.exit(1)

    print(f"CHIM Format Proxy — Applying patches to {herika}")
    print()

    print("[1/3] Patching lib/core/llm_connector.class.php ...")
    ok1 = patch_llm_connector(herika)

    print("[2/3] Patching ui/core/llm_connectors.php ...")
    ok2 = patch_llm_connectors_ui(herika)

    print("[3/3] Patching conf/conf_schema.json ...")
    ok3 = patch_conf_schema(herika)

    print()
    if ok1 and ok2 and ok3:
        print("All patches applied successfully!")
        print("Backups saved as .bak files (only on first patch run).")
    else:
        print("Some patches could not be applied. See errors above.")

    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    sys.exit(main())
