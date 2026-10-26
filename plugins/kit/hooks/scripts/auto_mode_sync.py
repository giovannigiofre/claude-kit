#!/usr/bin/env python3
"""Per-repo auto mode environment lines, kept in user settings.

Auto mode reads `autoMode` from user settings only, so a repo cannot describe its own environment
(organization, cloud, trusted domains, secret files, protected branches). The user approves each
repo's lines once and this script stores them under the Claude config dir (CLAUDE_CONFIG_DIR, else
~/.claude), one block per repo:

  kit-auto-mode/<slug>.json   {"repo": {"origin", "name", "paths"}, "environment": ["**Label**: text"]}

Nothing inside a repository is ever read for these lines: only the user's explicit command adds
them, so a cloned repo cannot make itself trusted. A repo is its normalized origin URL (ssh and
https forms are the same repo, any checkout or worktree matches), or its path when it has none.

Every run rebuilds `autoMode.environment` in settings.json: the user's own lines stay as they are,
the kit's lines (ending in MARKER) are replaced, each scoped to its repo by origin and paths. A new
list starts with "$defaults" so the built-in entries stay current; a non-list is left alone.
Writes happen under a lock, atomically, only when something changed, after a backup
(settings.json.kit-auto-mode-backup; the first one ever is also kept as .orig). Standard library only.

  python3 auto_mode_sync.py                     rebuild settings from the blocks (SessionStart)
  python3 auto_mode_sync.py --set FILE|- [DIR]  store the approved lines for the repo at DIR (default cwd)
  python3 auto_mode_sync.py --show [DIR]        print the stored lines for that repo
  python3 auto_mode_sync.py --remove [DIR]      forget that repo's lines
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_setup import read_json  # noqa: E402

MARKER = "[kit auto-mode]"
MAX_LINES = 20       # per repo
MAX_TEXT = 400       # characters of one line as the user approved it
MAX_LINE = 1000      # characters of one line in settings, scope included
MAX_PATHS = 3
BACKUP = "settings.json.kit-auto-mode-backup"


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def blocks_dir():
    return config_dir() / "kit-auto-mode"


@contextlib.contextmanager
def locked():
    config_dir().mkdir(parents=True, exist_ok=True)
    with open(config_dir() / "kit-auto-mode.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def write_atomic(path, text):
    """Replace the file's target (a symlinked settings.json stays a symlink) in one step."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def dumps(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def git(start, *args):
    try:
        out = subprocess.run(["git", "-C", str(start), *args], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def normalize_origin(url):
    """git@host:o/r.git, ssh://git@host/o/r, https://user:tok@host/o/r.git -> host/o/r (lowercase)."""
    url = (url or "").strip()
    m = re.match(r"^[\w.+-]+://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.+)$", url) or \
        re.match(r"^(?:[^@/]+@)?([^/:]+):(?!/)(.+)$", url)
    if not m:
        return url.rstrip("/").lower()
    path = re.sub(r"\.git$", "", m.group(2).strip("/"))
    return f"{m.group(1)}/{path}".lower()


def identify(start):
    """(key, origin, name, main checkout) for the repo at `start`, or None outside a git checkout."""
    common = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    top = git(start, "rev-parse", "--show-toplevel")
    if not common or not top:
        return None
    main = Path(common).parent if Path(common).name == ".git" else Path(top)
    origin = normalize_origin(git(top, "remote", "get-url", "origin"))
    name = origin.rsplit("/", 1)[-1] if origin else main.name
    return origin or str(main), origin, name, str(main)


def block_path(key):
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[-60:]
    return blocks_dir() / f"{slug}-{hashlib.sha1(key.encode()).hexdigest()[:8]}.json"


def clean(line):
    """(label, text) of one approved line: a single line, no bold markup."""
    line = " ".join(str(line).split())
    m = re.match(r"^\*\*(.+?)\*\*:\s*(.*)$", line)
    label, text = (m.group(1), m.group(2)) if m else ("Repo note", line)
    label = label.replace("*", "").strip()[:60] or "Repo note"
    return label, text.replace("**", "").strip()


def scoped(line, repo):
    """One repo line as the classifier reads it: scoped to that repo, tagged as the kit's."""
    label, text = clean(line)
    origin, paths = repo.get("origin") or "", [str(p) for p in repo.get("paths", [])][:MAX_PATHS]
    if origin:
        where = f"In the repository whose git origin is {origin}, in any checkout or worktree of it"
        where += f" (known checkouts: {', '.join(paths)})" if paths else ""
    else:
        where = f"In the repository checked out at {', '.join(paths) or '?'} and its worktrees"
    name = re.sub(r"[^\w.-]", "", str(repo.get("name") or "repo"))[:60]
    head = f"**{label} ({name} repo only)**: {where}, and nowhere else: "
    room = MAX_LINE - len(head) - len(MARKER) - 1
    text = text if len(text) <= room else text[:room - 1] + "…"
    return f"{head}{text} {MARKER}"


def load_blocks():
    """(blocks sorted by file name, warnings)."""
    blocks, warnings = [], []
    for path in sorted(blocks_dir().glob("*.json")):
        data, ok = read_json(path)
        env = data.get("environment") if ok else None
        repo = data.get("repo") if ok else None
        if not isinstance(env, list) or not isinstance(repo, dict):
            warnings.append(f"kit: {path} is not a valid auto mode block; skipped.")
            continue
        blocks.append({"repo": repo, "environment": [x for x in env if isinstance(x, str)][:MAX_LINES]})
    return blocks, warnings


def rebuild():
    """Bring settings.json in line with the blocks. Call under the lock. Returns lines to show."""
    blocks, out = load_blocks()
    kit_lines = [scoped(line, b["repo"]) for b in blocks for line in b["environment"]]
    path = config_dir() / "settings.json"
    settings, ok = read_json(path)
    if not ok:
        return out + ([f"kit: {path} is not a valid JSON object; auto mode lines not synced."] if kit_lines else [])
    auto = settings.get("autoMode", {})
    current = auto.get("environment") if isinstance(auto, dict) else None
    if not isinstance(auto, dict) or not (current is None or isinstance(current, list)):
        return out + ([f"kit: autoMode.environment in {path} is not a list; left as is, auto mode "
                       "lines not synced."] if kit_lines else [])
    if isinstance(current, list):
        env = [x for x in current if not (isinstance(x, str) and x.endswith(MARKER))] + kit_lines
    else:
        env = ["$defaults"] + kit_lines if kit_lines else None
    if env is None or env == current:
        return out
    if path.exists():
        shutil.copy2(path, path.with_name(BACKUP))
        if not path.with_name(BACKUP + ".orig").exists():  # settings as they were before the kit's first write
            shutil.copy2(path, path.with_name(BACKUP + ".orig"))
    auto["environment"] = env
    settings["autoMode"] = auto
    write_atomic(path, dumps(settings))
    out.append(f"kit: auto mode environment in {path} rebuilt: {len(kit_lines)} repo-scoped line(s) "
               f"from {len(blocks)} repo(s) (backup {BACKUP}).")
    return out


def sync():
    """The SessionStart entry: rebuild under the lock; reads no repository content."""
    if not any(blocks_dir().glob("*.json")):
        return []  # nothing approved on this machine: no lock, no write, nothing to say
    with locked():
        return rebuild()


def read_lines(source):
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    data = json.loads(text)
    env = data.get("environment") if isinstance(data, dict) else data
    if not isinstance(env, list) or not all(isinstance(x, str) for x in env):
        raise ValueError('expected {"environment": ["**Label**: text", ...]}')
    env = [" ".join(x.split()) for x in env if x.strip()]
    if len(env) > MAX_LINES or any(len(x) > MAX_TEXT for x in env):
        raise ValueError(f"at most {MAX_LINES} lines of at most {MAX_TEXT} characters each")
    return env


def show(lines):
    if lines:
        print("\n".join(lines))


def main(argv):
    cmd = argv[0] if argv and argv[0].startswith("-") else None
    if cmd not in (None, "--set", "--show", "--remove"):
        print(__doc__)
        return 2
    if cmd is None:
        show(sync())
        return 0
    rest = argv[1:]
    source = rest.pop(0) if cmd == "--set" and rest else None
    if cmd == "--set" and source is None:
        print("kit: --set needs a file, or - for stdin.")
        return 2
    repo = identify(rest[0] if rest else Path.cwd())
    if not repo:
        print("kit: not inside a git checkout (or git failed); nothing changed.")
        return 1
    key, origin, name, main_path = repo
    bpath = block_path(key)
    if cmd == "--show":
        data, ok = read_json(bpath)
        print(dumps(data) if ok and data else f"No auto mode lines stored for {key}.")
        return 0
    if cmd == "--set":
        try:
            env = read_lines(source)
        except (OSError, ValueError) as exc:
            print(f"kit: {exc}; nothing changed.")
            return 1
    with locked():
        if cmd == "--remove":
            with contextlib.suppress(FileNotFoundError):
                bpath.unlink()
        else:
            old, ok = read_json(bpath)
            old_paths = ((old or {}).get("repo") or {}).get("paths", []) if ok else []
            paths = [main_path] + [p for p in old_paths if isinstance(p, str) and p != main_path]
            write_atomic(bpath, dumps({"repo": {"origin": origin, "name": name, "paths": paths[:MAX_PATHS]},
                                       "environment": env}))
        out = rebuild()
    print(f"kit: {'removed' if cmd == '--remove' else 'stored'} auto mode lines for {key} ({bpath}).")
    show(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
