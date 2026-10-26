#!/usr/bin/env python3
"""Per-repo auto mode environment, kept in sync with ~/.claude/settings.json.

Auto mode reads `autoMode` from user settings only, so a repo cannot describe its own environment
(organization, cloud, trusted domains, secret files, protected branches). Each repo keeps its
lines in `.claude/auto-mode.local.json`, never committed:

  {"environment": ["**Organization**: colpal", "**Cloud provider(s)**: GCP project x-dev"]}

On every SessionStart in a kit project this script:
  - reads that file only when git does not track it: a cloned repo must never make itself trusted;
  - records the lines in ~/.claude/kit-auto-mode.json (main checkout -> name, origin, lines) and
    drops repos whose file is gone;
  - rebuilds `autoMode.environment` in ~/.claude/settings.json: the user's own lines stay as they
    are, the kit's lines (ending in MARKER) are replaced, each one scoped to its repo by name,
    origin and path. A new list starts with "$defaults" so the built-in entries stay current.

It writes only when something changed (backup first, other keys kept), never rewrites a settings
file that is not valid JSON, and runs no `claude` command. Standard library only.

  python3 auto_mode_sync.py [DIR]     sync for the repo containing DIR (default: cwd)
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
from machine_setup import read_json, settings_path  # noqa: E402

REPO_FILE = ".claude/auto-mode.local.json"
MARKER = "[kit: .claude/auto-mode.local.json]"
LABELLED = re.compile(r"^\*\*(.+?)\*\*:\s*(.*)$", re.S)


def registry_path():
    return Path.home() / ".claude" / "kit-auto-mode.json"


def git(root, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def main_checkout(start):
    """The repo's main working tree, so a worktree shares its checkout's entry."""
    common = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common and Path(common).name == ".git":
        return Path(common).parent
    return kitlib.git_root(start)


def scoped(line, name, path, origin):
    """One repo line, rewritten so the classifier reads it as applying in that repo only."""
    line = " ".join(line.split())
    m = LABELLED.match(line)
    label, text = (m.group(1), m.group(2)) if m else ("Repo note", line)
    where = f"In the repository {name} (checkout {path} and its worktrees"
    where += f", origin {origin})" if origin else ")"
    return f"**{label} ({name} only)**: {where}, and nowhere else: {text} {MARKER}"


def repo_lines(top):
    """(lines, warning): lines to record, [] to forget this repo (tracked file), None to leave it as is."""
    path = top / REPO_FILE
    if not path.is_file():
        return None, None
    if git(top, "ls-files", "--error-unmatch", REPO_FILE) is not None:
        return [], f"kit: {REPO_FILE} is committed in this repo, so auto mode ignores it (a cloned repo cannot make itself trusted); untrack it to use it."
    data, ok = read_json(path)
    env = data.get("environment") if ok else None
    if not isinstance(env, list) or not all(isinstance(x, str) for x in env):
        return None, f"kit: {path} needs {{\"environment\": [\"**Label**: text\", ...]}}; auto mode lines not synced."
    return [x for x in env if x.strip()], None


def sync(start):
    """Bring the registry and settings up to date. Returns the lines worth showing (none when nothing changed)."""
    top = kitlib.git_root(start)
    main = main_checkout(start)
    out = []
    registry, ok = read_json(registry_path())
    if not ok:
        return [f"kit: {registry_path()} is not a valid JSON object; auto mode lines not synced."]
    repos = registry.get("repos") if isinstance(registry.get("repos"), dict) else {}
    before = json.dumps(repos, sort_keys=True)

    if top and main:
        lines, warning = repo_lines(top)
        if warning:
            out.append(warning)
        if lines:
            repos[str(main)] = {"name": main.name, "lines": lines,
                                "origin": git(top, "remote", "get-url", "origin") or ""}
        elif lines == []:
            repos.pop(str(main), None)
    for key in [k for k in repos if not (Path(k) / REPO_FILE).is_file()]:
        del repos[key]

    path = settings_path()
    settings, ok = read_json(path)
    if not ok:
        return out + [f"kit: {path} is not a valid JSON object; auto mode lines not synced."]
    auto = settings.get("autoMode", {})
    if not isinstance(auto, dict):
        return out + [f"kit: autoMode in {path} is not an object; auto mode lines not synced."]
    current = auto.get("environment")
    kit_lines = [scoped(line, entry.get("name", Path(key).name), key, entry.get("origin"))
                 for key, entry in sorted(repos.items()) for line in entry.get("lines", [])]
    if isinstance(current, list):
        env = [x for x in current if not (isinstance(x, str) and x.endswith(MARKER))] + kit_lines
    else:
        env = ["$defaults"] + kit_lines if kit_lines else None

    if json.dumps(repos, sort_keys=True) != before:
        registry["repos"] = repos
        registry_path().parent.mkdir(parents=True, exist_ok=True)
        registry_path().write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if env is None or env == current:
        return out
    if path.exists():
        shutil.copy2(path, path.with_name("settings.json.kit-backup"))
    auto["environment"] = env
    settings["autoMode"] = auto
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out.append(f"kit: auto mode environment in {path} synced from {len(repos)} repo(s)' {REPO_FILE} "
               f"({len(kit_lines)} line(s); backup settings.json.kit-backup).")
    return out


def main(argv):
    for line in sync(Path(argv[0]) if argv else Path.cwd()):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
