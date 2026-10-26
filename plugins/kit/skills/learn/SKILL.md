---
name: learn
description: Tidies the kit's lesson ledger for this repo (merge, retire, propose hardening), shows or undoes what it learned, and turns a correction or a repeated mistake into a durable fix - a check, a hook entry, a project skill or a CLAUDE.md line. Use after the user corrects Claude, when the verifier caught the same defect twice, or with "undo", "news", "list" or "sweep".
disable-model-invocation: true
argument-hint: "[empty = distill + this session's corrections | undo <id> | news | list | stats | sweep [N] | the lesson to make stick]"
---

# /learn: the kit's lessons, kept small and true

Argument: $ARGUMENTS

The kit learns on its own: hooks capture gate failures, guard denials and verifier FAILs into a
ledger outside the repo (`~/.claude/kit-lessons/`), and threads get the repo's lessons when they
start. This skill is the hand on that loop. Below, `L` is
`python3 ${CLAUDE_SKILL_DIR}/../../hooks/scripts/lessons.py` (if `${CLAUDE_SKILL_DIR}` is not
expanded, the script is in the kit plugin's `hooks/scripts/`).

## Commands

- **empty**: run `$L distill .` and relay its lines as they are (each says what changed and how
  to undo it). It merges duplicates, retires stale lessons and writes hardening proposals; with
  a model allowed it also rewords lessons (one haiku call, at most $0.05, once a day per repo).
  `--no-model` skips the model. Then take this session's corrections and repeated failures, if
  any, through the section below.
- **undo <id>**: `$L undo <id> .`, then say what came back.
- **news**, **list**, **stats**: `$L news .`, `$L list --all .`, `$L stats .`; show the output,
  shortened to what the user asked about.

## A hardening proposal or a correction to make stick

When the distiller proposed hardening a lesson (it came back after threads were told), or the
argument is a lesson in words, make it mechanical. Instruction files behave like trained
weights: every always-loaded line costs tokens in every session and can make results worse, so
changes come from evidence, few at a time, approved by the user, and removing a line counts as
much as adding one. (Method adapted from Kun Chen, "Your AGENTS.md is a Neural Net", 2026.
Nothing copied.)

1. **State the lesson** in one sentence plus the reason, with its evidence: the ledger's
   `evidence` refs, the user's correction, or the failed check. A pattern you noticed yourself
   needs two occurrences; with one, record it as a candidate (`$L add pitfall <key> "<text>" .`).
2. **Pick the most mechanical home that works**, in this order:
   - a test, lint rule or script in the repo, whose error message says how to fix it;
   - a `check`, `onEdit` or `protect` entry in `.claude/kit.json`;
   - a project skill in `.claude/skills/` when it matters only for one kind of task;
   - a line in the repo's CLAUDE.md (or AGENTS.md) when every session needs it;
   - the user's `~/.claude/CLAUDE.md` for a personal preference across projects.
3. **Read the target first**, update rather than add, keep its tone. Look for lines no session
   needed and near-duplicates and propose removing them; keep always-loaded text (CLAUDE.md plus
   every skill description) under about 5k tokens.
4. **At most 4 changes per run.** Show each as a diff with its evidence and ask with one
   AskUserQuestion multi-select which to apply. Write only those; don't commit unless asked.
5. Once a mechanism covers a lesson, retire it: `$L retire <id> .`.

## Sweep

`sweep [N]` reviews the last N sessions of this project (default 10). Transcripts are JSONL under
`~/.claude/projects/<folder>/`, the folder being the project's absolute path with every
non-alphanumeric character replaced by `-`. Have an Explore agent read them for user turns that
correct, reject or redo Claude's work (a short quote and the date each), checks that failed the
same way more than once, and CLAUDE.md rules that never came up. Then apply the steps above.
