---
name: overnight
description: Sets up an unattended run of small verified steps toward one objective (overnight, for hours while away) - fresh session per iteration, a commit per step that passes the gate, stop condition, optional caps on iterations, cost and tokens. Use for "keep going while I sleep", grinding on a measurable objective, or a long loop with or without a budget.
argument-hint: "[objective; optional stop condition and budget]"
---

# kit:overnight: small verified steps until the objective is met

Input: $ARGUMENTS

`/goal` and `/loop` keep one conversation going: context piles up, and nothing enforces a
token or turn cap, so a night can end with the weekly quota gone. This runner starts a fresh
`claude -p` session per iteration, lets the project's gate decide whether each step is kept,
and stops on the conditions below. The morning result is a branch of small commits to pick
from. (Method adapted from kunchenguid/gnhf, MIT. Nothing copied.)

## 1. Shape the objective

Good objectives are either **measurable** (page load under 1.5 s, coverage above 80 %, a
benchmark score up, no failing e2e scenario) or ones where the user trusts Claude's judgement
(use the app as a 7-year-old would and fix the first thing that confuses you). Write:

- **Objective:** one paragraph, with how to measure progress if there is a measure.
- **Stop condition** (optional): when the run should end on its own, e.g. "lighthouse
  performance ≥ 90 on /". Without one, the run ends on caps or failures.
- **Gate:** the command that must pass before a step is committed: `.claude/kit.json` `verify`
  by default, else `check`. Without either, the agent only checks itself; say so. A measurable
  objective deserves a gate that checks the measure.
- **Boundary:** beside the stop condition and the gate, what must not change to reach them: no
  test deleted, skipped or weakened, no gate or lint config edited, no expected output
  rewritten. Put it in the objective, since an unattended agent that cannot reach a target
  can still reach it by moving the target. A check against an outside reference (a golden
  sample, an upstream total, a diff against a reference file within a stated tolerance) beats
  one the worker can edit.

If the objective is vague, use `kit:shape` first.

## 2. Budget: defaults

Do not ask. Unless the user named caps, use `--max-iterations 40 --max-usd 25`, and say so in
your reply in one line, with how to change them. When the user says no budget, leave the caps
out and pass `--no-caps`: the run then ends only on the stop condition, 3 failed iterations in a
row, or Ctrl-C, and the reply says plainly that nothing caps it. A `--detach` run given no caps and
no `--no-caps` takes 40 iterations and USD 25 by itself.

Other knobs: `--max-tokens` (input + cache-write + output), `--iteration-usd` (cap per
iteration), `--max-turns` (per iteration), `--max-failures` (default 3), `--effort` (`medium` is a
good default for small steps; raise it only where a run shows it helps), `--fallback-model` (when
the main model is overloaded), `--permission-mode` (default `auto`: a headless session cannot
answer a prompt, so anything that would ask is denied whatever the mode). A Fable or Mythos
model bills usage credits without asking in headless runs: the runner refuses `--model fable`
unless `--allow-credits` is given. `--no-unattended-note` drops the kit's note about unattended
runs from the system prompt, to measure whether the model still needs it.

## 3. Check before launching

- The working tree is clean, or use `--worktree ../<repo>-overnight` so the user keeps working
  in the main checkout (and several runs can go in parallel).
- The gate passes on the starting commit: run it once. A red gate at the start fails every
  iteration.
- No production credentials in the environment the agent will see.
- Safety: with the project on **Sandbox** (`items.py sandbox on`) the runner
  passes the Bash sandbox to every iteration, worktrees included (`--no-sandbox` to skip); on
  **Host** the kit guard still blocks irreversible actions. For `--permission-mode
  bypassPermissions`, only inside a microVM or devcontainer, never on the bare machine.
- Dry run to show the plan and the first prompt:
  `python3 ${CLAUDE_SKILL_DIR}/scripts/overnight.py "<objective>" --stop-when "<condition>" <caps> --dry-run`
  (if `${CLAUDE_SKILL_DIR}` is not substituted, the script is in `scripts/` next to this file).

## 4. Launch

It runs for hours, so start it yourself where it survives the session. First run
`python3 ${CLAUDE_SKILL_DIR}/../../hooks/scripts/items.py away on` (a permission prompt becomes a
denial until the user writes again). Then launch with `--detach`: the runner starts again
in its own process session, output in a log under the runs folder, and the Bash call returns
within about 5 seconds with the pid and the log path, or with the error and exit code of a run
that stopped at once; when it ends, the next interactive session start says so once. Add
`--push` unless the user said not to push in this repo: when the run ends with commits it pushes the branch once, so the result can be read from a phone; with
`push=ask` in the unattended settings it leaves the branch local and the log says so. The runner
refuses a protected `--branch` (main, master, the guard's `protectedBranches`, origin's default). Do not use
Bash `run_in_background` for it: that run ends with the session. A user who wants it in their own
terminal or tmux window gets the same line without `--detach`. Example:

```
python3 <kit>/skills/overnight/scripts/overnight.py "Pretend you are a 7-year-old, use the app end to end, fix the first usability problem you meet" \
  --worktree ../app-overnight --max-iterations 40 --max-usd 25 --push --detach
```

What each iteration does: one small step, the gate, then commit (`overnight #N: <summary>`)
or `git reset --hard` + `git clean -fd`. A step that changes nothing counts as a failure. Each
iteration's system prompt gets a short note that nobody is there to answer, and an iteration
that reports progress with no change (an early stop that only announced the next step) is
resumed with the same session, at most `--max-continuations` times (default 2). The
agent reports `blocked` when a human decision is needed, which stops the run. Rate limits are
waited out (`--rate-limit-wait`, default 900 s, up to 24 times in a row: six hours;
`--max-rate-limit-waits` changes it).

Three `claude -p` exits end the run at once, with the cause and the fix on the last line, instead
of counting as three "no change" iterations (Claude Code 2.1.314-2.1.319): a startup failure, a
transcript lost to a full disk, and auto mode refusing every action because no server-side safety
check was available. The last one is an environment matter: with `DISABLE_TELEMETRY` or
`CLAUDE_CODE_DISABLE_FEATURE_FLAGS` set, or behind an LLM gateway, auto mode has no check and
denies everything; unset them, or set `CLAUDE_CODE_AUTO_MODE_SERVER=0` to keep the built-in
classifier. The runner also keeps `credential_expires_at` from the first result (a claude.ai
sign-in, 2.1.318) and stops before the next iteration once the sign-in ends within 2 hours; renew
it with `claude auth login`, or use `claude setup-token` for unattended jobs. A missing or
unreadable field changes nothing.

Run files in `.kit/overnight/<run id>/` of the checkout the run is in, as the runner prints it
(kept out of git through `.git/info/exclude`):
`objective.md`, `notes.md` (memory between iterations; the runner adds one line per outcome),
`log.jsonl`, `state.json`, `end-state.json`. Continue a stopped run with
`--resume <that folder>` (flags given again override the saved ones).

## 5. The morning after

1. Read `end-state.json` (stop reason, commits, cost) and `notes.md`.
2. `git log --oneline <base>..<branch>`: decide which commits to keep. Drop the rest with an
   interactive rebase or cherry-pick the good ones onto a fresh branch.
3. Have `kit:verifier` review the branch against the objective, then `/kit:go` to open the PR
   with evidence and a risk rating. The overnight commits are first-pass work, not reviewed work.
4. If a failure repeated in the notes, run the `kit:learn` review yourself so the next run avoids
   it; ask the user only before it changes a committed instruction file.
