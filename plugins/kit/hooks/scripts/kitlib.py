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
    """Return (config, error). config is None when the project has no kit.json; a kit.json that
    is present means the project opted in, even an empty `{}` (callers test `config is None`)."""
    path = Path(root) / ".claude" / "kit.json"
    if not path.is_file():
        return None, None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # a broken config must be visible, not silently ignored
        return None, f"kit: cannot read {path}: {exc}"
    if not isinstance(config, dict):
        return None, f"kit: {path} must hold a JSON object"
    return config, None


def main_checkout(cwd):
    """The repository's main checkout (a linked worktree resolves to it), else the checkout of
    cwd, else None outside git. The items, the evidence and the lessons are keyed by it."""
    root = git_root(cwd)
    if not root:
        return None
    common = git_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=10)
    common = Path(common) if common else None
    if common and common.name == ".git" and (common.parent / ".git").is_dir():
        return common.parent
    return root


# The owner's unattended git preferences for one repository, in its main checkout's gitignored
# `.claude/kit.local.json` (`{"lead": {"unattended": {"push": "ask", "rebase": "ask", "merge": "ask"}}}`):
# local to this machine and this repo, never global, never committed. `ask` (the default, and
# whatever is missing, misspelt or unreadable) means nobody answers a permission prompt during an
# unattended run, so a thread hands that step back; `allow` means it proceeds as when attended.
UNATTENDED_STEPS = ("push", "rebase", "merge")
LOCAL_CONFIG = ".claude/kit.local.json"
# What `allow` needs so the step runs without a prompt: the owner adds these to the repo's
# .claude/settings.local.json `permissions.allow` himself; the kit never edits permission settings.
UNATTENDED_RULES = {"push": ["Bash(git push:*)"], "rebase": ["Bash(git rebase:*)"],
                    "merge": ["Bash(gh pr merge:*)", "Bash(git merge:*)"]}


def unattended_prefs(cwd):
    """(prefs, is_set, path): every step `ask` or `allow`; is_set when the repo's file names any step."""
    root = main_checkout(cwd) or Path(cwd)
    path = Path(root) / LOCAL_CONFIG
    value, _ = read_json(path)
    lead = (value or {}).get("lead")
    own = lead.get("unattended") if isinstance(lead, dict) else None
    own = own if isinstance(own, dict) else {}
    prefs = {k: ("allow" if str(own.get(k, "")).strip().lower() == "allow" else "ask") for k in UNATTENDED_STEPS}
    return prefs, any(k in own for k in UNATTENDED_STEPS), path


def save_unattended(cwd, changes):
    """Write `changes` ({step: ask|allow}) into the repo's kit.local.json beside its other keys and
    keep the file out of git; returns the prefs now in force. A file that does not parse is never
    rewritten (ValueError)."""
    prefs, _, path = unattended_prefs(cwd)
    value, ok = read_json(path)
    if not ok:
        raise ValueError(f"{path} is not a JSON object; fix or remove it first")
    lead = value.get("lead") if isinstance(value.get("lead"), dict) else {}
    own = lead.get("unattended") if isinstance(lead.get("unattended"), dict) else {}
    own = {**{k: prefs[k] for k in UNATTENDED_STEPS}, **own, **changes}
    value["lead"] = {**lead, "unattended": {k: own[k] for k in UNATTENDED_STEPS}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    exclude(path.parent.parent, LOCAL_CONFIG)
    return unattended_prefs(cwd)[0]


def exclude(root, rel):
    """Keep `rel` (a file under the checkout `root`) out of git through .git/info/exclude, unless
    the project ignores it already."""
    root = Path(root)
    try:
        if subprocess.run(["git", "-C", str(root), "check-ignore", "-q", rel], capture_output=True,
                          timeout=10).returncode == 0:
            return
    except Exception:
        return
    info = git_out(root, "rev-parse", "--git-path", "info/exclude")
    if not info:
        return
    info = Path(info) if Path(info).is_absolute() else root / info
    try:
        info.parent.mkdir(parents=True, exist_ok=True)
        text = info.read_text(encoding="utf-8") if info.exists() else ""
        line = "/" + rel.lstrip("/")
        if line not in text.splitlines():
            info.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n", encoding="utf-8")
    except OSError:
        pass


GATE_TIMEOUTS = {"check": 540, "verify": 1800}  # seconds; kit.json checkTimeout / verifyTimeout override


def gate_timeout(config, name):
    """The timeout of gate `name`: kit.json `checkTimeout` / `verifyTimeout`, else GATE_TIMEOUTS."""
    try:
        return int((config or {}).get(name + "Timeout") or GATE_TIMEOUTS[name])
    except (TypeError, ValueError):
        return GATE_TIMEOUTS[name]


def state_key(data):
    """The state a hook keeps for one agent: `<session>.<agent id or main>`, so threads running
    in parallel in one session (each hook input carries its agent_id) never share a file."""
    return f"{data.get('session_id') or 'nosession'}.{data.get('agent_id') or 'main'}"


def config_dir():
    """Claude Code's config dir: CLAUDE_CONFIG_DIR, else ~/.claude."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"
    r"|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bglpat-[A-Za-z0-9_-]{16,}|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\bA(?:KIA|SIA)[A-Z0-9]{16}\b|\bAIza[A-Za-z0-9_-]{30,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|://[^/\s:@]+:[^/\s@]+@"
    # NAME=value where the value mixes letters and digits, so `first_pass: always` is not one
    r"|(?<![A-Za-z0-9])(?:\w*(?:password|passwd|secret|token|api[_-]?key)|(?:\w*_)?pass)\s*[:=]\s*"
    r"(?=\S*[A-Za-z])(?=\S*\d)\S{6,}"
    r"|\bbearer\s*[:=]\s*\S{6,}|\bbearer\s+(?=\S*\d)\S{8,}",
    re.I,
)
OPAQUE = re.compile(r"[A-Za-z0-9+/_=-]{32,}")
# a commit SHA (40 hex) or a sha256 (64 hex), bare or in a URL or `sha=`
HEX_DIGEST = re.compile(r"(?<![A-Za-z0-9])(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![A-Za-z0-9])")
EXTENSION = re.compile(r"^\.(?:py|pyi|js|jsx|ts|tsx|mjs|cjs|json|ya?ml|toml|md|txt|sql|html?|css|scss|sh|go|rs"
                       r"|rb|java|kt|swift|c|h|cpp|hpp|cs|php|ex|exs|vue|svelte|lock|cfg|ini|env|csv|xml|prisma)"
                       r"(?![A-Za-z0-9])", re.I)
WORDS = re.compile(r"[a-z]{2,}_[a-z]{2,}|[a-z]{3,}-[a-z]{3,}")  # snake_case or a slug-of-words


def pathlike(run, after):
    """A run of OPAQUE that is a path or a name, not a token: snake_case words or a slug inside
    it, a known file extension right after it, or a `/` in a run with the few capitals and no
    `+`/`=` of a path (a random base64 key has about 40% capitals)."""
    if WORDS.search(run) or EXTENSION.match(after):
        return True
    return "/" in run and "+" not in run and "=" not in run and sum(c.isupper() for c in run) <= len(run) // 5


def looks_secret(text):
    """True when text holds something shaped like a key, token or password. A long opaque run of
    letters and digits counts, except a hex digest (a commit SHA, a sha256), a slug of words and a
    path (see `pathlike`): `src/api/v2/handlers/user_profile.py` is not a key."""
    if SECRET.search(text):
        return True
    text = HEX_DIGEST.sub(" ", text)
    return any(re.search(r"\d", m.group()) and re.search(r"[A-Za-z]", m.group())
               and not pathlike(m.group(), text[m.end():m.end() + 8]) for m in OPAQUE.finditer(text))


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


def git_out(cwd, *args, timeout=30, strip=True):
    """stdout of a git command, stripped unless strip=False (a porcelain status starts with a
    space that matters); "" on any failure."""
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            return ""
        return out.stdout.strip() if strip else out.stdout
    except Exception:
        return ""


def default_branch(root):
    """The branch work merges into: the remote's HEAD, else main or master when one exists."""
    head = git_out(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head.startswith("origin/"):
        return head
    for name in ("origin/main", "origin/master", "main", "master"):
        if git_out(root, "rev-parse", "--verify", "--quiet", name + "^{commit}"):
            return name
    return None


def changed_files(root, limit=400):
    """Files this work touched, relative to the checkout root: committed on this branch since it
    left the default branch, plus modified and untracked (not ignored) files in the tree. Deleted
    files are left out, so the list can be handed to a linter or a test runner as is. On the
    default branch itself, or without one, only the uncommitted files. Sorted; at most `limit`."""
    files = set()
    base = default_branch(root)
    head = git_out(root, "rev-parse", "--verify", "--quiet", "HEAD")
    merge_base = git_out(root, "merge-base", "HEAD", base) if base and head else ""
    if merge_base and merge_base != head:
        for line in git_out(root, "diff", "--name-only", "--diff-filter=ACMR", merge_base, "HEAD").splitlines():
            files.add(line)
    for line in git_out(root, "diff", "--name-only", "--diff-filter=ACMR", "HEAD" if head else "--cached").splitlines():
        files.add(line)
    for line in git_out(root, "ls-files", "--others", "--exclude-standard").splitlines():
        files.add(line)
    present = [f for f in sorted(files) if f and (Path(root) / f).is_file()]
    return present[:limit]


def changed_env(root):
    """Environment for a gate command: KIT_CHANGED_FILES (shell-quoted, space-separated, relative
    paths) and KIT_CHANGED_COUNT, so `check` can be diff-aware (`ruff check $KIT_CHANGED_FILES`)."""
    import shlex
    files = changed_files(root)
    return {"KIT_CHANGED_FILES": " ".join(shlex.quote(f) for f in files), "KIT_CHANGED_COUNT": str(len(files))}


def dirty_snapshot(root, limit=5000):
    """{relative path: mtime_ns} of every modified or untracked (not ignored) file in the
    checkout, so a later hook can tell which files a shell command changed. Deleted files are
    left out. At most `limit` entries; {} outside git."""
    out = git_out(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", strip=False)
    files = {}
    entries = out.split("\0")
    skip = False
    for entry in entries:
        if skip:  # the entry after a rename or copy is the old name, as its own NUL-ended entry
            skip = False
            continue
        if len(entry) < 4 or entry[:2] in ("D ", " D", "DD"):
            continue
        skip = "R" in entry[:2] or "C" in entry[:2]
        rel = entry[3:]  # with -z a rename is `R  new\0old\0`: this entry is the new name
        try:
            files[rel] = os.stat(Path(root) / rel).st_mtime_ns
        except OSError:
            continue
        if len(files) >= limit:
            break
    return files


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
