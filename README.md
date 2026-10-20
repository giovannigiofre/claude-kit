# claude-kit

My personal Claude Code harness. It gives you **one lead agent to talk to**. The lead plans the
work, hands it to worker agents, has every result checked by a separate verifier, and loops until
the work passes. Quality gates run on their own through hooks. The whole thing is a git repo
installed once as a plugin, and it works in every project.

Nothing in here is new. It packages what the Claude Code team describes publicly:

- Several Claudes running in parallel, each in its own worktree.
- A checked-in CLAUDE.md that grows every time Claude gets something wrong ("compounding
  engineering").
- Specialist subagents (`verify-app`, `code-simplifier`).
- A PostToolUse formatter hook, and a Stop hook that keeps Claude working.
- `/go` (verify → simplify → PR).
- `/loop` for recurring work.
- Dynamic workflows for large fan-outs.
- Above all, **verification**. Boris Cherny calls it "probably the most important thing", and
  says it can "2-3x the quality".

Sources are at the end.

---

## 1. How it works

```
                 you  (any prompt, even a brain-dump of ideas)
                  │
                  ▼
      SHAPE (automatic on brain-dumps: hook → kit:shape)
        splits the ideas, looks facts up, asks ≤3 rounds of
        multiple-choice questions → BRIEF (goal, DONE WHEN, scope,
        skills, mechanism) → "Start now?" ─────────────┐
                                                        │  (or type "/kit:lead <goal>" directly,
                  ┌─────────────────────────────────────┘   or /loop 30m /kit:lead next)
                  ▼
      ┌──────── LEAD (your main session) ─────────┐
      │ reads CLAUDE.md + .claude/kit.json         │
      │ defines a checkable "done"                 │
      │ splits into tasks, picks the mechanism     │
      └──┬──────────────┬──────────────┬───────────┘
         │              │              │
   kit:implementer  kit:implementer  workflow /kit:ship  (many tasks, parallel worktrees)
   (worktree A)     (worktree B)     workflow /kit:review (lenses + adversarial verify)
         │              │
         ▼              ▼
     kit:verifier   kit:verifier     ← independent; PASS / FAIL / CANNOT_VERIFY
         │ FAIL → back to implementer (max 3 rounds) → escalate to you
         ▼
      LEAD merges, runs `verify`, reports → /kit:go (simplify, commit, PR) → /kit:learn

  Hooks, in every session of a project that has .claude/kit.json:
    UserPromptSubmit → spots brain-dump prompts and routes them to kit:shape (mode: ask/auto/off;
                       also active without kit.json if ~/.claude/kit.json sets "shape")
    SessionStart → tells Claude the project's gates; after a compaction re-injects the handoff note
    PreToolUse   → blocks edits to protected paths (e.g. raw data that must never be overwritten)
    PostToolUse  → runs the formatter/validator for the edited file, feeds errors back;
                   once per session, if the edited file is LLM code, points Claude to kit:llm-build
    UserPromptSubmit + PostToolUse → context guard: at 70 % / 85 % of the auto-compact window,
                       asks Claude to update the handoff note before compaction
    Stop         → runs the fast `check`; if it fails, Claude must keep fixing (max 3 tries)
```

### What's in the plugin (`plugins/kit/`)

| Piece | Name in Claude Code | What it does |
|---|---|---|
| Skill | `/kit:shape [idea]` | Turns a brain-dump into a precise brief with multiple-choice questions, then launches it. Starts on its own via the prompt hook |
| Skill | `/kit:lead <goal>` | Makes the session the lead: plan, delegate, verify, loop, report |
| Skill | `/kit:go` | Finishes the work: verify → simplify → verify → commit on a branch → PR |
| Skill | `/kit:learn` | Writes a correction into CLAUDE.md, a skill or kit.json so it sticks |
| Skill | `/kit:techdebt` | End-of-session sweep for duplication, dead code and stale docs |
| Skill | `/kit:init` | Sets up the harness in a project by writing `.claude/kit.json` |
| Skill | `/kit:brand [app]` | New brand or rebrand: brief, three brand-board options on a Design canvas (via impeccable), then applies the chosen one, sweeps old-brand leftovers and runs two UI reviews |
| Skill | `/kit:ui [task]` | Any UI or design task: routes between impeccable (product UI, critique, audit) and taste (art direction of marketing pages, real-browser inspector) with one precedence rule and one done-check |
| Skill | `/kit:intake <tool>` | Evaluates an outside skill or plugin before adoption (§4); any skill the kit writes or rewrites goes through Anthropic's `skill-creator` loop |
| Skill | `kit:llm-build` | Design, build and review of any LLM code (SDK or raw HTTP calls, prompts, tools, model config): workflow vs agent, tools, context, structured output and grounding, injection defences (lethal trifecta), budgets, operations; checklist A-H in `checklist.md` and a "Done when" the verifier enforces (replaces `kit:llm-design`, 0.7.0) |
| Skill | `kit:llm-evals` | Error analysis → failure taxonomy → code checks + calibrated binary judges → CI gate. Extends the project's existing harness |
| Skill | `kit:prompt-optimize` | Eval-driven prompt loop: baseline, diagnose, minimal edit, keep/revert on a held-out split, fixed budget, run log |
| Skill | `kit:model-select` | Same suite across candidate models per role; pick from the quality/cost/latency frontier |
| Skill | `kit:systematic-debugging`, `kit:verification-before-completion` | Vendored from obra/superpowers (MIT, licence inside) |
| Agent | `kit:implementer` | Does one scoped task and returns a structured report |
| Agent | `kit:verifier` | Checks the work independently; assumes it's broken until proven otherwise. Keeps a per-project memory of recurring pitfalls |
| Agent | `kit:code-simplifier` | Simplifies the diff without changing behaviour |
| Agent | `kit:plan-reviewer` | Reviews a plan as a "staff engineer" before any code is written |
| Workflow | `/kit:ship` | Runs N tasks in parallel worktrees: implement → verify → fix loop |
| Workflow | `/kit:review` | Reviews the branch through 6 lenses (the `llm` lens only reports when the diff touches LLM code); 2 skeptics try to refute each finding |
| Hooks | (automatic) | `shape_detect`, `session_start`, `context_guard`, `protect`, `on_edit`, `llm_detect`, `stop_check` |

### Two layers: generic and project-specific

- **This repo is the generic layer.** It's the same in every project, and you install it once
  per machine.
- **Each project adds a thin layer of its own**, committed in that project:
  - `CLAUDE.md` / `AGENTS.md`: the project's rules. These always win over the kit.
  - `.claude/kit.json`: the project's commands for `check`, `verify`, `onEdit`, `protect` and
    `lead`.
  - `.claude/skills/*`: domain skills that workers load. For example, myinsurance has
    `collect-insurer-documents` and `run-group`.

**The hooks do nothing until a project has `.claude/kit.json`.** So installing the kit at user
scope never changes a project you haven't opted in.

### `.claude/kit.json` reference

```json
{
  "check": "fast gate (< ~30 s): lint + format check (+ types). Runs before every stop if files changed",
  "verify": "full gate: tests, evals, build. Used by kit:verifier and /kit:go",
  "checkTimeout": 540,
  "maxStopRetries": 3,
  "onEdit": [
    {"glob": "**/*.py", "run": "uv run ruff format -q \"$FILE\"", "timeout": 120}
  ],
  "protect": [
    {"glob": "data/raw/**", "mode": "no-overwrite", "reason": "raw files are immutable"},
    {"glob": "vendor/**", "mode": "read-only", "reason": "vendored code"}
  ],
  "shape": "ask",
  "llm": "on",
  "context": {"window": 300000, "warnAt": 0.7, "handoff": ".claude/handoff.md"},
  "lead": {
    "read": ["docs/backlog.md"],
    "backlog": "where the next work item comes from",
    "notes": "one line of project-specific orchestration advice"
  }
}
```

- `onEdit` commands run from the repo root. `$FILE` is the absolute path of the edited file and
  `$REL` is the path relative to the repo. `**` matches across directories; `*` stays within
  one directory.
- `shape` controls what happens on a brain-dump prompt:
  - `ask`: Claude first asks "Shape this into a brief first?";
  - `auto`: it shapes straight away;
  - `off`: nothing happens.

  Your personal default for every project, including ones without a `kit.json`, lives in
  `~/.claude/kit.json`: `{"shape": "ask"}`.
- `llm` (default `on` when the project has a `kit.json`): after an Edit/Write of a code file (or
  anything under a `prompts/` directory) whose content imports an LLM SDK (anthropic, openai,
  google-genai, mistral, cohere, ollama, litellm, langchain, llama_index, dspy, Vercel `ai`),
  calls a provider endpoint (`api.anthropic.com`, `api.openai.com`, `openrouter.ai/api`,
  `/chat/completions`, `/v1/messages` next to an Anthropic name, AWS Bedrock runtime calls, ...) or defines a system prompt or tool schema, the
  `llm_detect` hook tells Claude once per session (and once per subagent) to load
  `kit:llm-build`. Regex only, no model call. `"llm": "off"` silences it; without a project
  `kit.json` it follows `~/.claude/kit.json` (`"llm": "on"`), else stays off.
- `context` keeps long sessions lean (see "Context and compaction" below). `window` should match
  your `autoCompactWindow`; `$CLAUDE_CODE_AUTO_COMPACT_WINDOW`, if set, wins
  over it (as in Claude Code); default 300000. Put
  `{"context": {}}` in `~/.claude/kit.json` to have it in every project whose `kit.json` (if any)
  has no `context` key. Without either, the guard and the re-injection stay off.
- `protect` modes:
  - `read-only` blocks every edit.
  - `no-overwrite` lets Claude create new files but blocks edits to existing ones.
- The Stop hook runs only when the working tree changed since the last passing check, so
  question-and-answer turns cost nothing. After `maxStopRetries` failures in a row it lets
  Claude stop, and Claude must then report the failure.

---

## 2. Install

### Once per machine

Quickest route, which registers the marketplace and installs the kit:

```bash
git clone git@github.com:giovannigiofre/claude-kit.git ~/Documents/repositories/claude-kit
~/Documents/repositories/claude-kit/install.sh            # or: install.sh --github
```

By hand:

```bash
# from GitHub (after you push this repo):
claude plugin marketplace add giovannigiofre/claude-kit
# or from the local clone (edits take effect after /reload-plugins, no version bump needed):
claude plugin marketplace add ~/Documents/repositories/claude-kit

claude plugin install kit@claude-kit          # user scope = every project on this machine
claude plugin list                            # kit@claude-kit  ✔ enabled
```

Recommended user settings, which Boris also uses (`~/.claude/settings.json`, or through `/config`):

- `"permissions": {"defaultMode": "auto"}`: auto mode, so long runs don't stop for permission
  prompts.
- Turn on system notifications, so you know when a session needs you.
- `"autoCompactWindow": 300000`: compact at ~300k tokens instead of near the 1M limit.

### Context and compaction

Answer quality drops long before a 1M window is full, and every turn re-sends the whole
context. So the kit compacts early and makes compaction lossless:

1. **Compact earlier.** `autoCompactWindow` (100000 to 1000000, user or project
   `settings.json`) sets the size at which Claude Code compacts on its own. The kit recommends
   300000 for the main session; `/kit:init` writes it to the project's `.claude/settings.json`.
   The kit's agents set `autoCompactWindow: 200000` in their frontmatter (Claude Code 2.1.296+):
   workers need the brief, not a long history. `CLAUDE_CODE_AUTO_COMPACT_WINDOW` overrides both.
2. **Handoff before it happens.** No hook can start a compaction, so the context guard reads the
   current context size from the transcript and, at `warnAt` (70 %) and again at 85 % of the
   window, tells Claude to update `.claude/handoff.md`: goal, decisions, in-flight agents and
   branches, next steps, session rules. Subagents are skipped.
3. **Re-inject after.** On `SessionStart` with source `compact`, the kit prints the handoff note
   back into context, and CLAUDE.md is reloaded from disk anyway.
4. **Tell the summarizer what matters.** A `# Compact instructions` section in CLAUDE.md is read
   by the compaction summarizer; `/kit:init` adds one.

`.claude/handoff.md` is per checkout and should be gitignored. In a live session you can still run
`/compact <focus>` yourself at a natural boundary; the guard suggests it.

### Every new project (about 2 minutes)

```bash
cd my-new-project
claude
```

```
/kit:init
```

`/kit:init` reads the repo: its CI, `package.json`, `pyproject.toml`, Makefile and CLAUDE.md. It
times the candidate commands and writes `.claude/kit.json`, then proposes permission allow rules.
Read the file, adjust it, and commit it with the repo. That's all; the hooks are active from the
next edit.

Optional, per project:

- Run `/init` (built in) if the repo has no CLAUDE.md yet.
- Add domain skills under `.claude/skills/` for recurring tasks specific to that project.
- To have collaborators prompted to install the kit, commit this in the project's
  `.claude/settings.json`:

  ```json
  {
    "extraKnownMarketplaces": {
      "claude-kit": { "source": { "source": "github", "repo": "giovannigiofre/claude-kit" } }
    },
    "enabledPlugins": { "kit@claude-kit": true }
  }
  ```

### Update

```bash
cd ~/Documents/repositories/claude-kit && git pull     # or edit locally
claude plugin marketplace update claude-kit             # GitHub-installed copies
```

In a running session, run `/reload-plugins`. When you change behaviour, bump `version` in
`plugins/kit/.claude-plugin/plugin.json`.

### Uninstall or pause

- `claude plugin disable kit@claude-kit` turns it off everywhere.
- Delete `.claude/kit.json` to turn the hooks off in one project only.

---

## 3. Use it

### Daily loop

0. Just write what you have in mind, even several ideas at once. If it reads like a brain-dump,
   the prompt hook routes it to `kit:shape`. That skill splits the ideas, looks up whatever it
   can find itself, asks you a few multiple-choice rounds (recommended option first), and writes
   a brief with a checkable "done". It then offers to start the lead with the right skills
   attached. To skip it, start the prompt with `/`, or write `!go` or "just do it".
1. Start `claude` in the project and describe the goal through the lead:
   `/kit:lead add rate limiting to the /api/chat endpoint, tests included`
2. The lead:
   - writes a checkable "done";
   - for a risky plan, asks `kit:plan-reviewer`;
   - launches implementers (in parallel worktrees when tasks are independent);
   - sends each result to `kit:verifier`;
   - loops on failures and merges the branches.
3. When it reports everything verified, type `/kit:go`.
4. If you corrected it along the way, type `/kit:learn`.
5. At the end of the day, run `/kit:techdebt`.

You can also skip the lead for small things. Write the request and add `/kit:go` at the end
("fix the typo in the footer /kit:go"), the way Boris writes "Claude do blah blah /go".

### Examples

**A brain-dump: shaping starts on its own**
```
I'd like a premium history page, maybe a chart too, and then a weekly e-mail,
another idea is comparing cantons with deductibles, not sure if now or after launch?
```
In `ask` mode Claude first asks "Shape this into a brief first?". Round 1 is a multi-select of
the four ideas (now or park). Rounds 2–3 cover scope, the done-criterion and constraints, using
facts it looked up itself, like existing pages and the backlog. Then comes a BRIEF, and
"Start now" launches `kit:lead` with it. To skip shaping, start the prompt with "!go".

**A feature split across workers**
```
/kit:lead Add CSV export to the admin stats page: backend endpoint, frontend button,
tests. Done = pytest green and the button downloads a valid CSV in the browser.
```

**Many similar tasks in parallel: the ship workflow**
```
Run /kit:ship with tasks:
 - {id: "es-dict", goal: "add Spanish dictionary", scope: "web/src/dictionaries", done: "npm test passes"}
 - {id: "es-routes", goal: "add /es routes", scope: "web/src/app", done: "build passes, /es renders"}
```
Each task runs in its own worktree, is verified independently, and is fixed up to 3 times. The
result is a table of PASS/FAIL per task, with branches ready to merge.

**Review before merging**
```
/kit:review
```
Six lenses look for problems: correctness, project rules, tests, security/data, simplicity and,
when the diff touches LLM code, `llm` (the `kit:llm-build` checklist).
Each finding is then attacked by 2 skeptics, and only findings both skeptics fail to refute are
reported as confirmed.

**Keep working until a condition holds**
```
/goal every test in tests/api passes and ruff is clean
```
`/goal` uses a fast model to judge from the conversation, and the kit's Stop hook additionally
runs the real `check`. A convincing transcript alone can't end the run.

**Recurring work: a loop**
```
/loop 30m /kit:lead next
```
Every 30 minutes the lead takes the next backlog item from `kit.json` `lead.backlog` and drives
it through implement → verify. It stops when the backlog is empty, when an item needs your
decision, or after two failed iterations in a row. Other loop ideas in Boris's style:
`/loop 10m babysit my open PRs: fix CI failures and answer review comments`, or
`/loop 1h /kit:techdebt`.

**Unattended work in the background**

Run `claude agents` (agent view) and dispatch several sessions, each with its own prompt such as
`/kit:lead <goal>`. Each one gets its own worktree, and the screen shows which session needs
you. Use this for "dozens of Claudes running".

**Scheduled in the cloud: routines**

Set up nightly or weekly jobs, like a drift check or a dependency update, at
claude.ai/code/routines or with `/schedule`. Each one opens a PR that a human reviews.

**myinsurance (the first project using the kit)**
```
/kit:lead run-group atupri sympany
```
The lead reads the decision log and backlog listed in `kit.json`, finds each group's next stage,
and runs one worker per group. Each worker loads the matching project skill. A verifier re-runs
the gate (G3/G5/G6/G8) and checks provenance. The hooks keep `data/raw` immutable and validate
manifests on every edit.

**Building or improving an LLM feature: the four LLM-quality skills**

```
kit:llm-build  ──► kit:llm-evals ──► kit:prompt-optimize ──► kit:model-select
 (design, build,    (error analysis,   (baseline → diagnose →   (same suite across
  review, gate)      taxonomy, judges   edit → keep/revert,      models; pick per role
                     calibrated vs you)  held-out split, budget)  on the Pareto frontier)
```

Each one checks its precondition and hands off to the next: `prompt-optimize` and
`model-select` refuse to run without a suite you trust and send you to `llm-evals` first.
Selection is automatic: Claude Code matches your request against the skill descriptions
("the chatbot gives wrong premiums", "tune the system prompt", "is a cheaper model good
enough?"), and `kit:lead` routes any task that touches a prompt, tool, orchestration or model
to them. There is no prompt classifier (it would cost context on every turn), but a
file-content detector costs nothing on turns that don't touch LLM code: the `llm_detect` hook
catches requests like "fix the retry in llm.py" that never mention an LLM, including raw HTTP
calls to a provider with no SDK import. `kit:verifier` fails a prompt, tool-schema or model
change that comes without an eval result. The `picks-llm-skill`, `builds-llm-tool`,
`llm-edit-detected` and `injection-aware` evals check the routing and the build discipline.

```
/kit:lead raise the advisor's completeness score without new hard-check failures, budget USD 15
```

### Which mechanism, when

| You want | Use |
|---|---|
| Turn a messy idea into a clear, launchable goal | just write it (auto) or `/kit:shape` |
| One conversation that drives a goal to done | `/kit:lead <goal>` |
| A few independent changes at once | the lead with implementers in worktrees (automatic) |
| 5–100 similar items, or results cross-checked | `/kit:ship`, `/kit:review`, or ask for "a workflow" |
| Keep going until a condition holds | `/goal <condition>` (+ the Stop hook) |
| Repeat on an interval while your laptop is on | `/loop <interval> <prompt>` |
| Repeat on a schedule with the laptop off | routines (`/schedule`) |
| Many long sessions you check on now and then | `claude agents` (agent view) |
| Improve an LLM feature (chatbot, agent, RAG) | just describe it (or just edit the code): Claude picks `kit:llm-build` / `kit:llm-evals` / `kit:prompt-optimize` / `kit:model-select` from their descriptions, and the lead routes LLM tasks to them; or call one by name |
| Teammates that talk to each other | agent teams: experimental, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`; the kit's agent definitions work as teammate types |

---

## 4. Add third-party skills and tools

Before any outside skill, plugin or tool joins the setup, it goes through the same steps below.
Every decision is recorded in [`CATALOG.md`](CATALOG.md) (adopted, trial or rejected, with the
date and the reason), so the same tool is never evaluated twice from scratch.

### 4.1 One curated marketplace

The claude-kit marketplace can list other people's plugins too, **pinned to a commit**. Add an
entry to `.claude-plugin/marketplace.json`:

```json
{ "name": "ponytail", "source": { "source": "github", "repo": "DietrichGebert/ponytail", "sha": "<commit>" } }
```

That gives you one place to install from (`claude plugin install ponytail@claude-kit`).
Upstream changes never arrive silently: updating means reading the upstream diff and bumping
the `sha`.

### 4.2 Four checks before adopting

1. **Licence.** It decides the route:
   - a permissive licence (MIT, Apache-2.0) allows vendoring an unchanged copy, with its
     `LICENSE` and `UPSTREAM_COMMIT`;
   - anything else is installed from upstream (pinned) and never copied.
2. **What it runs as you.** Read every hook, script and MCP server. A plugin runs with your user
   permissions. Reject anything that sends code or data to a third party without saying so, or
   that evades site protections.
3. **Context cost.** `claude plugin details <name>` shows the tokens added to *every* session.
   The kit costs about 950. A tool that costs more than it saves gets a project scope or a
   reject.
4. **Overlap and conflict with the kit.** Hooks matter most: two Stop hooks, two formatters or
   two "auto-continue" mechanisms fight each other. If a tool duplicates a kit piece, keep one
   of them.

### 4.3 Trial, then decide

1. Install at **local scope** in one real project, for about a week:
   `claude plugin install <name>@claude-kit --scope local`.
2. Measure where possible with `claude plugin eval`. It runs the same cases with and without the
   plugin and scores the difference. A vendor's benchmark doesn't count as evidence.
3. Write the outcome in `CATALOG.md`:
   - **adopted (user scope):** generic, useful in every project; installed via the kit;
   - **adopted (project scope):** domain-specific, e.g. frontend design; enabled only in the
     repos that need it, through that repo's `.claude/settings.json`;
   - **rejected:** with the reason, so it isn't re-evaluated from scratch.

Scope rule: **generic → user scope through the kit; domain-specific → project scope only where
needed.**

### 4.4 Keep the setup lean

- Once a month, run the built-in `/checkup`. It flags unused plugins and MCP servers and slims
  CLAUDE.md, and asks before changing anything.
- In `/plugin` → Installed, the "Not used recently" group lists plugins you can turn off.
- Remove what isn't used. Every always-on skill description costs context in every session.

### 4.5 Tools that support this

| Piece | What | Status |
|---|---|---|
| `/kit:intake <repo or name>` | Runs the four checks on a candidate, writes the `CATALOG.md` row and proposes a pinned marketplace entry and a trial | built (0.2.0) |
| Verifier memory | `kit:verifier` has `memory: project`: it reads and adds recurring pitfalls per repo | built (0.2.0) |
| Kit evals (`plugins/kit/evals/`) | `verifier-catches-bug` (claimed-done change with a bug) and `lead-verifies-before-done` (a small goal driven to done must include verification evidence); `picks-llm-skill` and `optimize-needs-evals` (LLM-quality requests reach `kit:llm-evals` / `kit:prompt-optimize`, and nobody tunes a prompt without a measure); `builds-llm-tool`, `llm-edit-detected` and `injection-aware` (0.7.0: a new tool keeps arithmetic in code with a strict schema and an eval case; an LLM file edit with no LLM words in the prompt still reaches `kit:llm-build`; web search plus private data plus rendered links is treated as the lethal trifecta) | built; see §5 for how to run (0.7.0 cases not yet run) |

First eval result (2026-10-16, one run per arm): `verifier-catches-bug` scored 1.00 with the
kit and 1.00 without (delta 0). The planted bug is obvious enough that Claude catches it either
way, and for a one-line question it doesn't delegate to the verifier. The case therefore works
as a regression check, not as proof that the kit helps. A case that tells the two arms apart
needs a defect you only find by running the code; add one when a real one turns up in a project.

LLM-quality evals (2026-10-17, one run per arm): `picks-llm-skill` 1.00 with and 1.00 without
(Δ 0; the kit loaded `kit:llm-evals`, but plain Claude also proposes measuring first, so it is a
routing check). `optimize-needs-evals` first scored 0.00 in both arms: asked to "optimize the
system prompt", Claude rewrote it blind and never loaded `kit:prompt-optimize`, whose
description then said "against an existing eval suite". After rewording the trigger ("with or
without an eval suite ... never rewrite a prompt blind") it scored 1.00 with the kit and 0.00
without (Δ +1.00).

---

## 5. Develop the kit

```bash
claude plugin validate ./plugins/kit && claude plugin validate .
claude --plugin-dir ./plugins/kit            # try changes in one session without installing
```

Run the evals (they spend real tokens; `--max-cost-usd` caps the estimate):

```bash
cd plugins/kit
claude plugin eval . --case verifier-catches-bug --scaffold --trust-plugin --no-publish --max-cost-usd 4
claude plugin eval . --case lead-verifies-before-done --scaffold --trust-plugin --no-publish \
  --allow-tools Write Edit "Bash(python3 *)" "Bash(pytest *)" "Bash(git *)" --max-cost-usd 10
claude plugin eval . --case picks-llm-skill --scaffold --trust-plugin --no-publish --max-cost-usd 3
claude plugin eval . --case optimize-needs-evals --scaffold --trust-plugin --no-publish --max-cost-usd 3
claude plugin eval . --case builds-llm-tool --scaffold --trust-plugin --no-publish \
  --allow-tools Write Edit "Bash(python3 *)" "Bash(git *)" --max-cost-usd 6
claude plugin eval . --case llm-edit-detected --scaffold --trust-plugin --no-publish \
  --allow-tools Write Edit "Bash(python3 *)" --max-cost-usd 4
claude plugin eval . --case injection-aware --scaffold --trust-plugin --no-publish --max-cost-usd 3
```

Hook self-checks (no tokens):

```bash
python3 plugins/kit/hooks/tests/test_context.py && python3 plugins/kit/hooks/tests/test_llm_detect.py
```

Test a hook by hand:

```bash
echo '{"cwd":"'$PWD'","tool_input":{"file_path":"'$PWD'/src/x.py"}}' \
  | python3 plugins/kit/hooks/scripts/on_edit.py; echo $?
```

Rules for changing the kit:

- Keep it generic. Anything project-specific goes in that project's `kit.json` or skills.
- The hooks use the Python 3.9+ standard library only, so they run on a stock macOS.
- Vendored skills stay unchanged. Update `UPSTREAM_COMMIT` when you refresh them.

## Sources

- How Boris Cherny uses Claude Code (index of his posts, with links):
  https://howborisusesclaudecode.com/
- His Jan 2026 thread on parallel sessions, CLAUDE.md, `/commit-push-pr`, subagents, the
  PostToolUse formatter hook and verification:
  https://x.com/bcherny/status/2007179833990885678
- `/go`: https://x.com/bcherny/status/2044847858634064115
- `/loop`: https://x.com/bcherny/status/2038454341884154269
- Workflows: https://x.com/bcherny/status/2060048877944778995
- Claude Code docs:
  - parallel agents: https://code.claude.com/docs/en/agents
  - workflows: https://code.claude.com/docs/en/workflows
  - agent teams: https://code.claude.com/docs/en/agent-teams
  - subagents: https://code.claude.com/docs/en/sub-agents
  - plugins: https://code.claude.com/docs/en/plugins
  - marketplaces: https://code.claude.com/docs/en/plugins/create-marketplace
  - hooks: https://code.claude.com/docs/en/hooks
