<?php

$enginePath = dirname((__FILE__)) . DIRECTORY_SEPARATOR."..".DIRECTORY_SEPARATOR;
require_once($enginePath . "lib" .DIRECTORY_SEPARATOR."tokenizer_helper_functions.php");

// Cached version of openrouterjson connector with Anthropic/OpenAI/Gemini cache support
// Based on CHIM 2.2 architecture with additional caching and response format features

class openrouterjsoncached
{
    // Version tracking - update after making changes
    const VERSION = 'OpenRouter Cache Connector v2.0 for CHIM 2.2 | 2026/01/28';
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

    private function init_connector($customParms) {
        $this->_url = (isset($GLOBALS["CONNECTOR"][$this->name]["url"])) ? $GLOBALS["CONNECTOR"][$this->name]["url"] : "";
        if (strlen($this->_url) < 6)
            Logger::error("{$this->name} connector - missing url!");

        $this->_remove_cot = (isset($GLOBALS["CONNECTOR"][$this->name]["remove_chain_of_thought"])) ? $GLOBALS["CONNECTOR"][$this->name]["remove_chain_of_thought"] : true;
        $this->_disable_reasoning = ($GLOBALS["CONNECTOR"][$this->name]["disable_model_reasoning"] ?? true);

        $default_model = 'meta-llama/llama-3.3-70b-instruct';

        $s_fallback = trim($GLOBALS["CONNECTOR"][$this->name]["fallback_models"] ?? ""); //"google/gemini-2.0-flash-001,google/gemini-2.5-flash-lite,meta-llama/llama-4-scout"
        if (strlen($s_fallback) > 1)
            $this->_fallback_models = explode(",",$s_fallback); 

        $this->_providers_sort = strtolower(trim($GLOBALS["CONNECTOR"][$this->name]["providers_sort"] ?? ""));

        $s_providers2ignore = trim($GLOBALS["CONNECTOR"][$this->name]["providers_to_ignore"] ?? ""); //"Nebius AI Studio, Together, Infermatic";
        if (strlen($s_providers2ignore) > 1)
            $this->_providers2ignore = explode(",", $s_providers2ignore);
        
        $s_quantizations = trim($GLOBALS["CONNECTOR"][$this->name]["provider_quantizations"] ?? "");  //'fp8,fp16,bf16,fp32,unknown';
        if (strlen($s_quantizations) > 1)
            $this->_provider_quantizations = explode(",", $s_quantizations); 

        $f_max_price_prompt = floatval($GLOBALS["CONNECTOR"][$this->name]["provider_max_price_input"] ?? 0.0); //0.50
        $f_max_price_completition = floatval($GLOBALS["CONNECTOR"][$this->name]["provider_max_price_output"] ?? 0.0); //2.99
        if ($f_max_price_completition < 0.001 )
            $f_max_price_completition = 0.0;
        if ($f_max_price_prompt < 0.001 )
            $f_max_price_prompt = 0.0;
        else {
            if ($f_max_price_completition < 0.001 )
                $f_max_price_completition = 9999.0;
            $this->_provider_max_price = ['prompt' => $f_max_price_prompt, 'completion' => $f_max_price_completition];
        }

        $this->_is_nanogpt_com = (stripos($this->_url, "nano-gpt.com") > 0 ); //https://nano-gpt.com/api/v1/chat/completions
        if ($this->_is_nanogpt_com) {    
            $default_model = 'meta-llama/llama-4-scout';
        } else {
            $this->_is_mistral_ai = (stripos($this->_url, "mistral.ai") > 0 ); //https://api.mistral.ai/v1/chat/completions
            if ($this->_is_mistral_ai)    
                $default_model = 'mistral-small-latest';
        }

        $this->_model = $GLOBALS["CONNECTOR"][$this->name]["model"] ?? $default_model;
        
        // We shoud be able to overwrite model.
        $this->_model = isset($customParms["model"]) ?$customParms["model"] :  $this->_model;

        $this->_is_grok = (stripos($this->_model, "grok") > 0 ); 
        $this->_is_openai = $this->isOpenAIModel($this->_model);
        
        $this->_is_reasoning = $GLOBALS["CONNECTOR"][$this->name]["reasoning_model"] ?? false;  
        if (!$this->_is_reasoning)
            $this->_is_reasoning = $this->isReasoningModel($this->_model); // check if resoning model, use list of known reasoning models
        
        $this->_timeout = intval(($this->_is_reasoning) ? 90 : 30); // reasoning models could think more than 2 minutes
    }   
    
    public function open($contextData, $customParms)
    {

        $this->init_connector($customParms);

        $MAX_TOKENS=intval((isset($GLOBALS["CONNECTOR"][$this->name]["max_tokens"]) ? $GLOBALS["CONNECTOR"][$this->name]["max_tokens"] : 48));


        /***
            In the realm of perfection, the demand to tailor context for every language model would be nonexistent.

                                                                                                Tyler, 2023/11/09
        ****/
        
        if (isset($GLOBALS["FEATURES"]["MEMORY_EMBEDDING"]["ENABLED"]) && $GLOBALS["FEATURES"]["MEMORY_EMBEDDING"]["ENABLED"] && isset($GLOBALS["MEMORY_STATEMENT"]) ) {
            foreach ($contextData as $n=>$contextline)  {
                if (is_array($contextline) && isset($contextline["content"])) {
                    if (strpos($contextline["content"],"#MEMORY")===0) {
                        $contextData[$n]["content"]=str_replace("#MEMORY","##\nMEMORY\n",$contextline["content"]."\n##\n");
                    } else if (strpos($contextline["content"],$GLOBALS["MEMORY_STATEMENT"])!==false) {
                        $contextData[$n]["content"]=str_replace($GLOBALS["MEMORY_STATEMENT"],"(USE MEMORY reference)",$contextline["content"]);
                    }
                }
            }
        }

        require_once(__DIR__.DIRECTORY_SEPARATOR."..".DIRECTORY_SEPARATOR."functions".DIRECTORY_SEPARATOR."json_response.php");

        if (isset($GLOBALS["FUNCTIONS_ARE_ENABLED"]) && $GLOBALS["FUNCTIONS_ARE_ENABLED"]) {
            $contextData[0]["content"].=$GLOBALS["COMMAND_PROMPT"];
        }
        
        if (isset($GLOBALS["PATCH_PROMPT_ENFORCE_ACTIONS"]) && $GLOBALS["PATCH_PROMPT_ENFORCE_ACTIONS"]) {
            $prefix="{$GLOBALS["COMMAND_PROMPT_ENFORCE_ACTIONS"]}";
        } else {
            $prefix="";
        }

        if (isset($GLOBALS["HERIKA_SPEECHSTYLE"]) && (!empty($GLOBALS["HERIKA_SPEECHSTYLE"]))) {
            $speechReinforcement="Use <speech_style> for reference.";
        } else
            $speechReinforcement="";

        $zonosTones = $GLOBALS["TTSFUNCTION"] == "zonos_gradio" ? " (Response tones are mandatory in the response)" : "";
        $contextData[]=[
            'role' => 'user',
            'content' => "{$prefix}. $speechReinforcement \nUse ONLY this JSON object to give your answer. Do not send any other characters outside of this JSON structure $zonosTones: \n".json_encode($GLOBALS["responseTemplate"])
        ];
        $pb=[];
        $pb["user"]="";
        $pb["system"]="";
        
        $contextDataOrig=array_values($contextData);
        $lastrole="";
        $assistantAppearedInhistory=false;
        $lastTargetBuffer="";
        $assistantRoleBuffer="";
        $n_ctxsize = sizeof($contextDataOrig); 
        $this->_webbackup_func = $GLOBALS["FUNCTIONS_ARE_ENABLED"] ?: false;

        foreach ($contextDataOrig as $n=>$element) {
            
            if (!is_array($element)) {
                Logger::debug("$n=>$element was not an array");
                continue;

            }

            if (isset($element["content"]) && ($element["role"]!="tool") && ($n < ($n_ctxsize-2)) && ($n > ($n_ctxsize-6)) ) { // start online search request check
                //$s_msg = $element["content"];
                $i_pos = $this->isWebSearchInMessage($element["content"]); //check search trigger

                if ($this->_websearch && ($this->_websearch_index < $n) && ($element["role"] == "user")) {
                    if($i_pos === false) {
                        if (strpos($element["content"], "##") === false) { //is not memory mark
                            $this->_websearch = false; //previous web search was found in context history, do not repeat the search 
                            $GLOBALS["FUNCTIONS_ARE_ENABLED"] = $this->_webbackup_func;
                            Logger::debug("online FALSE, {$n}/{$n_ctxsize} line: ".$element["content"]);
                        }
                    }
                }

                if(!($i_pos === false)) { // found search trigger
                    $this->_websearch_text = $element["content"];
                    $this->_websearch_index = $n;
                    $this->_websearch = true;
                    $GLOBALS["FUNCTIONS_ARE_ENABLED"] = false;
                    $GLOBALS["FEATURES"]["MEMORY_EMBEDDING"]["ENABLED"] = false;
                    Logger::debug("online TRUE, {$n}/{$n_ctxsize} src: " . $this->_websearch_text);
                }
            } // --- end online search 
            
            if ($n>=($n_ctxsize-1) && $element["role"]!="tool") {
                // Last element
                $pb["user"].=$element["content"];
                $contextDataCopy[]=$element;
                
            } else {
                
                if ($lastrole=="assistant" && $lastrole!=$element["role"] && $element["role"]!="tool" ) {
                    $contextDataCopy[]=[
                        "role"=>"assistant",
                        "content"=>"{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\", \"listener\": \"$lastTargetBuffer\", \"mood\": \"\", \"action\": \"Talk\",\"target\": \"\", \"message\":\"".trim($assistantRoleBuffer)."\"}"
                        
                    ];
                    $lastTargetBuffer="";
                    $assistantRoleBuffer="";
                    $lastrole=$element["role"];
                }
                
                if ($element["role"]=="system") {
                    
                    $pb["system"]=$element["content"]."\nThis is the script history for this story\n#CONTEXT_HISTORY\n";
                    $contextDataCopy[]=$element;
                    
                } else if ($element["role"]=="user") {
                    if (empty($element["content"])) {
                        Logger::debug("Empty element[content]".__FILE__." ".__LINE__);
                        //unset($contextData[$n]);
                    } else
                        $contextDataCopy[]=$element;
                    
                    $pb["system"].=trim($element["content"])."\n";
                    
                } else if ($element["role"]=="assistant") {
                    $assistantAppearedInhistory=true;
                    $dialogueTarget=extractDialogueTarget($element["content"]) ?? "none"; // moved here to be available in tool_calls 
                    if (isset($element["tool_calls"])) {
                        $pb["system"].="{$GLOBALS["HERIKA_NAME"]} issued ACTION {$element["tool_calls"][0]["function"]["name"]}";
                        $lastAction="{$GLOBALS["HERIKA_NAME"]} issued ACTION {$element["tool_calls"][0]["function"]["name"]} {$element["tool_calls"][0]["function"]["arguments"]}";
                        $lastActionName=$element["tool_calls"][0]["function"]["name"];
                        $localFuncCodeName=getFunctionCodeName($element["tool_calls"][0]["function"]["name"]);
                        $localArguments=json_decode($element["tool_calls"][0]["function"]["arguments"],true);
                        if (isset($GLOBALS["F_RETURNMESSAGES"][$localFuncCodeName])) {
                            $lastAction=strtr($GLOBALS["F_RETURNMESSAGES"][$localFuncCodeName],[
                                        "#TARGET#"=>current($localArguments),
                                        ]);
                        }
                        $contextDataCopy[]=[
                                "role"=>"assistant",
                                "content"=>"{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\", \"listener\": \"{$dialogueTarget["target"]}\", \"mood\": \"\",\"action\": \"$lastActionName\",\"target\": \"".current($localArguments)."\", \"message\": \"\"}"
                            ];
                            
                        $gameRequestCopy=$GLOBALS["gameRequest"];    
                        $gameRequestCopy[3]="{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\", \"listener\": \"{$dialogueTarget["target"]}\", \"mood\": \"\",\"action\": \"$lastActionName\", \"target\": \"".current($localArguments)."\", \"message\": \"\"}";
                        $gameRequestCopy[0]="logaction";
                        logEvent($gameRequestCopy);   
                        
                        // Seems we were missing this case
                        if (isset($assistantRoleBuffer) && !empty($assistantRoleBuffer)) {
                            $contextDataCopy[]=[
                                "role"=>"assistant",
                                "content"=>"{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\", \"listener\": \"$lastTargetBuffer\", \"mood\": \"\", \"action\": \"Talk\",\"target\": \"\", \"message\":\"".trim($assistantRoleBuffer)."\"}"
                                
                            ];
                            $lastTargetBuffer="";
                            $assistantRoleBuffer="";
                            $lastrole=$element["role"];

                        }                        
                        
                        unset($contextData[$n]);
                    } else {
                        $alreadyJs=json_decode($element["content"],true);
                        if (is_array($alreadyJs)) {
                            $contextDataCopy[]=[
                                    "role"=>"assistant",
                                    "content"=>json_encode($alreadyJs)
                            ];
                            
                        } else {
                            //error_log("#### ".$element["content"]);
                            $pb["system"].=$element["content"]."\n";
                            //$dialogueTarget=extractDialogueTarget($element["content"]); // moved up
                            // Trying to provide examples
                            if (true) {
                                $assistantRoleBuffer.=$dialogueTarget["cleanedString"];                                
                                $lastTargetBuffer=$dialogueTarget["target"];
                                unset($contextData[$n]);
                                /*
                                $contextData[$n]=[
                                    "role"=>"assistant",
                                    "content"=>"{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\", \"listener\": \"{$dialogueTarget["target"]}\", \"mood\": \"\", \"action\": \"Talk\",\"target\": \"\", \"message\":\"".trim($dialogueTarget["cleanedString"])."\"}"
                                    
                                ];
                                */

                            } else {
                                
                                $contextData[$n]=[
                                        "role"=>"assistant",
                                        "content"=>"{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\", \"listener\": \"{$dialogueTarget["target"]}\", \"mood\": \"\", \"action\": \"Talk\",\"target\": \"\", \"message\":\"".trim($dialogueTarget["cleanedString"])."\"}"
                                        
                                    ];
                            }
                        }
                    }
                    
                } else if ($element["role"]=="tool") {
                    
                        if (!empty($element["content"])) {
                            $pb["system"].=$element["content"]."\n";
                            
                           
                            if (strpos($element["content"],"Error")===0) {
                                $GLOBALS["PATCH_STORE_FUNC_RES"]="{$GLOBALS["HERIKA_NAME"]} issued ACTION, but {$element["content"]}";
                                $contextDataCopy[]=[
                                    "role"=>"user",
                                    "content"=>"The Narrator: ({$GLOBALS["HERIKA_NAME"]} used action $lastActionName). {$GLOBALS["PATCH_STORE_FUNC_RES"]}"
                                    
                                ];
                            } else {
                                
                                $GLOBALS["PATCH_STORE_FUNC_RES"]=strtr($lastAction,["#RESULT#"=>$element["content"]]);
                                $contextDataCopy[]=[
                                    "role"=>"user",
                                    "content"=>"The Narrator: ({$GLOBALS["HERIKA_NAME"]} used action $lastActionName). {$GLOBALS["PATCH_STORE_FUNC_RES"]} ",
                                    
                                ];
                            }
                        } else {
                            ;
                            //unset($contextData[$n]);
                        }
                            
                }
                
            }

            

            // 
            $lastrole=$element["role"];
        }
        

        $contextData=$contextDataCopy;

        // Compact and remove context elements with empty content
        $contextDataCopy=[];
        foreach ($contextData as $n=>$element) {
            if (!empty($element["content"])) {
                $contextDataCopy[]=$element;
            }
        }
        
        if ((isset($GLOBALS["CONNECTOR"][$this->name]["PREFILL_JSON"])) && ($GLOBALS["CONNECTOR"][$this->name]["PREFILL_JSON"])) {
            $GLOBALS["PATCH"]["PREAPPEND"]="{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\",";
            $contextDataCopy[]= ["role"=>"assistant","content"=>$GLOBALS["PATCH"]["PREAPPEND"]];
        }
        
        $contextData=$contextDataCopy;
        
        if (!$assistantAppearedInhistory) { // is this still needed?
            
            if (isset($GLOBALS["CHIM_NO_EXAMPLES"]) && $GLOBALS["CHIM_NO_EXAMPLES"]) {
                $contextExamples=[];
            } else {
                // EXAMPLES
                $contextExamples[]= [
                    'role' => 'user', 
                    'content' => "The Narrator: {$GLOBALS["PLAYER_NAME"]} looks at {$GLOBALS["HERIKA_NAME"]}"
                ];
                
                $contextExamples[]= [
                    "role"=>"assistant",
                    "content"=>"{\"character\": \"{$GLOBALS["HERIKA_NAME"]}\",\"listener\": \"{$GLOBALS["PLAYER_NAME"]}\", \"mood\": \"default\", \"action\": \"Talk\",\"target\": \"\", \"message\": \"What are you looking at?\"}"
                        
                ];
                
                $finalContextDataWithExamples=[];
                foreach ($contextData as $n=>$final) {
                    if ($final["role"]=="system") {
                        $finalContextDataWithExamples[]=$final;
                        foreach ($contextExamples as $example)
                            $finalContextDataWithExamples[]=$example;
                        }
                    else
                        $finalContextDataWithExamples[]=$final;
                }
               
                $contextData=$finalContextDataWithExamples;
            }        
        }

        $temperature = floatval(($GLOBALS["CONNECTOR"][$this->name]["temperature"]) ? : 0.7);
        if ($temperature < 0.0) $temperature = 0.0;
        else if ($temperature > 2.0) $temperature = 2.0; 

        $presence_penalty = floatval(($GLOBALS["CONNECTOR"][$this->name]["presence_penalty"]) ? : 0.0);
        if ($presence_penalty < -2.0) $presence_penalty = -2.0;
        else if ($presence_penalty > 2.0) $presence_penalty = 2.0; 

        $frequency_penalty = floatval(($GLOBALS["CONNECTOR"][$this->name]["frequency_penalty"]) ? : 0.0); 
        if ($frequency_penalty < -2.0) $frequency_penalty = -2.0;
        else if ($frequency_penalty > 2.0) $frequency_penalty = 2.0; 

        $repetition_penalty = floatval(($GLOBALS["CONNECTOR"][$this->name]["repetition_penalty"]) ? : 0.0);
        if ($repetition_penalty < 0.0) $repetition_penalty = 0.0;
        else if ($repetition_penalty > 2.0) $repetition_penalty = 2.0; 

        $top_p = floatval(($GLOBALS["CONNECTOR"][$this->name]["top_p"]) ? : 1.0);
        if ($top_p > 1) $top_p = 1.0;
        else if ($top_p < 0.0) $top_p = 0.0; 

        $min_p = floatval(($GLOBALS["CONNECTOR"][$this->name]["min_p"]) ? : 0.0);
        if ($min_p > 1) $min_p = 1.0;
        else if ($min_p < 0.0) $min_p = 0.0; 

        $top_a = floatval(($GLOBALS["CONNECTOR"][$this->name]["top_a"]) ? : 0.0);
        if ($top_a > 1) $top_a = 1.0;
        else if ($top_a < 0.0) $top_a = 0.0; 

        $top_k = intval(($GLOBALS["CONNECTOR"][$this->name]["top_k"]) ? : 0);
        if ($top_k < 0) $top_k = 0; 

        if (isset($customParms["MAX_TOKENS"])) {
            $MAX_TOKENS=intval($customParms["MAX_TOKENS"]);
            unset($customParms["MAX_TOKENS"]);
        }
        if (isset($GLOBALS["FORCE_MAX_TOKENS"])) {
            $MAX_TOKENS=intval($GLOBALS["FORCE_MAX_TOKENS"]);
        }
        
        $data = array(
            'model' => $this->_model,
            'messages' => $contextData,
            'stream' => $this->_is_streaming, 
            'max_tokens' => $MAX_TOKENS,
            'temperature' => $temperature, 
            'top_k' => $top_k,
            'top_p' => $top_p, 
            'min_p' => $min_p,
            'top_a' => $top_a,
            'presence_penalty' => $presence_penalty, 
            'frequency_penalty' => $frequency_penalty, 
            'repetition_penalty' => $repetition_penalty,
            'stop'=>[
                    'USER',
                ],
            'transforms'=>[]
        );
        
        if ($GLOBALS["CONNECTOR"][$this->name]["ENFORCE_JSON"]) {
            if (isset($GLOBALS["CONNECTOR"][$this->name]["json_schema"]) && $GLOBALS["CONNECTOR"][$this->name]["json_schema"]) {
                $data["response_format"]=$GLOBALS["structuredOutputTemplate"];
            } else {
                $data["response_format"]=["type"=>"json_object"];
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
            
        if ($this->_is_reasoning) { // add parameter to hide <think> content

            if (!(stripos($this->_model, "x-ai/grok-4.1-fast") === false)) { //x-ai/grok-4.1-fast
                $data["reasoning"] = array ('exclude' => true, 'enabled' => false); // disable reasoning by default, if _disable_reasoning = false, will be overwritten below
            }
            
            //$data["reasoning"] = array ('exclude' => true, 'enabled' => true); // exclude = true - Use reasoning but don't include it in the response; enabled = false - do not use reasoning
            if ($this->_disable_reasoning)
                $data["reasoning"] = array ('exclude' => true, 'enabled' => false); // default value, CoT removed, resoning disabled, fast response
            else
                $data["reasoning"] = array ('exclude' => true, 'enabled' => true); // CoT removed, resoning enabled, slow
            
            //Logger::debug("[OPENROUTER]  Excluding reasoning");
            //$data["reasoning"] = array ('exclude' => true, 'effort' => 'low'); // reduce reasoning tokens - OpenAI
            //$data["reasoning"] = array ('exclude' => true, 'max_tokens' => 64 ); // reduce reasoning tokens - Anthropic 
            //Logger::debug("reasoning " . $this->_model);
            if (!(stripos($this->_model, "qwen3-") === false)) {//qwen3
                $data["enable_thinking"] = false;
            } elseif (stripos($this->_model, "grok-3-mini") != false) {//grok-3-mini needs reasoning and cannot be disabled
                $data["reasoning"]["enabled"] = true;
            } elseif (stripos($this->_model, "qwen3-235b-a22b-thinking-2507") != false) {//qwen/qwen3-235b-a22b-thinking-2507 needs reasoning cand cannot be disabled
                $data["reasoning"]["enabled"] = true;
            } elseif ($this->_model=="x-ai/grok-4") {// needs reasoning and cannot be disabled 
                $data["reasoning"]["enabled"] = true;
            }         
        }
        
        if ($this->_is_mistral_ai) { // Mistral AI API does not support penalty params
            unset($data["presence_penalty"]); 
            unset($data["frequency_penalty"]);
        } elseif ($this->_is_grok) { //Argument not supported on this model: stop
            unset($data["stop"]); 
        } elseif ($this->_is_openai) {
            // OpenAI models use max_completion_tokens
            //Logger::debug("[OPENROUTER] Excluding reasoning this->_is_openai");
            $data['max_completion_tokens'] = $MAX_TOKENS;
            unset($data['max_tokens']); 
            if ($this->_is_reasoning) {
                $data["reasoning"] = array ('exclude' => true, 'effort' => 'low'); // reduce reasoning tokens - OpenAI
            }
        }

        if ($MAX_TOKENS<1) {
            unset($data["max_completion_tokens"]); 
            unset($data["max_tokens"]); 
        }

        if (!empty($GLOBALS["CONNECTOR"]["openrouterjson"]["PROVIDER"])) {
            $providers=explode(",",$GLOBALS["CONNECTOR"]["openrouterjson"]["PROVIDER"]);
            $data["provider"]=["order"=>$providers];
        } 

        if (isset($this->_fallback_models) && (is_array($this->_fallback_models)) && (count($this->_fallback_models) > 0)) {
            $data['models'] = $this->_fallback_models;
        }

        if (isset($this->_providers_sort) && (in_array($this->_providers_sort,['price','throughput','latency']))) {
            $data['provider']['sort'] = $this->_providers_sort; 
        }

        if (isset($this->_providers2ignore) && (is_array($this->_providers2ignore)) && (count($this->_providers2ignore) > 0)) {
            $data['provider']['ignore'] = $this->_providers2ignore; 
        }

        if (isset($this->_provider_quantizations) && (is_array($this->_provider_quantizations)) && (count($this->_provider_quantizations) > 0)) {
            $data['provider']['quantizations'] = $this->_provider_quantizations; 
        }

        if (isset($this->_provider_max_price) && (is_array($this->_provider_max_price)) && (count($this->_provider_max_price) == 2)) {
            $json_price = json_encode($this->_provider_max_price); 
            if (isset($json_price))
                $data['provider']['max_price'] = json_decode($json_price);
        }
        
        if ($this->_websearch) { // online search request 

            $sx = $this->_model;
            if (strpos($sx, ":online") === false) 
                $sx = $sx . ":online";   
            $this->_model = $sx;

            $data["model"] = $this->_model;
            
            $search_text = $this->_websearch_text;
            $target = "";
            $i_pos = strpos($search_text, ":");
            if (!($i_pos === false)) {
                $target = substr($this->_websearch_text, 0, $i_pos);
                $search_text = substr($this->_websearch_text,strlen($target)+1);
                $i_pos2 = strripos($search_text, "(Talking to");
                if (!($i_pos2 === false)) {
                    $search_text = substr($search_text, 0, $i_pos2); 
                }
            }
            if (stripos($search_text, "Skyrim") === false) 
                $s_prefix = "Skyrim lore ";
            else
                $s_prefix = "";

            $data["response_format"] = array ('type' => 'json_object');
            $data["stream"] = true;

            $data["messages"] = array(); //clean everything 
            $data["messages"] = [
                ['role' => 'system', 
                 'content' => "" // "Role-play in Skyrim universe. "
                 ."You are an expert with extensive knowledge about Skyrim lore focusing on puzzle solutions, quests, places and people." 
                 ." Use web sources like gamerant.com, en.uesp.net, elderscrolls.fandom.com, gaming.stackexchange.com and avoid video sources like youtube.com "
                ],
                ['role' => 'user',
                 'content' => $s_prefix . trim($search_text)
                ],
                ['role' => 'user',
                 'content' => trim(" {$speechReinforcement} Always use this JSON object to give your answer: ".json_encode($GLOBALS["responseTemplate"], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES ))
                ]
            ];

            $data["plugins"] = array();
            $data["plugins"] = [
                ['id' => 'web', 
                 'search_prompt' => "Search the web to find relevant information related to Skyrim universe. "
                    . "Include relevant search results to provide most informative response. "
                    . "Write your answer from first person point of view. "
                    //. "IMPORTANT: avoid markdown and any text formatting, lists, numbered lists, step by step instructions. " 
                    . "Never mention web sources. ", // production
                 'max_results' => 2 
                ]
            ];

        } // --- end online search request

        if (isset($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"]) && is_array($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"])) {
            foreach ($GLOBALS["CONNECTOR"][$this->name]["extra_parameters"] as $k=>$v) {
                $data[$k]=$v;
            }
        }        

        if (stripos($data["model"], "openai/gpt-5-nano")===0) {
            unset($data["temperature"]);
            unset($data["top_p"]);
        }


        $GLOBALS["DEBUG_DATA"]["full"]=($data);

        file_put_contents(__DIR__."/../log/context_sent_to_llm.log",date(DATE_ATOM)."\n=\n".var_export($data,true)."\n=\n", FILE_APPEND);

        $headers = array(
            'Content-Type: application/json',
            "Authorization: Bearer {$GLOBALS["CONNECTOR"][$this->name]["API_KEY"]}",
            "HTTP-Referer:  https://dwemerdynamics.com/",
            "X-Title: Dwemer Dynamics"
        );

        $data["usage"]=["include"=>true];

        $timeout = max(intval(($GLOBALS["HTTP_TIMEOUT"]) ?? 30), $this->_timeout);
        $options = array(
            'http' => array(
                'method' => 'POST',
                'header' => implode("\r\n", $headers),
                'content' => json_encode($data),
                'timeout' => $timeout, 
                "ignore_errors" => true
            )
        );

        $context = stream_context_create($options);
        
        $this->primary_handler = $this->send($this->_url, $context);
        if (!$this->primary_handler) {
            $error=error_get_last();
            Logger::error(trim(print_r($error,true)));

            if ($GLOBALS["db"]) {
                $GLOBALS["db"]->insert(
                'audit_request',
                    array(
                        'request' => json_encode($data),
                        'result' => $error["message"],
                        'connector'=>$this->name,
                        'url'=>$this->_url
                    ));
            }
            return null;
        } else {
            $status_code = $this->getHttpStatusCode();
            if ($status_code >= 300) {
                $response = stream_get_contents($this->primary_handler);
                //$error_message = "Request to openrouterjson connector failed: {$status_line}.\nResponse body: {$response}";
                $error_message = "Request to openrouterjson connector failed: {$status_code}.\n Response body: {$response}.\n model: {$this->_model}";
                trigger_error($error_message, E_USER_WARNING);

                if ($GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                    'audit_request',
                        array(
                            'request' => json_encode($data),
                            'result' => $error_message,
                            'connector'=>$this->name,
                            'url'=>$this->_url
                        ));
                }

                $this->close();
                $this->primary_handler=false;
                return null;
            } else  {
                // Will do later
                /*
                if ($GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                    'audit_request',
                    array(
                        'request' => json_encode($data),
                        'result' => "Ok",
                        'connector'=>$this->name,
                        'url'=>$this->_url
                    ));
                }
                */
            }
        }

        $this->_dataSent=json_encode($data);    // Will use this data in tokenizer.
        $this->_rawbuffer="";
        file_put_contents(__DIR__."/../log/output_from_llm.log","\n== ".date(DATE_ATOM)." START\n\n", FILE_APPEND);
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
    

    public function process()
    {
        global $alreadysent;

        static $numOutputTokens=0;

        if (!isset($GLOBALS["patch_openrouter_timeout"]))
            $GLOBALS["patch_openrouter_timeout"]=time();

        $buffer = "";
        $totalBuffer = "";
        $mangledBuffer = "";
        $finalData = "";

        if ($this->isDone()) {
            if (!$this->_buffer || empty(trim($this->_buffer))) {
                $line = "";    
                Logger::warn("LLM didn't output anything");
            }
        } else {
            if ((time()-$GLOBALS["patch_openrouter_timeout"])>60) {
                $this->_rawbuffer.="Error, timeout when receiving data from LLM";
                Logger::error("Error, timeout when receiving data from LLM");
                $this->_forcedClose=true;
                return -1;
            }
            $line = fgets($this->primary_handler);
        }
        
        file_put_contents(__DIR__."/../log/debugStream.log", $line, FILE_APPEND);
        $this->_rawbuffer.=$line;
        
        // Check for error response
        if (strpos($line, '"error"') !== false) {
            Logger::error("Error response from LLM: $line");
            return -1;
        }
        
        $data=json_decode(substr($line, 6), true);

        if ($this->_is_reasoning)
            $buffer_preamble=4096; // some reasoning models output CoT part before JSON
        elseif ($this->_websearch)
            $buffer_preamble=256; 
        else
            $buffer_preamble=64; //was 10, 10 is not enough, some LLMs output a prefix tag/markup before JSON or "here is your JSON ..."

        if (isset($data["choices"][0]["delta"]["content"])) {
            if (strlen(($data["choices"][0]["delta"]["content"]))>0) {
                $buffer.=$data["choices"][0]["delta"]["content"];
                $this->_buffer.=$data["choices"][0]["delta"]["content"];
                // Check to see if we've received something that looks like it starts with a JSON object
                if (strlen($this->_buffer)>$buffer_preamble && strpos($this->_buffer, '{') === false) { 
                    Logger::error("{$this->name} Error decoding JSON from LLM {$this->_model} output: can't find JSON start mark after reading {$buffer_preamble} characters. LLM didn't output proper JSON object or there is a long non-JSON preamble. url:{$this->_url} buffer:{$this->_buffer} ");
                    return -1;
                }

            }

            $totalBuffer.=$data["choices"][0]["delta"]["content"];

            $this->_lastStreamedObject=$data;
        }
        
        if (isset($GLOBALS["PATCH"]["PREAPPEND"])) {
            $this->_buffer=$GLOBALS["PATCH"]["PREAPPEND"];
            unset($GLOBALS["PATCH"]["PREAPPEND"]);
        }
        
        $buffer="";
        if (!empty($this->_buffer))
            $finalData=__jpd_decode_lazy($this->_buffer, true);
            if (is_array($finalData)) {
                
                
                if (isset($finalData[0])&& is_array($finalData[0]))
                    $finalData=$finalData[0];
                
                if (isset($finalData["message"])) {
                    // Check first if action was issued
                    if (is_array($finalData)&&isset($finalData["action"])) {
                        if (($finalData["action"]=="Inspect")&&(!empty($finalData["target"]))) {
                            return "";
                            
                        }
                        
                    } 
                    
                    if (is_array($finalData)&&isset($finalData["message"])) {
                        if (is_array($finalData["message"]))
                            $finalData["message"]=implode(",",$finalData["message"]);
                        
                        $mangledBuffer = str_replace($this->_extractedbuffer, "", $finalData["message"]);
                        $this->_extractedbuffer=$finalData["message"];
                        if (isset($finalData["listener"])) {
                            if (isset($finalData["action"])&&($finalData["action"]=="Talk")&& lazyEmpty($finalData["listener"]) && !lazyEmpty($finalData["target"]))
                                $GLOBALS["SCRIPTLINE_LISTENER"]=$finalData["target"];
                            else
                                $GLOBALS["SCRIPTLINE_LISTENER"]=$finalData["listener"];
                        }
                        
                        if (isset($finalData["lang"])) {
                            $GLOBALS["LLM_LANG"]=$finalData["lang"];
                        }
                        
                        if (isset($finalData["mood"])) {
                            $GLOBALS["SCRIPTLINE_ANIMATION"]=GetAnimationHex($finalData["mood"]);
                            $GLOBALS["SCRIPTLINE_EXPRESSION"]=GetExpression($finalData["mood"]);
                        }
                        
                        // Store the entire response for TTS systems that need additional data like emotions
                        $GLOBALS["LAST_LLM_RESPONSE"] = $finalData;
                    }
                }
                
            } else
                $buffer="";
        
        return $mangledBuffer;
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
                return stripReasoningTokens($tempJson['message']);
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
    public function close($callName='')
    {
        if ($this->primary_handler) {
            fclose($this->primary_handler);
        }
        // Use callName just for logging purposes.
        if (empty($callName))
            $callName=$this->name;
        else
            $callName=$this->name."/".$callName;

        $json_response=$this->_lastStreamedObject;

        if (!isset($json_response["usage"]))
            $json_response["usage"]=[];
        
        if ($json_response) {
                if ($GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                    'audit_request',
                        array(
                            'request' => json_encode($this->_dataSent),
                            'result' => "Ok",
                            'usage'=>json_encode($json_response["usage"]),
                            'connector'=>$callName,
                            'url'=>$this->_url
                        ));
                }
                
        }
        else {
                if ($GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                    'audit_request',
                        array(
                            'request' => json_encode($this->_dataSent),
                            'result' => "ERROR|INVALID JSON RESPONSE",
                            'connector'=>$this->name,
                            'url'=>$this->_url
                        ));
                }
        }
        // Write the buffer to the log file without timestamp separators
        file_put_contents(__DIR__."/../log/output_from_llm.log", $this->_buffer . "\n", FILE_APPEND);
        file_put_contents(__DIR__."/../log/output_from_llm.log","\n== ".date(DATE_ATOM)." END\n\n", FILE_APPEND);
        return $this->_buffer;
    }

   

    // Method to close the data processing operation
    public function processActions()
    {
        global $alreadysent;

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

    public function fast_request($contextData, $customParms,$callName='')
    {
        
        $this->init_connector($customParms);
        
        if (empty($callName))
            $callName=$this->name;
        else
            $callName=$this->name."/".$callName;


        $MAX_TOKENS=((isset($GLOBALS["CONNECTOR"][$this->name]["max_tokens"]) ? $GLOBALS["CONNECTOR"][$this->name]["max_tokens"] : 48)+0);

        $temperature = floatval(($GLOBALS["CONNECTOR"][$this->name]["temperature"]) ? : 0.7);
        if ($temperature < 0.0) $temperature = 0.0;
        else if ($temperature > 2.0) $temperature = 2.0; 

        $presence_penalty = floatval(($GLOBALS["CONNECTOR"][$this->name]["presence_penalty"]) ? : 0.0);
        if ($presence_penalty < -2.0) $presence_penalty = -2.0;
        else if ($presence_penalty > 2.0) $presence_penalty = 2.0; 

        $frequency_penalty = floatval(($GLOBALS["CONNECTOR"][$this->name]["frequency_penalty"]) ? : 0.0); 
        if ($frequency_penalty < -2.0) $frequency_penalty = -2.0;
        else if ($frequency_penalty > 2.0) $frequency_penalty = 2.0; 

        $repetition_penalty = floatval(($GLOBALS["CONNECTOR"][$this->name]["repetition_penalty"]) ? : 0.0);
        if ($repetition_penalty < 0.0) $repetition_penalty = 0.0;
        else if ($repetition_penalty > 2.0) $repetition_penalty = 2.0; 

        $top_p = floatval(($GLOBALS["CONNECTOR"][$this->name]["top_p"]) ? : 1.0);
        if ($top_p > 1) $top_p = 1.0;
        else if ($top_p < 0.0) $top_p = 0.0; 

        $min_p = floatval(($GLOBALS["CONNECTOR"][$this->name]["min_p"]) ? : 0.0);
        if ($min_p > 1) $min_p = 1.0;
        else if ($min_p < 0.0) $min_p = 0.0; 

        $top_a = floatval(($GLOBALS["CONNECTOR"][$this->name]["top_a"]) ? : 0.0);
        if ($top_a > 1) $top_a = 1.0;
        else if ($top_a < 0.0) $top_a = 0.0; 

        $top_k = intval(($GLOBALS["CONNECTOR"][$this->name]["top_k"]) ? : 0);
        if ($top_k < 0) $top_k = 0; 

        if (isset($customParms["MAX_TOKENS"])) {
            $MAX_TOKENS=intval($customParms["MAX_TOKENS"]);
            unset($customParms["MAX_TOKENS"]);
        }
        if (isset($GLOBALS["FORCE_MAX_TOKENS"])) {
            $MAX_TOKENS=intval($GLOBALS["FORCE_MAX_TOKENS"]);
        }
        
        $data = array(
            'model' => $this->_model,
            'messages' => $contextData,
            'stream' => false, 
            'usage'=> ["include"=>true],
            'max_tokens' => $MAX_TOKENS,
            'temperature' => $temperature, 
            'top_k' => $top_k,
            'top_p' => $top_p, 
            'min_p' => $min_p,
            'top_a' => $top_a,
            'presence_penalty' => $presence_penalty, 
            'frequency_penalty' => $frequency_penalty, 
            'repetition_penalty' => $repetition_penalty,
            'stop'=>[
                    'USER',
                ],
            'transforms'=>[]
        );

        if (isset($GLOBALS["CONNECTOR"][$this->name]["stop"])&&sizeof($GLOBALS["CONNECTOR"][$this->name]["stop"])>0) {
            $data["stop"]=$GLOBALS["CONNECTOR"][$this->name]["stop"];
        }
        // Override

       

        if (isset($customParms["MAX_TOKENS"])) {
            if ($customParms["MAX_TOKENS"]==0) {
                unset($data["max_tokens"]);
            } elseif ($customParms["MAX_TOKENS"]) {
                $data["max_tokens"]=$customParms["MAX_TOKENS"];
            }
        }

        if (isset($GLOBALS["FORCE_MAX_TOKENS"])) {
            if ($GLOBALS["FORCE_MAX_TOKENS"]==0) {
                unset($data["max_tokens"]);
            } else {
                $data["max_tokens"]=$GLOBALS["FORCE_MAX_TOKENS"];

            }
        }
        

        // Mistral AI API does not support penalty params
        if ($this->_is_mistral_ai) {
            unset($data["presence_penalty"]); 
            unset($data["frequency_penalty"]);
        } 
        
        if ($this->_is_grok) { //Argument not supported on this model: stop
            unset($data["stop"]); 
        }  

        if ($this->_is_reasoning) { // add parameter to hide <think> content
            $data["reasoning"] = array ('exclude' => true,'enabled'=>false); // Use reasoning but don't include it in the response
            //$data["reasoning"] = array ('exclude' => true, 'effort' => 'low'); // reduce reasoning tokens - OpenAI
            //$data["reasoning"] = array ('exclude' => true, 'max_tokens' => 64 ); // reduce reasoning tokens - Anthropic 
            //Logger::debug("reasoning " . $this->_model);
            if (!(stripos($this->_model, "qwen3-") === false)) {//qwen3
                $data["enable_thinking"] = false;
            }       
            if (stripos($this->_model, "grok-3-mini") != false) {//grok-3-mini needs reasoning cand cannot be disabled
                $data["reasoning"]["enabled"] = true;
            }        
    }
        
        if ($this->_is_openai) {
            // OpenAI models use max_completion_tokens
            $data['max_completion_tokens'] = $MAX_TOKENS;
            unset($data['max_tokens']); 
            if ($this->_is_reasoning) {
                $data["reasoning"] = array ('exclude' => true, 'effort' => 'low'); // reduce reasoning tokens - OpenAI
            }
        }

        if ($MAX_TOKENS<1) {
            $data["max_tokens"]+=0;

            unset($data["max_completion_tokens"]); 
            unset($data["max_tokens"]); 

        }

        if (!empty($GLOBALS["CONNECTOR"]["openrouterjson"]["PROVIDER"])) {
            $providers=explode(",",$GLOBALS["CONNECTOR"]["openrouterjson"]["PROVIDER"]);
            $data["provider"]=["order"=>$providers];
        } 

        if (isset($this->_fallback_models) && (is_array($this->_fallback_models)) && (count($this->_fallback_models) > 0)) {
            $data['models'] = $this->_fallback_models;
        }


        if (isset($this->_providers_sort) && (in_array($this->_providers_sort,['price','throughput','latency']))) {
            $data['provider']['sort'] = $this->_providers_sort; 
        }

        if (isset($this->_providers2ignore) && (is_array($this->_providers2ignore)) && (count($this->_providers2ignore) > 0)) {
            $data['provider']['ignore'] = $this->_providers2ignore; 
        }

        if (isset($this->_provider_quantizations) && (is_array($this->_provider_quantizations)) && (count($this->_provider_quantizations) > 0)) {
            $data['provider']['quantizations'] = $this->_provider_quantizations; 
        }

        if (isset($this->_provider_max_price) && (is_array($this->_provider_max_price)) && (count($this->_provider_max_price) == 2)) {
            $json_price = json_encode($this->_provider_max_price); 
            if (isset($json_price))
                $data['provider']['max_price'] = json_decode($json_price);
        }
        
        
        foreach ($customParms as $parm=>$value) {
            $data[$parm]=$value;
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
        
        $data["transforms"]=[];

        $GLOBALS["DEBUG_DATA"]["full"]=($data);
     
        
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
                'timeout' => ($GLOBALS["HTTP_TIMEOUT"]) ?: 30
            )
        );

        $context = stream_context_create($options);
        
        file_put_contents(__DIR__."/../log/context_sent_to_llm_fast.log",date(DATE_ATOM)."\n=\n".var_export($data,true)."\n=\n", FILE_APPEND);

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

        
        
        file_put_contents(__DIR__."/../log/output_from_llm_fast.log",date(DATE_ATOM)."\n=\n{$json_response}\n=\n", FILE_APPEND);

        if ($json_response) {
            $text_response=json_decode($json_response,true);
           
            if (is_valid_array($text_response)) {
                if ($GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                    'audit_request',
                        array(
                            'request' => json_encode($data),
                            'result' => "Ok",
                            'usage'=>json_encode($text_response["usage"]),
                            'connector'=>$callName,
                            'url'=>$this->_url
                        ));
                }
                return $text_response["choices"][0]["message"]["content"];    
            }
            else {
                if ($GLOBALS["db"]) {
                    $GLOBALS["db"]->insert(
                    'audit_request',
                        array(
                            'request' => json_encode($data),
                            'result' => "ERROR|INVALID JSON RESPONSE",
                            'connector'=>$callName,
                            'url'=>$this->_url
                        ));
                }
                error_log("Error in openrouter request '$url':$json_response", 3);
                return "";
                
            }
            
        } else {
            if ($GLOBALS["db"]) {
                $GLOBALS["db"]->insert(
                'audit_request',
                    array(
                        'request' => json_encode($data),
                        'result' => "ERROR|NO RESPONSE",
                        'connector'=>$this->name,
                        'url'=>$this->_url
                    ));
            }
        }
            
    }

}

