---
name: techdebt
description: End-of-session sweep for technical debt in the code touched recently - duplicated logic, dead code, TODOs, missing tests, stale docs - reported as a short ranked list and optionally fixed. Use when the user runs /techdebt or asks to clean up after a session.
disable-model-invocation: true
argument-hint: "[scope: default = files changed on this branch / in the last day; 'fix' to apply the safe ones]"
---

# /techdebt

Scope: $ARGUMENTS (default: files changed on the current branch vs the default branch, plus
uncommitted changes; if on the default branch, commits from the last 24 hours).

1. List the files in scope (`git diff --name-only`, `git log --since`).
2. Delegate the sweep to an Explore agent (or one per area if the scope is large) asking for:
   duplicated logic that an existing helper already covers, dead code, TODO/FIXME added in scope,
   behaviour changed without a test, docs/README/CLAUDE.md that the change made stale.
3. Rank by cost of leaving it: correctness risk > duplication > dead code > style.
4. Report a table: item, file:line, why it matters, effort (S/M/L).
5. With `fix`: apply only S items that do not change behaviour, run `.claude/kit.json` `verify`,
   and list what was changed. Everything else stays a list for the user.
