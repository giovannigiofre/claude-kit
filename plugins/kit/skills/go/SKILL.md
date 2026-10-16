---
name: go
description: Finishes a piece of work end to end - verify it really works, simplify the diff, verify again, commit on a branch and open a PR. Use when the user appends "/go" to a request or says the work is ready to ship.
disable-model-invocation: true
argument-hint: "[optional: what was built, PR title hint, 'no-pr']"
---

# /go: verify, simplify, commit, PR

Context: $ARGUMENTS

1. **Finish the work first.** If the request this was appended to is not done yet, do it now.
2. **Verify.** Run `.claude/kit.json` `verify` (else the project's tests/lint/build). For a
   change with behaviour you can exercise (CLI, API, UI), exercise it. For a non-trivial change,
   also have `kit:verifier` check it independently. Fix failures and repeat. Do not continue on
   red.
3. **Simplify.** Run the built-in `/simplify` if available, else delegate to
   `kit:code-simplifier`. Re-run `verify` afterwards.
4. **Commit.** If on the default branch, create a branch first (`<type>/<short-slug>`). Stage
   only the files this work changed (never `git add -A` blindly; never secrets, `.env`, large
   data). Write a message that says why, matching the repo's commit style and attribution rules.
5. **PR.** Unless the arguments say `no-pr`: push the branch and open a PR with `gh pr create`.
   Body: what and why, how it was verified (commands + result lines), anything left open.
   Follow the repo's PR attribution rules.
6. **Report** the branch, commit, PR URL and the verification evidence in a few lines.

Stop and ask before pushing if the repo's instructions say commits/pushes need explicit approval
and the user did not just give it by typing /go, or if CI or the remote is a protected/prod
target.
