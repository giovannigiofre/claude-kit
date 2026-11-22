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
  agents/seo-growth/     the scheduled growth loop: data, one PR or nothing, a ledger of verdicts
  scripts/               clean_evidence.py: daily cleanup of old screenshots
  skills/                lead's: new-project, onboard-repo (with omni_project.py), new-agent
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

## Projects and Studio

A project in Omnigent is a folder with `lead` as its default agent. **Studio**
(`~/Documents/studio`, local git only) is the project for everything that is not one project's
work yet: ideas (`ideas/<slug>/`), agents being onboarded (`agents/<name>/`), repos to start on.
From Studio, `lead` follows its skills:

- `new-project`: questions, research by `researcher` and `seo` into the idea folder, a brief, then
  one approval message with the name, where the repo goes (your account or an org: always asked)
  and its visibility (always asked). It creates the repo with only a README and hands off.
- `onboard-repo`: an existing repo, or the one `new-project` just made. It writes a handoff to
  `~/Documents/studio/handoffs/<repo>.md` and runs
  `skills/onboard-repo/scripts/omni_project.py register <name> <path> --handoff <file>`, which
  registers the project and opens its first conversation on this Mac with the handoff as its
  first message. That conversation sets up the kit (and the scaffold, for a new repo) in one PR,
  brings the Studio notes into `docs/`, writes the project card, board and lessons, and adds the
  morning check if you asked for it.
- `new-agent`: role, research, a draft in this repo with eval cases, a live trial, a PR.

Who merges is per project, in `.claude/kit.json` (`lead.merge`: `user` or `agent`); `lead`
reads it, and a missing setting means `user`. Registering by hand:
`python3 omnigent/skills/onboard-repo/scripts/omni_project.py register <name> <abs path>`.

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

## seo-growth: the scheduled growth loop

`seo` works on demand; `seo-growth` runs on a schedule, once per site every 2 days (fiscometro and
nettoswiss, an hour apart). Each run reads the site's admin API, official news, Google's update
history and a fixed AI-citation panel, and opens at most **one** PR, or nothing (the usual outcome
while traffic is small). The owner merges every PR it opens, whatever `lead.merge` says: the sites
carry tax figures. It never merges, pushes to main or deploys.

```
agents/seo-growth/
  config.yaml            the prompt: pull, score, panel, verdicts, decide, ship, report
  data/                  owner-edited, never by the agent
    sites.json           per site: origin, repo, gate, rules, allowed action types, pre-launch date, feeds
    thresholds.json      floors and caps (20 extra clicks / 28 days, 2 open PRs, 28-day cool-down, ...)
    calendar.json        IT/CH demand peaks with official sources (one-time owner read, see below)
    panel.json           the fixed AI-citation prompts per site
  scripts/
    pull.sh              admin API (summary, pages, queries) + feeds + Google status + top pages' HTML
    score.py             the pull -> ranked candidates.json, with every guardrail applied
    ledger.py            per-page experiment ledger (~/.omnigent/seo-growth/<site>/ledger.jsonl)
    sources.py           RSS/Atom -> news.json, Google status -> rollouts.json, watched pages -> watch.json
    schema_lint.py       JSON-LD consistency (dateModified = visible date, complete WebApplication)
    report.sh            POST /admin/api/agent-report
  tests/                 the deterministic scenarios on a fixture pull (run by tests/run_all.py)
```

What `score.py` enforces before Claude sees a candidate:

- **Stops:** autopilot paused in the admin; no data (NettoSwiss is pre-launch until 15 Dec 2026,
  so its runs end with one line); 2 open `seo-growth` PRs.
- **Floors:** a candidate needs about 20 extra clicks over 28 days, estimated against the site's own
  CTR curve (low CTR for the position, striking distance in positions 5-20, internal links from GSC
  co-occurrence at most 3 per PR, decay, schema errors, official news on a cluster with impressions,
  calendar peaks 4-8 weeks ahead, AI-panel gaps).
- **Ledger rules:** no change on a page in its 28-day cool-down or with an open PR; nothing the owner
  closed in the last 90 days; never repeat a change that regressed; leave a page alone when it is
  above the curve or its last title change was kept.
- **Freeze:** a verdict whose windows overlap a Google core or spam rollout (or the 28 days after
  it) is `confounded` and waits; decay is not acted on while a rollout runs. An unreadable status
  page counts as a rollout (fail closed).
- **AI panel:** Claude runs the fixed prompts with its own web search and logs who is cited. It is
  a proxy, not Google AI Overviews; a candidate needs 3 runs in a row that agree. Cloudflare
  `aiReferrals` and `aiCrawls` from the admin are the ground truth beside it.

**Owner steps, once.**

1. The analyst token, shared by both sites, lives in one Keychain item. In the fiscometro checkout:
   `pnpm admin:token --analyst` (prints the token and its SHA-256). fiscometro: the digest goes in
   `.admin-secrets.env` as `ANALYST_TOKEN_SHA256`, then `pnpm admin:secrets`. nettoswiss: the same
   digest as the GitHub secret `ANALYST_TOKEN_SHA256` (live at the next deploy). Then
   `security add-generic-password -U -s seo-growth-analyst -a "$USER" -w` and paste the token at the
   prompt. Check: `bash omnigent/agents/seo-growth/scripts/pull.sh fiscometro --check` prints
   `ok ok autopilot=true site=https://fiscometro.it`. Only `pull.sh` and `report.sh` read the item; the kit's guard blocks
   `security find-generic-password` in Claude's own shell.
2. Read `data/calendar.json` once: check each date against its source, then set
   `owner_reviewed_on`. Until then no seasonal candidate is made, and an entry counts only when its
   `status` is `checked` for the year of the coming peak.
3. After this bundle is installed, ask `lead` for the two routines (every 2 days, e.g.
   `17 6 */2 * *` and `17 7 */2 * *` Europe/Rome).

Not part of this agent: wiring IndexNow into fiscometro's deploys (nettoswiss already does it) is a
separate one-off PR in fiscometro.

Tests: `python3 omnigent/agents/seo-growth/tests/test_seo_growth.py` (the deterministic half). The
model-judged cases (picking, refusing an injected instruction, unsourced numbers) live with the other
eval cases outside this repo, in `cases/seo-growth/`.

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

## Cloudflare with one sign-in

Two pieces, each signed in once, both refreshing on their own:

- **The Cloudflare MCP tools** come from claude.ai connectors, so they reach every Claude Code
  session on the account: the terminal, `lead` and every specialist. "Cloudflare Developer
  Platform" (Workers, KV, R2, D1) is already on the account and only needs Connect in claude.ai,
  Settings, Connectors. For DNS, zones and the rest of the API, add the custom connector
  `https://mcp.cloudflare.com/mcp` there. claude.ai holds and refreshes the tokens; nothing is on
  this Mac or in a repo.
- **wrangler** (deploys) is signed in with OAuth on this Mac (`wrangler login`, with
  `offline_access`, so it refreshes itself); `npx wrangler whoami` shows the account and scopes.
  Another Cloudflare account needs its own `wrangler login`.

Omnigent also has a server-side MCP registry (`OMNIGENT_MCP_REGISTRY`), but it needs an
encrypted credential store and an OAuth client of our own: worth it on a shared server, not
here.

## Background tasks are off for Omnigent sessions

Omnigent wakes `lead` only for a specialist turn that `lead` started. When a specialist runs a
sub-agent in the background and ends its turn, the turn Claude Code starts later to collect the
result reaches nobody. Prompts alone did not stop it, so the host's LaunchAgent
(`~/Library/LaunchAgents/ai.omnigent.host.plist`) sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` in
`EnvironmentVariables`: every Claude Code that Omnigent launches runs sub-agents in the foreground
and gets no `run_in_background`. The terminal is unaffected. `omnigent host enable` rewrites the
plist, so add the variable again after it.

## Old screenshots

Screenshots in the chat are files in `.kit/evidence/` of each Omnigent project, Studio and the
specialists' worktrees. `scripts/clean_evidence.py` deletes the images and videos there older than
3 days (notes and logs stay; an old chat then shows "Image not available"). It reads the project
list from the server, so new projects are covered. Terminal-only repos are not touched. Install:

```sh
mkdir -p ~/.omnigent/bin && cp omnigent/scripts/clean_evidence.py ~/.omnigent/bin/
```

and a LaunchAgent `ai.omnigent.evidence-cleanup` at 04:00 that runs it with Omnigent's own Python
(`~/.local/share/uv/tools/omnigent/bin/python`): that binary already has access to `~/Documents`,
while `/usr/bin/python3` under launchd does not and finds nothing. The log is
`~/.omnigent/logs/evidence-cleanup.log`; `--dry-run` shows what would go.
