#!/usr/bin/env python3
"""kit:overnight runner: many small, verified steps toward one objective, unattended.

Each iteration is a fresh headless agent session (`claude -p`), so no context builds up.
After each iteration the runner, not the agent, decides what happens to the change:
  - changed files and the gate passes  -> one commit on the run's branch
  - gate fails, or nothing changed     -> `git reset --hard` + `git clean -fd`, counts as a failure
  - agent reports done / stop condition met -> commit what passed and stop
  - agent reports blocked              -> undo, stop, a human must decide
Caps are all optional: iterations, USD, tokens. With none set the run goes on until the stop
condition holds or --max-failures consecutive iterations fail.
Memory between iterations is a notes.md file in the run directory, which the runner also
writes to (one line per iteration outcome) so the next session knows what failed and why.

Method adapted from kunchenguid/gnhf (MIT): one small step per iteration, a commit per
successful one, reset on failure, notes as memory, stop condition, caps. Nothing copied.

Standard library only, Python 3.9+. Run with --help for the options.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# The kit's working state lives in `.kit/` at the repo root. It used to live in `.claude/`, which
# Claude Code protects, so a background thread's every write there waited on an owner prompt.
# A project the kit has not moved yet keeps its runs where they are (kitlib.state_entry; this
# script is standalone, so it repeats the rule here).
STATE_DIR, LEGACY_STATE_DIR = ".kit", ".claude"
LEGACY_STATE = ("lead", "evidence", "overnight", "agent-memory/kit-verifier")

REPORT_SCHEMA = {
    "type": "object",
    "required": ["status", "summary", "stop_condition_met"],
    "properties": {
        "status": {"type": "string", "enum": ["progress", "no-op", "blocked", "done"]},
        "summary": {"type": "string", "description": "one line; becomes the commit message"},
        "stop_condition_met": {"type": "boolean"},
    },
}

# Appended to every iteration's system prompt. Current models sometimes end an unattended turn
# with a status note that announces the next step instead of taking it; naming that early stop
# makes it rarer (Anthropic's Opus 5.5 prompting guide, "Unattended agentic runs").
UNATTENDED = (
    "This is an unattended run: nobody reads your messages until it ends, and nobody will answer a "
    "question. A turn that ends with a summary announcing the next step, an offer to continue, or a "
    "list of decisions that don't block you ends this iteration with nothing done. Finish the step "
    "you chose, then give your report. An error, a timeout or a failing tool is not a blocker: "
    "diagnose it and work through it. Stop early only when nothing can move without a "
    "human; then report blocked and say what they must decide. Never take destructive or "
    "irreversible actions outside the repository."
)

CONTINUE = (
    "Your report says progress, but the working tree has no change. If you announced a step, take "
    "it now and finish it; if nothing is worth changing, report no-op; if a human must decide, "
    "report blocked. Then give your report again."
)

RATE_LIMIT = re.compile(r"rate.?limit|usage limit|hit your .{0,20}limit|session limit|weekly limit|overloaded|\b429\b", re.I)

# Exits of `claude -p` that no later iteration can recover from, so the run stops at once with the
# fix instead of spending --max-failures "no change" iterations. Each comes from the Claude Code
# CHANGELOG (anthropics/claude-code, read 2026-11-09):
#   2.1.314 "Fixed `claude -p` exiting with code 0 and no output when startup failed; it now prints
#           the error and exits 1"
#   2.1.317 "Fixed `claude -p` exiting 0 when a full disk or quota lost its transcript or
#           ~/.claude.json writes; it now prints an error and, in text and json output, exits 1."
#   2.1.319 "Fixed `claude -p` exiting 0 in auto mode when its actions were refused because no safety
#           check was available: text and JSON output now exit 1" and "Changed auto mode with
#           telemetry or feature flags off, including behind LLM gateways: calls the server can't
#           check are asked about or denied, with no fallback to the built-in classifier; set
#           `CLAUDE_CODE_AUTO_MODE_SERVER=0` to keep using it"
# Where the text lands (the headless page): "When a failure happens inside the run, such as missing
# authentication, Claude Code prints the failure as the result on stdout"; a startup failure prints
# to stderr with no result at all. The 2.1.319 result also carries `stopped_by_permission_check`,
# which the CLI's own result schema describes as "A permission check ended this turn by itself, and
# nobody asked for the stop. Today only auto mode does so, after a run of responses for which it
# got no usable safety verdict." The patterns are the 2.1.319 build's wording for each case.
NO_SAFETY_CHECK = re.compile(r"no (?:usable )?safety (?:check|verdict)|auto mode (?:is )?unavailable|"
                             r"auto mode[^.\n]{0,40}can.?.?t check|could not evaluate this action|"
                             r"classifier unavailable|check had no usable answer|"
                             r"safety check[^.\n]{0,80}(?:isn.t|is not|not) (?:running|available|getting through)", re.I)
FULL_DISK = re.compile(r"could not save[^\n]{0,160}(?:disk is full|quota is used up|ENOSPC|EDQUOT)|"
                       r"no space left on device|session_writes_lost", re.I)
STARTUP_FAILED = re.compile(r"startup failed|refused to start|could not start|not logged in|claude auth login|"
                            r"please run /login|failed to authenticate|authentication required|"
                            r"invalid (?:api key|auth token)|not valid json", re.I)
AUTO_MODE_FIX = ("auto mode has no server check here: unset DISABLE_TELEMETRY / CLAUDE_CODE_DISABLE_FEATURE_FLAGS, "
                 "or set CLAUDE_CODE_AUTO_MODE_SERVER=0")
LOGIN_MARGIN_S = 2 * 3600  # an iteration that outlives the claude.ai sign-in is wasted


def git(root, *args, check=True):
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and out.returncode != 0:
        raise SystemExit(f"overnight: git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def dirty(root):
    return bool(git(root, "status", "--porcelain", "--untracked-files=all"))


def undo(root, to="HEAD"):
    git(root, "reset", "-q", "--hard", to)
    git(root, "clean", "-q", "-fd")  # excluded/ignored files (the run directory) survive


def runs_dir(root, main=None):
    """`.kit/overnight` of this checkout, or `.claude/overnight` where runs already are. A new run in
    a project whose main checkout still keeps its state in `.claude` (and has no `.kit`) goes
    there too, so one project never has two layouts."""
    root = Path(root)
    for name in (STATE_DIR, LEGACY_STATE_DIR):
        if (root / name / "overnight").is_dir():
            return root / name / "overnight"
    main = Path(main) if main else root
    if not (main / STATE_DIR).is_dir() and any((main / LEGACY_STATE_DIR / n).is_dir() for n in LEGACY_STATE):
        return root / LEGACY_STATE_DIR / "overnight"
    return root / STATE_DIR / "overnight"


def exclude_runs_dir(root, runs=None):
    """Keep run directories (and the gate's evidence) out of git without touching the project's
    .gitignore. `undo` runs `git clean -fd`, so an unexcluded run directory would be deleted by the
    first failed iteration: this runs before that one. One line per folder, never all of `.kit/`.
    The same rule as the kit's kitlib.add_exclude_lines (this script stands alone): under a lock
    in the git dir, read the file, append only the missing lines, replace it in one step."""
    exclude = Path(git(root, "rev-parse", "--git-path", "info/exclude"))
    if not exclude.is_absolute():
        exclude = Path(root) / exclude
    runs = Path(runs) if runs else runs_dir(root)
    state = runs.parent.name
    wanted = [f"/{state}/overnight/", f"/{state}/evidence/"]
    if state != LEGACY_STATE_DIR and (Path(root) / LEGACY_STATE_DIR / "evidence").is_dir():
        wanted.append(f"/{LEGACY_STATE_DIR}/evidence/")
    add_lines(exclude, wanted)


def add_lines(path, wanted, wait=2.0):
    """Append the lines of `wanted` that `path` lacks, never removing or rewriting one."""
    import fcntl
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".kit-lock"), "a") as lock:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{path} is locked by another process; try again") from None
                time.sleep(0.05)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [line for line in dict.fromkeys(wanted) if line not in text.splitlines()]
        if not missing:
            return
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text + ("" if text.endswith("\n") or not text else "\n") + "\n".join(missing) + "\n")
            os.chmod(tmp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def slugify(text, limit=32):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "run"


def kit_config(root):
    """The checkout's .claude/kit.json, else its main checkout's: kit.json is personal and kept out
    of git by default, so a linked worktree has none of its own."""
    path = Path(root) / ".claude" / "kit.json"
    if path.exists():
        return path
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    if common and Path(common).name == ".git" and (Path(common).parent / ".claude" / "kit.json").exists():
        return Path(common).parent / ".claude" / "kit.json"
    return path


def kit_gate(root):
    path = kit_config(root)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        return None
    return cfg.get("verify") or cfg.get("check")


def sandbox_settings(checkout):
    """The project's sandbox block from .claude/settings.local.json (where the kit's Safety:
    Sandbox, or /sandbox, writes it), when it is on. A worktree does not carry that untracked
    file, so the runner passes the block to each iteration with --settings."""
    try:
        local = json.loads((Path(checkout) / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    block = local.get("sandbox") if isinstance(local, dict) else None
    return block if isinstance(block, dict) and block.get("enabled") is True else None


def run_gate(cmd, root, timeout):
    if not cmd:
        return True, "no gate configured"
    try:
        out = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"gate timed out after {timeout}s"
    tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-15:])
    return out.returncode == 0, tail


def tokens_of(usage):
    """Input, cache-write and output tokens. Cache reads are re-sent context and are excluded."""
    usage = usage or {}
    return sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "output_tokens"))


def parse_report(data):
    report = data.get("structured_output")
    if isinstance(report, dict):
        return report
    text = data.get("result") or ""
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text, re.S))):
        try:
            cand = json.loads(match.group(0))
        except ValueError:
            continue
        if isinstance(cand, dict) and "status" in cand:
            return cand
    return None


def fatal_reason(data, text):
    """Why no later iteration would do better, with the fix, or None. `data` is the JSON result
    (empty when there was none), `text` the result, its errors and stderr."""
    if data.get("stopped_by_permission_check") is True or NO_SAFETY_CHECK.search(text):
        return AUTO_MODE_FIX
    if data.get("subtype") == "session_writes_lost" or FULL_DISK.search(text):
        return "the disk is full or over quota and claude -p lost its transcript: free space on that disk, then --resume"
    match = STARTUP_FAILED.search(text)
    if data.get("startup_failure_reason") or match:
        why = data.get("startup_failure_reason")
        if not why:
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            why = text[start:end if end >= 0 else len(text)].strip()[:160]
        return f"claude -p could not start ({why}): fix the login or settings it names, then --resume"
    return None


def parse_expiry(value):
    """Epoch seconds of a result's `credential_expires_at`, or None. 2.1.318: "Added the date a
    stored claude.ai sign-in ends to `claude auth status` (`loginExpiresAt`) and to `claude -p` JSON
    results (`credential_expires_at`)"; the CLI writes it with toISOString(), so
    2026-11-20T08:00:00.000Z. Fail-open: a missing or unreadable value is None and changes nothing."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def build_prompt(args, iteration, notes_path, gate):
    notes = notes_path.read_text(encoding="utf-8").strip() if notes_path.exists() else ""
    stop = args.stop_when or "none given: keep improving until the run's caps or failures end it"
    gate_line = f"`{gate}`" if gate else "the project's obvious tests/lint/build"
    return f"""You are iteration {iteration} of an unattended overnight run. Nobody will answer questions.

OBJECTIVE: {args.objective}
STOP CONDITION: {stop}

NOTES FROM EARLIER ITERATIONS (your only memory; read them first):
{notes or "(none yet: this is the first iteration)"}

Do exactly one small, self-contained step toward the objective:
1. Pick the most valuable next step that fits in one iteration. Do not repeat a step the notes
   mark as done, or one that failed for a reason that still holds.
2. Make the change. Follow CLAUDE.md / AGENTS.md. Do not commit, push, create branches or
   rewrite git history: the runner commits after it checks your work.
3. Check it yourself with {gate_line}. The runner runs the same gate and throws the change
   away if it fails.
4. Append 1-3 lines to {notes_path}: what you did, what you learned, what should come next.
   If the file passes ~100 lines, rewrite the older lines into a short summary.
5. Report: status "progress" (you changed something that moves toward the objective), "no-op"
   (nothing worth changing), "blocked" (a human decision is needed: say which in the summary)
   or "done" (the objective is complete); stop_condition_met true only if the stop condition
   holds after your change; summary: one line, used as the commit message.
Never touch files outside this repository, secrets, credentials or production systems.
"""


def agent_command(args, prompt, budget_left=None, resume=None):
    """The claude -p command line of one iteration."""
    cmd = shlex.split(args.agent_cmd) + ["-p", prompt, "--output-format", "json",
                                         "--json-schema", json.dumps(REPORT_SCHEMA)]
    if not args.no_unattended_note:
        cmd += ["--append-system-prompt", UNATTENDED]
    if resume:
        cmd += ["--resume", resume]
    if args.effort:
        cmd += ["--effort", args.effort]
    # headless sessions cannot answer a prompt: anything that would ask is denied at once instead
    # of waiting (claude -p starts in the manual mode since 2.1.302 unless a mode is given)
    cmd += ["--permission-mode", args.permission_mode or "auto", "--permission-prompts", "none"]
    if args.model:
        cmd += ["--model", args.model]
    if args.fallback_model:
        cmd += ["--fallback-model", args.fallback_model]
    if args.max_turns:
        cmd += ["--max-turns", str(args.max_turns)]
    if getattr(args, "sandbox_block", None):
        cmd += ["--settings", json.dumps({"sandbox": args.sandbox_block})]
    per_iter = [b for b in (budget_left, args.iteration_usd) if b is not None]
    if per_iter:
        cmd += ["--max-budget-usd", f"{max(min(per_iter), 0.01):.2f}"]
    return cmd


def run_agent(args, prompt, root, budget_left, resume=None):
    cmd = agent_command(args, prompt, budget_left, resume)
    try:
        # KIT_HEADLESS: the kit's hooks skip anything that needs a person to answer
        out = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=args.iteration_timeout,
                             env={**os.environ, "KIT_HEADLESS": "1"})
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"iteration timed out after {args.iteration_timeout}s", "cost": 0.0, "tokens": 0}
    try:
        data = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
    except ValueError:
        data = {}
    cost = float(data.get("total_cost_usd") or 0.0)
    tokens = tokens_of(data.get("usage"))
    expires = data.get("credential_expires_at")  # when the claude.ai sign-in ends (2.1.318); absent on an API key
    if out.returncode != 0 or data.get("is_error") or not data:
        err = (data.get("subtype") or "") + " " + (data.get("result") or out.stderr or out.stdout)[-400:]
        errors = data.get("errors") if isinstance(data.get("errors"), list) else []
        text = "\n".join(s for s in (data.get("result"), *map(str, errors), out.stderr, "" if data else out.stdout) if s)
        return {"ok": False, "error": err.strip(), "cost": cost, "tokens": tokens, "expires": expires,
                "fatal": fatal_reason(data, text),
                "rate_limited": bool(RATE_LIMIT.search(err)), "budget": "budget" in (data.get("subtype") or "")}
    return {"ok": True, "report": parse_report(data), "cost": cost, "tokens": tokens,
            "session": data.get("session_id"), "expires": expires}


def spend_cap_reached(args, state):
    """The cost and token caps only: a continuation belongs to the current iteration, so the
    iteration cap must not stop it."""
    return ((args.max_usd is not None and state["cost"] >= args.max_usd)
            or (args.max_tokens is not None and state["tokens"] >= args.max_tokens))


def cap_reached(args, state):
    if args.max_iterations and state["iteration"] >= args.max_iterations:
        return f"max iterations ({args.max_iterations})"
    if args.max_usd is not None and state["cost"] >= args.max_usd:
        return f"budget USD {args.max_usd:.2f} spent ({state['cost']:.2f})"
    if args.max_tokens is not None and state["tokens"] >= args.max_tokens:
        return f"token cap {args.max_tokens} reached ({state['tokens']})"
    return None


DETACH_WAIT = 5  # seconds the launcher watches the run start, so an early refusal is not lost in a log


def detach(argv):
    """Start this runner again with `argv` in a new process session (setsid), its output in a log
    file under the runs folder, and return at once. The coordinator launches the night from one
    Bash call that has to return: a run tied to that call's process group, or to a background
    command, would end with the call or the session. A run that stops within DETACH_WAIT seconds
    (a dirty tree, a bad flag) prints its log and exit code here instead."""
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main = Path(common).parent if Path(common).name == ".git" else root
    runs = runs_dir(root, main)
    exclude_runs_dir(root, runs)  # before the log exists, so the run's clean-tree check passes
    (runs / "launch").mkdir(parents=True, exist_ok=True)
    log_path = runs / "launch" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
    with open(log_path, "w", encoding="utf-8") as log, open(os.devnull) as nothing:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *argv], cwd=Path.cwd(),
                                 stdin=nothing, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        code = child.wait(timeout=DETACH_WAIT)
    except subprocess.TimeoutExpired:
        print(f"overnight: started in the background, pid {child.pid}; log {log_path}")
        print(log_path.read_text(encoding="utf-8", errors="replace").rstrip())
        return 0
    print(log_path.read_text(encoding="utf-8", errors="replace").rstrip())
    print(f"overnight: the run ended at once (exit {code}); log {log_path}")
    return code


def push_branch(root, branch):
    """Push the run's branch to origin once, so the morning result can be read from a phone. A
    missing remote or a refused push is recorded, never fatal: the commits stay on the branch."""
    if not git(root, "remote", "get-url", "origin", check=False):
        return "skipped: no origin remote"
    try:
        out = subprocess.run(["git", "-C", str(root), "push", "-q", "-u", "origin", branch],
                             capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "failed: git push took over 300 s"
    if out.returncode != 0:
        return f"failed: {(out.stderr.strip().splitlines() or ['git push failed'])[-1][:200]}"
    return f"pushed {branch} to origin"


def main(argv=None):
    p = argparse.ArgumentParser(description="kit:overnight - unattended loop of small verified steps")
    p.add_argument("objective", nargs="?", help="what to improve (or use --objective-file)")
    p.add_argument("--objective-file", help="read the objective from this file")
    p.add_argument("--stop-when", help="natural-language condition that ends the run when it holds")
    p.add_argument("--max-iterations", type=int, default=None, help="cap on iterations (default: none)")
    p.add_argument("--max-usd", type=float, default=None, help="cap on total cost in USD (default: none)")
    p.add_argument("--max-tokens", type=int, default=None, help="cap on input+cache-write+output tokens (default: none)")
    p.add_argument("--iteration-usd", type=float, default=None, help="cap per iteration in USD (default: none)")
    p.add_argument("--max-failures", type=int, default=3, help="stop after this many consecutive failed iterations (default 3)")
    p.add_argument("--gate", help="command that must pass before a commit (default: kit.json verify, else check)")
    p.add_argument("--gate-timeout", type=int, default=1800)
    p.add_argument("--iteration-timeout", type=int, default=3600)
    p.add_argument("--rate-limit-wait", type=int, default=900, help="seconds to wait on a rate limit before retrying (0 = count as failure)")
    p.add_argument("--max-rate-limit-waits", type=int, default=24,
                   help="waits in a row before a rate limit counts as a failure (default 24: 6 h at 900 s)")
    p.add_argument("--branch", help="branch for the run (default overnight/<slug>-<run id>)")
    p.add_argument("--worktree", help="run in a new git worktree at this path instead of the current checkout")
    p.add_argument("--permission-mode", help="passed to the agent (default auto: a headless session cannot answer a prompt; "
                                             "anything that would ask is denied, whatever the mode)")
    p.add_argument("--model", help="passed to the agent (a Fable or Mythos model needs --allow-credits: in -p mode it "
                                   "bills usage credits without asking)")
    p.add_argument("--fallback-model", help="passed to the agent: model(s) to fall back to when the main one is overloaded")
    p.add_argument("--allow-credits", action="store_true", help="allow a model that bills usage credits (Fable, Mythos)")
    p.add_argument("--max-turns", type=int, default=None, help="passed to the agent: cap on turns per iteration")
    p.add_argument("--no-unattended-note", action="store_true",
                   help="do not append the kit's note about unattended runs to the agent's system prompt")
    p.add_argument("--effort", help="passed to the agent: low, medium, high, xhigh or max (default: your settings)")
    p.add_argument("--max-continuations", type=int, default=2,
                   help="times to resume an iteration that reports progress without a change (default 2)")
    p.add_argument("--no-sandbox", action="store_true",
                   help="do not pass the project's sandbox settings to the iterations")
    p.add_argument("--agent-cmd", default=os.environ.get("KIT_OVERNIGHT_AGENT", "claude"))
    p.add_argument("--resume", help="run directory of an earlier run to continue")
    p.add_argument("--dry-run", action="store_true", help="print the plan and the first prompt, run nothing")
    p.add_argument("--detach", action="store_true",
                   help="start the run in its own process session, with its output in a log file, and return at once")
    p.add_argument("--push", action="store_true",
                   help="when the run ends with commits, push its branch to origin once (a failed push is noted, not fatal)")
    argv = sys.argv[1:] if argv is None else list(argv)
    args = p.parse_args(argv)
    if args.model and re.search(r"fable|mythos", args.model, re.I) and not args.allow_credits:
        p.error(f"--model {args.model} bills usage credits in headless runs without asking; pass --allow-credits "
                "if that is what you want, or use an Opus model")
    given = {a.dest for a in p._actions
             if any(tok.split("=", 1)[0] in a.option_strings for tok in argv if tok.startswith("-"))}
    if args.detach and not args.dry_run:
        return detach([a for a in argv if a != "--detach"])

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    main_checkout = root
    state = None
    if args.resume:
        run_dir = Path(args.resume).resolve()
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        for key, val in state["args"].items():  # a flag given now wins; an omitted one keeps the saved value
            if key in ("resume", "dry_run", "detach"):
                continue
            if key not in given:
                setattr(args, key, val)
        state["failures"] = 0  # a resumed run gets a fresh failure streak
        state["stop_reason"] = None
        state.pop("credential_expires_at", None)  # the sign-in may have been renewed; the first iteration reads it again
        root = Path(state["root"])
    else:
        if args.objective_file:
            args.objective = Path(args.objective_file).read_text(encoding="utf-8").strip()
        if not args.objective:
            p.error("give an objective (argument or --objective-file)")
        if not args.worktree and dirty(root):
            raise SystemExit("overnight: working tree not clean; commit or stash first, or use --worktree")
        run_id = time.strftime("%Y%m%d-%H%M%S")
        branch = args.branch or f"overnight/{slugify(args.objective)}-{run_id}"
        if args.worktree:
            root = Path(args.worktree).resolve()
        state = {"root": str(root), "branch": branch, "run_id": run_id, "iteration": 0, "cost": 0.0,
                 "tokens": 0, "commits": [], "failures": 0, "stop_reason": None,
                 "args": {k: v for k, v in vars(args).items() if k not in ("resume", "dry_run", "detach")}}
        common = git(Path.cwd(), "rev-parse", "--path-format=absolute", "--git-common-dir")
        main = Path(common).parent if Path(common).name == ".git" else root
        run_dir = runs_dir(root, main) / run_id

    # the gate comes from the checkout the run starts from (a worktree may not exist yet)
    gate = args.gate or kit_gate(root if root.exists() else main_checkout)
    if args.no_sandbox:
        args.sandbox_block = None
    elif args.resume and "sandbox_block" in state:
        args.sandbox_block = state["sandbox_block"]  # a worktree has no settings.local.json of its own
    else:
        args.sandbox_block = sandbox_settings(main_checkout)
    state["sandbox_block"] = args.sandbox_block
    notes_path = run_dir / "notes.md"
    caps = [c for c in (args.max_iterations and f"{args.max_iterations} iterations",
                        args.max_usd is not None and f"USD {args.max_usd:.2f}",
                        args.max_tokens is not None and f"{args.max_tokens} tokens") if c]
    print(f"overnight: branch {state['branch']} in {root}")
    print(f"overnight: gate {gate or 'none (the agent checks itself)'}; caps: {', '.join(caps) or 'NONE'}"
          f"; stops after {args.max_failures} failures in a row"
          + (f" or when: {args.stop_when}" if args.stop_when else ""))
    print("overnight: sandbox " + ("on (the project's .claude/settings.local.json, passed with --settings)"
                                   if args.sandbox_block else "off (host: the kit guard still applies)"))
    if not caps:
        print("overnight: WARNING no budget set - the run ends only on the stop condition, "
              f"{args.max_failures} consecutive failures, or Ctrl-C")
    if args.dry_run:  # nothing is created or checked out
        shown = [a if a != "<prompt>" else "'<the prompt below>'" for a in agent_command(args, "<prompt>", args.iteration_usd)]
        print("agent command: " + " ".join(a if a.startswith("'") else shlex.quote(a) for a in shown))
        print("\n" + build_prompt(args, state["iteration"] + 1, notes_path, gate))
        return 0

    if args.resume:
        if dirty(root):
            raise SystemExit("overnight: the run's checkout has uncommitted changes; commit or stash them first")
        git(root, "checkout", "-q", state["branch"])
    elif args.worktree:
        git(main_checkout, "worktree", "add", "-q", "-b", state["branch"], str(root))
    else:
        git(root, "checkout", "-q", "-b", state["branch"])

    run_dir.mkdir(parents=True, exist_ok=True)
    exclude_runs_dir(root, run_dir.parent)
    (run_dir / "objective.md").write_text(args.objective + "\n", encoding="utf-8")
    log = (run_dir / "log.jsonl").open("a", encoding="utf-8")

    def save():
        (run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    def note(line):
        with notes_path.open("a", encoding="utf-8") as fh:
            fh.write(f"- [runner] #{state['iteration']}: {line}\n")

    start = None  # HEAD at the start of the current iteration

    def failed(reason):
        undo(root, start or "HEAD")
        state["failures"] += 1
        note(f"failed and undone - {reason}")
        print(f"overnight: #{state['iteration']} failed ({state['failures']} in a row): {reason}")
        save()

    rate_waits = 0
    try:
        while True:
            reason = cap_reached(args, state)
            if reason:
                state["stop_reason"] = reason
                break
            if state["failures"] >= args.max_failures:
                state["stop_reason"] = f"{args.max_failures} consecutive failed iterations"
                break
            expiry = parse_expiry(state.get("credential_expires_at"))
            if expiry is not None and expiry - time.time() < LOGIN_MARGIN_S:
                print(f"overnight: WARNING the claude.ai sign-in ends at {state['credential_expires_at']}, in "
                      f"{max(expiry - time.time(), 0) / 3600:.1f} h: an iteration that outlives it is wasted")
                state["stop_reason"] = ("sign-in ends within 2 h: run `claude auth login` (or `claude setup-token` "
                                        "for unattended jobs), then --resume")
                break
            state["iteration"] += 1
            start = git(root, "rev-parse", "HEAD")
            left = None if args.max_usd is None else args.max_usd - state["cost"]
            res = run_agent(args, build_prompt(args, state["iteration"], notes_path, gate), root, left)
            state["cost"] += res["cost"]
            state["tokens"] += res["tokens"]
            if res.get("expires"):
                state["credential_expires_at"] = res["expires"]
            log.write(json.dumps({"iteration": state["iteration"], **res}) + "\n")
            log.flush()

            if not res["ok"]:
                if res.get("fatal"):  # nothing a later iteration could do differently
                    undo(root, start)
                    note(f"run stopped - {res['fatal']}")
                    state["stop_reason"] = res["fatal"]
                    break
                if res.get("rate_limited") and args.rate_limit_wait and rate_waits < args.max_rate_limit_waits:
                    rate_waits += 1
                    state["iteration"] -= 1
                    undo(root, start)
                    print(f"overnight: rate or usage limit, waiting {args.rate_limit_wait}s ({rate_waits})")
                    time.sleep(args.rate_limit_wait)
                    continue
                total_cap_binds = left is not None and (args.iteration_usd is None or left <= args.iteration_usd)
                if res.get("budget") and total_cap_binds:
                    undo(root, start)
                    state["stop_reason"] = "budget reached during an iteration"
                    break
                failed(f"agent error: {res['error'][:200]}")
                continue
            rate_waits = 0

            # The runner commits, not the agent: fold any commit the agent made back into the tree,
            # so it goes through the gate like everything else.
            if git(root, "rev-parse", "HEAD") != start:
                git(root, "reset", "-q", "--soft", start)

            report = res["report"] or {"status": "progress", "summary": "", "stop_condition_met": False}
            # "progress" with nothing changed is an early stop, not a result: resume the same
            # session and ask for the step, a bounded number of times
            nudges = 0
            fatal = None
            while (report.get("status") == "progress" and not dirty(root) and res.get("session")
                   and nudges < args.max_continuations and not spend_cap_reached(args, state)):
                nudges += 1
                left = None if args.max_usd is None else args.max_usd - state["cost"]
                more = run_agent(args, CONTINUE, root, left, resume=res["session"])
                state["cost"] += more["cost"]
                state["tokens"] += more["tokens"]
                log.write(json.dumps({"iteration": state["iteration"], "continuation": nudges, **more}) + "\n")
                log.flush()
                if not more["ok"]:
                    fatal = more.get("fatal")
                    break
                res = more
                report = more["report"] or report
                if git(root, "rev-parse", "HEAD") != start:
                    git(root, "reset", "-q", "--soft", start)
            if fatal:
                undo(root, start)
                note(f"run stopped - {fatal}")
                state["stop_reason"] = fatal
                break
            status = report.get("status")
            summary = " ".join((report.get("summary") or "").split())[:120]

            if status == "blocked":
                undo(root, start)
                note(f"blocked - {summary}")
                state["stop_reason"] = f"blocked, needs a human: {summary}"
                break
            finished = status == "done" or bool(report.get("stop_condition_met"))
            if not dirty(root):
                if finished:
                    state["stop_reason"] = f"stop condition met: {summary}"
                    break
                failed(f"no change ({status}): {summary}")
                continue
            ok, out = run_gate(gate, root, args.gate_timeout)
            if not ok:
                failed(f"gate failed: {out.splitlines()[-1] if out else ''}")
                continue
            git(root, "add", "-A")
            done = subprocess.run(["git", "-C", str(root), "commit", "-q", "-m",
                                   f"overnight #{state['iteration']}: {summary or 'step'}",
                                   "-m", f"Run {state['run_id']}, objective: {args.objective[:200]}"],
                                  capture_output=True, text=True)
            if done.returncode != 0:
                failed(f"commit refused: {(done.stderr or done.stdout).strip()[-200:]}")
                continue
            sha = git(root, "rev-parse", "--short", "HEAD")
            state["commits"].append({"iteration": state["iteration"], "sha": sha, "summary": summary})
            state["failures"] = 0
            note(f"committed {sha} - {summary}")
            print(f"overnight: #{state['iteration']} committed {sha}: {summary}")
            save()
            if finished:
                state["stop_reason"] = f"stop condition met: {summary}"
                break
    except KeyboardInterrupt:
        undo(root, start or "HEAD")
        state["stop_reason"] = "interrupted"
    except BaseException as exc:  # never leave a half-done iteration without a record
        state["stop_reason"] = f"runner error: {exc!r}"[:300]
        try:
            undo(root, start or "HEAD")
        finally:
            save()
        raise
    finally:
        log.close()

    if args.push and state["commits"]:
        state["pushed"] = push_branch(root, state["branch"])
        note(f"push: {state['pushed']}")
        print(f"overnight: push {state['pushed']}")
    save()
    (run_dir / "end-state.json").write_text(json.dumps(
        {k: state[k] for k in ("branch", "iteration", "cost", "tokens", "commits", "stop_reason", "pushed") if k in state},
        indent=2), encoding="utf-8")
    print(f"overnight: stopped - {state['stop_reason']}")
    print(f"overnight: {len(state['commits'])} commits on {state['branch']} in {state['iteration']} iterations, "
          f"USD {state['cost']:.2f}, {state['tokens']} tokens; run dir {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
