---
name: shape
description: Turns a brain-dump (several ideas at once, an unclear goal, no way to tell when it is done) into a short brief through a few multiple-choice questions, then launches it. Use when a request mixes several new ideas or would mean guessing what the user wants, or when the user runs /kit:shape or says "help me think this through".
argument-hint: "[the idea; empty = the user's last message]"
---

# Shape: from a brain-dump to a brief

Input: $ARGUMENTS (empty: the user's last message).

Make the goal precise enough for the coordinator, a loop or `/goal` to run without guessing,
asking as little as possible. (Method adapted from mattpocock/skills `grilling`, MIT: rounds over
a decision tree, a recommended answer per question, facts looked up rather than asked.)

1. **Split** the input into separate ideas, one line each in the user's language, with what each
   depends on.
2. **Look facts up before asking**: what exists already, which files, the backlog, CLAUDE.md and
   decision logs, `.claude/kit.json` (`lead.read`, `lead.backlog`). For more than a quick lookup,
   start an Explore agent and keep going.
3. **Ask in at most 3 rounds** with AskUserQuestion: 1-4 questions per round, 2-4 options each,
   your recommended option first with "(Recommended)". Round 1, when there are several ideas:
   which now and in what order, the rest parked. Later rounds: only decisions that change what
   gets built (scope, the check that proves it done, constraints). Don't ask what you can look
   up, what has a conventional default, or style that doesn't change the outcome. Recommend on
   correctness, maintainability and running cost, not on build time. When options differ
   visually (layouts, flows, architectures), show them side by side in a small HTML page first.
   Still open after 3 rounds: take the recommendation and list it under ASSUMPTIONS. "Accept the
   recommendations" ends the questions.
4. **Write the brief** in the conversation (saved to the backlog file, or
   `docs/briefs/<date>-<slug>.md`, if the user wants):

   ```
   BRIEF: <one-line goal>
   WHY: <the user's reason>
   DONE WHEN: <a check: commands that exit 0, observable behaviour>
   SCOPE: <in> | OUT: <not now>
   CONSTRAINTS: <project rules that apply, limits the user gave>
   ASSUMPTIONS: <defaults taken, so the user can veto them>
   PARKED: <ideas moved to the backlog>
   ```
5. **Fresh eyes**, when the brief has several pieces, touches architecture or still reads two
   ways: one read-only subagent gets the brief alone and reports what it would have to guess,
   what DONE WHEN does not need, what exists to reuse and what it names that does not exist
   (`${CLAUDE_SKILL_DIR}/../lead/fresh-eyes.md`); fix the brief before launching.
6. **Launch**, one last question: start now (recommended: hand the brief to `kit:lead`, which
   opens a thread per independent piece); start as `/goal` (print the line to paste, since only
   the user can type it); save only; or edit.

Without AskUserQuestion (a headless run), don't shape: take the most reasonable reading and list
the assumptions. If the input is already clear, say so in one line and go to step 6.
