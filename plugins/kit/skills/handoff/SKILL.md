---
name: handoff
description: Turns the conclusion of a discussion into a brief and hands it to where the work gets done - this session's coordinator, another open session, a new background session, or just the disk as an item or a proposal card. Use with /kit:handoff after reasoning about a change.
disable-model-invocation: true
argument-hint: "[lead | session <name> | bg | save | card] [name of the item]"
---

# /kit:handoff: from a discussion to a brief someone can run

Arguments: $ARGUMENTS (a destination, optionally a name; empty: ask).

A discussion ends with an understanding, not with code. This turns it into the
brief `kit:shape` would have written, saves it as a coordinator item on disk, and sends it where
you choose. Below, `I` and `P` are shell functions (zsh does not split a `$I` variable into words):
`I(){ python3 ${CLAUDE_SKILL_DIR}/../../hooks/scripts/items.py "$@"; }` and
`P(){ python3 ${CLAUDE_SKILL_DIR}/../../hooks/scripts/proposals.py "$@"; }` (if `${CLAUDE_SKILL_DIR}` is not
expanded, the scripts are in the kit plugin's `hooks/scripts/`).

1. **Write the brief** from this conversation, in the user's language:

   ```
   BRIEF: <one-line goal>
   WHY: <the reason, from the discussion>
   DONE WHEN: <a check: commands that exit 0, observable behaviour>
   SCOPE: <in> | OUT: <not now>
   PLACES: <files, modules, tables the discussion identified, with what each must change>
   CONSTRAINTS: <project rules that apply, limits the user gave>
   DECISIONS: <choices made in the discussion, one line each, so the user can veto them>
   ASSUMPTIONS: <what was taken for granted>
   ```

   Ask at most one AskUserQuestion round, only for what the discussion left open and that
   changes the work. A conclusion that is an idea rather than a piece of work (no checkable
   done) goes to a proposal card instead: destination `card`.

2. **Save it**: `I new "<name>" --brief - --from handoff` with the brief on stdin. It prints
   the item id and the folder (`.kit/lead/items/<id>/BRIEF.md`, headed `ITEM: <id>`, which
   is how threads and hooks tie their reports to it). For `card`: a JSON object
   `{origin, summary, rationale, evidence, confidence, class}` to `P add -` (class A mechanical
   and reversible, B needs judgment, C a human decision) and stop here.

3. **Send it** to the destination (ask with AskUserQuestion when none was given):
   - **lead**: the item is queued; this session's coordinator starts it now (invoke `kit:lead`
     with the item id as argument when the kit:lead skill is not loaded yet).
   - **session <name>**: `ListAgents`, pick the named session (ask which when there are
     several), then `SendMessage` with the BRIEF.md text and one line: "a brief from a
     discussion in <repo>; after the user confirms it, run it as kit:lead item <id>
     (BRIEF.md at <path>)". It arrives there as a message from a peer, so that session will
     confirm with the user before starting.
   - **bg**: a new background session in this checkout:
     `claude --bg --name <id> "Read <path>/BRIEF.md and run it as item <id> with the kit:lead skill (ship mode from kit.json); report when the PR is ready."`
     Give the user the printed session id and `claude attach <id>` (or `claude agents`).
   - **save**: nothing else; the item waits in `.kit/lead/items/`.

4. **Reply in two lines**: the item id and path, and where it went (or that it waits).
