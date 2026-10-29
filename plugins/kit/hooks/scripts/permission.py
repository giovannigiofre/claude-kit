#!/usr/bin/env python3
"""PermissionRequest (Bash): the project's own gate commands run without a prompt.

kit.json `check` and `verify` are commands the user wrote and committed, and the kit's hooks
already run them unasked; a prompt before Claude runs one by hand is a click for nothing. The
same for the kit's own scripts that read, record or tidy (gate.py, lessons.py, compact_logs.py).
Only an exact `check` or `verify`, or one of those scripts by its real path, is allowed here;
anything else stays with the permission system (and the guard has already had its say).
Standard library only.
"""

import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
SCRIPTS = {"gate.py", "lessons.py", "compact_logs.py"}
PYTHON = {"python", "python3"}


def own_script(command):
    """True for `python3 <kit>/.../gate.py ...` where the path really is inside this plugin."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if len(argv) < 2 or Path(argv[0]).name not in PYTHON or any(ch in command for ch in ";&|`$<>"):
        return False
    script = Path(argv[1])
    try:
        resolved = script.resolve(strict=True)
    except OSError:
        return False
    return resolved.name in SCRIPTS and PLUGIN in resolved.parents


def allowed(command, config):
    command = command.strip()
    gates = {str(config.get(k) or "").strip() for k in ("check", "verify")} - {""}
    return command in gates or own_script(command)


def main():
    data = kitlib.read_input()
    if data.get("tool_name") != "Bash":
        return 0
    root = kitlib.project_root(data)
    config, _ = kitlib.load_config(root)
    if not config:
        return 0
    command = str((data.get("tool_input") or {}).get("command") or "")
    if allowed(command, config):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                                 "decision": {"behavior": "allow"}}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
