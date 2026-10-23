# Captain mode (`/kit:lead captain`, or `/loop /kit:lead captain`)

The user stops prompting workers one by one and talks to you instead; you are the loop that
prompts them. (Idea: Boris Cherny, who says loops now do his prompting while he talks to one
coordinating Claude; mechanics adapted from kunchenguid/firstmate, MIT. Nothing copied.)

From the lead skill, sections 0-3 apply to every item (ground rules, done-criterion, brief,
independent verification). Sections 4 and 5 do not: items ship one by one as set below, and
replies stay short.

## Start (once per session)

Skip this whole section when you already started the captain in this conversation (a self-paced
`/loop` re-sends the same prompt on every wake-up): go to "Each wake-up".

1. Read the board (`.claude/lead/board.md`, or `kit.json` `lead.board`) if it exists, else
   create it. If `.claude/lead/` is not gitignored, add `/.claude/lead/` to `.git/info/exclude`,
   so board rewrites never count as changes for the Stop hook's `check`.
2. Ask once with AskUserQuestion, taking defaults from `kit.json` `lead` where set:
   - how finished work ships: `local-only` (verified branches, the user merges), `pr` (the
     `/kit:go` steps up to the PR), `pr+babysit` (also keep CI green). Confirm it even when
     `kit.json` sets it: pushing needs the user's go-ahead in this session;
   - how many items run in parallel (default 3);
   - a budget: a cap on items started this session, or none.
3. Standing loops from `lead.loops`: list existing jobs with CronList first and create only the
   missing ones with CronCreate (session-only; recurring jobs expire after 7 days and fire only
   while the session is idle: say so). Each job's prompt is `/kit:lead captain loop <name>`, so
   the loop's work comes back to you and you hand it to a background agent (below). Without
   CronCreate, print the `/loop <every> /kit:lead captain loop <name>` line for the user.
4. Say in two lines what you will do.

## The board

The state that survives compaction and restarts. Rewrite it whole at every change (never
append), max ~60 lines, and keep a pointer to it in the handoff note:
```
SHIP: pr+babysit | PARALLEL: 3 | BUDGET: none (or: 4 of 10 items) | LOOPS: babysit-prs 10m
NEEDS YOU: <id: the decision, one line each; empty if none>
<id> | <ship|scout|overnight> | <goal> | DONE WHEN <check> | <queued|running|verifying|shipping|ci|needs-you|done|parked> | agent <name> | <branch/worktree/PR> | <last event>
```

## Each user message is one of four things

Handle it, update the board, reply in 2-4 lines, and hand control back at once. Never wait on
workers in the foreground: background agents and monitors wake you when they finish. Ask the
user in plain text; AskUserQuestion holds the turn and is for the start only.
1. **New work.** Split it into items. Give each a checkable DONE WHEN; if that needs a decision
   only the user can make, put the question under NEEDS YOU and go on with the rest.
   - **ship**: changes code.
   - **scout**: only finds something out. An Explore agent does the reading; you write its
     result to `.claude/lead/reports/<id>.md`.
   - **overnight**: hours of grinding toward one measurable objective. With the user's OK,
     launch `kit:overnight`'s runner with Bash `run_in_background`, always with `--worktree`.
2. **Steering** an item ("also handle X", "drop Y", "do Z first"): continue its worker with
   SendMessage to the agent name on the board when the change fits its brief; otherwise stop it
   (TaskStop), park or delete its branch, and requeue with the new brief.
3. **A question or "status"**: answer from the board and from what the workers reported, not
   from memory.
4. **A decision** on a NEEDS YOU item: apply it and resume that item.

## Dispatch

While fewer than PARALLEL items run (and the budget allows), start the next queued one in the
background, named after the item id so it can be reached after a compaction:
`kit:implementer` with `isolation: "worktree"` for ship items, Explore for scout items, each
with the self-contained brief from section 2. When a worker returns, send the result to
`kit:verifier` in the background; FAIL goes back to an implementer (max 3 rounds, then NEEDS
YOU). When an item passes:
- `local-only`: mark it done with its branch.
- `pr` and `pr+babysit`: brief a background general-purpose agent to carry out the steps of the
  kit's go skill on that branch. Give it the absolute path of that file: `../go/SKILL.md`
  relative to the directory you read this file from (check it exists with `ls` before you
  brief; subagents cannot resolve it themselves). Also give it the item's intent. Tell it: arguments `no-babysit`; it cannot ask the user, so it returns
  ask-user findings instead of asking and opens no PR while any are open; it returns the PR URL,
  the evidence verdict and the risk. Ask-user findings go to NEEDS YOU.
- `pr+babysit`, once the PR exists: set the item to `ci` and start a Monitor on
  `gh pr checks <PR>` that prints each finished check and exits when none is pending (timeout
  30 min; re-arm it when it expires). On a failure, brief a background agent to fix it as in
  `/kit:go` step 9 (max 3 rounds, then NEEDS YOU).

Anything outward-facing that the user has not approved in this session goes to NEEDS YOU.

## Standing loops

Boris's pattern: turn a workflow into a skill, then run it as a loop. `kit.json` `lead.loops`,
e.g. `[{"name": "babysit-prs", "every": "10m", "run": "/kit:go babysit"}]`. When a job fires
(`/kit:lead captain loop <name>`), never run its work in the foreground: hand `run` to a
background general-purpose agent with the same rules as above (absolute skill path, no
questions to the user) and reply in one line. A babysitting loop skips PRs whose item is in
`ci`: those already have a monitor and a fixer. Good candidates: PR babysitting, review comments
left after a merge, stale PRs, new issues or feedback turned into scout items.

## Heartbeat

Started as `/loop /kit:lead captain` (self-paced): after each wake-up, schedule the next one with
ScheduleWakeup, 1200-1800 s when nothing external is pending, the expected CI duration when you
are watching a run; `noop: true` when nothing changed. Started as plain `/kit:lead captain`, you
wake only on worker and monitor events, cron jobs and the user's messages, which is enough while
work is running.

## Each wake-up

Whatever woke you: advance the items whose workers finished, dispatch, then reply with at most
4 lines: started, finished (verified, with PR or branch), NEEDS YOU. Batch questions: interrupt
only when nothing else can move without the user.

## Stop

- **The user says stop** ("stop", "captain off", "pause"): delete the cron jobs you created
  (CronDelete), end a self-paced loop (ScheduleWakeup with `stop: true`), let running workers
  finish unless told to stop them, rewrite the board, and report what is done, running and
  waiting.
- **Budget reached:** stop dispatching new items; finish the running ones.
- **Queue empty:** end the heartbeat; keep the standing loops while PRs are open; report and wait
  for the next message.
- **Two items in a row fail verification after 3 rounds:** stop dispatching, report, wait.
- **No budget:** the captain runs until one of the above.
