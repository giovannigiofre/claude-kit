"""Shared helpers for the kit hooks. Standard library only, Python 3.9+.

Every hook is a no-op unless the project has opted in: `.claude/kit.json` (see the README for the
schema), or the kit's working state in its main checkout when kit.json went missing (load_config),
so installing the plugin at user scope never changes behaviour in a project that has not opted in.
A linked worktree with no kit.json of its own (it is personal and kept out of git by default)
uses its main checkout's: config_file.
"""

import difflib
import fnmatch
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


def json_trouble(path):
    """Why read_json said no to `path`, for a message: `<path> could not be read (<reason>)` when
    the file or a folder above it cannot be opened, else `<path> does not parse`."""
    try:
        Path(path).read_bytes()
    except FileNotFoundError:
        return f"{path} does not parse"
    except OSError as exc:
        return f"{path} could not be read ({exc.strerror or exc})"
    return f"{path} does not parse"


def read_input():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


# Inside a git hook, git exports these to the hook's processes; a kit script started from one would
# hand them on, and every git call would then answer for the repository that ran the hook, not for
# the folder it was asked about (`git -C <dir>` does not override GIT_DIR).
GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX")


def git_env():
    """The environment for a git subprocess: this one, without the variables that point git at a
    particular repository, so `git -C <dir>` answers for <dir>."""
    return {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARS}


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
            capture_output=True, text=True, timeout=10, env=git_env(),
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


CONFIG = ".claude/kit.json"


def config_file(root):
    """The kit.json that applies in checkout `root`: its own, else its main checkout's. /kit:init
    keeps kit.json out of git by default (personal), so a linked worktree has none of its own."""
    return _config_and_main(root)[0]


def _config_and_main(root):
    """(config_file(root), the main checkout when it was looked up, else None)."""
    own = Path(root) / CONFIG
    if own.exists():
        return own, None
    main = main_checkout(root)
    if main and (Path(main) / CONFIG).exists():
        return Path(main) / CONFIG, main
    return own, main


def has_kit_state(base):
    """True when the checkout `base` holds the coordinator's working state: a `lead/` folder in
    `.kit/` (or the legacy `.claude/`) with a board.md or an `items/` folder in it."""
    for folder in (STATE_DIR, LEGACY_STATE_DIR):
        lead = Path(base) / folder / "lead"
        try:
            if (Path(base) / folder).is_symlink() or not lead.is_dir():
                continue
            if (lead / "items").is_dir() or any(p.name.lower() == "board.md" and p.is_file() for p in lead.iterdir()):
                return True
        except OSError:
            continue
    return False


def config_missing(root):
    """True when no kit.json applies in `root` although its main checkout holds kit state: the
    project uses the kit and its kit.json went missing (load_config then returns `{}`)."""
    path, main = _config_and_main(root)
    return not path.exists() and has_kit_state(main or Path(root))


def load_config(root):
    """Return (config, error). config is None when the project has not opted in; a kit.json that
    is present means it did, even an empty `{}` (callers test `config is None`). A worktree
    without one uses its main checkout's (config_file).

    The other opt-in is the kit's own working state in the main checkout (has_kit_state): then a
    missing kit.json gives `{}`, the defaults, and config_missing(root) is True. In the owner's
    project (2026-11) a commit removed kit.json from git and disk, and every hook went silent for
    days while the coordinator kept its board and items: no guard, no REPORT.md, no cost lines.
    A project with neither stays untouched, as before."""
    path, main = _config_and_main(root)
    if not path.is_file():
        if path.exists():  # a folder named kit.json: not opted in, as before
            return None, None
        return ({} if has_kit_state(main or Path(root)) else None), None
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
# local to this machine and this repo, never global, never committed. `ask` means nobody answers a
# permission prompt during an unattended run, so a thread hands that step back; `allow` means it
# proceeds as when attended, once the permission rules let it run without a prompt
# (unattended_effective). A step the file does not set, or sets to anything else, takes
# UNATTENDED_DEFAULTS: until 2026-11 every unset step was `ask` and the coordinator asked the owner
# before each first run, a question he answered the same way each time (push and rebase on the
# thread's own branch, merge his), so now that answer is the default and nobody is asked.
UNATTENDED_STEPS = ("push", "rebase", "merge")
UNATTENDED_DEFAULTS = {"push": "allow", "rebase": "allow", "merge": "ask"}
LOCAL_CONFIG = ".claude/kit.local.json"
# What `allow` needs so the step runs without a prompt: the owner adds these to the repo's
# .claude/settings.local.json `permissions.allow`, by hand or by approving the coordinator's Edit
# of the PROPOSAL (unattended_proposal); the kit's code never writes them (settings_guard.py).
UNATTENDED_RULES = {"push": ["Bash(git push:*)"], "rebase": ["Bash(git rebase:*)"],
                    "merge": ["Bash(gh pr merge:*)", "Bash(git merge:*)"]}


def unattended_prefs(cwd):
    """(prefs, is_set, path): every step `ask` or `allow`, an unset or misspelt one taking its
    default; is_set when the repo's file names any step."""
    root = main_checkout(cwd) or Path(cwd)
    path = Path(root) / LOCAL_CONFIG
    value, _ = read_json(path)
    lead = (value or {}).get("lead")
    own = lead.get("unattended") if isinstance(lead, dict) else None
    own = own if isinstance(own, dict) else {}
    prefs = {}
    for k in UNATTENDED_STEPS:
        value = str(own.get(k, "")).strip().lower()
        prefs[k] = value if value in ("ask", "allow") else UNATTENDED_DEFAULTS[k]
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
    own = {**prefs, **changes}
    value["lead"] = {**lead, "unattended": {k: own[k] for k in UNATTENDED_STEPS}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    exclude(path.parent.parent, LOCAL_CONFIG)
    return unattended_prefs(cwd)[0]


# Where this project records finished work besides the code (an issue's status label and closing
# comment, a progress file, a diary, a published page): the coordinator finds them in the repo's
# own guidance once, confirms them with the owner and saves them in the same kit.local.json
# (`{"lead": {"records": ["...", ...]}}`); `items.py done` prints them as the item's checklist.
def lead_local(cwd, key):
    """kit.local.json `lead.<key>` of the repo's main checkout, or None."""
    value, _ = read_json(Path(main_checkout(cwd) or cwd) / LOCAL_CONFIG)
    lead = (value or {}).get("lead")
    return lead.get(key) if isinstance(lead, dict) else None


def save_lead_local(cwd, key, value):
    """Set kit.local.json `lead.<key>` beside the other keys (None removes it); a file that does
    not parse is never rewritten (ValueError)."""
    path = Path(main_checkout(cwd) or cwd) / LOCAL_CONFIG
    data, ok = read_json(path)
    if not ok:
        raise ValueError(f"{path} is not a JSON object; fix or remove it first")
    lead = dict(data.get("lead")) if isinstance(data.get("lead"), dict) else {}
    if value is None:
        if key not in lead:
            return
        lead.pop(key)
    else:
        lead[key] = value
    data["lead"] = lead
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    exclude(path.parent.parent, LOCAL_CONFIG)


def records(cwd):
    """(places, path): the saved record places, [] when not set or unreadable."""
    path = Path(main_checkout(cwd) or cwd) / LOCAL_CONFIG
    value, _ = read_json(path)
    lead = (value or {}).get("lead")
    places = lead.get("records") if isinstance(lead, dict) else None
    return [" ".join(str(p).split()) for p in places if str(p).strip()] if isinstance(places, list) else [], path


def save_records(cwd, places):
    """Replace the saved record places; a file that does not parse is never rewritten (ValueError)."""
    _, path = records(cwd)
    value, ok = read_json(path)
    if not ok:
        raise ValueError(f"{path} is not a JSON object; fix or remove it first")
    lead = value.get("lead") if isinstance(value.get("lead"), dict) else {}
    value["lead"] = {**lead, "records": [" ".join(p.split()) for p in places if p.strip()]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    exclude(path.parent.parent, LOCAL_CONFIG)
    return records(cwd)[0]


# Commands a thread runs for each step, to test the permission rules against. Claude Code checks
# deny, then ask, then allow, and the first that matches wins in every scope: an ask rule anywhere
# (a committed settings.json, the user's) beats an allow rule in settings.local.json.
# The forms the kit itself prescribes count too: threads force-push with --force-with-lease and
# push with -u (implementer.md), the lead merges with --squash --delete-branch (lead SKILL.md).
UNATTENDED_PROBES = {"push": ["git push", "git push -u origin feature-branch", "git push --force-with-lease",
                              "git push --force-with-lease origin feature-branch",
                              "git push -u --force-with-lease origin feature-branch"],
                     "rebase": ["git rebase origin/main"],
                     "merge": ["gh pr merge 12 --squash", "gh pr merge 12 --squash --delete-branch",
                               "gh pr merge --squash --delete-branch", "git merge origin/main"]}


def bash_rule_matches(rule, command):
    """True when permission rule `rule` (`Bash`, `Bash(*)`, `Bash(git push:*)`, `Bash(git push *)`,
    `Bash(git push*)`, an exact `Bash(git status)`, or a tool-name glob such as `*`) covers `command`."""
    m = re.fullmatch(r"\s*([^\s()]+)\s*(?:\((.*)\))?\s*", str(rule), re.S)
    if not m:
        return False
    tool = m.group(1)
    if tool != "Bash" and not ("*" in tool and fnmatch.fnmatchcase("Bash", tool)):
        return False
    spec = (m.group(2) or "").strip()
    if spec in ("", "*"):
        return True
    if spec.endswith(":*"):
        prefix = spec[:-2]
        return command == prefix or command.startswith(prefix + " ")
    pattern = ".*".join(re.escape(part) for part in spec.split("*"))
    if spec.endswith(" *"):  # `git push *` also covers a bare `git push`
        pattern = f"(?:{pattern}|{re.escape(spec[:-2])})"
    return re.fullmatch(pattern, command, re.S) is not None


def managed_settings():
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode/managed-settings.json")
    if sys.platform.startswith("win"):
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ClaudeCode" / "managed-settings.json"
    return Path("/etc/claude-code/managed-settings.json")


def permission_files(cwd):
    """Every settings file whose permission rules apply in this repo: managed, the user's, and the
    main checkout's committed settings.json and local settings.local.json."""
    root = Path(main_checkout(cwd) or cwd)
    return [managed_settings(), config_dir() / "settings.json",
            root / ".claude" / "settings.json", root / ".claude" / "settings.local.json"]


def _guard_rules(cwd):
    """The kit guard's own project rules (kit.json guard.denyCommands / askCommands, a regex over the
    command) as [(behavior, pattern, where, matches)]: a PreToolUse ask or deny there wins over
    any allow rule too. A command the guard's allowCommands lets through is not matched."""
    root = Path(main_checkout(cwd) or cwd)
    try:
        import guard  # imported here: guard imports this module
        active, opts = guard.settings(root)
    except Exception:
        return []
    if not active:
        return []
    project, _ = load_config(root)
    source = config_file(root) if isinstance(project, dict) and isinstance(project.get("guard"), dict) \
        else Path.home() / ".claude" / "kit.json"
    out = []
    for behavior, key in (("deny", "denyCommands"), ("ask", "askCommands")):
        for rule in opts.get(key) or []:
            pattern = rule.get("pattern") if isinstance(rule, dict) else rule
            if not pattern:
                continue

            def hit(command, pattern=str(pattern)):
                try:
                    return not guard.allowed(command, opts) and re.search(pattern, command) is not None
                except re.error:
                    return False
            out.append((behavior, str(pattern), f"{source} guard.{key}", hit))
    return out


def _unattended_steps(cwd):
    """(files, unreadable, steps): for each step the owner set to allow, the deny and ask rules that
    match its commands as [(behavior, rule, file)], and whether allow rules cover all of them."""
    prefs, _, _ = unattended_prefs(cwd)
    files = permission_files(cwd)
    rules, unreadable = [], []
    for f in files:
        value, ok = read_json(f)
        if not ok:
            unreadable.append(f)
            continue
        perms = value.get("permissions") if isinstance(value.get("permissions"), dict) else {}
        for behavior in ("deny", "ask", "allow"):
            listed = perms.get(behavior)
            for r in listed if isinstance(listed, list) else []:
                rules.append((behavior, str(r), f))
    allows = [r for (b, r, _) in rules if b == "allow"]
    guard_rules = _guard_rules(cwd)
    steps = {}
    for step in UNATTENDED_STEPS:
        if prefs[step] != "allow":
            continue
        probes = UNATTENDED_PROBES[step]
        found = [(b, r, f, [p for p in probes if bash_rule_matches(r, p)]) for (b, r, f) in rules if b in ("deny", "ask")]
        found += [(b, pattern, where, [p for p in probes if hit(p)]) for (b, pattern, where, hit) in guard_rules]
        found = [x for x in found if x[3]]
        denied = {p for (b, _, _, forms) in found if b == "deny" for p in forms}
        # a deny refuses at once, without a prompt, so nothing waits on it: it keeps the step at ask
        # only when it refuses every form; otherwise those forms are named and the thread hands them back
        refused = [(r, f, forms) for (b, r, f, forms) in found if b == "deny"] if len(denied) < len(probes) else []
        blocked = [(b, r, f) for (b, r, f, _) in found if b == "ask" or not refused]
        covered = all(any(bash_rule_matches(r, p) for r in allows) for p in probes if p not in denied)
        steps[step] = (blocked, covered, refused)
    return files, unreadable, steps


def asking_rules(cwd):
    """{step: [(rule, where)]}: the ask rules, in any settings scope or the kit guard's askCommands,
    that match a push, rebase or merge as the kit runs them, so such a command may stop on a prompt.
    Whether it does in a given mode is Claude Code's to decide; the owner's saved preference is not read."""
    rules = []
    for f in permission_files(cwd):
        value, ok = read_json(f)
        perms = value.get("permissions") if ok and isinstance(value.get("permissions"), dict) else {}
        listed = perms.get("ask")
        rules += [(str(r), f) for r in (listed if isinstance(listed, list) else [])]
    guard_rules = [(pattern, where, hit) for (b, pattern, where, hit) in _guard_rules(cwd) if b == "ask"]
    out = {}
    for step in UNATTENDED_STEPS:
        probes = UNATTENDED_PROBES[step]
        found = [(r, f) for (r, f) in rules if any(bash_rule_matches(r, p) for p in probes)]
        found += [(pattern, where) for (pattern, where, hit) in guard_rules if any(hit(p) for p in probes)]
        if found:
            out[step] = found
    return out


def unattended_effective(cwd):
    """(effective, notes): a step is `allow` only when the owner chose allow, no deny or ask rule in
    any scope matches its commands, and an allow rule covers every one of them; otherwise `ask`,
    with a note per allow-step saying what keeps it at ask and which file and rule to change."""
    files, unreadable, steps = _unattended_steps(cwd)
    _, is_set, _ = unattended_prefs(cwd)
    said = "allow saved" if is_set else "allow by default"
    effective, notes = {k: "ask" for k in UNATTENDED_STEPS}, {}
    for step, (blocked, covered, refused) in steps.items():
        if unreadable:
            notes[step] = (f"{step}: {said}, but it stays ask: {'; '.join(map(json_trouble, unreadable))}, "
                           f"so its rules are unknown; fix it first.")
        elif blocked:
            which = "; ".join(f'{b} rule "{r}" in {f}' for b, r, f in blocked)
            notes[step] = (f"{step}: {said}, but it stays ask: {which} matches, and deny and ask answers come "
                           f"before allow ones (Claude Code's rules in every scope, and the kit guard's), so an allow "
                           f"rule in settings.local.json cannot override it. The owner changes that rule, or {step} "
                           f"waits for them.")
        elif not covered:
            notes[step] = (f"{step}: {said}, but it stays ask until the owner adds "
                           + ", ".join(f'"{r}"' for r in UNATTENDED_RULES[step])
                           + f" to {files[-1]} permissions.allow.")
        else:
            effective[step] = "allow"
            if refused:
                notes[step] = (f"{step}: allow, but " + "; ".join(f'deny rule "{r}" in {f} refuses {", ".join(forms)}'
                                                                 for r, f, forms in refused)
                               + " outright (no prompt, so nothing waits): a thread hands that form back.")
    return effective, notes


# Commands outside the steps: a blocking rule that matches one of these asks for more than the step.
OTHER_COMMANDS = ["git reset --hard HEAD", "git status", "rm -rf build"]


def unattended_proposal(cwd):
    """The settings changes that would make every saved `allow` effective, for the owner to approve:
    [{"file", "committed", "remove": [(behavior, rule)], "add": [rule], "broad": [rule], "diff"}].
    Nothing is written here: the coordinator applies one only when the owner asks, with an Edit the
    owner approves in Claude Code's prompt (settings_guard.py asks for it). Empty while a settings
    file does not parse. Deny rules are never proposed for removal, and a kit.json guard rule is
    only named in the note: both stay the owner's to change by hand."""
    files, unreadable, steps = _unattended_steps(cwd)
    if unreadable:
        return []
    changes = {}
    for step, (blocked, covered, _) in steps.items():
        for b, r, f in blocked:
            if b == "deny":  # a deny is a project's hard line: never proposed for removal
                continue
            entry = changes.setdefault(f, {"remove": [], "add": []})
            if (b, r) not in entry["remove"]:
                entry["remove"].append((b, r))
        if not covered:
            entry = changes.setdefault(files[-1], {"remove": [], "add": []})
            entry["add"] += [r for r in UNATTENDED_RULES[step] if r not in entry["add"]]
    root = Path(main_checkout(cwd) or cwd)
    out = []
    for f in files:
        if f not in changes:
            continue
        old, _ = read_json(f)
        perms = dict(old.get("permissions") or {}) if isinstance(old.get("permissions"), dict) else {}
        for b, r in changes[f]["remove"]:
            perms[b] = [x for x in perms.get(b, []) if str(x) != r]
        add = [r for r in changes[f]["add"] if r not in (perms.get("allow") or [])]
        if add:
            perms["allow"] = list(perms.get("allow") or []) + add
        new = {**old, "permissions": perms}
        diff = "\n".join(difflib.unified_diff(json.dumps(old, indent=2).splitlines(), json.dumps(new, indent=2).splitlines(),
                                              fromfile=str(f), tofile=str(f), lineterm=""))
        committed = False
        try:
            rel = f.relative_to(root)
            committed = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", str(rel)],
                                       capture_output=True, timeout=10, env=git_env()).returncode == 0
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
        broad = [r for _, r in changes[f]["remove"] if any(bash_rule_matches(r, c) for c in OTHER_COMMANDS)]
        out.append({"file": f, "committed": committed, "remove": changes[f]["remove"], "add": add,
                    "broad": broad, "diff": diff})
    return out


EXCLUDE_LOCK_WAIT = 2.0  # seconds; a session start must not stall on a stuck holder


class Busy(OSError):
    """Another process held the lock for longer than the wait."""


def git_common_path(root, name):
    """The absolute path of `name` in the repository's common git dir (shared by its worktrees),
    else None outside git."""
    found = git_out(root, "rev-parse", "--path-format=absolute", "--git-path", name, timeout=10)
    return Path(found) if found else None


def git_lock(root, name, wait=None):
    """A lock on `<git dir>/<name>`, shared by every checkout of the repository (Busy after `wait`)."""
    path = git_common_path(root, name)
    if path is None:
        raise Busy(f"{root} is not in a git repository")
    return file_lock(path, wait)


class file_lock:
    """flock on `path`, tried every 50 ms until `wait` seconds have passed, then Busy."""

    def __init__(self, path, wait=None):
        self.path, self.fh = Path(path), None
        self.wait = EXCLUDE_LOCK_WAIT if wait is None else wait

    def __enter__(self):
        import fcntl
        import time
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a")
        deadline = time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() > deadline:
                    self.fh.close()
                    raise Busy(f"{self.path} is held by another process") from None
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.fh.close()  # closing the file releases the lock
        return False


def write_text_atomic(path, text):
    """Replace `path` with `text` through a temporary file in the same folder, so a reader sees the
    old file or the new one, never part of one; the file's mode is kept."""
    import shutil
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def add_exclude_lines(root, lines):
    """The one writer of .git/info/exclude: under a lock in the git dir, read the file, append the
    lines it lacks, and replace it in one step. It never removes or rewrites a line, so the owner's
    own and another process's survive two writers at once. Returns the lines added ([] when none,
    outside git, or when the lock stayed busy)."""
    wanted = list(dict.fromkeys(line for line in lines if line))
    info = git_common_path(root, "info/exclude") if wanted else None
    if not info:
        return []
    try:
        with file_lock(info.with_name("exclude.kit-lock")):
            text = info.read_text(encoding="utf-8") if info.exists() else ""
            have = set(text.splitlines())
            missing = [line for line in wanted if line not in have]
            if missing:
                write_text_atomic(info, text + ("" if not text or text.endswith("\n") else "\n")
                                  + "\n".join(missing) + "\n")
            return missing
    except OSError:
        return []


LOCAL_SETTINGS = ".claude/settings.local.json"


def exclude_local_settings(checkout):
    """Keep the checkout's settings.local.json, once the kit writes it, out of `git status` (an
    untracked file stops the overnight runner): one line in .git/info/exclude, unless git
    already tracks or ignores the file. Returns the lines added."""
    for args in (("ls-files", "--error-unmatch", "--", LOCAL_SETTINGS), ("check-ignore", "-q", "--", LOCAL_SETTINGS)):
        if git_run(checkout, *args)[0] in (0, None):
            return []
    return add_exclude_lines(checkout, ["/" + LOCAL_SETTINGS])


def exclude_lines(root, files=(), dirs=()):
    """The exclude lines (`/<file>`, `/<dir>/`) for paths under the checkout `root` that git does not
    ignore yet. One `git check-ignore` call for all of them; when that call fails (one path beyond a
    symlink fails it for all), each path is checked on its own, and a path git cannot answer for
    gets its line anyway: an extra ignore line is harmless, a missing one is not."""
    asked = [(f.strip("/"), "/" + f.strip("/")) for f in files]
    asked += [(f"{d.strip('/')}/probe", f"/{d.strip('/')}/") for d in dirs]
    if not asked:
        return []

    def check(paths):
        try:
            done = subprocess.run(["git", "-C", str(root), "check-ignore", "-z", "--stdin"],
                                  input="".join(p + "\0" for p in paths), capture_output=True, text=True,
                                  timeout=10, env=git_env())
        except Exception:
            return None
        return set(done.stdout.split("\0")) if done.returncode in (0, 1) else None

    ignored = check([p for p, _ in asked])
    if ignored is None:
        if not git_root(root):
            return []
        ignored = set()
        for path, _ in asked:
            ignored |= check([path]) or set()
    return [line for path, line in asked if path not in ignored]


def exclude(root, rel):
    """Keep `rel` (a file under the checkout `root`) out of git through .git/info/exclude, unless
    the project ignores it already."""
    add_exclude_lines(root, exclude_lines(root, files=[rel]))


def exclude_dir(root, rel):
    """Keep the folder `rel` (under the checkout `root`) out of git: the line `/<rel>/` in
    .git/info/exclude, unless the project ignores the folder already."""
    add_exclude_lines(root, exclude_lines(root, dirs=[str(rel)]))


# Where the kit keeps a project's working state: `.kit/` at the repo root, or `.claude/` in a
# project that has not moved yet. Claude Code asks the owner before any write inside `.claude`
# (a protected path; only `.claude/worktrees/` is exempt) and no allow rule pre-approves it, so
# background threads stalled on those prompts while the owner was away; writes under `.kit/`
# pass. What Claude Code reads (settings, skills/, agents/, worktrees/, loop.md) and the kit's own
# kit.json / kit.local.json stay in `.claude/`: the gate commands permission.py lets run unasked
# come from kit.json, so it stays behind the protected path. migrate_state.py moves the entries.
STATE_DIR = ".kit"
LEGACY_STATE_DIR = ".claude"
# What moves, an allowlist: a name missing here stays where it is (other agents' agent-memory too).
STATE_NAMES = ("lead", "evidence", "overnight", "agent-memory/kit-verifier")
# In the checkout they belong to, a linked worktree included: a run lives in the checkout it ran
# in, and a thread saves its proof under its own worktree. The gate's record is the exception:
# gate.py keeps it in the main checkout's evidence folder, so it outlives the worktree.
PER_CHECKOUT_STATE = ("overnight", "evidence")
LEGACY_LEAD = ".claude/lead/"  # a kit.json `lead.board` under it moves with the folder (board_file)


def has_legacy_state(base):
    """True when the checkout `base` still holds kit state under `.claude/`."""
    return any((Path(base) / LEGACY_STATE_DIR / name).exists() for name in STATE_NAMES)


def kit_dir_linked(base):
    """True when the checkout's `.kit` is a symlink: it is not the kit's folder, nothing is written
    through it, and the checkout stays on `.claude/` (migrate_state.py says so once)."""
    return (Path(base) / STATE_DIR).is_symlink()


def linked_part(base, rel):
    """The first symlink on the way from the folder `base` to `base/rel`, `rel` itself included
    (`.claude`, `.claude/agent-memory`, then the entry), or None. An entry reached through a link
    is the owner's, maybe shared by other checkouts: the kit reads it there but never moves it."""
    path = Path(base)
    for part in Path(rel).parts:
        path = path / part
        if path.is_symlink():
            return path
    return None


def state_dir_name(base):
    """`.kit` when it is a folder in the checkout `base` (pass the main checkout), `.claude` when
    that still holds kit state or `.kit` is a symlink, else `.kit`: a new project starts there."""
    base = Path(base)
    if kit_dir_linked(base):
        return LEGACY_STATE_DIR
    if (base / STATE_DIR).is_dir():
        return STATE_DIR
    return LEGACY_STATE_DIR if has_legacy_state(base) else STATE_DIR


def _state_bases(root, per_checkout):
    own = git_root(root) or Path(root)
    main = main_checkout(root) or own
    return own, main, (own if per_checkout else main)


def state_dir(root, per_checkout=False):
    """The folder new kit state goes to, decided on the main checkout; `per_checkout` puts it in
    `root`'s own checkout (overnight runs live in the worktree they ran in)."""
    _, main, base = _state_bases(root, per_checkout)
    return base / state_dir_name(main)


def state_entry(root, name, per_checkout=None):
    """Where the entry `name` (one of STATE_NAMES) is: `.kit/<name>` when it exists, else
    `.claude/<name>` when that exists (a `.kit` that is a symlink is never looked in), else
    under state_dir, where it will be made. Reads and
    writes both go through this, so an entry the move left behind (tracked in git, say) is still
    the one in use. `lead` and the verifier's memory are the main checkout's; `evidence` and
    `overnight` are each checkout's own (PER_CHECKOUT_STATE) unless `per_checkout` is False, as
    for gate.py's record, which stays in the main checkout's evidence."""
    if per_checkout is None:
        per_checkout = name.split("/")[0] in PER_CHECKOUT_STATE
    _, main, base = _state_bases(root, per_checkout)
    for folder in (LEGACY_STATE_DIR,) if kit_dir_linked(base) else (STATE_DIR, LEGACY_STATE_DIR):
        if (base / folder / name).exists():
            return base / folder / name
    return base / state_dir_name(main) / name


OVERNIGHT_UNTOLD = "untold.jsonl"  # overnight.py's tell_later: detached runs that ended, not yet said
OVERNIGHT_TOLD = "told.json"  # dead runs already said, in the main checkout's overnight folder
OVERNIGHT_GONE = "stopped without finishing: its process is gone (its container or machine stopped)"
OVERNIGHT_SAY = 5  # the most runs one session start says; the rest wait in the file for status
OVERNIGHT_LOCK_WAIT = 2.0  # seconds; a session start does not stall on a stuck holder


def overnight_alive(pid, proc=Path("/proc")):
    """Whether `pid` is still an overnight runner, told apart from a reused pid by its command
    line: /proc where there is one, else `ps -p <pid> -o command=`. Only without ps does a
    process that exists count as alive."""
    if proc.is_dir():
        try:
            return b"overnight.py" in (proc / str(pid) / "cmdline").read_bytes()
        except OSError:
            return False
    try:
        got = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5)
        return "overnight.py" in got.stdout
    except FileNotFoundError:
        pass
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell: not news yet
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _flock(fh, wait=OVERNIGHT_LOCK_WAIT):
    """An exclusive flock on the open file `fh`, tried until `wait` seconds have passed."""
    import fcntl
    import time
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.02)


def _untold_lines(data):
    return [line for line in data.split(b"\n") if line.strip()]


def _untold_entry(line):
    try:
        entry = json.loads(line.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None  # None: said as unreadable


def _dead_run(state_file):
    """The news entry of a run whose state.json has a pid and no stop_reason while that process
    is gone (a run that died with its container writes nothing), else None."""
    state = json.loads(state_file.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(state, dict) or state.get("stop_reason"):
        return None
    pid = state.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or overnight_alive(pid):
        return None
    return {"run": state.get("run_id") or state_file.parent.name, "dir": str(state_file.parent),
            "stop_reason": OVERNIGHT_GONE, "iterations": state.get("iteration"), "cost": state.get("cost"),
            "branch": state.get("branch"), "pushed": False}


def overnight_news(root, consume=False, limit=None):
    """The project's overnight runs that ended unseen, as (news, left): the lines detached runs left
    in each checkout's untold.jsonl (and in an untold.jsonl.*.reading an earlier kit left behind),
    and the runs that died without a word. Read only, it lists them all and changes nothing.
    `consume` says each one once, at most `limit`: the said lines are cut from untold.jsonl in place,
    under the same flock overnight.py appends under, so a run that ends meanwhile is neither lost
    nor said twice; the lines past `limit` stay there (`left` counts them). A dead run said is
    remembered in the main checkout's overnight/told.json; the run's own files are left alone."""
    rc, out, _ = git_run(root, "worktree", "list", "--porcelain")
    checkouts = [Path(ln[9:]) for ln in out.splitlines() if ln.startswith("worktree ")] if rc == 0 else []
    folders = [checkout / folder / "overnight" for checkout in checkouts for folder in (STATE_DIR, LEGACY_STATE_DIR)
               if (checkout / folder / "overnight").is_dir() and not (checkout / folder).is_symlink()]
    if not folders:
        return [], 0
    told_file = state_entry(root, "overnight", per_checkout=False) / OVERNIGHT_TOLD
    try:
        told = set(json.loads(told_file.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        told = set()
    if not consume:
        news = []
        for runs in folders:
            for leftover in sorted(runs.glob(OVERNIGHT_UNTOLD + ".*.reading")):
                try:
                    news += [_untold_entry(line) for line in _untold_lines(leftover.read_bytes())]
                except OSError:
                    pass
            try:
                with open(runs / OVERNIGHT_UNTOLD, "rb") as fh:
                    if _flock(fh):
                        news += [_untold_entry(line) for line in _untold_lines(fh.read())]
            except OSError:
                pass
            for state_file in sorted(runs.glob("*/state.json")):
                try:
                    entry = _dead_run(state_file)
                except Exception:  # one odd run never hides the others
                    continue
                if entry and entry["dir"] not in told:
                    news.append(entry)
        return news, 0
    try:
        consumer = file_lock(folders[0] / ".told.lock", OVERNIGHT_LOCK_WAIT)  # the same folder for every start
        consumer.__enter__()
    except Busy:
        return [], 0  # another start is saying them now
    try:
        return _overnight_consume(root, folders, told_file, told, limit)
    finally:
        consumer.__exit__(None, None, None)


def _overnight_consume(root, folders, told_file, told, limit):
    room = float("inf") if limit is None else limit
    news, left, newly = [], 0, []
    for runs in folders:
        untold = runs / OVERNIGHT_UNTOLD
        try:
            fh = open(untold, "r+b") if untold.exists() else None
            leftovers = sorted(runs.glob(OVERNIGHT_UNTOLD + ".*.reading"))
            if leftovers and fh is None:
                fh = open(untold, "a+b")
        except OSError:
            fh = None
        if fh is not None:
            with fh:
                if _flock(fh):
                    fh.seek(0)
                    lines = _untold_lines(fh.read())
                    gathered = []
                    for leftover in leftovers:  # an earlier kit's rename-read-unlink, cut short
                        try:
                            gathered.append((leftover, _untold_lines(leftover.read_bytes())))
                        except OSError:
                            pass
                    lines += [line for _, got in gathered for line in got]
                    take = lines[:max(0, int(min(room, len(lines))))]
                    keep = lines[len(take):]
                    fh.seek(0)
                    fh.truncate()  # in place: the writer's file stays the same inode
                    fh.write(b"".join(line + b"\n" for line in keep))
                    fh.flush()
                    for leftover, _ in gathered:
                        try:
                            leftover.unlink()
                        except OSError:
                            pass
                    news += [_untold_entry(line) for line in take]
                    room -= len(take)
                    left += len(keep)
        for state_file in sorted(runs.glob("*/state.json")):
            try:
                entry = _dead_run(state_file)
            except Exception:
                continue
            if not entry or entry["dir"] in told:
                continue
            if room > 0:
                news.append(entry)
                newly.append(entry["dir"])
                room -= 1
            else:
                left += 1
    if newly:
        kept = sorted(d for d in told | set(newly) if Path(d).is_dir())  # a removed run is forgotten
        try:
            write_text_atomic(told_file, json.dumps(kept, indent=2) + "\n")
            exclude_state(root, "overnight", per_checkout=False)
        except OSError:
            pass
    return news, left


def overnight_news_line(entry):
    """One run from overnight_news, as the session start says it. It never raises: a field that
    is missing or of the wrong type prints as `?`, and a record that is not a JSON object is said
    as an end that could not be read."""
    if not isinstance(entry, dict):
        return "kit: an overnight run ended (its record could not be read)"

    def text(key):
        value = entry.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)) or value == "":
            return "?"
        return " ".join(str(value).split())[:200] or "?"  # one line, whatever the file holds

    iterations = entry.get("iterations")
    iterations = iterations if isinstance(iterations, int) and not isinstance(iterations, bool) else "?"
    cost = entry.get("cost")
    ok = isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost == cost and abs(cost) < 1e12
    pushed = {True: "pushed", False: "not pushed"}.get(entry.get("pushed"), "pushed ?")
    return (f"kit: the overnight run {text('run')} ended: {text('stop_reason')}, {iterations} iterations, "
            f"USD {f'{cost:.2f}' if ok else '?'}, branch {text('branch')} {pushed}")


def board_file(root, config=None):
    """The board: kit.json `lead.board` (relative to `root`), else `<state>/lead/board.md`. A path
    inside the old lead folder (`.claude/lead/board.md`, the default /kit:init wrote, or a name of
    the owner's own such as `.claude/lead/BOARD.md`) follows the move: read only from `.claude/lead`,
    it showed "none open" once the folder had moved. A path anywhere else is the owner's."""
    lead = config.get("lead") if isinstance(config, dict) else None
    board = lead.get("board").strip() if isinstance(lead, dict) and isinstance(lead.get("board"), str) else ""
    if not board:
        return state_entry(root, "lead", per_checkout=False) / "board.md"
    path = Path(board) if Path(board).is_absolute() else Path(root) / board
    for base in dict.fromkeys(_state_bases(root, False)[:2]):
        try:
            inside = path.relative_to(base / LEGACY_LEAD)
        except ValueError:
            continue
        return state_entry(root, "lead", per_checkout=False) / inside
    return path


def exclude_state(root, name, per_checkout=None):
    """Keep the state entry `name` out of git where it is now: one line per entry
    (`/.kit/lead/`), never a blanket `/.kit/`, so a project may commit other files there."""
    path = state_entry(root, name, per_checkout)
    for base in dict.fromkeys(_state_bases(root, False)[:2]):
        try:
            exclude_dir(base, path.relative_to(base).as_posix())
            return
        except ValueError:
            continue


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


def personal_config():
    """The person's own kit.json, ~/.claude/kit.json: one per machine user, shared by every Claude
    Code account on it (a second account's CLAUDE_CONFIG_DIR does not move it). `"mode": "light"`
    there turns the coordinator line off; machine_setup.py records its answer there."""
    return Path.home() / ".claude" / "kit.json"


def personal_mode():
    """`light` when the personal kit.json says so, else `` (the coordinator, in a kit project)."""
    value, _ = read_json(personal_config())
    mode = (value or {}).get("mode")
    return "light" if isinstance(mode, str) and mode.strip().lower() == "light" else ""


def write_json_atomic(path, value, backup=None):
    """Write `value` to `path` through a temporary file beside its target, so a reader never sees
    half a file and a symlinked file stays a symlink; with `backup`, the old file is copied to that
    name beside `path` first. For a settings file another writer may change, use update_settings."""
    import shutil
    path = Path(path)
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists():
        shutil.copy2(target, path.with_name(backup))
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        if target.exists():
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# The one writer for Claude Code settings files (settings.json, settings.local.json) and the personal
# kit.json. Every kit write takes a lock, re-reads the file under it and merges into what is on disk
# at that moment, so two kit writers never lose each other's change. The lock files live in the
# user's own lock folder (the system temp dir's claude-kit-<uid>/, mode 0700; one that belongs to
# another user is refused), one per file written, named by a hash of its resolved path: nothing is written into the project or the config dir to lock, so a checkout
# stays clean and a symlinked settings file leaves nothing in its target's folder. Within one
# process each lock is reentrant, so a writer may call another (away_on writes the marker under the
# settings.json lock). Claude Code does not take this lock, so the file's size and mtime are compared again
# before the replace, and a change made meanwhile is merged once more.
SETTINGS_LOCK = "kit-settings.lock"  # the name earlier versions left beside a settings file
SETTINGS_LOCK_WAIT = 2.0  # seconds; a stuck holder must not stall a session start
SETTINGS_RETRIES = 5
_settings_held = {}  # lock file -> [depth, open file]


class SettingsBusy(OSError):
    """Another process held the settings lock for longer than SETTINGS_LOCK_WAIT."""

    def __init__(self, path):
        super().__init__(f"{path} is held by another process")
        self.lock = path


class LockFolderForeign(OSError):
    """The settings lock folder exists and belongs to another user."""

    def __init__(self, path):
        super().__init__(f"{path} belongs to another user")
        self.folder = path


def settings_lock_folder():
    """The current user's folder for the settings locks: <temp>/claude-kit-<uid>, so a second user
    on a shared temp dir (or a run as root) never leaves a folder the others cannot write."""
    who = os.getuid() if hasattr(os, "getuid") else __import__("getpass").getuser()
    return Path(tempfile.gettempdir()) / f"claude-kit-{who}"


def make_lock_folder(folder):
    """Create `folder` with mode 0700, or check an existing one is the current user's and tighten
    it to 0700 when it is looser. Raises LockFolderForeign for one of another user's, OSError when
    it cannot be made."""
    try:
        folder.mkdir(mode=0o700)
        os.chmod(folder, 0o700)  # mkdir's mode is narrowed by the umask; ours to read and write
    except FileExistsError:
        if not folder.is_dir():
            raise
    if hasattr(os, "getuid") and (os.lstat(folder).st_uid != os.getuid() or os.stat(folder).st_uid != os.getuid()):
        raise LockFolderForeign(folder)
    if os.stat(folder).st_mode & 0o077:
        os.chmod(folder, 0o700)  # another user could otherwise swap a lock file in it


def settings_lock_file(target=None):
    """The lock for the file `target` (default: the account's settings.json), in the current user's
    lock folder. The target is resolved first, so one file reached by two spellings or through a
    symlink is one lock (a second flock on it in one process would wait)."""
    import hashlib
    key = str(Path(target or user_settings()).resolve())
    name = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return settings_lock_folder() / f"settings-{name}.lock"


class settings_lock:
    """`with kitlib.settings_lock(file):` holds the lock for `file` (default: the account's
    settings.json); nested uses of one lock in one process share it. Raises SettingsBusy after
    SETTINGS_LOCK_WAIT, LockFolderForeign when the lock folder is another user's, or OSError when
    it cannot be created."""

    def __init__(self, target=None):
        self.path = settings_lock_file(target)

    def __enter__(self):
        held = _settings_held.get(self.path)
        if held is None:
            import fcntl  # here, so a platform without it cannot break importing this module
            import time
            make_lock_folder(self.path.parent)
            fh = open(self.path, "w")
            deadline = time.monotonic() + SETTINGS_LOCK_WAIT
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        fh.close()
                        raise SettingsBusy(self.path) from None
                    time.sleep(0.05)
            held = _settings_held[self.path] = [0, fh]
        held[0] += 1
        return self

    def __exit__(self, *exc):
        held = _settings_held[self.path]
        held[0] -= 1
        if held[0] == 0:
            held[1].close()  # closing releases the flock
            del _settings_held[self.path]
        return False


def write_failed(exc, what):
    """One line for an owner command whose settings write failed: what was not changed and what to
    do. `exc` is SettingsBusy (try again), LockFolderForeign (another user's lock folder) or another
    OSError (the path that cannot be written)."""
    if isinstance(exc, SettingsBusy):
        return (f"{what} was not changed: another kit process held {exc.lock} for more than "
                f"{SETTINGS_LOCK_WAIT:g} s. Try again in a moment.")
    if isinstance(exc, LockFolderForeign):
        return (f"{what} was not changed: the lock folder {exc.folder} belongs to another user. "
                f"Remove it, or set TMPDIR to a folder of your own, then try again.")
    where = exc.filename or "the settings folder"
    return f"{what} was not changed: {where} cannot be written ({exc.strerror or exc}). Make it writable, then try again."


def drop_old_lock(path):
    """Remove the kit-settings.lock an earlier version left beside `path` (and beside its target)."""
    path = Path(path)
    for folder in {path.parent, path.resolve().parent}:
        try:
            (folder / SETTINGS_LOCK).unlink(missing_ok=True)
        except OSError:
            pass  # a folder that is not ours to tidy, or a lock that is a folder: leave it


def _signature(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns, st.st_ino)


def update_settings(path, change, backup=None):
    """Change one settings file in place: resolve a symlink to its target, take the settings lock,
    read the file as it is now, call `change(settings)` (edit the dict in place; return False when
    there is nothing to write), copy the old file to `backup` beside `path`, then replace the target
    in one step, keeping its mode bits. Returns `written`, `same`, `broken` (not a JSON object; the
    file is left alone) or `busy` (it kept changing). Raises SettingsBusy when the file's lock is
    held, and OSError when the folder cannot be written."""
    path = Path(path)
    with settings_lock(path):
        for _ in range(SETTINGS_RETRIES):
            target = path.resolve()
            before = _signature(target)
            settings, ok = read_json(target)
            if not ok:
                return "broken"
            if change(settings) is False:
                return "same"
            if _signature(path.resolve()) != before:
                continue  # Claude Code or the owner wrote it meanwhile: merge again from theirs
            write_json_atomic(path, settings, backup=backup)
            drop_old_lock(path)
            return "written"
    return "busy"


# Away: Claude Code's permissions.denyInsteadOfPrompting (2.1.319) in the account's own settings.json.
# A tool call that would wait on a permission prompt is denied and the turn goes on, so a run nobody
# watches does not stall on a prompt. `items.py away on` sets it when the owner leaves and notes that
# it did in AWAY_MARKER beside settings.json: the time, the file and a hash of the value written.
# The key counts as the kit's only while that marker matches it; the kit removes it on `away off`
# (the coordinator runs it at the owner's next message) or at the next interactive session start.
# A marker whose key is gone is dropped the first time the kit reads the state, so a value the owner
# sets later is his, and the kit never removes it.
AWAY_KEY = "denyInsteadOfPrompting"
AWAY_MARKER = "kit-away.json"
AWAY_BACKUP = "settings.json.kit-away-backup"


def user_settings():
    return config_dir() / "settings.json"


def away_hash(path, value):
    import hashlib
    text = json.dumps({"settings": str(path), "key": AWAY_KEY, "value": value}, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def away_marker():
    """The marker as away_on wrote it, or None."""
    value, ok = read_json(config_dir() / AWAY_MARKER)
    return value if ok and value else None


def away_state():
    """(state, path): `kit` (on, set by the kit), `own` (on, set by the owner), `off`, or `broken`
    (settings.json is not a JSON object, or its permissions are not one). A marker left without its
    key (the owner removed it, or restored a backup) is dropped here."""
    path = user_settings()
    settings, ok = read_json(path)
    perms = (settings or {}).get("permissions", {})
    if not ok or not isinstance(perms, dict):
        return "broken", path
    marker = config_dir() / AWAY_MARKER
    if AWAY_KEY not in perms:
        if marker.exists():
            with settings_lock():
                again, ok = read_json(path)
                if ok and AWAY_KEY not in ((again or {}).get("permissions") or {}):
                    marker.unlink(missing_ok=True)
        return "off", path
    if perms[AWAY_KEY] is not True:
        return "off", path
    mark = away_marker()
    if mark and mark.get("settings") == str(path) and mark.get("hash") == away_hash(path, perms[AWAY_KEY]):
        return "kit", path
    return "own", path


def away_since():
    """When the kit turned away on, as local `YYYY-MM-DD HH:MM`, or None."""
    import time
    since = (away_marker() or {}).get("since")
    if not isinstance(since, (int, float)):
        return None
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(since))


def away_on():
    """Turn away on; returns (exit code, message)."""
    with settings_lock():
        state, path = away_state()
        if state == "broken":
            return 1, f"{path} is not a valid JSON object; nothing was changed. Fix it, then run away on again."
        if state == "own":
            return 0, f"Away is already on: you set permissions.{AWAY_KEY} in {path} yourself; the kit leaves it."
        if state == "kit":
            return 0, (f"Away is already on (since {away_since()}). The coordinator runs `I away off` at the "
                       "user's next message.")

        def turn_on(settings):
            perms = settings.setdefault("permissions", {})
            if not isinstance(perms, dict) or perms.get(AWAY_KEY) is True:
                return False
            perms[AWAY_KEY] = True

        if update_settings(path, turn_on, backup=AWAY_BACKUP) != "written":
            return 1, f"{path} changed while the kit wrote it; nothing was changed. Run away on again."
        write_json_atomic(config_dir() / AWAY_MARKER, {"settings": str(path), "since": int(time_now()),
                                                       "hash": away_hash(path, True)})
    return 0, (f"Away on: permissions.{AWAY_KEY} is true in {path} (backup {AWAY_BACKUP}). A tool call that "
               "would wait on a permission prompt is denied instead and the turn goes on. The next "
               "interactive session start turns it off.\n"
               "The owner is back when he writes: the coordinator runs `I away off` at the user's next "
               "message, before anything else.")


def away_off():
    """Turn away off if the kit turned it on; returns (exit code, message)."""
    marker = config_dir() / AWAY_MARKER
    with settings_lock():
        state, path = away_state()
        if state == "broken":
            return 1, f"{path} is not a valid JSON object; nothing was changed."
        if state == "own":
            return 0, (f"Away stays on: you set permissions.{AWAY_KEY} in {path} yourself, so the kit leaves it. "
                       "To turn it off, remove that key from the file.")
        if state == "kit":
            def turn_off(settings):
                perms = settings.get("permissions")
                if not isinstance(perms, dict) or perms.get(AWAY_KEY) is not True:
                    return False
                perms.pop(AWAY_KEY)
                if not perms:
                    settings.pop("permissions")

            if update_settings(path, turn_off, backup=AWAY_BACKUP) not in ("written", "same"):
                return 1, f"{path} kept changing; away is still on. Run away off again."
        marker.unlink(missing_ok=True)
    return 0, ("Away off: permission prompts ask again." if state == "kit" else "Away is off.")


def time_now():
    import time
    return time.time()


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
        out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout,
                             env=git_env())
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


# Variables that point git at another repository. A hook or a script started from inside a git
# command (a pre-push hook, a rebase's exec step) inherits them, and a `git -C <other repo>` run
# then reads the wrong repository; the branch and worktree checks clear them first.


hermetic_env = git_env  # one helper; the older name is kept for its callers


def git_run(cwd, *args, timeout=30):
    """(returncode, stdout, stderr) of a git command in a hermetic environment; (None, "", reason)
    when git cannot be run at all or times out."""
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                             timeout=timeout, env=hermetic_env())
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "", str(exc)


def git_base(root):
    """default_branch, with git run hermetically."""
    code, out, _ = git_run(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out.strip().startswith("origin/"):
        return out.strip()
    for name in ("origin/main", "origin/master", "main", "master"):
        if git_run(root, "rev-parse", "--verify", "--quiet", name + "^{commit}")[0] == 0:
            return name
    return None


def merge_tree_support(root):
    """None when the installed git can test a merge without touching a checkout (`git merge-tree
    --write-tree`, git 2.38+), else the reason it cannot."""
    code, out, err = git_run(root, "version")
    m = re.search(r"(\d+)\.(\d+)", out or "")
    if code != 0 or not m:
        return f"git version unknown ({(err or out).strip() or 'no output'})"
    if (int(m.group(1)), int(m.group(2))) < (2, 38):
        return f"git {m.group(1)}.{m.group(2)} has no `merge-tree --write-tree` (2.38+)"
    return None


def merge_tree(root, a, b, timeout=60):
    """("clean" | "conflict" | "unknown", [files in conflict], reason) for merging b into a, from
    `git merge-tree --write-tree --name-only`, which writes objects only, never a checkout or a
    ref. Exit 0 is clean and 1 a conflict; anything else (an unknown branch, an old git) is
    unknown with git's own words, never a guess."""
    reason = merge_tree_support(root)
    if reason:
        return "unknown", [], reason
    for ref in (a, b):  # merge-tree exits 1 for a name it cannot resolve too, as for a conflict
        if git_run(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")[0] != 0:
            return "unknown", [], f"no commit named {ref}"
    code, out, err = git_run(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", a, b, timeout=timeout)
    if code == 0:
        return "clean", [], ""
    lines = out.splitlines()
    if code == 1 and lines and re.fullmatch(r"[0-9a-f]{40,64}", lines[0].strip()):  # the tree written, then the files
        return "conflict", [ln for ln in lines[1:] if ln.strip()], ""
    return "unknown", [], (err or out).strip().splitlines()[0] if (err or out).strip() else f"git exited {code}"
