#!/usr/bin/env python3
"""Every self-check of the kit, in one command, before a pull request. No tokens, no network.

The repo has no CI (no Actions minutes), so this is the gate: run it on the branch you are about
to push, and put its last lines in the PR. It runs each standard-library test file and then the
mod's tests (`claude plugin test plugins/kit`: status line, watchdog, interim notices) when the
`claude` command is there; without it that step is reported as skipped, not as passed.

Run: python3 tests/run_all.py        (exit 0 = all good)
     python3 tests/run_all.py -v     (print each test's own output)

To make it this repo's gate for the kit itself, put it in your own .claude/kit.json:
  {"verify": "python3 tests/run_all.py"}
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = ("tests/test_*.py", "plugins/*/hooks/tests/test_*.py", "plugins/*/skills/*/tests/test_*.py")


def main(argv):
    verbose = "-v" in argv
    files = sorted(p for pattern in PATTERNS for p in ROOT.glob(pattern))
    failed = []
    for path in files:
        rel = path.relative_to(ROOT)
        out = subprocess.run([sys.executable, str(path)], cwd=str(ROOT), capture_output=True, text=True)
        ok = out.returncode == 0
        print(f"{'ok  ' if ok else 'FAIL'} {rel}")
        if verbose or not ok:
            print((out.stdout + out.stderr).rstrip())
        if not ok:
            failed.append(str(rel))
    mod = "skipped (no `claude` command here)"
    if shutil.which("claude"):
        out = subprocess.run(["claude", "plugin", "test", "plugins/kit"], cwd=str(ROOT), capture_output=True, text=True)
        tail = [line for line in (out.stdout + out.stderr).splitlines() if line.strip()][-3:]
        ok = out.returncode == 0
        mod = "ok" if ok else "FAIL"
        if verbose or not ok:
            print((out.stdout + out.stderr).rstrip())
        else:
            print("\n".join(tail))
        if not ok:
            failed.append("claude plugin test plugins/kit")
    print(f"{'ok  ' if mod == 'ok' else mod[:4] if mod == 'FAIL' else 'skip'} mod tests: {mod}")
    print(f"run_all: {len(files)} test files, {len(failed)} failed" + (": " + ", ".join(failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
