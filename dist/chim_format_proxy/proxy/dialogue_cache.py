"""
Dialogue Cache — per-character persistent dialogue accumulator.

CHIM sends a rolling context window where old messages drop off the front
on each request, making the message prefix unstable and defeating automatic
provider caching. This module accumulates dialogue turns across requests
so the prefix grows monotonically and stays stable.

Storage: JSONL file per character in proxy/cache/<character>.jsonl
Each line: {"role": "user"|"assistant", "content": "...", "hash": "..."}

Design modeled after the Claude subscription proxy's _append_dialogue_turns
(hash-based dedup, JSONL, periodic trim) but with the critical addition of
actually replacing the rolling window with the full cached history.
"""

import hashlib
import json
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger("chim_format_proxy")

CACHE_DIR = Path(__file__).parent / "cache"

# In-memory state per character (rebuilt from disk on first access)
_cache_hashes: dict[str, set[str]] = {}
_cache_turns: dict[str, list[dict]] = {}
_cache_timestamps: dict[str, float] = {}

_NAME_SANITIZE_RE = re.compile(r"[^\w\s.\-']")


def _hash_turn(role: str, content: str) -> str:
    """Stable short hash for dedup. 16 hex chars ~ 64 bits."""
    h = hashlib.sha256()
    h.update(role.encode("utf-8", errors="replace"))
    h.update(b"\x00")
    h.update(content.encode("utf-8", errors="replace"))
    return h.hexdigest()[:16]


def _cache_path(character: str) -> Path:
    safe = _NAME_SANITIZE_RE.sub("_", character).strip() or "unknown"
    return CACHE_DIR / f"{safe}.jsonl"


def _load_from_disk(character: str) -> tuple[list[dict], set[str]]:
    """Load cache from JSONL file. Returns (turns, hash_set)."""
    path = _cache_path(character)
    turns = []
    hashes = set()
    if not path.exists():
        return turns, hashes
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    turns.append(entry)
                    if "hash" in entry:
                        hashes.add(entry["hash"])
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"[cache] Failed to load cache for {character}: {e}")
    return turns, hashes


def _ensure_loaded(character: str) -> None:
    """Populate in-memory cache from disk if not already loaded.

    Also detects external file deletion: if we have in-memory state but the
    JSONL file is gone, treat it as a cache clear (graceful reset).
    """
    if character in _cache_turns:
        # Check if file was deleted externally
        if _cache_turns[character] and not _cache_path(character).exists():
            logger.info(f"[cache] JSONL file deleted externally for {character}, resetting in-memory cache")
            _cache_turns[character] = []
            _cache_hashes[character] = set()
        return
    turns, hashes = _load_from_disk(character)
    _cache_turns[character] = turns
    _cache_hashes[character] = hashes
    _cache_timestamps[character] = time.time()


def clear_cache(character: str) -> None:
    """Clear a character's dialogue cache (memory + disk)."""
    _cache_turns.pop(character, None)
    _cache_hashes.pop(character, None)
    _cache_timestamps.pop(character, None)
    path = _cache_path(character)
    if path.exists():
        path.unlink(missing_ok=True)
    logger.info(f"[cache] Cleared dialogue cache for {character}")


def accumulate_and_expand(
    dialogue_turns: list[dict],
    character: str,
    max_turns: int = 200,
    max_age: int = 3600,
    fresh_threshold: int = 3,
) -> list[dict]:
    """
    Accumulate dialogue turns in the per-character cache and return the
    full cached history. New turns from CHIM's rolling window are deduped
    against the cache and appended.

    Args:
        dialogue_turns: Current dialogue from CHIM (rolling window, raw format)
        character: NPC name (cache key)
        max_turns: Max turns to keep in cache before trimming oldest
        max_age: Seconds before cache is considered stale and cleared
        fresh_threshold: If CHIM sends <= this many turns, assume new
                        conversation and clear cache

    Returns:
        Full dialogue history as message dicts (role + content, no hash)
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Fresh conversation detection — very few turns means new game/session
    if len(dialogue_turns) <= fresh_threshold:
        if character in _cache_turns and _cache_turns[character]:
            logger.info(f"[cache] Fresh conversation for {character} "
                        f"({len(dialogue_turns)} turns <= {fresh_threshold}), clearing")
            clear_cache(character)

    _ensure_loaded(character)

    # Age-based invalidation
    last_ts = _cache_timestamps.get(character, 0)
    if time.time() - last_ts > max_age and _cache_turns.get(character):
        logger.info(f"[cache] Cache expired for {character} (>{max_age}s), clearing")
        clear_cache(character)
        _cache_turns[character] = []
        _cache_hashes[character] = set()

    _cache_timestamps[character] = time.time()

    cache = _cache_turns[character]
    hashes = _cache_hashes[character]

    # Dedup incoming turns against cache, append new ones
    new_entries = []
    for turn in dialogue_turns:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if not content or not isinstance(content, str):
            continue
        h = _hash_turn(role, content)
        if h in hashes:
            continue
        entry = {"role": role, "content": content, "hash": h}
        cache.append(entry)
        hashes.add(h)
        new_entries.append(entry)

    # Persist new entries (append-only)
    if new_entries:
        path = _cache_path(character)
        with open(path, "a", encoding="utf-8") as f:
            for entry in new_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Trim if over max_turns
    if len(cache) > max_turns:
        old_len = len(cache)
        cache = cache[-max_turns:]
        _cache_turns[character] = cache
        _cache_hashes[character] = {e["hash"] for e in cache}
        # Rewrite file with trimmed content
        path = _cache_path(character)
        with open(path, "w", encoding="utf-8") as f:
            for entry in cache:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"[cache] Trimmed {character} from {old_len} to {len(cache)} turns")

    if new_entries:
        logger.info(f"[cache] {character}: +{len(new_entries)} new, "
                     f"{len(cache)} total cached turns")

    # Return as plain message dicts (no hash field)
    return [{"role": e["role"], "content": e["content"]} for e in cache]
