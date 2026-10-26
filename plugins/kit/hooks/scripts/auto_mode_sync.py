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
An origin or path that is not a plain `host/path` or a plain directory path is refused, because
it is written into the line the classifier reads.

Every run rebuilds `autoMode.environment` in settings.json: the user's own lines stay as they are,
the kit's lines (its exact scoped form, ending in MARKER) are replaced, each scoped to its repo by origin and paths. A new
list starts with "$defaults" so the built-in entries stay current; a non-list is left alone.
Writes happen under a lock, atomically, only when something changed, after a backup
(settings.json.kit-auto-mode-backup; the first one ever is also kept as .orig). A read-only
settings.json is never replaced. Standard library only.

  python3 auto_mode_sync.py                         rebuild settings from the blocks (SessionStart)
  python3 auto_mode_sync.py --preview FILE|- [DIR]  print the lines --set would add, change nothing
  python3 auto_mode_sync.py --set FILE|- [DIR]      store the approved lines for the repo at DIR (default cwd)
  python3 auto_mode_sync.py --show [DIR]            print the stored lines for that repo
  python3 auto_mode_sync.py --remove [DIR]          forget that repo's lines
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_setup import read_json  # noqa: E402

MARKER = "[kit auto-mode]"
MAX_LINES = 20       # per repo
MAX_TEXT = 400       # characters of one line as the user approved it
MAX_LINE = 1000      # characters of one line in settings, scope included
MAX_PATHS = 3
MAX_ORIGIN = 200     # characters of a normalized origin
MAX_PATH = 300       # characters of one checkout path
RETRIES = 5          # rebuilds when another writer changes settings.json meanwhile
BACKUP = "settings.json.kit-auto-mode-backup"
# what may reach the classifier as a repo's identity: one token, no prose, no markup
ORIGIN_OK = re.compile(r"[a-z0-9.-]+(?::[0-9]+)?(?:/[a-z0-9._~-]+)+")
PATH_OK = re.compile(r"/[A-Za-z0-9._~+@/ -]+")
# characters that make URL parsers disagree on the host (git connects to evil.example for
# https://evil.example#@github.com/o/r), refused before any parsing
URL_BAD = re.compile(r"[#?\\%\s\x00-\x1f\x7f]")
HOST_OK = re.compile(r"[A-Za-z0-9.-]+(?::[0-9]+)?")
# a kit line, as scoped() writes it; only these are replaced, a user line merely ending in MARKER stays
KIT_LINE = re.compile(r"\*\*[^*\n]+ \([\w.-]* repo only\)\*\*: In the repository (?:whose git origin is "
                      r"`[^`\n]+`, in any checkout or worktree of it|checked out at `)[^\n]*" + re.escape(" " + MARKER))


class Refused(Exception):
    pass


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def blocks_dir():
    return config_dir() / "kit-auto-mode"


def settings_file():
    return config_dir() / "settings.json"


@contextlib.contextmanager
def locked():
    import fcntl  # here, so a platform without it cannot break importing this module
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


def clean_origin(url):
    """git@host:o/r.git, ssh://git@host/o/r, https://user:tok@host/o/r.git -> host/o/r (lowercase),
    or None when the URL is ambiguous or the result is not one plain `host/path` token."""
    url = url or ""
    if not url.isascii() or URL_BAD.search(url):  # ASCII before lower(): no Kelvin sign -> k
        return None
    if "://" in url:
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        userinfo, _, host = parts.netloc.rpartition("@")
        if parts.scheme.lower() == "file" or parts.query or parts.fragment or "@" in userinfo \
                or not HOST_OK.fullmatch(host):
            return None
        path = parts.path
    else:  # scp form [user@]host:path
        m = re.fullmatch(r"(?:[A-Za-z0-9._-]+@)?([A-Za-z0-9.-]+):(?!/)(.+)", url)
        if not m:
            return None
        host, path = m.groups()
    origin = f"{host}/{re.sub(r'[.]git$', '', path.strip('/'), flags=re.I)}".lower()
    return origin if plain_origin(origin) else None


def plain_origin(origin):
    return len(origin) <= MAX_ORIGIN and bool(ORIGIN_OK.fullmatch(origin)) \
        and not any(seg in (".", "..") for seg in origin.split("/"))


def clean_path(path):
    path = str(path)
    if len(path) > MAX_PATH or not PATH_OK.fullmatch(path) or "/../" in path + "/" or "/./" in path + "/":
        return None
    return path


def identify(start):
    """(key, origin, name, main checkout) for the repo at `start`. Raises Refused."""
    common = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    top = git(start, "rev-parse", "--show-toplevel")
    if not common or not top:
        raise Refused("not inside a git checkout (or git failed)")
    main = str(Path(common).parent if Path(common).name == ".git" else Path(top))
    if not clean_path(main):
        raise Refused(f"the checkout path {main!r} has characters the kit will not put in an auto "
                      "mode line (only letters, digits, space and ._~+@/- are allowed)")
    raw = git(top, "remote", "get-url", "origin")
    origin = clean_origin(raw) if raw else ""
    if origin is None:
        raise Refused(f"the origin URL {raw!r} is not a plain host/path, so it cannot scope auto "
                      "mode lines; fix `git remote get-url origin` first")
    name = origin.rsplit("/", 1)[-1] if origin else Path(main).name
    return origin or main, origin, name, main


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
    """One repo line as the classifier reads it: scoped to that repo, tagged as the kit's.
    Raises Refused when the stored origin or paths are not clean."""
    origin = repo.get("origin") or ""
    if origin and not plain_origin(origin):
        raise Refused(f"origin {origin!r} is not a plain host/path")
    paths = [str(p) for p in repo.get("paths", [])][:MAX_PATHS]
    if any(clean_path(p) is None for p in paths):
        raise Refused("a checkout path is too long or has characters the kit does not allow")
    label, text = clean(line)
    while paths and len(", ".join(paths)) > MAX_LINE // 2:  # leave room for the text
        paths.pop()
    shown = ", ".join(f"`{p}`" for p in paths)
    if origin:
        where = f"In the repository whose git origin is `{origin}`, in any checkout or worktree of it"
        where += f" (known checkouts: {shown})" if paths else ""
    elif paths:
        where = f"In the repository checked out at {shown} and its worktrees"
    else:
        raise Refused("a block needs an origin or a checkout path")
    name = re.sub(r"[^\w.-]", "", str(repo.get("name") or "repo"))[:60]
    head = f"**{label} ({name} repo only)**: {where}, and nowhere else: "
    room = MAX_LINE - len(head) - len(MARKER) - 1
    if room < 40:
        raise Refused("the scope leaves no room for the line")
    text = text if len(text) <= room else text[:room - 1] + "…"
    return f"{head}{text} {MARKER}"


def is_kit(line):
    return isinstance(line, str) and bool(KIT_LINE.fullmatch(line))


def load_blocks():
    """(kit lines, number of blocks, warnings) from the stored blocks."""
    lines, count, warnings = [], 0, []
    for path in sorted(blocks_dir().glob("*.json")):
        data, ok = read_json(path)
        env = data.get("environment") if ok else None
        repo = data.get("repo") if ok else None
        try:
            if not isinstance(env, list) or not isinstance(repo, dict):
                raise Refused("not a valid auto mode block")
            lines += [scoped(x, repo) for x in env[:MAX_LINES] if isinstance(x, str)]
            count += 1
        except Refused as exc:
            warnings.append(f"kit: {path}: {exc}; skipped.")
    return lines, count, warnings


def signature(path):
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size, st.st_ino
    except OSError:
        return None


def rebuild():
    """Bring settings.json in line with the blocks. Call under the lock. Returns lines to show."""
    kit_lines, count, out = load_blocks()
    path = settings_file()
    for _ in range(RETRIES):
        before = signature(path)
        settings, ok = read_json(path)
        if not ok:
            return out + ([f"kit: {path} is not a valid JSON object; auto mode lines not synced."] if kit_lines else [])
        auto = settings.get("autoMode", {})
        if not isinstance(auto, dict):
            return out + [f"kit: autoMode in {path} is not an object; left as is, auto mode lines not synced."]
        current = auto.get("environment")
        if current is not None and not isinstance(current, list):
            return out + [f"kit: autoMode.environment in {path} is not a list; left as is, auto mode "
                          "lines not synced."]
        if isinstance(current, list):
            env = [x for x in current if not is_kit(x)] + kit_lines
        else:
            env = ["$defaults"] + kit_lines if kit_lines else None
        if env is None or env == current:
            return out
        if path.exists() and not os.access(path, os.W_OK):
            return out + [f"kit: {path} is read-only; auto mode lines not synced (left as is)."]
        auto["environment"] = env
        settings["autoMode"] = auto
        if signature(path) != before:
            continue  # someone else wrote settings.json meanwhile: merge again from their version
        if path.exists():
            shutil.copy2(path, path.with_name(BACKUP))
            if not path.with_name(BACKUP + ".orig").exists():  # settings before the kit's first write
                shutil.copy2(path, path.with_name(BACKUP + ".orig"))
        write_atomic(path, dumps(settings))
        out.append(f"kit: auto mode environment in {path} rebuilt: {len(kit_lines)} repo-scoped line(s) "
                   f"from {count} repo(s) (backup {BACKUP}).")
        return out
    return out + [f"kit: {path} kept changing; auto mode lines not synced, next session start retries."]


def sync():
    """The SessionStart entry: reads no repository content. With no blocks it only takes the lock
    when settings.json still holds kit lines to remove."""
    if not any(blocks_dir().glob("*.json")):
        try:
            if MARKER not in settings_file().read_text(encoding="utf-8"):
                return []
        except OSError:
            return []
    with locked():
        return rebuild()


def read_lines(source):
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise Refused(f"not JSON ({exc})")
    env = data.get("environment") if isinstance(data, dict) else data
    if not isinstance(env, list) or not all(isinstance(x, str) for x in env):
        raise Refused('expected {"environment": ["**Label**: text", ...]}')
    env = [" ".join(x.split()) for x in env if x.strip()]
    if len(env) > MAX_LINES or any(len(x) > MAX_TEXT for x in env):
        raise Refused(f"at most {MAX_LINES} lines of at most {MAX_TEXT} characters each")
    return env


def show(lines):
    if lines:
        print("\n".join(lines))


def main(argv):
    cmd = argv[0] if argv and argv[0].startswith("-") else None
    if cmd not in (None, "--set", "--preview", "--show", "--remove"):
        print(__doc__)
        return 2
    try:
        if cmd is None:
            show(sync())
            return 0
        rest = argv[1:]
        source = rest.pop(0) if cmd in ("--set", "--preview") and rest else None
        if cmd in ("--set", "--preview") and source is None:
            raise Refused(f"{cmd} needs a file, or - for stdin")
        key, origin, name, main_path = identify(rest[0] if rest else Path.cwd())
        bpath = block_path(key)
        if cmd == "--show":
            data, ok = read_json(bpath)
            print(dumps(data) if ok and data else f"No auto mode lines stored for {key}.")
            return 0
        env = read_lines(source) if source else None
        old, ok = read_json(bpath)
        old_paths = ((old or {}).get("repo") or {}).get("paths", []) if ok else []
        paths = [main_path] + [p for p in old_paths if isinstance(p, str) and p != main_path]
        block = {"repo": {"origin": origin, "name": name, "paths": paths[:MAX_PATHS]}, "environment": env}
        if cmd == "--preview":
            show([scoped(x, block["repo"]) for x in env])
            return 0
    except (Refused, OSError) as exc:
        print(f"kit: {exc}; nothing changed.")
        return 1
    stored = False
    try:
        with locked():
            if cmd == "--remove":
                with contextlib.suppress(FileNotFoundError):
                    bpath.unlink()
            else:
                write_atomic(bpath, dumps(block))
            stored = True
            out = rebuild()
    except OSError as exc:
        if not stored:
            print(f"kit: could not {'remove' if cmd == '--remove' else 'store'} the auto mode lines for "
                  f"{key}: {exc}; nothing changed.")
        else:
            print(f"kit: {'removed' if cmd == '--remove' else 'stored'} the auto mode lines for {key}, but "
                  f"settings.json could not be updated ({exc}); the next session start applies them.")
        return 1
    print(f"kit: {'removed' if cmd == '--remove' else 'stored'} auto mode lines for {key} ({bpath}).")
    show(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
