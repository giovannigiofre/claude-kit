#!/usr/bin/env python3
"""keychain_header.py ITEM: read the analyst token from macOS Keychain and write one curl header line,
`Authorization: Bearer <token>`, to a file it creates itself: `header` (mode 600, O_EXCL) inside a fresh
`$TMPDIR/seo-growth-auth.XXXXXX` directory (mode 700). Prints that file's path, never the token.
It takes no output path, so it cannot be pointed at /dev/*, stdout or an existing file. The caller deletes
the directory (rm -rf on the path's parent).

The token lives only in this process and in OUTFILE, never in the calling shell. A locked Keychain that
would prompt or hang fails after SEO_GROWTH_KEYCHAIN_TIMEOUT seconds (default 20) with one line.
Exit 0 ok, 2 usage, 3 token missing, unreadable or unusable.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HELP = """token missing: Keychain item '{item}' not found (or Keychain is locked).
Owner, once, in a terminal (never in a chat):
  1. make an analyst token and its SHA-256 with the site's own tool (its README or RUNBOOK says how)
  2. store the SHA-256 as the site's ANALYST_TOKEN_SHA256 secret, the way that repo deploys secrets
  3. security add-generic-password -U -s {item} -a "$USER" -w     (paste the token at the prompt)"""


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1]:
        print("usage: keychain_header.py ITEM (it picks the output path itself and prints it)", file=sys.stderr)
        return 2
    item = sys.argv[1]
    timeout = float(os.environ.get("SEO_GROWTH_KEYCHAIN_TIMEOUT") or 20)
    try:
        p = subprocess.run(["security", "find-generic-password", "-s", item, "-w"],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        print("token missing: the 'security' command is not available (macOS Keychain is required).", file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired:
        print(f"token unavailable: reading Keychain item '{item}' timed out after {timeout:g}s (Keychain locked?); run stopped.",
              file=sys.stderr)
        return 3
    token = p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else ""
    if not token:
        print(HELP.format(item=item), file=sys.stderr)
        return 3
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
        print(f"token unusable: Keychain item '{item}' holds characters a bearer token cannot have.", file=sys.stderr)
        return 3
    d = tempfile.mkdtemp(prefix="seo-growth-auth.")  # mode 700, in $TMPDIR, a name nobody else holds
    try:
        out = os.path.join(d, "header")
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"Authorization: Bearer {token}\n")
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
