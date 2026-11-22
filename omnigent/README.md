# The kit on Omnigent

An [Omnigent](https://omnigent.ai) agent bundle: the kit's way of working (one coordinator,
specialists that report back, a PR you judge from evidence) as an Omnigent orchestrator, so it
runs from the Omnigent iOS app and, later, on an always-on host.

```
omnigent/
  config.yaml            lead: the orchestrator (claude-sdk brain, writes no code)
  agents/engineer/       implements in its own worktree, gate, evidence, PR
  agents/reviewer/       fresh-context review against the brief, never edits
  agents/researcher/     read-only answers from the repo and the web, with sources
  agents/designer/       UI work, screenshots of the real page (phone first)
  agents/seo/            search and content: audit, or a PR
```

Every specialist is a `claude-native` session: the real Claude Code CLI, with your plugins,
CLAUDE.md and this kit's hooks (gate, protected paths, guard). The kit notices it runs under
Omnigent (`OMNIGENT_RUNNER_ID`) and leaves coordinating to `lead`; from the terminal the kit
works as before.

## Install or update

```sh
omnigent agent add ~/Documents/repositories/claude-kit/omnigent
```

Re-running it replaces the installed copy. The agent is stored on the server, so it shows in the
new-session picker on the Mac and on the phone.

## Projects

A project in Omnigent is a folder with `lead` as its default agent. Create one in the app
(New project, Folder) or with the API:

```sh
curl -s -X POST http://127.0.0.1:6767/v1/projects -H 'Content-Type: application/json' \
  -H 'Origin: omnigent://internal' \
  -d '{"name":"<name>","config":{"agent_id":"<lead id from omnigent agent list>","workspace":"<abs path>"}}'
```

## How lead works

- Questions get an answer in place; anything deeper goes to `researcher`.
- Every repo change goes to a specialist with a brief: GOAL, SCOPE, DONE WHEN, WORKTREE, SHIP.
- Worktrees live in `~/.omnigent/worktrees/<repo>/<slug>`, never the main checkout.
- `reviewer` checks every non-trivial PR before you hear it is ready; you merge.
- A short board per repo at `~/.omnigent/boards/<repo>.md` carries state between conversations.

## Evals

`evals/` measures `engineer` and `reviewer` on real tasks from the owner's projects. Each task is
graded on its outcome: for the engineer, the reference PR's hidden tests plus a rubric; for the
reviewer, seeded and real defects it must catch and clean PRs it must pass. Each task runs 3 times
and reports pass@1 and pass^3. The cases come from private repos, so they live outside this public
repo (`~/Documents/omnigent-research/evals/`). A prompt change is kept only if it wins an A/B run
on the suite and the owner approves it. See [evals/README.md](evals/README.md).
