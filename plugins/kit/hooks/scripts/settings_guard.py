#!/usr/bin/env python3
"""PreToolUse (Write|Edit|MultiEdit|NotebookEdit|Bash|Monitor): changing a Claude Code settings
file always asks the owner.

The owner may have Claude change a settings file (say the PROPOSAL `items.py unattended`
prints), but only by approving that exact change in Claude Code's own prompt. So an Edit, Write,
MultiEdit or NotebookEdit of a settings file, and a shell command that names one and is not a
plain read, gets permissionDecision "ask" in every permission mode. The reason starts
"Sovrascrittura dei settings di Claude Code:" and names the file and the change. From a subagent
(a background thread, where nobody sees the prompt) the answer is "deny", except a foreground
built-in such as statusline-setup, which gets "ask". The hook never answers "allow": deny rules,
the guard and Claude Code's own protection of these files still apply, and permission.py never
allows a command this hook flags. Any error, kitlib missing included, means "ask". It acts only in
a project with .claude/kit.json, like every kit hook. Standard library only.

Settings files: settings*.json, in any case, in any `.claude` directory (the user's, a repo's, a
worktree's) or in CLAUDE_CONFIG_DIR, and the managed settings (managed-settings.json, or anything
in its folder). A shell command that writes (cp, mv, rsync, tee, ln, a redirection, git checkout
or restore...) into a Claude folder itself (`.claude/`, `~/.claude`, a glob in one) counts too; a
read, or a pipeline of plain readers, never does.
"""

import difflib
import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import kitlib  # noqa: E402
except Exception:  # without it nothing can be judged: main() asks (fail closed)
    kitlib = None

LABEL = "Sovrascrittura dei settings di Claude Code:"
NAME = re.compile(r"settings[\w.*?\[\]-]*\.json", re.I)
TOKEN = re.compile(r"[^\s'\"`;&|<>()]*(?:managed-settings|settings[\w.*?\[\]-]*)\.json", re.I)
# a Claude folder itself (`.claude`, `.claude/`, `~/.claude`, `$CLAUDE_CONFIG_DIR`), or a glob in one
FOLDER = re.compile(r"(?:(?<=[\s'\"=])|^)((?:[^\s'\"`;&|<>()]*/)?\.claude/?|\$\{?CLAUDE_CONFIG_DIR\}?/?"
                    r"|(?:[^\s'\"`;&|<>()]*/)?\.claude/[^\s'\"`;&|<>()/]*[*?\[][^\s'\"`;&|<>()/]*)(?=$|[\s'\"`;&|<>()])",
                    re.I)
# plain readers (not sort or uniq, which can write an output file)
READERS = {"cat", "head", "tail", "less", "more", "grep", "rg", "wc", "ls", "stat", "file", "diff", "jq", "bat",
           "cut", "tr", "nl"}
GIT_READERS = {"diff", "log", "show", "status", "blame"}
# commands that write files: a Claude folder named by one of these counts as a target
WRITERS = {"cp", "mv", "rsync", "tee", "ln", "install", "rm", "rmdir", "unlink", "truncate", "touch", "dd", "tar",
           "unzip", "patch", "ditto", "scp"}
GIT_WRITERS = {"checkout", "restore", "stash", "reset", "apply", "am", "mv", "rm", "clean", "switch", "merge", "pull",
               "rebase", "cherry-pick", "revert"}
WRAPPERS = {"sudo", "command", "env", "nohup", "time", "xargs", "exec"}
HARMLESS = re.compile(r"\s*(?:[0-9]*>>?|&>)\s*/dev/null|\s*[0-9]*>&[0-9]")  # 2>&1, >/dev/null
SEGMENTS = re.compile(r"\|\||&&|[;|&\n]")
# `cd .claude`, `pushd ~/.claude/`, `cd "$CLAUDE_CONFIG_DIR"`: a bare settings name after it is in a Claude folder
CD_CLAUDE = re.compile(r"(?:^|[;&|(]|\s)(?:cd|pushd)\s+['\"]?(?:[^\s'\";&|]*/)?(?:\.claude|\$\{?CLAUDE_CONFIG_DIR\}?)/?['\"]?"
                       r"(?=$|[\s;&|)])", re.I)


def _argv(segment):
    """The words of one simple command, wrappers (`sudo`, `env X=1`, `xargs -0`) and assignments skipped."""
    words = shlex.split(segment)
    while words and (words[0] in WRAPPERS or re.fullmatch(r"\w+=.*", words[0]) or
                     (words[0].startswith("-") and len(words) > 1)):
        words = words[1:]
    return words


def _git_sub(argv):
    rest, skip = argv[1:], False
    for word in rest:
        if skip:
            skip = False
        elif word in ("-C", "-c", "--git-dir", "--work-tree"):
            skip = True
        elif not word.startswith("-"):
            return word
    return ""


def writes(command):
    """True when the command may write a file: a redirection, or a writer (cp, mv, rsync, tee, ln,
    rm, sed -i, find -delete/-exec, git checkout/restore/stash/...) in any of its parts."""
    text = HARMLESS.sub(" ", command)
    if ">" in text or "`" in text or "$(" in text:
        return True
    for segment in SEGMENTS.split(text):
        try:
            argv = _argv(segment)
        except ValueError:
            return True  # unbalanced quotes: cannot tell, so it may write
        if not argv:
            continue
        name = os.path.basename(argv[0])
        if name in WRITERS:
            return True
        if name in ("sed", "perl", "ruby") and any(a.startswith("-i") or a == "--in-place" for a in argv[1:]):
            return True
        if name == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint") for a in argv[1:]):
            return True
        if name == "git" and _git_sub(argv) in GIT_WRITERS:
            return True
    return False


# Subagents that run in the foreground, where the owner sees the prompt (the hook input does not
# say whether an agent runs in the background): Claude Code's statusline-setup edits
# ~/.claude/settings.json by design. Every other subagent (the kit's threads, background agents) is refused.
FOREGROUND_AGENTS = {"statusline-setup"}


def _forms(path, cwd):
    p = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not p.is_absolute():
        p = Path(cwd or ".") / p
    forms = [Path(os.path.normpath(str(p)))]
    try:
        forms.append(p.resolve())
    except (OSError, RuntimeError):
        pass
    return forms


def is_settings(path, cwd):
    """True when `path` (as a tool or command names it, relative to `cwd`) is a Claude Code settings file."""
    config = [Path(os.path.normpath(str(kitlib.config_dir())))]
    managed = kitlib.managed_settings().parent
    for p in _forms(path, cwd):
        if p.name.lower() == "managed-settings.json" or managed in p.parents:
            return True
        if NAME.fullmatch(p.name) and (p.parent.name.lower() == ".claude" or p.parent in config
                                       or any(p.parent == c.resolve() for c in config)):
            return True
    return False


def read_only(command):
    """Plain reads only: one reader, or a pipeline of readers (`cat x | jq .`), with no
    redirection, chain or substitution."""
    text = HARMLESS.sub(" ", command)
    if any(ch in text for ch in "><;&`\n") or "$(" in text:
        return False
    for segment in text.split("|"):
        try:
            argv = shlex.split(segment)
        except ValueError:
            return False
        if not argv:
            return False
        if argv[0] == "git":
            if _git_sub(argv) not in GIT_READERS:
                return False
        elif argv[0] not in READERS:
            return False
    return True


def command_targets(command, cwd):
    """The settings files, or Claude folders, a shell command changes. Quotes and backslashes inside
    a name (`.claude/'settings'.json`, `settings\\.json`) are seen through, and names match in any
    case. A bare `settings.json` counts when it is in a Claude folder: the cwd is one, the command
    `cd`s into one, or it writes and names one (`find .claude -name settings.json -delete`); a
    worktree below `.claude/worktrees/` is not one. A Claude folder itself counts only for a
    command that writes. A plain read, or a pipeline of plain readers, changes nothing."""
    files, folders = [], []
    plain = re.sub(r"\$'|[\\'\"]", "", command)
    writer = writes(command)
    into = any(CD_CLAUDE.search(c) for c in (command, plain)) or \
        (writer and any(".claude" in c.lower() or "claude_config_dir" in c.lower() for c in (command, plain)))
    for text in (command, plain):
        for token in TOKEN.findall(text):
            bare = "/" not in token and "~" not in token and "$" not in token
            if is_settings(token, cwd) or (bare and into):
                files.append(token)
        if writer:
            folders += FOLDER.findall(text)
    if files and read_only(command):
        files = []
    return list(dict.fromkeys(files + folders))


MAX_REASON = 220  # Claude Code's permission prompt shows it whole: keep it to two short lines


def shown(path):
    """The path as the owner reads it: the home folder as ~."""
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if home and (text == home or text.startswith(home + os.sep)) else text


def snip(text, n=40):
    one = " ".join(str(text).split())
    return f"«{one[:n]}…»" if len(one) > n else f"«{one}»"


def summary(tool, inp, path):
    if tool == "Edit":
        every = " (ogni occorrenza)" if inp.get("replace_all") else ""
        return f"sostituisce {snip(inp.get('old_string', ''))} con {snip(inp.get('new_string', ''))}{every}"
    if tool == "MultiEdit":
        edits = inp.get("edits") or []
        first = edits[0] if edits else {}
        return (f"{len(edits)} modifiche; la prima sostituisce {snip(first.get('old_string', ''))} "
                f"con {snip(first.get('new_string', ''))}")
    if tool == "Write":
        new = str(inp.get("content", "")).splitlines()
        try:
            old = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return f"crea il file ({len(new)} righe)"
        diff = list(difflib.unified_diff(old, new, lineterm="", n=0))
        plus = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        minus = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        return f"riscrive l'intero file (+{plus}/-{minus} righe)"
    if tool == "NotebookEdit":
        return "modifica come notebook"
    return f"comando {snip(inp.get('command', ''), 80)}"


def opted_in(cwd):
    """Like every kit hook, this one acts only in a project with .claude/kit.json, the worktree's or
    its main checkout's (a broken one counts)."""
    root = kitlib.git_root(cwd) or Path(cwd)  # the session's own checkout, never this process's cwd
    return kitlib.config_file(root).is_file()


def decide(data):
    """(decision, reason), or None to leave the call to everything else."""
    tool = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if not opted_in(cwd):
        return None
    if tool in ("Bash", "Monitor"):
        targets = command_targets(str(inp.get("command") or ""), cwd)
        if not targets:
            return None
        where = ", ".join(dict.fromkeys(shown(t) for t in targets))
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path")
        if not path or not is_settings(path, cwd):
            return None
        target = _forms(path, cwd)[0]
        where = shown(target)
    else:
        return None
    change = summary(tool, inp, target if tool == "Write" else None)
    if data.get("agent_id") and str(data.get("agent_type") or "") not in FOREGROUND_AGENTS:
        return "deny", (f"{LABEL} {where}: {change}. Rifiutata da un subagent (thread in background), dove nessuno "
                        "vede la richiesta: solo la sessione principale, su richiesta del proprietario.")
    head = f"{LABEL} {where}: "
    tail = ". Approva solo se l'hai chiesta tu."
    room = MAX_REASON - len(head) - len(tail)
    return "ask", head + (change if len(change) <= room else change[:max(room - 1, 20)] + "…") + tail


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if kitlib is None:
            raise ImportError("kitlib")
        result = decide(data) if isinstance(data, dict) else None
    except Exception as exc:  # fail closed: the owner decides
        result = "ask", f"{LABEL} controllo non riuscito ({type(exc).__name__}); approva solo se sai cosa cambia questa chiamata."
    if result:
        decision, reason = result
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
