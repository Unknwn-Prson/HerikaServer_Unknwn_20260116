<?php

$enginePath = dirname((__FILE__)) . DIRECTORY_SEPARATOR."..".DIRECTORY_SEPARATOR;
require_once($enginePath . "lib" .DIRECTORY_SEPARATOR."tokenizer_helper_functions.php");

// Cached version of openrouterjson connector with Anthropic/OpenAI/Gemini cache support
// Based on CHIM 2.4.3 architecture with additional caching and response format features

class openrouterjsoncached
{
    // Version tracking - update after making changes
    const VERSION = 'OpenRouter Cache Connector v1.7.0 for CHIM 2.4.3+ | 2026/02/27';
    public $primary_handler;
    public $name;

    private $_functionName;
    private $_parameterBuff;
    private $_commandBuffer;
    private $_numOutputTokens;
    private $_dataSent;
    private $_fid;
    private $_buffer;
    private $_stopProc;
    public $_extractedbuffer;
    private $_rawbuffer;
    private $_forcedClose=false;
    private $_is_nanogpt_com;
    private $_is_mistral_ai;
    private $_is_streaming;
    private $_is_reasoning;
    private $_is_openai;
    private $_model="";
    private $_fallback_models;
    private $_providers_sort;
    private $_provider_quantizations;
    private $_providers2ignore;
    private $_provider_max_price;
    private $_url;
    // Web search properties (CHIM 2.2 feature - NOT YET IMPLEMENTED in cached connector)
    // TODO: Port web search detection/handling from openrouterjson.php if needed
    private $_websearch=false;
    private $_websearch_text="";
    private $_websearch_index=0;
    private $_webbackup_func=false;
    private $_remove_cot;
    private $_disable_reasoning;
    private $_cot_tag_base;
    private $_output_buffer; 
    private $_timeout;
    private $_is_grok;
    private $_lastStreamedObject;

    // Caching-specific properties
    private $_provider_caching;
    private $_responseFormat;
    private $_includeMood;
    private $_includeActions;
    private $_includeTarget;
    private $_includeListener;
    private $_defaultTarget;
    private $_simpleFormatParsed;
    private $_usedPrefill;
    private $_prefillContent;
    private $_simpleFormatMessageStart;
    private $_lastReturnedLength;
    public $_jsonResponsesEncoded = array();

    // Simple format parser state variables
    private $_reasoningState;
    private $_reasoningTagType;
    private $_metadataEnd;
    private $_sentencesSent;
    private $_metadataGroups;
    private $_flushedPartial;

    // Memory handling mode: 'accumulate' (dedupe) or 'fresh' (like regular connector)
    private $_memoryMode;

    // Cache invalidation mode: 'time_based' or 'sync_updates'
    private $_cacheInvalidationMode;


    public function __construct()
    {
        $this->name="openrouterjsoncached";
        $this->_commandBuffer=[];
        $this->_stopProc=false;
        $this->_extractedbuffer="";
        $this->_buffer="";
        $this->_forcedClose=false;
        $this->_is_nanogpt_com=false;
        $this->_is_mistral_ai=false;
        $this->_model="";
        $this->_fallback_models=null;
        $this->_providers_sort="";
        $this->_provider_quantizations=null;
        $this->_providers2ignore=null;
        $this->_provider_max_price=null;
        $this->_url="";
        $this->_is_streaming=true;
        $this->_is_reasoning=false;
        $this->_remove_cot=true;
        $this->_disable_reasoning=true;
        $this->_cot_tag_base="think";
        $this->_output_buffer="";
        $this->_timeout=30;
        $this->_is_grok=false;
        $this->_is_openai=false;
        $this->_websearch=false;
        $this->_websearch_text="";
        $this->_websearch_index=0;
        $this->_webbackup_func=false;

        // Initialize caching properties
        $this->_provider_caching = 'Anthropic';
        $this->_responseFormat = 'json';
        $this->_includeMood = true;
        $this->_includeActions = true;
        $this->_includeTarget = true;
        $this->_includeListener = true;
        $this->_defaultTarget = '';
        $this->_simpleFormatParsed = false;
        $this->_usedPrefill = false;
        $this->_prefillContent = '';
        $this->_simpleFormatMessageStart = -1;
        $this->_lastReturnedLength = 0;
        $this->_jsonResponsesEncoded = array();

        // Initialize simple format parser state
        $this->_reasoningState = 'NORMAL';
        $this->_reasoningTagType = '';
        $this->_metadataEnd = -1;
        $this->_sentencesSent = 0;
        $this->_metadataGroups = [];
        $this->_flushedPartial = false;

        // Initialize new v2 settings
        $this->_memoryMode = 'accumulate';  // 'accumulate' or 'fresh'
        $this->_cacheInvalidationMode = 'time_based';  // 'time_based' or 'sync_updates'

        require_once(__DIR__."/__jpd.php");
        require_once(__DIR__."/openrouterjsoncached_helpers.php");
        // Load reasoning token stripping functions (stripReasoningTokens, hasUnclosedReasoningMarker, etc.)
        if (file_exists(__DIR__."/../lib/reasoning_helpers.php")) {
            require_once(__DIR__."/../lib/reasoning_helpers.php");
        }

        logMessage("[{$this->name}] OpenRouter Cached Connector v" . self::VERSION . " initialized");
    }


    private function isWebSearchInMessage($s_msg="") {
        $b_res = false;
        if (strlen($s_msg) > 7) {
            $i_pos = stripos($s_msg, "Skyrim search");
            if ($i_pos === false) 
                $i_pos = stripos($s_msg, "Search Skyrim");
            if ($i_pos === false) 
                $i_pos = stripos($s_msg, "Find knowledge in Skyrim");
            if ($i_pos === false) 
                $i_pos = stripos($s_msg, "Search Elder Scrolls");
            if ($i_pos === false) 
                $i_pos = stripos($s_msg, "Find knowledge in Elder Scrolls");
            $b_res = (!($i_pos === false));
        }
        return $b_res;
    }


    private function isReasoningModel($s_model="") { //recognize a reasoning model that can hide <think> cot part with dedicated parameters
        $b_res = false;
        if (strlen($s_model) > 0) {
            $i_pos = stripos($s_model, "deepseek-r"); 
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "qwq-32b"); 
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "qwq-max");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "-thinking");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, ":thinking");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "-reasoning");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "grok-3-mini"); 
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "sonar-deep-research");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "r1-1776");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "dolphin3.0-r1-mistral");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "aion-1.0");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "reka-flash-3");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "olympiccoder-");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "MAI-DS-R1");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "qwen3-235b-a22b");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "qwen3-30b-a3b");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "qwen3-32b");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/o3");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/o4");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/o1");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/gpt-oss-120b");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/gpt-oss-20b");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "gpt-5-mini");
            //openai/gpt-5-nano ???
            if ($i_pos === false) { //openai/gpt-5
                if (($s_model == "openai/gpt-5")) {
                    $i_pos = 9;
                }
            }
            $b_res = (!($i_pos === false));
        }
        return $b_res;
    }

    private function isOpenAIModel($s_model="") { //OpenAI models have different parameters
        $b_res = false;
        if (strlen($s_model) > 0) {
            // OpenRouter models
            $i_pos = stripos($s_model, "openai/o1");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/gpt-5");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/gpt-oss-120b");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/gpt-oss-20b");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/o3");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "openai/o4-mini");
            // Nano-GPT models
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "azure-o1");
            if ($i_pos === false) 
                $i_pos = stripos($s_model, "azure-o3");
            // OpenAI model names
            if ($i_pos === false) { 
                if (($s_model == "o1") || ($s_model == "o1-mini") || ($s_model == "o1-preview") || 
                    ($s_model == "o3") || (strpos($s_model, "o3-mini") === 0) || (strpos($s_model, "o3-pro") === 0) || 
                    (strpos($s_model, "o4-mini") === 0)) {
                    $i_pos = 9;
                }
            }
            $b_res = (!($i_pos === false));
        }
        //Logger::debug("[OPENROUTER] is openai $s_model / $i_pos ". ($b_res ? "Y" : "N") ); //debug
        return $b_res;
    }

    /**
     * Indicates whether this connector handles sentence splitting internally.
     * Used by data_functions.php to bypass MINIMUM_SENTENCE_SIZE checks.
     * Returns true only in simple format mode.
     */
    public function handlesSentenceSplitting() {
        return ($this->_responseFormat === 'simple');
    }

    /**
     * Detects models that ALWAYS have reasoning enabled (cannot be disabled).
     * These models will always output reasoning tokens regardless of settings.
     * Used in _openPart4 to always include reasoning configuration.
     */
    private function isAlwaysReasoningModel($s_model="") {
        $b_res = false;
        if (strlen($s_model) > 0) {
            // OpenAI reasoning models (o1, o3, o4, gpt-5*)
            if ($this->isOpenAIModel($s_model)) {
                $b_res = true;
            }

            // DeepSeek R1 variants (always reasons)
            if (!$b_res) {
                $i_pos = stripos($s_model, "deepseek-r1");
                if ($i_pos === false)
                    $i_pos = stripos($s_model, "r1-1776");
                $b_res = (!($i_pos === false));
            }
        }
        return $b_res;
    }

    /**
     * Check if cache should be invalidated based on sync_updates mode
     * Queries NPC extended_data for dynamic profile and middle-term memory changes
     */
    private function _checkSyncInvalidation($herikaName) {
        // Don't process for narrator or default
        if ($herikaName === 'The Narrator' || $herikaName === 'default_herika') {
            return;
        }

        try {
            // Load NpcMaster if not already available
            $enginePath = __DIR__ . DIRECTORY_SEPARATOR . ".." . DIRECTORY_SEPARATOR;
            if (!class_exists('NpcMaster')) {
                if (file_exists($enginePath . "lib/npc_master.class.php")) {
                    require_once($enginePath . "lib/npc_master.class.php");
                } else {
                    logMessage("NpcMaster class not found - sync_updates unavailable", null, 'WARN');
                    return;
                }
            }

            // Get NPC data
            $npcMaster = new \NpcMaster();
            $npcData = $npcMaster->getByName($herikaName);

            if (!$npcData) {
                logMessage("NPC data not found for {$herikaName} - sync_updates skipped", null, 'WARN');
                return;
            }

            // Get extended data (contains dynamic profile and middle_term_memory)
            $extendedData = $npcMaster->getExtendedData($npcData);

            // Extract relevant fields for hash
            $profileData = [];
            $memoryData = null;

            // Dynamic profile fields
            $profileFields = ['personality', 'relationships', 'occupation', 'skills', 'speechstyle', 'goals'];
            foreach ($profileFields as $field) {
                if (isset($extendedData[$field])) {
                    $profileData[$field] = $extendedData[$field];
                }
            }

            // Middle-term memory
            if (isset($extendedData['middle_term_memory']) && is_array($extendedData['middle_term_memory'])) {
                $memoryData = $extendedData['middle_term_memory'];
            }

            // Check if invalidation is needed
            if (shouldInvalidateSyncCache($herikaName, $this->_responseFormat, $profileData, $memoryData)) {
                // Clear the cache files
                $result = clearNpcCacheFiles($herikaName, $this->_responseFormat);
                logMessage("Sync invalidation triggered for {$herikaName}: cleared {$result['cleared']} files");
            }

        } catch (\Exception $e) {
            logMessage("Error in sync invalidation check: " . $e->getMessage(), null, 'ERROR');
        }
    }

    // ================================================================================
    // OPEN METHOD - Split into 4 parts for caching support
    // Part 1: Configuration and initialization
    // Part 2: System prompt processing with caching
    // Part 3: Dialogue history caching and cache control placement
    // Part 4: Payload construction and API request
    // ================================================================================

    public function open($contextData, $customParms) {
        $start_time = microtime(true);
        require_once(__DIR__ . DIRECTORY_SEPARATOR . ".." . DIRECTORY_SEPARATOR . "functions" . DIRECTORY_SEPARATOR . "json_response.php");

        $herikaName = isset($GLOBALS["HERIKA_NAME"]) ? $GLOBALS["HERIKA_NAME"] : 'default_herika';
        $n_ctxsize = count($contextData);

        logMessage("[{$this->name}:{$herikaName}] OPEN START: Received contextData with {$n_ctxsize} elements.");

        // Load URL configuration
        $this->_url = isset($GLOBALS["CONNECTOR"][$this->name]["url"]) ? $GLOBALS["CONNECTOR"][$this->name]["url"] : '';
        if (empty($this->_url)) {
            logMessage("{$this->name} connector - missing url!");
            return null;
        }

        // Load basic configuration
        $MAX_TOKENS = intval(isset($GLOBALS["CONNECTOR"][$this->name]["max_tokens"]) ? $GLOBALS["CONNECTOR"][$this->name]["max_tokens"] : 4096);
        $this->_model = (isset($GLOBALS["CONNECTOR"][$this->name]["model"])) ? $GLOBALS["CONNECTOR"][$this->name]["model"] : 'anthropic/claude-3-haiku-20240307';
        $this->_model = isset($customParms["model"]) ? $customParms["model"] : $this->_model;

        // Caching configuration
        $max_dialogue_cache_size = intval(isset($GLOBALS["CONNECTOR"][$this->name]["max_dialogue_cache_context_size"]) ? $GLOBALS["CONNECTOR"][$this->name]["max_dialogue_cache_context_size"] : $n_ctxsize * 4);
        $customInstruction = isset($GLOBALS["CONNECTOR"][$this->name]["custom_system_instruction"]) ? $GLOBALS["CONNECTOR"][$this->name]["custom_system_instruction"] : '';
        $lastCustomInstruction = isset($GLOBALS["CONNECTOR"][$this->name]["custom_last_instruction"]) ? $GLOBALS["CONNECTOR"][$this->name]["custom_last_instruction"] : '';

        // Reasoning/thinking configuration
        $toggleThinking = isset($GLOBALS["CONNECTOR"][$this->name]["toggle_thinking"]) ? $GLOBALS["CONNECTOR"][$this->name]["toggle_thinking"] : false;
        // Default 1024 is Anthropic's minimum for extended thinking (budget_tokens)
        $thinkingTokens = isset($GLOBALS["CONNECTOR"][$this->name]["thinking_tokens"]) ? $GLOBALS["CONNECTOR"][$this->name]["thinking_tokens"] : 1024;
        $effort_level = isset($GLOBALS["CONNECTOR"][$this->name]["effort_level"]) ? $GLOBALS["CONNECTOR"][$this->name]["effort_level"] : "low";

        // Cache provider configuration
        $this->_provider_caching = isset($GLOBALS["CONNECTOR"][$this->name]["provider_caching"]) ? $GLOBALS["CONNECTOR"][$this->name]["provider_caching"] : "Anthropic";
        logMessage("provider caching: {$this->_provider_caching}");

        $CONTEXTHISTORY = isset($GLOBALS['CONTEXT_HISTORY']) ? $GLOBALS['CONTEXT_HISTORY'] : 50;
        logMessage("CONTEXT HISTORY: $CONTEXTHISTORY");

        // Dialogue cache configuration
        $dialogue_cache_uncached_count = isset($GLOBALS["CONNECTOR"][$this->name]["dialogue_cache_uncached_count"])
            ? (int)$GLOBALS["CONNECTOR"][$this->name]["dialogue_cache_uncached_count"]
            : 4;

        // Response format configuration
        $this->_responseFormat = isset($GLOBALS["CONNECTOR"][$this->name]["response_format"])
            && in_array($GLOBALS["CONNECTOR"][$this->name]["response_format"], ['json', 'simple'])
            ? $GLOBALS["CONNECTOR"][$this->name]["response_format"]
            : 'json';

        // Field inclusion configuration
        $this->_includeActions = (isset($GLOBALS["FUNCTIONS_ARE_ENABLED"]) && $GLOBALS["FUNCTIONS_ARE_ENABLED"])
            && (isset($GLOBALS["CONNECTOR"][$this->name]["include_actions_list"])
                ? (bool)$GLOBALS["CONNECTOR"][$this->name]["include_actions_list"]
                : true);

        $this->_includeMood = isset($GLOBALS["CONNECTOR"][$this->name]["include_mood_requirement"])
            ? (bool)$GLOBALS["CONNECTOR"][$this->name]["include_mood_requirement"]
            : true;

        $this->_includeTarget = isset($GLOBALS["CONNECTOR"][$this->name]["include_target_requirement"])
            ? (bool)$GLOBALS["CONNECTOR"][$this->name]["include_target_requirement"]
            : true;

        $this->_includeListener = isset($GLOBALS["CONNECTOR"][$this->name]["include_listener_requirement"])
            ? (bool)$GLOBALS["CONNECTOR"][$this->name]["include_listener_requirement"]
            : true;

        // Quality prompt setting (defaults to true for advanced models)
        $minimizeQualityPrompt = isset($GLOBALS["CONNECTOR"][$this->name]["minimize_quality_prompt"])
            ? (bool)$GLOBALS["CONNECTOR"][$this->name]["minimize_quality_prompt"]
            : true;

        // --- BEGIN CACHED CONNECTOR SETTINGS ---
        // Refusal filter: disable checkOAIComplains for this connector (defaults to ON = disabled)
        // Uses the existing OPENAI_FILTER_DISABLED mechanism in chat_helper_functions.php
        $disableRefusalFilter = isset($GLOBALS["CONNECTOR"][$this->name]["disable_refusal_filter"])
            ? (bool)$GLOBALS["CONNECTOR"][$this->name]["disable_refusal_filter"]
            : true; // Default: disabled for cached connector (non-OpenAI models)
        if ($disableRefusalFilter) {
            $GLOBALS["OPENAI_FILTER_DISABLED"] = true;
        }

        // Asterisk preservation: preserve text between *...* instead of stripping
        // Uses the PRESERVE_ASTERISKS mechanism in chat_helper_functions.php unmoodSentence()
        $preserveAsterisks = isset($GLOBALS["CONNECTOR"][$this->name]["preserve_asterisks"])
            ? (bool)$GLOBALS["CONNECTOR"][$this->name]["preserve_asterisks"]
            : false; // Default: off (standard TTS behavior)
        if ($preserveAsterisks) {
            $GLOBALS["PRESERVE_ASTERISKS"] = true;
        }

        // Sentence filter bypass: skip legacy sentence validation in returnLines()
        // Disables: is_array check, <2 char check, "The Narrator:" check
        // Uses the DISABLE_SENTENCE_FILTERS mechanism in chat_helper_functions.php returnLines()
        $disableSentenceFilters = isset($GLOBALS["CONNECTOR"][$this->name]["disable_sentence_filters"])
            ? (bool)$GLOBALS["CONNECTOR"][$this->name]["disable_sentence_filters"]
            : true; // Default: disabled for cached connector (modern models don't need these)
        if ($disableSentenceFilters) {
            $GLOBALS["DISABLE_SENTENCE_FILTERS"] = true;
        }
        // --- END CACHED CONNECTOR SETTINGS ---

        // Memory mode configuration (NEW in v2)
        $this->_memoryMode = isset($GLOBALS["CONNECTOR"][$this->name]["memory_mode"])
            ? $GLOBALS["CONNECTOR"][$this->name]["memory_mode"]
            : 'accumulate';

        // Cache invalidation mode (NEW in v2)
        $this->_cacheInvalidationMode = isset($GLOBALS["CONNECTOR"][$this->name]["cache_invalidation_mode"])
            ? $GLOBALS["CONNECTOR"][$this->name]["cache_invalidation_mode"]
            : 'time_based';

        // Sync_updates cache invalidation - check if profile/memory has changed
        if ($this->_cacheInvalidationMode === 'sync_updates') {
            $this->_checkSyncInvalidation($herikaName);
        }

        // Enforce dependency: target required if actions enabled
        if ($this->_includeActions) {
            $this->_includeTarget = true;
        }

        logMessage("Response Format Config: format={$this->_responseFormat}, actions={$this->_includeActions}, mood={$this->_includeMood}, target={$this->_includeTarget}, listener={$this->_includeListener}, memoryMode={$this->_memoryMode}");

        // Continue to Part 2...
        return $this->_openPart2($contextData, $customParms, $herikaName, $MAX_TOKENS, $max_dialogue_cache_size,
                                  $customInstruction, $lastCustomInstruction, $toggleThinking, $thinkingTokens,
                                  $effort_level, $CONTEXTHISTORY, $dialogue_cache_uncached_count, $start_time, $minimizeQualityPrompt);
    }

    // Part 2: System Prompt Processing with Caching
    private function _openPart2($contextData, $customParms, $herikaName, $MAX_TOKENS, $max_dialogue_cache_size,
                                 $customInstruction, $lastCustomInstruction, $toggleThinking, $thinkingTokens,
                                 $effort_level, $CONTEXTHISTORY, $dialogue_cache_uncached_count, $start_time, $minimizeQualityPrompt = true) {

        // Cache file names include response format to separate caches
        $cacheSystemFile = "system_cache_{$this->_responseFormat}_{$herikaName}.tmp";
        $cacheCombinedDialogueFile = "combined_dialogue_cache_{$this->_responseFormat}_{$herikaName}.tmp";
        $cacheControlType = ["type" => "ephemeral", "ttl" => "1h"];

        // Build actions prefix
        if (isset($GLOBALS["PATCH_PROMPT_ENFORCE_ACTIONS"]) && $GLOBALS["PATCH_PROMPT_ENFORCE_ACTIONS"]) {
            $prefix = isset($GLOBALS["COMMAND_PROMPT_ENFORCE_ACTIONS"]) ? "{$GLOBALS["COMMAND_PROMPT_ENFORCE_ACTIONS"]}" : "";

            // Filter quality instructions if minimize_quality_prompt is enabled
            if ($minimizeQualityPrompt && stripos($prefix, 'Provide variety') !== false) {
                $prefix = "";
            }
        } else {
            $prefix = "";
        }

        // Speech style reinforcement
        if (isset($GLOBALS["HERIKA_SPEECHSTYLE"]) && !empty($GLOBALS["HERIKA_SPEECHSTYLE"])) {
            $speechReinforcement = "Use #SpeechStyle.";
        } else {
            $speechReinforcement = "";
        }

        // Zonos TTS support (from CHIM 2.2)
        $zonosTones = (isset($GLOBALS["TTSFUNCTION"]) && $GLOBALS["TTSFUNCTION"] == "zonos_gradio") ? " (Response tones are mandatory in the response)" : "";

        // Build actions list if enabled
        $availableActions = "";
        if ($this->_includeActions && isset($GLOBALS["COMMAND_PROMPT"])) {
            $availableActions = preg_replace('/\(available targets:[^\n]*/', '', $GLOBALS["COMMAND_PROMPT"]);
        }

        // Build response format instruction based on format type
        $formatInstruction = "";

        if ($this->_responseFormat === 'json') {
            $template = isset($GLOBALS["responseTemplate"]) ? $GLOBALS["responseTemplate"] : [];

            // Remove fields not included
            if (!$this->_includeMood && is_array($template) && isset($template['mood'])) {
                unset($template['mood']);
            }
            if (!$this->_includeActions && is_array($template) && isset($template['action'])) {
                unset($template['action']);
            }
            if (!$this->_includeTarget && is_array($template) && isset($template['target'])) {
                unset($template['target']);
            }
            if (!$this->_includeListener && is_array($template) && isset($template['listener'])) {
                unset($template['listener']);
            }

            $prefixPart = trim(implode(' ', array_filter([$prefix, $speechReinforcement], 'strlen')));
            $formatInstruction = "{$prefixPart} Use ONLY this JSON object to give your answer. Do not send any other characters outside of this JSON structure$zonosTones: " . json_encode($template);
        } else {
            $prefixPart = trim(implode(' ', array_filter([$prefix, $speechReinforcement], 'strlen')));
            $formatInstruction = buildSimpleFormatInstruction(
                $this->_includeMood,
                $this->_includeListener,
                $this->_includeActions,
                $this->_includeTarget,
                $prefixPart
            );
        }

        $actionsText = "";
        if (!empty($availableActions)) {
            $actionsText .= "\n" . $availableActions . "\n";
        }
        // For JSON format, instruction goes in system message
        if ($this->_responseFormat === 'json') {
            $actionsText .= $formatInstruction;
        }

        $dynamicEnvironment = "";
        $systemEntries = [];

        // Process system prompts and extract dynamic sections
        foreach ($contextData as $n => $element) {
            if (isset($element["role"]) && $element["role"] == "system") {
                $systemContentString = '';
                if (is_string($element['content'])) {
                    $systemContentString = $element['content'];
                } elseif (is_array($element['content']) && isset($element['content'][0]['type']) &&
                          $element['content'][0]['type'] === 'text' && isset($element['content'][0]['text'])) {
                    $systemContentString = $element['content'][0]['text'];
                }

                $systemContentCurrent = trim($systemContentString);

                // Extract dynamic sections that change frequently (for reinsertion later)
                $environmental = extract_and_remove_section($systemContentCurrent, 'Environmental Context');
                $additional = extract_and_remove_section($systemContentCurrent, 'Additional Information');
                $equipment = extract_any_subsection($systemContentCurrent, 'Equipment', true);
                $appearance = extract_any_subsection($systemContentCurrent, 'Physical Appearance', false);
                $cleanliness = extract_any_subsection($systemContentCurrent, 'Cleanliness', true);
                $additionalCharacter = extract_specific_section($systemContentCurrent, 'Additional Character Information');
                $combatStatus = extract_specific_section($systemContentCurrent, 'Combat Vitals');
                $arousal = extract_specific_section($systemContentCurrent, 'Arousal Status');

                $dynamicEnvironment = $environmental . "\n\n" . $additional . "\n\n" . $additionalCharacter . "\n\n" .
                                     $combatStatus . "\n\n" . $arousal . "\n\n" . $equipment . "\n\n" .
                                     $appearance . "\n\n" . $cleanliness;

                // Add custom system instruction
                $customInstructionPart = !empty($customInstruction) ? "\n" . $customInstruction : '';
                $finalSend = $systemContentCurrent . $customInstructionPart . "\n" . $actionsText;

                $content = ['type' => 'text', 'text' => $finalSend];
                if ($this->_provider_caching !== "OpenAI" && $this->_provider_caching !== "None") {
                    $content['cache_control'] = $cacheControlType;
                }
                $systemEntries[] = array("role" => "system", "content" => array($content));
            }
        }

        $finalMessagesToSend = writeArrayToFileWithCache($systemEntries, $cacheSystemFile);

        // Continue to Part 3...
        return $this->_openPart3($contextData, $customParms, $herikaName, $MAX_TOKENS, $max_dialogue_cache_size,
                                  $lastCustomInstruction, $toggleThinking, $thinkingTokens, $effort_level,
                                  $CONTEXTHISTORY, $dialogue_cache_uncached_count, $start_time,
                                  $finalMessagesToSend, $cacheCombinedDialogueFile, $cacheControlType, $dynamicEnvironment, $formatInstruction);
    }

    // Part 3: Dialogue History Caching and Cache Control Placement
    private function _openPart3($contextData, $customParms, $herikaName, $MAX_TOKENS, $max_dialogue_cache_size,
                                 $lastCustomInstruction, $toggleThinking, $thinkingTokens, $effort_level,
                                 $CONTEXTHISTORY, $dialogue_cache_uncached_count, $start_time,
                                 $finalMessagesToSend, $cacheCombinedDialogueFile, $cacheControlType, $dynamicEnvironment, $formatInstruction) {

        // Process dialogue history (non-system entries)
        $contentTextToSend = [];
        $memoryItems = [];  // For memory mode handling

        foreach ($contextData as $n => $element) {
            if (!isset($element))
                continue;

            if (isset($element["role"]) && $element["role"] != "system") {
                $contentString = '';
                if (is_string($element['content'])) {
                    $contentString = $element['content'];
                } elseif (is_array($element['content']) && isset($element['content'][0]['type']) &&
                          $element['content'][0]['type'] === 'text' && isset($element['content'][0]['text'])) {
                    $contentString = $element['content'][0]['text'];
                }

                if (containsOnlySymbols($contentString)) {
                    continue;
                }

                if (!empty(trim($contentString))) {
                    $item = array('type' => 'text', 'text' => "$contentString");

                    // Memory mode handling: if 'fresh' mode, separate memory items
                    if ($this->_memoryMode === 'fresh' && strpos($contentString, '<memory>') !== false) {
                        $memoryItems[] = $item;
                    } else {
                        $contentTextToSend[] = $item;
                    }
                }
            }
        }

        // Remove first few items if list is large (optimization)
        if (count($contentTextToSend) > 4) {
            $contentTextToSend = array_slice($contentTextToSend, 4);
        }

        // Remove instruction to add back later (with null safety)
        $instruction = !empty($contentTextToSend) ? array_pop($contentTextToSend) : ['type' => 'text', 'text' => ''];

        // Manage cached event list (excludes memory items in 'fresh' mode)
        $completeEventList = manageCharacterEventList($contentTextToSend, $cacheCombinedDialogueFile, $max_dialogue_cache_size);
        logMessage("New elements added to cache: {$completeEventList['new_count']}");
        $completeEventList = $completeEventList['updated_list'];

        // Add custom instructions if present
        $addToIndex = 0;
        if (!empty($lastCustomInstruction)) {
            $addToIndex = 1;
            $completeEventList[] = ['type' => 'text', 'text' => $lastCustomInstruction];
        }

        // For simple format, append format instruction to user instruction
        if ($this->_responseFormat === 'simple' && !empty($formatInstruction)) {
            $instructionText = is_array($instruction) && isset($instruction['text']) ? $instruction['text'] : $instruction;
            $instructionText .= ' ' . $formatInstruction;
            $instruction = is_array($instruction) ? ['type' => 'text', 'text' => $instructionText] : $instructionText;
        }

        // Re-add memory items in 'fresh' mode (they go at end, uncached)
        if ($this->_memoryMode === 'fresh' && !empty($memoryItems)) {
            foreach ($memoryItems as $memItem) {
                $completeEventList[] = $memItem;
            }
            logMessage("Memory mode 'fresh': Added " . count($memoryItems) . " memory items to end of context");
        }

        $completeEventList[] = $instruction;

        // Store default target for simple format
        $this->_defaultTarget = getLastUserMessageSpeaker($contextData);

        // Calculate cache control index
        $totalElements = count($completeEventList);
        $lastIndex = $totalElements - $dialogue_cache_uncached_count - 1 - $addToIndex;

        logMessage("Cache control calculation: totalElements=$totalElements, uncached=$dialogue_cache_uncached_count, calculatedIndex=$lastIndex");

        // Place cache control marker
        if ($lastIndex >= 0) {
            if ($this->_provider_caching == "Gemini") {
                logMessage("Using gemini caching (ignores dialogue_cache_uncached_count)");
                $offset = 10;
                $elements = count($completeEventList);
                $batchSize = $CONTEXTHISTORY - $offset;
                $batchNumber = floor($elements / $batchSize);

                $indexToCache = max(0, ($batchNumber * $CONTEXTHISTORY) - $offset);

                if ($indexToCache >= $elements) {
                    $indexToCache = $elements - 1;
                }

                if ($indexToCache == 0) {
                    $indexToCache = 33; // Gemini requires minimum 32 tokens
                }

                if (isset($completeEventList[$indexToCache]) && $this->_provider_caching != "OpenAI" && $this->_provider_caching != "None") {
                    $completeEventList[$indexToCache]["cache_control"] = $cacheControlType;
                }
            } else {
                logMessage("Using standard caching with dialogue_cache_uncached_count=$dialogue_cache_uncached_count");
                if (isset($completeEventList[$lastIndex]) && $this->_provider_caching != "OpenAI" && $this->_provider_caching != "None") {
                    $completeEventList[$lastIndex]["cache_control"] = $cacheControlType;
                    logMessage("Cache control placed at index $lastIndex");
                }
            }
        }

        // Add dynamic environment context if available
        if (!containsOnlySymbols($dynamicEnvironment)) {
            $text = preg_replace('/^\s*#+.*$/m', '', $dynamicEnvironment);
            $text = preg_replace('/^\s*[-•]\s*/', '', $text);
            $text = preg_replace('/\s+/', ' ', $text);
            $text = preg_replace('/[.]{2,}/', '.', $text);
            $dynamicEnvironment = trim("ASSISTANT: Environmental Context: $text");

            $insertPosition = max(0, count($completeEventList) - 2);
            array_splice($completeEventList, $insertPosition, 0, [array('type' => 'text', 'text' => $dynamicEnvironment)]);
        }

        $completeEventList = removeDuplicateMemories($completeEventList);

        $tokenCount = countTokensByWords($completeEventList);
        logMessage("Estimated token count: $tokenCount");

        // Handle prefill for simple format (incompatible with reasoning)
        // Skip prefill for "None" caching mode - some providers (like Palmyra/Bedrock)
        // require the last message to be a user message
        if ($this->_responseFormat === 'simple' && !$toggleThinking && $this->_provider_caching !== "None") {
            $finalMessagesToSend[] = array('role' => 'user', 'content' => $completeEventList);
            $prefillText = '(';
            $finalMessagesToSend[] = array('role' => 'assistant', 'content' => array(
                array('type' => 'text', 'text' => $prefillText)
            ));
            $this->_usedPrefill = true;
            $this->_prefillContent = $prefillText;
        } else {
            $finalMessagesToSend[] = array('role' => 'user', 'content' => $completeEventList);
            $this->_usedPrefill = false;
            $this->_prefillContent = '';
        }

        // Continue to Part 4...
        return $this->_openPart4($customParms, $herikaName, $MAX_TOKENS, $toggleThinking, $thinkingTokens,
                                  $effort_level, $start_time, $finalMessagesToSend);
    }

    // Part 4: Final Payload Construction and API Request
    private function _openPart4($customParms, $herikaName, $MAX_TOKENS, $toggleThinking, $thinkingTokens,
                                 $effort_level, $start_time, $finalMessagesToSend) {

        // Detect model capabilities
        $isOpenAIReasoning = $this->isOpenAIModel($this->_model);
        $isAlwaysReasoning = $this->isAlwaysReasoningModel($this->_model);

        // Build reasoning configuration
        $reasoning = [
            "exclude" => true,
            "enabled" => ($toggleThinking || $isAlwaysReasoning),
        ];

        if ($isOpenAIReasoning && $reasoning["enabled"]) {
            $reasoning["effort"] = $effort_level;
        } else if ($reasoning["enabled"]) {
            $reasoning["max_tokens"] = intval($thinkingTokens);
        }

        // Convert messages to simple string format for OpenAI provider only
        // Anthropic uses: {"role": "...", "content": [{"type": "text", "text": "..."}]}
        // OpenAI uses: {"role": "...", "content": "..."}
        // "None" mode keeps array structure (works via OpenRouter transformation)
        if ($this->_provider_caching === "OpenAI") {
            $finalMessagesToSend = $this->_convertToSimpleContentFormat($finalMessagesToSend);
            logMessage("[{$this->name}] Converted messages to simple content format for provider: {$this->_provider_caching}");
        }

        // Construct payload
        $data = array(
            'model' => $this->_model,
            'messages' => $finalMessagesToSend,
            'stream' => true,
            'usage' => array("include" => true),
            'temperature' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["temperature"])) ? $GLOBALS["CONNECTOR"][$this->name]["temperature"] : 1),
            'top_k' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["top_k"])) ? $GLOBALS["CONNECTOR"][$this->name]["top_k"] : 0),
            'top_p' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["top_p"])) ? $GLOBALS["CONNECTOR"][$this->name]["top_p"] : 1),
            'frequency_penalty' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["frequency_penalty"])) ? $GLOBALS["CONNECTOR"][$this->name]["frequency_penalty"] : 0),
            'presence_penalty' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["presence_penalty"])) ? $GLOBALS["CONNECTOR"][$this->name]["presence_penalty"] : 0),
            'repetition_penalty' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["repetition_penalty"])) ? $GLOBALS["CONNECTOR"][$this->name]["repetition_penalty"] : 1),
            'min_p' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["min_p"])) ? $GLOBALS["CONNECTOR"][$this->name]["min_p"] : 0),
            'top_a' => floatval((isset($GLOBALS["CONNECTOR"][$this->name]["top_a"])) ? $GLOBALS["CONNECTOR"][$this->name]["top_a"] : 0),
            'transforms' => array(),
            'stop' => array('USER')
        );

        // Only add reasoning parameter for providers/models that support it
        // Don't add for "None" mode (generic models like Palmyra don't support it)
        if ($this->_provider_caching !== "None") {
            $data['reasoning'] = $reasoning;
        }

        // Handle max tokens
        $effectiveMaxTokens = null;
        if (isset($customParms["MAX_TOKENS"])) {
            $maxTokensValue = $customParms["MAX_TOKENS"] + 0;
            if ($maxTokensValue >= 0) {
                $effectiveMaxTokens = $maxTokensValue;
            }
        } else {
            if (isset($MAX_TOKENS))
                $effectiveMaxTokens = $MAX_TOKENS;
        }
        if (isset($GLOBALS["FORCE_MAX_TOKENS"])) {
            $forceMaxTokensValue = intval($GLOBALS["FORCE_MAX_TOKENS"]);
            if ($forceMaxTokensValue >= 0) {
                $effectiveMaxTokens = $forceMaxTokensValue;
            }
        }
        if ($effectiveMaxTokens !== null) {
            if ($effectiveMaxTokens > 0) {
                $data["max_tokens"] = (int) $effectiveMaxTokens;
            } else {
                unset($data["max_tokens"]);
            }
        } else {
            if (isset($data["max_tokens"]))
                unset($data["max_tokens"]);
        }

        // Add provider information
        if (!empty($GLOBALS["CONNECTOR"][$this->name]["PROVIDER"])) {
            $providers = explode(",", $GLOBALS["CONNECTOR"][$this->name]["PROVIDER"]);
            $data["provider"] = array("order" => $providers);
        } else {
            $data["provider"] = array("order" => array("Anthropic"));
        }

        $data["transforms"] = array();

        // Add extra_parameters support (CHIM 2.4.3)
        if (isset($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"]) && is_array($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"])) {
            foreach ($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"] as $k => $v) {
                $data[$k] = $v;
            }
        }

        // Add Google safety settings if block_none is enabled in metadata (for Google models via OpenRouter)
        if (isset($GLOBALS["CONNECTOR"][$this->name]["block_none"]) && $GLOBALS["CONNECTOR"][$this->name]["block_none"]) {
            // Only add safety settings if this is a Google/Gemini model
            if (preg_match('/google|gemini/i', $this->_model)) {
                $data["safety_settings"] = [
                    ["category" => "HARM_CATEGORY_HARASSMENT", "threshold" => "BLOCK_NONE"],
                    ["category" => "HARM_CATEGORY_HATE_SPEECH", "threshold" => "BLOCK_NONE"],
                    ["category" => "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold" => "BLOCK_NONE"],
                    ["category" => "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold" => "BLOCK_NONE"]
                ];
            }
        }

        // Handle OpenAI reasoning models - special parameter handling
        if ($isOpenAIReasoning) {
            if (isset($data["max_tokens"])) {
                $data["max_completion_tokens"] = $data["max_tokens"];
                unset($data["max_tokens"]);
            }

            if ($reasoning["enabled"]) {
                $cleanedData = [
                    'model' => $data['model'],
                    'messages' => $data['messages'],
                    'stream' => $data['stream'],
                    'reasoning' => $data['reasoning']
                ];

                if (isset($data['max_completion_tokens'])) {
                    $cleanedData['max_completion_tokens'] = $data['max_completion_tokens'];
                }
                if (isset($data['provider'])) {
                    $cleanedData['provider'] = $data['provider'];
                }
                if (isset($data['transforms'])) {
                    $cleanedData['transforms'] = $data['transforms'];
                }

                $data = $cleanedData;
            }
        }

        // Log request
        if (!isset($GLOBALS["DEBUG_DATA"])) {
            $GLOBALS["DEBUG_DATA"] = array();
        }
        $GLOBALS["DEBUG_DATA"]["full"] = ($data);
        $this->_dataSent = json_encode($data, JSON_PRETTY_PRINT);

        try {
            $finalMsgCount = isset($finalMessagesToSend) ? count($finalMessagesToSend) : 0;
            $logEntry = sprintf(
                "[%s] [%s:%s]\nPayload (%d msgs):\n%s\n---\n",
                date(DATE_ATOM),
                $this->name,
                $herikaName,
                $finalMsgCount,
                var_export($data, true)
            );
            @file_put_contents(__DIR__ . "/../log/context_sent_to_llm.log", $logEntry, FILE_APPEND | LOCK_EX);
        } catch (Exception $e) {
            logMessage("Context Log Err: " . $e->getMessage());
        }

        // Prepare API request
        $apiKey = isset($GLOBALS["CONNECTOR"][$this->name]["API_KEY"]) ? $GLOBALS["CONNECTOR"][$this->name]["API_KEY"] : '';
        if (empty($apiKey)) {
            logMessage("API Key missing!");
            return null;
        }

        $headers = array(
            'Content-Type: application/json',
            "Authorization: Bearer {$apiKey}",
            "HTTP-Referer:  https://dwemerdynamics.com/",
            "X-Title: Dwemer Dynamics"
        );

        // Anthropic-specific headers for extended cache TTL
        if ($this->_provider_caching === "Anthropic") {
            $headers[] = "anthropic-beta: extended-cache-ttl-2025-04-11";
        }

        $timeout = isset($GLOBALS["HTTP_TIMEOUT"]) ? (int) $GLOBALS["HTTP_TIMEOUT"] : 60;
        $options = array(
            'http' => array(
                'method' => 'POST',
                'header' => implode("\r\n", $headers),
                'content' => json_encode($data),
                'timeout' => $timeout,
                'ignore_errors' => true
            )
        );

        $context = stream_context_create($options);

        // Initialize stream state
        $this->primary_handler = null;
        $this->_rawbuffer = "";
        $this->_buffer = "";
        $this->_forcedClose = false;
        $this->_jsonResponsesEncoded = array();

        $end_time = microtime(true);
        $execution_time = $end_time - $start_time;
        logMessage("Time for preparing cached request: $execution_time seconds");

        // Open stream
        try {
            $this->primary_handler = $this->send($this->_url, $context);
        } catch (Exception $e) {
            $errMsg = $e->getMessage();
            logMessage("fopen Exception [{$this->name}:{$herikaName}]: {$errMsg}");
            Logger::error("[{$this->name}] fopen Exception: {$errMsg}");
            // Log to output_from_llm.log for visibility
            @file_put_contents(__DIR__ . "/../log/output_from_llm.log",
                "\n== " . date(DATE_ATOM) . " EXCEPTION [{$this->name}:{$herikaName}] ==\nfopen Exception: {$errMsg}\n",
                FILE_APPEND | LOCK_EX);
            return null;
        }

        if (!$this->primary_handler) {
            $error = error_get_last();
            $errMsg = isset($error['message']) ? $error['message'] : 'fopen returned false';
            logMessage("Stream Open Fail [{$this->name}:{$herikaName}]: {$errMsg}");
            Logger::error("[{$this->name}] Stream Open Fail: {$errMsg}");
            if (isset($http_response_header) && is_array($http_response_header)) {
                logMessage("HTTP Headers on fail: " . implode("\n", $http_response_header));
            }
            // Log to output_from_llm.log for visibility
            @file_put_contents(__DIR__ . "/../log/output_from_llm.log",
                "\n== " . date(DATE_ATOM) . " ERROR [{$this->name}:{$herikaName}] ==\nStream Open Fail: {$errMsg}\n",
                FILE_APPEND | LOCK_EX);
            return null;
        }

        // Check HTTP status code - OpenRouter returns errors with 4xx/5xx status codes
        $status_code = $this->getHttpStatusCode();
        if ($status_code >= 300) {
            $response = stream_get_contents($this->primary_handler);
            $error_message = "OpenRouter request failed with status {$status_code}.\nModel: {$this->_model}\nResponse: {$response}";

            logMessage("HTTP Error [{$this->name}:{$herikaName}]: {$error_message}");
            Logger::error("[{$this->name}] {$error_message}");

            // Log to output_from_llm.log for visibility
            @file_put_contents(__DIR__ . "/../log/output_from_llm.log",
                "\n== " . date(DATE_ATOM) . " ERROR [{$this->name}:{$herikaName}] ==\n{$error_message}\n",
                FILE_APPEND | LOCK_EX);

            // Also log to audit_request table if available
            if (isset($GLOBALS["db"]) && $GLOBALS["db"]) {
                try {
                    $GLOBALS["db"]->insert('audit_request', array(
                        'request' => $this->_dataSent ?? 'unknown',
                        'result' => $error_message,
                        'connector' => $this->name,
                        'url' => $this->_url
                    ));
                } catch (Exception $e) {
                    logMessage("Could not log to audit_request: " . $e->getMessage());
                }
            }

            fclose($this->primary_handler);
            $this->primary_handler = null;
            return null;
        }

        return true;
    }

    public function send($url, $context) {
        if (isset($GLOBALS['mockConnectorSend'])) {
            return call_user_func($GLOBALS['mockConnectorSend'], $url, $context);
        }
        return fopen($url, 'r', false, $context);
    }

    public function getHttpStatusCode() {
        if (isset($GLOBALS['mockConnectorResponseMetaData'])) {
            $responseInfo = call_user_func($GLOBALS['mockConnectorResponseMetaData']);
        } else {
            $responseInfo = stream_get_meta_data($this->primary_handler);
        }

        $statusLine = $responseInfo['wrapper_data'][0];
        preg_match('/\d{3}/', $statusLine, $matches); // get three digits (200, 300, 404, etc)
        return isset($matches[0]) ? intval($matches[0]) : null;
    }
    

    public function process() {
        global $alreadysent;
        $herikaName = isset($GLOBALS["HERIKA_NAME"]) ? $GLOBALS["HERIKA_NAME"] : 'default_herika';

        if ($this->isDone()) {
            // Even if stream is done, check if there's remaining content to flush
            // This is a safety net - content should already be flushed at finish_reason/message_stop
            if ($this->_responseFormat === 'simple') {
                $flushed = $this->_flushAllRemainingSimpleFormat();
                if (!empty($flushed)) {
                    return $flushed;
                }
            } elseif ($this->_responseFormat === 'json' && !empty($this->_buffer)) {
                // For JSON format, attempt final parse of accumulated buffer
                // This catches cases where content was received but stop event came before parse
                $result = $this->_parseAndReturnContent();
                if (!empty($result)) {
                    // Clear buffer to prevent duplicate returns on subsequent calls
                    $this->_buffer = '';
                    return $result;
                }
            }
            return "";
        }

        $line = @fgets($this->primary_handler);
        if ($line === false) {
            if (feof($this->primary_handler)) {
                // Stream ended - flush ALL remaining simple format content
                if ($this->_responseFormat === 'simple') {
                    $flushed = $this->_flushAllRemainingSimpleFormat();
                    if (!empty($flushed)) {
                        return $flushed;
                    }
                }
                return "";
            } else {
                $error = error_get_last();
                $errMsg = isset($error['message']) ? $error['message'] : 'fgets error';
                logMessage("Read Err [{$this->name}:{$herikaName}]: {$errMsg}");
                Logger::error("[{$this->name}] Read Error: {$errMsg}");
                $this->_rawbuffer .= "\nRead Err: {$errMsg}\n";
                // Log to output_from_llm.log for visibility
                @file_put_contents(__DIR__ . "/../log/output_from_llm.log",
                    "\n== " . date(DATE_ATOM) . " READ ERROR [{$this->name}:{$herikaName}] ==\n{$errMsg}\n",
                    FILE_APPEND | LOCK_EX);
                $this->_forcedClose = true;
                return $errMsg;
            }
        }

        try {
            @file_put_contents(__DIR__ . "/../log/debugStream.log", $line, FILE_APPEND | LOCK_EX);
        } catch (Exception $e) {
        }

        $this->_rawbuffer .= $line;
        $buffer = "";

        if (strpos($line, 'data: ') === 0) {
            $jsonData = trim(substr($line, 6));
            if ($jsonData === '[DONE]') {
                // Stream ended with explicit DONE marker - flush ALL remaining content
                if ($this->_responseFormat === 'simple') {
                    $flushed = $this->_flushAllRemainingSimpleFormat();
                    if (!empty($flushed)) {
                        return $flushed;
                    }
                } elseif ($this->_responseFormat === 'json') {
                    // JSON format: parse and return the complete JSON message
                    $result = $this->_parseAndReturnContent();
                    if (!empty($result)) {
                        return $result;
                    }
                }
                return "";
            }

            if (!empty($jsonData)) {
                $data = json_decode($jsonData, true);
                if (json_last_error() === JSON_ERROR_NONE && is_array($data)) {
                    // Handle Anthropic format
                    if (isset($data['type'])) {
                        switch ($data['type']) {
                            case 'content_block_delta':
                                if (isset($data['delta']['type']) && $data['delta']['type'] === 'text_delta' &&
                                    isset($data['delta']['text'])) {
                                    $buffer = $data['delta']['text'];
                                    $this->_buffer .= $buffer;
                                }
                                break;

                            case 'content_block_start':
                                if (isset($data['content_block']['type']) && $data['content_block']['type'] === 'tool_use') {
                                    $this->_jsonResponsesEncoded[] = json_encode($data);
                                }
                                break;

                            case 'message_delta':
                                if (isset($data['delta']['stop_reason']) && $data['delta']['stop_reason'] !== null) {
                                    logMessage("[{$this->name}:{$herikaName}] Stop (delta): " . $data['delta']['stop_reason']);

                                    // Flush ALL remaining content before closing
                                    if ($this->_responseFormat === 'simple') {
                                        $flushed = $this->_flushAllRemainingSimpleFormat();
                                        if (!empty($flushed)) {
                                            $this->_forcedClose = true;
                                            return $flushed;
                                        }
                                    } elseif ($this->_responseFormat === 'json') {
                                        // JSON format: parse and return the complete JSON message
                                        $this->_forcedClose = true;
                                        $result = $this->_parseAndReturnContent();
                                        if (!empty($result)) {
                                            return $result;
                                        }
                                    }

                                    $this->_forcedClose = true;
                                }
                                break;

                            case 'message_stop':
                                logMessage("[{$this->name}:{$herikaName}] Stop (message_stop). Usage:" .
                                    (isset($data['message']['usage']) ? json_encode($data['message']['usage']) : 'N/A'));

                                // Log cache efficiency
                                if (isset($data['message']['usage'])) {
                                    $usage = $data['message']['usage'];
                                    $cacheRead = isset($usage['cache_read_input_tokens']) ? $usage['cache_read_input_tokens'] : 0;
                                    $cacheCreate = isset($usage['cache_creation_input_tokens']) ? $usage['cache_creation_input_tokens'] : 0;
                                    $normalInput = isset($usage['input_tokens']) ? $usage['input_tokens'] : 0;
                                    $totalConsideredInput = $cacheRead + $cacheCreate + $normalInput;
                                    $efficiency = ($totalConsideredInput > 0) ? round(($cacheRead / $totalConsideredInput * 100), 1) : 0;
                                    $logPerfEntry = sprintf(
                                        "[%s] CACHE_PERF %s: Read:%d Create:%d New:%d Total:%d Efficiency:%.1f%%\n",
                                        date(DATE_ATOM),
                                        $herikaName,
                                        $cacheRead,
                                        $cacheCreate,
                                        $normalInput,
                                        $totalConsideredInput,
                                        $efficiency
                                    );
                                    @file_put_contents(__DIR__ . DIRECTORY_SEPARATOR . "_cached_perf.log", $logPerfEntry, FILE_APPEND);
                                }

                                // Flush ALL remaining content before closing
                                if ($this->_responseFormat === 'simple') {
                                    $flushed = $this->_flushAllRemainingSimpleFormat();
                                    if (!empty($flushed)) {
                                        $this->_forcedClose = true;
                                        return $flushed;
                                    }
                                } elseif ($this->_responseFormat === 'json') {
                                    // JSON format: parse and return the complete JSON message
                                    $this->_forcedClose = true;
                                    $result = $this->_parseAndReturnContent();
                                    if (!empty($result)) {
                                        return $result;
                                    }
                                }

                                $this->_forcedClose = true;
                                break;

                            case 'error':
                                $eM = print_r((isset($data['error']) ? $data['error'] : $data), true);
                                logMessage("Stream Err (Anthropic): {$eM}");
                                Logger::error("[{$this->name}] Stream Error (Anthropic): {$eM}");
                                $this->_rawbuffer .= "\nErr (Anthropic):{$eM}\n";
                                $this->_buffer .= "\n[ERROR: {$eM}]";
                                // Log to output_from_llm.log for visibility
                                @file_put_contents(__DIR__ . "/../log/output_from_llm.log",
                                    "\n== " . date(DATE_ATOM) . " STREAM ERROR [{$this->name}:{$herikaName}] ==\n{$eM}\n",
                                    FILE_APPEND | LOCK_EX);
                                $this->_forcedClose = true;
                                return $eM;

                            case 'ping':
                                break;

                            default:
                                logMessage("[{$this->name}:{$herikaName}] Unhandled Anthropic Type: " . $data['type']);
                                break;
                        }
                    }
                    // Handle OpenAI format
                    elseif (isset($data["choices"][0]["delta"])) {
                        if (isset($data["choices"][0]["delta"]["content"])) {
                            $buffer = $data["choices"][0]["delta"]["content"];
                            $this->_buffer .= $buffer;
                        }

                        if (isset($data["choices"][0]["delta"]["tool_calls"])) {
                            $this->_jsonResponsesEncoded[] = json_encode($data);
                        }

                        if (isset($data["choices"][0]["finish_reason"]) && $data["choices"][0]["finish_reason"] !== null) {
                            logMessage("[{$this->name}:{$herikaName}] Stop (choice): " . $data["choices"][0]["finish_reason"]);

                            // CRITICAL FIX: Flush ALL remaining content at once
                            // Gemini/OpenAI format doesn't have additional events after finish_reason,
                            // so we must return all content now before _forcedClose is set
                            if ($this->_responseFormat === 'simple') {
                                $flushed = $this->_flushAllRemainingSimpleFormat();
                                if (!empty($flushed)) {
                                    $this->_forcedClose = true;
                                    return $flushed;
                                }
                            } elseif ($this->_responseFormat === 'json') {
                                // JSON format: parse and return the complete JSON message
                                $this->_forcedClose = true;
                                $result = $this->_parseAndReturnContent();
                                if (!empty($result)) {
                                    return $result;
                                }
                            }

                            $this->_forcedClose = true;
                        }

                        $this->_lastStreamedObject = $data;
                    }
                    // Generic error (OpenRouter error response in stream)
                    elseif (isset($data['error'])) {
                        $eM = print_r($data['error'], true);
                        logMessage("Stream Err (Generic): {$eM}");
                        Logger::error("[{$this->name}] Stream Error: {$eM}");
                        $this->_rawbuffer .= "\nErr (Generic):{$eM}\n";
                        $this->_buffer .= "\n[ERROR: {$eM}]";
                        // Log to output_from_llm.log for visibility
                        @file_put_contents(__DIR__ . "/../log/output_from_llm.log",
                            "\n== " . date(DATE_ATOM) . " STREAM ERROR [{$this->name}:{$herikaName}] ==\n{$eM}\n",
                            FILE_APPEND | LOCK_EX);
                        $this->_forcedClose = true;
                        return $eM;
                    }
                } else {
                    logMessage("JSON Decode Err [{$this->name}:{$herikaName}]: " . json_last_error_msg());
                }
            }
        } elseif (trim($line) === "event: message_stop") {
            logMessage("[{$this->name}:{$herikaName}] Explicit stream end event received.");

            // Flush ALL remaining content before closing
            if ($this->_responseFormat === 'simple') {
                $flushed = $this->_flushAllRemainingSimpleFormat();
                if (!empty($flushed)) {
                    $this->_forcedClose = true;
                    return $flushed;
                }
            } elseif ($this->_responseFormat === 'json') {
                // JSON format: parse and return the complete JSON message
                $this->_forcedClose = true;
                $result = $this->_parseAndReturnContent();
                if (!empty($result)) {
                    return $result;
                }
            }

            $this->_forcedClose = true;
        }

        // Parse and return content based on format
        if (!empty($buffer)) {
            return $this->_parseAndReturnContent();
        }

        return "";
    }

    // ================================================================================
    // SIMPLE FORMAT PARSER METHODS (for response_format = 'simple')
    // These methods implement the sentence streaming algorithm for non-JSON responses
    // ================================================================================

    /**
     * Preprocesses reasoning tags in the buffer (Step 0 of simple format algorithm)
     * Strips <think>, <thinking>, and <answer> tags from the buffer
     * Returns false when waiting for closing tag (signals caller to wait for more data)
     */
    private function _preprocessReasoningTags() {
        // Check for orphaned closing tag (prefill case)
        if ($this->_reasoningState === 'NORMAL') {
            if (preg_match('/<\/(think|thinking)>/', $this->_buffer, $matches, PREG_OFFSET_CAPTURE)) {
                $closePos = $matches[0][1];
                $closeLen = strlen($matches[0][0]);
                $this->_buffer = substr($this->_buffer, $closePos + $closeLen);
                logMessage("[{$this->name}] Stripped orphaned closing tag (prefill case)");
            }
        }

        // State machine for reasoning tags
        while (true) {
            if ($this->_reasoningState === 'WAITING_FOR_REASONING_CLOSE') {
                $closeTag = '</' . $this->_reasoningTagType . '>';
                $closePos = strpos($this->_buffer, $closeTag);

                if ($closePos !== false) {
                    $this->_buffer = substr($this->_buffer, $closePos + strlen($closeTag));
                    logMessage("[{$this->name}] Stripped reasoning block: <{$this->_reasoningTagType}>...</{$this->_reasoningTagType}>");
                    $this->_reasoningState = 'NORMAL';
                    $this->_reasoningTagType = '';
                } else {
                    return false; // Still waiting for closing tag
                }
            } else { // NORMAL state
                if (preg_match('/^<(think|thinking)>/i', $this->_buffer, $matches)) {
                    $this->_reasoningTagType = strtolower($matches[1]);
                    $this->_reasoningState = 'WAITING_FOR_REASONING_CLOSE';
                    logMessage("[{$this->name}] Detected reasoning tag opening: <{$this->_reasoningTagType}>");
                } else {
                    break; // No reasoning tag at start, exit loop
                }
            }
        }

        // Strip answer tags (preserve content)
        $beforeAnswerStrip = $this->_buffer;
        $this->_buffer = preg_replace('/<answer>(.*?)<\/answer>/is', '$1', $this->_buffer);
        if ($beforeAnswerStrip !== $this->_buffer) {
            logMessage("[{$this->name}] Stripped <answer> tags, preserved content");
        }

        return true; // Ready to continue
    }

    /**
     * Extracts metadata from normalized buffer (Step 4 of simple format algorithm)
     * Searches for (mood)(listener)(action)(target) pattern at start
     * Returns array with 'found', 'metadataEnd', and 'groups' keys
     */
    private function _extractMetadata($normalizedBuffer) {
        // Check if all fields disabled - no metadata expected
        if (!$this->_includeMood && !$this->_includeListener &&
            !$this->_includeActions && !$this->_includeTarget) {
            return [
                'found' => true,
                'metadataEnd' => 0,
                'groups' => []
            ];
        }

        // Find consecutive (...) at start
        if (!preg_match('/^\s*(?:\([^)]*\)\s*)+/', $normalizedBuffer, $match)) {
            return ['found' => false];
        }

        $metadataSection = $match[0];
        $metadataEnd = strlen($metadataSection);
        $potentialMessage = substr($normalizedBuffer, $metadataEnd);

        // Search for at least one complete sentence in message
        if (!preg_match('/\.\.\.(?:\s+|$)|[.!?](?:\s+|$)/', $potentialMessage)) {
            return ['found' => false]; // No sentence yet, wait
        }

        // Extract groups from metadata section
        preg_match_all('/\(([^)]*)\)/', $metadataSection, $matches);

        return [
            'found' => true,
            'metadataEnd' => $metadataEnd,
            'groups' => $matches[1]
        ];
    }

    /**
     * Maps extracted metadata groups to global fields
     * Handles: mood -> animations, listener, action + target -> commands
     */
    private function _mapGroupsToFields($groups) {
        $idx = 0;

        // Map mood
        if ($this->_includeMood && isset($groups[$idx])) {
            $mood = trim($groups[$idx++]);
            if ($mood !== '') {
                $GLOBALS["SCRIPTLINE_ANIMATION"] = function_exists('GetAnimationHex')
                    ? GetAnimationHex($mood) : '';
                $GLOBALS["SCRIPTLINE_EXPRESSION"] = function_exists('GetExpression')
                    ? GetExpression($mood) : '';
            }
        }

        // Map listener
        if ($this->_includeListener && isset($groups[$idx])) {
            $listener = trim($groups[$idx++]);
            if ($listener !== '') {
                $GLOBALS["SCRIPTLINE_LISTENER"] = $listener;
            }
        }

        // Map action and target
        if ($this->_includeActions && isset($groups[$idx])) {
            $action = trim($groups[$idx++]);
            if ($action !== '' && strcasecmp($action, 'Talk') !== 0) {
                $action = validateActionName($action);
                $target = $this->_includeTarget && isset($groups[$idx])
                    ? trim($groups[$idx])
                    : $this->_defaultTarget;
                $character = $GLOBALS["HERIKA_NAME"] ?? 'Herika';
                $commandKey = md5("{$character}|command|{$action}@{$target}\r\n");
                if (!isset($GLOBALS['alreadysent'][$commandKey])) {
                    $func = function_exists('getFunctionCodeName')
                        ? getFunctionCodeName($action)
                        : $action;
                    $cmd = "{$character}|command|{$func}@{$target}\r\n";
                    $this->_commandBuffer[] = $cmd;
                    $GLOBALS['alreadysent'][$commandKey] = $cmd;
                }
            }
        }
    }

    /**
     * Flushes remaining content when stream ends
     * Returns complete sentences first, then trailing partial with added period
     */
    private function _flushRemainingSimpleFormat() {
        if ($this->_metadataEnd === -1) {
            logMessage("[{$this->name}] Flush: No metadata extracted, nothing to flush");
            return "";
        }

        // Normalize buffer for prefill
        $normalizedBuffer = $this->_buffer;
        if ($this->_usedPrefill && !empty($normalizedBuffer) && $normalizedBuffer[0] !== '(') {
            $normalizedBuffer = '(' . $normalizedBuffer;
        }

        // Extract message portion
        $message = substr($normalizedBuffer, $this->_metadataEnd);
        logMessage("[{$this->name}] Flush: Message length=" . strlen($message));

        // Split into sentences
        $sentences = $this->_splitIntoSentences($message);
        logMessage("[{$this->name}] Flush: Found " . count($sentences) . " sentences, sent " . $this->_sentencesSent);

        // First: Flush unsent complete sentences
        if ($this->_sentencesSent < count($sentences)) {
            $sentence = $sentences[$this->_sentencesSent];
            $this->_sentencesSent++;
            logMessage("[{$this->name}] Flushing sentence #{$this->_sentencesSent}");
            return $sentence . ' ';  // BUG FIX: Add trailing space
        }

        // Second: Flush trailing partial (once)
        if (!$this->_flushedPartial) {
            $this->_flushedPartial = true;

            if (preg_match_all('/[.!?…]/', $message, $matches, PREG_OFFSET_CAPTURE)) {
                $lastMatch = end($matches[0]);
                $lastPunctPos = $lastMatch[1];
                $partial = trim(substr($message, $lastPunctPos + 1));
            } else {
                $partial = trim($message);
            }

            if (!empty($partial) && !preg_match('/[.!?…]$/', $partial)) {
                $partial .= '.';
                logMessage("[{$this->name}] Flushing trailing partial: " . substr($partial, 0, 50));
                return $partial . ' ';  // BUG FIX: Add trailing space
            }
        }

        return "";
    }

    /**
     * Flushes ALL remaining simple format content at once.
     * Used when stream definitively ends to prevent content loss when caller stops
     * calling process() after isDone() returns true.
     *
     * CRITICAL FIX for Gemini response cutoffs: Unlike _flushRemainingSimpleFormat()
     * which returns one sentence at a time, this returns ALL remaining content
     * concatenated, ensuring nothing is lost when the stream ends.
     */
    private function _flushAllRemainingSimpleFormat() {
        if ($this->_metadataEnd === -1) {
            logMessage("[{$this->name}] FlushAll: No metadata extracted, nothing to flush");
            return "";
        }

        // Normalize buffer for prefill
        $normalizedBuffer = $this->_buffer;
        if ($this->_usedPrefill && !empty($normalizedBuffer) && $normalizedBuffer[0] !== '(') {
            $normalizedBuffer = '(' . $normalizedBuffer;
        }

        // Extract message portion
        $message = substr($normalizedBuffer, $this->_metadataEnd);

        // Split into sentences
        $sentences = $this->_splitIntoSentences($message);
        logMessage("[{$this->name}] FlushAll: Found " . count($sentences) . " sentences, sent " . $this->_sentencesSent);

        // Collect ALL unsent sentences
        $allRemaining = "";
        while ($this->_sentencesSent < count($sentences)) {
            $sentence = $sentences[$this->_sentencesSent];
            $this->_sentencesSent++;
            $allRemaining .= $sentence . ' ';
        }

        // Also add trailing partial if any
        if (!$this->_flushedPartial) {
            $this->_flushedPartial = true;

            if (preg_match_all('/[.!?…]/', $message, $matches, PREG_OFFSET_CAPTURE)) {
                $lastMatch = end($matches[0]);
                $lastPunctPos = $lastMatch[1];
                $partial = trim(substr($message, $lastPunctPos + 1));
            } else {
                $partial = trim($message);
            }

            if (!empty($partial) && !preg_match('/[.!?…]$/', $partial)) {
                $partial .= '.';
                $allRemaining .= $partial . ' ';
            }
        }

        if (!empty($allRemaining)) {
            logMessage("[{$this->name}] FlushAll: Returning all remaining: " . strlen($allRemaining) . " chars");
        }

        return $allRemaining;
    }

    /**
     * Splits message into complete sentences (Step 7 of simple format algorithm)
     * Uses sentence-ending punctuation followed by whitespace as delimiters
     */
    private function _splitIntoSentences($text) {
        // Split on sentence endings followed by whitespace
        $parts = preg_split('/(?<=\.\.\.)\s+|(?<=[.!?])\s+/', $text, -1, PREG_SPLIT_NO_EMPTY);

        logMessage("[{$this->name}] _splitIntoSentences: Split into " . count($parts) . " parts");

        // Filter: keep only sentences ending with punctuation
        $sentences = [];
        foreach ($parts as $part) {
            $part = trim($part);
            if (preg_match('/[.!?…]+$/', $part)) {
                $sentences[] = $part;
            }
        }

        return $sentences;
    }

    /**
     * Unified content parsing dispatcher - handles both JSON and simple formats
     * Called by process() to parse and return content appropriately
     */
    private function _parseAndReturnContent() {
        if ($this->_responseFormat === 'json') {
            // JSON format parsing
            $extracted_json_or_text = extractJson($this->_buffer);
            $tempJson = json_decode($extracted_json_or_text, true);

            if (json_last_error() === JSON_ERROR_NONE && isset($tempJson['message']) && !empty($tempJson['message'])) {
                if (isset($tempJson["mood"])) {
                    $GLOBALS["SCRIPTLINE_ANIMATION"] = function_exists('GetAnimationHex') ? GetAnimationHex($tempJson["mood"]) : '';
                    $GLOBALS["SCRIPTLINE_EXPRESSION"] = function_exists('GetExpression') ? GetExpression($tempJson["mood"]) : '';
                }
                if (isset($tempJson["listener"])) {
                    if (isset($tempJson["action"]) && ($tempJson["action"] == "Talk") &&
                        function_exists('lazyEmpty') && lazyEmpty($tempJson["listener"]) && !lazyEmpty($tempJson["target"])) {
                        $GLOBALS["SCRIPTLINE_LISTENER"] = $tempJson["target"];
                    } else {
                        $GLOBALS["SCRIPTLINE_LISTENER"] = $tempJson["listener"];
                    }
                }
                // Strip any reasoning tokens from final message
                if (function_exists('stripReasoningTokens')) {
                    return stripReasoningTokens($tempJson['message']);
                }
                return $tempJson['message'];
            }
        } else {
            // SIMPLE FORMAT PARSER

            // Step 0: Preprocess reasoning tags
            if (!$this->_preprocessReasoningTags()) {
                return ""; // Waiting for reasoning closing tag
            }

            // Step 3: Normalize for prefill
            $normalizedBuffer = $this->_buffer;
            if ($this->_usedPrefill && !empty($normalizedBuffer) && $normalizedBuffer[0] !== '(') {
                $normalizedBuffer = '(' . $normalizedBuffer;
            }

            // Step 4: Extract metadata section (one-time)
            if ($this->_metadataEnd === -1) {
                $result = $this->_extractMetadata($normalizedBuffer);

                if (!$result['found']) {
                    // Step 5: Timeout fallback if buffer too large
                    if (strlen($normalizedBuffer) > 100) {
                        logMessage("[{$this->name}] Simple format timeout - LLM didn't follow format");
                        $parts = preg_split('/(?<=\.\.\.)\s+|(?<=[.!?])\s+/', $normalizedBuffer, -1, PREG_SPLIT_NO_EMPTY);
                        $sentences = [];
                        foreach ($parts as $part) {
                            $part = trim($part);
                            if (preg_match('/[.!?…]+$/', $part)) {
                                $sentences[] = $part;
                            }
                        }
                        $this->_metadataEnd = 0;
                        $this->_sentencesSent = 0;

                        if (!empty($sentences)) {
                            $this->_sentencesSent = 1;
                            return $sentences[0] . ' ';  // BUG FIX: Add trailing space
                        }
                    }
                    return ""; // Wait for more chunks
                }

                // Metadata found!
                $this->_metadataEnd = $result['metadataEnd'];
                $this->_metadataGroups = $result['groups'];
                $this->_mapGroupsToFields($result['groups']);
                logMessage("[{$this->name}] Metadata extracted: groups=" . count($result['groups']));
            }

            // Step 6: Extract message portion
            $message = substr($normalizedBuffer, $this->_metadataEnd);

            // Step 7: Split into sentences
            $sentences = $this->_splitIntoSentences($message);

            // Step 8: Return next unsent sentence
            if ($this->_sentencesSent < count($sentences)) {
                $sentence = $sentences[$this->_sentencesSent];
                $this->_sentencesSent++;
                logMessage("[{$this->name}] Returning sentence #{$this->_sentencesSent}");
                return $sentence . ' ';  // BUG FIX: Add trailing space
            }

            return "";
        }

        return "";
    }

    // ================================================================================
    // END SIMPLE FORMAT PARSER METHODS
    // ================================================================================

    // Method to close the data processing operation
    public function close($callName = '') {
        if ($this->primary_handler) {
            @fclose($this->primary_handler);
            $this->primary_handler = null;
        }

        $herikaName = isset($GLOBALS["HERIKA_NAME"]) ? $GLOBALS["HERIKA_NAME"] : 'default_herika';
        // $callName parameter available for logging purposes (matching CHIM 2.3.3 signature)

        try {
            $proc = isset($this->_buffer) ? $this->_buffer : '<empty>';
            $jsonResponses = isset($this->_jsonResponsesEncoded) && is_array($this->_jsonResponsesEncoded) ?
                implode("\n", $this->_jsonResponsesEncoded) : "<no JSON responses>";

            $logContent = sprintf(
                "Processed Text:\n%s\n\nJSON Responses:\n%s\n\n[%s] [%s:%s] END STREAM\n==\n",
                $proc,
                $jsonResponses,
                date(DATE_ATOM),
                $this->name,
                $herikaName
            );

            @file_put_contents(__DIR__ . "/../log/output_from_llm.log", $logContent, FILE_APPEND | LOCK_EX);
        } catch (Exception $e) {
            logMessage("[{$this->name}:{$herikaName}] Close Log Err: " . $e->getMessage());
        }

        $this->_rawbuffer = "";
        $this->_forcedClose = false;

        return "";
    }

   

    // Method to process actions from LLM response - supports both JSON and simple formats
    public function processActions()
    {
        global $alreadysent;
        $this->_commandBuffer = isset($this->_commandBuffer) ? $this->_commandBuffer : array();
        $herikaName = isset($GLOBALS["HERIKA_NAME"]) ? $GLOBALS["HERIKA_NAME"] : 'default_herika';

        logMessage("[{$this->name}:{$herikaName}] processActions: responseFormat={$this->_responseFormat}");

        // Handle simple format action processing
        if ($this->_responseFormat === 'simple') {
            $parsed = extractSimpleFormatFromBuffer(
                $this->_buffer,
                $this->_includeMood,
                $this->_includeListener,
                $this->_includeActions,
                $this->_includeTarget
            );

            if ($parsed['found'] && $this->_includeActions && !empty($parsed['action'])) {
                $action = validateActionName($parsed['action']);
                $target = $this->_includeTarget && !empty($parsed['target']) ? $parsed['target'] : $this->_defaultTarget;
                $character = $herikaName;

                $commandKey = md5("{$character}|command|{$action}@{$target}\r\n");

                if (!isset($alreadysent[$commandKey]) || empty($alreadysent[$commandKey])) {
                    $functionCodeName = function_exists('getFunctionCodeName') ? getFunctionCodeName($action) : $action;
                    $functionCodeName = empty($functionCodeName) ? $action : $functionCodeName;

                    $commandString = "{$character}|command|{$functionCodeName}@{$target}\r\n";
                    $this->_commandBuffer[] = $commandString;
                    $alreadysent[$commandKey] = $commandString;

                    logMessage("[{$this->name}:{$herikaName}] Generated command from simple format: {$commandString}");
                }
            }

            $this->_jsonResponsesEncoded = array();

            if (!empty($this->_commandBuffer)) {
                logMessage("[{$this->name}:{$herikaName}] Final Command Buffer: " . implode(", ", $this->_commandBuffer));
            } else {
                logMessage("[{$this->name}:{$herikaName}] No commands generated.");
            }

            return empty($this->_commandBuffer) ? array() : $this->_commandBuffer;
        }

        // JSON format action processing (CHIM 2.2 style with multi-param support)
        if ($this->_functionName) {
            Logger::info("Old function scheme");
            $parameterArr = json_decode($this->_parameterBuff, true);
            if (is_array($parameterArr)) {
                $parameter = current($parameterArr); // Only support for one parameter

                if (!isset($alreadysent[md5("{$GLOBALS["HERIKA_NAME"]}|command|{$this->_functionName}@$parameter\r\n")])) {
                    $functionCodeName=getFunctionCodeName($this->_functionName);
                    $this->_commandBuffer[]="{$GLOBALS["HERIKA_NAME"]}|command|$functionCodeName@$parameter\r\n";
                    //echo "Herika|command|$functionCodeName@$parameter\r\n";

                }

                $alreadysent[md5("{$GLOBALS["HERIKA_NAME"]}|command|{$this->_functionName}@$parameter\r\n")] = "{$GLOBALS["HERIKA_NAME"]}|command|{$this->_functionName}@$parameter\r\n";
                if (ob_get_level()) @ob_flush();
            } else 
                return null;
        } else {
            $GLOBALS["DEBUG_DATA"]["RAW"]=$this->_buffer;
            unset($GLOBALS["_JSON_BUFFER"]);
            $parsedResponse=__jpd_decode_lazy($this->_buffer);   // USE JPD_LAZY?
            //error_log("New function scheme");
            if (is_array($parsedResponse)) {
                //error_log("New function scheme: ".print_r($this->_buffer,true));

                if (isset($parsedResponse[0]["action"])) {
                    $parsedResponse=$parsedResponse[0];
                }

                if (!isset($parsedResponse["target"]))    
                    $parsedResponse["target"] = "";
                
                // Build parameter string - use JSON for functions with multiple parameters
                $functionDef=findFunctionByName(trim($parsedResponse["action"]));
                $paramString = "";
                $functionCodeName = "";
                if (isset($functionDef)) {
                    $functionCodeName=getFunctionCodeName($parsedResponse["action"]);
                    $paramCount = count($functionDef["parameters"]["properties"] ?? []);
                    
                    // For functions with multiple parameters, send as JSON
                    if ($paramCount > 1) {
                        $params = [];
                        foreach (array_keys($functionDef["parameters"]["properties"] ?? []) as $paramName) {
                            if (isset($parsedResponse[$paramName])) {
                                $params[$paramName] = $parsedResponse[$paramName];
                            }
                        }
                        
                        // Check if required parameters are missing
                        $requiredParams = $functionDef["parameters"]["required"] ?? [];
                        $missingParams = [];
                        foreach ($requiredParams as $reqParam) {
                            if (!isset($params[$reqParam]) || $params[$reqParam] === "") {
                                $missingParams[] = $reqParam;
                            }
                        }
                        
                        if (!empty($missingParams)) {
                            Logger::warn("openrouterjson: Missing required parameters for {$functionCodeName}: " . implode(", ", $missingParams) . ". Skipping command.");
                            // Skip this command by setting action to empty
                            $parsedResponse["action"] = "";
                            $functionCodeName = "";
                        } else {
                            $paramString = json_encode($params);
                            Logger::info("openrouterjson: Multi-param function {$functionCodeName}, params: {$paramString}");
                        }
                    } else {
                        // Legacy: single parameter as plain string
                        $paramString = $parsedResponse["target"] ?? "";
                    }
                } else {
                    $paramString = $parsedResponse["target"] ?? "";
                    $functionCodeName = $parsedResponse["action"] ?? "";
                }
                
                $commandStr = "{$GLOBALS["HERIKA_NAME"]}|command|$functionCodeName@{$paramString}\r\n";
                Logger::info("openrouterjson: Sending command: {$commandStr}");
                if (!empty($parsedResponse["action"])) {
                    if (!isset($alreadysent[md5($commandStr)])) {
                        
                        if (isset($functionDef)) {
                            if (strlen($functionDef["parameters"]["required"][0] ?? '')>0) {
                                if (!empty($paramString)) {
                                    $this->_commandBuffer[]=$commandStr;
                                }
                                else {
                                    $this->_commandBuffer[]="{$GLOBALS["HERIKA_NAME"]}|command|$functionCodeName@\r\n";
                                    Logger::warn("openrouterjson: Missing required parameter: target");
                                    // Change. we allow this. Post filter maybe can fix.
                                }
                                    
                            } else {
                                $this->_commandBuffer[]=$commandStr;
                            }
                        } elseif ($parsedResponse["action"] != "Talk") {
                            Logger::warn("openrouterjson: Function not found for {$parsedResponse["action"]}");
                        }
                        
                        $alreadysent[md5($commandStr)]=end($this->_commandBuffer);
                    
                    } else {
                         Logger::warn("openrouterjson: Function not found for {$parsedResponse["action"]} already sent");
                    }
                        
                }
                
                if (ob_get_level()) @ob_flush();
            } else {
                Logger::info("No actions");
                return [];
            }
        }

        //print_r($parsedResponse);
        Logger::info("openrouterjson: Returning command buffer with " . count($this->_commandBuffer) . " commands");
        if (!empty($this->_commandBuffer)) {
            foreach ($this->_commandBuffer as $cmd) {
                Logger::info("openrouterjson: Buffer contains: {$cmd}");
            }
        }
        return $this->_commandBuffer;
    }

    public function isDone()
    {
        if ($this->_forcedClose)
            return true;
        return !$this->primary_handler || feof($this->primary_handler);
    }

    public function setDone()
    {
        $this->_forcedClose=true;
    }

    /**
     * Converts messages from Anthropic content block format to simple string format.
     * Anthropic format: {"role": "...", "content": [{"type": "text", "text": "..."}]}
     * Simple format:    {"role": "...", "content": "..."}
     *
     * Used for OpenAI and "None" (generic) cache providers that don't support
     * Anthropic-style content blocks.
     *
     * @param array $messages Array of message objects
     * @return array Converted messages with simple string content
     */
    private function _convertToSimpleContentFormat($messages) {
        $converted = [];

        foreach ($messages as $msg) {
            $newMsg = $msg;

            if (isset($msg['content']) && is_array($msg['content'])) {
                // Check if it's an array of content blocks (Anthropic format)
                // vs a simple array of strings (which some code might produce)
                $textParts = [];

                foreach ($msg['content'] as $block) {
                    if (is_array($block)) {
                        if (isset($block['type']) && $block['type'] === 'text' && isset($block['text'])) {
                            $textParts[] = $block['text'];
                        } elseif (isset($block['text'])) {
                            // Block without type but has text
                            $textParts[] = $block['text'];
                        }
                        // Skip cache_control and other non-text fields
                    } elseif (is_string($block)) {
                        // Simple string in array
                        $textParts[] = $block;
                    }
                }

                // Join all text parts with newlines
                $newMsg['content'] = implode("\n", $textParts);
            }
            // If content is already a string, leave it as-is

            $converted[] = $newMsg;
        }

        return $converted;
    }

    /**
     * Non-streaming request method for compatibility with summary/profile connectors.
     * This allows the cached connector to be used for CORE_CONNECTOR_MEDIUMTERM,
     * CORE_CONNECTOR_SUMMARY, and other non-streaming use cases.
     *
     * @param array $contextData The context/messages to send
     * @param array $customParms Custom parameters (MAX_TOKENS, model, temperature, etc.)
     * @param string $callName Optional call name for logging
     * @return string The LLM response text, or empty string on error
     */
    public function fast_request($contextData, $customParms, $callName = '')
    {
        // Initialize URL
        $this->_url = isset($GLOBALS["CONNECTOR"][$this->name]["url"]) ? $GLOBALS["CONNECTOR"][$this->name]["url"] : '';
        if (empty($this->_url)) {
            logMessage("{$this->name} connector - missing url!");
            return "";
        }

        // Initialize model
        $this->_model = isset($GLOBALS["CONNECTOR"][$this->name]["model"]) ? $GLOBALS["CONNECTOR"][$this->name]["model"] : 'anthropic/claude-3-haiku-20240307';
        if (isset($customParms["model"])) {
            $this->_model = $customParms["model"];
        }

        // Detect model types
        $this->_is_reasoning = $this->isReasoningModel($this->_model);
        $this->_is_openai = $this->isOpenAIModel($this->_model);
        $this->_is_grok = (stripos($this->_model, 'grok') !== false);

        if (empty($callName)) {
            $callName = $this->name;
        } else {
            $callName = $this->name . "/" . $callName;
        }

        // Get max tokens
        $MAX_TOKENS = intval(isset($GLOBALS["CONNECTOR"][$this->name]["max_tokens"]) ? $GLOBALS["CONNECTOR"][$this->name]["max_tokens"] : 48);
        if (isset($customParms["MAX_TOKENS"])) {
            $MAX_TOKENS = intval($customParms["MAX_TOKENS"]);
            unset($customParms["MAX_TOKENS"]);
        }
        if (isset($GLOBALS["FORCE_MAX_TOKENS"])) {
            $MAX_TOKENS = intval($GLOBALS["FORCE_MAX_TOKENS"]);
        }

        // Get parameters with defaults
        $temperature = floatval(isset($GLOBALS["CONNECTOR"][$this->name]["temperature"]) ? $GLOBALS["CONNECTOR"][$this->name]["temperature"] : 0.7);
        $temperature = max(0.0, min(2.0, $temperature));

        $presence_penalty = floatval(isset($GLOBALS["CONNECTOR"][$this->name]["presence_penalty"]) ? $GLOBALS["CONNECTOR"][$this->name]["presence_penalty"] : 0.0);
        $presence_penalty = max(-2.0, min(2.0, $presence_penalty));

        $frequency_penalty = floatval(isset($GLOBALS["CONNECTOR"][$this->name]["frequency_penalty"]) ? $GLOBALS["CONNECTOR"][$this->name]["frequency_penalty"] : 0.0);
        $frequency_penalty = max(-2.0, min(2.0, $frequency_penalty));

        $repetition_penalty = floatval(isset($GLOBALS["CONNECTOR"][$this->name]["repetition_penalty"]) ? $GLOBALS["CONNECTOR"][$this->name]["repetition_penalty"] : 0.0);
        $repetition_penalty = max(0.0, min(2.0, $repetition_penalty));

        $top_p = floatval(isset($GLOBALS["CONNECTOR"][$this->name]["top_p"]) ? $GLOBALS["CONNECTOR"][$this->name]["top_p"] : 1.0);
        $top_p = max(0.0, min(1.0, $top_p));

        $min_p = floatval(isset($GLOBALS["CONNECTOR"][$this->name]["min_p"]) ? $GLOBALS["CONNECTOR"][$this->name]["min_p"] : 0.0);
        $min_p = max(0.0, min(1.0, $min_p));

        $top_a = floatval(isset($GLOBALS["CONNECTOR"][$this->name]["top_a"]) ? $GLOBALS["CONNECTOR"][$this->name]["top_a"] : 0.0);
        $top_a = max(0.0, min(1.0, $top_a));

        $top_k = intval(isset($GLOBALS["CONNECTOR"][$this->name]["top_k"]) ? $GLOBALS["CONNECTOR"][$this->name]["top_k"] : 0);
        $top_k = max(0, $top_k);

        // Build request data
        $data = array(
            'model' => $this->_model,
            'messages' => $contextData,
            'stream' => false,
            'usage' => ["include" => true],
            'max_tokens' => $MAX_TOKENS,
            'temperature' => $temperature,
            'top_k' => $top_k,
            'top_p' => $top_p,
            'min_p' => $min_p,
            'top_a' => $top_a,
            'presence_penalty' => $presence_penalty,
            'frequency_penalty' => $frequency_penalty,
            'repetition_penalty' => $repetition_penalty,
            'stop' => ['USER'],
            'transforms' => []
        );

        // Handle custom stop sequences
        if (isset($GLOBALS["CONNECTOR"][$this->name]["stop"]) && sizeof($GLOBALS["CONNECTOR"][$this->name]["stop"]) > 0) {
            $data["stop"] = $GLOBALS["CONNECTOR"][$this->name]["stop"];
        }

        // Handle reasoning models
        if ($this->_is_reasoning) {
            $data["reasoning"] = array('exclude' => true, 'enabled' => false);
            if (stripos($this->_model, "qwen3-") !== false) {
                $data["enable_thinking"] = false;
            }
        }

        // Handle OpenAI models
        if ($this->_is_openai) {
            $data['max_completion_tokens'] = $MAX_TOKENS;
            unset($data['max_tokens']);
            if ($this->_is_reasoning) {
                $data["reasoning"] = array('exclude' => true, 'effort' => 'low');
            }
        }

        // Handle Grok models (no stop param)
        if ($this->_is_grok) {
            unset($data["stop"]);
        }

        // Handle max_tokens edge cases
        if ($MAX_TOKENS < 1) {
            unset($data["max_completion_tokens"]);
            unset($data["max_tokens"]);
        }

        // Add provider if configured
        if (!empty($GLOBALS["CONNECTOR"][$this->name]["PROVIDER"])) {
            $providers = explode(",", $GLOBALS["CONNECTOR"][$this->name]["PROVIDER"]);
            $data["provider"] = ["order" => $providers];
        }

        // Apply custom parameters
        foreach ($customParms as $parm => $value) {
            $data[$parm] = $value;
        }

        $data["transforms"] = [];

        // Add extra_parameters support (CHIM 2.4.3)
        if (isset($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"]) && is_array($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"])) {
            foreach ($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"] as $k => $v) {
                $data[$k] = $v;
            }
        }

        // Add Google safety settings if block_none is enabled in metadata (for Google models via OpenRouter)
        if (isset($GLOBALS["CONNECTOR"][$this->name]["block_none"]) && $GLOBALS["CONNECTOR"][$this->name]["block_none"]) {
            // Only add safety settings if this is a Google/Gemini model
            if (preg_match('/google|gemini/i', $this->_model)) {
                $data["safety_settings"] = [
                    ["category" => "HARM_CATEGORY_HARASSMENT", "threshold" => "BLOCK_NONE"],
                    ["category" => "HARM_CATEGORY_HATE_SPEECH", "threshold" => "BLOCK_NONE"],
                    ["category" => "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold" => "BLOCK_NONE"],
                    ["category" => "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold" => "BLOCK_NONE"]
                ];
            }
        }

        $GLOBALS["DEBUG_DATA"]["full"] = $data;

        // Set up HTTP request
        $headers = array(
            'Content-Type: application/json',
            "Authorization: Bearer {$GLOBALS["CONNECTOR"][$this->name]["API_KEY"]}",
            "HTTP-Referer:  https://dwemerdynamics.com/",
            "X-Title: Dwemer Dynamics"
        );

        $options = array(
            'http' => array(
                'method' => 'POST',
                'header' => implode("\r\n", $headers),
                'content' => json_encode($data),
                'timeout' => isset($GLOBALS["HTTP_TIMEOUT"]) ? (int)$GLOBALS["HTTP_TIMEOUT"] : 30
            )
        );

        $context = stream_context_create($options);

        @file_put_contents(__DIR__ . "/../log/context_sent_to_llm_fast.log", date(DATE_ATOM) . "\n=\n" . var_export($data, true) . "\n=\n", FILE_APPEND);

        try {
            $json_response = file_get_contents($this->_url, false, $context);
            if ($json_response === false) {
                $error = error_get_last();
                error_log("Error fetching response from URL: " . $this->_url . ". Error: " . $error['message']);
            }
        } catch (Exception $e) {
            error_log("Exception occurred while fetching response from URL: " . $this->_url . ". Exception: " . $e->getMessage());
            $json_response = false;
        }

        @file_put_contents(__DIR__ . "/../log/output_from_llm_fast.log", date(DATE_ATOM) . "\n=\n{$json_response}\n=\n", FILE_APPEND);

        if ($json_response) {
            $text_response = json_decode($json_response, true);

            if (is_array($text_response) && isset($text_response["choices"][0]["message"]["content"])) {
                if (isset($GLOBALS["db"]) && $GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                        'audit_request',
                        array(
                            'request' => json_encode($data),
                            'result' => "Ok",
                            'usage' => json_encode(isset($text_response["usage"]) ? $text_response["usage"] : []),
                            'connector' => $callName,
                            'url' => $this->_url
                        )
                    );
                }
                $content = $text_response["choices"][0]["message"]["content"];
                // Strip reasoning tokens if present
                if (function_exists('stripReasoningTokens')) {
                    $content = stripReasoningTokens($content);
                }
                return $content;
            } else {
                if (isset($GLOBALS["db"]) && $GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                        'audit_request',
                        array(
                            'request' => json_encode($data),
                            'result' => "ERROR|INVALID JSON RESPONSE",
                            'connector' => $callName,
                            'url' => $this->_url
                        )
                    );
                }
                error_log("Error in openrouter cached request: $json_response");
                return "";
            }
        } else {
            if (isset($GLOBALS["db"]) && $GLOBALS["db"]) {
                $GLOBALS["db"]->insert(
                    'audit_request',
                    array(
                        'request' => json_encode($data),
                        'result' => "ERROR|NO RESPONSE",
                        'connector' => $this->name,
                        'url' => $this->_url
                    )
                );
            }
        }

        return "";
    }

}

