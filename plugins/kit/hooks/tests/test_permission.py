#!/usr/bin/env python3
"""Self-check for permission.py: only the project's exact gate commands and the kit's own
scripts are allowed without a prompt.

Run: python3 plugins/kit/hooks/tests/test_permission.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def ask(repo, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo), "session_id": "s",
               "hook_event_name": "PermissionRequest"}
    out = subprocess.run([sys.executable, str(SCRIPTS / "permission.py")], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    if not out.stdout.strip():
        return "prompt"
    return json.loads(out.stdout)["hookSpecificOutput"]["decision"]["behavior"]


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        (repo / ".claude").mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "make lint", "verify": "make test"}))
        gate = SCRIPTS / "gate.py"
        elsewhere = Path(tmp) / "gate.py"
        elsewhere.write_text("print('not the kit')\n")
        (Path(tmp) / "items.py").write_text("print('not the kit')\n")
        cases = [
            ("make lint", "allow"), ("make test", "allow"), ("  make test\n", "allow"),
            ("make lint && rm -rf x", "prompt"), ("make", "prompt"), ("make test; echo", "prompt"),
            (f"python3 {gate} verify", "allow"), (f'python3 "{gate}" status', "allow"),
            (f"python3 {gate} verify > out.txt", "prompt"), (f"python3 {elsewhere} verify", "prompt"),
            (f'python3 "{SCRIPTS / "items.py"}" list --status queued', "allow"),
            (f"python3 {SCRIPTS / 'items.py'} new \"Login page\" --brief - --from lead", "allow"),
            (f"python3 {SCRIPTS / 'proposals.py'} take readme-install", "allow"),
            # the move out of .claude: status and a bare migrate only, the rest is the owner's call
            (f"python3 {SCRIPTS / 'migrate_state.py'} migrate", "allow"),
            (f"python3 {SCRIPTS / 'migrate_state.py'} status", "allow"),
            (f"python3 {SCRIPTS / 'migrate_state.py'} migrate --force", "prompt"),
            (f"python3 {SCRIPTS / 'migrate_state.py'} undo", "prompt"),
            (f"python3 {SCRIPTS / 'migrate_state.py'} migrate --root /other", "prompt"),
            (f"python3 {SCRIPTS / 'migrate_state.py'} --root /other migrate", "prompt"),
            (f"python3 {SCRIPTS / 'migrate_state.py'} migrate --dry-run", "prompt"),
            (f"python3 {SCRIPTS / 'migrate_state.py'}", "prompt"),
            (f"python3 {Path(tmp) / 'migrate_state.py'} migrate", "prompt"),
            (f"python3 {Path(tmp) / 'items.py'} list", "prompt"),  # a script of that name elsewhere is not the kit's
            (f"python3 {SCRIPTS / 'machine_setup.py'} --apply", "prompt"), ("rm -rf /", "prompt"),
        ]
        for command, want in cases:
            got = ask(repo, command)
            if got != want:
                failed += 1
                print(f"FAIL {want} expected, got {got}: {command!r}")
        (repo / ".claude" / "kit.json").unlink()
        if ask(repo, "make lint") != "prompt":
            failed += 1
            print("FAIL without kit.json nothing is allowed")
    print("permission: all checks passed" if not failed else f"permission: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
