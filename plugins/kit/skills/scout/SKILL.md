---
name: scout
description: Use when the user asks to look for improvements or what to do next ("what should we work on", "find things to fix"). Scans the project with read-only explorers and writes deduplicated proposal cards (class A mechanical, B needs judgment, C human-only) into .kit/lead/proposals/; "take <id>" turns a card into a coordinator item.
argument-hint: "[area or lens | take <id> | list | retire]"
---

# /kit:scout: find work, write cards, never change anything

Arguments: $ARGUMENTS. `P` is a shell function (zsh does not split a `$P` variable into words):
`P(){ python3 ${CLAUDE_SKILL_DIR}/../../hooks/scripts/proposals.py "$@"; }` (if `${CLAUDE_SKILL_DIR}` is not expanded, the script is in the kit plugin's `hooks/scripts/`).
(Method adapted from albiol2004/trio-agent-loop `trio-bridge`, MIT: scouts return lists, the
orchestrator never reads the scanned files, cards are fingerprinted and immutable.)

- **`list`**: `P list` (or `--class A`); show it and stop.
- **`take <id>`**: `P take <id>` makes a queued item from the card; say the item id and that
  the coordinator picks it up at the next message (or `kit:lead <id>`).
- **`retire`**: `P retire` archives cards older than 30 days or whose origin is gone.
- **Otherwise, a scan** of the area or lens given (empty: the whole project):

1. **Dispatch** one to three Explore agents in the background with `effort: "low"`, in one
   message, each with a disjoint lens: documentation (stale or contradicting the code),
   configuration and CI (drift, missing or failing checks), code hygiene (TODO and FIXME clusters, recent changes with no
   test, `git log -20`). Each brief says: read only, never run a state-changing command; return
   a JSON list of objects `{origin, summary, rationale, evidence, confidence, class}` and
   nothing else: `origin` the file or path, `summary` one sentence naming the concrete problem
   (deterministic wording: it feeds the fingerprint), `rationale` one sentence tied to the
   evidence, `evidence` a list of `file:line` references or the exact failing command,
   `confidence` low, medium or high, `class` A (mechanical, reversible: a thread can take it),
   B (likely right, needs judgment) or C (a human decision: product direction, large blast
   radius, irreversible). No file contents, no prose.
2. **Collect** the lists as they arrive; never read the scanned files yourself. A scout that
   returns prose or file dumps is re-dispatched once with the contract restated.
3. **Write the cards**: the concatenated list to `P add -`. The script drops duplicates
   (fingerprint, a card already taken, a summary that is already an item) and anything that
   looks like a secret.
4. **Report** in at most five lines: what `P add` printed (added per class, skipped, total),
   the folder, and the one or two class A cards worth taking first (`/kit:scout take <id>`).
   The coordinator's `next` takes class A cards on its own and asks about B; C is never
   started by an agent.
