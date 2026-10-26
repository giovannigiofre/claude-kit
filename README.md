# claude-kit

My personal Claude Code harness. You talk to **one coordinator**: it starts a background thread
for each piece of work, every thread works in its own worktree and ends with a PR you can judge
without reading the diff, and deterministic hooks keep the quality gates on. It is a git repo
installed once as a plugin marketplace, and it works in every project.

Design rule, from the research in [docs/proposta-kit-1.0.md](docs/proposta-kit-1.0.md): **few
instructions, deterministic checks, native features first.** Current models verify their own
work and follow instructions literally, so generic rules and mandated process cost tokens and can
lower quality; tests, gates and hooks don't. Every piece of the kit is an assumption about what
the model can't do alone, re-checked when a new model lands.

---

## A day with the kit

| When | Type | What happens |
|---|---|---|
| Once per project | `/kit:init` | writes `.claude/kit.json` (check, verify, formatters, protected paths), an e2e skill that says how to exercise the app, and proposes safety and permissions |
| All day | just talk | in a project with `kit.json`, loop mode is on by default: every message goes to the coordinator (`kit:lead`), which answers, starts a thread or steers one, in at most four lines |
| A messy idea | just write it | the coordinator (or `kit:shape`) asks 2-3 multiple-choice rounds and writes a brief with a checkable DONE WHEN |
| Something broke | describe it | `kit:investigate`: evidence (asks you once, with exact export steps), reproduction, hypotheses, a regression-tested fix |
| UI or LLM work | describe it | the kit asks "Use Kit UI / Kit LLM for this?" and installs that plugin for the project on yes |
| First PR in a project | answer once | "Do I merge PRs once they're green, or do you always review them first?"; the answer is saved in `kit.json` (`lead.merge`) |
| Finishing by hand | `/kit:go` | PR with intent, live evidence, what was fixed, risk; keeps CI green; merges if the project allows it |
| Evening | "tonight keep doing X until Y" | `kit:overnight`: a fresh session per small step, a commit only when the gate passes, caps or none |
| Weekly | `/kit:learn sweep` | turns repeated corrections into checks or rules, and prunes instructions that no longer help (at most 4 changes, each approved) |

Your time goes to the two ends: saying what you want, and judging the PR. The middle is the
threads' job.

**The coordinator** is Claude Projects for the terminal (Projects runs only on web, desktop and
mobile today). One conversation routes each message: a question is answered in place, new work
becomes a thread (`kit:implementer` in its own worktree, in the background), a follow-up goes to
the thread already working in that area. The board (`.claude/lead/board.md`) holds every item as
`working`, `review` (ready for you), `needs-you`, `done`; it survives compaction and restarts, and
comes back into context after a compaction. Threads run the project's gate, exercise the change,
and per the ship mode commit, open a PR, and fix CI; on their own branches they may rebase and
force-push as the work needs. Every commit and PR is yours: `kit.json` `author` sets your git
identity, and nothing credits an AI. Who merges is per project: you, or the coordinator for green,
reviewed, not-high-risk PRs. Medium- or high-risk work gets a review by
`kit:verifier` in a fresh context before it reaches you. When a thread finishes while you're away,
the coordinator sends a notification (desktop, or phone with Remote Control).

**The status line.** `kit: loop · host · $1.20 · 2 running · 1 overnight · 1 ready · 1 need you`,
read again every 15 seconds. Mode per project (`/kit-mode`): **Light** (a normal session) or
**Loop** (every typed message goes to the coordinator; the default in a project with
`kit.json`). Safety per project (`/kit-safety`): **Host** or **Sandbox**.

---

## How it works

```
 you ── message ──► COORDINATOR (kit:lead, loop mode)
                     │ answers in place, or
                     │ starts / steers a thread ──► kit:implementer (background, own worktree)
                     │                                 change → `verify` gate → exercise it →
                     │                                 commit → PR (Intent, Evidence, Fixed, Risk) → CI fixes
                     │ ◄── report ─────────────────────┘
                     │ medium/high risk ──► kit:verifier (fresh context) ──► findings back to the thread
                     ▼
                   board.md: NEEDS YOU · ready for review · working   (+ notification)

 Hooks in every project with .claude/kit.json (silent when all is well):
   PreToolUse   protect  blocks edits to protected paths
                guard    blocks irreversible or credential-leaking commands, in any permission mode
   PostToolUse  on_edit  runs the formatter/validator for the edited file, feeds errors back
   Stop         check    runs the fast `check`; on failure Claude keeps fixing (max 3 tries)
   SessionStart          lists the project's gates; after a compaction, re-injects the board;
                         says once when a newer kit is installed than the one loaded (restart)
   SubagentStart         gives each kit:implementer this repo's lesson indexes: the verifier's
                         pitfalls and your feedback memories (index lines, about 600 tokens max)
```

## What's in it

**Core plugin `kit`** (user scope, every project):

| Piece | What it does |
|---|---|
| `kit:lead` | The coordinator: board, threads, routing, short replies, standing loops, notifications |
| `kit:shape` | A brain-dump into a brief through at most 3 multiple-choice rounds |
| `kit:investigate` | Root-cause debugging for any failure; `scripts/compact_logs.py` reads big log exports and diffs a failing run against a working one |
| `kit:overnight` | Launches `scripts/overnight.py`: fresh `claude -p` per step, commit on a green gate, reset otherwise, notes as memory, optional caps, resumes early stops |
| `kit:extras` | Offers `kit-ui` or `kit-llm` when a task needs one the project lacks |
| `/kit:go` | Intent → sync → test like a user → `/code-review` → `/simplify` → risk → PR → CI green |
| `/kit:init` | Sets up a project (kit.json, e2e skill, safety, permissions) |
| `/kit:learn` | Corrections into checks, hooks, skills or CLAUDE.md lines; prunes too |
| `/kit:intake` | Evaluates an outside tool before adoption (see [CATALOG.md](CATALOG.md)) |
| `kit:implementer` | A thread: one item from brief to PR in its own worktree, effort medium |
| `kit:verifier` | A fresh-context review against the intent, with a per-project memory of pitfalls |
| Hooks + mod | `protect`, `guard`, `on_edit`, `stop_check`, `session_start`, `subagent_start`; the mod (`kit.tsx`: modes, safety, status line) |

**Domain plugins** (project scope, offered by `kit:extras` when a task needs them):

| Plugin | Skills |
|---|---|
| `kit-ui` | `kit-ui:ui` (impeccable and taste as one team, one precedence rule, one done-check), `kit-ui:brand` (three brand boards, then an applied design system) |
| `kit-llm` | `kit-llm:llm-build` (build checklist A-H for code that calls an LLM), `kit-llm:llm-evals` (error analysis, calibrated judges, then prompt optimization or model choice), and a hook that spots LLM code on edit |

**Native features the kit uses instead of its own copies:** `/code-review`, `/simplify`,
`/goal`, `/loop`, `/autofix-pr`, agent view (`claude agents`), the Workflow tool, auto-compact
with a `# Compact instructions` section in CLAUDE.md, auto mode, `/doctor prompt-audit`.

## Install

```bash
git clone git@github.com:giovannigiofre/claude-kit.git ~/Documents/repositories/claude-kit
~/Documents/repositories/claude-kit/install.sh            # or: install.sh --github
```

That registers the marketplace and installs `kit` at user scope. `kit-ui` and `kit-llm` are
installed per project when the kit offers them, or by hand:
`claude plugin install kit-llm@claude-kit --scope project`.

**On every machine, the kit sets itself up.** At the first session (or in `install.sh`), Claude
explains and asks once to add two things to `~/.claude/settings.json`, which no plugin or project
file can set: `"attribution": {"commit": "", "pr": "", "sessionUrl": false}` (no Claude trailer,
footer or session link: you are the only author) and an `autoMode.allow` rule that lets agents
rewrite and force-push, with lease, the branches they created. On yes it merges them in (with a
backup, other keys kept); on no it never asks again on that machine
(`hooks/scripts/machine_setup.py --apply | --decline | --check`).
Each repo's own auto mode environment (org, cloud, secrets, protected branches) is approved once
in `/kit:init`, kept in your Claude config, and added to that list scoped to the repo; nothing in
a repo can add to it ([reference](docs/reference.md#auto-mode-environment-per-repo)).

Also worth having in `~/.claude/settings.json` (auto mode is already the default on Pro and Max):
system notifications on; `"env": {"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "4"}` if you want a
hard cap on parallel threads. To change the mode default everywhere, put `{"mode": "light"}`
(or `"loop"`) in `~/.claude/kit.json`; `/kit-mode` sets it per project.

Two lines worth having in your personal `~/.claude/CLAUDE.md`, because models trained on human
estimates otherwise pick the cheap, brittle option and test only in units:

```markdown
- When making technical decisions, don't give weight to development cost: weigh correctness,
  maintainability, scalability and running cost. Never estimate in days or weeks.
- For a bug fix, first reproduce the bug end to end, as the user meets it, not only in a unit test.
```

**Every new project:** `cd project && claude`, then `/kit:init`. Read `.claude/kit.json`, adjust
it, commit it. The hooks do nothing in a project without it, so a user-scope install never
changes a project you haven't opted in. Details of every key: [docs/reference.md](docs/reference.md).

**Update:** `git pull` in the clone (or `claude plugin marketplace update claude-kit`), then
`/reload-plugins`. Bump `version` in the plugin's `plugin.json` when behaviour changes.

**Pause:** `claude plugin disable kit@claude-kit` everywhere, or delete `.claude/kit.json` in one
project.

## Safety

- **Host** (your own machine): no OS sandbox. The guard still blocks recursive deletes outside
  the repo, pushes or force pushes to main, `git reset --hard` or `clean` over uncommitted work,
  `sudo`, `curl … | sh`, and reading `~/.ssh`, `~/.aws`, gh, docker or kube config and the
  keychain. It also keeps you the only author: it blocks a commit, PR, issue or comment that
  credits an AI (`Co-Authored-By: Claude`, "Generated with Claude Code", a session link), through
  git, `gh` or the GitHub MCP tools, and a commit made under an AI git identity. It reads shell
  text, so it is best effort.
- **Sandbox** (overnight runs, unfamiliar repos): the same guard plus Claude Code's Bash sandbox
  in `.claude/settings.local.json` (writes in the project and temp, network to GitHub, package
  registries and the Anthropic API, credential folders unreadable). `kit:overnight` passes it to
  every iteration.
- **Full isolation** for `--dangerously-skip-permissions` only: a microVM or a devcontainer.

## Changing the kit

- Keep it generic; anything project-specific goes in that project's `kit.json` or skills. Domain
  knowledge goes in a domain plugin that `kit:extras` offers.
- `python3 tests/test_budget.py` must pass: always-on description budgets per plugin, short
  SKILL.md files, no shouted rules, no per-prompt or every-tool hooks in core, and every
  `kit:` reference resolving. Raise a budget only with a reason.
- Prefer a check a machine runs (a hook, a script, a test) over a sentence. Explain the why
  instead of commanding; don't tell the model to verify or plan, give it something to run.
- Hooks and scripts use the Python 3.9+ standard library only.
- **When a new model lands:** run `/doctor prompt-audit` on the plugins, re-run the kit's evals
  with and without the kit, and delete what no longer changes the result.

Tests and evals: [docs/reference.md#develop](docs/reference.md#develop).

## Sources

- Research behind this version (Anthropic's guides for Opus 5 and 5.5, the Claude Code team,
  measured studies of context files and instruction following, practitioners' loops):
  [docs/proposta-kit-1.0.md](docs/proposta-kit-1.0.md).
- Boris Cherny: verification as the main lever, `/go`, loops that do the prompting:
  https://x.com/bcherny/status/2044847858634064115, https://x.com/bcherny/status/2038454341884154269
- Claude Code docs, Projects (the model for `kit:lead`): https://code.claude.com/docs/en/claude-projects
- Kun Chen (MIT, methods adapted, nothing copied): no-mistakes for `/kit:go`, gnhf for
  `kit:overnight`, firstmate for the coordinator, "Your AGENTS.md is a Neural Net" for
  `/kit:learn`: https://github.com/kunchenguid
- Third-party tools considered, with decisions: [CATALOG.md](CATALOG.md).
