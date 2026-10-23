---
name: shape
description: Turns a brain-dump prompt (several ideas at once, unclear goal, no done-criterion) into a precise brief through short multiple-choice rounds, then launches it with the right skills and mechanism. Use when the kit prompt hook asks for it, when the user runs /kit:shape, or when a request mixes several new ideas and starting work would mean guessing what the user wants.
argument-hint: "[the idea; empty = the user's last message]"
---

# /kit:shape: from a brain-dump to a launchable brief

Input: $ARGUMENTS (if empty, the user's last message).

The user writes ideas as they come. Your job is to make the goal precise enough for a lead,
a loop or `/goal` to run without guessing. Ask as little as possible.
(Method adapted from mattpocock/skills `grilling`, MIT: rounds over a decision tree, a
recommended answer for every question, and facts are looked up, never asked.)

## 1. Split

Break the input into separate ideas (goal-sized units). Restate each in one line, in the
user's language. Mark what each depends on.

## 2. Look up facts before asking anything

Anything the environment can answer is your job, not the user's. Examples: does this exist
already, which files, what does the backlog say, what does CLAUDE.md or the decision log
require, which project skills fit. For more than a quick lookup, dispatch an Explore agent and
keep going: only questions that depend on its answer wait for it. Read `.claude/kit.json`
(`lead.read`, `lead.backlog`) if it exists.

## 3. Ask in rounds, multiple choice

Use the AskUserQuestion tool. Each call takes 1-4 questions, each with 2-4 options, and a
header of at most 12 characters. Put your recommended option first with "(Recommended)" in its
label; "Other" is added automatically.

- **Round 1 (always, if there is more than one idea):** which ideas now, and in what order;
  park the rest in the backlog. Use multiSelect where it fits.
- **Later rounds:** only decisions whose prerequisites are already settled, the ones that change
  what gets built. Typical ones:
  - scope (minimal or full);
  - the done-criterion (which check proves it);
  - constraints (deadline, budget, must-not-touch areas);
  - mechanism (one lead run, parallel tasks, a recurring loop).
- **Never ask:**
  - a fact you can look up;
  - a choice with a conventional default (use the default and state it in the brief);
  - style questions that don't change the outcome.
- **Recommend on quality, not on build time.** Pick the recommended option for correctness,
  maintainability and running cost; agents build in minutes what a human estimate puts in
  weeks, so "quicker to build" is not a reason. Never put days or weeks on an option.
- **Show options that differ visually.** When the options are layouts, screens, flows or
  architectures, a wall of text hides the difference: before asking, write one small
  self-contained HTML page that shows them side by side (in the project's design system if it
  has one) and open it, or use a published artifact where the session offers one. Then ask the
  question with the options named as on the page.
- **At most 3 rounds.** If decisions are still open after that, choose the recommended option,
  list it under ASSUMPTIONS in the brief, and continue.
- If the user answers "accept the recommendations" (or picks every recommended option), stop
  asking.

## 4. Write the brief

Show it in the conversation (and, if the user wants it saved, append it to the project's backlog
file from `kit.json` `lead.backlog`, else `docs/briefs/<date>-<slug>.md`):

```
BRIEF: <one-line goal>
WHY: <the user's reason, one line>
DONE WHEN: <checkable criterion: command(s) that exit 0, observable behaviour>
SCOPE: <in> | OUT: <explicitly not now>
CONSTRAINTS: <project rules that apply (CLAUDE.md/AGENTS.md/decisions), limits the user gave>
SKILLS/AGENTS: <project skills the workers must load; kit agents to use>
MECHANISM: <kit:lead | kit:ship with N tasks | /goal <condition> | /loop <interval> /kit:lead next>
ASSUMPTIONS: <decisions taken by default, so the user can veto them>
PARKED: <ideas moved to the backlog>
```

## 5. Launch

One last AskUserQuestion, header "Launch":

1. **Start now (Recommended).** Invoke the `kit:lead` skill with the brief as its goal. For
   several independent tasks the lead uses `kit:ship`.
2. **Start as /goal.** `/goal` is a command only the user can type, so print the exact line to
   paste: `/goal <DONE WHEN condition>`, followed by the brief.
3. **Save only.** Write the brief to the backlog file and stop.
4. **Edit.** Ask what to change, update the brief, and ask again.

For a recurring mechanism, print the exact `/loop ...` line, or with the user's OK invoke the
`loop` skill if it is available.

## Rules

- In the user's language. Short. No lecture about the method.
- Do not start implementation before the launch answer.
- Without AskUserQuestion (a non-interactive run, e.g. `claude -p` or a routine), nobody can
  answer: do not shape. Proceed with the most reasonable reading and list your assumptions.
- If the input is in fact clear (one goal, obvious done-criterion), say so in one line and go
  straight to step 5 with the brief.
