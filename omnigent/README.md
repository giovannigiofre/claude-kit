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
  agents/designer/       UI work with Open Design's craft rules, screenshots, a live preview
    skills/              design-brief, design-system, design-craft, design-review
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
- Every repo change goes to a specialist with a brief: GOAL, SCOPE, DONE WHEN, WORKTREE, SHIP,
  OUTPUT. Parallel only for independent pieces that touch different files.
- Worktrees live in `~/.omnigent/worktrees/<repo>/<slug>`, never the main checkout.
- `reviewer` checks every non-trivial PR before you hear it is ready, with a fixed PASS/FAIL
  rule; you merge.
- Memory outside the repo: `~/.omnigent/boards/<repo>.md` (tasks) and
  `~/.omnigent/lessons/<repo>.md` (facts and corrections you confirmed).
- What needs you while you are away goes to the Omnigent inbox (`sys_user_inbox_post`).

## Evals

`evals/` measures `engineer` and `reviewer` on real tasks from the owner's projects. Each task is
graded on its outcome: for the engineer, the reference PR's hidden tests plus a rubric; for the
reviewer, seeded and real defects it must catch and clean PRs it must pass. Each task runs 3 times
and reports pass@1 and pass^3. The cases come from private repos, so they live outside this public
repo (`~/Documents/omnigent-research/evals/`). A prompt change is kept only if it wins an A/B run
on the suite and the owner approves it. See [evals/README.md](evals/README.md).

## Routines

A weekday 08:00 (Europe/Rome) schedule per project sends `lead` a `ROUTINE:` message: read the
board, open PRs, checks and CI, update the board, post to the inbox only what needs you, start
no work. `session_mode: continue`, no cost cap (a cap on a continued session also stops work you start in it). Schedules live on the server; list
them with `curl -s http://127.0.0.1:6767/v1/scheduled-tasks`, or ask `lead` to add, change or
stop one. They run only while the host is online (`omnigent host enable` installs it as a
login service).

## The designer and Open Design

The designer does not run Open Design. It carries what makes Open Design's output good, as four
skills: ask only what changes the result and lock one direction before code (`design-brief`),
bind the project's tokens (`design-system`), numeric craft rules and a banned-patterns list
applied while writing (`design-craft`), and a checklist, a lint (`scripts/slop_lint.py`), a
scored pass, real screenshots at 390/768/1440px and a live preview on the tailnet
(`tailscale serve --set-path /preview/<slug>`) before handoff (`design-review`). The files
copied from Open Design, their tag and the update rule are in
`agents/designer/skills/design-craft/references/open-design/UPSTREAM.md`.

## Cloudflare without signing in

Agents use one scoped Cloudflare API token kept in the login Keychain; no OAuth that expires,
nothing in a repo or config file.

1. In the Cloudflare dashboard, My Profile, API Tokens, Create Token, template "Edit Cloudflare
   Workers", then add D1 Edit, Zone Read, DNS Edit and Account Analytics Read. Account
   Resources: only the accounts the projects deploy to; Zone Resources: only their zones.
2. Store it (the prompt keeps it out of the shell history):
   `security add-generic-password -a "$USER" -s cloudflare-api-token -w`
3. wrangler reads `CLOUDFLARE_API_TOKEN`: export it from the Keychain in `~/.zshenv`
   (`security find-generic-password -s cloudflare-api-token -w`).
4. The Cloudflare MCP server, user scope, with a `headersHelper` that prints
   `{"Authorization":"Bearer <token>"}` from the Keychain, so the token is read per request.
5. Check from a headless worker: `wrangler whoami`, then a preview deploy.
