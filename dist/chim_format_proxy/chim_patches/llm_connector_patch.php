<?php
/**
 * PATCH for lib/core/llm_connector.class.php
 *
 * Add this elseif block AFTER the openrouterjson block (line ~313) and
 * BEFORE the google_openaijson block in setOldGlobals().
 *
 * This block is identical to the openrouterjson block except:
 * 1. It matches driver == "openrouterjsonreformat"
 * 2. It writes to $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]
 * 3. It injects x_* format settings from metadata into extra_parameters
 *    so openrouterjson's open() forwards them in the request body
 */

// --- BEGIN FORMAT PROXY PATCH ---
// Insert this block after the "openrouterjson" elseif and before "google_openaijson"

        } else if ($currentConnectorData["driver"] == "openrouterjsonreformat") {

            $apiBadge = new ApiBadge();
            $apiKeyData = $apiBadge->getById($currentConnectorData["api_badge_id"]);

            $GLOBALS["CONNECTOR"]["openrouterjsonreformat"]["url"] = $currentConnectorData["url"] ?? 'http://127.0.0.1:38800/v1/chat/completions';
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

            // Decode metadata into globals (same as openrouterjson)
            $metadata = json_decode($currentConnectorData['metadata'] ?? '{}', true);
            if (is_array($metadata)) {
                foreach ($metadata as $key => $value) {
                    $GLOBALS["CONNECTOR"]["openrouterjsonreformat"][$key] = $value;
                }
            }

            // FORMAT PROXY BRIDGE: inject x_* settings into extra_parameters
            // so openrouterjson's open() includes them in the HTTP request body
            // via chimGetEnabledConnectorExtraParameters()
            $formatKeys = [
                'x_input_format', 'x_input_include_name', 'x_input_include_mood',
                'x_input_include_action', 'x_input_include_listener',
                'x_output_format', 'x_output_include_mood', 'x_output_include_action',
                'x_output_include_target', 'x_output_include_listener',
                'x_upstream_type', 'x_proxy_port', 'x_upstream_url',
            ];
            $formatParams = [];
            foreach ($formatKeys as $fk) {
                if (isset($GLOBALS["CONNECTOR"]["openrouterjsonreformat"][$fk])) {
                    $formatParams[$fk] = $GLOBALS["CONNECTOR"]["openrouterjsonreformat"][$fk];
                }
            }
            // Also pass the character name so the proxy can use it for JSON reconstruction
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

// --- END FORMAT PROXY PATCH ---
