# Design Plan: Diary Injection & Event-Based Generation System

## Overview

Create a parallel injection system where **diaries** and **memories** work independently with separate toggles, plus add configurable diary generation triggers beyond the existing sleep/wait behavior.

**Two major features:**
1. **Diary Injection** - Inject relevant diary entries into NPC context (separate from memory injection)
2. **Diary Generation Modes** - Choose between sleep/wait triggers, event-count triggers, or both

---

## Part 1: Diary Injection System

### 1.1 Configuration Settings

Add to `conf/conf.sample.php` (and `conf.php`):

```php
// ============================================
// DIARY INJECTION SETTINGS
// ============================================

// Enable/disable diary injection into NPC context
$INJECT_DIARIES = true;

// Enable/disable memory injection into NPC context (existing, add toggle if not present)
$INJECT_MEMORIES = true;

// Number of diaries to search/rank when injecting
$DIARY_SEARCH_LIMIT = 5;

// Diary relevance threshold modifier
// Higher = more selective, Lower = more permissive
// Added to base threshold of 0.25
$DIARY_THRESHOLD_MODIFIER = 0.0;

// How old must a diary be (in game hours) before it can be injected?
// Prevents injecting diaries the NPC just wrote moments ago
$DIARY_MIN_AGE_HOURS = 1;

// Context window size for diary search (how much recent context to consider for relevance)
$DIARY_CONTEXT_WINDOW = 50;
```

### 1.2 New Function: `offerDiary()`

**File:** `lib/chat_helper_functions.php`

**Purpose:** Retrieve and rank relevant diary entries for injection, mirroring how `offerMemory()` works.

**Signature:**
```php
function offerDiary($gameRequest) {
    // Returns: string (formatted diary entry) or empty string
}
```

**Logic Flow:**

1. **Check if enabled:** Return early if `$INJECT_DIARIES` is false.

2. **Extract NPC name** from the game request.

3. **Build search keywords:**
   - Use MiniMe-T5 if enabled (AI keyword extraction from recent dialogue)
   - Fallback: regex-based keyword extraction from recent dialogue

4. **Query diaries** (SQL sketch):
   ```sql
   SELECT d.*, m.uid, m.gamets
   FROM diarylog d
   JOIN memory m ON m.event IN ('diary', 'auto_diary', 'nearby_diary', 'backgroundlife_diary')
     AND m.speaker = '{npc_name}'
     AND m.message = d.content
   WHERE d.tags LIKE '%{keyword}%'
     OR d.content LIKE '%{keyword}%'
     OR d.people LIKE '%{keyword}%'
   ORDER BY m.gamets DESC
   LIMIT {DIARY_SEARCH_LIMIT}
   ```

5. **Vector search (if enabled):**
   - If `USE_TEXT2VEC` is enabled: search diary embeddings via TXTAI
   - Otherwise: use PostgreSQL FTS on diary content

6. **Rank results** by keyword matches, recency, and relevance (same approach as memory ranking).

7. **Time validation:**
   ```php
   $hoursAgo = ($currentGameTS - $diary['gamets']) / 3600;
   if ($hoursAgo < $DIARY_MIN_AGE_HOURS) continue; // Skip too-recent diaries
   ```

8. **Threshold check:**
   ```php
   if ($diaries[0]['rank'] >= 0.25 + $DIARY_THRESHOLD_MODIFIER) {
       // Format and return diary
   }
   ```

9. **Format output:**
   ```php
   $timeAgo = formatTimeAgo($hoursAgo);
   return "{$timeAgo}, {$npc_name} wrote in their diary: \"{$diary['content']}\"";
   ```

### 1.3 Integration Point: `main.php`

**Location:** Around line 1656-1676 (where memory injection currently happens)

**Current code (simplified):**
```php
if (in_array($gameRequest[0], ["inputtext", "inputtext_s", "ginputtext", ...])) {
    $memoryInjection = offerMemory($gameRequest);
    if (!empty($memoryInjection)) {
        $memoryInjectionCtx[] = array(
            'role' => 'user',
            'content' => "<memory> {$HERIKA_NAME} remembers this: [$memoryInjection] </memory>"
        );
    }
}
```

**Modified code:**
```php
if (in_array($gameRequest[0], ["inputtext", "inputtext_s", "ginputtext", ...])) {

    // Memory injection (existing, now gated by toggle)
    if ($INJECT_MEMORIES) {
        $memoryInjection = offerMemory($gameRequest);
        if (!empty($memoryInjection)) {
            $memoryInjectionCtx[] = array(
                'role' => 'user',
                'content' => "<memory> {$HERIKA_NAME} remembers this: [$memoryInjection] </memory>"
            );
        }
    }

    // Diary injection (NEW)
    if ($INJECT_DIARIES) {
        $diaryInjection = offerDiary($gameRequest);
        if (!empty($diaryInjection)) {
            $memoryInjectionCtx[] = array(
                'role' => 'user',
                'content' => "<diary> {$HERIKA_NAME} recalls from their diary: [$diaryInjection] </diary>"
            );
        }
    }
}
```

---

## Part 2: Diary Generation Modes

### 2.1 Configuration Settings

Add to `conf/conf.sample.php` (and `conf.php`):

```php
// ============================================
// DIARY GENERATION SETTINGS
// ============================================

// Diary generation mode:
//   "sleep_wait"  = Generate on sleep/wait events only (existing behavior)
//   "event_count" = Generate every X events (NEW - tracked persistently in DB)
//   "both"        = Use both triggers
$DIARY_GENERATION_MODE = "sleep_wait";

// Event-based diary generation: generate a diary every X qualifying events
$DIARY_EVENTS_THRESHOLD = 50;

// Which event types count toward the threshold
$DIARY_EVENTS_TYPE_FILTER = ["inputtext", "ginputtext", "info"];
```

### 2.2 Database Changes

**New table: `diary_event_tracker`**

```sql
CREATE TABLE diary_event_tracker (
    npc_name VARCHAR(255) PRIMARY KEY,
    event_count INT DEFAULT 0,
    last_diary_gamets BIGINT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Purpose:** Persist event counts per NPC across server restarts. Each NPC accumulates events independently, and the counter resets when a diary is generated.

### 2.3 Modified Function: `processAutoDiary()`

**File:** `lib/dynamic_update_util.php` (around line 216)

**Current behavior:** Only triggers on `"goodnight"` and `"waitstart"` events.

**New behavior:**

```php
function processAutoDiary($eventType, $npcName, $gameTS) {
    global $DIARY_GENERATION_MODE, $DIARY_EVENTS_THRESHOLD, $DIARY_EVENTS_TYPE_FILTER;

    $shouldGenerate = false;

    // --- Mode 1: Sleep/Wait (existing behavior) ---
    if ($DIARY_GENERATION_MODE == "sleep_wait" || $DIARY_GENERATION_MODE == "both") {
        if (in_array($eventType, ["goodnight", "waitstart"])) {
            $shouldGenerate = true;
        }
    }

    // --- Mode 2: Event Count (NEW) ---
    if ($DIARY_GENERATION_MODE == "event_count" || $DIARY_GENERATION_MODE == "both") {
        if (in_array($eventType, $DIARY_EVENTS_TYPE_FILTER)) {

            // Increment persistent event counter
            $db->exec("INSERT INTO diary_event_tracker (npc_name, event_count, last_updated)
                       VALUES ('{$npcName}', 1, NOW())
                       ON CONFLICT (npc_name)
                       DO UPDATE SET event_count = diary_event_tracker.event_count + 1,
                                     last_updated = NOW()");

            // Check if threshold reached
            $result = $db->query("SELECT event_count FROM diary_event_tracker
                                  WHERE npc_name = '{$npcName}'");
            $row = $result->fetch();

            if ($row['event_count'] >= $DIARY_EVENTS_THRESHOLD) {
                $shouldGenerate = true;

                // Reset counter
                $db->exec("UPDATE diary_event_tracker
                           SET event_count = 0,
                               last_diary_gamets = {$gameTS}
                           WHERE npc_name = '{$npcName}'");
            }
        }
    }

    // --- Generate diary if triggered ---
    if ($shouldGenerate) {
        if (!isDiaryCooldownActive($npcName)) {
            generateFollowerDiary($npcName, $gameTS);
        }
    }
}
```

### 2.4 Helper: `getDiaryEventCount()`

**Purpose:** Query current event count for an NPC (useful for UI display and debugging).

```php
function getDiaryEventCount($npcName) {
    global $db;
    $result = $db->query("SELECT event_count FROM diary_event_tracker
                          WHERE npc_name = '{$npcName}'");
    $row = $result->fetch();
    return $row ? $row['event_count'] : 0;
}
```

---

## Part 3: UI Integration

### 3.1 Global Settings Page

**File:** `ui/global_settings.php`

Add a new section for diary settings:

```html
<div class="setting-group">
    <h3>Diary Injection Settings</h3>

    <label>
        <input type="checkbox" name="INJECT_DIARIES" value="1"
               <?php echo $INJECT_DIARIES ? 'checked' : ''; ?>>
        Enable Diary Injection (inject diary entries into NPC context)
    </label>

    <label>
        <input type="checkbox" name="INJECT_MEMORIES" value="1"
               <?php echo $INJECT_MEMORIES ? 'checked' : ''; ?>>
        Enable Memory Injection (inject memory summaries into NPC context)
    </label>

    <label>
        Diary Search Limit:
        <input type="number" name="DIARY_SEARCH_LIMIT"
               value="<?php echo $DIARY_SEARCH_LIMIT; ?>" min="1" max="20">
    </label>

    <label>
        Diary Threshold Modifier:
        <input type="number" name="DIARY_THRESHOLD_MODIFIER" step="0.05"
               value="<?php echo $DIARY_THRESHOLD_MODIFIER; ?>" min="-0.5" max="0.5">
    </label>

    <label>
        Diary Minimum Age (game hours):
        <input type="number" name="DIARY_MIN_AGE_HOURS"
               value="<?php echo $DIARY_MIN_AGE_HOURS; ?>" min="0" max="24">
    </label>
</div>

<div class="setting-group">
    <h3>Diary Generation Settings</h3>

    <label>
        Generation Mode:
        <select name="DIARY_GENERATION_MODE" id="diary_gen_mode">
            <option value="sleep_wait"  <?php echo $DIARY_GENERATION_MODE == 'sleep_wait'  ? 'selected' : ''; ?>>
                Sleep/Wait Events Only
            </option>
            <option value="event_count" <?php echo $DIARY_GENERATION_MODE == 'event_count' ? 'selected' : ''; ?>>
                Every X Events
            </option>
            <option value="both"        <?php echo $DIARY_GENERATION_MODE == 'both'        ? 'selected' : ''; ?>>
                Both
            </option>
        </select>
    </label>

    <label id="event_threshold_setting"
           style="display: <?php echo in_array($DIARY_GENERATION_MODE, ['event_count', 'both']) ? 'block' : 'none'; ?>;">
        Generate Diary Every X Events:
        <input type="number" name="DIARY_EVENTS_THRESHOLD"
               value="<?php echo $DIARY_EVENTS_THRESHOLD; ?>" min="10" max="500">
    </label>
</div>

<script>
document.getElementById('diary_gen_mode').addEventListener('change', function() {
    var show = (this.value === 'event_count' || this.value === 'both');
    document.getElementById('event_threshold_setting').style.display = show ? 'block' : 'none';
});
</script>
```

---

## Part 4: Implementation Order

### Phase 1: Diary Injection (Core)
1. Add config settings to `conf/conf.sample.php`
2. Create `offerDiary()` in `lib/chat_helper_functions.php`
3. Integrate diary injection call in `main.php` (alongside existing memory injection)
4. Test with existing diary data

### Phase 2: Event-Based Generation
1. Create `diary_event_tracker` table (add migration or setup SQL)
2. Modify `processAutoDiary()` in `lib/dynamic_update_util.php`
3. Add `getDiaryEventCount()` helper
4. Test: event counting increments, threshold triggers generation, counter resets, persistence across restarts

### Phase 3: UI Integration
1. Add diary settings section to `ui/global_settings.php`
2. Add JavaScript for conditional show/hide of event-count options
3. Add tooltips / inline help text

### Phase 4: Testing & Polish
1. Test diary injection with various conversation topics
2. Test event-based generation: accumulation, threshold trigger, server restart persistence
3. Test "both" mode (sleep/wait AND event-count triggers coexisting)
4. Performance check on diary search queries (ensure indexes exist)
5. Update user-facing documentation if applicable

---

## Part 5: Edge Cases & Considerations

### Diary Injection
| Scenario | Handling |
|----------|----------|
| No diaries exist for NPC | Return empty string, no injection |
| Multiple diaries match | Rank by relevance + recency, return best match |
| Diary was just written | Skip if younger than `DIARY_MIN_AGE_HOURS` |
| Both diary and memory match | Both injected independently (separate context entries) |
| Diary content is very long | Truncate to reasonable length before injection |

### Event-Based Generation
| Scenario | Handling |
|----------|----------|
| Server restarts mid-count | Counts persist in `diary_event_tracker` table |
| Multiple NPCs active | Each tracked independently by `npc_name` |
| Irrelevant event types | Filtered by `$DIARY_EVENTS_TYPE_FILTER` |
| Both modes active | Either trigger can fire; cooldown prevents double-generation |
| Rapid events near threshold | Cooldown check (`isDiaryCooldownActive`) prevents spam |

### Performance
| Concern | Mitigation |
|---------|------------|
| Diary search speed | Index `diarylog.tags`, `diarylog.people`; limit results |
| Event tracking overhead | Single DB upsert per qualifying event |
| Vector search | Reuse existing TXTAI infrastructure; embed diaries same as memories |

---

## Part 6: Files Changed Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `conf/conf.sample.php` | **Edit** | Add diary injection + generation config settings |
| `lib/chat_helper_functions.php` | **Edit** | Add `offerDiary()` function (~100 lines) |
| `main.php` | **Edit** | Add diary injection call next to memory injection (~15 lines) |
| `lib/dynamic_update_util.php` | **Edit** | Modify `processAutoDiary()` for event-count mode (~50 lines) |
| `ui/global_settings.php` | **Edit** | Add diary settings UI section (~50 lines) |
| Database | **Migration** | Create `diary_event_tracker` table |

**Estimated new code:** ~300-400 lines

---

## Summary of Capabilities

- [x] Independent diary/memory injection toggles
- [x] Diary generation on sleep/wait (existing behavior, now configurable)
- [x] Diary generation every X events (persistent across server restarts)
- [x] Hybrid mode (both triggers)
- [x] Full UI configurability
- [x] No breaking changes to existing systems
