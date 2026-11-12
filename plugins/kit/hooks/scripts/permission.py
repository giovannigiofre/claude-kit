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
(`items.py unattended push=allow`, run by the owner: the main checkout's gitignored, untracked
.claude/kit.local.json, read by kitlib.unattended_prefs), the prompt for that step's plain form is
answered here, whatever rule raised it (an ask rule in a committed settings.json, or no allow
rule). The saved answer is this part's opt-in, so it works in a repo without kit.json. The
command must be exactly one of these shapes (SHAPES), made only of letters, digits, blanks and
`_ . / ~ = | > & -`, so no quote, `#`, `;`, `$`, backtick or bracket can hide a second command:

  push    [cd <dir> &&] git [-C <dir>] push [-u|--set-upstream] [-q] origin <branch>: an existing
          local branch (not a tag of the same name, no refs/ or heads/ prefix) that is not the
          default, main, master or a guard.protectedBranches one, with no remote.origin.push
          refspec, push.default unset, simple or current, and origin's push URL its fetch URL
  rebase  [cd <dir> &&] [GIT_EDITOR=true] git [-C <dir>] rebase <the remote default, e.g.
          origin/main> (not while the default branch is checked out) | --continue | --abort
  merge   [cd <dir> &&] gh pr merge <n> [--repo|-R <owner/repo of origin>] one of --squash|--merge|
          --rebase (-s|-m|-r) [--delete-branch|-d]; without -R only where origin is the only
          remote; GH_REPO, when set, names origin's repo and GH_HOST, when set, is github.com

<dir> is absolute, `.`/`..`-relative, `~` or `~/…` (never `~-`, `~1`, `~user`), and a `cd` never
takes a bare relative name, which CDPATH could send elsewhere. Each may end in `2>&1`,
`| tail -N` or `| head -N`, or `> f.log` / `>> f.txt` / `.out` (with `2>&1`) when that file, as
it really is (not a symlink or hard link), is untracked and under this checkout's .claude/ or a
temp folder, never in .git. Anything else gets no answer, so Claude Code asks (or, in a
background thread that cannot ask, refuses) as before. So does a command the kit guard asks about or denies, and deny rules
refuse before any prompt. A kit:implementer thread (that exact agent type) gets push and rebase;
merge is the coordinator's, answered for the main session only. Standard library only.
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
    if resolved.name == "items.py" and settings_guard._sets_unattended(argv[2:]):
        return False  # saving `allow` is the owner's answer, never Claude's own (settings_guard asks)
    return resolved.name in SCRIPTS and PLUGIN in resolved.parents


def allowed(command, config, cwd=None):
    command = command.strip()
    if settings_guard.command_targets(command, cwd):
        return False
    gates = {str(config.get(k) or "").strip() for k in ("check", "verify")} - {""}
    return command in gates or own_script(command)


# ---------------------------------------------------------------- the unattended git steps

# The whole command is matched against one exact shape per step, never parsed: only these
# characters may appear (no quotes, `#`, `;`, `$`, backticks, brackets, `<`, `*`, `:`, `+`, `\`,
# newlines), and each shape is a full match on the command with its blanks collapsed.
SAFE = re.compile(r"[A-Za-z0-9_./~=|>&\- ]+", re.A)
# a directory or log file: not `-` (`cd -` goes back), and a leading `~` only as `~` or `~/…`, since
# bash reads `~-`, `~+`, `~1` and `~user` as other folders (OLDPWD, PWD, the dirs stack, a home)
PATH = r"(?:~(?:/[A-Za-z0-9_./~-]*)?|[A-Za-z0-9_./][A-Za-z0-9_./~-]*)"
BRANCH = r"[A-Za-z0-9][A-Za-z0-9_./-]*"
LEAD = rf"(?:cd (?P<cd>{PATH}) && )?"
GIT = rf"git(?: -C (?P<dir>{PATH}))?"
TAIL = r"(?: 2>&1)? \| (?:tail|head)(?: -n)? -?\d+"
OUT = rf"(?:{TAIL}| >>? (?P<out>{PATH}\.(?:log|txt|out))(?: 2>&1)?| 2>&1)?"
SHAPES = {
    "push": re.compile(rf"{LEAD}{GIT} push(?: (?:-u|--set-upstream))?(?: (?:-q|--quiet))? origin (?P<branch>{BRANCH}){OUT}", re.A),
    "rebase": re.compile(rf"{LEAD}(?:GIT_EDITOR=true )?{GIT} rebase (?P<onto>origin/{BRANCH}|--continue|--abort){OUT}", re.A),
    "merge": re.compile(rf"{LEAD}gh pr merge (?P<number>\d+)(?: (?:--repo|-R) (?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?"
                        rf"(?P<flags>(?: (?:--squash|-s|--merge|-m|--rebase|-r|--delete-branch|-d)){{1,2}}){OUT}", re.A),
}
METHODS = {"--squash", "-s", "--merge", "-m", "--rebase", "-r"}


def resolve(path, cwd):
    p = Path(os.path.expanduser(path))
    return Path(os.path.normpath(str(p if p.is_absolute() else Path(cwd) / p)))


def _under(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def temp_roots():
    return {Path(os.path.realpath(r)) for r in ("/tmp", "/private/tmp", "/var/folders", tempfile.gettempdir())}


def output_file_ok(target, cwd, root):
    """A log the step's output may go to: an untracked file under this checkout's (or its main
    checkout's) .claude/, or one under a temp folder; never in .git, never a file git tracks. The
    file is judged where it really is: not a symlink or a hard link (`k.log` linked to
    kit.local.json would be truncated), and its real name ends in .log, .txt or .out too."""
    literal = resolve(target, cwd)
    real = Path(os.path.realpath(str(literal)))
    if os.path.islink(literal) or ".git" in real.parts or not real.parent.is_dir():
        return False
    if real.suffix not in (".log", ".txt", ".out") or real.name.lower() == "kit.local.json" \
            or settings_guard.NAME.fullmatch(real.name):
        return False
    try:
        st = os.lstat(real)
        if not os.path.isfile(real) or st.st_nlink > 1:
            return False
    except FileNotFoundError:
        pass
    except OSError:
        return False
    if kitlib.git_out(real.parent, "ls-files", "--error-unmatch", "--", real.name):
        return False  # tracked, in this checkout or any other
    roots = {Path(os.path.realpath(str(r))) for r in (root, kitlib.main_checkout(root) or root)}
    inside = sorted((r for r in roots if _under(real, r)), key=lambda r: len(r.parts))
    if inside:  # a checkout may sit in a temp folder or another's .claude/: only its own .claude/ counts
        return _under(real, inside[-1] / ".claude")
    return any(_under(real, t) for t in temp_roots())


def _slug(url):
    m = re.search(r"github\.com[:/]+([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else ""


def origin_slug(root):
    return _slug(kitlib.git_out(root, "remote", "get-url", "origin"))


PUSH_DEFAULTS = {"", "simple", "current"}  # upstream/tracking push `feat` to the branch it tracks (origin/main)


def push_ok(root, branch, protected):
    """`git push origin <branch>` moves only that local branch to the same name on origin: no ref
    prefix, not a tag, not the default or a protected branch, no push refspec in the config that
    would map it elsewhere, a push.default that keeps the name (unset, simple or current: with
    upstream or tracking a branch made from origin/main is pushed onto main), and origin pushes
    where it fetches from (no pushurl or pushInsteadOf pointing at another repo)."""
    if kitlib.git_out(root, "config", "--get", "push.default").lower() not in PUSH_DEFAULTS:
        return False
    fetch_url = kitlib.git_out(root, "remote", "get-url", "origin")
    push_url = kitlib.git_out(root, "remote", "get-url", "--push", "origin")
    if not fetch_url or (push_url != fetch_url and (not origin_slug(root) or _slug(push_url) != origin_slug(root))):
        return False
    if branch.startswith(("refs/", "heads/", "tags/", "remotes/")) or ".." in branch or "//" in branch \
            or branch.endswith((".lock", "/", ".")):
        return False
    default = (kitlib.default_branch(root) or "").split("/", 1)[-1]
    if branch in set(protected) | {"main", "master", "HEAD", default}:
        return False
    if "origin" not in kitlib.git_out(root, "remote").split() or kitlib.git_out(root, "config", "--get-all", "remote.origin.push"):
        return False
    exists = kitlib.git_out(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    tag = kitlib.git_out(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{branch}")
    return bool(exists) and not tag


def merge_ok(root, repo, flags):
    """`gh pr merge` on this checkout's origin only: -R naming it, or no -R where origin is the only
    remote and GH_REPO does not point elsewhere."""
    slug = origin_slug(root)
    if not slug or len([f for f in flags if f in METHODS]) != 1 or len(set(flags)) != len(flags):
        return False
    host = os.environ.get("GH_HOST", "").strip().lower()
    if host and host != "github.com":
        return False  # gh would merge on another host's repo of the same name
    gh_repo = os.environ.get("GH_REPO", "").strip().lower()
    if gh_repo and gh_repo.split("/")[-2:] != slug.split("/"):
        return False
    if repo:
        return repo.lower() == slug
    return kitlib.git_out(root, "remote").split() == ["origin"]


def unattended_step(command, cwd, agent=None):
    """The step ('push', 'rebase' or 'merge') this command is, when the owner allowed that step in
    this repo and the command is exactly that step's shape; else None. `agent` is the subagent's
    type (None for the main session)."""
    command = command.strip(" \t\n")  # not str.strip(): a no-break space is part of a bash word
    if not SAFE.fullmatch(command):
        return None
    plain = re.sub(" +", " ", command)
    step = m = None
    for name, shape in SHAPES.items():
        m = shape.fullmatch(plain)
        if m:
            step = name
            break
    if not step:
        return None
    if agent is not None and (step == "merge" or agent != "kit:implementer"):
        return None  # a thread pushes and rebases its branch; the coordinator merges
    cd = m.group("cd")
    if cd and not (cd.startswith(("/", "~", "./", "../")) or cd in (".", "..")):
        return None  # `cd name` may follow CDPATH (the shell's, unseen here) to another folder
    here = resolve(cd, cwd) if cd else Path(cwd)
    where = resolve(m.groupdict().get("dir"), here) if m.groupdict().get("dir") else here
    root = kitlib.git_root(where)
    if not root:
        return None
    try:
        import guard  # its own answer and protected branches count; imported here, since it imports kitlib
        active, opts = guard.settings(root)
    except Exception:
        return None
    if m.group("out") and not output_file_ok(m.group("out"), here, root):
        return None
    if step == "push" and not push_ok(root, m.group("branch"), (opts.get("protectedBranches") or []) if active else []):
        return None
    if step == "rebase" and m.group("onto").startswith("origin/"):
        default = kitlib.default_branch(root) or ""
        current = kitlib.git_out(root, "branch", "--show-current")
        if not default.startswith("origin/") or m.group("onto") != default or not current \
                or current == default.split("/", 1)[1]:
            return None
    if step == "merge" and not merge_ok(root, m.group("repo"), m.group("flags").split()):
        return None
    prefs, _, _ = kitlib.unattended_prefs(root)
    if prefs.get(step) != "allow" or settings_guard.command_targets(command, str(here)):
        return None
    if active:
        try:
            if guard.check_bash(command, here, Path(os.path.normpath(str(root))), opts):
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
