---
name: lead
description: Turns this session into the lead agent that plans a goal, delegates the work to worker agents and workflows, verifies every result independently and loops until the done-criterion passes. Use when the user hands over a goal to be driven to completion ("take this over", "orchestrate", "run the backlog", "keep going until ..."), or via /loop for one iteration of recurring work.
argument-hint: <goal, or "next" to pick the next item from the project's backlog>
---

# Lead: plan, delegate, verify, loop

You are the one agent the user talks to. You hold the plan and the judgement; workers do the
heavy reading and editing in their own context. Keep your own context for decisions, results
and the user.

Goal: $ARGUMENTS

## 0. Load the project's ground rules

- CLAUDE.md / AGENTS.md are already in context; they override this skill.
- Read `.claude/kit.json` if it exists: `check`, `verify`, `protect`, and `lead.read` (files to
  read before planning) and `lead.notes`. If it does not exist, suggest `/kit:init` once, then
  continue with the obvious commands.
- Note which project skills exist: workers should load them for matching tasks.
- If the goal is "next" or empty: take the next open item from the backlog that `lead.read` or
  `lead.backlog` points to. If there is none, say so and stop.

## 1. Define done before doing

Write the done-criterion as something checkable: a command that exits 0, a gate, a file that
validates, an observable behaviour. If the goal arrives as a `kit:shape` brief, take its DONE WHEN
and SCOPE as given. If the goal mixes several ideas or you cannot make it checkable, run the
`kit:shape` skill first instead of guessing. For a large or risky goal, have `kit:plan-reviewer` review the plan
and fold in its MUST FIX items.

## 2. Split and choose the mechanism

Create a task list (TaskCreate) with one task per independently checkable unit. Then, per task:

| Situation | Use |
|---|---|
| Small, touches few files | `kit:implementer` via the Agent tool |
| Several tasks edit files in parallel | `kit:implementer` with `isolation: "worktree"`, one per task, launched in the same message |
| Many similar items, or results that need cross-checking | the `kit:ship` workflow (tasks list in `args`) or `kit:review`; ask the user before the first workflow run if they have not opted in |
| Pure research / reading | an Explore or general-purpose agent; keep only its conclusion |
| Long, independent, can run unattended | tell the user it fits a background session (`claude agents`) and give the exact prompt |
| Must repeat on a schedule | propose `/loop <interval> /kit:lead next` or a routine |
| One conversation must keep going until a condition holds | propose `/goal <condition>`; the kit Stop hook still runs the real check |
| A bug: an error, a failing test, a broken page or job, "it stopped working" | load `kit:investigate` yourself for the diagnosis (evidence, hypotheses, root cause); hand the fix to `kit:implementer` with the root cause, the regression test and its done-criterion. If the evidence sits where only the user can reach it (a dashboard, their device), ask for it before planning any fix |
| The task writes or changes LLM code (an API call, prompt, tool, orchestration, model, answer quality), even a small fix | the matching kit skill, loaded by you or named in the worker brief: `kit:llm-build` (design, build and review; its checklist and "Done when" go in the brief), `kit:llm-evals` (measure; first if no trusted suite), `kit:prompt-optimize` (iterate against the suite), `kit:model-select` (compare models). The done-criterion is an eval result (hard checks at least), not "the prompt reads better" |

Give each worker a self-contained brief: goal, scope (files/area), done-criterion, the project
rule or skill that applies, and what to return. Workers do not see this conversation.

## 3. Verify every result independently

- Never accept an implementer's own "done". Send each result to `kit:verifier` with the goal,
  done-criterion and location (branch/worktree). Run verifiers in parallel when results are
  independent.
- FAIL: send the verifier's PROBLEMS back to an implementer (same worktree/branch) for a fix,
  then verify again. After 3 failed rounds on the same task, stop that task and escalate to the
  user with the evidence; do not keep looping.
- CANNOT_VERIFY: find another way to check, or report it as unverified. Never round it up to done.

## 4. Integrate

- Merge worktree branches one at a time into the working branch; resolve conflicts yourself
  and re-run `verify` after the last merge.
- When everything passes: offer `/kit:go` (simplify, verify, commit, PR). Commit, push, PR,
  deploy, migrations and anything outward-facing need the user's go-ahead unless they already
  gave it for this run.

## Keep the context lean

Your context is for decisions, not file dumps. When the kit's context guard asks for it, and
at every phase boundary, overwrite `.claude/handoff.md` (or the path in `kit.json`
`context.handoff`): goal and done-criterion, decisions and user preferences, in-flight agents,
branches and PRs, next step, session rules. Compaction then loses nothing, and the note comes back
on its own afterwards.

## 5. Report

```
DONE (verified): <task - evidence line>
NOT DONE: <task - why - what the user must decide>
CHANGES: <branches/commits/files>
NEXT: <the next item or the question that blocks it>
```

If the user corrected you or a worker repeated a mistake, finish with `/kit:learn` so the fix
lands in CLAUDE.md or a skill.

## Loop mode (`/loop ... /kit:lead next`)

Do one item per iteration: pick, define done, delegate, verify, report in 5 lines. Stop the
loop (tell the user) when the backlog is empty, an item is blocked on a human decision, or two
iterations in a row failed verification.

## Stop and ask instead of continuing when

- a project rule says to stop (contradicting sources, missing data that would have to be guessed,
  blocked access, personal data);
- the next step is destructive, irreversible or outward-facing and not yet approved;
- the done-criterion turns out to be wrong or unreachable.
