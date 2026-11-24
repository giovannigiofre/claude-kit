---
name: new-agent
description: Use in Studio when the owner wants a new agent or specialist (a role such as legal, marketing, data), or wants to change what an existing specialist does - define the role, research it, draft it in claude-kit, measure it with evals and a live trial, then install it after the owner's merge.
---

# Onboard a new agent

The bundle lives in claude-kit (`~/Documents/repositories/claude-kit/omnigent/`). A specialist
is `omnigent/agents/<name>/config.yaml` plus its skills, listed in the root `config.yaml`
under `tools.agents` and in the lead's Specialists list. The terminal kit stays engineering
only: nothing here goes under `plugins/`. Notes go in `~/Documents/studio/agents/<name>/`.

## 1. The role, in one message

Ask, each with your suggestion: what it does and what it never does; read-only or does it
change repos (then it works in a worktree and ships PRs like the engineer); which projects;
a specialist under the lead (the default) or an agent of its own (its own bundle under
`omnigent/standalone/<name>/`, installed on its own). Write `role.md` with the answers.

## 2. Research

`researcher`, read-only, with sources, into `research.md`:
- how a strong practitioner does this job: their method, checklists and failure modes;
- existing agents, prompts and skills for the role. Judge each the way the kit's intake does:
  licence, what it runs as the user, context cost, overlap with what the bundle has;
- the tools, MCP servers or accounts it needs. A login is the owner's to do; never ask for a
  secret in the chat.

Send the owner a five-line summary and what you would take from it.

## 3. Draft, measure, try

One `engineer` dispatch on a claude-kit worktree, SHIP `pr`:
- the config and skills, the prompt in the house shape (role, numbered method, a fixed
  verdict or report format), the lists in the root config, a README line;
- 5 eval cases (10 for a role that changes repos) from real tasks in the owner's projects,
  in `~/Documents/omnigent-research/evals/cases/<name>/<id>/` (outside the repo): `case.json`
  with `role`, `repo` or `repo_path`, `base`; `brief.md` in the lead's brief format;
  `rubric.md` with what a good outcome must contain and what makes it FAIL;
- a run: `python3 omnigent/evals/run.py run <name> -k 3`, with the table in the PR.

Then a live trial: install the branch's bundle (`omnigent agent add <worktree>/omnigent`),
dispatch one real task in a project, and put its report and the reviewer's verdict in the PR.
Reinstall from main afterwards if the PR is not merged.

## 4. Install

The owner merges claude-kit PRs. After the merge: `git -C ~/Documents/repositories/claude-kit
pull` and `omnigent agent add ~/Documents/repositories/claude-kit/omnigent`, then tell the
owner which projects can use it.
