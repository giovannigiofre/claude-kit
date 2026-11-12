#!/usr/bin/env python3
"""PermissionRequest (Bash): the project's own gate commands, and the git steps the owner allowed, run
without a prompt.

kit.json `check` and `verify` are commands the user wrote (personal or committed), and the kit's hooks
already run them unasked; a prompt before Claude runs one by hand is a click for nothing. The
same for the kit's own scripts that read, record or tidy (gate.py, lessons.py, compact_logs.py)
and the coordinator's board tools (items.py, proposals.py), which write only under
.claude/lead/. Only an exact `check` or `verify`, or one of those scripts by its real path, is
allowed here (in a project with kit.json); anything else stays with the permission system (and the
guard has already had its say). A command that changes a Claude Code settings file is never
allowed here, whatever it runs: settings_guard.py has asked the owner about it.

The unattended git steps (unattended_step): when the owner saved `allow` for a step in this repo
(`items.py unattended push=allow`: the main checkout's gitignored .claude/kit.local.json, read by
kitlib.unattended_prefs), the prompt for that step's plain form is answered here, whatever rule
raised it (an ask rule in a committed settings.json, or no allow rule). The saved answer is this
part's opt-in, so it works in a repo without kit.json. One shape per step:

  push    git [-C <dir>] push [-u|--set-upstream] [-q] <remote> <branch>: a remote of this checkout
          and a named branch that is not the default, main, master or a guard.protectedBranches
          one; never a force, --mirror, --delete, --all, --tags, --no-verify, a `:` or `+`
          refspec, HEAD, or a bare `git push`
  rebase  [GIT_EDITOR=true] git [-C <dir>] rebase <the remote default, e.g. origin/main> (not while
          the default branch is checked out) | --continue | --abort
  merge   gh pr merge <n> [--repo|-R <owner/repo of this checkout's origin>] --squash|--merge|--rebase
          (or -s|-m|-r) [--delete-branch|-d]; never --admin, --auto, a body or a subject

Around the step: a leading `cd <dir> &&`; `2>&1`; a pipe into tail, head, grep, cut or wc; an
output file (`> f.log`, `>> f.txt`, `.out`) under a temp folder or this checkout, not in .git or
a Claude folder other than its worktrees; after `;` or `&&`, commands that only read (echo, pwd,
ls, cat, grep, tail, head, wc, git status|diff|log|rev-parse|show, gh pr view|checks). Anything
else, such as `git commit ... && git push`, $(...), backticks, a here-document, `&`, `||` or a
second line, gets no answer, so Claude Code asks (or, in a background thread that cannot ask,
refuses) as before. So does a command the kit guard asks about or denies, and deny rules refuse
before any prompt. A kit:implementer thread gets push and rebase; merge is the coordinator's, so
it is answered for the main session only. Standard library only.
"""

import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import settings_guard  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
SCRIPTS = {"gate.py", "lessons.py", "compact_logs.py", "items.py", "proposals.py"}
PYTHON = {"python", "python3"}


def own_script(command):
    """True for `python3 <kit>/.../gate.py ...` where the path really is inside this plugin."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if len(argv) < 2 or Path(argv[0]).name not in PYTHON or any(ch in command for ch in ";&|`$<>"):
        return False
    script = Path(argv[1])
    try:
        resolved = script.resolve(strict=True)
    except OSError:
        return False
    return resolved.name in SCRIPTS and PLUGIN in resolved.parents


def allowed(command, config, cwd=None):
    command = command.strip()
    if settings_guard.command_targets(command, cwd):
        return False
    gates = {str(config.get(k) or "").strip() for k in ("check", "verify")} - {""}
    return command in gates or own_script(command)


# ---------------------------------------------------------------- the unattended git steps

NAME = re.compile(r"[A-Za-z0-9][\w./-]*")
FILTERS = {"tail", "head", "grep", "egrep", "cut", "wc"}
READERS = {"echo", "pwd", "ls", "true", "cat", "grep", "egrep", "tail", "head", "wc"}
GIT_READS = {"status", "diff", "log", "rev-parse", "show"}
LOGS = (".log", ".txt", ".out")


def words(command):
    """[(op, argv, redirect)], op the operator before each simple command ('', '&&', ';', '|') and
    redirect its `>`/`>>` target, or None for what this part does not read: a second line, $(...),
    backticks, a here-document or `<`, subshells or braces, `&`, `||`, other redirects."""
    if "\n" in command or "\r" in command or any(s in command for s in ("$(", "`", "<", "(", ")", "{", "}")):
        return None
    text = re.sub(r"(?<!\S)2>&1(?![^\s;|&])", " ", command)  # `2>&1;` and `2>&1|` too
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|>")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    out, op, argv, redirect = [], "", [], None
    for tok in tokens:
        if tok in ("&&", ";", "|"):
            if not argv or redirect == "":
                return None
            out.append((op, argv, redirect))
            op, argv, redirect = tok, [], None
        elif tok in (">", ">>"):
            if redirect is not None or not argv:
                return None
            redirect = ""
        elif re.fullmatch(r"[;&|>]+", tok):
            return None
        elif redirect == "":
            redirect = tok
        elif redirect is not None:
            return None  # words after the redirect target
        else:
            argv.append(tok)
    if argv and redirect != "":
        out.append((op, argv, redirect))
    elif not (op == ";" and redirect is None):  # only a trailing `;` may end with no command
        return None
    return out


def resolve(path, cwd):
    p = Path(os.path.expanduser(path))
    return Path(os.path.normpath(str(p if p.is_absolute() else Path(cwd) / p)))


def _under(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def output_file_ok(target, cwd, root):
    """A log: a .log/.txt/.out file under a temp folder or this checkout, never in .git or a Claude
    folder (bar the checkout's worktrees)."""
    if not target or "$" in target or not target.endswith(LOGS):
        return False
    real = Path(os.path.realpath(str(resolve(target, cwd))))
    parts = real.parts  # a checkout may itself sit in a temp folder: .git and .claude are refused first
    if ".git" in parts:
        return False
    if ".claude" in parts:
        rest = parts[parts.index(".claude") + 1:]
        if not (len(rest) >= 2 and rest[0] == "worktrees"):
            return False
    temps = {Path(os.path.realpath(r)) for r in ("/tmp", "/private/tmp", "/var/folders", tempfile.gettempdir())}
    roots = {Path(os.path.realpath(str(r))) for r in (root, kitlib.main_checkout(root) or root)}
    return any(_under(real, r) for r in temps | roots)


def filter_ok(argv):
    """A pipe stage that only cuts the step's output down (it names no file)."""
    name, rest = argv[0], argv[1:]
    if name not in FILTERS:
        return False
    if name in ("tail", "head"):
        return all(re.fullmatch(r"-n|-c|-?\d+|-[nc]\d+", a) for a in rest)
    if name in ("cut", "wc"):
        return all(a.startswith("-") for a in rest)
    flags = [a for a in rest if a.startswith("-")]
    return len(rest) - len(flags) == 1 and all(re.fullmatch(r"-[EivFcnwx]+", f) for f in flags)


def reader_ok(argv):
    """A command after the step that only reads."""
    name = argv[0]
    if name in READERS:
        return not (name == "tail" and any(a.startswith(("-f", "-F", "--follow")) for a in argv[1:]))
    if name == "git":
        args = argv[1:]
        if args[:1] == ["-C"]:
            args = args[2:]
        return bool(args) and args[0] in GIT_READS and not any(a.startswith("--output") for a in args)
    if name == "gh":
        return argv[1:3] in (["pr", "view"], ["pr", "checks"]) and "--watch" not in argv
    return False


def origin_slug(root):
    url = kitlib.git_out(root, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]+([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else ""


def merge_of(args, cwd):
    number, repo, method, i = None, None, [], 0
    while i < len(args):
        a = args[i]
        if re.fullmatch(r"\d+", a) and number is None:
            number = a
        elif a in ("--repo", "-R") and i + 1 < len(args):
            repo, i = args[i + 1], i + 1
        elif a.startswith("--repo="):
            repo = a.split("=", 1)[1]
        elif a in ("--squash", "--merge", "--rebase", "-s", "-m", "-r"):
            method.append(a)
        elif a not in ("--delete-branch", "-d"):
            return None
        i += 1
    root = kitlib.git_root(cwd)
    if number is None or len(method) != 1 or not root:
        return None
    if repo and repo.lower() != origin_slug(root):
        return None
    return "merge", root


def step_of(argv, cwd, protected):
    """(step, checkout) for a plain push, rebase or merge as the module docstring says, else None."""
    env = {}
    while argv and re.fullmatch(r"[A-Za-z_]\w*=.*", argv[0]):
        k, _, v = argv[0].partition("=")
        env[k] = v
        argv = argv[1:]
    if not argv:
        return None
    if argv[0] == "gh":
        return merge_of(argv[3:], cwd) if not env and argv[1:3] == ["pr", "merge"] else None
    if argv[0] != "git":
        return None
    args, where = argv[1:], cwd
    if args[:1] == ["-C"]:
        if len(args) < 2:
            return None
        where, args = resolve(args[1], cwd), args[2:]
    root = kitlib.git_root(where)
    if not root or not args:
        return None
    default = kitlib.default_branch(root) or ""
    if args[0] == "push" and not env:
        rest = [a for a in args[1:] if a not in ("-u", "--set-upstream", "-q", "--quiet")]
        if len(rest) != 2 or any(a.startswith("-") for a in rest):
            return None
        remote, branch = rest
        if not NAME.fullmatch(remote) or not NAME.fullmatch(branch) or ".." in branch or branch.endswith((".lock", "/")):
            return None
        names = set(protected) | {"main", "master", "HEAD", default.split("/", 1)[-1]}
        if remote not in kitlib.git_out(root, "remote").split() or branch in names:
            return None
        return "push", root
    if args[0] == "rebase" and set(env) <= {"GIT_EDITOR"} and env.get("GIT_EDITOR", "true") == "true" and len(args) == 2:
        if args[1] in ("--continue", "--abort"):
            return "rebase", root
        current = kitlib.git_out(root, "branch", "--show-current")
        if default.startswith("origin/") and args[1] == default and current and current != default.split("/", 1)[1]:
            return "rebase", root
    return None


def unattended_step(command, cwd, agent=None):
    """The step ('push', 'rebase' or 'merge') this command is, when the owner allowed that step in
    this repo and nothing around it does more than read or log; else None. `agent` is the
    subagent's type (None for the main session)."""
    command = command.strip()
    parts = words(command)
    if not parts:
        return None
    cwd = Path(cwd)
    if parts[0][1][:1] == ["cd"]:
        _, argv, redirect = parts[0]
        if len(argv) != 2 or redirect or "$" in argv[1] or len(parts) < 2 or parts[1][0] != "&&":
            return None
        cwd = resolve(argv[1], cwd)
        parts = [("", parts[1][1], parts[1][2])] + parts[2:]
    root = kitlib.git_root(cwd)
    if not root:
        return None
    try:
        import guard  # its own answer and protected branches count; imported here, since it imports kitlib
        active, opts = guard.settings(root)
    except Exception:
        return None
    found = None
    for op, argv, redirect in parts:
        if op == "|":
            if not filter_ok(argv):
                return None
        elif found is None:
            if op:  # a command before the step, other than the leading cd
                return None
            found = step_of(argv, cwd, (opts.get("protectedBranches") or []) if active else [])
            if not found:
                return None
        elif not reader_ok(argv):
            return None
        if redirect and not output_file_ok(redirect, cwd, root):
            return None
    if not found:
        return None
    step, repo = found
    if agent is not None and (step == "merge" or not str(agent).endswith("implementer")):
        return None  # a thread pushes and rebases its branch; the coordinator merges
    prefs, _, _ = kitlib.unattended_prefs(repo)
    if prefs.get(step) != "allow" or settings_guard.command_targets(command, str(cwd)):
        return None
    if active:
        try:
            if guard.check_bash(command, cwd, Path(os.path.normpath(str(root))), opts):
                return None  # the guard asks or denies: that question stays the owner's
        except Exception:
            return None
    return step


def main():
    data = kitlib.read_input()
    if data.get("tool_name") != "Bash":
        return 0
    command = str((data.get("tool_input") or {}).get("command") or "")
    config, _ = kitlib.load_config(kitlib.project_root(data))
    ok = config is not None and allowed(command, config, data.get("cwd"))
    if not ok:
        cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        # agent_type alone also marks a main session started with --agent: agent_id marks a subagent
        agent = (data.get("agent_type") or "subagent") if data.get("agent_id") else None
        try:
            ok = unattended_step(command, cwd, agent) is not None
        except Exception:
            ok = False  # no answer: Claude Code asks as before
    if ok:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                                 "decision": {"behavior": "allow"}}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
