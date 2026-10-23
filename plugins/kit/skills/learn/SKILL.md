---
name: learn
description: Turns a correction or a repeated mistake into a durable fix - a check, a hook entry, a project skill or a CLAUDE.md line - and prunes instructions that no longer earn their place. Use after the user corrects Claude, when the verifier caught the same defect twice, or weekly with "sweep" over recent sessions.
disable-model-invocation: true
argument-hint: "[the lesson | sweep [N sessions] | empty = this session's corrections]"
---

# /learn: make corrections stick, keep the instructions small

Lesson: $ARGUMENTS (empty: the corrections and repeated failures in this session; `sweep`: see
below).

Instruction files behave like trained weights: every always-loaded line costs tokens in every
session, and rules the model follows can also make it worse (generic guidelines measurably lower
pass rates). So changes come from evidence, few at a time, approved by the user, and removing a
line counts as much as adding one. (Method adapted from Kun Chen, "Your AGENTS.md is a Neural
Net", 2026. Nothing copied.)

1. **State each lesson** in one sentence plus the reason, e.g. "Run `ins publish` after every
   `extract load`: loads drop publication."
2. **Evidence:** quote the moment it comes from (the user's correction or the failed check). A
   user correction or "remember this" is enough on its own; a pattern you noticed yourself needs
   two occurrences before it becomes a change. With one, mention it as a candidate and stop.
3. **Pick the most mechanical home that works**, in this order:
   - a test, lint rule or script in the repo, whose error message says how to fix it;
   - a `check`, `onEdit` or `protect` entry in `.claude/kit.json`;
   - a project skill in `.claude/skills/` when it matters only for one kind of task (only its
     description is always loaded);
   - a line in the repo's CLAUDE.md (or AGENTS.md) when every session needs it;
   - the user's `~/.claude/CLAUDE.md` for a personal preference across projects.
4. **Prune.** For each touched file, look for lines the model would follow anyway, lines no
   session needed, and near-duplicates; propose deleting them ("would removing this cause a
   mistake?"). Keep the always-loaded text (CLAUDE.md plus every skill description, as `/context`
   shows) under about 5k tokens; move long conditional sections into a project skill.
5. **Read the target first**, update rather than add, keep its tone. If the repo has its own place
   for lessons (a decision log), use it.
6. **At most 4 changes per run**, additions and deletions together. Show each as a diff with its
   evidence and ask with one AskUserQuestion multi-select which to apply. Write only those; don't
   commit unless asked.

## Sweep

`/kit:learn sweep [N]` reviews the last N sessions of this project (default 10). Transcripts are
JSONL under `~/.claude/projects/<folder>/`, the folder being the project's absolute path with every
non-alphanumeric character replaced by `-`. Have an Explore agent read them for user turns that
correct, reject or redo Claude's work (a short quote and the date each), checks that failed the
same way more than once, and CLAUDE.md rules that never came up. Then apply steps 2-6. No
transcripts: say so and fall back to this session.
