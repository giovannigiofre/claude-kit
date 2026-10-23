---
name: learn
description: Turns a correction or a repeated mistake into a durable rule in CLAUDE.md, AGENTS.md, a project skill or .claude/kit.json, so the next session does not repeat it ("compounding engineering"). Use after the user corrects Claude, after a verifier caught the same defect twice, when the user says "remember this" about how to work in this repo, or with "sweep" to mine recent session transcripts for repeated corrections.
argument-hint: "[the lesson | sweep [N sessions] | empty to extract it from this session]"
---

# /learn: make the correction stick, keep the rules lean

Lesson: $ARGUMENTS (if empty, find the corrections and repeated failures in this session; if
`sweep`, see "Sweep" below).

Treat the instruction files like trained weights: every line is loaded into every session and
costs tokens whether the task needs it or not, and a rule written from one odd moment can make
the agent worse. So rules come from evidence, few at a time, and the user approves each one.
(Method adapted from Kun Chen, "Your AGENTS.md is a Neural Net", 2026. Nothing copied.)

1. **State each lesson** in one imperative sentence plus the reason, e.g. "Run `ins publish`
   after every `extract load` - loads drop publication."
2. **Evidence.** Quote the moment it comes from (the user's correction or the failed check, one
   short line). An explicit "remember this" or a correction from the user is enough on its own.
   A pattern you noticed yourself needs at least two occurrences (two sessions, or the verifier
   catching it twice) before it becomes a rule; with one, write it in your reply as a candidate
   and stop.
3. **Pick the narrowest durable home:**
   - something a machine can check -> a `check`/`onEdit`/`protect` entry in `.claude/kit.json`
     (a hook beats a sentence);
   - needed only for one kind of task (testing, releases, a data pipeline) -> that task's
     project skill in `.claude/skills/`, creating it if needed (only its one-line description is
     always loaded; the body loads when the task comes up);
   - a step inside a recurring task -> that project skill's checklist;
   - a rule every session in this repo needs -> the repo's CLAUDE.md (or AGENTS.md if
     CLAUDE.md imports it);
   - a personal preference across all projects -> the user's `~/.claude/CLAUDE.md` or auto-memory,
     not the repo. Keep that file short: it is loaded into every session of every project.
4. **Read the target first.** Update an existing line rather than adding a near-duplicate; keep
   the file's tone and length. If a rule became wrong, delete it. If the repo has its own rule
   for where lessons go (a lessons-learned doc, a decision log), follow it. If the repo has both
   CLAUDE.md and AGENTS.md with diverging content, suggest one import or symlink the other.
5. **At most 4 changes per run** (one AskUserQuestion multiSelect holds 4 options). Show each
   as a diff with its evidence line and ask the user which to accept. Write only the accepted ones.
   Do not commit unless asked.
6. **Move conditional sections out.** If CLAUDE.md holds a long section that only some tasks
   need (an e2e testing guide, a release checklist), propose moving it into a project skill as
   one of the 4 changes.

## Sweep

`/kit:learn sweep [N]` reviews the last N sessions of this project (default 10), not just this
one. Claude Code keeps transcripts as JSONL under `~/.claude/projects/<folder>/`, where the
folder name is the project's absolute path with every non-alphanumeric character replaced by
`-`; list `~/.claude/projects` to find it. Read them with an Explore agent (they are large;
ask it for user turns that correct, reject or redo Claude's work, with a short quote and the
session date, and for checks that failed the same way more than once). Then apply steps 2-6: only patterns seen in at least
two sessions, at most 4 proposed changes, each approved by the user. If the transcript folder
is not there, say so and fall back to this session.
