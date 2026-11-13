"""Shared helpers for the kit hooks. Standard library only, Python 3.9+.

Every hook is a no-op unless the project has `.claude/kit.json` (see the README for the schema),
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
    own = Path(root) / CONFIG
    if own.exists():
        return own
    main = main_checkout(root)
    if main and (Path(main) / CONFIG).exists():
        return Path(main) / CONFIG
    return own


def load_config(root):
    """Return (config, error). config is None when the project has no kit.json; a kit.json that
    is present means the project opted in, even an empty `{}` (callers test `config is None`).
    A worktree without one uses its main checkout's (config_file)."""
    path = config_file(root)
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
    that match a push, rebase or merge as the kit runs them. Each such command stops on a prompt
    in every permission mode (auto too) and from a thread; the owner's saved preference is not read."""
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
            notes[step] = (f"{step}: {said}, but it stays ask: {', '.join(map(str, unreadable))} does not parse, "
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


def exclude(root, rel):
    """Keep `rel` (a file under the checkout `root`) out of git through .git/info/exclude, unless
    the project ignores it already."""
    root = Path(root)
    try:
        if subprocess.run(["git", "-C", str(root), "check-ignore", "-q", rel], capture_output=True,
                          timeout=10, env=git_env()).returncode == 0:
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


def exclude_dir(root, rel):
    """Keep the folder `rel` (under the checkout `root`) out of git: the line `/<rel>/` in
    .git/info/exclude, unless the project ignores the folder already."""
    root, rel = Path(root), str(rel).strip("/")
    try:
        if subprocess.run(["git", "-C", str(root), "check-ignore", "-q", f"{rel}/probe"], capture_output=True,
                          timeout=10, env=git_env()).returncode == 0:
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
        line = f"/{rel}/"
        if line not in text.splitlines():
            info.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n", encoding="utf-8")
    except OSError:
        pass


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


def state_dir_name(base):
    """`.kit` when it exists in the checkout `base` (pass the main checkout), `.claude` when that
    still holds kit state, else `.kit`: a new project starts there."""
    base = Path(base)
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
    `.claude/<name>` when that exists, else under state_dir, where it will be made. Reads and
    writes both go through this, so an entry the move left behind (tracked in git, say) is still
    the one in use. `lead`, `evidence` and the verifier's memory are the main checkout's."""
    if per_checkout is None:
        per_checkout = name.split("/")[0] in PER_CHECKOUT_STATE
    _, main, base = _state_bases(root, per_checkout)
    for folder in (STATE_DIR, LEGACY_STATE_DIR):
        if (base / folder / name).exists():
            return base / folder / name
    return base / state_dir_name(main) / name


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
    """Write `value` to `path` through a temporary file in the same folder, so a reader never sees half
    a file; with `backup`, the old file is copied to that name beside it first."""
    import shutil
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(backup))
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# Away: Claude Code's permissions.denyInsteadOfPrompting (2.1.319) in the account's own settings.json.
# A tool call that would wait on a permission prompt is denied and the turn goes on, so a run nobody
# watches does not stall on a prompt. `items.py away on` sets it when the owner leaves; the kit
# notes that it did (AWAY_MARKER beside settings.json) and takes it away again at the next
# interactive session start or on `away off`. A value the owner set himself has no marker and is
# never removed. Until 2026-11 the mod's `/kit-safety unattended` wrote it to the project's
# settings.local.json instead, where it was easy to forget; session_start removes that one.
AWAY_KEY = "denyInsteadOfPrompting"
AWAY_MARKER = "kit-away.json"
AWAY_BACKUP = "settings.json.kit-away-backup"


def user_settings():
    return config_dir() / "settings.json"


def away_state():
    """(state, path): `kit` (on, set by the kit), `own` (on, set by the owner), `off`, or `broken`
    (settings.json is not a JSON object, or its permissions are not one)."""
    path = user_settings()
    settings, ok = read_json(path)
    perms = (settings or {}).get("permissions", {})
    if not ok or not isinstance(perms, dict):
        return "broken", path
    if perms.get(AWAY_KEY) is not True:
        return "off", path
    return ("kit" if (config_dir() / AWAY_MARKER).exists() else "own"), path


def away_on():
    """Turn away on; returns (exit code, message)."""
    state, path = away_state()
    if state == "broken":
        return 1, f"{path} is not a valid JSON object; nothing was changed. Fix it, then run away on again."
    if state == "own":
        return 0, f"Away is already on: you set permissions.{AWAY_KEY} in {path} yourself; the kit leaves it."
    if state == "kit":
        return 0, "Away is already on; the next interactive session start turns it off."
    settings, _ = read_json(path)
    settings.setdefault("permissions", {})[AWAY_KEY] = True
    write_json_atomic(path, settings, backup=AWAY_BACKUP)
    write_json_atomic(config_dir() / AWAY_MARKER, {"settings": str(path), "since": int(time_now())})
    return 0, (f"Away on: permissions.{AWAY_KEY} is true in {path} (backup {AWAY_BACKUP}). A tool call that "
               "would wait on a permission prompt is denied instead and the turn goes on. The next "
               "interactive session start, or `away off`, turns it off.")


def away_off():
    """Turn away off if the kit turned it on; returns (exit code, message)."""
    state, path = away_state()
    marker = config_dir() / AWAY_MARKER
    if state == "broken":
        return 1, f"{path} is not a valid JSON object; nothing was changed."
    if state == "own":
        return 0, (f"Away stays on: you set permissions.{AWAY_KEY} in {path} yourself, so the kit leaves it. "
                   "To turn it off, remove that key from the file.")
    if state == "kit":
        settings, _ = read_json(path)
        settings["permissions"].pop(AWAY_KEY, None)
        if not settings["permissions"]:
            settings.pop("permissions")
        write_json_atomic(path, settings, backup=AWAY_BACKUP)
    if marker.exists():
        marker.unlink()
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
