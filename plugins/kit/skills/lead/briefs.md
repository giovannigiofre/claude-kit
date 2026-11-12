# Brief checklist

Lines a brief gets when the work calls for them, on top of the goal, DONE WHEN, scope, ship mode
and EXPECT. Each one is a verifier finding that cost a round before. Keep the project's specifics
(its helper files, its tracker, its pitfalls) in its gitignored `CLAUDE.local.md` and point the
brief at them; this list stays generic.

- **Every brief: one branch in one worktree.** A thread writes only inside its own worktree, so
  a brief never asks it to create or work a second worktree or branch (a docs fix on another
  branch, a follow-up PR): a second branch is a second thread.
- **A new database migration:** an upgrade test that starts from the previous schema, with rows
  in it, and runs the migration; the PR says how to roll back or roll forward if it fails in
  production.
- **A milestone or progress item the project tracks** (a progress file, a checklist, a roadmap
  entry): the commit that changes its state updates it too.
- **Browser or end-to-end tests:** use the project's own test helpers (sign-in, fixtures, waits)
  and read the known e2e pitfalls in the project's local facts file first; name both in the brief.
  None written down yet: the thread puts what it learns under OPEN, for `CLAUDE.local.md`.
- **UI text that shows what people typed** (a name, a title, an address): long unbroken words
  wrap (`overflow-wrap: anywhere`, or the design system's way) and the evidence shows one at
  phone width.

A defect a verifier finds twice that none of these covers: add a line for it to the project's
`CLAUDE.local.md`, where every later brief picks it up.
