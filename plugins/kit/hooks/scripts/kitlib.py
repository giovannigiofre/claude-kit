"""Shared helpers for the kit hooks. Standard library only, Python 3.9+.

Every hook is a no-op unless the project has `.claude/kit.json` (see the README for the schema),
so installing the plugin at user scope never changes behaviour in a project that has not opted in.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


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


def read_input():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def git_root(start):
    """Top level of the git checkout containing `start` (a worktree has its own), else None."""
    start = Path(start)
    if start.is_file() or not start.exists():
        start = start.parent
    while not start.exists() and start != start.parent:
        start = start.parent
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def project_root(data, path_hint=None):
    """The checkout the hook is about: the file's checkout if given, else the session cwd."""
    for cand in (path_hint, data.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if cand:
            root = git_root(cand)
            if root:
                return root
    cand = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(cand)


def load_config(root):
    """Return (config, error). config is None when the project has no kit.json."""
    path = Path(root) / ".claude" / "kit.json"
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # a broken config must be visible, not silently ignored
        return None, f"kit: cannot read {path}: {exc}"


def config_dir():
    """Claude Code's config dir: CLAUDE_CONFIG_DIR, else ~/.claude."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def glob_to_regex(glob):
    """`**` spans directories, `*` and `?` stay inside one path segment."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile("^" + out + "$")


def matches(glob, relpath):
    return bool(glob_to_regex(glob).match(relpath))


def relpath(root, file_path):
    try:
        return Path(file_path).resolve().relative_to(Path(root).resolve()).as_posix()
    except Exception:
        return None


def run_shell(cmd, cwd, env_extra=None, timeout=600):
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(cwd), env=env,
            capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {cmd}"


def tail(text, lines=60):
    parts = text.strip().splitlines()
    return "\n".join(parts[-lines:])


def state_path(session_id, name):
    d = Path(tempfile.gettempdir()) / "claude-kit"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "nosession")
    return d / f"{safe}.{name}.json"


def load_state(session_id, name):
    p = state_path(session_id, name)
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_state(session_id, name, value):
    state_path(session_id, name).write_text(json.dumps(value))
