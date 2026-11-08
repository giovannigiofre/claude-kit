# B: prose audit of claude-kit 1.9.0 (read-only)

Scope read: every SKILL.md and sibling file under `plugins/kit/skills`, both agents, the text the hooks inject (`session_start.py`, `subagent_start.py`, `subagent_stop.py`, `stop_check.py`, `kit.tsx`, `watchdog.ts`), README, docs/reference.md, CATALOG.md, and the kit-llm / kit-ui skills and hook. Claims about Claude Code were checked against the current docs (sub-agents, hooks, skills, worktrees, scheduled-tasks, cross-session-messaging, agent-teams, tools-reference, settings-reference, plugin CLI, headless, memory) and the changelog up to 2.1.319. Script subcommands were checked against the dispatch code in `items.py`, `proposals.py`, `lessons.py`, `gate.py`. `python3 tests/test_budget.py` passes (kit 2531/2600 always-on chars).

Ranked by value over cost. Severity: high = the model will do the wrong thing.

---

## 1. Fresh-eyes logs a status that hides the item from `next`

Severity: **high** · Cost: S · Confidence: high

Evidence:
- `plugins/kit/skills/lead/fresh-eyes.md:27-28`: "Log it (`items.py log <id> checked "fresh eyes: <n> gaps fixed"`)."
- `plugins/kit/hooks/scripts/items.py:37`: `STATUSES = ("queued", "working", "review", "needs-you", "landing", "done", "parked", "reported", "verdict")`; `items.py:121-130` `status_of` returns the status word of the **last** LOG line; `items.py:196-206` `list_items(status=...)` filters on it.
- `plugins/kit/skills/lead/SKILL.md:9-10`: "`next`: the next queued item on disk" (the lead finds it with `$I list --status queued`, `SKILL.md:36-45`).

After the fresh-eyes pass the item's last LOG line is `checked`, so `list --status queued` no longer returns it and `next` skips straight to proposal cards or the backlog. `items.py log` accepts any word, so nothing warns.

Change: in fresh-eyes.md write `$I log <id> queued "fresh eyes: <n> gaps fixed"` (the status stays `queued`, the note carries the fact). Optionally add `checked` to `STATUSES` and make `list` treat it as queued, but the prose fix alone removes the failure.

## 2. The lead is told both to merge only on the user's word and to merge on its own

Severity: **high** · Cost: S · Confidence: high

Evidence:
- `plugins/kit/skills/lead/SKILL.md:76`: "**"Merge it":** merge the PR (`gh pr merge`) only on the user's word."
- `plugins/kit/skills/lead/SKILL.md:114-117`: "`agent`: merge it yourself (`gh pr merge --squash --delete-branch` …) once CI is green, the review has nothing open and the risk is not high".
- Same policy in `README.md:47-49` and `plugins/kit/skills/go/SKILL.md:59-63`.

In a project with `lead.merge: agent` the two sentences contradict; a literal reader waits for a word that, by policy, is not coming. (The owner's rule that the loop template never merges is a different thing and is respected by `init/loop.md:25`.)

Change: delete the "Merge it" bullet from "Each message", or rewrite it as "**"Merge it"** (merge `user` or `ask`): merge that PR now and `$I done` it." The merge-policy paragraph already covers the rest.

## 3. `EXPECT:` is read from the Agent prompt, but the lead may leave it in BRIEF.md

Severity: **medium** (a safety net silently off) · Cost: S · Confidence: high

Evidence:
- `plugins/kit/skills/lead/SKILL.md:42-44`: "Brief a thread with the `ITEM: <id>` line, the absolute BRIEF.md path … and only what the file lacks."
- `plugins/kit/skills/lead/SKILL.md:88-89`: "an `EXPECT: 90m` line, how long it should run (the watchdog checks on it past that)".
- `plugins/kit/hooks/kit.tsx:397`: `expectMs: expectedMs(String(e.prompt ?? ''))` — the watchdog parses the **Agent call's prompt**, never BRIEF.md on disk. `docs/reference.md:268` says "an `EXPECT: 90m` (or `2h`) line in the brief", which the lead can read as the file.

Change: in the "Threads" bullet say "an `EXPECT: 90m` line **in the Agent prompt itself** (the watchdog reads the prompt, not BRIEF.md)". This also resolves the two competing descriptions of the brief (items 42-45 vs 85-100): the prompt is ITEM line + path + EXPECT + effort/ship + whatever BRIEF.md lacks.

## 4. Thread names assume agent teams, which the kit does not enable

Severity: **medium** · Cost: S · Confidence: medium-high

Evidence:
- `plugins/kit/skills/lead/SKILL.md:80-81`: "`kit:implementer` in the background with `isolation: "worktree"`, named after the item id"; `SKILL.md:65-66`: "SendMessage to its agent name"; board column `agent <name>` (`SKILL.md:28`); `SKILL.md:44`: `$I log <id> working "thread <name>"`.
- sub-agents docs, "Subagent names": "If you start a session with agent teams enabled, Claude can give a subagent a name by passing a `name` parameter on the Agent tool call." Tools reference, Agent row: "With agent teams enabled, a call that carries a `name` can launch a teammate instead." agent-teams docs: "Agent teams are experimental and disabled by default. Enable them by setting `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`".
- `CATALOG.md:96` records agent teams as "Not taken now … (experimental)".
- Resume works without a name: sub-agents docs, "Resume subagents": "Claude uses the `SendMessage` tool with the agent's ID or name as the `to` field … `SendMessage` doesn't require agent teams to be enabled."

Without the variable there is no name to give; the ID the Agent call returns is the handle, and the ID is also what survives a restart ("give Claude the subagent's agent ID instead"). The watchdog already falls back (`kit.tsx:349`, `a.name || a.description || a.id`).

Change: lead `SKILL.md:80-81` → "…with `isolation: "worktree"`; keep the agent ID the call returns: it is how you SendMessage, TaskStop and log the thread (`$I log <id> working "agent <agentId>"`). A name works only in a session with agent teams on." Rename the board column to `agent <id>`. Drop "named after the item id". `docs/reference.md` and `CATALOG.md:96` ("SendMessage to resume a finished thread … names survive restarts from 2.1.299") need the same one-line correction.

## 5. Where a scout thread's report goes: two answers

Severity: **medium** · Cost: S · Confidence: high

Evidence:
- `plugins/kit/skills/lead/SKILL.md:68-69`: "Finding something out without changing code is a **scout** thread; save its report to `.claude/lead/reports/<id>.md`."
- `plugins/kit/skills/lead/SKILL.md:38-39` and `docs/reference.md:170`: REPORT.md under `.claude/lead/items/<id>/` is written by the SubagentStop hook for a kit:implementer briefed with `ITEM:`.
- `items.py:17` offers `--kind ship|scout`; no skill ever uses it. The lead does not say which agent type a scout thread is (kit:implementer, which the hook files, or Explore, which it does not).

Change: one sentence in the lead: "A scout thread is a `kit:implementer` made with `$I new … --kind scout` and briefed read-only; its report lands in the item's REPORT.md like any other." Delete `.claude/lead/reports/`. If the owner prefers Explore agents for scouting, say so and keep the file path, but then say the hook does not file it.

## 6. Dangling "README §4"

Severity: **medium** · Cost: S · Confidence: high

Evidence:
- `plugins/kit/skills/intake/SKILL.md:13`: "Its `CATALOG.md` is the record; README §4 is the procedure."
- `CATALOG.md:4`: "The procedure is in [README §4](README.md#4-add-third-party-skills-and-tools)."; `CATALOG.md:54`: "README §4.3".
- `README.md` has no numbered sections (A day with the kit, How it works, What's in it, Install, Safety, Changing the kit, Sources); the anchor does not exist.

The model running `/kit:intake` is sent to read a section that is not there. Also stale in CATALOG (history-exempt in the test, but still a pointer): `kit:llm-evals`, `kit:model-select`, `kit:prompt-optimize`, `kit:llm-build` (`CATALOG.md:35-47`) are now `kit-llm:llm-evals` (`model-select.md`, `prompt-optimize.md`) and `kit-llm:llm-build`.

Change: intake line 13 → "Its `CATALOG.md` is the record; the steps below are the procedure." CATALOG line 4 → "The procedure is `/kit:intake`." Line 54: drop "README §4.3". Search-replace the four old skill names.

## 7. Verify vs e2e: the init description and the README table still say "e2e skill"

Severity: low · Cost: S · Confidence: high

Evidence: `plugins/kit/skills/init/SKILL.md:3` (description): "a project e2e skill that says how to exercise the app"; `README.md:116`: "`/kit:init` | Sets up a project (kit.json, e2e skill, safety, permissions)"; versus `init/SKILL.md:42-49`, `README.md:21`, `CATALOG.md:80`: the skill is named `verify` since 2.1.286 ("an older `e2e` skill keeps working but is not run natively: rename it"). Docs confirm the mechanism: skills.md "When a session starts with a skill named `verify` or `simplify` in place, Claude Code's commit instructions tell Claude to run it right before each commit".

Change: "e2e skill" → "verify skill" in both places.

## 8. Lead's `$I` definition and path lookup: use `${CLAUDE_SKILL_DIR}` like every other skill

Severity: low (readability, one wasted tool call per session) · Cost: S · Confidence: high

Evidence: `plugins/kit/skills/lead/SKILL.md:36-37`: "(`I` is `python3 <kit>/hooks/scripts/items.py`; the kit's install path is in `claude plugin marketplace list --json`)"; `SKILL.md:48`: `python3 <kit>/hooks/scripts/proposals.py take <id>`. Handoff, scout and learn define the same scripts as `python3 ${CLAUDE_SKILL_DIR}/../../hooks/scripts/items.py` (`handoff/SKILL.md:14-16`). skills.md: "`${CLAUDE_SKILL_DIR}` … The directory containing the skill's `SKILL.md` file. For plugin skills, this is the skill's subdirectory within the plugin" and it is substituted in the markdown body.

Change: define `I` and `P` once in the lead with the `${CLAUDE_SKILL_DIR}/../../hooks/scripts/` form and the same "if not expanded" fallback the other skills carry; delete the marketplace-list parenthetical. (Keep the `claude plugin marketplace list --json` lookup only in `init` step 9, where an absolute path is written into a committed file.)

## 9. Board header disagrees between the lead and the reference

Severity: low · Cost: S · Confidence: high

Evidence: `plugins/kit/skills/lead/SKILL.md:25`: `SHIP: <local | pr | pr+fix> | MERGE: <user | agent | ask> | PARALLEL: <n> | BUDGET: …`; `docs/reference.md:421`: `SHIP: pr | PARALLEL: 3 | BUDGET: none` (no MERGE). The mod only keys on `SHIP:`/`RULES:`/`NEEDS YOU:` (`kit.tsx:184-191`), so nothing breaks, but the user doc shows a board the lead never writes.

Change: add `| MERGE: user` to the reference's block.

## 10. Reference claims about effort and `-p` that overstate the docs

Severity: low · Cost: S · Confidence: high

Evidence:
- `docs/reference.md:209-210`: "`kit:implementer` declares `effort: medium` (Opus 5.5's default) as its **floor**, so a session running at `xhigh` does not spawn `xhigh` threads". sub-agents docs, `effort` field: "Effort level when this subagent is active. **Overrides** the session effort level, but not the `CLAUDE_CODE_EFFORT_LEVEL` environment variable." It is a fixed level, not a floor: a `low` session also gets `medium` threads. Changelog 2.1.317: "Changed subagents … on a different model from the main conversation to use that model's saved effort level or its default, instead of the session's effort level" (the implementer is `model: opus`); 2.1.316 added `CLAUDE_CODE_SUBAGENT_EFFORT`.
- `docs/reference.md:450-451`: "since Claude Code 2.1.302 `-p` would otherwise start in the manual mode". Changelog 2.1.302: "Changed `claude -p` and Agent SDK sessions with no permission mode to start in `default` mode **on third-party providers, with telemetry off or on a fresh install**; `--permission-mode auto` keeps auto."

Change: "declares `effort: medium`, the level its threads run at whatever the session's; the call's `effort` overrides it" and "(on third-party providers, with telemetry off or on a fresh install, 2.1.302+, `-p` starts in manual mode without it)". Everything else in that section (per-call override, survives resume, 2.1.292, the five values, `CLAUDE_CODE_EFFORT_LEVEL` beats both) matches the docs word for word.

## 11. Undocumented kit.json key `verifyTimeout`

Severity: low · Cost: S · Confidence: high

Evidence: `plugins/kit/hooks/scripts/gate.py:128`: `config.get("checkTimeout" if name == "check" else "verifyTimeout", 1800)`; `docs/reference.md:7-36` and `init/SKILL.md:98-112` list `checkTimeout` only.

Change: add `"verifyTimeout": 1800` to the reference schema with one clause ("the gate's `verify` run; `gate.py --timeout` overrides"), or drop the key from gate.py.

## 12. Instructions that duplicate a hook, a script or the native default

Severity: low · Cost: S · Confidence: high

- `plugins/kit/skills/lead/SKILL.md:21-22`: "Add `/.claude/lead/` to `.git/info/exclude` unless it is gitignored." `items.py:138` (`ensure_excluded`) does this on every `new`; `docs/reference.md:190` says so. Delete the sentence.
- `plugins/kit/skills/lead/SKILL.md:58-59`: "Never wait on a thread in the foreground or poll it". Subagents start in the background by default (sub-agents docs: "With nothing configured, a subagent that Claude spawns from your main conversation starts in the background") and the guard's wait rule refuses foreground sleeps and poll loops (`guard.py:1005-1057`, `docs/reference.md:61-66`). Keep only the useful half: "To wait on CI or a deploy, arm one Monitor or background command per subject, before you tell the user "I'll let you know"."
- `plugins/kit/agents/implementer.md:34-35` / `verifier.md:28`: "wait for its notice, not in a loop" — same guard rule; "one watcher per thing you wait on" is the part worth keeping.

## 13. The same guidance in three or four places

Severity: low · Cost: M · Confidence: high

- CLAUDE.local.md + `@AGENTS.md` + `.worktreeinclude`: `README.md:175-181`, `init/SKILL.md:29-32` and `50-54`, `lead/SKILL.md:91-93`. Home: init step 6 (it writes the files). README keeps one line with a link; the lead keeps "thread facts go in `CLAUDE.local.md` (listed in `.worktreeinclude`); `lead.notes` is yours only" and drops the AGENTS.md clause.
- Attribution setting + auto-mode allow rule: `README.md:147-156`, `docs/reference.md:56-60`, `71-75`, `85-93`, `init/SKILL.md:73-81`, plus the SessionStart offer text (`session_start.py:104-111`). Home: reference "Auto mode environment" (the full story) and the hook (the action). README: two lines and a link. init step 11: the action only ("set attribution … ; the machine settings are offered at session start, `machine_setup.py --apply` if declined earlier").
- The hook list in `README.md:76-100` repeats `docs/reference.md` sections (Stop hook, SubagentStart, lessons, distiller) at near-full length. Keep the README block to one line per hook.

## 14. Readability in the skills the model acts on most

Severity: low · Cost: S each · Confidence: high

- `lead/SKILL.md:85-100`: the brief's bullet list is one 15-line sentence chain with nested parentheticals ("UI or LLM work whose kit plugin is missing here: offer it first (`kit:extras`), then the skill file's absolute path. Thread facts go in …; `lead.notes` is yours only;"). Split into "what the prompt carries" (goal/DONE WHEN/scope, EXPECT, ship mode, effort, skills by absolute path) and one separate sentence on where project facts live.
- `lead/SKILL.md:83-84` and `implementer.md:18-19`: `git -C <repo> worktree add -b <branch> <repo>-<id> origin/<default>` creates the worktree **inside** `<repo>` unless `<repo>` is an absolute path (the path is resolved after `-C`). Say "`<repo>` absolute" or write `../<name>-<id>`.
- `implementer.md:26-35` (step 3): one ten-line sentence with three parentheticals; "your caller is not blocked on you" has no clear referent for a thread. Three sentences: the gate; the surface; long commands.
- `verifier.md:18-19`: "`git show origin/main:CLAUDE.md`" hard-codes `main` in the same sentence that says "from the base branch"; write `origin/<base>`.
- `go/SKILL.md:48-58` (step 7): four mechanisms (`/autofix-pr`, `gh pr checks --watch`, bare `/loop`, `babysit`) in one paragraph with a parenthetical about user-only skills at the end. Three short paragraphs: watch; fix (3 rounds); hand over after ~10 min.
- `lead/SKILL.md:50-54` plus `123-124`: default ship is `pr`, yet "ask once before the first push" — both true, but a reader has to join two paragraphs 70 lines apart. Put the ask-once clause next to the defaults.

---

## Verified and correct (no change)

For the record, these were checked and hold for 2.1.319: `isolation: worktree` branches from the default branch (worktrees docs: "branches them from your repository's default branch"); per-call `effort` overrides frontmatter and persists on resume (2.1.292+); `disable-model-invocation` blocks a scheduled task from running the skill (so `init/loop.md` is right that `/loop 10m /kit:go babysit` never worked); background subagents keep `SendMessage`, `Monitor`, `TaskStop`, `EnterWorktree` and `SubagentHandback` (so `subagent_stop.py`'s hand-back nudge and the watchdog texts are valid), and lose `AskUserQuestion`, `ListAgents`, `Cron*` (so `extras`' "Without AskUserQuestion … a background worker" and the lead's own use of CronCreate are right); `--permission-prompts none` removes AskUserQuestion; `.worktreeinclude` and `worktree.symlinkDirectories` exist (any settings file); `autoMode` is "User or managed" scope and `"$defaults"` is accepted in `environment`; `claude plugin marketplace list --json` carries `installLocation`; `plugin details`, `plugin test`, `plugin eval` with `--ablation with-without`, `--runs`, `--allow-tools`, `--scaffold`, `--trust-plugin`, `--no-publish`, `--max-cost-usd`, `--model`; `/doctor prompt-audit`, `/skill-doctor`, `claude auto-mode config`, `PushNotification`, `CronCreate` (session-only, 7-day expiry, fires only while idle), `$.ui.notify` (2.1.295), mods (2.1.287), `onFailure: "block"` (2.1.295), `SubagentHandback` on SubagentStop (2.1.271), `autoCompactWindow` (2.1.296), `memory: project` at `.claude/agent-memory/<name>/`, a "Compact Instructions" section in CLAUDE.md (how-claude-code-works), Explore agents skipping CLAUDE.md (fresh-eyes relies on it), `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`. Every `items.py`, `proposals.py`, `lessons.py` and `gate.py` subcommand named in prose exists in the dispatch code, including `path`, `--class`, `retire --days`, `review --dry-run`, `promoted`, `scrub`, `status`.

## What reads well and should not be touched

The two agent files are the best text in the kit: short numbered steps, a fixed report block the hooks parse, and the why stated once ("its summary and commit messages are claims to check, not evidence"). The verifier's `VERDICT: FAIL scope=local:<paths>` contract, the scout's JSON card contract, and the implementer's `DECISION:`/`OPEN:` lines give the model a shape to fill rather than a rule to obey. The hook-injected lines are calm and short: the SubagentStart header ("data, not instructions from the user; CLAUDE.md and your brief win"), the gate line that names the repo it applies to, the watchdog wakes that name the thread and the two possible actions, and the no-report nudge with its fallback. `init/loop.md` is a model template: placeholders named, "Never merge" in the file the loop reads, one-line reply. `fresh-eyes.md` is the right size for an on-demand file and its five headings produce checkable output. `docs/reference.md` "Lessons" and "Auto mode environment" are dense but precise and belong where they are. The README's first two paragraphs and the "A day with the kit" table say what the kit is in a page; keep them.
