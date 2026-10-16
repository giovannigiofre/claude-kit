---
name: intake
description: Evaluates a third-party skill, plugin or tool before it joins the setup - licence, what it runs as the user, context cost, overlap with the kit - then writes the CATALOG.md entry and proposes a pinned marketplace entry and a trial. Use when the user mentions adopting, installing or trying an outside skill/plugin/tool ("should we use X", "add Y to the kit", "install Z").
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
4. **Overlap and conflict with the kit.** Compare with `kit:lead`, the kit agents, `/kit:go`,
   `/kit:review`, and the kit hooks (SessionStart notice, PreToolUse protect, PostToolUse onEdit,
   Stop check). Two Stop hooks, two formatters or two auto-continue mechanisms fight; say which
   one should win.
5. **Claims.** Separate vendor-reported numbers from independent evidence. A vendor benchmark is
   not evidence that it helps in this user's projects.
6. **Decide a proposal**: `adopted-user`, `adopted-project` (which repos), `vendored`, `trial`
   (default for anything plausible), or `rejected`, with the reason in one or two sentences.
7. **Write it down**: add or update the row in `CATALOG.md` (date = today). For `trial`/adopted
   plugins, add a marketplace entry pinned to the reviewed commit:
   `{"name": "<name>", "source": {"source": "github", "repo": "<owner/repo>", "sha": "<sha>"}, "description": "..."}`
   and run `claude plugin validate <kit dir>`.
8. **Propose the trial** (do not run it without the user's go-ahead): the project, the install
   command `claude plugin install <name>@claude-kit --scope local`, any config to change
   (e.g. turn off telemetry or ledgers), what to watch for a week, and - if feasible - a
   `claude plugin eval` comparison. Show the diff of CATALOG.md and marketplace.json; commit only
   if asked.
