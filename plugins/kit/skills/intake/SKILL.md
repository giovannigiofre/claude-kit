---
name: intake
description: Evaluates a third-party skill, plugin or tool before it joins the setup - licence, what it runs as the user, context cost, overlap with the kit - then writes the CATALOG.md entry and proposes a pinned marketplace entry and a trial. Use when the user mentions adopting, installing or trying an outside skill/plugin/tool ("should we use X", "add Y to the kit", "install Z").
disable-model-invocation: true
argument-hint: <github owner/repo, URL or name>
---

# /kit:intake - adopt outside tools deliberately

Candidate: $ARGUMENTS

The kit lives at the marketplace named `claude-kit` (find its directory with
`claude plugin marketplace list`). Its `CATALOG.md` is the record; README §4 is the procedure.

1. **Look it up first.** If `CATALOG.md` already has the tool, report that decision and stop
   unless the user wants a re-evaluation (then say what changed).
2. **Identify the real source.** Find the canonical repository (not an aggregator or a fork),
   the latest commit sha, the licence file, and what kind of thing it is: skill, plugin,
   MCP server, separate agent/harness. If it is a separate harness (it replaces Claude Code),
   record it as "not an addition" and stop.
3. **Clone into the session scratchpad** (a new empty directory; never run its code or install
   it during the review) and read:
   - the licence -> MIT/Apache/BSD: may be vendored unchanged; anything else: upstream install only;
   - every hook config and the scripts they call, every MCP server, every command that runs a
     process: what runs, when, what it writes where, and whether anything leaves the machine
     (network calls, webhooks, telemetry) and if so whether it is opt-in;
   - its always-on text: SessionStart/SubagentStart injections, skill descriptions. Estimate
     the per-session context cost (after a trial install, `claude plugin details <name>` gives
     the real figure).
4. **Overlap and conflict.** Compare with Claude Code's built-ins first (`/code-review`,
   `/simplify`, `/goal`, `/loop`, `/autofix-pr`, agent view, workflows: a third-party copy of a
   native feature is usually a reject), then with the kit: `kit:lead`, the kit agents, `/kit:go`,
   and the hooks (SessionStart notice, PreToolUse protect and guard, PostToolUse onEdit, Stop
   check). Two Stop hooks, two formatters or two auto-continue mechanisms fight; say which one
   should win.
5. **Instructions it adds.** Generic behaviour rules ("think step by step", "keep it simple",
   mandatory TDD or planning) have measurably lowered pass rates and raised cost on current
   models; count them as a cost, not a feature.
6. **Claims.** Separate vendor-reported numbers from independent evidence. A vendor benchmark is
   not evidence that it helps in this user's projects.
7. **Decide a proposal**: `adopted-user`, `adopted-project` (which repos), `vendored`, `trial`
   (default for anything plausible), or `rejected`, with the reason in one or two sentences.
8. **Write it down**: add or update the row in `CATALOG.md` (date = today). For `trial`/adopted
   plugins, add a marketplace entry pinned to the reviewed commit:
   `{"name": "<name>", "source": {"source": "github", "repo": "<owner/repo>", "sha": "<sha>"}, "description": "..."}`
   and run `claude plugin validate <kit dir>`.
9. **Propose the trial** (do not run it without the user's go-ahead): the project, the install
   command `claude plugin install <name>@claude-kit --scope local`, any config to change
   (e.g. turn off telemetry or ledgers), what to watch for a week, and - if feasible - a
   `claude plugin eval` comparison. Show the diff of CATALOG.md and marketplace.json; commit only
   if asked.

## Writing, adapting or rewriting a skill

When the decision means writing skill text - a kit wrapper that orders outside tools (like
`kit-ui:ui` over impeccable and taste), an `adapted (method only)` skill, a rewrite of a vendored
skill, or a new kit skill - load `skill-creator` (Anthropic, `skill-creator@claude-plugins-official`,
Apache-2.0, `adopted-user`) and follow its loop instead of writing freehand:

1. Capture intent from the conversation first; ask only what it does not answer.
2. Draft `SKILL.md`: a "pushy" description that carries every trigger, a body under 500 lines,
   the why behind each rule, references split out for detail.
3. Write 2-3 realistic test prompts to `evals/evals.json` beside the skill.
4. Run them with the skill and without it (or with the old version) in parallel subagents, in a
   workspace outside the repo (the session scratchpad); draft assertions while they run.
5. Grade, aggregate, and show the user the outputs with `eval-viewer/generate_review.py`
   (`--static <file>` in a background or headless session) before revising.
6. Revise from the feedback; repeat until the user is satisfied.
7. Offer the description optimization loop (`scripts/run_loop.py`) for skills that must
   trigger on their own.

Kit conventions still apply: generic skills live in `plugins/kit/skills/<name>/`, domain skills
in a domain plugin (`plugins/kit-ui`, `plugins/kit-llm`, or a new `kit-<domain>` that
`kit:extras` then offers); keep `evals/` in the repo, add a row to the README and, for wrappers,
to CATALOG.md. Run `python3 tests/test_budget.py` from the kit repo: it fails when the kit's
always-loaded text grows past its budget.
