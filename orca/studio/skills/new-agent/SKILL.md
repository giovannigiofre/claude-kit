---
name: new-agent
description: Use in Studio when the owner wants a new agent or specialist (a role such as legal, marketing, data), or wants to change what an existing specialist does - define the role, research it, draft it in claude-kit, measure it with evals and a live trial, then install it after the owner's merge.
---

# Onboard a new agent

A specialist is one Claude Code agent file, `orca/agents/<name>.md` in claude-kit, with the files
it needs beside it, copied to `~/.claude/agents/` by `orca/install.sh`. The terminal kit stays engineering
only: nothing here goes under `plugins/`. Notes go in `~/Documents/studio/agents/<name>/`.

## 1. The role, in one message

Ask, each with your suggestion: what it does and what it never does; read-only or does it
change repos (then it works in a worktree and ships PRs like the engineer); which projects. Write `role.md` with the answers.

## 2. Research

`researcher`, read-only, with sources, into `research.md`:
- how a strong practitioner does this job: their method, checklists and failure modes;
- existing agents, prompts and skills for the role. Judge each the way the kit's intake does:
  licence, what it runs as the user, context cost, overlap with what the bundle has;
- the tools, MCP servers or accounts it needs. A login is the owner's to do; never ask for a
  secret in the chat.

Send the owner a five-line summary and what you would take from it.

## 3. Draft, measure, try

One `kit:implementer` thread on a claude-kit worktree, SHIP `pr`:
- the agent file, the prompt in the house shape (role, numbered method, a fixed
  verdict or report format), a README line;
- 5 eval cases (10 for a role that changes repos) from real tasks in the owner's projects,
  in `~/Documents/omnigent-research/evals/cases/<name>/<id>/` (outside the repo): `case.json`
  with `role`, `repo` or `repo_path`, `base`; `brief.md` in the lead's brief format;
  `rubric.md` with what a good outcome must contain and what makes it FAIL;
- a run of each case by hand, with the results in the PR (`omnigent/evals/run.py` drives Omnigent sessions and has no Orca runner yet).

Then a live trial: run the branch's `orca/install.sh`, dispatch one real task in a
project, and put its report and the verifier's verdict in the PR. If the PR is not merged, remove the
file from `~/.claude/agents/`.

## 4. Install

The owner merges claude-kit PRs. After the merge: `git -C ~/Documents/repositories/claude-kit pull`
and `sh ~/Documents/repositories/claude-kit/orca/install.sh`, then tell the owner. New sessions see it.
