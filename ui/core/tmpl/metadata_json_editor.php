<!-- Javascript stuff to bring up a json editor for the metadata/override -->
<?php
// Build a visual editor for common metadata keys using conf schema
$schemaPath = __DIR__ . "/../../../conf/conf_schema.json";
$confSchema = [];
if (file_exists($schemaPath)) {
    $confSchema = json_decode(file_get_contents($schemaPath), true);
}

// Local overrides for visual metadata schema (decouple UI copy from conf_schema)
// These entries will be used instead of conf_schema when rendering visual controls
$localSchemaOverrides = [
    'RECHAT_H' => [
        'type' => 'integer',
        'description' => "Rechat Rounds. Higher values will increase the amount of times AI NPC's will go back-and-forth during a conversation. 1 = 1 Round | 2 = 2 Rounds | 3 = 3 Rounds etc",
    ],
    'RECHAT_P' => [
        'type' => 'integer',
        'description' => 'Rechat Probability. Chance that an AI NPC will continue an ongoing conversation. 0 = Never | 50 = 50% | 100 = Always',
    ],
    'CORE_LANG' => [
        'type' => 'select',
        'description' => 'Custom Language. The lang folder is in the CHIM Server. Leave it blank for English.',
    ],
    'MINIME_T5' => [
        'type' => 'boolean',
        'description' => "Enable Minime-T5 LLM. Helps dumber LLM's be more accurate with action and memory functions. Must be installed in the CHIM Launcher. Only works for English!",
    ],
    'AUTO_DIARY' => [
        'type' => 'boolean',
        'description' => 'Automatically create diary entries for all current followers when sleeping. Wait events are controlled by AUTO_DIARY_WAIT setting.',
    ],
    'BORED_EVENT' => [
        'type' => 'integer',
        'description' => 'Bored Event Probability. Chance of an AI NPC starting a random conversation every couple of minutes.0 = Never | 50 = 50% | 100 = Always',
    ],
    'DIARY_PROMPT' => [
        'type' => 'longstring',
        'description' => 'Default profile only! Instructions for generating diary entries. You can adjust max tokens by changing MAX_TOKENS_MEMORY for the DIARY connector you are using.',
    ],
    'OGHMA_AMOUNT' => [
        'type' => 'select',
        'values' => ['1','2','3'],
        'description' => 'Number of Oghma keywords to extract from each response. More keyword extraction will mean longer response times.',
    ],
    'LANG_LLM_XTTS' => [
        'type' => 'boolean',
        'description' => 'XTTS Only! Will offer a language field to LLM, and will try match to XTTSv2 language.',
    ],
    'QUEST_COMMENT' => [
        'type' => 'boolean',
        'description' => 'Will trigger AI (NPCs and Narrator) to talk about new objectives in your current active quest. Will trigger a lot of events on a new character, so leave disabled until you complete the tutorial!',
    ],
    'DIARY_COOLDOWN' => [
        'type' => 'integer',
        'description' => 'Cooldown in seconds between sleep/wait-triggered diary entries. Only applies when Diary Generation Mode includes sleep_wait or both. Has no effect on event-count-based diaries.',
    ],
    'COMBAT_BARK_COOLDOWN' => [
        'type' => 'integer',
        'description' => 'Cooldown period in seconds between combat barks to prevent spam during combat. This cooldown is global across all NPCs in the party.',
    ],
    'OGHMA_INFINIUM' => [
        'type' => 'boolean',
        'description' => "Needs Minime-T5 enabled and running. Tamriel lore information will be added to the prompt, enhancing their understanding on specific topics.",
    ],
    'INJECT_DIARIES' => [
        'type' => 'boolean',
        'description' => 'Inject relevant past diary entries into NPC conversation context alongside memory injection.',
    ],
    'DIARY_THRESHOLD_MODIFIER' => [
        'type' => 'number',
        'description' => 'Controls how picky the system is when recalling past diaries during conversation. Higher = only very relevant diaries are recalled (fewer, more on-topic). Lower = broader recall (more diaries, but may include less relevant ones). Range: -0.25 (very loose) to 0.5 (very strict). Default: 0.',
    ],
    'DIARY_MIN_AGE_HOURS' => [
        'type' => 'integer',
        'description' => 'Minimum age in game hours before a diary can be injected. Prevents recalling entries just written.',
    ],
    'DIARY_GENERATION_MODE' => [
        'type' => 'select',
        'values' => ['sleep_wait', 'event_count', 'both'],
        'description' => 'How auto-diaries are generated. sleep_wait = created when the player sleeps or waits. event_count = created after a set number of dialogue events (see Diary Events Threshold). both = either trigger can fire.',
    ],
    'DIARY_EVENTS_THRESHOLD' => [
        'type' => 'integer',
        'description' => 'For event_count mode: generate diary every X qualifying events per NPC.',
    ],
    'CONTEXT_HISTORY' => [
        'type' => 'integer',
        'description' => 'Amount of context history (dialogue and events) that will be sent to LLM. Improves short term memory.Higher Context = more tokens used and slower response time.We recommend you do not go over 100',
    ],
    'MAX_WORDS_LIMIT' => [
        'type' => 'integer',
        'description' => "Enforce a word limit for AI's responses. Leave as 0 to have no limit.",
    ],
    'HERIKA_ANIMATIONS' => [
        'type' => 'boolean',
        'description' => 'Will issue animations for the NPC to play',
    ],
    'QUEST_COMMENT_CHANCE' => [
        'type' => 'select',
        'values' => ['10%','25%','50%','75%','100%'],
        'description' => 'Chance that an AI Quest Comment will happen every time a quest updates.',
    ],
    'RECHAT_ALLOW_ACTIONS' => [
        'type' => 'boolean',
        'description' => 'Allow AI NPCs to trigger actions between eachother during Rechat. This can cause some chaos...',
    ],
    'CONTEXT_HISTORY_DIARY' => [
        'type' => 'integer',
        'description' => 'Amount of context history (dialogue and events) that will be sent to LLM specifically for diary entries. If set to 0, will use the regular CONTEXT_HISTORY value instead.',
    ],
    'BORED_EVENT_SERVERSIDE' => [
        'type' => 'boolean',
        'description' => 'Smart Bored Events. Will use the director to generate dynamic bored event topics. It is slower but topics will improve the quality of bored event topics.',
    ],
    'ENFORCE_ACTIONS_PROMPT' => [
        'type' => 'boolean',
        'description' => 'Encourage AI NPCs to use actions more often.',
    ],
    'REMOVE_ASTERISKS_FROM_OUTPUT' => [
        'type' => 'boolean',
        'description' => 'Remove text between ** when the AI responds, such as *couch*, *smiles*, "claps, etc',
    ],
    'CONTEXT_HISTORY_DYNAMIC_PROFILE' => [
        'type' => 'integer',
        'description' => 'Amount of context history (dialogue and events) that will be sent to LLM specifically for dynamic profile updates. If set to 0, will use the regular CONTEXT_HISTORY value instead.',
    ],
];

// Visual keys to expose (can be expanded easily)
$visualKeys = [
  "RECHAT_H","RECHAT_P","CORE_LANG","MINIME_T5","BORED_EVENT",
  "DIARY_PROMPT","OGHMA_AMOUNT","LANG_LLM_XTTS","QUEST_COMMENT","DIARY_COOLDOWN","COMBAT_BARK_COOLDOWN",
  "OGHMA_INFINIUM","CONTEXT_HISTORY","MAX_WORDS_LIMIT","HERIKA_ANIMATIONS",
  "QUEST_COMMENT_CHANCE","RECHAT_ALLOW_ACTIONS","CONTEXT_HISTORY_DIARY","BORED_EVENT_SERVERSIDE","ENFORCE_ACTIONS_PROMPT",
  "REMOVE_ASTERISKS_FROM_OUTPUT","CONTEXT_HISTORY_DYNAMIC_PROFILE",
  "INJECT_DIARIES","DIARY_THRESHOLD_MODIFIER","DIARY_MIN_AGE_HOURS","DIARY_GENERATION_MODE","DIARY_EVENTS_THRESHOLD"
];

// Organize visual keys into categories for display
$visualGroups = [
  'Core' => ["CORE_LANG","ENFORCE_ACTIONS_PROMPT","REMOVE_ASTERISKS_FROM_OUTPUT","MAX_WORDS_LIMIT"],
  'Rechat' => ["RECHAT_H","RECHAT_P","RECHAT_ALLOW_ACTIONS"],
  'Diary' => ["DIARY_PROMPT","DIARY_GENERATION_MODE","INJECT_DIARIES","DIARY_THRESHOLD_MODIFIER","DIARY_MIN_AGE_HOURS","DIARY_EVENTS_THRESHOLD","DIARY_COOLDOWN"],
  'Combat' => ["COMBAT_BARK_COOLDOWN"],
  'Oghma' => ["OGHMA_INFINIUM","OGHMA_AMOUNT","MINIME_T5"],
  'Context' => ["CONTEXT_HISTORY","CONTEXT_HISTORY_DIARY","CONTEXT_HISTORY_DYNAMIC_PROFILE"],
  'Quest' => ["QUEST_COMMENT","QUEST_COMMENT_CHANCE"],
  'Behavior' => ["BORED_EVENT","BORED_EVENT_SERVERSIDE","HERIKA_ANIMATIONS"],
  'Language/Voice' => ["LANG_LLM_XTTS"],
];

// Pretty label similar to global_settings General tab
function meta_pretty_label(string $name): string {
    $p = str_replace('_', ' ', strtolower(trim($name)));
    return ucwords($p);
}

// Simple icon mapping for common groups/keys
function meta_icon_for(string $key): string {
    $u = strtoupper($key);
    if (strpos($u, 'DIARY') !== false) return '📙';
    if (strpos($u, 'COMBAT_BARK') !== false) return '⚔️';
    if (strpos($u, 'RECHAT') === 0) return '🔁';
    if (strpos($u, 'CONTEXT_HISTORY') === 0) return '🧠';
    if (strpos($u, 'OGHMA') === 0) return '🧾';
    if (strpos($u, 'QUEST_') === 0) return '🧭';
    if (strpos($u, 'LANG_') === 0 || strpos($u, 'CORE_LANG') === 0) return '🌐';
    if ($u === 'HERIKA_ANIMATIONS') return '🎞️';
    return '⚙️';
}

$metadataCurrent = [];
if (isset($editItem["metadata"]) && !empty($editItem["metadata"])) {
    $tmp = json_decode($editItem["metadata"], true);
    if (is_array($tmp)) $metadataCurrent = $tmp;
}

// Show visual controls only on core_profiles page
$currentScript = basename($_SERVER['SCRIPT_NAME'] ?? '');
$showVisual = ($currentScript === 'core_profiles.php');

$visualKeysLookup = array_flip($visualKeys);
$nonVisualCurrent = $showVisual ? array_diff_key($metadataCurrent, $visualKeysLookup) : $metadataCurrent;

function renderMetaInput($key, $schema, $value, $controlOnly = false) {
    $type = $schema["type"] ?? 'string';
    $desc = htmlspecialchars($schema["description"] ?? '');
    $values = $schema["values"] ?? [];
    $html = '';
    if ($type === 'boolean') {
        $isTrue = ($value === true || $value === 'true' || $value === 1 || $value === '1');
        $html .= "<input type=\"hidden\" name=\"meta_vis[$key]\" value=\"false\">";
        $html .= "<input class=\"meta-toggle\" type=\"checkbox\" name=\"meta_vis[$key]\" value=\"true\"" . ($isTrue ? ' checked' : '') . ">";
    } elseif ($type === 'select' && is_array($values) && count($values)>0) {
        $html .= "<select name=\"meta_vis[$key]\">";
        $html .= "<option value=\"\">-- select --</option>";
        foreach ($values as $opt) {
            $sel = ((string)$value === (string)$opt) ? 'selected' : '';
            $html .= "<option value=\"" . htmlspecialchars($opt) . "\" $sel>" . htmlspecialchars($opt) . "</option>";
        }
        $html .= "</select>";
    } elseif ($type === 'select' && $key === 'CORE_LANG') {
        // Fallback values for CORE_LANG when not provided in schema
        $opts = ['en','de','es','fr','jp'];
        $html .= "<select name=\"meta_vis[$key]\">";
        $html .= "<option value=\"\">-- select --</option>";
        foreach ($opts as $opt) {
            $sel = ((string)$value === (string)$opt) ? 'selected' : '';
            $html .= "<option value=\"$opt\" $sel>" . htmlspecialchars($opt) . "</option>";
        }
        $html .= "</select>";
    } else {
        // integer/number/longstring/string with optional sliders for known ranges
        $ph = ($type==='integer' || $type==='number') ? 'Enter number' : 'Enter value';
        $val = is_bool($value) ? ($value? 'true':'false') : (string)$value;

        // Known ranges from conf_wizard
        $ranges = [
            'RECHAT_P' => ['min'=>0,'max'=>100,'step'=>1],
            'BORED_EVENT' => ['min'=>0,'max'=>100,'step'=>1],
            'CONTEXT_HISTORY' => ['min'=>0,'max'=>200,'step'=>1],
            'RECHAT_H' => ['min'=>1,'max'=>10,'step'=>1],
            'DIARY_COOLDOWN' => ['min'=>10,'max'=>1200,'step'=>1],
            'COMBAT_BARK_COOLDOWN' => ['min'=>10,'max'=>600,'step'=>1],
            'CONTEXT_HISTORY_DIARY' => ['min'=>0,'max'=>400,'step'=>1],
            'CONTEXT_HISTORY_DYNAMIC_PROFILE' => ['min'=>0,'max'=>400,'step'=>1],
            'DIARY_THRESHOLD_MODIFIER' => ['min'=>-0.25,'max'=>0.5,'step'=>0.05],
            'DIARY_MIN_AGE_HOURS' => ['min'=>0,'max'=>48,'step'=>1],
            'DIARY_EVENTS_THRESHOLD' => ['min'=>5,'max'=>500,'step'=>5]
        ];

        if (($type==='integer' || $type==='number') && isset($ranges[$key])) {
            $rid = 'meta_range_'.$key;
            $nid = 'meta_num_'.$key;
            $min = $ranges[$key]['min'];
            $max = $ranges[$key]['max'];
            $step = $ranges[$key]['step'];
            $safeVal = htmlspecialchars($val);
            $html .= "<input type=\"range\" id=\"$rid\" min=\"$min\" max=\"$max\" step=\"$step\" value=\"$safeVal\" oninput=\"document.getElementById('$nid').value=this.value\">";
            $html .= "<div style=\"margin-top:6px;\"><input type=\"number\" id=\"$nid\" name=\"meta_vis[$key]\" min=\"$min\" max=\"$max\" step=\"$step\" value=\"$safeVal\" style=\"width:80px;\" oninput=\"metaClamp('$rid','$nid',$min,$max)\"></div>";
        } else if ($type === 'longstring') {
            $html .= "<textarea name=\"meta_vis[$key]\" rows=\"4\" placeholder=\"" . htmlspecialchars($ph) . "\">" . htmlspecialchars($val) . "</textarea>";
        } else if ($type==='integer' || $type==='number') {
            $html .= "<input type=\"number\" name=\"meta_vis[$key]\" value=\"" . htmlspecialchars($val) . "\" placeholder=\"" . htmlspecialchars($ph) . "\">";
        } else {
            $html .= "<input type=\"text\" name=\"meta_vis[$key]\" value=\"" . htmlspecialchars($val) . "\" placeholder=\"" . htmlspecialchars($ph) . "\">";
        }
    }
    return $html;
}
?>

<?php if ($showVisual): ?>
    <div class="content-section" style="margin-bottom:10px;">
        <?php
        $rendered = [];
        foreach ($visualGroups as $title => $keys) {
            $keysInVisual = array_values(array_intersect($keys, $visualKeys));
            if (count($keysInVisual) === 0) continue;
            echo '<h2 style="font-family: \''."MagicCards".'\', serif; color: rgb(242,124,17); text-shadow: 1px 1px 2px rgba(0,0,0,0.5); word-spacing: 6px; margin: 10px 0 12px; font-size: 1.2em;">'.htmlspecialchars($title).'</h2>';
            echo '<div class="provider-grid">';
            foreach ($keysInVisual as $k) {
                $schemaEntry = $localSchemaOverrides[$k] ?? ($confSchema[$k] ?? []);
                $type = $schemaEntry['type'] ?? 'string';
                $desc = htmlspecialchars($schemaEntry['description'] ?? '');
                $label = meta_pretty_label($k);
                $icon = meta_icon_for($k);
                $val = $metadataCurrent[$k] ?? '';
                echo '<div class="provider-card">';
                echo   '<div class="provider-head">';
                echo     '<div class="provider-title">';
                echo       '<div class="provider-icon">'.htmlspecialchars($icon).'</div>';
                echo       '<div>'.htmlspecialchars($label).'</div>';
                if ($type === 'boolean') {
                    $isTrue = ($val === true || $val === 'true' || $val === 1 || $val === '1');
                    echo   '<div class="provider-toggle">'
                         . '<input type="hidden" name="meta_vis['.htmlspecialchars($k).']" value="false">'
                         . '<input type="checkbox" value="true" name="meta_vis['.htmlspecialchars($k).']"'.($isTrue?' checked':'').'>'
                         . '</div>';
                }
                echo     '</div>';
                echo   '</div>';
                echo   '<div class="provider-body">';
                if ($type !== 'boolean') {
                    echo renderMetaInput($k, $schemaEntry, $val, true);
                }
                echo   '</div>';
                if (!empty($desc)) echo '<div style="margin-top:6px; color:#bbb; font-size:12px;">'.$desc.'</div>';
                echo '</div>';
                $rendered[$k] = true;
            }
            echo '</div>';
        }
        $remaining = array_values(array_diff($visualKeys, array_keys($rendered)));
        if (count($remaining) > 0) {
            echo '<h2 style="font-family: \''."MagicCards".'\', serif; color: rgb(242,124,17); text-shadow: 1px 1px 2px rgba(0,0,0,0.5); word-spacing: 6px; margin: 10px 0 12px; font-size: 1.2em;">Other</h2>';
            echo '<div class="provider-grid">';
            foreach ($remaining as $k) {
                $schemaEntry = $localSchemaOverrides[$k] ?? ($confSchema[$k] ?? []);
                $type = $schemaEntry['type'] ?? 'string';
                $desc = htmlspecialchars($schemaEntry['description'] ?? '');
                $label = meta_pretty_label($k);
                $icon = meta_icon_for($k);
                $val = $metadataCurrent[$k] ?? '';
                echo '<div class="provider-card">';
                echo   '<div class="provider-head">';
                echo     '<div class="provider-title">';
                echo       '<div class="provider-icon">'.htmlspecialchars($icon).'</div>';
                echo       '<div>'.htmlspecialchars($label).'</div>';
                if (($schemaEntry['type'] ?? '') === 'boolean') {
                    $isTrue = ($val === true || $val === 'true' || $val === 1 || $val === '1');
                    echo   '<div class="provider-toggle">'
                         . '<input type="hidden" name="meta_vis['.htmlspecialchars($k).']" value="false">'
                         . '<input type="checkbox" value="true" name="meta_vis['.htmlspecialchars($k).']"'.($isTrue?' checked':'').'>'
                         . '</div>';
                }
                echo     '</div>';
                echo   '</div>';
                echo   '<div class="provider-body">';
                if (($schemaEntry['type'] ?? '') !== 'boolean') {
                    echo renderMetaInput($k, $schemaEntry, $val, true);
                }
                echo   '</div>';
                if (!empty($desc)) echo '<div style="margin-top:6px; color:#bbb; font-size:12px;">'.$desc.'</div>';
                echo '</div>';
            }
            echo '</div>';
        }
        ?>
    </div>
    <script>
    (function(){
        // Sync On/Off labels for metadata boolean checkboxes
        document.querySelectorAll('.meta-toggle').forEach(cb => {
            const label = cb.closest('label');
            const span = label ? label.querySelector('.toggle-text') : null;
            function sync(){ if (span) span.textContent = cb.checked ? 'On' : 'Off'; }
            cb.addEventListener('change', sync);
        });

        // Grey out DIARY_COOLDOWN when Diary Generation Mode is "event_count"
        const modeSelect = document.querySelector('select[name="meta_vis[DIARY_GENERATION_MODE]"]');
        const cooldownCard = (function(){
            // Find the provider-card that contains DIARY_COOLDOWN controls
            const inputs = document.querySelectorAll('[name="meta_vis[DIARY_COOLDOWN]"]');
            for (const inp of inputs) {
                const card = inp.closest('.provider-card');
                if (card) return card;
            }
            return null;
        })();
        if (modeSelect && cooldownCard) {
            function syncCooldownState() {
                const isEventOnly = (modeSelect.value === 'event_count');
                cooldownCard.style.opacity = isEventOnly ? '0.4' : '1';
                cooldownCard.style.pointerEvents = isEventOnly ? 'none' : 'auto';
            }
            syncCooldownState();
            modeSelect.addEventListener('change', syncCooldownState);
        }
    })();
    </script>
<?php endif; ?>
 
<script>
let jsonEditor ;
let jsonEditor2 ;

// Clamp helper for sliders
function metaClamp(rangeId, numberId, min, max){
    const r = document.getElementById(rangeId)
    const n = document.getElementById(numberId)
    if (!r || !n) return
    let v = parseFloat(n.value)
    if (isNaN(v)) v = min
    if (v < min) v = min
    if (v > max) v = max
    n.value = v
    r.value = v
}

function consolidation() {
    const SHOW_VISUAL = <?= $showVisual ? 'true' : 'false' ?>;
    const VISUAL_KEYS = <?= json_encode($visualKeys, JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE) ?>;
    const content = jsonEditor.get()
    let base = {}
    try {
        base = content.json || {}
    } catch (idontcare) { base = {} }

    // Remove any visual keys from JSON editor content to avoid duplication (only on core_profiles page)
    if (SHOW_VISUAL) {
        VISUAL_KEYS.forEach(k => { if (k in base) delete base[k] })
        // Ensure AUTO_DIARY is not stored in profile metadata (global-only)
        if ('AUTO_DIARY' in base) delete base['AUTO_DIARY']
    }

    // Collect visual fields (explicitly iterate over known keys to capture false for checkboxes)
    const form = document.getElementById('core_profile_form') || document.forms[0]
    const visual = {}
    if (SHOW_VISUAL) {
        VISUAL_KEYS.forEach(key => {
            let inp = form.querySelector(`[name="meta_vis[${key}]"]`)
            if (!inp) return
            const tag = (inp.tagName || '').toLowerCase()
            if (tag === 'input' && (inp.type === 'hidden' || inp.type === 'text' || inp.type === 'number' || inp.type === 'radio')){
                let v
                if (inp.type === 'radio') {
                    const chk = form.querySelector(`[name="meta_vis[${key}]"]:checked`)
                    v = chk ? chk.value : ''
                } else {
                    v = inp.value
                }
                if (v !== '') visual[key] = (v === 'true') ? true : (v === 'false' ? false : v)
            } else if (tag === 'textarea' || tag === 'select') {
                const v = inp.value
                if (v !== '') visual[key] = v
            }
        })
    }

    // Build ordered object: base first (non-visual), then visual keys appended
    const merged = {}
    Object.keys(base).forEach(k => { merged[k] = base[k] })
    if (SHOW_VISUAL) {
        VISUAL_KEYS.forEach(k => { if (k in visual) merged[k] = visual[k] })
    }

    try {
        form.metadata.value = JSON.stringify(merged, null, 0)
    } catch (idontcare) {}
    
    if (form.metadata.value=='')  {
        return confirm("Metadata is empty. You sure?");
    }

    debugger;
    if (form.extended_data!=undefined) {
        const content2 = jsonEditor2.get()

        try {
            form.extended_data.value=JSON.stringify(content2.json, null, 0)
        } catch (idontcare) {}
        
        // Ensure middle_term_enabled checkbox is persisted into extended_data JSON
        try {
            const mtm = document.getElementById('middle_term_enabled')
            if (mtm) {
                let obj = {}
                try { obj = JSON.parse(String(form.extended_data.value||'')||'{}')||{} } catch(_e){ obj = {} }
                obj.middle_term_enabled = mtm.checked ? 1 : 0
                form.extended_data.value = JSON.stringify(obj)
            }
        } catch(_e) {}
    }

    return true;
}


</script>

<script type="module">
    import { createJSONEditor } from 'https://cdn.jsdelivr.net/npm/vanilla-jsoneditor/standalone.js'
    document.addEventListener("DOMContentLoaded", function() {
        let content = {
            text: undefined,
            json: <?php echo json_encode($nonVisualCurrent ?? [], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE) ?>
            
        }


        jsonEditor = createJSONEditor({
        target: document.getElementById('metadata'),
        props: {
            content,
            onChange: (updatedContent, previousContent, { contentErrors, patchResult }) => {
            // content is an object { json: JSONData } | { text: string }
            console.log('onChange', { updatedContent, previousContent, contentErrors, patchResult })
            content = updatedContent
            }
        }
        })
        console.log("javascript init done");

    });


    document.addEventListener("DOMContentLoaded", function() {
        let content = {
            text: undefined,
            json: <?php echo (!empty($editItem["extended_data"])?$editItem["extended_data"]:"{}") ?>
            
        }

        if (document.getElementById('extended_data')) {
            jsonEditor2 = createJSONEditor({
            target: document.getElementById('extended_data'),
            props: {
                content,
                onChange: (updatedContent, previousContent, { contentErrors, patchResult }) => {
                // content is an object { json: JSONData } | { text: string }
                console.log('onChange', { updatedContent, previousContent, contentErrors, patchResult })
                content = updatedContent
                }
            }
            })
        }
        console.log("javascript init done");

    });

    document.addEventListener("DOMContentLoaded", function() {
        const miniUpdateAppearance = document.getElementById('small_update_appearance');
        miniUpdateAppearance.addEventListener('click', async function(e){
            
            e.preventDefault();
            try {
            const doc = document;
            const nameEl = doc ? doc.getElementById('npc_name') : null;
            const npcName = nameEl ? String(nameEl.value||'').trim() : '';
            
            showProcessing()
            const res = await fetch('../cmd/action_ai_update_appearance.php?name='+encodeURIComponent(npcName));
            let j = {}; try { 
                j = await res.json(); 
                if (j.done) {
                     doc.getElementById('appearance').value = j.appearance
                     hideProcessing()
                }
            } catch(_e) {
                 j = {ok:false};
                 }
            
            
            

            } catch(_e){console.log(_e)}
        });
    });

    function showProcessing() {
        
        processingMessage = document.createElement('div');
        processingMessage.textContent = 'Processing...';
        processingMessage.style.position = 'fixed';
        processingMessage.style.top = '50%';
        processingMessage.style.left = '50%';
        processingMessage.style.transform = 'translate(-50%, -50%)';
        processingMessage.style.backgroundColor = '#000';
        processingMessage.style.color = '#fff';
        processingMessage.style.padding = '10px 20px';
        processingMessage.style.borderRadius = '8px';
        processingMessage.style.zIndex = '10001';
        processingMessage.id="processing_wheel"
        document.body.appendChild(processingMessage);
      }
    function hideProcessing() {
        processingMessage.innerHTML=''
        processingMessage.style.zIndex = '-10001';

    }
    var processingMessage;


</script>