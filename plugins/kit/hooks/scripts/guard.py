#!/usr/bin/env python3
"""PreToolUse (Bash|Read|Grep|Glob|Agent|Task|GitHub MCP tools): deterministic guardrails, best effort.

A rule in a prompt is a preference; a rule in a hook is checked every time. This hook blocks the
few actions that cannot be undone or that leak credentials, whatever the permission mode
(default, auto, or a headless overnight iteration), and leaves the rest to the permission
system. It reads shell text, so it is a guardrail, not a boundary: an obfuscated command can
slip past it. The OS boundary is the Bash sandbox (the kit's "Sandbox" safety profile).

  rm-outside       recursive delete (rm -r, find -delete/-exec rm, rmtree in python -c ...) of
                   /, the home folder, the repo root, .git, or anything outside the repo, the
                   repo's other registered worktrees (a linked one may go whole), the temp
                   folders and the cache folders; a target known only at run time ($VAR,
                   $(...), xargs) is asked about
  push-protected   a push to a protected branch (main, master, the remote's default), a force
                   push to one, a mirror push, or deleting one
  discard-work     git reset --hard, checkout/restore of the whole tree, clean, stash drop/clear
                   while there are uncommitted changes; git clean -x/-X always
  system           sudo/su/doas, mkfs, dd to a device, disk erase, shutdown/reboot, recursive
                   chmod/chown outside the repo
  pipe-to-shell    a download piped into a shell or interpreter (curl ... | sh)
  secrets          reading credential stores (~/.ssh, ~/.aws, gh/docker/kube config, .netrc,
                   ~/.gnupg, the macOS keychain) with Bash, Read, Grep or Glob, symlinks resolved
  agents           optional cap on subagents per session (guard.agentsAsk / guard.agentsDeny)
  attribution      the user is the only author: an AI credited in a commit message, a PR, an
                   issue or a comment (Co-Authored-By: Claude, "Generated with Claude Code", a
                   claude.ai session link), a commit made under an AI git identity, or git's
                   identity set to one, by git, gh or a GitHub MCP tool;
                   guard.attribution = "allow" turns this rule off

Multi-line commands, subshells, braces, if/for/while bodies, $(...) and backticks, sh -c and
`cd` within one command are followed.

Active when the project has .claude/kit.json (unless its "guard" is "off"), or everywhere when
~/.claude/kit.json says "guard": "on". Options, under "guard" in either file:
  {"protectedBranches": ["main", "master"], "agentsAsk": 15, "agentsDeny": 40,
   "allowCommands": ["^rm -rf /opt/my-build$"], "attribution": "block"}
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

SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh"}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "deno", "bun"}
DOWNLOADERS = {"curl", "wget", "fetch", "http", "https"}
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "nice", "env", "xargs", "timeout", "caffeinate"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "{", "}", "!", "case",
            "esac", "function", "select"}
SECRET_PATHS = ["~/.ssh", "~/.aws", "~/.config/gh", "~/.netrc", "~/.docker/config.json",
                "~/.kube/config", "~/.gnupg", "~/Library/Keychains", "~/.git-credentials",
                "~/.config/gcloud", "~/.azure"]
CACHE_PATHS = ["~/.cache", "~/Library/Caches", "~/.npm/_cacache", "~/.cargo/registry/cache"]
UNKNOWN = object()


def home():
    return Path(os.path.normpath(os.environ.get("HOME") or str(Path.home())))


def expand(word, cwd):
    """A path for a shell word, or UNKNOWN when it depends on run-time values."""
    w = word
    for var in ("${HOME}", "$HOME"):
        w = w.replace(var, str(home()))
    for var in ("${PWD}", "$PWD", "$(pwd)", "`pwd`"):
        w = w.replace(var, str(cwd))
    for var in ("${TMPDIR}", "$TMPDIR"):
        w = w.replace(var, tempfile.gettempdir())
    if "$" in w or "`" in w:
        return UNKNOWN
    if w == "~" or w.startswith("~/"):
        w = str(home()) + w[1:]
    p = Path(w)
    if not p.is_absolute():
        p = Path(cwd) / p
    return Path(os.path.normpath(str(p)))


def tilde(paths):
    return [Path(os.path.normpath(str(home()) + p[1:])) for p in paths]


def temp_roots():
    roots = {"/tmp", "/private/tmp", "/var/folders", "/private/var/folders", tempfile.gettempdir()}
    return [Path(os.path.normpath(r)) for r in roots]


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
    user_guard = user.get("guard")
    if isinstance(project, dict):
        g = project.get("guard", user_guard)
        if g == "off":
            return False, {}
        if isinstance(g, dict):
            return True, g
        return True, user_guard if isinstance(user_guard, dict) else {}
    if user_guard == "on" or isinstance(user_guard, dict):
        return True, user_guard if isinstance(user_guard, dict) else {}
    return False, {}


# ---------------------------------------------------------------- shell parsing

def substitutions(text):
    """The bodies of $(...) and `...` in a line, nested ones included."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("$(", i) and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            body = text[i + 2:j - 1]
            out.append(body)
            out.extend(substitutions(body))
            i = j
        elif text[i] == "`":
            j = text.find("`", i + 1)
            if j == -1:
                break
            out.append(text[i + 1:j])
            i = j + 1
        else:
            i += 1
    return out


def tokenize(line):
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = "#"
        return list(lex)
    except ValueError:
        return line.split()


def strip_wrappers(argv):
    argv = list(argv)
    while argv:
        name = Path(argv[0]).name
        if argv[0] in KEYWORDS:
            argv = argv[1:]
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
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


def segments(command):
    """Simple commands of a shell text, in order: lines, ; && || | & ( ) and braces split them,
    keywords and redirections are dropped, $(...), backticks and sh -c bodies are followed."""
    text = command.replace("\\\n", " ")
    out = []
    heredoc = None
    for line in text.split("\n"):
        if heredoc is not None:
            if line.strip() == heredoc:
                heredoc = None
            continue  # the body of a here-document is data, not commands
        if not line.strip():
            continue
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            heredoc = m.group(1)
        for body in substitutions(line):
            out.extend(segments(body))
        cur, pipe_from, skip = [], None, False
        for tok in tokenize(line) + [";"]:
            if skip:
                skip = False
                continue
            if tok and set(tok) <= set("<>"):
                skip = True  # the redirection's target is a file, not an argument
                continue
            if tok and set(tok) <= set(";&|()"):
                argv = strip_wrappers(cur)
                if argv:
                    out.append({"argv": argv, "piped_from": pipe_from})
                pipe_from = argv if tok == "|" else None
                cur = []
            else:
                cur.append(tok)
    nested = []
    for seg in out:
        argv = seg["argv"]
        if Path(argv[0]).name in SHELLS and "-c" in argv[1:-1]:
            nested.extend(segments(argv[argv.index("-c") + 1]))
    return out + nested


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


# ---------------------------------------------------------------- the checks
# Each returns None, or (decision, rule, why) with decision "deny" or "ask".

def delete_target(word, cwd, root):
    if word in (".", "..", ".*", "/*", "~/*", "*") and Path(cwd) in (Path("/"), home()):
        return ("deny", f"delete of '{word}' in {cwd}")
    if word in ("..", ".*") or word.endswith("/.."):
        return ("deny", f"delete of '{word}'")
    target = expand(word, cwd)
    if target is UNKNOWN:
        return ("ask", f"delete target '{word}' is only known when the command runs")
    hm = home()
    if any(under(target, c) for c in tilde(CACHE_PATHS)):
        return None
    if target == Path("/") or target == hm or under(hm, target):
        return ("deny", f"delete of '{word}' ({target})")
    if target.name == ".git" or (under(target, root) and "/.git/" in str(target) + "/"):
        return ("deny", f"delete inside .git ('{word}')")
    if target == root or under(root, target):
        return ("deny", f"delete of the repository root ('{word}')")
    if under(target, root) or any(under(target, t) for t in temp_roots()):
        return None
    if in_sibling_worktree(target, root):
        return None
    return ("deny", f"delete outside the repository ('{word}' -> {target})")


def in_sibling_worktree(target, root):
    """True when target is in another worktree registered to this repository (a thread's checkout
    next to this one): anything inside one, or a linked one as a whole; never the main
    checkout's root, nor anything in a .git."""
    listing = git(root, "worktree", "list", "--porcelain")
    entries = [block.splitlines() for block in listing.split("\n\n") if block.startswith("worktree ")]
    trees = [None if "bare" in lines else Path(os.path.normpath(lines[0][len("worktree "):]))
             for lines in entries]  # a bare repository's directory is all history: never a worktree
    for i, tree in enumerate(trees):
        if tree is None:
            continue
        for t in {target, Path(os.path.realpath(str(target)))}:
            if t == tree:
                if i > 0:  # the first entry is the main checkout
                    return True
            elif under(t, tree) and ".git" not in t.relative_to(tree).parts:
                return True
    return False


def check_rm(argv, cwd, root):
    flags = [a for a in argv[1:] if a.startswith("-")]
    recursive = any(f in ("-r", "-R", "--recursive") or (not f.startswith("--") and ("r" in f or "R" in f))
                    for f in flags)
    if not recursive:
        return None
    targets = [a for a in argv[1:] if not a.startswith("-")]
    if not targets:
        return ("ask", "rm-outside", "recursive delete whose targets come from input (xargs or similar)")
    for word in targets:
        found = delete_target(word, cwd, root)
        if found:
            return (found[0], "rm-outside", f"recursive {found[1]}")
    return None


def check_find(argv, cwd, root):
    deletes = "-delete" in argv or any(
        a in ("-exec", "-execdir", "-ok") and i + 1 < len(argv) and Path(argv[i + 1]).name in ("rm", "rmdir", "shred")
        for i, a in enumerate(argv))
    if not deletes:
        return None
    paths = []
    for a in argv[1:]:
        if a.startswith("-") or a in ("(", "!", ")"):
            break
        paths.append(a)
    for word in paths or ["."]:
        target = expand(word, cwd)
        if target is not UNKNOWN and (target == root or under(target, root)) and ".git" not in target.parts:
            continue  # find deletes what matches below the path, not the path itself
        found = delete_target(word, cwd, root)
        if found:
            return (found[0], "rm-outside", f"find deleting: {found[1]}")
    return None


def check_interpreter(argv):
    name = Path(argv[0]).name
    if name not in INTERPRETERS:
        return None
    code = " ".join(argv[argv.index(f) + 1] for f in ("-c", "-e", "--eval") if f in argv[:-1])
    if not code:
        return None
    if re.search(r"rmtree|rmSync|rm_rf|remove_dir_all|rimraf|\brm\s+-[a-zA-Z]*r", code) and \
            re.search(r"expanduser|Path\.home|homedir\(|environ\[.HOME|getenv\(.HOME|ENV\[.HOME|['\"]~|['\"]/['\"]",
                      code):
        return ("deny", "rm-outside", f"{name} code deleting the home folder or /")
    if secret_word(code):
        return ("deny", "secrets", f"{name} code reading {secret_word(code)}")
    return None


def check_git(argv, cwd, opts):
    args = argv[1:]
    while args and args[0] in ("-C", "-c", "--git-dir", "--work-tree"):
        if args[0] == "-C" and len(args) > 1:
            target = expand(args[1], cwd)
            cwd = cwd if target is UNKNOWN else target
        args = args[2:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if sub == "push":
        branches = protected_branches(cwd, opts)
        force = any(a in ("-f", "--force", "--force-with-lease", "--force-if-includes") or
                    a.startswith("--force-with-lease=") for a in rest)
        if "--mirror" in rest:
            return ("deny", "push-protected", "git push --mirror")
        positional = [a for a in rest if not a.startswith("-")]
        refspecs = positional[1:] if len(positional) > 1 else []
        current = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        if not refspecs:
            if current in branches:
                return ("deny", "push-protected",
                        f"push from '{current}', a protected branch: work on a branch and open a PR")
            return None
        delete = "--delete" in rest or "-d" in rest
        for spec in refspecs:
            plus = spec.startswith("+")
            dst = re.sub(r"^refs/heads/", "", spec.lstrip("+").split(":")[-1])
            if spec.startswith(":"):
                delete = True
            if dst in branches or (dst == "HEAD" and current in branches):
                if delete:
                    return ("deny", "push-protected", f"deleting the protected branch '{dst}'")
                if force or plus:
                    return ("deny", "push-protected", f"force push to the protected branch '{dst}'")
                return ("deny", "push-protected", f"push to the protected branch '{dst}': open a PR instead")
        return None

    def has_changes(untracked=False):
        return bool(git(cwd, "status", "--porcelain", "--untracked-files=" + ("all" if untracked else "no")))

    if sub == "clean":
        if any(re.match(r"^-[a-zA-Z]*[xX]", a) for a in rest):
            return ("deny", "discard-work", "git clean -x/-X deletes ignored files such as .env and local data")
        if any(re.match(r"^-[a-zA-Z]*f", a) or a == "--force" for a in rest) and has_changes(untracked=True):
            return ("deny", "discard-work", "git clean -f would delete untracked work")
        return None
    if sub == "reset" and "--hard" in rest and has_changes():
        return ("deny", "discard-work", "git reset --hard would discard uncommitted changes")
    if sub in ("checkout", "restore") and ("." in rest or ":/" in rest) and "--staged" not in rest \
            and has_changes():
        return ("deny", "discard-work", f"git {sub} of the whole tree would discard uncommitted changes")
    if sub == "stash" and rest[:1] in (["drop"], ["clear"]):
        return ("deny", "discard-work", f"git stash {rest[0]} deletes stashed work")
    return None


AI_CREDIT = re.compile(
    r"co-authored-by:[^\n]*(?:claude|anthropic\.com)"
    r"|generated (?:with|by) \[?claude"
    r"|claude-session:"
    r"|claude\.ai/code/session_",
    re.I,
)
AI_NAMES = {"claude", "claude code", "claude[bot]", "claude-code"}
COMMIT_SUBS = {"commit", "merge", "tag", "notes", "commit-tree", "cherry-pick", "revert", "am"}
MAKES_COMMIT = {"commit", "merge", "commit-tree", "cherry-pick", "revert", "am"}
GH_WRITES = {"pr", "issue", "release", "api", "gist"}
NO_AI = ("the user is the only author of commits, PRs and comments: no AI co-author trailer, no "
         "\"Generated with\" footer, no session link")


def is_ai_identity(text):
    """'Name <email>', a bare name or a bare email that belongs to an AI, not to a person."""
    m = re.match(r"^\s*(.*?)\s*<([^>]*)>\s*$", text or "")
    name, email = (m.group(1), m.group(2)) if m else ((text or "").strip(), "")
    if "@" in name and not email:
        name, email = "", name
    return name.strip().lower() in AI_NAMES or email.strip().lower().endswith("anthropic.com")


def message_files(args, cwd):
    """The text of the message or body files a command names (-F, --file, --body-file)."""
    texts = []
    for i, a in enumerate(args):
        path = None
        if a in ("-F", "--file", "--body-file") and i + 1 < len(args):
            path = args[i + 1]
        elif a.startswith(("--file=", "--body-file=")):
            path = a.split("=", 1)[1]
        if path and path != "-":
            target = expand(path, cwd)
            if target is not UNKNOWN:
                try:
                    texts.append(Path(target).read_text(encoding="utf-8", errors="replace")[:200_000])
                except Exception:
                    pass
    return texts


def check_attribution(argv, cwd, command):
    name, args = Path(argv[0]).name, argv[1:]
    if name == "gh":
        if args and args[0] in GH_WRITES and any(AI_CREDIT.search(t) for t in [command] + message_files(args, cwd)):
            return ("deny", "attribution", f"gh {args[0]} text credits an AI; {NO_AI}")
        return None
    while args and args[0] in ("-C", "-c", "--git-dir", "--work-tree"):
        if args[0] == "-C" and len(args) > 1:
            target = expand(args[1], cwd)
            cwd = cwd if target is UNKNOWN else target
        args = args[2:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if sub == "config":
        values = [a for a in rest if not a.startswith("-")]
        if len(values) >= 2 and values[0] in ("user.name", "user.email") and is_ai_identity(values[1]):
            return ("deny", "attribution", f"sets git's {values[0]} to an AI; {NO_AI}")
        return None
    if sub not in COMMIT_SUBS:
        return None
    # a here-document holding the message is part of the command text
    if any(AI_CREDIT.search(t) for t in [command] + message_files(rest, cwd)):
        return ("deny", "attribution", f"the git {sub} message credits an AI; {NO_AI}. Remove those lines")
    author = next((a.split("=", 1)[1] for a in rest if a.startswith("--author=")), None)
    if author is None and "--author" in rest[:-1]:
        author = rest[rest.index("--author") + 1]
    if author is not None:
        if is_ai_identity(author):
            return ("deny", "attribution", f"--author names an AI ('{author}'); {NO_AI}")
        return None
    if sub in MAKES_COMMIT:
        who = f"{git(cwd, 'config', 'user.name')} <{git(cwd, 'config', 'user.email')}>"
        if is_ai_identity(who):
            return ("deny", "attribution",
                    f"git's identity in this checkout is '{who}', an AI; {NO_AI}. Set the user's own "
                    "identity for this repo first (git config user.name / user.email): `author` in "
                    ".claude/kit.json, their recent commits (git log --format='%an <%ae>'), or ask them")
    return None


def check_github_tool(tool_input):
    """A GitHub MCP call (PR, issue, comment, file commit): no AI credit in any text field."""
    stack = [tool_input]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and AI_CREDIT.search(item):
            return ("deny", "attribution", f"the text sent to GitHub credits an AI; {NO_AI}")
    return None


def check_system(argv, cwd, root):
    name = Path(argv[0]).name
    if name in ("sudo", "su", "doas"):
        return ("deny", "system", f"'{name}' runs as another user")
    if name.startswith("mkfs") or name in ("shutdown", "reboot", "halt", "poweroff", "fdisk"):
        return ("deny", "system", f"'{name}' changes the machine")
    if name == "diskutil" and any(a.lower().startswith("erase") or a in ("partitionDisk", "zeroDisk")
                                  for a in argv[1:]):
        return ("deny", "system", "diskutil erase")
    if name == "dd" and any(a.startswith("of=/dev/") for a in argv[1:]):
        return ("deny", "system", "dd to a device")
    if name in ("chmod", "chown", "chgrp") and any(f in ("-R", "--recursive") for f in argv[1:]):
        for word in [a for a in argv[2:] if not a.startswith("-")]:
            target = expand(word, cwd)
            if target is UNKNOWN:
                continue
            if target == Path("/") or target == home() or not (under(target, root) or
                                                             any(under(target, t) for t in temp_roots())):
                return ("deny", "system", f"recursive {name} outside the repository ('{word}')")
    return None


def secret_word(text):
    """The credential store a text names as a path (~/.ssh, $HOME/.aws, /Users/me/.ssh), if any."""
    hm = str(home())
    for raw in SECRET_PATHS:
        rest = re.escape(raw[1:])
        if re.search(r"(^|[\s'\"=:(])(~|\$HOME|\$\{HOME\}|" + re.escape(hm) + ")" + rest + r"(/|\s|$|['\")])", text):
            return raw
    if re.search(r"\bsecurity\s+(find|dump)-(generic|internet)-password|\bsecurity\s+dump-keychain", text):
        return "the macOS keychain"
    return None


def secret_path(path):
    """The credential store a path is in, following symlinks."""
    stores = tilde(SECRET_PATHS)
    for candidate in {Path(path), Path(os.path.realpath(str(path)))}:
        for raw, store in zip(SECRET_PATHS, stores):
            if candidate == store or under(candidate, store):
                return raw
    return None


def check_secrets(argv, cwd):
    name = Path(argv[0]).name
    if name == "security" and len(argv) > 1 and re.match(r"(find|dump)-(generic|internet)-password|dump-keychain",
                                                         argv[1]):
        return ("deny", "secrets", "reads the macOS keychain")
    if name in ("echo", "printf", "git", "true", ":"):
        return None
    words = argv[1:]
    if name in ("grep", "egrep", "rg", "ag", "ack"):
        positional = [w for w in words if not w.startswith("-")]
        words = [w for w in words if w not in positional[:1]]  # the first positional is the pattern
    for word in words:
        for part in (word.split("=", 1)[-1], word):
            if not part or part.startswith("-"):
                continue
            target = expand(part, cwd)
            if target is UNKNOWN:
                continue
            found = secret_path(target)
            if found:
                return ("deny", "secrets", f"reads {found}")
    return None


def check_bash(command, cwd, root, opts):
    for pattern in opts.get("allowCommands") or []:
        try:
            if re.search(pattern, command):
                return None
        except re.error:
            continue
    if re.search(r":\(\)\s*\{\s*:\|:&\s*\};\s*:", command):
        return ("deny", "system", "fork bomb")
    if re.search(r">\s*/dev/(sd|disk|nvme|hd)", command):
        return ("deny", "system", "write to a disk device")
    asked = None
    for seg in segments(command):
        argv = seg["argv"]
        name = Path(argv[0]).name
        if name == "cd":
            target = expand(argv[1], cwd) if len(argv) > 1 else home()
            cwd = cwd if target is UNKNOWN else target
            continue
        if seg["piped_from"] and (name in SHELLS or name in INTERPRETERS) and \
                Path(seg["piped_from"][0]).name in DOWNLOADERS:
            return ("deny", "pipe-to-shell", f"'{seg['piped_from'][0]} ... | {name}' runs downloaded code")
        checks = [check_secrets(argv, cwd)]
        if name in ("git", "gh") and opts.get("attribution") != "allow":
            checks.append(check_attribution(argv, cwd, command))
        if name == "rm":
            checks.append(check_rm(argv, cwd, root))
        elif name == "find":
            checks.append(check_find(argv, cwd, root))
        elif name == "git":
            checks.append(check_git(argv, cwd, opts))
        elif name in INTERPRETERS:
            checks.append(check_interpreter(argv))
        else:
            checks.append(check_system(argv, cwd, root))
        for found in checks:
            if found and found[0] == "deny":
                return found
            if found and not asked:
                asked = found
    return asked


def check_agents(data, opts):
    ask, deny = opts.get("agentsAsk"), opts.get("agentsDeny")
    if not isinstance(ask, int) and not isinstance(deny, int):
        return None
    session = data.get("session_id") or "nosession"
    count = int(kitlib.load_state(session, "guard-agents") or 0) + 1
    kitlib.save_state(session, "guard-agents", count)
    if isinstance(deny, int) and count > deny:
        return ("deny", "agents", f"this session already started {count - 1} subagents (guard.agentsDeny = {deny})")
    if isinstance(ask, int) and count > ask:
        return ("ask", "agents", f"subagent #{count} this session (guard.agentsAsk = {ask}); confirm to continue")
    return None


def main():
    data = kitlib.read_input()
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or os.getcwd())
    root = Path(os.path.normpath(str(kitlib.git_root(cwd) or cwd)))
    active, opts = settings(root)
    if not active:
        return 0
    found = None
    if tool == "Bash":
        found = check_bash(str(tool_input.get("command") or ""), cwd, root, opts)
    elif tool in ("Read", "Grep", "Glob"):
        target = str(tool_input.get("file_path") or tool_input.get("path") or "")
        if target:
            path = expand(target, cwd)
            store = secret_path(path) if path is not UNKNOWN else None
            if store:
                found = ("deny", "secrets", f"reads {store}")
        if not found and tool == "Glob" and secret_word(" " + str(tool_input.get("pattern") or "")):
            found = ("deny", "secrets", "globs a credential store")
    elif tool in ("Agent", "Task"):
        found = check_agents(data, opts)
    elif tool.startswith("mcp__") and "github" in tool.lower() and opts.get("attribution") != "allow":
        found = check_github_tool(tool_input)
    if not found:
        return 0
    decision, rule, why = found
    if decision == "ask":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask",
            "permissionDecisionReason": f"kit guard ({rule}): {why}"}}))
        return 0
    print(f"kit guard ({rule}): {why}. Blocked by the kit's guardrails whatever the permission mode. "
          "Find a safer way (work inside the repo, on a branch, through a PR), or ask the user; they "
          "can allow a specific command with guard.allowCommands in .claude/kit.json.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
