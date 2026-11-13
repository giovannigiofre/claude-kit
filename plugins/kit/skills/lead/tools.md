# The coordinator's other commands

`I` is the items script (see SKILL.md, "Items on disk"). Each of these only reads, unless it says otherwise.

- **`I status`** (`--json` for a tool): every open item with its status, last event and how long ago, the
  thread, the branch or PR, what the thread cost in tokens, and the questions waiting. Built from the item
  folders, so it is right even when the board is behind. Use it to answer "where are we" and before you
  rewrite the board.
- **`I conflicts [<id> ...]`**: which open branches would not merge cleanly with each other or with the
  default branch, and in which files. Run it before an item goes to `review`, and before starting a thread
  whose files overlap one at work. Exit 1 means a conflict: rebase the later branch first, in its thread.
  Exit 2 means it could not tell (an old git, a missing branch): say so, do not guess.
- **`DEPENDS: <id>[, <id>]`** in a brief: `I list` and `I status` show the item as `blocked-by <id>` until that
  item is done. Start it only then; an id that does not exist blocks too, so fix the brief.
- **`I done <id>`** checks that the item's PR is merged before it archives the item, when `gh` is there. An
  open or closed-unmerged PR is refused (`--force` when you know better); without `gh` it says the merge
  state is unknown and goes on.
- **The `cost` lines in an item's LOG.md** (tokens in and out, cache read and written, tool calls, minutes)
  are written when a thread finishes. When a kind of brief keeps costing far more than its neighbours, say
  so to the user: it is usually a brief that was too wide.
- **`python3 <kit>/hooks/scripts/worktrees.py`**: every linked worktree as merged, dirty, conflict, ready,
  stale or active, with a plan (remove, salvage, keep). It removes nothing: run the commands it prints for
  the `remove` rows after a merge, and push or bundle a `salvage` row before anything else.
