# Template for `.claude/loop.md`, written by /kit:init step 9

Claude Code's bare `/loop` runs a built-in maintenance prompt at a pace the model picks; when
the project has `.claude/loop.md`, that file replaces it. A scheduled prompt cannot invoke a
user-only skill such as `/kit:go`, so this file is how the project tells the native loop how
its PRs are tended. Fill the placeholders from the repo (`<project>`, `<user>`: the git author
in kit.json, `<base>`: the default branch, `<verify>`: the `verify` command from kit.json) and
commit the file like CLAUDE.md. It costs nothing until `/loop` runs. It never merges: a green PR
is reported and left to the person. Since Claude Code 2.1.319 a self-paced loop ends when a round
finishes without rescheduling, so the file says when to schedule the next round.

```markdown
# Maintenance loop for <project>

Each round, in this order. While the PR is open, schedule the next round before you finish
(sooner after a push, later when all is green); stop only once it is merged or closed.

1. Finish any work still open in this conversation.
2. Tend the current branch's PR (`gh pr view --json number,state,mergeable,statusCheckRollup,reviews`):
   - CI red: read the failed job's log (`gh run view <id> --log-failed`), fix the root cause,
     run the project's gate (`<verify>`; through the kit's `gate.py verify` where the kit is
     installed, so the run is recorded), push. After 3 rounds on the same
     failure, stop and leave one comment on the PR: what fails and why you did not fix it.
   - Review comments: apply the mechanical ones and reply on each thread. A product or design
     question goes to <user> as a comment; do not decide it yourself.
   - Conflict with <base>: sync the way /kit:go does (rebase a branch only you push to, merge a
     shared one), resolve, run the gate, push.
   - Green with nothing open: say so in one line and schedule the next round at a longer
     interval. Never merge.
3. Clean up: nothing left behind (`git status`); worktrees of merged PRs removed.

Do not touch other PRs, open new ones, or deploy anything. Reply in one line: what changed,
or "nothing", and nothing more.
```
