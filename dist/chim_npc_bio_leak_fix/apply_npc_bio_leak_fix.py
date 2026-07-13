#!/usr/bin/env python3
"""
CHIM NPC Biography Leak Fix — Auto-patcher
=========================================

Fixes a cross-actor prompt-contamination bug in CHIM 3.0.0.

Bug: setOldGlobalsFromCurrentNpcData() in lib/core/npc_master.class.php sets the
HERIKA_* biography globals with a bare `if (isset($currentNpcData['field']))` and
NO `else`. When an NPC's column is NULL, isset() is false, so the global is neither
set nor cleared. In the resident server process the PREVIOUS actor's value (usually
The Narrator's) persists and is injected into the current NPC's prompt by
minai's BuildPersonalityContext(). See BUG_REPORT.md.

Fix: mirror the existing `unset($GLOBALS['HERIKA_RELATIONSHIPS'])` guard — set the
global only when the NPC has a non-empty value, otherwise unset it.

This patcher is idempotent and safe to re-run (e.g. after a CHIM update).

Run from WSL:  python3 apply_npc_bio_leak_fix.py /var/www/html/HerikaServer
"""

import re
import shutil
import sys
from pathlib import Path

MARKER = "NPC_BIO_LEAK_FIX"

# (npc_data column, target global) — the seven biography fields consumed by
# BuildPersonalityContext() that use the unsafe set-if-isset pattern.
# NOTE: prompt_head/PROMPT_HEAD and oghma_knowledge_tags/OGHMA_KNOWLEDGE share the
# pattern but are intentionally left alone (clearing them risks removing required
# prompt structure rather than an optional bio section). See BUG_REPORT.md.
PAIRS = [
    ("npc_static_bio", "HERIKA_BACKGROUND"),
    ("personality",    "HERIKA_PERSONALITY"),
    ("occupation",     "HERIKA_OCCUPATION"),
    ("appearance",     "HERIKA_APPEARANCE"),
    ("skills",         "HERIKA_SKILLS"),
    ("speechstyle",    "HERIKA_SPEECHSTYLE"),
    ("goals",          "HERIKA_GOALS"),
]


def backup(path: Path):
    bak = path.with_suffix(path.suffix + ".npcbiofix.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"  Backup: {bak.name}")


def build_pattern(field: str, glob: str) -> re.Pattern:
    """Match the exact 3-line set-if-isset block, tolerant of whitespace."""
    f = re.escape(field)
    g = re.escape(glob)
    return re.compile(
        r"(?m)^([ \t]*)if \(isset\(\$currentNpcData\['" + f + r"'\]\)\)\s*\{\n"
        r"[ \t]*\$GLOBALS\['" + g + r"'\]\s*=\s*\$currentNpcData\['" + f + r"'\];\n"
        r"[ \t]*\}"
    )


def make_replacement(field: str, glob: str):
    def _repl(m: re.Match) -> str:
        indent = m.group(1)
        body = indent + "    "
        return (
            f"{indent}if (isset($currentNpcData['{field}']) && trim((string)$currentNpcData['{field}']) !== '') {{ // {MARKER}\n"
            f"{body}$GLOBALS['{glob}'] = $currentNpcData['{field}'];\n"
            f"{indent}}} else {{\n"
            f"{body}unset($GLOBALS['{glob}']);\n"
            f"{indent}}}"
        )
    return _repl


def patch(herika: Path) -> bool:
    path = herika / "lib" / "core" / "npc_master.class.php"
    if not path.exists():
        print(f"  [ERROR] {path} not found")
        return False

    content = path.read_text(encoding="utf-8")
    if MARKER in content:
        print("  [SKIP] Already patched")
        return True

    patched = 0
    missing = []
    for field, glob in PAIRS:
        new_content, n = build_pattern(field, glob).subn(make_replacement(field, glob), content, count=1)
        if n:
            content = new_content
            patched += 1
            print(f"  [OK] Guarded {glob} (from '{field}')")
        else:
            missing.append(f"{glob} (from '{field}')")

    for m in missing:
        print(f"  [WARN] Block not found — CHIM may have changed: {m}")

    # Abort rather than write a half-fix if a confirmed-contaminating field is missing.
    missing_text = " ".join(missing)
    if "HERIKA_PERSONALITY" in missing_text or "HERIKA_SPEECHSTYLE" in missing_text:
        print("  [ERROR] Critical field (personality/speechstyle) not found. Aborting write.")
        return False

    backup(path)
    path.write_text(content, encoding="utf-8")
    print(f"  [OK] Patched {patched}/{len(PAIRS)} biography fields")
    return True


def main() -> int:
    herika = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/var/www/html/HerikaServer")
    if not herika.exists():
        print(f"[ERROR] HerikaServer directory not found: {herika}")
        return 1

    print(f"CHIM NPC Biography Leak Fix — patching {herika}")
    print()
    ok = patch(herika)
    print()
    if ok:
        print("Done. The fix takes effect on the next request — no server restart")
        print("required (CHIM runs PHP per-request under apache2; opcache picks up")
        print("the edited file automatically).")
    else:
        print("Patch failed. See messages above. No changes written.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
