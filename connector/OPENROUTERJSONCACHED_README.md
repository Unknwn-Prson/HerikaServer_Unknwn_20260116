# OpenRouter Cached Connector v1.7.6

A high-performance cached connector for CHIM 2.4.3+ with multi-provider caching support, flexible response formats, automatic cache invalidation, diary injection, event-based diary generation, and comprehensive cache management tools.

## Version Information

| Version | CHIM Version | Release Date |
|---------|--------------|--------------|
| v1.7.6  | CHIM 2.4.3+  | 2026-02-27   |
| v1.6.0  | CHIM 2.4.3+  | 2026-02-12   |
| v1.5.16 | CHIM 2.3.3   | 2026-02-11   |
| v1.5.5  | CHIM 2.3.3   | 2026-02-06   |
| v1.5.0  | CHIM 2.3.3   | 2026-02-04   |
| v2.0.1  | CHIM 2.3.3   | 2026-01-29   |

## Features

### Core Caching
- **Multi-Provider Support**: Anthropic, OpenAI, and Gemini caching systems
- **File-Based Caching**: Separate caching for system prompts and dialogue history
- **Dynamic Content Extraction**: Automatically separates static character info from dynamic environment data
- **Cache Performance Logging**: Track cache efficiency with detailed metrics

### Cache Management
- **Automatic Invalidation**: Time-based (1h inactivity) or sync with profile/memory updates
- **Cache Statistics UI**: View NPC count, total size, entry count directly in CHIM UI
- **Manual Cache Clear**: One-click button to clear all NPC cache files
- **Memory Mode Toggle**: Choose between accumulated (deduplicated) or fresh memory handling

### Diary Features (NEW in v1.7.6)
- **Diary Injection**: Recall relevant diary entries during NPC dialogue via FTS/vector search
- **Event-Based Generation**: Alternative to sleep/wait-only diary triggers
- **Profile-Based Settings**: Per-profile and per-NPC diary configuration
- **Three Generation Modes**: sleep_wait (original), event_count (new), both

### Response Format Flexibility
- **JSON Mode** (default): Structured JSON responses with full validation
- **Simple Mode**: Natural language format with parenthetical metadata `(mood)(listener)(action)(target) message`

### Reasoning/Thinking Support
- Full support for reasoning models (Claude 4.5, DeepSeek, OpenAI o-series)
- Automatic reasoning token stripping from output
- Configurable thinking tokens and effort levels

### Granular Content Controls
Toggle individual response components:
- Actions list (Talk, Attack, Cast, etc.)
- Mood requirement
- Target requirement
- Listener requirement

## Installation

### Quick Install (Recommended)
1. Download `openrouterjsoncached_v1.7.6_CHIM2.4.3.zip`
2. Extract contents directly into your HerikaServer folder
3. Overwrite existing files when prompted

### Manual Install
Copy these files to your HerikaServer installation:
```
connector/openrouterjsoncached.php
connector/openrouterjsoncached_helpers.php
conf/conf_schema.json
lib/core/llm_connector.class.php
ui/core/llm_connectors.php
```

See INSTALLATION_INSTRUCTIONS.txt for the full list including upstream overwrites.

## Configuration

### UI Configuration (Recommended)
1. Go to **CHIM UI -> LLM Connectors**
2. Create a new connector or edit existing
3. Set **Driver** to `openrouterjsoncached`
4. Configure settings in the **Caching Settings** section

### Available Settings

| Setting | Options | Description |
|---------|---------|-------------|
| Provider Caching Type | Anthropic, OpenAI, Gemini | Which provider's caching system to use |
| Response Format | JSON, Simple | Output format from LLM |
| Uncached Dialogue Count | 0-10 | Recent messages to keep uncached for freshness |
| Max Cache Context Size | Integer | Maximum dialogue entries to cache |
| Memory Mode | Accumulate, Fresh | How to handle memory injections |
| Cache Invalidation | Time-based, Sync | When to invalidate cache |
| Minimize Quality Prompt | On/Off | Use minimal instructions for advanced models |

### Reasoning Settings

| Setting | Description |
|---------|-------------|
| Toggle Thinking | Enable/disable reasoning for supported models |
| Thinking Tokens | Max tokens for reasoning (Anthropic/Gemini) |
| Effort Level | Reasoning depth for OpenAI models (minimal/low/medium/high) |

### Diary Settings (Profile-Level)

| Setting | Default | Description |
|---------|---------|-------------|
| Inject Diaries | ON | Recall diary entries during dialogue |
| Diary Threshold Modifier | 0.0 | Scoring threshold adjustment (+stricter, -permissive) |
| Diary Min Age Hours | 1 | Minimum in-game hours before entry can be recalled |
| Diary Generation Mode | sleep_wait | How diary generation is triggered |
| Diary Events Threshold | 50 | Events before auto-generation triggers (event_count mode) |

### Advanced Settings

| Setting | Description |
|---------|-------------|
| Custom System Instruction | Additional instruction added to system prompt |
| Custom Last Instruction | Text inserted before user's current message |

## Cache Provider Details

### Anthropic Caching (Recommended)
- Uses `cache_control` with ephemeral cache (1 hour TTL)
- Caches system prompts automatically
- Places cache breakpoint based on uncached dialogue count
- Best cache hit rates and longest TTL
- **Best for**: Claude models (claude-3.5-sonnet, claude-4, etc.)

### OpenAI Caching
- Uses model-native caching (automatically handled)
- No manual cache control markers needed
- Effort-based reasoning: minimal, low, medium, high
- **Best for**: GPT-4, GPT-5, o1/o3/o4 reasoning models

### Gemini Caching
- Uses batch-based caching strategy
- Calculates cache index based on context history
- Optimal for very long conversations
- **Note**: Ignores uncached dialogue count setting

## Response Format Modes

### JSON Mode (Default)
```json
{
    "mood": "concerned",
    "listener": "Player",
    "action": "Talk",
    "target": "Player",
    "message": "I'm worried about that cave we just passed."
}
```
**When to use**: Maximum structure, easier debugging, full validation

### Simple Mode
```
(concerned)(Player)(Talk)(Player) I'm worried about that cave we just passed.
```
**When to use**: More natural LLM output, lower token usage, faster responses, less capable models

## Cache Invalidation Modes

### Time-Based (Default)
- Cache expires after 1 hour of inactivity
- Cache cleared when max context size exceeded
- Simple, predictable behavior

### Sync with Updates
- Everything from time-based, PLUS:
- Automatically detects changes in dynamic profile
- Automatically detects changes in middle-term memory
- Clears cache when profile/memory data changes
- **Best for**: Games with frequently updating NPC profiles

## Memory Modes

### Accumulate (Default)
- Memories are deduplicated across requests
- Each memory appears once in the cached context
- More cache-efficient
- **Best for**: Most use cases

### Fresh
- Memories placed at end of context, outside cache
- Re-sent with each request (like regular connector)
- **Best for**: When memories seem stale or not updating

## Cache Management UI

The connector includes a cache management section in the LLM Connectors UI:

### Cache Statistics
Displays real-time information:
- **Total NPCs cached**: Number of NPCs with active cache files
- **Total size**: Combined size of all cache files
- **Total entries**: Number of dialogue entries across all caches
- **Oldest cache**: Age of the oldest cache file

### Manual Cache Clear
One-click button to clear all cache files:
- Clears dialogue cache files
- Clears system cache files
- Clears sync hash files
- Displays success/error status

## Compatibility

### Compatible Connector Types
- **CORE_CONNECTOR (Main)**: Primary conversation connector
- **CORE_CONNECTOR_DIRECTOR**: Director mode

### Incompatible Connector Types
These use `fast_request()` which is not supported:
- CORE_CONNECTOR_PLAYER
- CORE_CONNECTOR_SUMMARY
- CORE_CONNECTOR_MEDIUMTERM
- CORE_CONNECTOR_PROFILES

The cached connector is automatically hidden from these selections in the UI.

## Limitations

### Web Search Not Supported
The "Skyrim search:" feature is **not currently supported** by the cached connector. If you need web search functionality, use the standard `openrouterjson` connector instead.

### Streaming Only
This connector is streaming-only. The `fast_request()` method is not implemented, which is why it cannot be used for summary/profile connectors.

## File Locations

### Connector Files
```
connector/openrouterjsoncached.php        - Main connector class
connector/openrouterjsoncached_helpers.php - Helper functions
```

### Cache Files (auto-generated)
```
temp/system_cache_{format}_{npc}.tmp           - Cached system prompts
temp/combined_dialogue_cache_{format}_{npc}.tmp - Cached dialogue history
temp/sync_hash_{format}_{npc}.tmp              - Profile/memory hashes (sync mode)
```

### Log Files
```
log/cache.log         - General caching logs
log/_cached_perf.log  - Cache performance metrics
```

## Performance Tips

### Optimal Cache Settings
- **Max Cache Context Size**: 93-150 for most uses (93 = ~1 hour gameplay)
- **Uncached Dialogue Count**: 4-6 for balance between freshness and efficiency

### Provider Selection
| Provider | Best For | Cache Hit Rate |
|----------|----------|----------------|
| Anthropic | Claude models, best overall | Highest |
| OpenAI | GPT-4/5, reasoning models | Good |
| Gemini | Very long conversations | Good |

### Format Selection
- Use **JSON** for complex interactions, debugging, full features
- Use **Simple** for faster responses, lower costs, simpler models

### Content Controls
- Disable unused features to reduce prompt size
- Actions list is the largest component (~500-1000 tokens)
- Disabling actions significantly reduces prompt tokens

## Troubleshooting

### Cache Not Working
1. Check `temp/` directory exists and is writable
2. Verify provider_caching matches your model provider
3. Check `log/cache.log` for errors
4. Ensure API key has cache access (Anthropic tier requirements)

### Low Cache Efficiency
- Increase max_dialogue_cache_context_size
- Decrease dialogue_cache_uncached_count (keep >2 for freshness)
- Check if dynamic content is being re-cached

### Simple Format Not Parsing
- Ensure LLM is using parentheses format: `(value)(value)`
- Check `log/cache.log` for parsing errors
- Try enabling fewer components initially
- Consider using JSON format for more reliable parsing

### Actions Not Triggering
- Ensure include_actions_list is enabled
- Verify include_target_requirement is enabled (required for actions)
- Check action name is in valid actions list
- Review `log/cache.log` for processActions() errors

### Cache Not Clearing on Profile Updates
- Ensure cache_invalidation_mode is set to "Sync with updates"
- Check that NPC has extended_data with dynamic profile fields
- Verify temp/ directory is writable

### Diary Entries Not Injected
- Check INJECT_DIARIES is enabled in the active profile
- Verify diary entries exist in memory_summary
- Check DIARY_MIN_AGE_HOURS is not filtering out all entries

### Event-Based Diary Not Triggering
- Check DIARY_GENERATION_MODE is "event_count" or "both"
- Verify DIARY_EVENTS_THRESHOLD is reasonable (default 50)
- Ensure AUTO_DIARY is enabled globally

## Version History

| Version | Date | CHIM | Changes |
|---------|------|------|---------|
| v1.7.6 | 2026-02-27 | 2.4.3+ | Diary injection, event-based diary, profile settings, AUTO_DIARY_WAIT removed |
| v1.6.0 | 2026-02-12 | 2.4.3+ | CHIM 2.4.3 compatibility update |
| v1.5.16 | 2026-02-11 | 2.3.3 | JSON format stream end fix |
| v1.5.5 | 2026-02-06 | 2.3.3 | fast_request(), upstream sync |
| v2.0.1 | 2026-01-29 | 2.3.3 | sync_updates invalidation, cache stats UI, cache clear button |
| v2.0.0 | 2026-01-28 | 2.3.3 | Port to CHIM 2.3.3, memory mode toggle, close() signature fix |
| v1.4 | 2026-01-21 | 2.0.5 | Core/Additionals split, bug fixes |
| v1.0-v1.3 | 2026-01-16 | 2.0.3 | Initial implementation |

## Credits

Based on:
- Original CHIM Anthropic cache connector
- OpenRouter JSON connector
- Enhanced with caching, response formats, diary features, and management tools

## Support

For issues or questions:
- GitHub: https://github.com/Unknwn-Prson/HerikaServer_Unknwn_20260116
- CHIM Discord community
