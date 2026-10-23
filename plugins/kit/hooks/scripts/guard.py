#!/usr/bin/env python3
"""PreToolUse (Bash|Read|Grep|Glob|Agent|Task): deterministic guardrails.

A rule in a prompt is a preference; a rule in a hook is an invariant. This hook blocks the few
actions that cannot be undone or that leak credentials, whatever the permission mode (default,
auto, or a headless overnight iteration), and leaves everything else to the permission system:

  rm-outside       recursive delete of /, the home folder, the repo root or .git, or anything
                   outside the repo and the temp folders
  push-protected   a push to a protected branch (main, master, the remote's default), a force
                   push to one, a mirror push, or deleting one
  discard-work     git reset --hard, checkout/restore of the whole tree, clean, stash drop/clear
                   while there are uncommitted changes; git clean -x/-X always
  system           sudo/su/doas, mkfs, dd to a device, disk erase, shutdown/reboot, recursive
                   chmod/chown outside the repo
  pipe-to-shell    a download piped into a shell or interpreter (curl ... | sh)
  secrets          reading credential stores (~/.ssh, ~/.aws, gh/docker/kube config, .netrc,
                   ~/.gnupg, the macOS keychain) with Bash, Read, Grep or Glob
  agents           optional cap on subagents per session (guard.agentsAsk / guard.agentsDeny)

Active when the project has .claude/kit.json (unless its "guard" is "off"), or everywhere when
~/.claude/kit.json says "guard": "on". Options, under "guard" in either file:
  {"protectedBranches": ["main", "master"], "agentsAsk": 15, "agentsDeny": 40,
   "allowCommands": ["^rm -rf /tmp/my-build$"]}
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh", "python", "python3", "node", "perl", "ruby"}
DOWNLOADERS = {"curl", "wget", "fetch", "http", "https"}
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "nice", "env", "xargs", "timeout"}
SECRET_PATHS = ["~/.ssh", "~/.aws", "~/.config/gh", "~/.netrc", "~/.docker/config.json",
                "~/.kube/config", "~/.gnupg", "~/Library/Keychains", "~/.git-credentials",
                "~/.config/gcloud", "~/.azure"]


def home():
    return Path(os.environ.get("HOME") or Path.home())


def expand(word, cwd):
    word = word.replace("${HOME}", str(home())).replace("$HOME", str(home()))
    if word == "~" or word.startswith("~/"):
        word = str(home()) + word[1:]
    p = Path(word)
    if not p.is_absolute():
        p = Path(cwd) / p
    return Path(os.path.normpath(str(p)))


def temp_roots():
    roots = {Path("/tmp"), Path("/private/tmp"), Path("/var/folders"), Path("/private/var/folders"),
             Path(tempfile.gettempdir())}
    return [Path(os.path.normpath(str(r))) for r in roots]


def under(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def settings(root):
    """(active, options): project kit.json wins, else the user's ~/.claude/kit.json."""
    project, _ = kitlib.load_config(root)
    user = {}
    try:
        user = json.loads((home() / ".claude" / "kit.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    user = user if isinstance(user, dict) else {}
    if isinstance(project, dict):
        g = project.get("guard", user.get("guard"))
        if g == "off":
            return False, {}
        return True, g if isinstance(g, dict) else (user.get("guard") if isinstance(user.get("guard"), dict) else {})
    g = user.get("guard")
    if g == "on" or isinstance(g, dict):
        return True, g if isinstance(g, dict) else {}
    return False, {}


def segments(command):
    """Simple commands of a shell line: split on ; && || | & and newlines, recurse into sh -c."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""
        tokens = list(lex)
    except ValueError:
        tokens = command.split()
    out, cur, pipe_from = [], [], None
    for tok in tokens + [";"]:
        if tok and set(tok) <= set(";&|"):
            if cur:
                out.append({"argv": cur, "piped_from": pipe_from})
            pipe_from = cur if tok == "|" else None
            cur = []
        else:
            cur.append(tok)
    nested = []
    for seg in out:
        argv = strip_wrappers(seg["argv"])
        if len(argv) >= 3 and Path(argv[0]).name in SHELLS and "-c" in argv[1:-1]:
            nested.extend(segments(argv[argv.index("-c") + 1]))
    return out + nested


def strip_wrappers(argv):
    argv = list(argv)
    while argv:
        name = Path(argv[0]).name
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            argv = argv[1:]
        elif name in WRAPPERS:
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                argv = argv[1:]
            if name == "timeout" and argv:
                argv = argv[1:]
        else:
            break
    return argv


def git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def protected_branches(cwd, opts):
    names = set(opts.get("protectedBranches") or ["main", "master"])
    head = git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head.startswith("origin/"):
        names.add(head[len("origin/"):])
    return names


def check_rm(argv, cwd, root):
    flags = [a for a in argv[1:] if a.startswith("-")]
    recursive = any(f in ("-r", "-R", "--recursive") or (not f.startswith("--") and ("r" in f or "R" in f))
                    for f in flags)
    if not recursive:
        return None
    hm = Path(os.path.normpath(str(home())))
    for word in [a for a in argv[1:] if not a.startswith("-")]:
        if word in (".", "..", ".*", "/*", "~/*") or word.endswith("/.."):
            return f"recursive delete of '{word}'"
        target = expand(word, cwd)
        if target == Path("/") or target == hm or under(hm, target):
            return f"recursive delete of '{word}' ({target})"
        if target.name == ".git" or "/.git/" in str(target) + "/" and under(target, root):
            return f"recursive delete inside .git ('{word}')"
        if target == root or under(root, target):
            return f"recursive delete of the repository root ('{word}')"
        if under(target, root) or any(under(target, t) for t in temp_roots()):
            continue
        return f"recursive delete outside the repository ('{word}' -> {target})"
    return None


def check_git(argv, cwd, opts):
    args = argv[1:]
    while args and args[0] in ("-C", "-c", "--git-dir", "--work-tree"):
        if args[0] == "-C" and len(args) > 1:
            cwd = expand(args[1], cwd)
        args = args[2:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if sub == "push":
        branches = protected_branches(cwd, opts)
        force = any(a in ("-f", "--force", "--force-with-lease", "--force-if-includes") or
                    a.startswith("--force-with-lease=") for a in rest)
        if "--mirror" in rest:
            return "push-protected", "git push --mirror"
        positional = [a for a in rest if not a.startswith("-")]
        refspecs = positional[1:] if len(positional) > 1 else []
        if not refspecs:
            current = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
            if current in branches:
                return "push-protected", f"push from '{current}', a protected branch: work on a branch and open a PR"
            return None
        delete = "--delete" in rest or "-d" in rest
        for spec in refspecs:
            plus = spec.startswith("+")
            dst = spec.lstrip("+").split(":")[-1].replace("refs/heads/", "")
            if spec.startswith(":"):
                delete = True
            if dst in branches or (dst == "HEAD" and git(cwd, "rev-parse", "--abbrev-ref", "HEAD") in branches):
                if delete:
                    return "push-protected", f"deleting the protected branch '{dst}'"
                if force or plus:
                    return "push-protected", f"force push to the protected branch '{dst}'"
                return "push-protected", f"push to the protected branch '{dst}': open a PR instead"
        return None
    def has_changes(untracked=False):
        return bool(git(cwd, "status", "--porcelain", "--untracked-files=" + ("all" if untracked else "no")))

    if sub == "clean":
        if any(re.match(r"^-[a-zA-Z]*[xX]", a) for a in rest):
            return "discard-work", "git clean -x/-X deletes ignored files such as .env and local data"
        if any(re.match(r"^-[a-zA-Z]*f", a) or a == "--force" for a in rest) and has_changes(untracked=True):
            return "discard-work", "git clean -f would delete untracked work"
        return None
    if sub == "reset" and "--hard" in rest and has_changes():
        return "discard-work", "git reset --hard would discard uncommitted changes"
    if sub in ("checkout", "restore") and any(a in (".", ":/", "--", "-f", "--force") for a in rest) \
            and ("." in rest or ":/" in rest) and "--staged" not in rest and has_changes():
        return "discard-work", f"git {sub} of the whole tree would discard uncommitted changes"
    if sub == "stash" and rest[:1] in (["drop"], ["clear"]):
        return "discard-work", f"git stash {rest[0]} deletes stashed work"
    return None


def check_system(argv, cwd, root):
    name = Path(argv[0]).name
    if name in ("sudo", "su", "doas"):
        return f"'{name}' runs as another user"
    if name.startswith("mkfs") or name in ("shutdown", "reboot", "halt", "poweroff", "fdisk"):
        return f"'{name}' changes the machine"
    if name == "diskutil" and any(a.lower().startswith("erase") or a in ("partitionDisk", "zeroDisk")
                                  for a in argv[1:]):
        return "diskutil erase"
    if name == "dd" and any(a.startswith("of=/dev/") for a in argv[1:]):
        return "dd to a device"
    if name in ("chmod", "chown", "chgrp") and any(f in ("-R", "--recursive") for f in argv[1:]):
        for word in [a for a in argv[2:] if not a.startswith("-")]:
            target = expand(word, cwd)
            if target == Path("/") or target == home() or not (under(target, root) or
                                                             any(under(target, t) for t in temp_roots())):
                return f"recursive {name} outside the repository ('{word}')"
    return None


def mentions_secret(text, cwd):
    hm = str(home())
    for raw in SECRET_PATHS:
        full = hm + raw[1:]
        if raw in text or full in text or raw.replace("~", "$HOME") in text:
            return raw
    if re.search(r"\bsecurity\s+(find|dump)-(generic|internet)-password|\bsecurity\s+dump-keychain", text):
        return "the macOS keychain"
    if re.search(r"(^|[\s/'\"])id_(rsa|ed25519|ecdsa)(\s|$|['\"])", text):
        return "an SSH private key"
    return None


def check_bash(command, cwd, root, opts):
    for pattern in opts.get("allowCommands") or []:
        try:
            if re.search(pattern, command):
                return None
        except re.error:
            continue
    secret = mentions_secret(command, cwd)
    if secret:
        return "secrets", f"reads {secret}"
    if re.search(r":\(\)\s*\{\s*:\|:&\s*\};\s*:", command):
        return "system", "fork bomb"
    if re.search(r">\s*/dev/(sd|disk|nvme|hd)", command):
        return "system", "write to a disk device"
    for seg in segments(command):
        argv = strip_wrappers(seg["argv"])
        if not argv:
            continue
        name = Path(argv[0]).name
        if seg["piped_from"] and name in SHELLS:
            src = strip_wrappers(seg["piped_from"])
            if src and Path(src[0]).name in DOWNLOADERS:
                return "pipe-to-shell", f"'{src[0]} ... | {name}' runs downloaded code"
        if name == "rm":
            why = check_rm(argv, cwd, root)
            if why:
                return "rm-outside", why
        elif name == "git":
            found = check_git(argv, cwd, opts)
            if found:
                return found
        else:
            why = check_system(argv, cwd, root)
            if why:
                return "system", why
    return None


def check_agents(data, opts):
    ask, deny = opts.get("agentsAsk"), opts.get("agentsDeny")
    if not isinstance(ask, int) and not isinstance(deny, int):
        return None
    session = data.get("session_id") or "nosession"
    count = int(kitlib.load_state(session, "guard-agents") or 0) + 1
    kitlib.save_state(session, "guard-agents", count)
    if isinstance(deny, int) and count > deny:
        return "deny", f"this session already started {count - 1} subagents (guard.agentsDeny = {deny})"
    if isinstance(ask, int) and count > ask:
        return "ask", f"subagent #{count} this session (guard.agentsAsk = {ask}); confirm to continue"
    return None


def main():
    data = kitlib.read_input()
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or os.getcwd())
    root = kitlib.git_root(cwd) or cwd
    root = Path(os.path.normpath(str(root)))
    active, opts = settings(root)
    if not active:
        return 0
    found = None
    if tool == "Bash":
        found = check_bash(str(tool_input.get("command") or ""), cwd, root, opts)
    elif tool in ("Read", "Grep", "Glob", "NotebookRead"):
        target = str(tool_input.get("file_path") or tool_input.get("path") or "")
        pattern = str(tool_input.get("pattern") or "")
        secret = mentions_secret(str(expand(target, cwd)) if target else "", cwd) or \
            (mentions_secret(pattern, cwd) if tool == "Glob" else None)
        if secret:
            found = ("secrets", f"reads {secret}")
    elif tool in ("Agent", "Task"):
        verdict = check_agents(data, opts)
        if verdict:
            decision, why = verdict
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": decision,
                "permissionDecisionReason": f"kit guard: {why}"}}))
            return 0
    if not found:
        return 0
    rule, why = found
    print(f"kit guard ({rule}): {why}. This is blocked by the kit's guardrails whatever the permission "
          "mode. Find a safer way (work inside the repo, on a branch, through a PR), or ask the user; "
          "they can allow a specific command with guard.allowCommands in .claude/kit.json.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
