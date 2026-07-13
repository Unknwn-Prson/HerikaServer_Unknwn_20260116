# CHIM Bug: NPC biography globals leak across actors

**Severity:** High — silently injects one actor's persona into other NPCs' prompts.
**Version:** CHIM 3.0.0.
**Location:** `lib/core/npc_master.class.php` → `setOldGlobalsFromCurrentNpcData()`.
**Consumer:** `ext/minai_plugin/contextbuilders/context_modules/core_context.php` → `BuildPersonalityContext()`.

## Summary

When an NPC's biography column is `NULL`, the loader neither sets nor clears the
matching `$GLOBALS['HERIKA_*']`. A prior actor loaded earlier in the same request
leaves its value in the global, which is then emitted into the current NPC's prompt.

## Root cause

Seven fields use set-if-`isset` with no `else`:

```php
if (isset($currentNpcData['personality'])) {
    $GLOBALS['HERIKA_PERSONALITY'] = $currentNpcData['personality'];
}
```

`isset(NULL) === false` → the global is left untouched. In the same method,
`HERIKA_RELATIONSHIPS` and the `PATCH_OVERRIDE_VOICE`/`TTS_NPC_*` globals DO clear
via `else { unset(...); }`. These seven were missed:
`HERIKA_BACKGROUND, HERIKA_PERSONALITY, HERIKA_OCCUPATION, HERIKA_APPEARANCE,
HERIKA_SKILLS, HERIKA_SPEECHSTYLE, HERIKA_GOALS`.

## Mechanism

Leak is intra-request (CHIM runs PHP per-request under apache2; `$GLOBALS` reset
each request):

1. During request setup a prior actor's biography globals are populated — e.g.
   The Narrator's, via `narrator.class.php::loadCharacterIntoGlobals()` from
   `core_narrator` on a narration/welcome event.
2. An NPC with `NULL` `personality` then loads → global not overwritten or cleared.
3. `BuildPersonalityContext()` reads the stale global → emits
   `#### Behavioral patterns` / `#### Speech style` from the wrong actor.

## Reproduction

1. Give The Narrator a `personality` (and/or `speechstyle`) value.
2. Use an NPC whose `core_npc_master.personality` is `NULL`.
3. Trigger a narration event, then converse with the NPC.
4. The NPC's prompt now contains the Narrator's personality/speechstyle —
   invisible in the CHIM UI, because it was never the NPC's data.

## Scope

Every NPC with any empty biography field. Contaminant = the prior actor loaded
earlier in the same request (typically The Narrator, which speaks frequently via
welcome / bored / quest / random-narration events).

## Fix

Mirror the existing `relationships` guard for all seven fields:

```php
if (isset($currentNpcData['personality']) && trim((string)$currentNpcData['personality']) !== '') {
    $GLOBALS['HERIKA_PERSONALITY'] = $currentNpcData['personality'];
} else {
    unset($GLOBALS['HERIKA_PERSONALITY']);
}
```

Takes effect on the next request; no restart required.

Automated patch: `apply_npc_bio_leak_fix.py` (idempotent).

## Related, intentionally not patched

`PROMPT_HEAD` (from `prompt_head`) and `OGHMA_KNOWLEDGE` (from
`oghma_knowledge_tags`) share the pattern. Left as-is: an empty value there would
drop required prompt structure, not just an optional bio section — clearing them
needs separate consideration.
