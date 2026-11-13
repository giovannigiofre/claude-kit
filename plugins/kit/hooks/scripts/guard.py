#!/usr/bin/env python3
"""PreToolUse (Bash|Read|Grep|Glob|Agent|Task|GitHub MCP tools): deterministic guardrails, best effort.

A rule in a prompt is a preference; a rule in a hook is checked every time. This hook blocks the
few actions that cannot be undone or that leak credentials, whatever the permission mode
(default, auto, or a headless overnight iteration), and leaves the rest to the permission
system. It reads shell text, so it is a guardrail, not a boundary: an obfuscated command can
slip past it. The OS boundary is the Bash sandbox (the kit's "Sandbox" safety profile).

  rm-outside       recursive delete (rm -r, find -delete/-exec rm, rmtree in python -c ...) of
                   /, the home folder, the repo root, .git, or anything outside the repo except
                   its other linked worktrees, the temp folders and the cache folders; after
                   `cd <dir> &&` into another work tree, that repository counts as inside too
                   (its root and .git do not). A variable set once by a plain NAME=value
                   earlier in the command is judged by its value; a target known only at run
                   time ($(...) other than mktemp, a loop variable, a value set twice or by
                   eval or source, an escaped or single-quoted $NAME, xargs, a folder after
                   `cd -`, popd or `cd $X`) is asked about. A repository entered by cd counts
                   only when it holds that folder. find with no name or path test at a repo
                   root counts as deleting the root
  push-protected   a push to a protected branch (main, master, the remote's default), a force
                   push to one, a mirror push, or deleting one
  discard-work     git reset --hard, checkout/restore of the whole tree, clean, stash drop/clear
                   while there are uncommitted changes; git clean -x/-X always
  system           sudo/su/doas, mkfs, dd to a device, disk erase, shutdown/reboot, recursive
                   chmod/chown outside the repo
  pipe-to-shell    a download piped into a shell or interpreter (curl ... | sh)
  secrets          reading credential stores (~/.ssh, ~/.aws, gh/docker/kube config, .netrc,
                   ~/.gnupg, the macOS keychain) with Bash, Read, Grep or Glob, symlinks resolved;
                   the store's own tool may name it (ssh -i ~/.ssh/key, kubectl --kubeconfig,
                   aws, gh, docker, gcloud, gpg)
  agents           optional cap on subagents per session (guard.agentsAsk / guard.agentsDeny)
  attribution      the user is the only author: an AI credited in a commit message, a PR, an
                   issue or a comment (Co-Authored-By: Claude, "Generated with Claude Code", a
                   claude.ai session link), a commit made under an AI git identity, or git's
                   identity set to one, by git, gh or a GitHub MCP tool. For gh only what is
                   published counts: the title, body, message or field values and files of a
                   writing subcommand (pr/issue create, edit, comment, ...; api with POST, a
                   field or --input); `gh pr view ... | grep "Generated with Claude"` reads;
                   guard.attribution = "allow" turns this rule off
  wait             a foreground wait that holds the turn (and, in a thread, its caller): sleep
                   over 60 s (guard.sleepMaxSec), a while/until loop that sleeps while it polls
                   (not `while read`), gh run watch or gh pr checks --watch; never a Monitor
                   command, one run in the background or ended with &, or one allowCommands
                   names; guard.waits = false turns this rule off
  memory           the kit verifier (agent type kit:verifier only) writing a memory file (a
                   MEMORY.md in any case, anything in an agent-memory folder; by redirect, tee,
                   cp/mv/install/ln/rsync, dd, sed -i/perl -i/truncate, or interpreter code that
                   opens a quoted path) outside <main checkout>/.kit/agent-memory/kit-verifier
                   (`.claude/` in a project the kit has not moved yet: kitlib.state_entry);
                   quoted text and here-document bodies are data, not writes; checked in every
                   repo, kit.json or not, guard off too, since the verifier is the kit's
  hook-bypass      a git commit, push, merge, rebase, cherry-pick or am that skips the repository's
                   hooks: --no-verify, -n on commit and am (on push it is --dry-run, on merge and
                   rebase --no-stat), -c core.hooksPath=<elsewhere>, HUSKY=0 or HUSKY_SKIP_HOOKS=1
                   set for it; and git config pointing core.hooksPath away from the repository's
                   hooks (its current folder or an existing folder in its work tree are its own)
  retry            the same push, rebase or PR merge, as the same command text in the same folder at
                   the same commit, a fourth time within 30 minutes: it is refused and the thread
                   hands the step back; guard.retries = false turns this rule off
  project          kit.json guard.denyCommands / guard.askCommands: the project's own rules,
                   each {"pattern": "<regex over the command>", "reason": "..."}; /kit:learn
                   writes one when a lesson deserves a check instead of a sentence

Multi-line commands, subshells, braces, if/for/while bodies, $(...) and backticks, sh -c and
`cd` within one command are followed; quoted text over several lines (a commit message) and
here-document bodies are arguments, not commands.

Active when the project has .claude/kit.json (unless its "guard" is "off"), or everywhere when
~/.claude/kit.json says "guard": "on". Options, under "guard" in either file:
  {"protectedBranches": ["main", "master"], "agentsAsk": 15, "agentsDeny": 40,
   "allowCommands": ["^rm -rf /opt/my-build$"], "attribution": "block", "waits": true, "sleepMaxSec": 60,
   "denyCommands": [{"pattern": "^npm install(?! --frozen)", "reason": "use pnpm here"}], "askCommands": []}

Before each Bash command in a project whose kit.json has `protect` or `onEdit` it also notes
which files are already modified and when, per session and agent (bash_edits.py, PostToolUse,
compares and runs protect and onEdit on what the command changed), so an edit made with sed or
a heredoc gets the same checks as one made with the Edit tool.

Each denial is counted in the kit's lesson ledger (lessons.py) by its shape, once per session,
as an event for the statistics; it never becomes a lesson (the hook enforces the rule itself).
"""

import fnmatch
import glob
import hashlib
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


def expand(word, cwd, raw=False):
    """A path for a shell word, or UNKNOWN when it depends on run-time values. With raw, the path
    is joined but not normalised as text, so `link/..` and a trailing `/` survive for resolved()."""
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
    elif w.startswith("~"):  # ~user: that user's home folder
        user = os.path.expanduser(w.split("/")[0])
        if user.startswith("~"):
            return UNKNOWN
        w = user + w[len(w.split("/")[0]):]
    joined = os.path.join(str(cwd), w)
    return joined if raw else Path(os.path.normpath(joined))


def quote_mask(text):
    """For each character of a shell text: "'" inside single quotes or $'...', '"' inside double
    quotes, "\\" when a backslash escapes it, " " otherwise. $(...) and backticks quote afresh."""
    mask, stack, i = [], [], 0
    while i < len(text):
        ch, top = text[i], stack[-1] if stack else None
        if top in ("'", "$'"):
            if ch == "\\" and top == "$'" and i + 1 < len(text):
                mask += ["'", "'"]
                i += 2
                continue
            mask.append("'")
            if ch == "'":
                stack.pop()
            i += 1
            continue
        if ch == "\\" and i + 1 < len(text):
            mask += [top or " ", "\\"]
            i += 2
            continue
        mask.append(top if top == '"' else " ")
        if text.startswith("$(", i):
            stack.append("(")
            mask.append(mask[-1])
            i += 1
        elif ch == "`":
            stack.pop() if top == "`" else stack.append("`")
        elif top == '"':
            if ch == '"':
                stack.pop()
                mask[-1] = " "
        elif ch in "'\"":
            stack.append("$'" if ch == "'" and text[i - 1:i] == "$" else ch)
        elif top == "(" and ch in "()":
            stack.pop() if ch == ")" else stack.append("(")
        i += 1
    return "".join(mask)


def mktemp_value(inner, known):
    """Where `$(mktemp ...)` puts its file or folder, as a path below the folder it is made in
    (the template's folder, -p DIR, or $TMPDIR): rm -rf of it is judged as a delete in that
    folder. None when the folder is not an absolute path known now."""
    if re.search(r"[`;&|<>()]", inner) or ("'" in inner and "$" in inner):
        return None
    try:
        words = shlex.split(inner)[1:]
    except ValueError:
        return None
    env = {"HOME": str(home()), "TMPDIR": tempfile.gettempdir(), **known}
    words = [with_vars(str(home()) + w[1:] if w == "~" or w.startswith("~/") else w, env) for w in words]
    base, template, in_dir = env["TMPDIR"], None, False
    while words:
        w = words.pop(0)
        if w in ("-p", "--tmpdir") and words:
            base, in_dir = words.pop(0), True
        elif w.startswith("--tmpdir="):
            base, in_dir = w.split("=", 1)[1], True
        elif w.startswith("-t"):
            in_dir = True
            if w == "-t" and words:
                words.pop(0)
        elif w.startswith("-"):
            continue  # -d, -q, -u
        else:
            template = w
    if template and (re.search(r"\s", template) or glob.has_magic(template)):
        return None
    if template and "/" in template:
        base = os.path.dirname(template)
    elif template and not in_dir:
        return None  # a bare template is made in the working folder
    if "$" in base or not os.path.isabs(base) or re.search(r"\s", base) or glob.has_magic(base):
        return None
    return os.path.normpath(base) + "/mktemp.XXXXXX"


def assigned_value(command, name, known):
    """The value a command gives `name` with its one plain `name=value`, when that value is known
    now: a literal, ~, $HOME, $TMPDIR, names already known, or the folder $(mktemp ...) makes.
    None when the name is set more than once or any other way (read, for, local, ${name:=...},
    eval or source), or the value has other $(...), backticks, a glob, whitespace, or is empty:
    those are only known when the command runs. The caller rules out eval, source and `.`."""
    n = re.escape(name)
    sets = list(re.finditer(rf"(?<![\w$]){n}\+?=", command))
    other = rf"\bfor\s+{n}\b|\bselect\s+{n}\b|\$\{{{n}:?[=?]|\(\([^)]*\b{n}\b|\b{n}\[|\bprintf\s+-v\s*{n}\b" \
            rf"|\b(read|unset|declare|typeset|local|readonly|let|getopts|mapfile|readarray)\b[^\n;&|]*\b{n}\b"
    if len(sets) != 1 or command[sets[0].end() - 2] == "+" or re.search(other, command):
        return None
    c, i, parts = command, sets[0].end(), []
    if m := re.match(r"(\"?)\$\((mktemp\b[^()`]*)\)\1(?=[\s;&|)]|$)", c[i:]):
        return mktemp_value(m.group(2), known)
    while i < len(c) and c[i] not in " \t\n;&|()<>":
        if c[i] in "'\"":
            j = c.find(c[i], i + 1)
            if j == -1 or (c[i] == '"' and re.search(r"[\\`]", c[i + 1:j])):
                return None
            parts.append((c[i], c[i + 1:j]))
            i = j + 1
        elif c[i] in "\\`":
            return None
        else:
            j = i
            while j < len(c) and c[j] not in " \t\n;&|()<>'\"\\`":
                j += 1
            parts.append(("", c[i:j]))
            i = j
    value = ""
    for k, (quote, text) in enumerate(parts):
        if quote and k == 0 and text.startswith("~"):
            return None  # a quoted ~ is a folder named ~, not the home folder
        if quote == "'":
            value += text
            continue
        if not quote and glob.has_magic(text):
            return None
        if not quote and k == 0 and (text == "~" or text.startswith("~/")):
            text = str(home()) + text[1:]
        text = with_vars(text, {"HOME": str(home()), "TMPDIR": tempfile.gettempdir(), **known})
        if "$" in text:
            return None
        value += text
    return value if value and not re.search(r"\s", value) else None


def with_vars(word, env):
    """A word with the variables of `env` put in ($NAME and ${NAME}); an unknown one stays."""
    return re.sub(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)(?!\w)",
                  lambda m: env.get(m.group(1) or m.group(2), m.group(0)), word)


def braces(word, limit=256):
    """The words the shell makes of `word` by brace expansion, before rm or find sees them:
    {a,b}, nested ones, {1..9..2} and {a..e}; ${...} and a brace with no comma or range stay as
    written. None when there would be more than `limit` words (or 32 braces) to judge."""
    if word.count("{") > 32:
        return None
    i = 0
    while (i := word.find("{", i)) != -1:
        depth, commas = 0, []
        for j in range(i, len(word)):
            depth += {"{": 1, "}": -1}.get(word[j], 0)
            if depth == 1 and word[j] == ",":
                commas.append(j)
            if depth == 0:
                break
        else:
            return [word]  # never closed: no expansion
        if i and word[i - 1] == "$":
            i = j + 1
            continue
        body, alts = word[i + 1:j], None
        if commas:
            alts = [word[a + 1:b] for a, b in zip([i] + commas, commas + [j])]
        elif m := re.fullmatch(r"(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?|([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?", body):
            a, b = (int(m[1]), int(m[2])) if m[1] else (ord(m[4]), ord(m[5]))
            step = max(abs(int(m[3] or m[6] or 1)), 1)
            if abs(b - a) // step >= limit:
                return None
            seq = range(a, b + 1, step) if a <= b else range(a, b - 1, -step)
            alts = [str(n) if m[1] else chr(n) for n in seq]
        if alts is None:
            i += 1
            continue
        out = []
        for alt in alts:
            more = braces(word[:i] + alt + word[j + 1:], limit)
            if more is None or len(out) + len(more) > limit:
                return None
            out += more
        return out
    return [word]


def repo_roots(repos):
    return {p for r in repos for p in (Path(r), Path(os.path.realpath(str(r))))}


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
        lex.commenters = ""  # logical_lines already dropped real comments; `a#;b` is two commands
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


def logical_lines(text, bodies=None):
    """The command lines of a shell text. A newline inside quotes or $(...) stays in its line (a
    multi-line commit message is one argument), a line ending in && || or | goes on to the next,
    a comment ends at the newline, and the bodies of here-documents opened outside quotes are
    dropped: they are data, not commands. Inside "...", $(...) and backticks quote afresh.
    A list passed as `bodies` gets each dropped body as (the line up to its <<, the body)."""
    lines, cur, stack, heredocs, i = [], [], [], [], 0
    while i < len(text):
        ch, top = text[i], stack[-1] if stack else None
        if top in ("'", "$'"):
            if ch == "\\" and top == "$'" and i + 1 < len(text):
                cur.append(text[i:i + 2])
                i += 2
                continue
            if ch == "'":
                stack.pop()
        elif ch == "\\" and i + 1 < len(text):
            cur.append(text[i:i + 2])
            i += 2
            continue
        elif top in ("((", "a("):  # arithmetic: no quotes, no here-documents, << is a shift
            if top == "((" and text.startswith("))", i):
                stack.pop()
                cur.append("))")
                i += 2
                continue
            if ch == "(":
                stack.append("a(")
            elif ch == ")" and top == "a(":
                stack.pop()
        elif text.startswith("$((", i) or (not top and text.startswith("((", i)):
            stack.append("((")
            n = 3 if ch == "$" else 2
            cur.append(text[i:i + n])
            i += n
            continue
        elif text.startswith("$(", i):
            stack.append("(")
            cur.append("$(")
            i += 2
            continue
        elif ch == "`":
            stack.pop() if top == "`" else stack.append("`")
        elif top == '"':
            if ch == '"':
                stack.pop()
        elif ch in "'\"":
            stack.append("$'" if ch == "'" and cur and cur[-1] == "$" else ch)
        elif top == "(" and ch in "()":
            stack.pop() if ch == ")" else stack.append("(")
        elif top == "`" or (top == "(" and ch == "\n" and not heredocs):
            pass  # inside $(...) or backticks: a newline there is part of the substitution
        elif ch == "#" and (not cur or cur[-1] in " \t;&|()\n"):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("<<<", i):  # a here-string: its word is on this line
            cur.append("<<<")
            i += 3
            continue
        elif text.startswith("<<", i):
            m = re.match(r"<<-?[ \t]*([^\s;&|<>()]+)", text[i:])
            word = m and re.sub(r"[\\'\"]", "", m.group(1))
            if word and m.group(1).count("'") % 2 == 0 and m.group(1).count('"') % 2 == 0:
                heredocs.append((word, "".join(cur)))  # the shell ends it at the word with its quotes removed
                cur.append(m.group(0))
                i += len(m.group(0))
                continue
        elif ch == "\n":
            if top:  # a here-document inside $(...): the substitution goes on after its body
                cur.append("\n")
            elif re.search(r"(&&|\|\||\|)\s*$", "".join(cur)):
                cur.append(" ")  # the command goes on after the newline (and any here-document)
            else:
                lines.append("".join(cur))
                cur = []
            i += 1
            for word, opener in heredocs:  # skip each body, up to its closing word
                body = []
                while i < len(text):
                    end = text.find("\n", i)
                    end = len(text) if end == -1 else end
                    line, i = text[i:end], end + 1
                    if line.strip() == word:
                        break
                    body.append(line)
                if bodies is not None:
                    bodies.append((opener, "\n".join(body)))
            heredocs = []
            continue
        cur.append(ch)
        i += 1
    lines.append("".join(cur))
    return [line for line in lines if line.strip()]


def assignments(words):
    """{NAME: value} of the NAME=value words among `words` (as the shell sees them, quotes removed)."""
    return {m.group(1): w[m.end():] for w in words if (m := ASSIGN.match(w))}


OPENERS, CLOSERS = {"if", "for", "while", "until", "case", "select", "{"}, {"fi", "done", "esac", "}"}
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=")


def segments(command, inner=False):
    """Simple commands of a shell text, in order: lines, ; && || | & ( ) and braces split them,
    keywords and redirections are dropped, $(...), backticks and sh -c bodies are followed.
    A segment made only of variable assignments (or `export NAME=...`) lists their names under
    "assigns"; "plain" says it runs in this shell, unconditionally and once (not in a subshell,
    a pipeline, the background, a loop or an if, nor after && or ||). "nested" marks sh -c bodies,
    which get only exported variables."""
    out, depth, lost = [], 0, False
    for line in logical_lines(command.replace("\\\n", " ")):
        for body in substitutions(line):
            out.extend(segments(body, inner=True))
        cur, pipe_from, skip, prev = [], None, False, ";"
        for tok in tokenize(line) + [";"]:
            if skip:
                skip = False
                continue
            if tok and set(tok) <= set("<>"):
                skip = True  # the redirection's target is a file, not an argument
                continue
            if tok and set(tok) <= set(";&|()"):
                words = cur
                while words and (words[0] in KEYWORDS or words[0] in OPENERS):
                    depth += (words[0] in OPENERS) - (words[0] in CLOSERS)
                    words = words[1:]
                lost = lost or depth < 0  # a case pattern's `)` or the like: stop trusting the depth
                plain = not (inner or lost or depth or words != cur or set(prev) & set("&|")
                             or "|" in tok or "&" in tok.replace("&&", ""))
                argv = strip_wrappers(cur)
                assigns = [ASSIGN.match(w).group(1) for w in words if ASSIGN.match(w)]
                if words and (len(assigns) == len(words) or (words[0] == "export" and assigns)):
                    out.append({"argv": argv, "piped_from": None, "assigns": assigns, "plain": plain,
                                "env": assignments(words)})
                elif argv:
                    out.append({"argv": argv, "piped_from": pipe_from, "plain": plain,
                                "env": assignments(cur[:len(cur) - len(argv)])})
                depth += tok.count("(") - tok.count(")")
                pipe_from = argv if tok == "|" else None
                prev, cur = tok, []
            else:
                cur.append(tok)
    nested = []
    for seg in out:
        argv = seg["argv"]
        if argv and Path(argv[0]).name in SHELLS and "-c" in argv[1:-1]:
            nested.extend(dict(s, nested=True, plain=False) for s in segments(argv[argv.index("-c") + 1], True))
    return out + nested


def git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10,
                             env=kitlib.git_env())
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

def resolved(raw):
    """What rm really acts on, walked on the filesystem (symlinks followed, `..` taken after them),
    not as text. The last name is followed too when the word ends in `/` (rm then removes the
    link's target); a glob is matched inside the real folder; otherwise rm -rf on a link removes
    only the link."""
    head, name = os.path.split(raw)
    if name in ("", ".", ".."):
        return Path(os.path.realpath(raw))
    return Path(os.path.realpath(head)) / name


def delete_target(word, cwd, repos):
    if word in (".", "..", ".*", "/*", "~/*", "*") and Path(cwd) in (Path("/"), home()):
        return ("deny", f"delete of '{word}' in {cwd}")
    if word in ("..", ".*") or word.endswith("/.."):
        return ("deny", f"delete of '{word}'")
    target = expand(word, cwd)
    if target is UNKNOWN:
        return ("ask", f"delete target '{word}' is only known when the command runs")
    real, hm = resolved(expand(word, cwd, raw=True)), home()
    roots = repo_roots(repos)
    for t in {target, real}:
        if t == Path("/") or t == hm or under(hm, t):
            return ("deny", f"delete of '{word}' ({t})")
        if t.name == ".git" or (any(under(t, r) for r in roots) and "/.git/" in str(t) + "/"):
            return ("deny", f"delete inside .git ('{word}')")
        if any(t == r or under(r, t) for r in roots):
            return ("deny", f"delete of the repository root ('{word}')")
    # what is allowed is decided on the real path, so a symlink cannot lead the delete elsewhere
    if any(under(real, c) for c in tilde(CACHE_PATHS)) or any(under(real, r) for r in roots) \
            or any(under(real, t) for t in temp_roots()) or any(in_sibling_worktree(real, r) for r in repos):
        return None
    return ("deny", f"delete outside the repository ('{word}' -> {real})")


def in_sibling_worktree(real, root):
    """True when the real path `real` is in, or is, another linked worktree registered to this
    repository (a thread's checkout next to this one), outside its .git. The main checkout stays
    outside: it can hold uncommitted work, and a bare repository's folder is all history."""
    listing = git(root, "worktree", "list", "--porcelain")
    entries = [block.splitlines() for block in listing.split("\n\n") if block.startswith("worktree ")]
    linked = [Path(os.path.realpath(lines[0][len("worktree "):])) for lines in entries[1:]]  # [0]: main or bare
    return any(real == tree or (under(real, tree) and ".git" not in real.relative_to(tree).parts)
               for tree in linked)


def check_rm(argv, cwd, repos):
    flags = [a for a in argv[1:] if a.startswith("-")]
    recursive = any(f in ("-r", "-R", "--recursive") or (not f.startswith("--") and ("r" in f or "R" in f))
                    for f in flags)
    if not recursive:
        return None
    targets = [a for a in argv[1:] if not a.startswith("-")]
    if not targets:
        return ("ask", "rm-outside", "recursive delete whose targets come from input (xargs or similar)")
    words = [braces(word) for word in targets]
    if None in words:
        return ("ask", "rm-outside", "recursive delete of too many brace expansions to judge")
    for word in sum(words, []):
        found = delete_target(word, cwd, repos)
        if found:
            return (found[0], "rm-outside", f"recursive {found[1]}")
    return None


GIT_NAMES = [".git", "HEAD", "ORIG_HEAD", "FETCH_HEAD", "COMMIT_EDITMSG", "config", "index", "packed-refs",
             "description", "objects", "refs", "heads", "tags", "hooks", "info", "logs", "exclude", "pack",
             "pack-0a.pack", "pack-0a.idx", "pre-commit.sample", "0a"]


def reaches_git(args):
    """True when find's expression can match .git or what is in it: no name or path test, a
    negation or an -o, or a test whose pattern matches .git itself."""
    def matches(test, pattern):
        if test == "-regex":
            try:
                return any(re.fullmatch(pattern, p) for p in ("./.git", "./.git/x"))
            except re.error:
                return True
        if test.endswith("name") and test != "-wholename":  # .git or a name inside it
            pattern = pattern.lower() if test == "-iname" else pattern
            return any(fnmatch.fnmatchcase(n.lower() if test == "-iname" else n, pattern) for n in GIT_NAMES)
        return any(fnmatch.fnmatchcase(p, pattern.lower() if test == "-ipath" else pattern)
                   for p in ("./.git", "./.git/x"))
    tests = [(a, args[k + 1]) for k, a in enumerate(args[:-1]) if re.fullmatch(r"-i?(name|path|regex)|-wholename", a)]
    return not tests or any(a in ("!", "-not", "-o", "-or") for a in args) or any(matches(*t) for t in tests)


def check_find(argv, cwd, repos):
    deletes = "-delete" in argv or any(
        a in ("-exec", "-execdir", "-ok") and i + 1 < len(argv) and Path(argv[i + 1]).name in ("rm", "rmdir", "shred")
        for i, a in enumerate(argv))
    if not deletes:
        return None
    args, options, paths = argv[1:], [], []
    while args and re.fullmatch(r"-[HLPEXdsxf]+", args[0]):  # options before the paths, maybe combined
        options.append(args.pop(0))
        if options[-1].endswith("f") and args:  # BSD: -f names a path
            paths.append(args.pop(0))
    options = "".join(options)
    if "L" in options or "-follow" in args:
        return ("ask", "rm-outside", "find following symlinks while deleting")
    if args[:1] == ["--"]:
        args = args[1:]
    for a in args:
        if a.startswith("-") or a in ("(", "!", ")"):
            break
        paths.append(a)
    roots = repo_roots(repos)
    expanded = [braces(word) for word in paths or ["."]]
    if None in expanded:
        return ("ask", "rm-outside", "find deleting in too many brace expansions to judge")
    words = []
    for word in sum(expanded, []):  # a brace or a glob is judged by what the shell will match
        raw = expand(word, cwd, raw=True)
        found = glob.glob(raw) if raw is not UNKNOWN and glob.has_magic(word) else []
        words += [m + ("/" if word.endswith("/") else "") for m in found] or [word]
    for word in words:
        if "H" in options:  # -H follows each path given: judge it as the folder it leads to
            word = word.rstrip("/") + "/"
        raw = expand(word, cwd, raw=True)
        if raw is not UNKNOWN:
            real = resolved(raw)
            whole = reaches_git(args)
            if any(under(real, r) and not (real == r and whole) for r in roots) and ".git" not in real.parts:
                continue  # find deletes what matches below the path; with no name or path test, all of .git
        found = delete_target(word, cwd, repos)
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


HOOK_SUBS = {"commit", "push", "merge", "rebase", "cherry-pick", "am"}
# -n is --no-verify only on commit and am; on push it is --dry-run, on merge and rebase --no-stat,
# on cherry-pick --no-commit (git <sub> -h, git 2.43)
SHORT_NO_VERIFY = {"commit", "am"}
# short options that take a value: the rest of the cluster (-mfix) or the next word is that value
SHORT_VALUES = {"commit": "mFcCt", "push": "o", "merge": "mFsX", "rebase": "CsxX", "cherry-pick": "mX",
                "am": "Cp"}
SHORT_OPTIONAL = {"commit": "Su", "merge": "S", "rebase": "Sr", "cherry-pick": "S", "am": "S"}  # value only attached
LONG_VALUES = {"--message", "--file", "--reedit-message", "--reuse-message", "--trailer", "--template", "--author",
               "--date", "--cleanup", "--fixup", "--squash", "--pathspec-from-file", "--strategy",
               "--strategy-option", "--into-name", "--exec", "--onto", "--push-option", "--repo", "--receive-pack",
               "--mainline", "--quoted-cr", "--directory", "--exclude", "--include", "--patch-format",
               "--resolvemsg"}
CONFIG_VALUE_FLAGS = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value"}
HOOKS_FIX = ("The hooks are the repository's own checks: skipping one hides what it found instead of fixing "
             "it. Run the step without the bypass and fix what the hook reports; if you cannot, hand the step "
             "back with the hook's output")


def skips_verify(sub, rest):
    """Whether a git commit/push/merge/rebase/cherry-pick/am argument list asks git to skip the hooks:
    --no-verify (or an abbreviation git accepts), or -n alone or in a cluster where -n means that.
    Option values (`-m "--no-verify"`, `-mn`) are text, not flags; the last of --verify/--no-verify wins."""
    skip, i = False, 0
    while i < len(rest):
        a = rest[i]
        i += 1
        if a == "--":
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if "=" not in a and name in LONG_VALUES:
                i += 1
            elif len(name) >= len("--no-ve") and "--no-verify".startswith(name):
                skip = True
            elif name == "--verify":
                skip = False
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch in SHORT_VALUES.get(sub, ""):
                    i += k == len(a) - 2  # nothing attached: the next word is the value
                    break
                if ch in SHORT_OPTIONAL.get(sub, ""):
                    break
                if ch == "n" and sub in SHORT_NO_VERIFY:
                    skip = True
    return skip


def hooks_elsewhere(cwd, value):
    """Whether core.hooksPath = `value` would run hooks from another folder than the repository's
    own: its current hooks folder, or an existing folder in its work tree (outside .git), as husky's
    .husky or a .githooks folder are. An unset value means git's default, <common dir>/hooks."""
    current = git(cwd, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    if not current:
        return False  # not a repository: no hooks to skip
    if value is None:
        common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
        new = os.path.join(common, "hooks") if common else ""
    elif "$" in value or "`" in value:
        return True
    else:
        new = git(cwd, "-c", f"core.hooksPath={value}", "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    if not new:
        return True
    new, current = os.path.realpath(new), os.path.realpath(current)
    if new == current:
        return False
    top = git(cwd, "rev-parse", "--show-toplevel")
    inside = top and under(new, os.path.realpath(top)) and ".git" not in Path(new).relative_to(os.path.realpath(top)).parts
    return not (inside and os.path.isdir(new) and value is not None)


def check_hooks(argv, cwd, env):
    """hook-bypass: a git step that skips the repository's hooks (--no-verify, commit's or am's -n,
    core.hooksPath pointed elsewhere for the command or in the config, HUSKY=0 or HUSKY_SKIP_HOOKS=1).
    A thread that meets a red pre-commit or pre-push hook can turn it green by not running it, and
    the problem the hook found then reaches the branch unseen."""
    args, configs = argv[1:], []
    while args and args[0].startswith("-"):
        a = args[0]
        if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path") and len(args) > 1:
            if a == "-C":
                target = expand(args[1], cwd)
                cwd = cwd if target is UNKNOWN else target
            elif a == "-c":
                configs.append(args[1])
            args = args[2:]
            continue
        if a.startswith("--config-env="):  # the value comes from an environment variable: unknown here
            key = a.split("=", 1)[1].split("=", 1)[0]
            configs.append(key + "=$" + key)
        args = args[1:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if sub == "config":
        unset, words, i = False, [], 0
        while i < len(rest):
            a = rest[i]
            i += 1
            if a in ("--unset", "--unset-all"):
                unset = True
            elif a in CONFIG_VALUE_FLAGS:
                i += 1
            elif not a.startswith("-"):
                words.append(a)
        if words[:1] in (["set"], ["unset"]):
            unset = unset or words[0] == "unset"
            words = words[1:]
        if words and words[0].lower() == "core.hookspath" and (unset or len(words) >= 2):
            if hooks_elsewhere(cwd, None if unset else words[1]):
                return ("deny", "hook-bypass", "git config points core.hooksPath away from the repository's hooks")
        return None
    if sub not in HOOK_SUBS:
        return None
    if skips_verify(sub, rest):
        return ("deny", "hook-bypass", f"git {sub} with --no-verify" + (" (-n)" if sub in SHORT_NO_VERIFY else "")
                + " skips the repository's hooks")
    for item in configs:
        key, _, value = item.partition("=")
        if key.lower() == "core.hookspath" and hooks_elsewhere(cwd, value):
            return ("deny", "hook-bypass", f"git -c core.hooksPath={value} {sub} runs no hooks of this repository")
    if env.get("HUSKY") == "0" or env.get("HUSKY_SKIP_HOOKS", "").lower() in ("1", "true"):
        name = "HUSKY=0" if env.get("HUSKY") == "0" else "HUSKY_SKIP_HOOKS"
        return ("deny", "hook-bypass", f"{name} makes git {sub} skip the repository's husky hooks")
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
# gh subcommands that publish text; `gh pr view`, `gh issue list --search ...` only read
GH_WRITES = {("pr", "create"), ("pr", "edit"), ("pr", "comment"), ("pr", "review"), ("pr", "merge"),
             ("pr", "close"), ("pr", "reopen"), ("issue", "create"), ("issue", "edit"), ("issue", "comment"),
             ("issue", "close"), ("issue", "reopen"), ("release", "create"), ("release", "edit"),
             ("gist", "create"), ("gist", "edit")}
GH_TEXT_FLAGS = {"-b", "--body", "-t", "--title", "-m", "--message", "--subject", "-n", "--notes", "-d", "--desc",
                 "-c", "--comment", "--comment-body", "-f", "-F", "--field", "--raw-field"}
GH_VALUE_FLAGS = GH_TEXT_FLAGS | {"-R", "--repo", "--hostname", "-X", "--method", "--input", "--body-file",
                                  "-q", "--jq", "--json", "-s", "--search", "-L", "--limit", "-l", "--label",
                                  "-a", "--assignee", "-r", "--reviewer", "-B", "--base", "-H", "--head", "--header",
                                  "-p", "--project", "-M", "--milestone", "-e", "--editor", "--template", "-A", "--author",
                                  "-S", "--state", "--sort", "--order", "-T", "--target"}
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


def gh_words(args):
    """(positionals, {flag: [values]}) of a gh command: `--flag value` and `--flag=value` forms."""
    positional, values, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and "=" in a:
            flag, value = a.split("=", 1)
            values.setdefault(flag, []).append(value)
        elif a.startswith("-"):
            # a boolean flag that shares a letter (`-d` is --draft for pr create) must not eat the next flag
            if a in GH_VALUE_FLAGS and i + 1 < len(args) and not args[i + 1].startswith("-"):
                values.setdefault(a, []).append(args[i + 1])
                i += 1
            else:
                values.setdefault(a, [])
        else:
            positional.append(a)
        i += 1
    return positional, values


def gh_writes(positional, values):
    """Whether a gh command publishes text: a writing subcommand, or `gh api` with a method that
    writes, a field or an input file."""
    sub = tuple(positional[:2])
    if sub in GH_WRITES:
        return True
    if positional[:1] == ["api"]:
        methods = [m.upper() for m in values.get("-X", []) + values.get("--method", [])]
        return any(m in ("POST", "PATCH", "PUT") for m in methods) \
            or any(f in values for f in ("-f", "-F", "--field", "--raw-field", "--input"))
    return False


def gh_texts(args, cwd, command):
    """What a gh command would publish: the values of its text flags, the files it names, and the
    whole command when a value comes from a here-document or a substitution the parser cannot
    see into (its body is only in the command text)."""
    positional, values = gh_words(args)
    texts = [v for flag in GH_TEXT_FLAGS for v in values.get(flag, [])]
    texts += message_files(args, cwd)
    for path in values.get("--input", []):
        target = expand(path, cwd) if path != "-" else UNKNOWN
        if target is not UNKNOWN:
            try:
                texts.append(Path(target).read_text(encoding="utf-8", errors="replace")[:200_000])
            except Exception:
                pass
    if "<<" in command or any("$(" in t or "`" in t for t in texts):
        texts.append(command)
    return texts


def check_attribution(argv, cwd, command):
    name, args = Path(argv[0]).name, argv[1:]
    if name == "gh":
        positional, values = gh_words(args)
        if gh_writes(positional, values) and any(AI_CREDIT.search(t) for t in gh_texts(args, cwd, command)):
            return ("deny", "attribution", f"gh {' '.join(positional[:2])} text credits an AI; {NO_AI}")
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


# the tool a credential store belongs to may be pointed at it (`ssh -i ~/.ssh/key`, `kubectl
# --kubeconfig=~/.kube/config`): that is the tool using its own store, not Claude reading it
STORE_OWNERS = {"~/.ssh": {"ssh", "scp", "sftp", "rsync", "ssh-add", "ssh-keygen", "ssh-copy-id"},
                "~/.kube/config": {"kubectl", "helm"}, "~/.aws": {"aws"}, "~/.config/gh": {"gh"},
                "~/.docker/config.json": {"docker"}, "~/.config/gcloud": {"gcloud"}, "~/.gnupg": {"gpg", "gpg2"}}


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
            if found and name not in STORE_OWNERS.get(found, ()):
                return ("deny", "secrets", f"reads {found}")
    return None


def check_bash(command, cwd, root, opts):
    if allowed(command, opts):
        return None
    for decision, key in (("deny", "denyCommands"), ("ask", "askCommands")):
        for rule in opts.get(key) or []:
            pattern = rule.get("pattern") if isinstance(rule, dict) else rule
            reason = (rule.get("reason") if isinstance(rule, dict) else "") or "a rule of this project"
            try:
                if pattern and re.search(pattern, command):
                    return (decision, "project", f"{reason} (kit.json guard.{key})")
            except re.error:
                continue
    if re.search(r":\(\)\s*\{\s*:\|:&\s*\};\s*:", command):
        return ("deny", "system", "fork bomb")
    if re.search(r">\s*/dev/(sd|disk|nvme|hd)", command):
        return ("deny", "system", "write to a disk device")
    asked, env, repos, lost_cwd, shell_env = None, {}, [root], False, {}
    code = "\n".join(logical_lines(command.replace("\\\n", " ")))  # no comments, no here-document bodies
    mask = quote_mask(code)
    # a $NAME escaped or in single quotes stays as written: the shell does not put the value in
    literal = {m.group(1) for m in re.finditer(r"\$\{?([A-Za-z_]\w*)", code) if mask[m.start()] in "'\\"}
    segs = segments(command)
    # eval, source and . can set any variable unseen, also as \eval, "eval" or behind `command`
    unseen = any(seg["argv"] and (seg["argv"][0] == "." or Path(seg["argv"][0]).name in ("eval", "source"))
                 for seg in segs)
    for seg in segs:
        if seg.get("assigns"):
            shell_env.update(seg.get("env") or {})  # `export HUSKY=0; git commit`: as the commands after it see it
        for var in seg.get("assigns") or []:
            value = assigned_value(code, var, env) if seg["plain"] and not unseen else None
            if value is not None:
                env[var] = value
            elif var in ("HOME", "TMPDIR", "PWD"):
                env[var] = "${%s:?}" % var  # expand() must not put the session's value in
            else:
                env.pop(var, None)
        known = {n: v for n, v in env.items() if n not in literal}
        argv = seg["argv"] if seg.get("nested") else [with_vars(a, known) for a in seg["argv"]]
        if not argv:
            continue
        name = Path(argv[0]).name
        if name in ("cd", "pushd", "popd"):
            args = [a for a in argv[1:] if a not in ("-L", "-P", "-e", "-@", "--")]
            # with CDPATH set, `cd name` can land in a folder other than ./name
            searched = args and not args[0].startswith(("/", ".", "~", "$")) \
                and ("CDPATH" in code or os.environ.get("CDPATH"))
            target = UNKNOWN if name == "popd" or (name == "pushd" and not args) or searched \
                or re.fullmatch(r"-|[+-]\d+", (args or [""])[0]) else expand(args[0], cwd) if args else home()
            lost_cwd = lost_cwd or target is UNKNOWN
            cwd = cwd if target is UNKNOWN else target
            # `cd <dir> &&` into another work tree: its relative deletes are judged against that
            # repository too (its root and .git stay protected, as this one's do). A top that
            # does not hold the folder (core.worktree set elsewhere) is not trusted.
            top = git(cwd, "rev-parse", "--show-toplevel") if seg["plain"] and target is not UNKNOWN else ""
            top = Path(os.path.normpath(top)) if top else None
            inside = top and under(os.path.realpath(cwd), os.path.realpath(top))
            repos = [root] + ([top] if inside and top != root and not under(home(), top) else [])
            continue
        if seg["piped_from"] and (name in SHELLS or name in INTERPRETERS) and \
                Path(seg["piped_from"][0]).name in DOWNLOADERS:
            return ("deny", "pipe-to-shell", f"'{seg['piped_from'][0]} ... | {name}' runs downloaded code")
        checks = [check_secrets(argv, cwd)]
        if name in ("git", "gh") and opts.get("attribution") != "allow":
            checks.append(check_attribution(argv, cwd, command))
        if name in ("rm", "find"):
            check = check_rm if name == "rm" else check_find
            found = check(argv, cwd, repos)
            if not found and lost_cwd and check(argv, Path("/"), repos):  # after `cd -` or `cd $X`
                found = ("ask", "rm-outside", "delete in a folder only known when the command runs")
            checks.append(found)
        elif name == "git":
            checks.append(check_git(argv, cwd, opts))
            checks.append(check_hooks(argv, cwd, {**shell_env, **(seg.get("env") or {})}))
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


SLEEP_MAX_SEC = 60  # start-then-hit (`npm run dev & sleep 15; curl ...`) is fine; K8's waits ran minutes
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
WAIT_FIX = ("run it with run_in_background and let its completion notice wake you, or watch it with the "
            "Monitor tool (an until-loop condition) when you need to act on a line of its output; for CI, "
            "start `gh pr checks <n> --watch` in the background")


def sleep_seconds(args):
    total = 0.0
    for a in args:
        m = re.fullmatch(r"(\d+(?:\.\d*)?|\.\d+)([smhd]?)", a)
        if a in ("inf", "infinity"):
            return float("inf")
        if not m:
            return None  # $DELAY and the like: not judged
        total += float(m.group(1)) * UNITS[m.group(2) or "s"]
    return total


def allowed(command, opts):
    for pattern in opts.get("allowCommands") or []:
        try:
            if re.search(pattern, command):
                return True
        except re.error:
            continue
    return False


# shell words only where a command can start, so out/done.flag or --while-x are no keyword
KW = r"(?<![\w/.$-]){}(?![\w/.-])"
LOOP = re.compile(r"{}\s+((?:(?!{})[\s\S])*?)(?:[;\n]\s*|\s){}((?:(?!{})[\s\S])*?){}".format(
    r"(?:" + KW.format("while") + "|" + KW.format("until") + ")", KW.format("do"), KW.format("do"),
    KW.format("done"), KW.format("done")))


# `sleep` in command position, also as `command sleep`, `/bin/sleep`, `timeout 40 sleep`, `{ sleep`, `(sleep`
SLEEP_CMD = re.compile(r"(?:^|[;&|\n({]|" + KW.format("then") + "|" + KW.format("else") + r")\s*"
                       r"(?:(?:command|timeout(?:\s+(?:-[sk]\s+\S+|-\S+))*\s+\S+)\s+)*(?:\S*/)?sleep(?=\s|;|$)")


def sleep_limit(opts):
    """guard.sleepMaxSec when it is a number of seconds, else the default."""
    limit = (opts or {}).get("sleepMaxSec")
    return limit if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit >= 0 else SLEEP_MAX_SEC


def check_wait(command, tool_input, opts=None):
    """A foreground wait: the turn blocks on it, the caller sees no progress, and nothing tells
    anyone when it hangs. In the background the same wait costs nothing. A long Bash `timeout` is
    not a wait: most calls that set one end in seconds."""
    opts = opts or {}
    if tool_input.get("run_in_background") or opts.get("waits") is False or allowed(command, opts):
        return None
    limit = sleep_limit(opts)
    code = "\n".join(logical_lines(command.replace("\\\n", " ")))
    mask = quote_mask(code)
    # quoted text is an argument, never the wait itself
    bare = "".join(c if mask[i] == " " else " " for i, c in enumerate(code))
    if re.search(r"(?:^|[;&|]\s*|\s)&\s*$", bare.rstrip()) and not re.search(r"&&\s*$", bare.rstrip()):
        return None
    # a `sleep` run as a command in the loop's own body, the loop polling some state: `while read`
    # walks its input and a sleep there only throttles it
    for m in LOOP.finditer(bare):
        cond, body = m.group(1).strip(), m.group(2)
        # one read alone, or with the last-line idiom `|| [[ -n $line ]]`: nothing polled
        if re.fullmatch(r"""(?:\w+=\S*\s+)*read\b[^;&|\n]*?(?:\|\|\s*\[\[?\s*-n\s+(?:"[^"]*"|'[^']*'|\S+)\s*\]\]?\s*)?""", cond):
            continue
        if SLEEP_CMD.search(" " + body):
            return ("deny", "wait", "a loop that sleeps until something changes (polling in the foreground)")
    # `sleep 600 &` runs in the background: not a wait
    for seg in segments(re.sub(r"\bsleep\s+[^;&|\n]*&(?!&)", ";", command)):
        argv = seg["argv"]
        if not argv:
            continue
        name = Path(argv[0]).name
        if name == "sleep":
            secs = sleep_seconds(argv[1:])
            if secs is not None and secs > limit:
                return ("deny", "wait", f"sleep {' '.join(argv[1:])} in the foreground")
        elif name == "gh" and argv[1:3] == ["run", "watch"]:
            return ("deny", "wait", "gh run watch in the foreground")
        elif name == "gh" and argv[1:3] == ["pr", "checks"] and any(a == "--watch" or a.startswith("--watch=") for a in argv):
            return ("deny", "wait", "gh pr checks --watch in the foreground")
    return None


RETRY_STEPS = (("git", "push"), ("git", "rebase"), ("gh", "pr", "merge"))
RETRY_MAX = 3            # attempts of the same step at the same commit before the guard stops the next
RETRY_WINDOW_SEC = 1800


def check_retry(command, cwd, state, opts):
    """A push, rebase or PR merge tried again and again at the same commit goes no differently the
    fourth time: one thread's same `git push -u origin <branch>` ran five times in 18 minutes, each
    stopped on a prompt nobody answered (2026-11-12). The same command text, in the same folder, at
    the same HEAD, RETRY_MAX times within RETRY_WINDOW_SEC: the next is refused and the thread hands
    the step back. A new commit, another branch or another command starts afresh. Never raises;
    guard.retries = false turns it off."""
    if opts.get("retries") is False:
        return None
    try:
        import time
        steps = [seg["argv"] for seg in segments(command) if seg.get("argv")]
        if not any(tuple(Path(a[0]).name if i == 0 else a[i] for i in range(len(step))) == step
                   for a in steps for step in RETRY_STEPS if len(a) >= len(step)):
            return None
        head = git(cwd, "rev-parse", "HEAD")
        key = hashlib.sha1(f"{cwd}\0{head}\0{' '.join(command.split())}".encode()).hexdigest()[:16]
        now = time.time()
        seen = {k: [t for t in v if now - t < RETRY_WINDOW_SEC] for k, v in kitlib.load_state(state, "retries").items()}
        tries = seen.get(key, [])
        if len(tries) >= RETRY_MAX:
            return ("deny", "retry", f"this exact command already ran {len(tries)} times at this commit")
        seen[key] = tries + [now]
        kitlib.save_state(state, "retries", {k: v for k, v in seen.items() if v})
    except Exception:
        return None
    return None


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


def snapshot(root, session):
    """What is already modified or untracked, and when: bash_edits.py (PostToolUse) compares it
    with the tree after the command, so an edit made with sed or a heredoc gets protect and
    onEdit too. Never fails the guard."""
    try:
        import time
        kitlib.save_state(session, "bash-snapshot", {"ts": time.time(), "files": kitlib.dirty_snapshot(root)})
    except Exception:
        pass


def record_denial(cwd, rule, why, session):
    """Count the denial in the kit's lesson ledger by its shape (quoted words and paths dropped),
    once per session, as an event for the statistics only: the rule is enforced by this hook on
    every call, so it never becomes a lesson that spends a thread's budget."""
    try:
        import lessons
        lessons.LOCK_WAIT = 0.5  # the deny must land well inside the hook's timeout
        shape = re.sub(r"\s+", " ", re.sub(r"'[^']*'|\S*/\S*|\d+", "…", why)).strip()
        key = f"guard-{rule}-" + hashlib.sha1(shape.encode()).hexdigest()[:8]
        lessons.capture(cwd, "guard", key, "", ref=shape, once_per=session)  # no text: an event, not a lesson
    except Exception:
        pass


MEMORY_NAME = "agent-memory/kit-verifier"  # a kit state entry, where kitlib.state_entry finds it
MEMORY_COPIERS = {"cp", "mv", "install", "ln", "rsync", "ditto"}
MEMORY_EDITORS = {"sed", "gsed", "perl"}  # in place (-i): the files they name are written
MEMORY_CODE = re.compile(r"\bopen\s*\(|write_text|write_bytes|writeFile|appendFile|shutil\.(?:copy|move)|\.rename\(")
MEMORY_PATH = re.compile(r"[\"']([^\"'\s]*(?:memory\.md|agent-memory)[^\"'\s]*)[\"']", re.I)
INTERPRETER = re.compile(r"(?:python[\d.]*|node(?:js)?|deno|bun|perl|ruby|php)")
CODE_FLAGS = {"-c", "-e", "-E", "--eval", "-p", "--print", "-r"}


def memory_words(command):
    """What a shell text writes and runs, judged on its words, never on quoted text or the body of a
    here-document fed to a command that is not a shell or an interpreter: (redirection targets,
    NAME=value assignments made where a command starts, the code it hands an interpreter)."""
    targets, env, code, bodies = [], {}, [], []
    lines = logical_lines(command.replace("\\\n", " "), bodies)
    for line in lines + [b for line in lines for b in substitutions(line)]:
        start = True
        words = tokenize(line)
        for i, tok in enumerate(words):
            if ">" in tok and set(tok) <= set("<>&|;()"):  # > >> >| &> &>> <> (and ;> when glued)
                if i + 1 < len(words):
                    targets.append(words[i + 1])
            elif start and (m := ASSIGN.match(tok)):
                env[m.group(1)] = tok[m.end():]
                continue
            elif start and tok == "export":
                continue
            start = bool(tok) and set(tok) <= set(";&|()")
    for seg in segments(command):
        argv = seg.get("argv") or []
        if seg.get("nested") or not argv:
            continue
        if Path(argv[0]).name in SHELLS and "-c" in argv[1:-1]:
            more = memory_words(argv[argv.index("-c") + 1])
            targets, code = targets + more[0], code + more[2]
            env.update(more[1])
        elif INTERPRETER.fullmatch(Path(argv[0]).name):
            code += [argv[i + 1] for i, a in enumerate(argv[:-1]) if a in CODE_FLAGS]
    for opener, body in bodies:  # a here-document read by a shell is commands, by an interpreter code
        argv = next((s["argv"] for s in reversed(segments(opener)) if s.get("argv")), [])
        name = Path(argv[0]).name if argv else ""
        if name in SHELLS:
            more = memory_words(body)
            targets, code = targets + more[0], code + more[2]
        elif INTERPRETER.fullmatch(name):
            code.append(body)
    return targets, env, code


def memory_write(command, cwd):
    """For the kit verifier (in every repo): the memory file this command writes outside its one
    memory folder, <main checkout>/.kit/agent-memory/kit-verifier (subagent_start.py names it),
    else None. A write counts when its target (a redirection, tee, the destination of cp/mv/install/
    ln/rsync, dd's of=, a file sed -i/perl -i/truncate names, or a quoted path in code given to an
    interpreter that opens or writes a file: best effort) is a MEMORY.md (any case: macOS), lies in
    an agent-memory folder, or is made after a `cd` into one; plain NAME=value variables are put in,
    and a target still holding a variable counts as outside. Quoted text and here-document bodies
    are data (a note that mentions MEMORY.md is not a write). Temp folders are left alone (fixtures)."""
    flat = re.sub(r"[\"'\\]", "", command).lower()
    if "memory.md" not in flat and "agent-memory" not in flat:
        return None
    main = kitlib.main_checkout(cwd)
    stable = Path(os.path.realpath(str(kitlib.state_entry(main, MEMORY_NAME)))) if main else None
    targets, env, code = memory_words(command)
    base = Path(cwd)
    segs = [s for s in segments(command) if s.get("argv")]
    found = next((s["argv"][1] for s in segs if Path(s["argv"][0]).name == "cd" and len(s["argv"]) > 1), None)
    if found:
        base = Path(os.path.expanduser(with_vars(found, env)))
        base = base if base.is_absolute() else Path(cwd) / base
    temps = [Path(os.path.realpath(str(t))) for t in temp_roots()]
    for seg in segs:  # cp/mv/install/ln/rsync: the destination is the last argument (or -t's)
        argv = seg["argv"]
        name = Path(argv[0]).name
        if name in MEMORY_COPIERS:
            args = [a for a in argv[1:] if not a.startswith("-")]
            dest = next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("-t", "--target-directory")), None)
            if dest or len(args) >= 2:
                targets.append(dest or args[-1])
        elif name == "tee":
            targets += [a for a in argv[1:] if not a.startswith("-")]
        elif name == "dd":
            targets += [a[3:] for a in argv[1:] if a.startswith("of=")]
        elif name == "truncate" or (name in MEMORY_EDITORS and any(
                a.startswith("-i") or a == "--in-place" or re.fullmatch(r"-\w*i\w*", a) for a in argv[1:])):
            targets += [a for a in argv[1:] if not a.startswith("-") and re.search(r"(?i)memory\.md|agent-memory", a)]
    for text in code:  # python/node/perl writing a file: any quoted path naming memory in its code
        if MEMORY_CODE.search(text):
            targets += MEMORY_PATH.findall(text)
    for raw in targets:
        target = with_vars(raw, env)
        if target.startswith("&") or target == "/dev/null":
            continue
        path = Path(os.path.expanduser(target))
        path = Path(os.path.realpath(str(path if path.is_absolute() else base / path)))
        if not (path.name.lower() == "memory.md" or "agent-memory" in [p.lower() for p in path.parts]
                or "agent-memory" in [p.lower() for p in base.parts]):
            continue
        if "$" not in target and any(under(path, t) for t in temps):
            continue
        if "$" in target or stable is None or not under(path, stable):
            return target
    return None


def main():
    data = kitlib.read_input()
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or os.getcwd())
    root = Path(os.path.normpath(str(kitlib.git_root(cwd) or cwd)))
    if tool == "Bash" and data.get("agent_id") and data.get("agent_type") == "kit:verifier":
        try:
            stray = memory_write(str(tool_input.get("command") or ""), cwd)
        except Exception:
            stray = None
        if stray:
            main_dir = kitlib.main_checkout(cwd)
            where = kitlib.state_entry(main_dir, MEMORY_NAME) if main_dir else "the folder the kit named at start-up"
            print(f"kit guard (memory): this writes {stray}, outside your memory folder {where}. Write the "
                  "pitfall there, by that absolute path: a memory written anywhere else is lost with its "
                  "worktree, or left untracked in the repo.", file=sys.stderr)
            return 2
    if tool == "Bash":
        config = kitlib.load_config(root)[0]
        if config is not None and (config.get("protect") or config.get("onEdit")):  # only when bash_edits.py will compare
            snapshot(root, kitlib.state_key(data))
    active, opts = settings(root)
    if not active:
        return 0
    found = None
    if tool in ("Bash", "Monitor"):
        # A Monitor command is the way out of a wait, never one. Since 2.1.314 a hook matched on
        # Bash also runs for Monitor's command, and it then arrives as tool_name "Bash" with only
        # command and description; the transcript does not hold the call yet. Live probe on
        # 2.1.317: once the matcher names Monitor the hook runs once, as tool_name "Monitor"
        # with its timeout_ms, so hooks.json names Monitor and the tool name is the discriminator.
        monitor = tool == "Monitor"
        try:
            found = None if monitor else check_wait(str(tool_input.get("command") or ""), tool_input, opts)
        except Exception:  # the wait rule never stops a command on its own failure
            found = None
        try:
            found = found or check_bash(str(tool_input.get("command") or ""), cwd, root, opts)
        except Exception as error:  # a crash would let the command run unchecked
            found = ("ask", "guard", f"the guard could not judge this command ({type(error).__name__})")
        if not found and not monitor:
            found = check_retry(str(tool_input.get("command") or ""), cwd, kitlib.state_key(data), opts)
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
    record_denial(cwd, rule, why, data.get("session_id") or "")
    if rule == "retry":
        print(f"kit guard (retry): {why}; another try will go the same way. Stop retrying: say what the last "
              "attempt printed and hand the step back (`needs push`, `needs rebase`, `needs merge`), or change "
              "what is wrong first. A new commit or a different command is a fresh start.", file=sys.stderr)
        return 2
    if rule == "hook-bypass":
        print(f"kit guard (hook-bypass): {why}. {HOOKS_FIX}. Blocked whatever the "
              "permission mode; a project can allow a specific command with guard.allowCommands in "
              ".claude/kit.json.", file=sys.stderr)
        return 2
    if rule == "wait":
        print(f"kit guard (wait): {why} holds this turn with no progress and no alarm if it hangs. "
              f"Instead, {WAIT_FIX}. A short sleep ({sleep_limit(opts):g} s or less) is fine.", file=sys.stderr)
        return 2
    print(f"kit guard ({rule}): {why}. Blocked by the kit's guardrails whatever the permission mode. "
          "Find a safer way (work inside the repo, on a branch, through a PR), or ask the user; they "
          "can allow a specific command with guard.allowCommands in .claude/kit.json.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
