# Reference

## `.claude/kit.json`

Committed with the project; `/kit:init` writes it from what the repo and its CI run.

```json
{
  "check": "fast gate (< ~30 s): lint + format check (+ types); runs before Claude stops if files changed",
  "verify": "full gate: tests, evals, build; what 'done' means for threads, /kit:go and kit:overnight",
  "checkTimeout": 540,
  "maxStopRetries": 3,
  "onEdit": [{"glob": "**/*.py", "run": "uv run ruff format -q \"$FILE\"", "timeout": 120}],
  "protect": [
    {"glob": "data/raw/**", "mode": "no-overwrite", "reason": "raw files are immutable"},
    {"glob": "vendor/**", "mode": "read-only", "reason": "vendored code"}
  ],
  "guard": {"protectedBranches": ["main", "master"], "agentsAsk": 15, "agentsDeny": 40, "allowCommands": [],
            "denyCommands": [{"pattern": "^npm install\\b", "reason": "pnpm only here"}], "askCommands": []},
  "llm": "on",
  "learn": {"model": true},
  "author": "Giovanni Giofré <99892523+giovannigiofre@users.noreply.github.com>",
  "lead": {
    "read": ["docs/backlog.md"],
    "backlog": "docs/backlog.md",
    "notes": "one line of project-specific advice for the coordinator",
    "board": ".claude/lead/board.md",
    "ship": "pr",
    "merge": "user",
    "parallel": 3,
    "budget": "none",
    "loops": [{"name": "babysit-prs", "every": "10m", "run": "/kit:go babysit"}]
  }
}
```

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
  the same.
- `guard`: on by default in a project with `kit.json`; `"off"` turns it off. `protectedBranches`
  defaults to main, master and the remote's default branch. `denyCommands` / `askCommands`: the
  project's own rules, `{"pattern": "<regex over the whole command>", "reason": "..."}` each
  (a plain string is a pattern); `/kit:learn` writes one when a lesson is "never run X here". `agentsAsk` / `agentsDeny` are an
  optional per-session cap on subagents (ask past one, refuse past the other); the native
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` caps how many run at once. `allowCommands`: regexes the
  guard lets through. `attribution` (default `"block"`): blocks AI credits in commit messages, PR,
  issue and comment text (git, `gh`, GitHub MCP tools) and commits under an AI git identity
  (name "Claude", an `anthropic.com` email); `"allow"` turns that rule off. Pair it with
  `"attribution": {"commit": "", "pr": "", "sessionUrl": false}` in `settings.json`, so Claude
  doesn't write the credits in the first place. `{"guard": "on"}` in `~/.claude/kit.json` guards projects without a
  `kit.json` too.
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
`.claude/skills/e2e/SKILL.md` (how to exercise the app), `.claude/review-decisions.md` (findings
you declined, so reviews don't raise them again). Gitignored: `.claude/evidence/`,
`.claude/overnight/`, `.claude/lead/`.

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
it in step 4. `.claude/evidence/` is added to `.git/info/exclude` when the project does not
ignore it. The Stop hook uses the same hash to know whether anything changed since its last
passing check.

## Edits made through the shell

In auto mode Claude is told to change files with `sed`, heredocs and short scripts rather than
the Edit tool, so a hook on `Write|Edit` never sees those edits. Before each Bash command in a
kit project the guard notes which files are modified or untracked and their mtimes; after it,
`bash_edits.py` (PostToolUse, matcher Bash) compares. A file the command changed gets the
`onEdit` commands for its glob, and a protected one is reported (read-only: any change;
no-overwrite: a change to a file that existed before) with the way to restore it; the hook
reverts nothing itself. A command that changed more than 40 files is reported, not checked.
Cost: one `git status` before and after each shell command.

## Permission prompts

`permission.py` (PermissionRequest, matcher Bash) allows, without a prompt, a command that is
exactly kit.json `check` or `verify`, or the kit's own `gate.py`, `lessons.py` or
`compact_logs.py` by their real path. Nothing else is touched: the guard has already judged the
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

**Capture** is deterministic and costs no tokens: a failed fast `check` (Stop), a guard denial,
and a kit:verifier FAIL (SubagentStop: each problem headline becomes a candidate). The verdict
is read from the verifier's report: its final message, else the SubagentHandback report in its
transcript. Verifier verdicts and revert commits are counted as events, for stats and the
distiller; a verdict is tied to the branch its brief names (else its report, else a PR number),
and a PASS confirms only the last FAIL on the same branch (with no branch named, it confirms
nothing). Each report counts once, so a verifier resumed with SendMessage records its next round
too. The same key seen again is counted, not added; a repeat after the lesson was delivered
counts as a miss. A new automatic lesson starts as a candidate and turns active on its second
sighting, at most 3 a day per repo. Text that looks like a key or token is refused.

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
`claude -p` or the SDK. Turn it off with `KIT_LEARN_MODEL=0` or `"learn": {"model": false}` in
kit.json.

**Promotion** (`promote.py`, run by the distiller): a lesson active in 2 repos becomes one machine
lesson (`M` ids) that every repo gets; the repo copies turn `promoted`, and undoing the machine
lesson gives them back for good. A machine lesson seen in 3 or more repos or about the kit, and
any `kit-defect` lesson, becomes a kit candidate, announced once. Only `/kit:learn promote <id>`,
run in an interactive session, prepares a claude-kit branch: the smallest generic change, a
regression test or eval that fails without it, the budget test, and `lessons.py scrub` on the
diff (no repo names, orgs, paths, env var names from the ledgers, or secrets). It opens the PR in
that session and never merges it. `lessons.py promoted <id> <version> <url>` then makes the lesson
retire itself once the PR is merged (checked with `gh`) and that kit version is installed.

```bash
python3 <kit>/hooks/scripts/lessons.py list [--all] [DIR]
python3 <kit>/hooks/scripts/lessons.py render implementer|verifier|lead [DIR]
python3 <kit>/hooks/scripts/lessons.py add pitfall KEY "one line" [DIR]
python3 <kit>/hooks/scripts/lessons.py retire L4 [DIR]
python3 <kit>/hooks/scripts/lessons.py undo L4 [DIR]
python3 <kit>/hooks/scripts/lessons.py stats [DIR]
python3 <kit>/hooks/scripts/lessons.py news [DIR]
python3 <kit>/hooks/scripts/lessons.py distill [--no-model] [DIR]
python3 <kit>/hooks/scripts/lessons.py promote [ID] [DIR]
python3 <kit>/hooks/scripts/lessons.py promoted ID VERSION PR_URL [DIR]
git diff origin/main... | python3 <kit>/hooks/scripts/lessons.py scrub -
```

## Modes and the status line

- **Light**: a normal session. `/kit:lead <work>` starts the coordinator when you want it.
- **Loop**: every message you type (terminal or Remote Control) gets one line of context sending
  it to the coordinator; headless runs, scheduled prompts and notifications never do. `/kit-mode
  loop|light`. Without a choice for the project, the personal default in
  `~/.claude/kit.json` (`{"mode": "light"}` or `"loop"`) applies, else loop in a project with
  `.claude/kit.json` and light elsewhere.
- **Board** (`.claude/lead/board.md`):

  ```
  SHIP: pr | PARALLEL: 3 | BUDGET: none
  RULES: <standing preferences you stated>
  NEEDS YOU: <id: question>; <id: question>
  <id> | <ship|scout|overnight> | <goal> | DONE WHEN <check> | <status> | agent <name> | <branch/PR> | <last event>
  ```

  Status: `queued`, `working`, `review`, `needs-you`, `landing`, `done`, `parked`. The status line
  counts the `review` items (`N ready`) and the NEEDS YOU questions (`N need you`), re-reading
  the board every 15 seconds, and the threads stopped on a question or a permission (`N
  waiting`, from the engine's agent list). When a tick finds more ready items or questions than
  the last one, the mod sends one native notification (`$.ui.notify`, Claude Code 2.1.295+;
  silently skipped where the engine lacks it).
- **Safety**: `/kit-safety host|sandbox`. Sandbox writes the kit's block into
  `.claude/settings.local.json`; check it with `/sandbox`, add hosts under
  `sandbox.network.allowedDomains`. Where the sandbox can't start, commands run unsandboxed with
  a warning rather than all failing.

The mod needs Claude Code with mods (2.1.287+). Without it, the skills and hooks still work; use
`/kit:lead` directly instead of loop mode.

## Overnight runner

```
python3 <kit>/skills/overnight/scripts/overnight.py "<objective>" --stop-when "<condition>" \
  --worktree ../app-overnight --max-iterations 40 --max-usd 25 --effort medium [--fallback-model sonnet] [--max-turns 60]
```

Each iteration runs `claude -p` in permission mode `auto` unless `--permission-mode` says
otherwise, with `--permission-prompts none` (a headless session cannot answer a prompt: anything
that would ask is denied at once; since Claude Code 2.1.302 `-p` would otherwise start in the
manual mode). A Fable or Mythos model bills usage credits without asking in `-p`, so the runner
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
python3 plugins/kit/hooks/tests/test_session_start.py
python3 plugins/kit/hooks/tests/test_subagent_start.py
python3 plugins/kit/hooks/tests/test_lessons.py
python3 plugins/kit/hooks/tests/test_machine_setup.py
python3 plugins/kit/hooks/tests/test_auto_mode_sync.py
python3 plugins/kit/skills/investigate/tests/test_compact_logs.py
python3 plugins/kit/skills/overnight/tests/test_overnight.py
python3 plugins/kit-llm/hooks/tests/test_llm_detect.py
claude plugin test plugins/kit               # the mod (modes, safety, status line) against the engine
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
