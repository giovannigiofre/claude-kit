#!/usr/bin/env python3
"""Self-check for stop_check.py: the check runs only when the tree changed, gets the changed
files, blocks the stop on failure and gives up after maxStopRetries.

Run: python3 plugins/kit/hooks/tests/test_stop_check.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "stop_check.py"


def sh(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def stop(repo, session, tmpdir):
    # a temp config dir: the gate failures this test provokes must not reach the real lesson ledger
    env = {**os.environ, "TMPDIR": tmpdir, "CLAUDE_CONFIG_DIR": str(Path(tmpdir) / "config")}
    out = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps({"cwd": str(repo), "session_id": session}),
                         capture_output=True, text=True, timeout=60, env=env)
    return out.returncode, out.stderr


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        sh(repo, "config", "user.email", "t@example.invalid")
        sh(repo, "config", "user.name", "t")
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text(json.dumps({
            "check": "echo \"$KIT_CHANGED_COUNT:$KIT_CHANGED_FILES\" >> runs.log; test ! -f fail", "maxStopRetries": 2}))
        (repo / ".gitignore").write_text("runs.log\nfail\n")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "init")
        runs = repo / "runs.log"

        code, _ = stop(repo, "s1", tmp)
        if code != 0 or not runs.exists():
            failed += 1
            print(f"FAIL first stop runs the check: {code} {runs.exists()}")
        if runs.read_text() != "0:\n":
            failed += 1
            print(f"FAIL no changed files on a clean main: {runs.read_text()!r}")
        code, _ = stop(repo, "s1", tmp)
        if runs.read_text().count("\n") != 1:
            failed += 1
            print("FAIL an unchanged tree does not run the check again")

        sh(repo, "checkout", "-q", "-b", "feat/x")
        (repo / "x.py").write_text("x\n")
        stop(repo, "s1", tmp)
        if runs.read_text().splitlines()[-1] != "1:x.py":
            failed += 1
            print(f"FAIL the changed file reaches the check: {runs.read_text()!r}")

        (repo / "fail").write_text("")
        (repo / "x.py").write_text("y\n")
        codes = [stop(repo, "s1", tmp)[0] for _ in range(3)]
        if codes != [2, 2, 0]:
            failed += 1
            print(f"FAIL two blocked stops then give up (maxStopRetries 2): {codes}")
        _, err = stop(repo, "s2", tmp)
        if "kit check failed (attempt 1/2)" not in err:
            failed += 1
            print(f"FAIL a new session starts a fresh count: {err[:120]}")

        # an empty kit.json is opted in, but has no check to run: silent, and no run
        (repo / ".claude" / "kit.json").write_text("{}")
        before = runs.read_text()
        code, err = stop(repo, "s3", tmp)
        if code != 0 or err or runs.read_text() != before:
            failed += 1
            print(f"FAIL `{{}}` has no check: nothing runs, nothing said: {code} {err[:80]}")

    print("stop_check: all checks passed" if not failed else f"stop_check: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
