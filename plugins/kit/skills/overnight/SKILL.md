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

If the objective is vague, use `kit:shape` first.

## 2. Budget: ask

Ask with AskUserQuestion (header "Budget"); if nobody can answer (a non-interactive run), pick
caps, write them in the command and say they are your assumption:

1. **Caps (Recommended):** max iterations and/or USD, e.g. `--max-iterations 40 --max-usd 25`.
2. **Iterations only:** e.g. `--max-iterations 40`.
3. **No budget:** the run ends only on the stop condition, 3 failed iterations in a row, or
   Ctrl-C. Fine on a subscription the user is happy to spend; say plainly that nothing caps it.

Other knobs: `--max-tokens` (input + cache-write + output), `--iteration-usd` (cap per
iteration), `--max-failures` (default 3), `--permission-mode auto` (headless sessions cannot
answer permission prompts; without allow rules or auto mode most iterations fail).

## 3. Check before launching

- The working tree is clean, or use `--worktree ../<repo>-overnight` so the user keeps working
  in the main checkout (and several runs can go in parallel).
- The gate passes on the starting commit: run it once. A red gate at the start fails every
  iteration.
- No production credentials in the environment the agent will see.
- Dry run to show the plan and the first prompt:
  `python3 ${CLAUDE_SKILL_DIR}/scripts/overnight.py "<objective>" --stop-when "<condition>" <caps> --dry-run`
  (if `${CLAUDE_SKILL_DIR}` is not substituted, the script is in `scripts/` next to this file).

## 4. Launch

It runs for hours, so start it where it survives the session: give the user the line to run in
a terminal or a tmux window, or, if they ask you to start it, launch it with Bash
`run_in_background`. Example:

```
python3 <kit>/skills/overnight/scripts/overnight.py "Pretend you are a 7-year-old, use the app end to end, fix the first usability problem you meet" \
  --worktree ../app-overnight --max-iterations 40 --max-usd 25 --permission-mode auto
```

What each iteration does: one small step, the gate, then commit (`overnight #N: <summary>`)
or `git reset --hard` + `git clean -fd`. A step that changes nothing counts as a failure. The
agent reports `blocked` when a human decision is needed, which stops the run. Rate limits are
waited out (`--rate-limit-wait`, default 900 s, up to 4 times in a row).

Run files in `.claude/overnight/<run id>/` (kept out of git through `.git/info/exclude`):
`objective.md`, `notes.md` (memory between iterations; the runner adds one line per outcome),
`log.jsonl`, `state.json`, `end-state.json`. Continue a stopped run with
`--resume .claude/overnight/<run id>` (flags given again override the saved ones).

## 5. The morning after

1. Read `end-state.json` (stop reason, commits, cost) and `notes.md`.
2. `git log --oneline <base>..<branch>`: decide which commits to keep. Drop the rest with an
   interactive rebase or cherry-pick the good ones onto a fresh branch.
3. Run `/kit:review` on the branch, then `/kit:go` to open the PR with evidence and a risk
   rating. The overnight commits are first-pass work, not reviewed work.
4. If a failure repeated in the notes, run `/kit:learn` so the next run avoids it.
