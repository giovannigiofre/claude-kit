#!/usr/bin/env python3
"""PermissionRequest (Bash): the project's own gate commands run without a prompt.

kit.json `check` and `verify` are commands the user wrote (personal or committed), and the kit's hooks
already run them unasked; a prompt before Claude runs one by hand is a click for nothing. The
same for the kit's own scripts that read, record or tidy (gate.py, lessons.py, compact_logs.py)
and the coordinator's board tools (items.py, proposals.py), which write under the kit's lead/
folder (.kit/lead/, or .claude/lead/ in a project not moved yet). Three items.py commands write
settings instead: `away on|off` the user's settings.json, `sandbox on|off` the checkout's
settings.local.json, `unattended <choices>` kit.local.json. The coordinator runs them at the
owner's word, so they run unasked from the main session; from a subagent they are never allowed
here (guard.py denies them first; this holds with the guard off too). migrate_state.py
moves that state folder itself and refuses while a thread is at work, so only `status` and a bare
`migrate` run unasked: `undo`, `--force` (moves past a thread at work) and `--root` (another
repo) are the owner's to approve. Only an exact `check` or
`verify`, or one of those scripts by its real path, is allowed here; anything else stays with
the permission system (and the guard has already had its say). A command that changes a Claude Code settings file is never allowed here, whatever it
runs: settings_guard.py has asked the owner about it. Standard library only.
"""

import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import settings_guard  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
SCRIPTS = {"gate.py", "lessons.py", "compact_logs.py", "items.py", "proposals.py",
           "migrate_state.py"}
PYTHON = {"python", "python3"}


def owner_command(args):
    """items.py arguments that change the owner's settings: away or sandbox with an action other
    than status, unattended with any choice."""
    sub, rest = (args[0], args[1:]) if args else ("", [])
    return (sub in ("away", "sandbox") and rest not in ([], ["status"])) or (sub == "unattended" and bool(rest))


def own_script(command, agent=False):
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
    if resolved.name not in SCRIPTS or PLUGIN not in resolved.parents:
        return False
    if agent and resolved.name == "items.py" and owner_command(argv[2:]):
        return False
    return resolved.name != "migrate_state.py" or argv[2:] in (["status"], ["migrate"])


def allowed(command, config, cwd=None, agent=False):
    command = command.strip()
    if settings_guard.command_targets(command, cwd):
        return False
    gates = {str(config.get(k) or "").strip() for k in ("check", "verify")} - {""}
    return command in gates or own_script(command, agent)


def main():
    data = kitlib.read_input()
    if data.get("tool_name") != "Bash":
        return 0
    root = kitlib.project_root(data)
    config, _ = kitlib.load_config(root)
    if config is None:
        return 0
    command = str((data.get("tool_input") or {}).get("command") or "")
    if allowed(command, config, data.get("cwd"), bool(data.get("agent_id"))):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                                 "decision": {"behavior": "allow"}}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
