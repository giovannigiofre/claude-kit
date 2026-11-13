#!/usr/bin/env python3
"""The kit's settings for this account on this machine, in the user's settings.json (user scope,
which no plugin or project file can set; under CLAUDE_CONFIG_DIR when that is set, else ~/.claude):

  attribution   {"commit": "", "pr": "", "sessionUrl": false}: Claude Code adds no co-author
                trailer, PR footer or session link, so the user is the only author
  autoMode      an allow rule that lets agents rewrite and force-push (with lease) the branches
                they created for their own tasks, which auto mode blocks by default

session_start.py calls `pending()` and, until the user answers, asks Claude to offer this once.
Claude explains, asks, then runs one of:

  python3 machine_setup.py --check     what is missing (exit 0 = nothing)
  python3 machine_setup.py --apply     merge the settings in (backup first, other keys kept) and
                                       remember "yes" in ~/.claude/kit.json
  python3 machine_setup.py --decline   remember "no" in ~/.claude/kit.json, never ask again

The answer is for the machine: ~/.claude/kit.json stays in the home folder whatever
CLAUDE_CONFIG_DIR says, while the settings are per account. So once the user said yes, a second
account on the same machine (another CLAUDE_CONFIG_DIR) gets them at its next session start
without being asked (`auto_apply`), and session_start.py says so in one line.

A settings file that is not valid JSON is never rewritten. Standard library only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kitlib import config_dir, read_json, update_settings  # noqa: E402

ATTRIBUTION = {"commit": "", "pr": "", "sessionUrl": False}
BACKUP = "settings.json.kit-backup"
OWN_BRANCHES = ("On a branch an agent created for its own task (not the default branch, not one "
                "someone else pushed to), rewriting its commits (amend, rebase, setting the user's "
                "authorship) and pushing it with --force-with-lease")


def settings_path():
    # the account's own settings: with CLAUDE_CONFIG_DIR (a second account on the same machine) Claude
    # Code reads settings.json there, and ~/.claude/settings.json belongs to the other account
    return config_dir() / "settings.json"


def kit_path():
    return Path.home() / ".claude" / "kit.json"


def missing(settings):
    out = []
    if settings.get("attribution") not in (ATTRIBUTION, False):
        out.append("attribution: no AI co-author, PR footer or session link (you are the only author)")
    allow = (settings.get("autoMode") or {}).get("allow") if isinstance(settings.get("autoMode"), dict) else None
    if not (isinstance(allow, list) and OWN_BRANCHES in allow):
        out.append("autoMode.allow: agents may rewrite and force-push (with lease) the branches they created")
    return out


def answer():
    """The user's answer on this machine: "applied", "declined", or None."""
    kit, _ = read_json(kit_path())
    value = kit.get("machineSetup") if isinstance(kit, dict) else None
    return value if value in ("applied", "declined") else None


def remember(value):
    """Write machineSetup into ~/.claude/kit.json beside its other keys; False when it does not parse."""
    def note(kit):
        kit["machineSetup"] = value

    return update_settings(kit_path(), note) == "written"


def pending():
    """What to offer on this machine, or [] when it is set up, declined, or the file is unreadable."""
    if answer() == "declined":
        return []
    settings, ok = read_json(settings_path())
    return missing(settings) if ok else []


def unreadable():
    """One line when this account's settings.json is not valid JSON (and the user has not said no on
    this machine): the kit left it alone, so the user knows why nothing was offered or applied."""
    if answer() == "declined":
        return None
    _, ok = read_json(settings_path())
    if ok:
        return None
    return (f"kit: {settings_path()} is not valid JSON, so the kit's machine settings were not offered "
            "or applied and the file was left alone. Claude Code cannot read it either: fix it, and the "
            "next session start offers them.")


def merge():
    """(code, lines): merge the settings into this account's settings.json, backup first. The file
    is read again under the kit's settings lock, so a change another writer made is kept."""
    path = settings_path()
    existed = path.exists()
    todo = []

    def add(settings):
        todo[:] = missing(settings)
        if not todo:
            return False
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

    result = update_settings(path, add, backup=BACKUP)
    if result == "broken":
        return 1, [f"{path} is not a valid JSON object; nothing was changed. Fix it, then run --apply again."]
    if result == "busy":
        return 1, [f"{path} kept changing while the kit wrote it; nothing was changed. Run --apply again."]
    if result == "same":
        return 0, ["Nothing to do: this machine already has the kit's settings."]
    lines = [f"Backup: {path.with_name(BACKUP)}"] if existed else []
    return 0, lines + [f"Updated {path}:"] + [f"- {line}" for line in todo]


def apply():
    code, lines = merge()
    print("\n".join(lines))
    if code == 0:
        if remember("applied"):
            print(f"Noted in {kit_path()}: another account on this machine gets these settings without being asked.")
        print("New sessions pick it up; in a running one, settings reload on their own.")
    return code


def auto_apply():
    """At session start: when the user said yes on this machine and this account's settings still
    lack the kit's, merge them in. One line for the user, or None when there was nothing to do.
    An account that set an attribution of its own is asked instead: the yes was given for another
    account, and a value the user wrote himself is not replaced without asking."""
    if answer() != "applied" or not pending():
        return None
    settings, ok = read_json(settings_path())
    if not ok or settings.get("attribution", ATTRIBUTION) not in (ATTRIBUTION, False):
        return None
    existed = settings_path().exists()
    try:
        code, _ = merge()
    except OSError:  # the settings lock is busy (kitlib.SettingsBusy): the next session start retries
        return None
    if code != 0:
        return None
    backup = "; a backup is beside it" if existed else ""
    return (f"kit: applied the kit's machine settings to {settings_path()} (no AI co-author, agents may "
            f"force-push only their own branches), as you chose on this machine before{backup}.")


def decline():
    path = kit_path()
    if not remember("declined"):
        print(f"{path} is not a valid JSON object; nothing was changed.")
        return 1
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
