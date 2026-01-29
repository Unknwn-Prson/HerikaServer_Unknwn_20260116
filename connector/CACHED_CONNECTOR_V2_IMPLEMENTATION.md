# OpenRouter Cached Connector v2.0.1 - Technical Implementation

This document provides technical details for developers and maintainers of the cached connector.

## Architecture Overview

### Version Information
- **Current Version**: v2.0.1
- **Target CHIM Version**: 2.3.3
- **Base Connector**: `openrouterjson.php` from CHIM 2.3.3

### Design Philosophy
The cached connector is designed as a **streaming-only** connector that optimizes API costs by caching repetitive context data. It maintains full compatibility with CHIM's connector interface while adding provider-specific caching strategies.

## File Structure

```
connector/
├── openrouterjsoncached.php         # Main connector class (1629 lines)
├── openrouterjsoncached_helpers.php # Helper functions (750+ lines)
└── __jpd.php                        # JSON parsing dependency

conf/
└── conf_schema.json                 # Connector configuration schema

lib/core/
└── llm_connector.class.php          # Connector loader with defaults

ui/
├── global_settings.php              # Global settings with connector filter
└── core/
    └── llm_connectors.php           # Connector UI with caching controls
```

## Class Structure

### Main Class: `openrouterjsoncached`

```php
class openrouterjsoncached {
    const VERSION = 'OpenRouter Cache Connector v2.0.1 for CHIM 2.3.3 | 2026/01/29';

    // Core properties (inherited from openrouterjson)
    private $_model, $_url, $_buffer, $_timeout, etc.

    // Caching-specific properties
    private $_provider_caching;      // 'Anthropic', 'OpenAI', 'Gemini'
    private $_responseFormat;        // 'json', 'simple'
    private $_memoryMode;            // 'accumulate', 'fresh'
    private $_cacheInvalidationMode; // 'time_based', 'sync_updates'

    // Response format controls
    private $_includeMood, $_includeActions, $_includeTarget, $_includeListener;

    // Simple format parser state
    private $_reasoningState, $_metadataEnd, $_sentencesSent, etc.
}
```

### Public Interface

| Method | Description |
|--------|-------------|
| `__construct()` | Initialize connector with defaults |
| `open($contextData, $customParms)` | Process context and open API stream |
| `process()` | Process streaming chunks |
| `close($callName='')` | Close stream and cleanup |
| `processActions($result)` | Extract actions from response |
| `handlesSentenceSplitting()` | Returns true for simple format |

### Private Methods - open() Split

The `open()` method is split into 4 parts for maintainability:

| Part | Method | Responsibility |
|------|--------|----------------|
| 1 | `open()` | Configuration loading, sync invalidation check |
| 2 | `_openPart2()` | System prompt processing, cache file setup |
| 3 | `_openPart3()` | Dialogue history caching, cache control placement |
| 4 | `_openPart4()` | Payload construction, API request |

## Helper Functions

Located in `openrouterjsoncached_helpers.php`:

### Logging
```php
logMessage($message, $context, $level, $logFile)
```

### Memory Handling
```php
removeDuplicateMemories($array)        // Deduplicate memory entries
extractMemoryContent($text)            // Extract <memory> tag content
```

### Cache Management
```php
manageCharacterEventList($newList, $filename, $maxLength, $maxAge)
clearNpcCacheFiles($npcName, $responseFormat)  // NEW in v2.0.1
getCacheStats($npcName, $responseFormat)       // NEW in v2.0.1
```

### Sync Invalidation (NEW in v2.0.1)
```php
getSyncHash($npcName, $responseFormat)
setSyncHash($npcName, $hash, $responseFormat)
calculateSyncHash($profileData, $memoryData)
shouldInvalidateSyncCache($npcName, $responseFormat, $profileData, $memoryData)
```

### Simple Format Parsing
```php
buildSimpleFormatInstruction($actions, $includeMood, $includeListener, $includeActions, $includeTarget)
extractSimpleFormatFromBuffer($buffer, $includeMood, $includeListener, $includeActions, $includeTarget)
validateActionName($action)
```

## Caching Implementation

### Cache File Naming
```
temp/system_cache_{format}_{npcName}.tmp
temp/combined_dialogue_cache_{format}_{npcName}.tmp
temp/sync_hash_{format}_{npcName}.tmp
```

Where:
- `{format}` = 'json' or 'simple'
- `{npcName}` = Character name (e.g., 'Lydia')

### Provider-Specific Cache Control

#### Anthropic
```php
$cacheControlType = ["type" => "ephemeral", "ttl" => "1h"];
// Placed at calculated index based on dialogue_cache_uncached_count
$completeEventList[$lastIndex]["cache_control"] = $cacheControlType;
```

#### OpenAI
```php
// No manual cache control - uses model-native caching
// Skip cache_control marker placement
```

#### Gemini
```php
// Batch-based caching
$batchSize = $CONTEXTHISTORY - $offset;
$batchNumber = floor($elements / $batchSize);
$cacheIndex = ($batchNumber + 1) * $batchSize - 1;
```

### Sync Invalidation Flow (v2.0.1)

```
open() called
    │
    ├─ cache_invalidation_mode == 'sync_updates'?
    │       │
    │       └─ YES: _checkSyncInvalidation($npcName)
    │               │
    │               ├─ Load NPC extended_data via NpcMaster
    │               ├─ Extract profile fields + middle_term_memory
    │               ├─ Calculate MD5 hash of data
    │               ├─ Compare with stored hash
    │               │       │
    │               │       └─ Hash mismatch?
    │               │               │
    │               │               └─ YES: clearNpcCacheFiles()
    │               │                       setSyncHash(newHash)
    │               │
    │               └─ Continue to _openPart2()
    │
    └─ NO: Continue to _openPart2()
```

## Response Format Implementation

### JSON Mode
Standard CHIM JSON response processing. Uses existing JSON parsing infrastructure.

### Simple Mode
Custom parser for `(mood)(listener)(action)(target) message` format:

```php
// State machine in _preprocessReasoningTags()
$this->_reasoningState = 'NORMAL' | 'IN_REASONING';

// Metadata extraction in _extractMetadata()
preg_match_all('/\(([^)]+)\)/', $input, $matches);

// Sentence streaming in _splitIntoSentences()
preg_split('/(?<=[.!?])\s+/', $text);
```

## UI Integration

### AJAX Endpoints (llm_connectors.php)

```php
// Cache statistics
GET llm_connectors.php?action=cache_stats
Response: {"npc_count": 5, "total_size": 102400, "total_entries": 450, "oldest_age": 1800}

// Cache clear
POST llm_connectors.php?action=clear_cache
Response: {"success": true, "cleared": 15, "errors": []}
```

### JavaScript Functions

```javascript
// Embedded editor
window.clearNpcCache()
loadCacheStats()

// Main editor
window.clearNpcCacheMain()
loadCacheStatsMain()
```

## Configuration Schema

### conf_schema.json Entry

```json
"openrouterjsoncached": {
    "_title": "OpenRouter API (JSON) with Caching",
    "provider_caching": {"type":"select","values":["Anthropic","OpenAI","Gemini"]},
    "response_format": {"type":"select","values":["json","simple"]},
    "memory_mode": {"type":"select","values":["accumulate","fresh"]},
    "cache_invalidation_mode": {"type":"select","values":["time_based","sync_updates"]},
    "dialogue_cache_uncached_count": {"type":"integer"},
    "max_dialogue_cache_context_size": {"type":"integer"},
    // ... additional settings
}
```

### llm_connector.class.php Defaults

```php
case 'openrouterjsoncached':
    $GLOBALS["CONNECTOR"]["openrouterjsoncached"]["memory_mode"] = 'accumulate';
    $GLOBALS["CONNECTOR"]["openrouterjsoncached"]["cache_invalidation_mode"] = 'time_based';
    // ... decode metadata, set GLOBALS
    break;
```

## Compatibility Enforcement

### global_settings.php Filter

```php
// Incompatible CORE_CONNECTOR types (use fast_request)
$incompatibleWithCached = [
    'CORE_CONNECTOR_PLAYER',
    'CORE_CONNECTOR_SUMMARY',
    'CORE_CONNECTOR_MEDIUMTERM',
    'CORE_CONNECTOR_PROFILES'
];

// Skip cached connector in dropdown for these types
if ($filterCached && $row['driver'] === 'openrouterjsoncached') {
    continue;
}
```

## Testing Checklist

### Syntax Validation
```bash
php -l connector/openrouterjsoncached.php
php -l connector/openrouterjsoncached_helpers.php
```

### Functional Tests
- [ ] JSON format with Anthropic caching
- [ ] Simple format with sentence streaming
- [ ] Memory mode: accumulate (deduplication works)
- [ ] Memory mode: fresh (memories re-sent each request)
- [ ] Cache invalidation: time-based (1h expiry)
- [ ] Cache invalidation: sync_updates (profile/memory changes)
- [ ] Cache statistics display
- [ ] Manual cache clear
- [ ] Reasoning model support (Claude, DeepSeek, OpenAI o-series)
- [ ] Hidden from incompatible CORE_CONNECTOR types

### Integration Tests
- [ ] New connector creation via UI
- [ ] Connector editing and saving
- [ ] Metadata persistence (JSON encoding/decoding)
- [ ] Cache files created in temp/
- [ ] Log files created in log/

## Known Limitations

1. **No Web Search**: "Skyrim search:" feature not implemented
2. **No fast_request()**: Streaming-only, incompatible with summary connectors
3. **Gemini Caching**: Ignores dialogue_cache_uncached_count setting
4. **Sync Invalidation**: Requires NpcMaster class availability

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v2.0.1 | 2026-01-29 | sync_updates invalidation, cache management UI, CHIM 2.3.3 sync |
| v2.0.0 | 2026-01-28 | Port to CHIM 2.3.3, memory mode, close() signature fix |
| v1.4 | 2026-01-21 | Core/Additionals split for CHIM 2.0.5 |
| v1.0-v1.3 | 2026-01-16 | Initial implementation for CHIM 2.0.3 |

## Future Considerations

### Potential Enhancements
- Web search support (port from openrouterjson)
- Per-NPC cache settings
- Cache warming/preloading
- Cache compression

### Upstream Tracking
Monitor `abeiro/HerikaServer` for:
- Changes to openrouterjson.php
- New CORE_CONNECTOR types
- llm_connector.class.php modifications
- conf_schema.json structure changes
