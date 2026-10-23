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


def run(home, *args):
    out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                         env={**os.environ, "HOME": str(home)}, timeout=30)
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
    print("machine_setup: all checks passed")


if __name__ == "__main__":
    main()
