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
from pathlib import Path

RUNS_DIR = Path(".claude") / "overnight"

REPORT_SCHEMA = {
    "type": "object",
    "required": ["status", "summary", "stop_condition_met"],
    "properties": {
        "status": {"type": "string", "enum": ["progress", "no-op", "blocked", "done"]},
        "summary": {"type": "string", "description": "one line; becomes the commit message"},
        "stop_condition_met": {"type": "boolean"},
    },
}

RATE_LIMIT = re.compile(r"rate.?limit|usage limit|hit your .{0,20}limit|session limit|weekly limit|overloaded|\b429\b", re.I)


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


def exclude_runs_dir(root):
    """Keep run directories out of git without touching the project's .gitignore."""
    exclude = Path(git(root, "rev-parse", "--git-path", "info/exclude"))
    if not exclude.is_absolute():
        exclude = Path(root) / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    missing = [line for line in (f"/{RUNS_DIR.as_posix()}/", "/.claude/evidence/") if line not in text.splitlines()]
    if missing:
        exclude.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "\n".join(missing) + "\n",
                           encoding="utf-8")


def slugify(text, limit=32):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "run"


def kit_gate(root):
    path = Path(root) / ".claude" / "kit.json"
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


def run_agent(args, prompt, root, budget_left):
    cmd = shlex.split(args.agent_cmd) + ["-p", prompt, "--output-format", "json",
                                         "--json-schema", json.dumps(REPORT_SCHEMA)]
    if args.permission_mode:
        cmd += ["--permission-mode", args.permission_mode]
    if args.model:
        cmd += ["--model", args.model]
    if getattr(args, "sandbox_block", None):
        cmd += ["--settings", json.dumps({"sandbox": args.sandbox_block})]
    per_iter = [b for b in (budget_left, args.iteration_usd) if b is not None]
    if per_iter:
        cmd += ["--max-budget-usd", f"{max(min(per_iter), 0.01):.2f}"]
    try:
        out = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=args.iteration_timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"iteration timed out after {args.iteration_timeout}s", "cost": 0.0, "tokens": 0}
    try:
        data = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
    except ValueError:
        data = {}
    cost = float(data.get("total_cost_usd") or 0.0)
    tokens = tokens_of(data.get("usage"))
    if out.returncode != 0 or data.get("is_error") or not data:
        err = (data.get("subtype") or "") + " " + (data.get("result") or out.stderr or out.stdout)[-400:]
        return {"ok": False, "error": err.strip(), "cost": cost, "tokens": tokens,
                "rate_limited": bool(RATE_LIMIT.search(err)), "budget": "budget" in (data.get("subtype") or "")}
    return {"ok": True, "report": parse_report(data), "cost": cost, "tokens": tokens}


def cap_reached(args, state):
    if args.max_iterations and state["iteration"] >= args.max_iterations:
        return f"max iterations ({args.max_iterations})"
    if args.max_usd is not None and state["cost"] >= args.max_usd:
        return f"budget USD {args.max_usd:.2f} spent ({state['cost']:.2f})"
    if args.max_tokens is not None and state["tokens"] >= args.max_tokens:
        return f"token cap {args.max_tokens} reached ({state['tokens']})"
    return None


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
    p.add_argument("--permission-mode", help="passed to the agent, e.g. auto or acceptEdits (default: your settings)")
    p.add_argument("--model", help="passed to the agent")
    p.add_argument("--no-sandbox", action="store_true",
                   help="do not pass the project's sandbox settings to the iterations")
    p.add_argument("--agent-cmd", default=os.environ.get("KIT_OVERNIGHT_AGENT", "claude"))
    p.add_argument("--resume", help="run directory of an earlier run to continue")
    p.add_argument("--dry-run", action="store_true", help="print the plan and the first prompt, run nothing")
    argv = sys.argv[1:] if argv is None else list(argv)
    args = p.parse_args(argv)
    given = {a.dest for a in p._actions
             if any(tok.split("=", 1)[0] in a.option_strings for tok in argv if tok.startswith("-"))}

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    main_checkout = root
    state = None
    if args.resume:
        run_dir = Path(args.resume).resolve()
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        for key, val in state["args"].items():  # a flag given now wins; an omitted one keeps the saved value
            if key in ("resume", "dry_run"):
                continue
            if key not in given:
                setattr(args, key, val)
        state["failures"] = 0  # a resumed run gets a fresh failure streak
        state["stop_reason"] = None
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
                 "args": {k: v for k, v in vars(args).items() if k not in ("resume", "dry_run")}}
        run_dir = root / RUNS_DIR / run_id

    # the gate comes from the checkout the run starts from (a worktree may not exist yet)
    gate = args.gate or kit_gate(root if root.exists() else main_checkout)
    args.sandbox_block = None if args.no_sandbox else sandbox_settings(main_checkout)
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
    exclude_runs_dir(root)
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
            state["iteration"] += 1
            start = git(root, "rev-parse", "HEAD")
            left = None if args.max_usd is None else args.max_usd - state["cost"]
            res = run_agent(args, build_prompt(args, state["iteration"], notes_path, gate), root, left)
            state["cost"] += res["cost"]
            state["tokens"] += res["tokens"]
            log.write(json.dumps({"iteration": state["iteration"], **res}) + "\n")
            log.flush()

            if not res["ok"]:
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

    save()
    (run_dir / "end-state.json").write_text(json.dumps(
        {k: state[k] for k in ("branch", "iteration", "cost", "tokens", "commits", "stop_reason")}, indent=2),
        encoding="utf-8")
    print(f"overnight: stopped - {state['stop_reason']}")
    print(f"overnight: {len(state['commits'])} commits on {state['branch']} in {state['iteration']} iterations, "
          f"USD {state['cost']:.2f}, {state['tokens']} tokens; run dir {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
