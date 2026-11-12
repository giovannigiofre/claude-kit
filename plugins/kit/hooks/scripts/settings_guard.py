#!/usr/bin/env python3
"""PreToolUse (Write|Edit|MultiEdit|NotebookEdit|Bash|Monitor): changing a Claude Code settings
file always asks the owner.

The owner may have Claude change a settings file (say a permission rule), but only by approving
that exact change in Claude Code's own prompt. So an Edit, Write,
MultiEdit or NotebookEdit of a settings file, and a shell command that names one and is not a
plain read, gets permissionDecision "ask" in every permission mode. The reason starts
"Sovrascrittura dei settings di Claude Code:" and names the file and the change. From a subagent
(a background thread, where nobody sees the prompt) the answer is "deny", except a foreground
built-in such as statusline-setup, which gets "ask". The hook never answers "allow": deny rules,
the guard and Claude Code's own protection of these files still apply, and permission.py never
allows a command this hook flags. Any error, kitlib missing included, means "ask". It acts only in
a project with .claude/kit.json, like every kit hook, with one exception: the owner's unattended
answer (a repo's .claude/kit.local.json, and `items.py unattended …=allow`) is guarded in every
repo, since that answer is what lets permission.py approve git steps. Standard library only.

Settings files: settings*.json, in any case, in any `.claude` directory (the user's, a repo's, a
worktree's) or in CLAUDE_CONFIG_DIR, and the managed settings (managed-settings.json, or anything
in its folder). A Claude folder itself (`.claude/`, `~/.claude`, a glob in one) counts when the
part of the command naming it may write. This fails safe: any first word that is not known to leave
files alone counts, and the strings `bash -c` and `eval` run are judged too. A read, or a pipeline
of plain readers, never counts. A command with a word over 8 KB is not read (the hook must answer
inside its 10 s timeout, where Claude Code fails open): it asks if it mentions a Claude folder or
settings at all.
"""

import difflib
import fnmatch
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
# Names are looked for one word at a time (split at blanks, quotes and shell punctuation), with
# TOKEN.match at the word's start only: findall over the whole command was quadratic on one long
# word (a 20 KB base64 blob took 18 s, past the hook's 10 s timeout, where Claude Code fails open).
WORD = re.compile(r"[^\s'\"`;&|<>()]+")
TOKEN = re.compile(r"[^\s'\"`;&|<>()]*(?:managed-settings|settings[\w.*?\[\]-]*)\.json", re.I)
LONG_WORD = 8192  # a word longer than this is not read: the command asks if it names a Claude folder or settings
LONG_TARGET = "un comando con una parola troppo lunga da leggere"
LONG_HINT = re.compile(r"\.claude|claude_config_dir|settings|ClaudeCode", re.I)
# a Claude folder itself (`.claude`, `.claude/`, `~/.claude`, `$CLAUDE_CONFIG_DIR`, the macOS managed
# settings folder), or a glob in one; its prefix stops at `=`, so a word full of them stays linear
FOLDER = re.compile(r"(?:(?<=[\s'\"=])|^)((?:[^\s'\"`;&|<>()=]*/)?\.claude/?|\$\{?CLAUDE_CONFIG_DIR\}?/?"
                    r"|/Library/Application\\? Support/ClaudeCode/?"
                    r"|(?:[^\s'\"`;&|<>()=]*/)?\.claude/[^\s'\"`;&|<>()/]*[*?\[][^\s'\"`;&|<>()/]*)(?=$|[\s'\"`;&|<>()])",
                    re.I)
# plain readers (not sort or uniq, which can write an output file)
READERS = {"cat", "head", "tail", "less", "more", "grep", "rg", "wc", "ls", "stat", "file", "diff", "jq", "bat",
           "cut", "tr", "nl"}
GIT_READERS = {"diff", "log", "show", "status", "blame"}
# Fail-safe: a command that names a Claude folder counts as writing it unless every stage of its
# pipeline is known not to write a file. These first words never write one (a redirection is caught apart).
NON_WRITERS = READERS | {"true", "false", "test", "[", "echo", "printf", "pwd", "cd", "pushd", "popd", "which",
                         "type", "mkdir", "for", "select", "in", "fi", "done", "esac", "}", ")", ";;"}
# git subcommands that leave the working tree's files alone (checkout, restore, stash, reset... do not)
GIT_SAFE = GIT_READERS | {"add", "commit", "push", "fetch", "branch", "tag", "worktree", "rev-parse", "ls-files",
                          "ls-tree", "config", "remote", "grep", "describe", "shortlog", "reflog", "cat-file",
                          "check-ignore", "notes", "rev-list", "merge-base", "for-each-ref", "show-ref", ""}
# known writers (anything not in NON_WRITERS counts anyway; these are named for the reader)
WRITERS = {"cp", "mv", "rsync", "tee", "ln", "install", "rm", "rmdir", "unlink", "truncate", "touch", "dd", "tar",
           "unzip", "patch", "ditto", "scp", "cpio"}
WRAPPERS = {"sudo", "doas", "command", "builtin", "env", "nohup", "time", "xargs", "exec", "nice", "ionice",
            "timeout", "stdbuf", "caffeinate"}
# words that open a compound command or a block: the command proper follows them
OPENERS = {"(", "{", "!", "if", "then", "do", "else", "elif", "while", "until"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
HARMLESS = re.compile(r"\s*(?:[0-9]*>>?|&>)\s*/dev/null|\s*[0-9]*>&[0-9]")  # 2>&1, >/dev/null
SEGMENTS = re.compile(r"\|\||&&|[;|&\n]")
PIPELINES = re.compile(r"\|\||&&|[;&\n]")
# `cd .claude`, `pushd ~/.claude/`, `cd "$CLAUDE_CONFIG_DIR"`: a bare settings name after it is in a Claude folder
CD_CLAUDE = re.compile(r"(?:^|[;&|(]|\s)(?:cd|pushd)\s+['\"]?(?:[^\s'\";&|]*/)?(?:\.claude|\$\{?CLAUDE_CONFIG_DIR\}?)/?['\"]?"
                       r"(?=$|[\s;&|)])", re.I)


def _argv(segment):
    """The words of one simple command: block openers (`(`, `{`, `then`, `do`...), wrappers (`sudo`,
    `env X=1`, `xargs -0`, `timeout 10`, `nice -n 5`) and assignments skipped."""
    words = shlex.split(segment)
    while words:
        first = words[0]
        if first[:1] in "({" and len(first) > 1:  # `(cp` and `{cp` as shlex leaves them
            words = [first[1:]] + words[1:]
        elif (first in OPENERS or first in WRAPPERS or re.fullmatch(r"\w+=.*", first) or
              re.fullmatch(r"\d+(?:\.\d+)?[smhd]?", first) or (first.startswith("-") and len(words) > 1)):
            words = words[1:]
        else:
            break
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


def _segment_writes(segment, depth):
    try:
        argv = _argv(segment)
    except ValueError:
        return True  # unbalanced quotes: cannot tell, so it may write
    if not argv:
        return False
    name = os.path.basename(argv[0])
    if name in WRITERS:
        return True
    if name in SHELLS or name == "eval":  # judge the string it runs: `bash -c '…'`, `eval '…'`
        flag = next((i for i, a in enumerate(argv[1:-1], 1) if re.fullmatch(r"-\w*c\w*", a)), None)
        if name == "eval":
            inner = " ".join(argv[1:])
        elif flag is not None:
            inner = argv[flag + 1]
        else:
            return True  # a shell reading a script or stdin: cannot tell
        return depth >= 3 or writes(inner, depth + 1)
    if name == "git":
        return _git_sub(argv) not in GIT_SAFE
    if name in ("sed", "perl", "ruby"):  # in place, or running code: perl -e/-E, ruby -e
        return any(a.startswith("-i") or a == "--in-place" or
                   (name != "sed" and re.fullmatch(r"-\w*[eE]\w*", a)) for a in argv[1:])
    if name == "find":
        return any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls")
                   for a in argv[1:])
    return name not in NON_WRITERS


def writing_parts(command, depth=0):
    """The parts of the command (pipelines, split at `;`, `&&`, `||`, `&`) that may write a file.
    Fail-safe: a stage counts as writing unless its first word is known not to write (a reader,
    echo, mkdir, a block keyword, git status/add/commit...). A redirection or a substitution
    anywhere makes the whole command count."""
    text = HARMLESS.sub(" ", command)
    if ">" in text or "`" in text or "$(" in text:
        return [command]
    return [part for part in PIPELINES.split(text)
            if any(_segment_writes(stage, depth) for stage in part.split("|"))]


def writes(command, depth=0):
    """True when some part of the command may write a file (see writing_parts)."""
    return bool(writing_parts(command, depth))


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
    worktree below `.claude/worktrees/` is not one. A Claude folder itself counts where it is named by a
    part that may write (see writing_parts), or anywhere once the command cds into it and writes.
    A plain read, or a pipeline of plain readers, changes nothing."""
    files, folders = [], []
    if any(len(w) > LONG_WORD for w in WORD.findall(command)):
        return [LONG_TARGET] if LONG_HINT.search(command) else []
    plain = re.sub(r"\$'|[\\'\"]", "", command)
    parts = writing_parts(command)
    cd_claude = any(CD_CLAUDE.search(c) for c in (command, plain))
    into = cd_claude or (parts and any(".claude" in c.lower() or "claude_config_dir" in c.lower() for c in (command, plain)))
    # the folder counts where a writing part names it, or anywhere once the command cds into it and writes
    written = [command] if (cd_claude and parts) else parts
    for text in (command, plain):
        for token in dict.fromkeys(m.group() for m in map(TOKEN.match, WORD.findall(text)) if m):
            bare = "/" not in token and "~" not in token and "$" not in token
            if is_settings(token, cwd) or (bare and into):
                files.append(token)
    for part in written:
        for text in (part, re.sub(r"\$'|[\\'\"]", "", part)):
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


ALLOW_STEP = re.compile(r"\bunattended\b.*\b(?:push|rebase|merge)\s*=\s*['\"]?allow\b", re.I | re.S)
GLOB = re.compile(r"[*?\[]")
LOCAL = "kit.local.json"


def is_local(path, cwd):
    """True for a repo's .claude/kit.local.json, where the owner's unattended answer lives."""
    return any(p.name.lower() == LOCAL and p.parent.name.lower() == ".claude" for p in _forms(path, cwd))


def _words(command):
    """The command's words as the shell passes them, quotes and backslashes taken out (`al''low`,
    `al\\low` and `a"llow"` are all `allow`), plus the words with every quote character simply
    dropped (`$'…'`, unbalanced quotes)."""
    out = []
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split, lex.commenters = True, ""
        out = list(lex)
    except ValueError:
        pass
    return out + re.sub(r"\$'|[\\'\"]", "", command).split()


def _braces(word, room=64):
    """`kit.local.{json,x}` as the shell expands it (one brace at a time, at most `room` words)."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", word)
    if not m:
        return [word]
    out = []
    for alt in m.group(1).split(","):
        out += _braces(word[:m.start()] + alt + word[m.end():], room)
        if len(out) >= room:
            break
    return out[:room]


def _names_local(word):
    """True when a word names kit.local.json, or is a glob or brace form the shell may expand to it
    (`.claude/kit.loc*.json`, `kit.local.{json,bak}`, `.claude/*`); a bare glob counts only with
    three letters of its own (`*.json`, not `*`)."""
    for w in _braces(word.lower()):
        if LOCAL in w:
            return True
        head, _, base = w.rpartition("/")
        if not GLOB.search(base) or not fnmatch.fnmatchcase(LOCAL, base):
            continue
        if head:
            if fnmatch.fnmatchcase(".claude", head.rsplit("/", 1)[-1]):
                return True
        elif len(re.sub(r"\[[^\]]*\]|[*?]", "", base)) >= 3:
            return True
    return False


def _sets_unattended(words):
    """`items.py unattended push=allow` (or the `I` function) in any spelling: a `step=value` word
    after `unattended` whose value is not `ask` (only `ask` can be saved without the owner)."""
    low = [w.lower() for w in words]
    for i, w in enumerate(low):
        if w == "unattended" and any("=" in a and a.partition("=")[2] != "ask" for a in low[i + 1:]):
            return True
    return False


def local_targets(command):
    """The owner's unattended answer, as a command may change it: `items.py unattended push=allow`
    (or the `I` shell function), or a command that names kit.local.json (a glob or brace form
    included) and is not a plain read. Quotes and backslashes are seen through."""
    out = []
    if read_only(command):
        return out
    words = _words(command)
    if ALLOW_STEP.search(command) or _sets_unattended(words):
        out.append("kit.local.json (unattended …=allow)")
    named = any(LOCAL in w.lower() for w in words)
    if named or any(_names_local(w) for part in writing_parts(command) for w in _words(part)):  # a glob where it may write
        out.append(".claude/kit.local.json")
    return out


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
    opted = opted_in(cwd)  # the unattended answer is guarded everywhere: it is the opt-in on its own
    if tool in ("Bash", "Monitor"):
        command = str(inp.get("command") or "")
        targets = (command_targets(command, cwd) if opted else []) + local_targets(command)
        if not targets:
            return None
        where = ", ".join(dict.fromkeys(shown(t) for t in targets))
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path")
        if not path or not ((opted and is_settings(path, cwd)) or is_local(path, cwd)):
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
