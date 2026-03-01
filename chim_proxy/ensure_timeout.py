"""Ensure $HTTP_TIMEOUT in conf.php is at least 30s."""
import os, re, sys

CONF = r"\\wsl.localhost\DwemerAI4Skyrim3\var\www\html\HerikaServer\conf\conf.php"

try:
    if not os.path.exists(CONF):
        print("      conf.php not found - skipping.")
        sys.exit(0)

    src = open(CONF, encoding="utf-8", errors="replace").read()

    m = re.search(r'\$HTTP_TIMEOUT\s*=\s*(\d+)\s*;', src)
    if m:
        val = int(m.group(1))
        if val >= 30:
            print("      HTTP_TIMEOUT is %ds (OK)." % val)
            sys.exit(0)
        src = re.sub(r'\$HTTP_TIMEOUT\s*=\s*\d+\s*;', '$HTTP_TIMEOUT=30;', src)
        open(CONF, "w", encoding="utf-8").write(src)
        print("      HTTP_TIMEOUT was %ds - updated to 30s." % val)
    else:
        insert = '$HTTP_TIMEOUT=30;\t//Timeout for AI requests.\n'
        pos = src.rfind('?>')
        if pos != -1:
            src = src[:pos] + insert + src[pos:]
        else:
            src += '\n' + insert
        open(CONF, "w", encoding="utf-8").write(src)
        print("      HTTP_TIMEOUT was not set - added as 30s.")
except Exception as e:
    print("      Could not check HTTP_TIMEOUT: %s" % e)
