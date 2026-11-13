#!/usr/bin/env python3
"""Self-check for machine_setup.py.

Run: python3 plugins/kit/hooks/tests/test_machine_setup.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "machine_setup.py"
sys.path.insert(0, str(SCRIPT.parent))
import machine_setup  # noqa: E402


def run(home, *args, config=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    env["HOME"] = str(home)
    if config:
        env["CLAUDE_CONFIG_DIR"] = str(config)
    out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=30)
    return out.returncode, out.stdout


def main():
    home = Path(tempfile.mkdtemp())
    settings = home / ".claude" / "settings.json"

    code, out = run(home, "--check")
    assert code == 1 and "attribution" in out and "autoMode" in out, out

    settings.parent.mkdir()
    own = {"permissions": {"allow": ["Bash(npm test)"]}, "autoMode": {"allow": ["Trust our staging bucket"]},
           "attribution": {"commit": "Generated with AI", "pr": "x"}}
    settings.write_text(json.dumps(own))
    code, out = run(home, "--apply")
    assert code == 0, out
    after = json.loads(settings.read_text())
    assert after["permissions"] == own["permissions"], "other keys are kept"
    assert after["attribution"] == {"commit": "", "pr": "", "sessionUrl": False}, after
    assert after["autoMode"]["allow"] == ["Trust our staging bucket", machine_setup.OWN_BRANCHES], \
        "a custom allow list is extended, not given $defaults it did not have"
    assert (home / ".claude" / "settings.json.kit-backup").is_file()
    assert json.loads((home / ".claude" / "kit.json").read_text()) == {"machineSetup": "applied"}, \
        "the yes is remembered for the machine"
    assert run(home, "--check")[0] == 0
    code, out = run(home, "--apply")
    assert code == 0 and "Nothing to do" in out and json.loads(settings.read_text()) == after, "idempotent"

    fresh = Path(tempfile.mkdtemp())
    run(fresh, "--apply")
    allow = json.loads((fresh / ".claude" / "settings.json").read_text())["autoMode"]["allow"]
    assert allow == ["$defaults", machine_setup.OWN_BRANCHES], "a new list keeps the built-in rules"

    broken = Path(tempfile.mkdtemp())
    (broken / ".claude").mkdir()
    (broken / ".claude" / "settings.json").write_text("{ not json")
    code, out = run(broken, "--apply")
    assert code == 1 and (broken / ".claude" / "settings.json").read_text() == "{ not json", "never rewritten"

    declined = Path(tempfile.mkdtemp())
    (declined / ".claude").mkdir()
    (declined / ".claude" / "kit.json").write_text(json.dumps({"mode": "loop"}))
    assert run(declined, "--decline")[0] == 0
    kit = json.loads((declined / ".claude" / "kit.json").read_text())
    assert kit == {"mode": "loop", "machineSetup": "declined"}, kit
    assert run(declined, "--check")[0] == 0, "declined: nothing offered"
    # a second account on the same machine (CLAUDE_CONFIG_DIR): its own settings.json gets the kit's
    # settings, and the first account's ~/.claude/settings.json is left as it is
    two = Path(tempfile.mkdtemp())
    work = two / "work-account"
    (two / ".claude").mkdir()
    (two / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
    assert run(two, "--check", config=work)[0] == 1, "the second account has nothing yet"
    code, out = run(two, "--apply", config=work)
    applied = json.loads((work / "settings.json").read_text())
    assert code == 0 and applied["attribution"]["commit"] == "" and applied["autoMode"]["allow"][0] == "$defaults", out
    assert json.loads((two / ".claude" / "settings.json").read_text()) == {"permissions": {"allow": ["Bash(ls)"]}}, \
        "the other account's settings are untouched"
    assert run(two, "--check", config=work)[0] == 0 and run(two, "--check")[0] == 1, "each account is checked on its own"

    # after that yes, a third account on this machine is set up at its session start without the question
    def auto(home, config):
        saved = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_CONFIG_DIR")}
        os.environ.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(config))
        try:
            return machine_setup.auto_apply()
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    third = two / "third-account"
    line = auto(two, third)
    assert line and "applied the kit's machine settings" in line and "backup" not in line, line
    assert machine_setup.missing(json.loads((third / "settings.json").read_text())) == [], "set up in full"
    assert auto(two, third) is None, "once: a set-up account is silent"
    custom = two / "custom-account"
    custom.mkdir()
    (custom / "settings.json").write_text(json.dumps({"attribution": {"commit": "Signed by me"}}))
    assert auto(two, custom) is None and "Signed by me" in (custom / "settings.json").read_text(), \
        "an attribution the user wrote in that account is not replaced without asking"
    assert auto(declined, declined / "other") is None and not (declined / "other").exists(), "declined: nothing"
    nobody = Path(tempfile.mkdtemp())
    assert auto(nobody, nobody / "acct") is None, "never answered: asked, not applied"
    print("machine_setup: all checks passed")


if __name__ == "__main__":
    main()
