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

    def within(home, config, fn):
        saved = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_CONFIG_DIR")}
        os.environ.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(config))
        try:
            return fn()
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    # an account whose settings.json is not JSON gets one line: the file was left alone, and why
    bad = two / "bad-account"
    bad.mkdir()
    (bad / "settings.json").write_text("{bad")
    line = within(two, bad, machine_setup.unreadable)
    assert line and "not valid JSON" in line and "left alone" in line, line
    assert within(two, bad, machine_setup.auto_apply) is None and (bad / "settings.json").read_text() == "{bad"
    assert within(two, third, machine_setup.unreadable) is None, "a readable file: no line"
    assert within(declined, declined / "x", machine_setup.unreadable) is None, "declined: silent"

    # a symlinked settings.json (dotfiles): the link stays a link, its target gets the settings
    linked = Path(tempfile.mkdtemp())
    (linked / "dotfiles").mkdir()
    target = linked / "dotfiles" / "settings.json"
    target.write_text(json.dumps({"model": "opus"}))
    target.chmod(0o640)
    (linked / ".claude").mkdir()
    (linked / ".claude" / "settings.json").symlink_to(target)
    code, out = run(linked, "--apply")
    link = linked / ".claude" / "settings.json"
    assert code == 0 and link.is_symlink() and link.resolve() == target, out
    assert json.loads(target.read_text())["model"] == "opus" and "attribution" in json.loads(target.read_text())
    assert (target.stat().st_mode & 0o777) == 0o640, "the target keeps its mode bits"
    assert not list((linked / "dotfiles").glob(".settings.json.*")), "no temporary file left beside the target"

    # two kit writers interleaved: away off writes settings.json after merge read it and before merge
    # writes. merge reads again under the lock and keeps away off's change, as it keeps its own.
    import kitlib
    race = Path(tempfile.mkdtemp())
    (race / ".claude").mkdir()
    (race / ".claude" / "settings.json").write_text(json.dumps({"model": "opus"}))

    def interleaved():
        assert kitlib.away_on()[0] == 0 and kitlib.away_state()[0] == "kit"
        real, calls = machine_setup.missing, []

        def late(settings):
            if not calls:
                calls.append(kitlib.away_off())
            return real(settings)
        machine_setup.missing = late
        try:
            return machine_setup.merge(), calls
        finally:
            machine_setup.missing = real
    (code, lines), calls = within(race, race / ".claude", interleaved)
    final = json.loads((race / ".claude" / "settings.json").read_text())
    assert code == 0 and calls and calls[0][0] == 0, (lines, calls)
    assert "permissions" not in final, f"away off's change is not lost: {final}"
    assert final["model"] == "opus" and machine_setup.missing(final) == [], f"merge's change is kept too: {final}"

    # a busy settings lock, or a home folder where ~/.claude cannot be made: one line, exit 1, no traceback
    busy = Path(tempfile.mkdtemp())
    (busy / ".claude").mkdir()
    # the locks of settings.json (--apply) and kit.json (--decline), in the kit's temp state folder
    import kitlib
    holders = []
    for target in (busy / ".claude" / "settings.json", busy / ".claude" / "kit.json"):
        lock = kitlib.settings_lock_file(target)
        lock.parent.mkdir(parents=True, exist_ok=True)
        holders.append(subprocess.Popen([sys.executable, "-c", "import fcntl, sys, time\n"
                                         "f = open(sys.argv[1], 'w'); fcntl.flock(f, fcntl.LOCK_EX)\n"
                                         "print('held', flush=True); time.sleep(10)", str(lock)],
                                        stdout=subprocess.PIPE, text=True))
        holders[-1].stdout.readline()
    try:
        for flag in ("--apply", "--decline"):
            code, out = run(busy, flag)
            assert code == 1 and len(out.strip().splitlines()) == 1 and "Try again" in out, (flag, out)
    finally:
        for holder in holders:
            holder.kill()
            holder.wait()
    assert not list((busy / ".claude").glob("*.lock")), "no lock is left beside the settings"
    assert not (busy / ".claude" / "settings.json").exists() and not (busy / ".claude" / "kit.json").exists()
    ro = Path(tempfile.mkdtemp()) / "account"
    code, out = run(Path("/proc/self"), "--apply", config=ro)
    assert code == 1 and "Traceback" not in out and "kit.json was not changed" in out and "are applied" in out, out
    assert machine_setup.missing(json.loads((ro / "settings.json").read_text())) == [], \
        "the account's settings are written; their lock is in the temp folder, not the home"
    for flag in ("--apply", "--decline"):
        code, out = run(Path("/proc/self"), flag)
        assert code == 1 and len(out.strip().splitlines()) == 1 and "cannot be written" in out, (flag, out)
    print("machine_setup: all checks passed")


if __name__ == "__main__":
    main()
