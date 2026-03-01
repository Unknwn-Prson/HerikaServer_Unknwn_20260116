"""Ensure $HTTP_TIMEOUT in conf.php is at least 30s."""
import re, sys

conf = sys.argv[1]
try:
    src = open(conf, encoding="utf-8", errors="replace").read()
except Exception as e:
    print(f"      Could not read conf.php: {e}")
    sys.exit(0)

m = re.search(r'\$HTTP_TIMEOUT\s*=\s*(\d+)\s*;', src)
if m:
    val = int(m.group(1))
    if val >= 30:
        print(f"      HTTP_TIMEOUT is {val}s (OK).")
        sys.exit(0)
    src = re.sub(r'\$HTTP_TIMEOUT\s*=\s*\d+\s*;', '$HTTP_TIMEOUT=30;', src)
    open(conf, "w", encoding="utf-8").write(src)
    print(f"      HTTP_TIMEOUT was {val}s — updated to 30s.")
else:
    insert = '$HTTP_TIMEOUT=30;\t//Timeout for AI requests.\n'
    pos = src.rfind('?>')
    if pos != -1:
        src = src[:pos] + insert + src[pos:]
    else:
        src += '\n' + insert
    open(conf, "w", encoding="utf-8").write(src)
    print("      HTTP_TIMEOUT was not set — added as 30s.")
