#!/usr/bin/env python3
"""The kit's settings for this machine, in ~/.claude/settings.json (user scope, which no plugin or
project file can set):

  attribution   {"commit": "", "pr": "", "sessionUrl": false}: Claude Code adds no co-author
                trailer, PR footer or session link, so the user is the only author
  autoMode      an allow rule that lets agents rewrite and force-push (with lease) the branches
                they created for their own tasks, which auto mode blocks by default

session_start.py calls `pending()` and, until the user answers, asks Claude to offer this once.
Claude explains, asks, then runs one of:

  python3 machine_setup.py --check     what is missing (exit 0 = nothing)
  python3 machine_setup.py --apply     merge the settings in (backup first, other keys kept)
  python3 machine_setup.py --decline   remember "no" in ~/.claude/kit.json, never ask again

A settings file that is not valid JSON is never rewritten. Standard library only.
"""

import json
import shutil
import sys
from pathlib import Path

ATTRIBUTION = {"commit": "", "pr": "", "sessionUrl": False}
OWN_BRANCHES = ("On a branch an agent created for its own task (not the default branch, not one "
                "someone else pushed to), rewriting its commits (amend, rebase, setting the user's "
                "authorship) and pushing it with --force-with-lease")


def settings_path():
    return Path.home() / ".claude" / "settings.json"


def kit_path():
    return Path.home() / ".claude" / "kit.json"


def read_json(path):
    """(value, ok): missing is ({}, True); unreadable or not a JSON object is (None, False)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, True
    except Exception:
        return None, False
    try:
        value = json.loads(text)
    except ValueError:
        return None, False
    return (value, True) if isinstance(value, dict) else (None, False)


def missing(settings):
    out = []
    if settings.get("attribution") not in (ATTRIBUTION, False):
        out.append("attribution: no AI co-author, PR footer or session link (you are the only author)")
    allow = (settings.get("autoMode") or {}).get("allow") if isinstance(settings.get("autoMode"), dict) else None
    if not (isinstance(allow, list) and OWN_BRANCHES in allow):
        out.append("autoMode.allow: agents may rewrite and force-push (with lease) the branches they created")
    return out


def pending():
    """What to offer on this machine, or [] when it is set up, declined, or the file is unreadable."""
    kit, _ = read_json(kit_path())
    if isinstance(kit, dict) and kit.get("machineSetup") == "declined":
        return []
    settings, ok = read_json(settings_path())
    return missing(settings) if ok else []


def apply():
    path = settings_path()
    settings, ok = read_json(path)
    if not ok:
        print(f"{path} is not a valid JSON object; nothing was changed. Fix it, then run --apply again.")
        return 1
    todo = missing(settings)
    if not todo:
        print("Nothing to do: this machine already has the kit's settings.")
        return 0
    if path.exists():
        backup = path.with_name("settings.json.kit-backup")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    if settings.get("attribution") not in (ATTRIBUTION, False):
        settings["attribution"] = dict(ATTRIBUTION)
    auto = settings.get("autoMode")
    auto = auto if isinstance(auto, dict) else {}
    allow = auto.get("allow")
    if not isinstance(allow, list):
        allow = ["$defaults"]  # keep Claude Code's built-in allow rules, add ours after them
    if OWN_BRANCHES not in allow:
        allow.append(OWN_BRANCHES)
    auto["allow"] = allow
    settings["autoMode"] = auto
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {path}:")
    for line in todo:
        print(f"- {line}")
    print("New sessions pick it up; in a running one, settings reload on their own.")
    return 0


def decline():
    path = kit_path()
    kit, ok = read_json(path)
    if not ok:
        print(f"{path} is not a valid JSON object; nothing was changed.")
        return 1
    kit["machineSetup"] = "declined"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Noted in {path}: the kit will not offer these settings again on this machine.")
    return 0


def main(argv):
    if argv[:1] == ["--apply"]:
        return apply()
    if argv[:1] == ["--decline"]:
        return decline()
    todo = pending()
    for line in todo:
        print(f"- {line}")
    return 1 if todo else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
