---
name: learn
description: Turns a correction or a repeated mistake from this session into a durable rule in CLAUDE.md, AGENTS.md, a project skill or .claude/kit.json, so the next session does not repeat it ("compounding engineering"). Use after the user corrects Claude, after a verifier caught the same defect twice, or when the user says "remember this" about how to work in this repo.
argument-hint: "[the lesson, or empty to extract it from this session]"
---

# /learn: make the correction stick

Lesson: $ARGUMENTS (if empty, find the corrections and repeated failures in this session).

1. State each lesson in one imperative sentence plus the reason, e.g. "Run `ins publish` after
   every `extract load` - loads drop publication."
2. Pick the narrowest durable home:
   - a rule every session in this repo needs -> the repo's CLAUDE.md (or AGENTS.md if CLAUDE.md
     imports it);
   - a step inside a recurring task -> that project skill's checklist;
   - something a machine can check -> a `check`/`onEdit`/`protect` entry in `.claude/kit.json`
     (a hook beats a sentence);
   - a personal preference across all projects -> the user's auto-memory, not the repo.
3. Read the target first. Update an existing line rather than adding a near-duplicate; keep the
   file's tone and length. If the repo has its own rule for where lessons go (a lessons-learned
   doc, a decision log), follow it.
4. Show the user the exact lines added or changed. Do not commit unless asked.
