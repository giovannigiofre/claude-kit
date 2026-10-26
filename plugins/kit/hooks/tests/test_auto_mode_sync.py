#!/usr/bin/env python3
"""Self-check for auto_mode_sync.py, with a temporary HOME, CLAUDE_CONFIG_DIR and git repos.

Run: python3 plugins/kit/hooks/tests/test_auto_mode_sync.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = HOOKS / "auto_mode_sync.py"
sys.path.insert(0, str(HOOKS))
import auto_mode_sync  # noqa: E402

BASE = Path(tempfile.mkdtemp())
HOME, CONFIG = BASE / "home", BASE / "config"
ENV = {**os.environ, "HOME": str(HOME), "CLAUDE_CONFIG_DIR": str(CONFIG), "KIT_HEADLESS": "1"}
SETTINGS = CONFIG / "settings.json"


def sync(*args, stdin=None):
    out = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True,
                         text=True, env=ENV, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout


def repo(name, origin):
    path = BASE / name
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    return path


def env_of():
    return json.loads(SETTINGS.read_text())["autoMode"]["environment"]


def main():
    CONFIG.mkdir(parents=True)
    own = {"permissions": {"allow": ["Bash(npm test)"]},
           "autoMode": {"environment": ["$defaults", "**Organization**: my own line"]}}
    SETTINGS.write_text(json.dumps(own))
    shop = repo("shop", "git@github.com:Acme/shop.git")
    lines = json.dumps({"environment": ["**Organization**: acme", "**Cloud provider(s)**: GCP shop-dev"]})

    # --set: scoped lines are added, the user's settings and lines are kept
    assert "rebuilt" in sync("--set", "-", str(shop), stdin=lines)
    assert json.loads(SETTINGS.read_text())["permissions"] == own["permissions"]
    env = env_of()
    assert env[:2] == own["autoMode"]["environment"] and len(env) == 4, env
    assert env[2] == ("**Organization (shop repo only)**: In the repository whose git origin is "
                      "`github.com/acme/shop`, in any checkout or worktree of it (known checkouts: "
                      f"`{shop.resolve()}`), and nowhere else: acme {auto_mode_sync.MARKER}"), env[2]

    # nothing changed: the SessionStart rebuild writes nothing and says nothing
    mtime = SETTINGS.stat().st_mtime_ns
    assert sync() == "" and SETTINGS.stat().st_mtime_ns == mtime

    # a file inside the repo is never read
    (shop / ".claude").mkdir()
    (shop / ".claude" / "auto-mode.local.json").write_text(json.dumps({"environment": ["**X**: evil.example"]}))
    (shop / ".claude" / "kit.json").write_text(json.dumps({"check": "true"}))
    subprocess.run([sys.executable, str(HOOKS / "session_start.py")], input=json.dumps({"cwd": str(shop)}),
                   capture_output=True, text=True, env=ENV, timeout=60)
    assert "evil" not in SETTINGS.read_text()

    # an origin whose host git reads differently (evil.example) is refused, nothing is written
    before = SETTINGS.read_text()
    subprocess.run(["git", "-C", str(shop), "config", "remote.origin.url",
                    "https://evil.example#@github.com/acme/shop"], check=True)
    out = subprocess.run([sys.executable, str(SCRIPT), "--set", "-", str(shop)], input=lines,
                         capture_output=True, text=True, env=ENV, timeout=60)
    assert out.returncode == 1 and "not a plain host/path" in out.stdout, out.stdout
    assert SETTINGS.read_text() == before
    subprocess.run(["git", "-C", str(shop), "config", "remote.origin.url", "git@github.com:acme/shop.git"], check=True)

    # --remove drops the repo's lines; blocks deleted by hand are cleaned up by the next rebuild
    sync("--remove", str(shop))
    assert env_of() == own["autoMode"]["environment"]
    sync("--set", "-", str(shop), stdin=lines)
    for block in (CONFIG / "kit-auto-mode").glob("*.json"):
        block.unlink()
    sync()
    assert env_of() == own["autoMode"]["environment"]

    # a non-list environment is left as it is
    SETTINGS.write_text(json.dumps({"autoMode": {"environment": "mine"}}))
    assert "not a list" in sync("--set", "-", str(shop), stdin=lines)
    assert env_of() == "mine"
    sync("--remove", str(shop))

    # parallel --set calls in many repos: every one lands
    SETTINGS.write_text("{}")
    repos = [repo(f"p{i}", f"git@github.com:acme/p{i}.git") for i in range(8)]
    procs = [subprocess.Popen([sys.executable, str(SCRIPT), "--set", "-", str(r)], stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, env=ENV, text=True) for r in repos]
    for p in procs:
        p.communicate(lines)
    assert len(env_of()) == 1 + 2 * len(repos), env_of()
    print("auto_mode_sync: all checks passed")


if __name__ == "__main__":
    main()
