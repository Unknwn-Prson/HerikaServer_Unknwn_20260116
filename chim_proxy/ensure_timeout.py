"""Ensure $HTTP_TIMEOUT in conf.php is at least 30s."""
import os, re, sys

CONF = r"\\wsl.localhost\DwemerAI4Skyrim3\var\www\html\HerikaServer\conf\conf.php"

try:
    if not os.path.exists(CONF):
        print("      conf.php not found - skipping.")
        sys.exit(0)

    # Read as raw bytes to detect encoding and avoid silent corruption
    raw = open(CONF, "rb").read()

    # Try UTF-8-BOM first, then UTF-8, then Latin-1 (which never fails)
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            src = raw.decode(enc)
            detected_enc = enc
            break
        except UnicodeDecodeError:
            continue

    m = re.search(r'\$HTTP_TIMEOUT\s*=\s*(\d+)\s*;', src)
    if m:
        val = int(m.group(1))
        if val >= 30:
            print("      HTTP_TIMEOUT is %ds (OK)." % val)
            sys.exit(0)
        # Replace only the first occurrence to avoid touching comments/conditionals
        src = re.sub(r'\$HTTP_TIMEOUT\s*=\s*\d+\s*;', '$HTTP_TIMEOUT=30;', src, count=1)
        # Write back in the same encoding we read
        open(CONF, "w", encoding=detected_enc, newline="").write(src)
        print("      HTTP_TIMEOUT was %ds - updated to 30s." % val)
    else:
        insert = '$HTTP_TIMEOUT=30;\t//Timeout for AI requests.\n'
        pos = src.rfind('?>')
        if pos != -1:
            src = src[:pos] + insert + src[pos:]
        else:
            src += '\n' + insert
        open(CONF, "w", encoding=detected_enc, newline="").write(src)
        print("      HTTP_TIMEOUT was not set - added as 30s.")
except Exception as e:
    print("      Could not check HTTP_TIMEOUT: %s" % e)
