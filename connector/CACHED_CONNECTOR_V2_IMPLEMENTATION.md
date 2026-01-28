# OpenRouter Cached Connector v2 - Implementation Documentation

This document tracks the implementation process for porting the cached connector from CHIM 2.0.5 to CHIM 2.2.

## Overview

**Base file:** `origin/aiagent:connector/openrouterjson.php` (CHIM 2.2, 1454 lines)
**Target file:** `connector/openrouterjsoncached_v2.php`
**Reference:** `connector/openrouterjsoncached.php` (v1.4 for CHIM 2.0.5)

## Architecture Differences

The cached connector fundamentally restructures how requests are processed:

| Aspect | Regular Connector | Cached Connector |
|--------|-------------------|------------------|
| `open()` method | Monolithic (~600 lines) | Split into 4 parts |
| Context handling | Pass-through | Temp file caching with deduplication |
| Response format | JSON only | JSON or Simple format |
| Sentence streaming | N/A | Built-in for simple format |
| `fast_request()` | Available | Removed (streaming-only) |

## Compatibility

**Compatible connector types:**
- CORE_CONNECTOR_DIRECTOR (streaming)
- Main conversation connector (CONNECTORS selection)

**Incompatible connector types (uses fast_request):**
- CORE_CONNECTOR_MEDIUMTERM
- CORE_CONNECTOR_OGHMA_CUSTOM
- CORE_CONNECTOR_PLAYER
- CORE_CONNECTOR_PROFILES
- CORE_CONNECTOR_SUMMARY

These must be hidden from selection in the UI/schema.

---

## Implementation Steps

### Step 1: Class Rename and Metadata
**Status:** Pending

Changes:
- [ ] Rename class from `openrouterjson` to `openrouterjsoncached`
- [ ] Add VERSION constant after class declaration
- [ ] Add header comment describing the connector
- [ ] Update `$this->name` in constructor to `"openrouterjsoncached"`

```php
// Add after line 5:
// Cached version of openrouterjson connector with Anthropic/OpenAI/Gemini cache support
// Based on CHIM 2.2 architecture with additional caching and response format features

// Change line 6:
class openrouterjsoncached

// Add after class opening:
const VERSION = 'OpenRouter Cache Connector v2.0 for CHIM 2.2 | 2026/01/28';

// Change in constructor:
$this->name="openrouterjsoncached";
```

---

### Step 2: Add New Properties
**Status:** Pending

Add these properties after `$_lastStreamedObject` (around line 44):

```php
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

// Memory handling mode (NEW in v2)
private $_memoryMode; // 'accumulate' or 'fresh'
```

---

### Step 3: Update Constructor
**Status:** Pending

Changes to constructor:
- [ ] Change `$this->name` to `"openrouterjsoncached"`
- [ ] Initialize all new caching properties
- [ ] Add helper file inclusion
- [ ] Add initialization log message

```php
// After existing initializations, add:

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
$this->_memoryMode = 'accumulate'; // default

// Initialize simple format parser state
$this->_reasoningState = 'NORMAL';
$this->_reasoningTagType = '';
$this->_metadataEnd = -1;
$this->_sentencesSent = 0;
$this->_metadataGroups = [];
$this->_flushedPartial = false;

require_once(__DIR__."/__jpd.php");
require_once(__DIR__."/openrouterjsoncached_helpers.php");

logMessage("[{$this->name}] OpenRouter Cached Connector v" . self::VERSION . " initialized");
```

---

### Step 4: Add New Methods
**Status:** Pending

New methods to add:

#### 4.1 `handlesSentenceSplitting()`
```php
public function handlesSentenceSplitting() {
    return ($this->_responseFormat === 'simple');
}
```

#### 4.2 `isAlwaysReasoningModel()`
Detects models that always have reasoning enabled (o1, o3, o4, gpt-5, DeepSeek-R1).

#### 4.3 Simple Format Parser Methods
- `_preprocessReasoningTags()` - Strip <think>/<thinking>/<answer> tags
- `_extractMetadata()` - Extract (mood)(listener)(action)(target) groups
- `_mapGroupsToFields()` - Map groups to global variables
- `_flushRemainingSimpleFormat()` - End-of-stream flushing
- `_splitIntoSentences()` - Split on sentence endings (with trailing space fix)
- `_parseAndReturnContent()` - Unified content parsing dispatcher

---

### Step 5: Rewrite open() Method
**Status:** Pending

The monolithic `open()` method must be split into 4 parts:

#### Part 1: `open()` - Initialization and Configuration
- Read all config parameters
- Set up cache file paths
- Initialize response format settings
- Call `_openPart2()`

#### Part 2: `_openPart2()` - System Prompt Processing
- Extract dynamic sections (Environmental Context, etc.)
- Build action prompt with minimize_quality_prompt filtering
- Build format instruction (JSON template or simple format)
- Handle custom system instruction
- Apply cache control to system entries
- Call `_openPart3()`

#### Part 3: `_openPart3()` - Dialogue History Caching
- Process non-system context entries
- **NEW: Filter out <memory> tags if memoryMode='fresh'**
- Manage cached event list via `manageCharacterEventList()`
- Calculate cache control placement
- Handle prefill for simple format
- **NEW: Re-add memory items at end if filtered**
- Call `_openPart4()`

#### Part 4: `_openPart4()` - Payload Construction and API Request
- Build reasoning configuration
- Construct final payload with caching parameters
- Add Anthropic beta header for extended cache TTL
- Open HTTP stream

**CHIM 2.2 features to preserve:**
- Web search detection and handling (make toggleable)
- Zonos TTS tone support
- Grok model detection
- New model detection (gpt-5, gpt-oss-*)

---

### Step 6: Rewrite process() Method
**Status:** Pending

Changes:
- Support both Anthropic-native and OpenAI SSE formats
- Add cache efficiency logging on message_stop
- Call `_parseAndReturnContent()` for format-aware parsing
- Handle simple format sentence streaming
- **BUG FIX: Add trailing space to returned sentences**

---

### Step 7: Rewrite close() and processActions()
**Status:** Pending

#### close()
- Remove database audit inserts
- Use structured log format with LOCK_EX
- Reset stream state

#### processActions()
- Support both JSON and simple format
- Use `extractSimpleFormatFromBuffer()` helper for simple format
- Validate action names

---

### Step 8: Remove fast_request()
**Status:** Pending

Remove the entire `fast_request()` method. This connector is streaming-only.

---

## Bug Fixes in v2

### BUG FIX 1: Word Joining
**Problem:** Sentences returned without trailing spaces, causing "Hello.How are you?"
**Fix:** In `_splitIntoSentences()` or return statements, add trailing space to sentences.

```php
// In _parseAndReturnContent, around line 1401:
return $sentence . ' ';  // Add trailing space
```

---

## New Features in v2

### Feature 1: Memory Handling Toggle
**Config key:** `memory_mode`
**Values:** `'accumulate'` (default) | `'fresh'`

- `accumulate`: Memories persist in dialogue cache with deduplication (current behavior)
- `fresh`: Memories excluded from cache, fresh each request (like regular connector)

Implementation in `_openPart3()`:
```php
// Before manageCharacterEventList:
$memoryItems = [];
if ($this->_memoryMode === 'fresh') {
    foreach ($contentTextToSend as $key => $item) {
        if (strpos($item['text'], '<memory>') !== false) {
            $memoryItems[] = $item;
            unset($contentTextToSend[$key]);
        }
    }
    $contentTextToSend = array_values($contentTextToSend);
}

// After cache processing, before adding instruction:
if ($this->_memoryMode === 'fresh' && !empty($memoryItems)) {
    $completeEventList = array_merge($completeEventList, $memoryItems);
}
```

### Feature 2: Cache Sync with Dynamic Updates
**Config key:** `cache_invalidation_mode`
**Values:** `'time_based'` (default) | `'sync_updates'`

- `time_based`: Current behavior (context-size + 1h inactivity)
- `sync_updates`: Invalidate cache when dynamic profile or middle-term memory changes

Implementation: Check NPC's `extended_data` modification timestamp against cache file timestamp.

---

## Supporting File Changes

### conf/conf_schema.json
- Add `openrouterjsoncached` config block with all new settings
- Add `memory_mode` and `cache_invalidation_mode` settings
- Hide from incompatible CORE_CONNECTOR_* types

### lib/core/llm_connector.class.php
- Add `openrouterjsoncached` driver case in `setOldGlobals()`
- Handle metadata JSON for extended settings

### ui/core/llm_connectors.php
- Add UI controls for cached connector settings
- Conditional display based on feature markers

---

## Testing Checklist

- [ ] Syntax check: `php -l connector/openrouterjsoncached_v2.php`
- [ ] JSON format works with Anthropic caching
- [ ] Simple format works with sentence streaming
- [ ] Sentences have proper spacing (no word joining)
- [ ] Memory toggle works (accumulate vs fresh)
- [ ] Cache invalidation modes work
- [ ] Web search can be disabled
- [ ] Hidden from incompatible connector types in UI
- [ ] Middle-term memory injection works correctly
- [ ] Dynamic profile content cached appropriately

---

## Version History

| Version | Date | CHIM Version | Changes |
|---------|------|--------------|---------|
| v1.0-v1.4 | 2026-01-16 to 2026-01-21 | CHIM 2.0.3-2.0.5 | Initial implementation, Core/Additionals split |
| v2.0 | 2026-01-28 | CHIM 2.2 | Port to CHIM 2.2, memory toggle, cache sync, bug fixes |
