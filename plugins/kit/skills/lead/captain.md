# Captain mode (`/kit:lead captain`, or `/loop /kit:lead captain`)

The user stops prompting workers one by one and talks to you instead; you are the loop that
prompts them. (Idea: Boris Cherny, who says loops now do his prompting while he talks to one
coordinating Claude; mechanics adapted from kunchenguid/firstmate, MIT. Nothing copied.)

**Start (once).** Read the board if one exists (`.claude/lead/board.md`, or `kit.json`
`lead.board`), else create it. Ask once with AskUserQuestion, unless `kit.json` `lead` already
says: how finished work ships (`local-only`: verified branches to merge; `pr`: the `/kit:go`
steps up to the PR; `pr+babysit`: also watch CI until green), how many items may run in
parallel (default 3), and a budget (a cap on items started this session, or none). Then start
the standing loops in `lead.loops` (below) and say in two lines what you will do.

**The board** is the state that survives compaction and restarts. Rewrite it whole at every
change (never append), max ~60 lines:
```
SHIP: pr+babysit | PARALLEL: 3 | BUDGET: none | LOOPS: babysit-prs every 10m
NEEDS YOU: <id: the decision, one line each; empty if none>
<id> | <ship|scout> | <goal> | DONE WHEN <check> | <queued|running|verifying|shipping|ci|needs-you|done|parked> | <branch/worktree/PR> | <last event>
```
Keep a pointer to it in the handoff note, so it comes back after a compaction.

**Every user message is one of four things.** Handle it, update the board, reply in 2-4 lines,
and hand control back at once. Never wait on workers in the foreground: background agents and
monitors wake you when they finish.
1. **New work.** Split it into items. Give each a checkable DONE WHEN; if that needs a decision
   only the user can make, ask one short question or put it under NEEDS YOU and go on with the
   rest. A **ship** item changes code; a **scout** item only finds out something and writes
   `.claude/lead/reports/<id>.md`. Hours of grinding toward one measurable objective becomes a
   `kit:overnight` item, launched in the background with the user's OK.
2. **Steering** an item ("also handle X", "drop Y", "do Z first"): continue the running worker
   with SendMessage when the change fits its brief; otherwise stop it (TaskStop), undo or park
   its branch, and requeue with the new brief.
3. **A question or "status"**: answer from the board and from what the workers reported, not
   from memory.
4. **A decision** on a NEEDS YOU item: apply it and resume that item.

**Dispatch.** While fewer than PARALLEL items run, start the next queued one: a `kit:implementer`
with `isolation: "worktree"` in the background (or an Explore agent for scout items), with the
self-contained brief from section 2. When a worker returns, send the result to `kit:verifier`
in the background; FAIL goes back to an implementer (max 3 rounds, then NEEDS YOU). When an
item passes: for `local-only`, mark it done with its branch; for `pr`, have a background
general-purpose agent carry out the steps of the kit's `go/SKILL.md` on that branch with
`no-babysit` and return the PR URL, evidence verdict and risk; for `pr+babysit`, then watch CI
with a Monitor on `gh pr checks` that emits each finished check and exits when none is pending,
and fix failures as in `/kit:go` step 9. Ask-user findings and anything outward-facing that was
not approved go to NEEDS YOU.

**Standing loops** (Boris's pattern: turn a workflow into a skill, then run it as a loop).
`kit.json` `lead.loops`, e.g.
`[{"name": "babysit-prs", "every": "10m", "run": "/kit:go babysit for each open PR of mine"}]`.
Start each with CronCreate if the tool exists (session-only; recurring jobs expire after 7
days: say so), else print the `/loop <every> <run>` line for the user. Good candidates: PR
babysitting, sweeping review comments left after merge, closing stale PRs, turning new issues
or feedback into scout items.

**Heartbeat.** Started as `/loop /kit:lead captain` (self-paced), schedule the next wake-up with
ScheduleWakeup: 1200-1800 s when nothing external is pending, the expected CI duration when you
are watching a run; `noop: true` when nothing changed. Started as plain `/kit:lead captain`, you
wake only on worker and monitor events and on the user's messages, which is enough while work
is running.

**Each wake-up**, whatever woke you: advance the items whose workers finished, dispatch, then
reply with at most 4 lines: started, finished (verified, with PR or branch), NEEDS YOU. Batch
questions: interrupt only when nothing else can move without the user.

**Stop** when the user says so ("stop", "captain off", "pause"): delete the cron jobs you created
(CronDelete), end a self-paced loop (ScheduleWakeup with `stop: true`), let running workers
finish unless told to stop them, rewrite the board, and report what is done, running and
waiting. Also stop dispatching when the budget is reached; with no budget, the captain runs
until the user stops it, the backlog is empty, or two items in a row fail verification after 3
rounds (then report and wait).
