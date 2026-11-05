# /kit:learn promote: a lesson from several repos becomes a kit change

A kit candidate is a machine lesson (held by 2+ real repos) the distiller found in 3 or more repos,
about the kit itself, or recorded as a kit defect, that the structural check and the model's
genericity judge passed. Promoting it means a PR on the kit's own repo, which the user reviews and
merges. This runs only here, in a session the user started the command in; no hook does it. `L` is
the same `lessons.py` as in SKILL.md.

1. **Brief.** `$L promote <id> .` prints the lesson, why it qualifies, the kit checkout and the
   branch name, or why it cannot be promoted (stop there and say so). Without an id it lists the
   candidates; ask which one.
2. **Branch.** In the kit checkout the brief names, never switch the user's own branch:
   `git -C <kit> fetch origin` then `git -C <kit> worktree add <scratchpad>/kit-<branch> -b <branch> origin/main`.
   With no checkout registered, clone the kit's origin into the scratchpad and branch there.
3. **Change.** Do it yourself or hand it to a kit:implementer thread with the brief, scoped to:
   - the smallest change that holds in any repo, a hook, script or test before a sentence;
   - a regression check that fails without the change and passes with it, run both ways: a
     stdlib test beside the hook, or an eval case under `plugins/kit/evals/` for skill or agent
     text;
   - `tests/test_budget.py` passes; a new always-loaded line replaces one or fits the budget;
   - the `version` in `plugins/kit/.claude-plugin/plugin.json` bumped (a patch for a fix);
   - the repo's own checks, as its README lists them.
4. **Scrub.** `git -C <worktree> diff origin/main... | $L scrub -` and the same for the commit
   message and the PR body must print `scrub: clean`. It flags repo names, orgs, checkout paths
   and env var names from this machine's ledgers, and anything secret-shaped. Rewrite until
   clean; never paste a ledger's evidence refs into the kit.
5. **PR.** Commit as the user (their git identity, no AI co-author or footer), push the branch,
   and `gh pr create` with **Intent** (the lesson, in generic words), **Evidence** (the
   regression check failing before and passing after; "seen in N repos, M times", no names) and
   **Risk**. Never merge it and never push to the default branch.
6. **Record.** `$L promoted <id> <new version> <PR url> .`, so the lesson retires itself once the
   user merges and updates the kit. Give the user the PR link in one line.
