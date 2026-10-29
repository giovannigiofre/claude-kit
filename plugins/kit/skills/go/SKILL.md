---
name: go
description: Finishes work end to end - intent, sync with the base, test it the way a user would, review, simplify, risk rating, PR, then keeps CI green. Use when the user appends "/go" or says the work is ready to ship; "/kit:go babysit [PR]" only watches open PRs.
disable-model-invocation: true
argument-hint: "[optional: what was built, PR title hint, 'no-pr', 'no-babysit', 'babysit [PR]']"
---

# /go: from first-pass code to a PR the user can judge without the diff

Context: $ARGUMENTS

The PR description should tell the user what was intended, prove it works, list what was fixed
on the way and rate the risk, so they can decide how closely to read the diff. (Boris Cherny's
`/go` - test end to end, `/simplify`, PR - plus intent, evidence and risk from
kunchenguid/no-mistakes, MIT. Nothing copied.)

`babysit [PR]`: skip to step 7 (no number: each open PR of yours, `gh pr list --author @me`).

1. **Finish the work** the request was about, if it isn't done.
2. **Intent**, 2-5 lines: what the user asked for and why, constraints, what is out of scope.
   From this conversation, else the branch's commits and linked issue; ask if still unclear. It
   is the yardstick for the review, not the diff.
3. **Sync with the base**: fetch, then rebase a local-only branch or merge into a shared one.
   Resolve conflicts now, so what gets checked is what will merge.
4. **Test it the way a user meets it.** Run the gate through
   `python3 ${CLAUDE_SKILL_DIR}/../../hooks/scripts/gate.py verify` (it runs kit.json `verify`
   and records the tree it passed on; without that record the guard refuses the PR), else the
   project's tests, lint, build. Then exercise the change: run the CLI, call the API, load the
   page (a project `verify` skill, or an older `e2e` one, says how). Save proof under
   `.claude/evidence/<branch>/` and write one line per scenario: `<scenario> | pass/fail |
   <evidence file>`. A test that mocks the changed path, or reading the code, is not evidence.
   Fix failures and repeat.
5. **Review, then simplify.** Run the `code-review` skill on the branch with the intent from step
   2; skip findings already declined in `.claude/review-decisions.md`. Fix the mechanical ones
   that don't change what was asked. Collect those that touch the intent or a product decision
   and ask about them once, with AskUserQuestion; a declined one goes into
   `.claude/review-decisions.md` (date, finding, reason). Then run the `simplify` skill, update
   docs that describe the changed behaviour, and re-run `verify`.
6. **Risk and PR.** Rate the risk low, medium or high in one or two lines: blast radius (shared
   modules, auth, money, migrations, data deletion, public API), how much the evidence covers,
   how hard it is to roll back. Branch first if on the default branch. Stage only the files this
   work changed (no secrets, `.env`, large data or `.claude/evidence/`), commit as the repo's
   configured git user with a message that says why (no AI co-author lines or footers), run the
   gate again if anything changed since (the record must match the committed tree), push and
   `gh pr create` (unless `no-pr`) with sections **Intent**, **Changes**,
   **Evidence**, **Fixed along the way**, **Risk**, **Open**; attach screenshots and logs with
   `--attach <file>` (gh 2.99+) rather than naming paths on this machine. Follow the repo's
   commit and PR conventions.
7. **Keep CI green** (unless `no-babysit`). With the Claude GitHub App on the repo,
   `/autofix-pr` watches the PR from the cloud. Otherwise watch `gh pr checks <PR> --watch`; on a
   failure read the log (`gh run view <id> --log-failed`), fix the root cause, re-run step 4 for
   what you touched, push; at most 3 rounds, then report. A merge conflict: sync as in step 3.
   Review comments that ask for a product decision go to the user. If CI takes longer than
   about 10 minutes, hand over to Claude Code's own loop: a bare `/loop` tends this branch's PR
   (comments, failed CI, conflicts) at its own pace. (`/kit:go babysit` works when the user types
   it; a scheduled prompt cannot invoke a user-only skill.)
8. **Merge per the project's policy** (`.claude/kit.json` `lead.merge`): `agent` merges once CI
   is green, nothing from the review is open and the risk is not high (`gh pr merge --squash
   --delete-branch`, or the method the repo allows); `user`, or a high risk, leaves the PR for
   the user. Not set: ask "In this project, do I merge PRs once they're green, or do you always
   review them first?" and save the answer there.
9. **Report** in a few lines: branch, PR, evidence verdict, risk, CI state, merged or waiting,
   what the user still has to decide.

Ask before pushing when the repo's rules require explicit approval beyond typing `/go`, or when
the remote is protected or production. Never force-push a branch other people work on.
