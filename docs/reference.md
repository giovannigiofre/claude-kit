# Reference

## `.claude/kit.json`

Committed with the project; `/kit:init` writes it from what the repo and its CI run.

```json
{
  "check": "fast gate (< ~30 s): lint + format check (+ types); runs before Claude stops if files changed",
  "verify": "full gate: tests, evals, build; what 'done' means for threads, /kit:go and kit:overnight",
  "checkTimeout": 540, "verifyTimeout": 1800,
  "maxStopRetries": 3,
  "onEdit": [{"glob": "**/*.py", "run": "uv run ruff format -q \"$FILE\"", "timeout": 120}],
  "protect": [
    {"glob": "data/raw/**", "mode": "no-overwrite", "reason": "raw files are immutable"},
    {"glob": "vendor/**", "mode": "read-only", "reason": "vendored code"}
  ],
  "guard": {"protectedBranches": ["main", "master"], "allowCommands": [],
            "denyCommands": [{"pattern": "^npm install\\b", "reason": "pnpm only here"}], "askCommands": []},
  "watchdog": {"silentMin": 20, "bashDeadlineMin": 30, "permissionMin": 2},
  "llm": "on",
  "learn": {"model": true},
  "author": "Giovanni Giofré <99892523+giovannigiofre@users.noreply.github.com>",
  "lead": {
    "read": ["docs/backlog.md"],
    "backlog": "docs/backlog.md",
    "notes": "one line of project-specific advice for the coordinator (threads never see it)",
    "board": ".claude/lead/board.md",
    "ship": "pr",
    "merge": "user",
    "parallel": 3,
    "budget": "none",
    "loops": [{"name": "tend-prs", "every": "10m", "run": "tend the threads' open PRs: failed CI, review comments, merge conflicts"}]
  }
}
```

- The file's presence opts the project in, `{}` included; every key is optional. The
  session-start line names any key the kit does not know, with the nearest known name
  (`unknown key "chek" (did you mean "check"?)`), and a `check`/`verify` that is not a string or a
  `protect`/`onEdit` that is not a list; a misspelt key never fails silently.
- `onEdit` commands run from the repo root; `$FILE` is the absolute path of the edited file,
  `$REL` the path relative to the repo. `**` matches across directories, `*` within one.
- `protect`: `read-only` blocks every edit; `no-overwrite` allows new files and blocks edits to
  existing ones.
- The Stop hook runs `check` only when the tree's content (uncommitted and untracked files
  included) changed since the last passing check, so question-and-answer turns cost nothing.
  After `maxStopRetries` failures in a row it lets Claude stop, and Claude must report the
  failure. The command runs with `KIT_CHANGED_FILES` (the files this branch touched since it
  left the default branch, plus uncommitted ones; shell-quoted, space-separated; `echo
  "$KIT_CHANGED_FILES" | xargs -r ruff check` keeps names with spaces whole), `KIT_CHANGED_COUNT`
  and `KIT_GATE` in its environment, so `check` can look only at what changed. `gate.py` passes
  the same. `checkTimeout` (540 s) bounds `check` wherever it runs, `verifyTimeout` (1800 s)
  bounds `verify`; a gate that times out fails.
- `guard`: on by default in a project with `kit.json`; `"off"` turns it off. `protectedBranches`
  defaults to main, master and the remote's default branch. `denyCommands` / `askCommands`: the
  project's own rules, `{"pattern": "<regex over the whole command>", "reason": "..."}` each
  (a plain string is a pattern); `/kit:learn` writes one when a lesson is "never run X here". `agentsAsk` / `agentsDeny` are an
  optional per-session cap on subagents (ask past one, refuse past the other); the native
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` caps how many run at once. `allowCommands`: regexes the
  guard lets through. `attribution` (default `"block"`): blocks AI credits in commit messages, PR,
  issue and comment text (git; the `gh` subcommands that write: create, edit, comment, review,
  merge, `api` with a body; GitHub MCP tools) and commits under an AI git identity (name
  "Claude", an `anthropic.com` email); reading with `gh pr view … | grep` is not a write.
  `"allow"` turns that rule off. The `secrets` rule lets a store's own tool use it (`ssh -i`,
  `kubectl --kubeconfig`, `aws`, `gh`, `docker`, `gcloud`, `gpg`) and still refuses reading it
  with `cat`, `grep`, Read or Glob. Pair `attribution` with
  `"attribution": {"commit": "", "pr": "", "sessionUrl": false}` in `settings.json`, so Claude
  doesn't write the credits in the first place. `{"guard": "on"}` in `~/.claude/kit.json` guards projects without a
  `kit.json` too. The guard's `wait` rule refuses a foreground wait (sleep over
  `sleepMaxSec`, 60 by default, a while/until loop that sleeps while it polls, `gh run watch`,
  `gh pr checks --watch`) and names the way out: `run_in_background`, the Monitor tool, the
  completion notice. A Monitor command, a background command, one ended with `&`, a `while read`
  loop, a long Bash `timeout` and a command `allowCommands` names pass; `"waits": false` turns
  the rule off.
- `watchdog`: the thresholds of the stall watchdog (see [Stalls](#stalls)), in minutes; `0`
  turns that check off, a value that is not a number keeps the default.
- `learn`: `{"model": false}` keeps the lesson distiller to its no-token passes (see Lessons).
- `llm` (read by the `kit-llm` plugin's hook): `"off"` silences the LLM-code hint in this project.
- `author`: who commits in this project, as `"Name <email>"`. When git's identity in the checkout
  is missing or an AI's (a cloud container's default), the SessionStart hook sets the repo's own
  git config to it, so every commit, the threads' included, is yours. Together with the guard's
  `attribution` rule and `"attribution": {"commit": "", "pr": "", "sessionUrl": false}` in
  settings, you are the only author of commits, PRs and comments.
- `lead` configures the coordinator. `ship`: `local` (verified branches, you merge), `pr` (threads
  push and open PRs), `pr+fix` (they also keep CI green). `merge`: `user` (you review and merge
  every PR) or `agent` (the coordinator merges a PR once CI is green, the review has nothing open
  and the risk is not high; a high-risk PR still waits for you); unset, the coordinator asks when
  the first PR is ready and writes your answer here. Setting `pr` or `pr+fix` here is a
  standing go-ahead to push; without it the coordinator asks once per session. `parallel`:
  threads working at once (default 3). `budget`: `{"items": N}` or `"none"`. `loops`: standing
  loops the coordinator schedules (session-only, they expire after 7 days).

Threads may commit, amend, rebase and force-push (with `--force-with-lease`) on the branches
they created for their own items, never on the default branch or someone else's. Auto mode
blocks history rewrites by default, and `autoMode` is read from user settings only, so the kit
offers this rule (with `attribution` off) once per machine at session start and merges it into
`~/.claude/settings.json` on yes (`hooks/scripts/machine_setup.py`; `--decline` stops the offer):

```json
{"autoMode": {"allow": ["$defaults", "On a branch an agent created for its own task (not the default branch, not one someone else pushed to), rewriting its commits (amend, rebase, setting the user's authorship) and pushing it with --force-with-lease"]}}
```

Also per project, committed: `CLAUDE.md` (the project's rules, which win over the kit),
`.claude/skills/verify/SKILL.md` (how to run and exercise the app; Claude Code runs a skill of
that name before each commit), `.claude/loop.md` (what a bare `/loop` does for this project's
PR: fix CI, answer reviews, sync with the base, reschedule itself while the PR is open; it never
merges), `.claude/review-decisions.md`
(findings you declined, so reviews don't raise them again). Gitignored: `.claude/evidence/`,
`.claude/overnight/`, `.claude/lead/`, `.claude/kit.local.json` (the kit adds each to
`.git/info/exclude` when it writes there and the project does not ignore it).

### Auto mode environment, per repo

Auto mode reads `autoMode` (allow, soft_deny, environment) from user settings only; an `autoMode`
block in a project's settings is ignored. So the environment lines that describe one repo
(organization, cloud, trusted domains, secret files, protected branches) are stored in your
Claude config dir (`$CLAUDE_CONFIG_DIR`, else `~/.claude`), one block per repo, and the kit adds
them to `autoMode.environment` scoped to that repo. Only environment lines are per repo; `allow`
and `soft_deny` stay in your user settings.

```bash
S=<kit>/hooks/scripts/auto_mode_sync.py
D='{"environment": ["**Organization**: acme", "**Cloud provider(s)**: GCP project shop-dev"]}'
echo "$D" | python3 $S --preview -    # the exact lines --set would add; changes nothing
echo "$D" | python3 $S --set -        # store them for the repo you are in, then rebuild
python3 $S --show             # what is stored for this repo
python3 $S --remove           # forget this repo
python3 $S                    # rebuild only (what SessionStart runs)
```

`/kit:init` drafts the lines from what the repo shows, shows you the `--preview` output and runs
`--set` once you approve it.

**Security model:** nothing inside a repository can add auto mode lines. No file in the repo is
read for them; only your `--set` command writes a block, so a cloned repo cannot declare itself
trusted, whatever it commits.

- A repo is its origin URL, normalized (`git@github.com:Acme/shop.git` and
  `https://github.com/acme/shop` are the same `github.com/acme/shop`, credentials dropped), so
  every checkout and worktree matches; without an `origin` remote, its main checkout path. Both
  end up in the line the classifier reads, so `--set` refuses an origin that is not plain ASCII,
  contains `#`, `?`, `\`, `%`, whitespace or control characters (URL parsers disagree on the host
  there), or does not normalize to one plain `host/path` token of at most 200 characters (letters,
  digits, `._~-`, no `..`), and a checkout path over 300 characters or with anything but letters,
  digits, space and `._~+@/-`. A stored block that fails the same check is skipped at rebuild.
  An ssh URL with a port (`ssh://git@host:2222/o/r`) is a different repo from the scp form
  (`git@host:o/r`); that fails closed, the lines simply do not apply to the other form.
- Blocks: `kit-auto-mode/<slug>.json` = `{"repo": {"origin", "name", "paths"}, "environment": [...]}`.
  At most 20 lines of 400 characters per repo.
- Each line is written as ``**Organization (shop repo only)**: In the repository whose git origin
  is `github.com/acme/shop`, in any checkout or worktree of it (known checkouts: `/path/shop`),
  and nowhere else: acme [kit auto-mode]``. Labels lose `**` and newlines; the `(repo only)` suffix and
  the trailing tag are always the kit's. A rebuild replaces only lines in exactly this form (the scoped
  prefix and the tag), so your own lines stay, in order, even one that happens to end in the tag.
  A line is capped at 1000 characters; known checkouts are dropped first to keep room for the text.
- A new list starts with `"$defaults"` (`environment` supports it, as `allow` does), so the
  built-in entries stay current; a list without it is left that way, and a non-list
  `environment` is left alone with a one-line warning.
- Writes happen under a lock (`kit-auto-mode.lock`, waited on for at most 2 seconds: a busy lock skips the sync at session start with one line, and `--set`/`--remove` store the block, exit 1 and leave it for the next session start), atomically, only when the result changes,
  after a backup to `settings.json.kit-auto-mode-backup`; the first backup ever is also kept as
  `settings.json.kit-auto-mode-backup.orig`. If another program writes settings.json during a
  rebuild, the rebuild starts again from that version. A settings file that is not valid JSON,
  a read-only one, or one whose `autoMode` is not an object is never rewritten (one-line warning).
- If `--set` stored the block but could not update settings.json, it says so and exits non-zero;
  the next session start applies it.

At session start in a kit project the hook only rebuilds from the stored blocks (no git, no
`claude` command, nothing read from the repo), so a reset or hand-edited settings file gets the
lines back; it is silent when nothing changed. With no blocks it takes no lock and writes nothing
unless settings.json still has `[kit auto-mode]` lines, which it then removes. Check the result with `claude auto-mode config`.

## Items and proposal cards

`hooks/scripts/items.py`: each coordinator item is a folder, the mailbox between you, the
coordinator, its threads and the verifier (state in files you can `cat`, edit to steer, and
resume from; the source of the idea is in CATALOG.md).

```
.claude/lead/items/<id>/BRIEF.md     headed `ITEM: <id>`; the goal, DONE WHEN, scope; edit it to steer the next round
.claude/lead/items/<id>/REPORT.md    the thread's final report (written by the SubagentStop hook, kit:implementer)
.claude/lead/items/<id>/VERDICT.md   the verifier's report (SubagentStop, kit:verifier)
.claude/lead/items/<id>/LOG.md       one line per event: queued, working, reported, verdict, review, done
.claude/lead/items/done/<id>/        archived (a second item with the same id lands in done/<id>-2/)
```

```bash
python3 <kit>/hooks/scripts/items.py new "<name>" --brief - --from lead|handoff [--kind scout]  # id and folder printed
python3 <kit>/hooks/scripts/items.py list [--status queued]
python3 <kit>/hooks/scripts/items.py log <id> <status> [note]
python3 <kit>/hooks/scripts/items.py show <id>
python3 <kit>/hooks/scripts/items.py done <id>
python3 <kit>/hooks/scripts/items.py unattended [push=ask|allow] [rebase=ask|allow] [merge=ask|allow]
```

`unattended`: the owner's git preferences for unattended runs in this repo, in the main
checkout's `.claude/kit.local.json` (`{"lead": {"unattended": {"push": "ask", "rebase": "ask",
"merge": "ask"}}}`), which the command adds to `.git/info/exclude`: local to this machine and
repo, never global, never committed. Without arguments it prints the brief line `UNATTENDED:
push=ask rebase=ask merge=ask` and whether it is set; a missing, broken or misspelt value is
`ask`. The coordinator asks only when an unattended run starts and nothing is set, saves the
answer and briefs every thread of the run with that line ([unattended.md](../plugins/kit/skills/lead/unattended.md)).
A thread does not run a step set to `ask` and hands back `needs push` (rebase, merge); `allow`
runs it. The line carries the effective value, so a saved `allow` prints as `ask` with a note
naming what to change. Claude Code checks deny, then ask, then allow rules, and the first match
wins whichever scope it is in. So the command checks the rules in managed settings, the user's
`~/.claude/settings.json`, and the repo's `.claude/settings.json` and `settings.local.json`
against the step's commands. A matching deny or ask rule (a committed `Bash(git push*)` ask, say)
keeps the step at `ask`: the note names the rule and its file, and says that an allow rule in
`settings.local.json` cannot override it. With no allow rule covering the step, the note names
the rules to add to `.claude/settings.local.json` (`Bash(git push:*)`, `Bash(git rebase:*)`,
`Bash(gh pr merge:*)` and `Bash(git merge:*)`). A settings file that does not parse also keeps
the step at `ask`. The kit never edits permission settings.

A thread briefed with the BRIEF.md text carries the `ITEM:` line; when it finishes, the hook
files its report under the item (`reported | done, 2 decision(s), agent <id>` in the LOG); when
the verifier finishes, its verdict (`verdict | FAIL scope=local:src/x.py, reviewed <sha>, agent
<id>`; the sha is the branch head the verifier read, so a later push makes the verdict stale).
The hook finds the item from the main checkout even when the thread stops inside its worktree
(the default), where `.claude/lead/` does not exist. The report filed is the one the thread
handed back with SubagentHandback; its closing line is not the report. The lead reads BRIEF.md
again before re-briefing (you may have edited it) and VERDICT.md; a `FAIL scope=local:<paths>`
becomes a scoped fix sent to the thread, not a new brief. `DECISION:` lines in a report are the
thread's judgment calls, shown to you once so you can veto them. `new` also appends a `queued`
row to the board when one exists, so the status line and the coordinator see an item that
`/kit:handoff` or `/kit:scout take` queued from another session; the session-start line says
how many items wait on disk. `.claude/lead/` is added to `.git/info/exclude` when the project
does not ignore it.

`hooks/scripts/proposals.py`: candidate work found by read-only explorers (`/kit:scout`), one
card per finding in `.claude/lead/proposals/<id>.md` (frontmatter: id, fingerprint, origin,
class, confidence, created, evidence; body: Suggestion, Rationale). The fingerprint is the
sha256 of the normalized `origin|summary|rationale`, so a re-run never duplicates a card; a
summary that is already an item is skipped, and so is anything that looks like a secret.
Classes: A mechanical and reversible (the coordinator's `next` takes it), B needs judgment
(it asks), C a human decision (never started by an agent). `take <id>` turns a card into a
queued item and retires the card; `retire [--days 30]` archives cards older than that or whose
origin file is gone.

## Effort and fresh eyes

Threads start fresh: a `kit:implementer` sees its own system prompt, the project's CLAUDE.md, a
`git status` snapshot, the brief and the kit's start-up line (lessons and the gate command), and
nothing of the coordinator's conversation. The brief is the whole channel. Two consequences the
kit acts on:

- **Effort per thread.** `kit:implementer` declares `effort: medium` (Opus 5.5's default): the
  level its threads run at whatever the session's, so an `xhigh` session does not spawn `xhigh`
  threads (and a `low` one still gets `medium` threads; since 2.1.317 a subagent on another
  model falls back to that model's default anyway). The coordinator passes `effort` on the Agent
  call: `low` for a brief with a checkable DONE WHEN, a small scope and its PLACES listed,
  `medium` otherwise, `high` for ambiguous or architectural work; after a `FAIL` that is not
  `scope=local`, or a `BLOCKED`, it re-dispatches one level higher, never past `high` without
  asking (Sun et al. 2026: starting low and escalating on a verified failure matched or beat a
  fixed top effort at lower cost). The call value overrides the frontmatter and stays in effect
  when the thread is resumed (sub-agents reference, Claude Code 2.1.292+); the values are `low`,
  `medium`, `high`, `xhigh`, `max`. Scouts run at `low`, `kit:verifier` at `medium` (declared in
  its frontmatter; it used to inherit the session's level). `CLAUDE_CODE_SUBAGENT_EFFORT`
  (2.1.316) sets the level for subagents that name none, your own `.claude/agents` and the native
  Explore and Plan agents; `CLAUDE_CODE_EFFORT_LEVEL` beats every frontmatter and call. Anthropic's
  effort page puts subagents under `low` ("simpler tasks that need the best speed and lowest
  costs, such as subagents") and says to run an effort sweep on your own evals rather than carry
  a setting over. The sweep for the kit:
  `CLAUDE_CODE_EFFORT_LEVEL=low claude plugin eval . --case lead-verifies-before-done --runs 3 ...`
  against the same at `medium`, comparing pass rate and cost; change the default only on that
  evidence.
- **Fresh eyes on a brief** (`skills/lead/fresh-eyes.md`): for an item that is large,
  architectural or reads two ways, one read-only subagent gets the brief alone and returns a
  paraphrase, what it would have to guess, what DONE WHEN does not need, what exists to reuse
  and what the brief names that does not exist. The lead fixes the brief before the thread
  starts. Adapted from Google's Elephant-Goldfish Model (Apache-2.0), which runs five such
  passes on a design document before any code; the kit runs one, on a brief, only when the
  item deserves it.

## The gate record

`hooks/scripts/gate.py` runs a gate and keeps the result as evidence:

```bash
python3 <kit>/hooks/scripts/gate.py verify [--timeout N]   # runs kit.json verify, prints its output, exits with its code
python3 <kit>/hooks/scripts/gate.py check
python3 <kit>/hooks/scripts/gate.py status [verify|check]  # does the last record cover the tree as it is now? (exit 0 / 1)
```

The record, `.claude/evidence/<branch>/gate-<name>.json`, holds the command, exit code, duration,
the hash of the tree it ran on (committed and uncommitted content, ignored files left out, so a
commit of the same content keeps the hash), whether the gate itself changed files (a formatter),
and the last 25 lines of output: a gate that ran is a claim until something records what it ran
on, and this is what the PR's Evidence section and the verifier cite. Nothing blocks on it.
Threads and the verifier are told the exact command at start (SubagentStart) and `/kit:go` runs
it in step 4. Run from a linked worktree, the record is written under the main checkout's
`.claude/evidence/`, so it outlives the worktree. `.claude/evidence/` is added to
`.git/info/exclude` when the project does not ignore it. The Stop hook uses the same hash to know whether anything changed since its last
passing check.

## Edits made through the shell

In auto mode Claude is told to change files with `sed`, heredocs and short scripts rather than
the Edit tool, so a hook on `Write|Edit` never sees those edits. Before each Bash command in a
kit project the guard notes which files are modified or untracked and their mtimes; after it,
`bash_edits.py` (PostToolUse, matcher Bash) compares. A file the command changed gets the
`onEdit` commands for its glob, and a protected one is reported (read-only: any change;
no-overwrite: a change to a file that existed before) with the way to restore it; the hook
reverts nothing itself. A command that changed more than 40 files is reported, not checked.
The before-image is kept per session and agent, so parallel threads in one checkout do not
overwrite each other's. Cost: one `git status` before and after each shell command, only in a
project that has `protect` or `onEdit`.

## Stalls

Nothing in Claude Code tells the coordinator that a thread went quiet. The kit's mod watches on
its 15 s tick (interactive sessions only) and wakes the coordinator with a prompt of its own:

- a running thread whose transcript has not moved for `silentMin` (20), skipped while it waits
  on its own subagent, background command or Monitor (a Monitor counts until its `timeout_ms`);
- a thread past the duration its brief expected: an `EXPECT: 90m` (or `2h`) line in the Agent
  prompt the thread was started with (the mod reads that prompt, not BRIEF.md on disk);
- a background command past its deadline (its Bash `timeout`, else `bashDeadlineMin`, 30) while
  its owner has been quiet for `silentMin`. A command whose description holds `(server)` is
  meant to keep running and has none. A thread still within its brief's EXPECT is not woken
  about a command that only passed the `bashDeadlineMin` guess, only one past its own `timeout`. A background thread's command that runs past 3 minutes is
  moved to the background by Claude Code itself (2.1.318) and counts as one of these;
- a thread that waits (status `waiting`) on its own background work when none of it can wake
  it, for `5` min: every command has ended, or what is left is a holder.

A command has ended when its output file (next to the threads' transcripts) ends with Claude
Code's `[exited with code N]` or `[killed]` line; the mod reads it (up to 1 MB, once it has
stopped growing) and drops the command once its owner acts again. An ended command no longer
hides a quiet thread. A holder is a loop that ends only when its thread acts (a `hold` in the
description, `while [ -e f ]`, `until [ ! -f f ]`, `sleep infinity`): it never hides a quiet
thread, whatever its label. A silent or stuck wake names what it found: the ended command with
its last output lines, the holder, a permission prompt the thread is inside, and the recovery
(`TaskStop`, then `SendMessage` with what the thread missed). A thread resumed by SendMessage
counts its silence from the resume, and one the mod has no record of (it finished before) is
still timed by its transcript.

Each stall wakes at 1x, 2x and 4x its threshold, and the third wake also sends a native
notification, and it stays quiet until real activity starts it over: the turn a wake itself
starts does not count. A thread waiting `permissionMin` (2) on a permission
prompt notifies the person (not one a hook answered first); the prompt is never answered for them. A turn that failed on the API
gets a "continue" nudge after 15, 30 and 60 s when the error clears on its own (overloaded, a
server error, a short rate limit, `max_output_tokens`) and a notification plus a NEEDS YOU wake when it does not (a
login, a usage limit). A thread that ends without its report reaching the coordinator (a refused
or missing `SubagentHandback`) is told once by `subagent_stop.py` to send it; if it stops again
without one, the coordinator is woken to SendMessage it. The coordinator addresses a thread by
the agent ID the Agent call returned (a name needs agent teams, which the kit does not enable;
the ID also survives a restart, and the hooks write it into the item's LOG); a message reaches
a thread even while its command runs (2.1.317: the command moves to the background). The facts
live in memory, bounded to the work in flight; a module reload only makes the watchdog quieter.

Claude Code itself sends a task notice each time a thread stops with background work still
running ("Agent X is waiting on its own background work"; the result says it has not reported
yet). It changes nothing for the coordinator, yet each one was a turn: 144 in one 24-hour
session. The mod drops it at `prompt.submit` before it becomes a turn, and the transcript shows
one dim line saying so. Only a notice whose every `<task-notification>` block is such an interim
one, with nothing beside it but Claude Code's preamble, is dropped; a thread's report, a
command's notice, a mix or the same text typed by the person passes. The thread's report comes
later under the same task id, and the `stuck` check above covers work that ended without waking
it. What the kit cannot change: Claude Code still emits the notice, and without the mod (a
session that has not loaded it) each one still wakes the coordinator.

## Permission prompts

`permission.py` (PermissionRequest, matcher Bash) allows, without a prompt, a command that is
exactly kit.json `check` or `verify`, or the kit's own `gate.py`, `lessons.py`, `items.py`,
`proposals.py` or `compact_logs.py` by their real path. Nothing else is touched: the guard has already judged the
command, and the permission system decides the rest. `/fewer-permission-prompts` (built in)
writes a broader read-only allowlist to project settings if you want one.

## Lessons

The kit keeps what each repo has taught it in a ledger outside every repo, under the Claude
config dir (`~/.claude` unless `CLAUDE_CONFIG_DIR` says otherwise):

```
~/.claude/kit-lessons/<slug>.jsonl        one lesson per line (id, kind, text, status, seen, misses, evidence)
~/.claude/kit-lessons/<slug>.events.jsonl raw captured events, capped
~/.claude/kit-lessons/<slug>.ops.jsonl    before-images of every change, for undo
~/.claude/kit-lessons/_machine.jsonl      lessons that hold on this machine across repos
```

A repo is its normalized git origin, so every checkout and worktree of it shares one ledger (the
slug is the auto mode one). Only kit code writes there; nothing in a repo can plant a lesson.

**Capture** is deterministic and costs no tokens: a failed fast `check` (Stop) and a
kit:verifier FAIL (SubagentStop: each problem headline becomes a candidate). A guard denial is
counted as an event for the statistics but never becomes a lesson: the hook already enforces
it, and a delivered copy would only spend the threads' budget. The verdict
is read from the verifier's report: its final message, else the SubagentHandback report in its
transcript. Verifier verdicts and revert commits are counted as events, for stats and the
distiller; a verdict is tied to the branch its brief names (else its report, else a PR number),
and a PASS confirms only the last FAIL on the same branch (with no branch named, it confirms
nothing). Each report counts once, so a verifier resumed with SendMessage records its next round
too. The same key seen again is counted, not added; a repeat after the lesson was delivered
counts as a miss. A new automatic lesson starts as a candidate and turns active on its second
sighting, at most 3 a day per repo. Text that looks like a key or token is refused (a path with
digits, a migration file name or a sha256 is not a token). A repo under a
temp dir (`/tmp`, `/var/folders`, `$TMPDIR`; `KIT_TEMP_ROOTS` overrides the list) gets no ledger:
tests and scratchpad probes teach nothing. Tests point `CLAUDE_CONFIG_DIR` at a temp dir.

**Import**: at session start the kit imports, once and without touching the files, the
kit:verifier memory index (`.claude/agent-memory/kit-verifier/MEMORY.md`) and your auto-memory
`feedback_*` entries. A verifier pitfall about claude-kit itself (naming the kit's repo and one of its files) goes
to claude-kit's ledger. Each imported lesson lists its source, so an entry is imported once; nothing is written
inside the repo. Threads also run the import at start, so a memory written mid-session reaches the
next thread.

**Delivery**: kit:implementer and kit:verifier get this repo's active lessons at start (the
verifier minus its own memory, which it already reads), the main session gets gate and guard
lessons after the gate lines. Most repeated and newest first; about 600 tokens for a thread,
400 for the session. With an empty ledger the thread gets the memory index lines directly.

**Distiller** (`distill.py`): runs after a kit:verifier PASS that follows a FAIL on the same branch (the FAIL's
problems become active lessons), at SessionEnd once 5 new events are pending (in the background),
and on `/kit:learn`. Without tokens it merges lessons that say the same thing, retires a lesson
marked wrong twice (`harmful`), and proposes retiring stale ones: automatic pitfall and gate
lessons not seen for 60 days, candidates seen once in 30. A proposal changes nothing; accept it
with `/kit:learn retire <id>`, or keep the lesson with `/kit:learn undo <id>` (it is not asked
again). Unanswered, it is asked again after 30 days; a new sighting withdraws it. It also writes a hardening proposal
for a lesson that came back twice after threads were told (a check, a test or a CLAUDE.md line;
announced, never applied). Every change is one line at the next session start, with
`undo: /kit:learn undo <id>`.

It may also make one model call to reword and merge lessons: `claude -p --model haiku` with no
tools, hooks or plugins, from an empty folder, capped at $0.05 (`--max-budget-usd`) and run at
most once a day per repo. A typical call costs about $0.001. The model can only edit, merge
or retire existing lessons, and its text passes the same secret filter. It never runs in a
headless session: overnight (`KIT_HEADLESS`), or any `CLAUDE_CODE_ENTRYPOINT` other than an
interactive one (`cli`, `claude-vscode`, `claude-desktop`, `claude-desktop-3p`), so not in
`claude -p` or the SDK; `CLAUDE_CODE_SESSION_ATTENDED=1` (set in an attended cloud session)
counts as interactive whatever the entrypoint. Turn it off with `KIT_LEARN_MODEL=0` or
`"learn": {"model": false}` in kit.json.

**Promotion** (`promote.py`, run by the distiller): a lesson active in 2 real repos, whose wording
passes the structural check (no repo name, org or path from the ledgers, no file name or path, no
env var) and the model's genericity judge (would it be correct and useful in an unrelated repo with
a different stack, naming no product, library, service, tool config or project term?), becomes one
machine lesson (`M` ids) that every repo gets; the repo copies turn `promoted`, and undoing the
machine lesson gives them back for good. Only a machine lesson goes further: seen in 3 or more
repos, about the kit, or a `kit-defect`, it becomes a kit candidate, announced once, when its
wording passes the structural check; a project-specific lesson stays in its repo's ledger. Only
`/kit:learn promote <id>`, run in an interactive session, prepares a claude-kit branch: the
smallest generic change, a regression test or eval that fails without it, the budget test, and
`lessons.py scrub` on the diff (no repo names, orgs, paths, env var names from the ledgers, or
secrets). It opens the PR in that session and never merges it. `lessons.py promoted <id> <version>
<url>` then makes the lesson retire itself once the PR is merged (checked with `gh`) and that kit
version is installed. The judge is one haiku call per batch, part of the distill's one counted
model run for the day (with the reword call); with no model (`--no-model`, headless, turned off), a
timeout or an unclear answer the lesson stays local and is asked about on a later run. It may give
a generic rewording, promoted only when that passes the structural check too.

**Upkeep**: from 14 days after the last review (the first session starts the clock) the session
start adds one line, "the lesson review is due", at most once per 14 days (a declined review comes
back a period later), and `/kit:learn` runs `lessons.py review --dry-run`, which changes nothing
and previews the distiller's merges, retires and promotions on a throwaway copy of the ledgers (its
rewords too when the model is allowed: that one call counts for the day and the review applies its
answer; `--no-model` says rewords are skipped), then, once the user agrees, `lessons.py review`: it
drops the ledgers of test and scratchpad repos and retires the machine lessons only they held
(`prune`), retires lessons neither seen nor delivered for 90 days, then runs the distiller. Every
retire can be undone; a dropped ledger cannot. The dry run writes only metadata to `_repos.json`
(`model_runs`, and `model_preview`, the answers the review applies), never a lesson; its judge
verdicts are kept the same way, so the review promotes what it listed.

```bash
python3 <kit>/hooks/scripts/lessons.py list [--all] [DIR]
python3 <kit>/hooks/scripts/lessons.py render implementer|verifier|lead [DIR]
python3 <kit>/hooks/scripts/lessons.py add pitfall KEY "one line" [DIR]
python3 <kit>/hooks/scripts/lessons.py retire L4 [DIR]
python3 <kit>/hooks/scripts/lessons.py undo L4 [DIR]
python3 <kit>/hooks/scripts/lessons.py stats [DIR]
python3 <kit>/hooks/scripts/lessons.py news [DIR]
python3 <kit>/hooks/scripts/lessons.py distill [--no-model] [DIR]
python3 <kit>/hooks/scripts/lessons.py review [--dry-run] [--no-model] [DIR]
python3 <kit>/hooks/scripts/lessons.py prune [--dry-run]
python3 <kit>/hooks/scripts/lessons.py promote [ID] [DIR]
python3 <kit>/hooks/scripts/lessons.py promoted ID VERSION PR_URL [DIR]
git diff origin/main... | python3 <kit>/hooks/scripts/lessons.py scrub -
```

## Modes and the status line

- **Light**: a normal session. `/kit:lead <work>` starts the coordinator when you want it.
- **Loop**: every message you type (terminal or Remote Control) gets one line of context sending
  it to the coordinator; headless runs, scheduled prompts and notifications never do. `/kit-mode
  loop|light|ask`. Without a choice for the project, the personal default in
  `~/.claude/kit.json` (`{"mode": "light"}` or `"loop"`) applies, else loop in a project with
  `.claude/kit.json` and light elsewhere.
- **Ask**: a discussion about the repository. Every typed message gets one line of context:
  explore, explain, reason and propose; change no code; documentation (Markdown, `docs/`) may be
  edited when you ask; offer `/kit:handoff` when something worth doing emerges. It is an
  instruction, not a block: the guard keeps protecting the irreversible things, nothing else is
  refused. `/kit:handoff [lead | session <name> | bg | save | card]` writes the brief
  (`kit:shape`'s format plus PLACES and DECISIONS), saves it as an item
  (`.claude/lead/items/<id>/BRIEF.md`) and sends it: to this session's coordinator (queued; it
  starts at the next message in loop mode), to another open session on this machine
  (cross-session `SendMessage`; it arrives as a message from a peer and that session confirms with
  you first; the receiving session's `crossSessionInbound` setting must accept), to a new
  background session (`claude --bg --name <id>`, then `claude attach <id>` or `claude agents`),
  or nowhere (`save`); `card` makes a proposal card instead, for an idea with no checkable done.
- **Board** (`.claude/lead/board.md`):

  ```
  SHIP: pr | MERGE: user | PARALLEL: 3 | BUDGET: none
  RULES: <standing preferences you stated>
  NEEDS YOU: <id: question>; <id: question>
  <id> | <ship|scout|overnight> | <goal> | DONE WHEN <check> | <status> | agent <id> | <branch/PR> | <last event>
  ```

  Status: `queued`, `working`, `review`, `needs-you`, `landing`, `done`, `parked`. The status line
  counts the `review` items (`N ready`), the NEEDS YOU questions and `needs-you` rows (`N need
  you`) and the `queued` rows, re-reading the board every 15 seconds (a board written as a
  Markdown table, or with capitalised statuses, counts the same), and the threads stopped on a
  question or a permission (`N waiting`, from the engine's agent list). When a tick finds more
  ready items or questions than the last one, the mod sends one native notification
  (`$.ui.notify`, Claude Code 2.1.295+; silently skipped where the engine lacks it), unless you
  were active in the terminal within the last minute; in loop mode the coordinator is told the
  mod notifies, so you get one notice per event, not two.
- **Safety**: `/kit-safety host|sandbox`. Sandbox writes the kit's block into
  `.claude/settings.local.json`; check it with `/sandbox`, add hosts under
  `sandbox.network.allowedDomains`. Where the sandbox can't start, commands run unsandboxed with
  a warning rather than all failing. `/kit-safety unattended on|off` (Claude Code 2.1.319) writes
  `permissions.denyInsteadOfPrompting` into the same file: a tool call that would wait on a
  permission prompt is denied and the turn goes on, in this session and its threads. For an
  evening nobody will watch; off by default, since a denied action lowers a thread's chances
  silently; the status line shows `unattended` while it is on, so a forgotten switch is visible
  the next morning. `permissions.blockWritesOutsideWorkingDirectories` (2.1.314) is not for a kit
  project: it refuses a thread's edits in another repo and removes the worktree tools.

The mod needs Claude Code with mods (2.1.287+). Without it, the skills and hooks still work; use
`/kit:lead` directly instead of loop mode.

## Overnight runner

```
python3 <kit>/skills/overnight/scripts/overnight.py "<objective>" --stop-when "<condition>" \
  --worktree ../app-overnight --max-iterations 40 --max-usd 25 --effort medium [--fallback-model sonnet] [--max-turns 60]
```

Each iteration runs `claude -p` in permission mode `auto` unless `--permission-mode` says
otherwise, with `--permission-prompts none` (a headless session cannot answer a prompt: anything
that would ask is denied at once; since Claude Code 2.1.302 `-p` starts in the manual mode
without it on third-party providers, with telemetry off or on a fresh install). Auto mode needs
Anthropic's server check: with `DISABLE_TELEMETRY` or `CLAUDE_CODE_DISABLE_FEATURE_FLAGS` set,
or behind an LLM gateway, every unchecked action is denied (2.1.319) and `claude -p` exits 1
saying so; the runner stops at once with the cause (unset those variables, or
`CLAUDE_CODE_AUTO_MODE_SERVER=0`) instead of spending three "no change" iterations, and does the
same for a startup failure or a lost transcript. It also reads `credential_expires_at` from the
first iteration's JSON and stops before a round that would outlive the claude.ai sign-in.
A Fable or Mythos model bills usage credits without asking in `-p`, so the runner
refuses `--model fable` unless `--allow-credits` is given. `--no-unattended-note` drops the
kit's note about unattended runs from the system prompt (to measure whether a model still
needs it); `--dry-run` prints the exact agent command.

Each iteration is a fresh `claude -p` that makes one small change; the runner runs the gate and
commits it, or resets. It stops on the stop condition, a cap, a `blocked` report, or 3 failed
iterations in a row (no change counts as a failure). Every iteration's system prompt says nobody
is there to answer; an iteration that reports progress without a change is resumed in the same
session up to `--max-continuations` times (default 2). Rate limits are waited out. Run files:
`.claude/overnight/<run>/` (`objective.md`, `notes.md`, `log.jsonl`, `state.json`,
`end-state.json`); `--resume <run dir>` continues a stopped run.

## Cloud sessions

A claude.ai/code session runs in a container where only the plugins of its environment exist,
so the kit is there only when the environment's setup script installs it:
`claude plugin marketplace add <checkout of claude-kit> && claude plugin install kit@claude-kit`,
then `python3 <kit>/hooks/scripts/machine_setup.py --apply` (non-interactive; the session-start
offer is skipped where `CLAUDE_CODE_REMOTE=true`). With it, the gates, the guard, the board, the
items and the threads work as on your machine. Two things differ. The lesson ledger lives under
`~/.claude`, which a container starts empty and loses at the end: cloud threads get no lessons
and leave none (the ledger is per machine; a `/kit:learn promote` from your Mac is what carries a
lesson across). And `.claude/lead/` is gitignored, so a cloud session and your Mac never see
each other's board, items, evidence or proposal cards; two leads on one checkout both rewrite
the board whole, last writer wins, while LOG appends and `done` are safe. The kit reads
`CLAUDE_CODE_SESSION_ATTENDED=1` as "someone is at the keyboard" whatever the entrypoint, so an
attended cloud session gets the lesson-review line and the model pass like a terminal one.

## Develop

```bash
claude plugin validate ./plugins/kit && claude plugin validate .
claude --plugin-dir ./plugins/kit            # try changes in one session without installing
```

Self-checks (no tokens):

```bash
python3 tests/test_budget.py
python3 plugins/kit/hooks/tests/test_guard.py
python3 plugins/kit/hooks/tests/test_gate.py
python3 plugins/kit/hooks/tests/test_stop_check.py
python3 plugins/kit/hooks/tests/test_bash_edits.py
python3 plugins/kit/hooks/tests/test_permission.py
python3 plugins/kit/hooks/tests/test_items.py
python3 plugins/kit/hooks/tests/test_proposals.py
python3 plugins/kit/hooks/tests/test_session_start.py
python3 plugins/kit/hooks/tests/test_subagent_start.py
python3 plugins/kit/hooks/tests/test_lessons.py
python3 plugins/kit/hooks/tests/test_subagent_stop.py
python3 plugins/kit/hooks/tests/test_machine_setup.py
python3 plugins/kit/hooks/tests/test_auto_mode_sync.py
python3 plugins/kit/skills/investigate/tests/test_compact_logs.py
python3 plugins/kit/skills/overnight/tests/test_overnight.py
python3 plugins/kit-llm/hooks/tests/test_llm_detect.py
claude plugin test plugins/kit               # the mod (modes, safety, status line, watchdog) against the engine
```

Test a hook by hand:

```bash
echo '{"cwd":"'$PWD'","tool_input":{"file_path":"'$PWD'/src/x.py"}}' \
  | python3 plugins/kit/hooks/scripts/on_edit.py; echo $?
```

### Evals

They spend real tokens; `--max-cost-usd` caps the estimate. Each runs the same case with and
without the plugin (`--ablation with-without`); look at which cases flip, not only the mean, and
run at least 3 times per arm (`--runs 3`): the 2026 harness studies put rerun noise at 2-6
points, more than most single components move. Pin `--model` so two kits are compared on the
same model.

| Plugin | Case | Checks |
|---|---|---|
| kit | `lead-dispatches-threads` | three pieces of work become board items and background threads (at most `parallel`), short replies |
| kit | `lead-verifies-before-done` | a small goal ends with a checkable done and evidence from running it |
| kit | `verifier-catches-bug` | a claimed-done change with a planted bug is rejected |
| kit | `go-reports-risk-and-evidence` | `/kit:go` reports intent, evidence from running the CLI, a risk rating |
| kit | `overnight-sets-budget` | an overnight request reaches `kit:overnight` with a gate, a stop condition and a budget choice |
| kit | `investigate-asks-for-evidence` | console-only production logs: one batched request for failing and working exports |
| kit | `investigate-logs-root-cause` | the fix lands where the bad data enters, with a regression test |
| kit | `offers-domain-plugin` | a UI request in a project without kit-ui reaches `kit:extras` |
| kit-llm | `picks-llm-skill`, `optimize-needs-evals` | answer-quality and prompt-tuning requests measure first |
| kit-llm | `builds-llm-tool`, `llm-edit-detected`, `injection-aware` | build discipline, the edit hook, the lethal trifecta |

```bash
cd plugins/kit
claude plugin eval . --case verifier-catches-bug --scaffold --trust-plugin --no-publish --max-cost-usd 4
claude plugin eval . --case lead-dispatches-threads --scaffold --trust-plugin --no-publish \
  --allow-tools Write Edit "Bash(python3 *)" "Bash(pytest *)" "Bash(git *)" --max-cost-usd 10
cd ../kit-llm
claude plugin eval . --case picks-llm-skill --scaffold --trust-plugin --no-publish --max-cost-usd 3
```

Kit 1.0 on Opus 5.5 (2026-10-23, one run per arm, about USD 3.3 in all), with minus without:

| Case | With | Without | Note |
|---|---|---|---|
| `offers-domain-plugin` | 1.00 | 0.00 | `kit:extras` fired and offered Kit UI |
| `llm-edit-detected` | 1.00 | 0.00 | the hook routed a plain "fix the retry" to llm-build: capped backoff, no retry on 4xx, tests |
| `optimize-needs-evals` | 1.00 | 0.00 | measure before rewriting the prompt |
| `picks-llm-skill` | 1.00 | 1.00 | plain Opus also measures first |
| `verifier-catches-bug` | 1.00 | 1.00 | Opus finds the bug itself and uses no verifier, as its prompting guide predicts |
| `lead-dispatches-threads` | 0.67 | 0.00 | board and threads started; the threads could not commit because the eval sandbox mounts `.git` read-only |
| `go-reports-risk-and-evidence`, `lead-verifies-before-done` | 0.50 | 0.50 | same read-only `.git`: no commit possible in either arm; rerun on a machine where the sandbox allows git writes |

Earlier results (one run per arm, on earlier kit versions): `verifier-catches-bug` 1.00 with the
kit and 1.00 without (the planted bug is obvious enough that Claude catches it either way);
`picks-llm-skill` 1.00 and 1.00; `optimize-needs-evals` 0.00 in both arms until the skill
description said "with or without an eval suite ... never rewrite a prompt blind", then 1.00
with the kit and 0.00 without. A case that tells the arms apart needs a defect you only find by
running the code.
