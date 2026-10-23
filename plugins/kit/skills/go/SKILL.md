---
name: go
description: Finishes work end to end - intent, sync with base, live evidence, review, risk rating, commit, PR, then watches CI until green. Use when the user appends "/go" or says the work is ready to ship; "/kit:go babysit [PR]" only watches open PRs.
disable-model-invocation: true
argument-hint: "[optional: what was built, PR title hint, 'no-pr', 'no-babysit', 'babysit [PR]']"
---

# /go: from first-pass code to a clean, verified PR

Context: $ARGUMENTS

The goal is that the user can judge the PR from its description: what was intended, the proof
that it works, what the pipeline already fixed, and how risky it is. They should not need to
read the diff to decide whether to read the diff.
(Method adapted from kunchenguid/no-mistakes, MIT: intent first, rebase before review, live
evidence, findings with an action, risk assessment, CI babysitting. Nothing copied.)

If the arguments are `babysit [PR]`, skip to step 9 (no PR number = each open PR of yours in
this repo, from `gh pr list --author @me`).

1. **Finish the work first.** If the request this was appended to is not done yet, do it now.
2. **Intent.** Write 2-5 lines: what the user asked for and why, the constraints they gave, and
   what is explicitly out of scope. Take it from this conversation; if the session holds no
   trace of the request, from the branch's commits and the linked issue; if still unclear, ask.
   The intent is the acceptance criterion for steps 4-5, not the diff.
3. **Sync with the base.** `git fetch` and bring the branch up to date with the default branch
   (rebase a local-only branch; merge if the branch is already pushed and shared). Resolve
   conflicts now, so everything below checks what will actually merge.
4. **Verify with live evidence.** Run `.claude/kit.json` `verify` (else the project's
   tests/lint/build). Then exercise the change the way a user meets it: run the CLI, call the
   API, load the page. Save what proves it (command output, screenshot, log excerpt) under
   `.claude/evidence/<branch>/` (gitignored). A test that mocks the changed path, or reading the
   code, is not live evidence. Record one line per scenario:
   `<scenario> | pass/fail/untested | live yes/no | <evidence file>` and an overall verdict:
   **go**, **no-go**, **inconclusive**, or **no-surface** (nothing user-facing to exercise, so the
   gates are the evidence). Fix failures and repeat. Do not continue on no-go.
5. **Review in a fresh context.** For a non-trivial change, have `kit:verifier` check it against
   the intent; for a large or risky one, run the `kit:review` workflow. Treat the implementer's
   claims (including your own) as claims, not evidence. Per finding:
   - **auto-fix**: mechanical, does not change what the user asked for (a missed null check,
     a lint error, a stale comment). Fix it, then re-verify.
   - **ask-user**: touches the intent or a product decision. Collect these; ask once, with
     AskUserQuestion, before the commit.
   - **no-op**: not worth acting on. Drop it.
   A finding the user declines goes into `.claude/review-decisions.md` (one line: date, the
   finding, the reason), so later reviews do not raise it again.
   When fixing, prefer deleting code the intent does not need over adding more, and fix every
   site where the same rule must hold, not only the reported line.
6. **Simplify and update the docs.** Run the built-in `/simplify` if available, else delegate
   to `kit:code-simplifier`. Update README, docs and comments that describe the changed
   behaviour. Re-run `verify`.
7. **Risk.** Rate the change **low / medium / high**, with one or two lines of rationale:
   blast radius (shared modules, auth, money, migrations, data deletion, public API), how much
   of it the live evidence covers, and how hard it is to roll back. This tells the user how
   closely to read the diff; it never replaces the checks above.
8. **Commit and PR.** If on the default branch, create a branch first (`<type>/<short-slug>`).
   Stage only the files this work changed (never `git add -A` blindly; never secrets, `.env`,
   large data, `.claude/evidence/`). Write a message that says why, matching the repo's commit
   style and attribution rules. Unless the arguments say `no-pr`: push and open a PR with
   `gh pr create`. Body sections:
   - **Intent**: from step 2.
   - **Changes**: what changed, in a few lines.
   - **Verification**: the scenario lines and verdict from step 4, gate commands with their
     result lines; attach or link the evidence files (screenshots go in a PR comment with
     `gh pr comment` if they cannot be embedded).
   - **Fixed by the pipeline**: findings fixed in step 5, one line each.
   - **Risk**: from step 7.
   - **Open**: anything left, including findings the user still has to decide.
   Follow the repo's PR attribution rules.
9. **Babysit until green.** Unless the arguments say `no-babysit`: watch the checks with
   `gh pr checks <PR> --watch --fail-fast`. On a CI failure, read the failing log
   (`gh run view <id> --log-failed`), fix the root cause, re-run step 4 for what you touched, and
   push; at most 3 rounds, then stop and report. On a merge conflict, sync as in step 3 and
   re-verify. Review comments that ask for a product decision go to the user. If CI takes more
   than about 10 minutes, stop watching and print the line to continue later:
   `/loop 10m /kit:go babysit <PR>`.
10. **Report** in a few lines: branch, PR URL, verdict, risk, CI state, what the user still has
   to decide.

Stop and ask before pushing if the repo's instructions say commits or pushes need explicit
approval and the user did not just give it by typing /go, or if CI or the remote is a
protected or production target. Never force-push a branch other people work on.
