# A-code: review of the kit's hooks, scripts and mod (kit 1.9.0, main @ 776ac45)

Scope: `plugins/kit/hooks/scripts/*.py`, `kit.tsx`, `watchdog.ts`, `hooks.json`, `install.sh`,
`plugins/kit-llm/hooks/llm_detect.py` (kit-ui has no hooks). Read-only; nothing under the repo was edited.

Method: all 17 Python test files pass under both Python 3.13 and the real Python 3.9.25 on this box
(`compileall` clean under 3.9); `claude plugin test plugins/kit` passes 24/24 (mod + watchdog). Every hook's
output was checked against the hooks reference (fetched 2026-11-08): guard `permissionDecision: ask` /
exit 2, protect/on_edit/bash_edits exit 2, permission.py `hookSpecificOutput.decision.behavior`, stop_check
exit 2, subagent_stop top-level `decision: block` + `reason`, subagent_start/llm_detect
`hookSpecificOutput.additionalContext`, session_start plain stdout, session_end within the 60 s cap. All
conform. Probes ran in a scratch repo under
`(scratch)/a-probe/`
("repo with space", a worktree "wt 1", a 40k-tracked/20k-untracked "big" repo, an empty repo, a non-git folder).

Findings, ranked by value over cost.

---

## 1. A thread's REPORT.md gets its closing line, not its hand-back report — **high**

**Evidence.** `plugins/kit/hooks/scripts/subagent_stop.py:287-293`:
```python
report = data.get("last_assistant_message") or ""
...
brief, handed = from_transcript_any(data["agent_transcript_path"])
report = report or handed
```
The hooks reference says, for SubagentStop since 2.1.271: "a subagent that runs with the SubagentHandback
tool delivers its report through that tool before it stops. The `last_assistant_message` field then holds the
subagent's closing text, if any, which is not the delivered report." The implementer prompt
(`agents/implementer.md:11`) tells threads exactly that: hand back, then stop.

Probe (transcript with a `SubagentHandback` carrying a full `STATUS: done … DECISION: …` report, then the
closing text "Report delivered to the coordinator."):
```
REPORT.md  -> Report delivered to the coordinator.
LOG.md     -> ... | reported | no status line
```
With an empty `last_assistant_message` the same transcript files the real report (control). The verifier path
is correct because it tests `HAS_VERDICT` before preferring `last_assistant_message` (line 297); the
implementer path has the precedence backwards. `test_subagent_stop.py` has no case for `file_report` with a
hand-back, so the tests cannot catch it.

**Why it matters.** The items mailbox is what the coordinator and the owner read after a compaction or from
another session; the lead skill re-reads REPORT.md before re-briefing. Any thread that says one polite line
after its hand-back (most do) leaves a REPORT.md with no STATUS, no CHANGED, no DECISION lines, and the LOG
says "no status line".

**Change.** In `main()` for the implementer: `report = handed or report` (the hand-back wins when the
transcript has one), or mirror the verifier: keep `last_assistant_message` only when it matches
`^\W*STATUS:`. Add one test with a hand-back plus closing text. Cost **S**. Confidence **high**.

---

## 2. `kitlib.looks_secret` refuses any text holding a path with a digit — **medium**

**Evidence.** `kitlib.py:96` `OPAQUE = re.compile(r"[A-Za-z0-9+/_=-]{32,}")` and `looks_secret` (101-107): a
run of 32+ chars from that class that has a letter and a digit and no `word-word` is a secret. `/` and `_`
are in the class, so a path is one run. Probe:
```
True | The verifier failed a branch here for: src/api/v2/handlers/user_profile.py returns 500 on empty body
True | fix src/app/v2/routes/user_settings_handler.py
True | tests/integration/test_payment_flow_v2.py flaky
True | run migrations/0042_add_user_settings_table.py before verify
True | evidence sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```
Callers that silently drop on True: `lessons.observe` (338: returns None, so a verifier FAIL problem or a
gate failure naming such a file never becomes a lesson), `lessons.index_entries` (436, memory lines skipped),
`subagent_start.index_lines` (61), `proposals.clean` (110: the card is refused — any card whose evidence
cites a sha256 or a versioned path), `distill.usable` (a model rewording dropped), `promote.scrub`.

**Why it matters.** Django/FastAPI/Next.js repos are full of `v2/`, `0042_`, `_handler.py` paths; the
lesson ledger and the scout cards lose exactly the concrete lessons the kit exists to keep, with no message.

**Change.** Treat a run that contains `/` or `_` between lowercase words as a path, not a token: split the
candidate on `/` before testing, or exclude matches where `re.search(r"[a-z]{2,}[/_][a-z]{2,}", m)`. Keep the
sha256 case as is or allow 64-hex like the 40-hex SHA. Add the five strings above to `test_lessons.py`.
Cost **S**. Confidence **high**.

---

## 3. The bash-edits snapshot is shared by every thread of a session — **medium**

**Evidence.** `guard.py:1106-1113` saves `bash-snapshot` under `kitlib.state_path(session_id, …)`;
`bash_edits.py:42-45` loads and clears the same key. The hooks reference: "When a subagent calls a tool …
the input carries the `agent_id` and `agent_type`", and `session_id` is the session's. Two threads running
Bash in parallel (the kit's normal state: `lead.parallel` = 3) overwrite each other's before-image. Probe
(agents A and B, same session): A's guard snapshot, A writes `data/raw.txt` (protected `data/**`), B's guard
snapshot (now holds the file as pre-existing), A's bash_edits → exit 0, nothing reported; B's bash_edits →
nothing (snapshot already consumed). Control with A alone → exit 2 "kit protect: data/raw.txt matches
'data/**' (read-only)".

Also: the snapshot (`git status --porcelain -z -uall` + one `stat` per dirty file, 0.1-0.2 s on the 40k/20k
repo) runs on every Bash call in a kit project (`guard.py:1137`), while `bash_edits.py:39` returns at once
when the project has neither `protect` nor `onEdit`: the hot-path cost is paid for nothing in those projects.

**Why it matters.** Protected paths and onEdit formatters are the deterministic checks the design rule
leans on; threads in worktrees run inside the main session's git root? No — a worktree has its own root, so
the usual thread case is safe; but two threads in the *same* checkout (scouts, verifier runs, `cd <repo>`
briefs) and the main session itself race. Silent miss, no error.

**Change.** Key the state by `f"{session_id}.{agent_id or 'main'}"` in both scripts (one helper in kitlib,
e.g. `state_key(data)`), and take the snapshot only when `config.get("protect") or config.get("onEdit")`.
Cost **S**. Confidence **high**.

---

## 4. The attribution rule denies read-only `gh pr`/`gh issue`/`gh api` commands — **medium**

**Evidence.** `guard.py:767` `GH_WRITES = {"pr", "issue", "release", "api", "gist"}` and
`check_attribution` 802-805: any `gh <one of those> …` whose *command text* matches `AI_CREDIT` is denied.
Probe:
```
gh pr view 12 --json body -q .body | grep -i "generated with claude"   -> exit 2 (attribution)
gh issue list --search "Co-Authored-By: Claude"                         -> exit 2 (attribution)
git log --format=%B | grep -c "Co-Authored-By: Claude" || true          -> exit 0 (git is scoped to COMMIT_SUBS)
```
Likewise `git commit -m "docs: remove claude.ai/code/session_ links from README"` is denied (the message
*mentions* the pattern); that one is arguable and can stay.

**Why it matters.** The owner's rule is "no AI credit in what is published"; the natural way for the
verifier or `/kit:go` to *check* a PR for a leftover trailer is `gh pr view … | grep`, and the guard blocks
the check itself with the message "gh pr text credits an AI". Blocked whatever the permission mode.

**Change.** Scope `gh` like `git` is scoped: deny only writing subcommands (`pr|issue create|edit|comment|
review|merge|close|reopen`, `release|gist create|edit`, `api` with `-X/--method POST|PATCH|PUT`, `-f`, `-F`,
`--input`), and look at `message_files` plus the flag values (`-b/--body`, `-t/--title`, `-m`), not the
whole command text. Cost **S**. Confidence **high**.

---

## 5. The secrets rule denies handing a credential path to the tool that owns it — **medium/low**

**Evidence.** `guard.py:899-920` `check_secrets`: every non-flag word (and the part after `=`) that expands
into a `SECRET_PATHS` store denies, whatever the command. Probe:
```
ssh -i ~/.ssh/id_ed25519 deploy@host uptime            -> exit 2 (secrets: reads ~/.ssh)
kubectl --kubeconfig=~/.kube/config get pods           -> exit 2 (secrets: reads ~/.kube/config)
GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/adc.json python3 app.py -> exit 0 (assignment words are stripped)
```
The rule's intent (docstring line 28) is "reading credential stores … with Bash, Read, Grep or Glob". `ssh
-i`, `scp -i`, `rsync -e "ssh -i"`, `kubectl --kubeconfig`, `aws --profile` with `AWS_SHARED_CREDENTIALS_FILE`
are the tool using its own store, not Claude reading it; the inconsistency with the `NAME=path` form shows
the boundary was not meant to be there.

**Why it matters.** Deploy and cluster commands in `verify`/investigate work get a hard deny with "find a
safer way", and the only escape is a per-command `allowCommands` regex. This is a false positive of an
existing rule, not a new rule, so it stays within "the guard stays minimal".

**Change.** In `check_secrets`, skip the store when `argv[0]` is its owner: `ssh|scp|sftp|rsync|ssh-add|
ssh-keygen` for `~/.ssh`, `kubectl|helm` for `~/.kube`, `aws` for `~/.aws`, `gh` for `~/.config/gh`,
`docker` for `~/.docker`, `gcloud` for `~/.config/gcloud`, `gpg` for `~/.gnupg`. Cost **S**. Confidence
**high** on behaviour, **medium** on how often the owner hits it.

---

## 6. The missing-report nudge fires in projects without kit.json — **low**

**Evidence.** `subagent_stop.py:276-281` emits `{"decision": "block", …}` *before* `load_config(root)` is
consulted (282-285). Probe in `a-probe/nokit` (no `.claude/kit.json`, a transcript with the background
thread's RUN_START line and no hand-back): the block is printed. `kitlib.py:3-4` and README line 76 promise
"Every hook is a no-op unless the project has `.claude/kit.json`". The nudge only triggers for background
subagents (RUN_START gate), so the blast radius is one forced extra turn per such thread in non-kit projects;
the mod's follow-up wake is also unconditional (`kit.tsx:490-512`).

**Change.** Move the config check above the nudge, or state the exception in the kitlib docstring and the
README if it is wanted everywhere. Cost **S**. Confidence **high**.

---

## 7. `dirty_snapshot` parses `-z` output with the non-`-z` rename syntax — **low**

**Evidence.** `kitlib.py:198-205` asks `git status --porcelain=v1 -z` and then looks for `" -> "`. With `-z`
a rename is two NUL-separated entries (`R  new\0old\0`), so that branch is dead and the old name arrives as a
bare path that is cut at `entry[3:]` and dropped by the `OSError` (probe: `'R  src/api/v2/handlers/profile.py
\x00src/api/v2/handlers/user_profile.py\x00'` → `{'src/api/v2/handlers/profile.py': …}`). Harmless today
(the garbage path never stats), but a cut old-name that happens to exist would be reported as a changed file.

**Change.** After an `R`/`C` entry skip the next entry; delete the `" -> "` branch. Cost **S**. Confidence
**high**.

---

## 8. Two defaults for `checkTimeout`; `verifyTimeout` undocumented — **low**

**Evidence.** `stop_check.py:73` defaults `checkTimeout` to 540; `gate.py:128` defaults both
`checkTimeout` and `verifyTimeout` to 1800. `grep verifyTimeout README.md docs plugins/kit/skills` → nothing;
`docs/reference.md:11` documents only `checkTimeout: 540`. `/kit:init` cannot write a key nobody documents.

**Change.** One `GATE_TIMEOUTS = {"check": 540, "verify": 1800}` in kitlib used by both, and a line in
reference.md for `verifyTimeout`. Cost **S**. Confidence **high**.

---

## 9. `wakeTurn` is set when the wake is scheduled, not when its turn starts — **low**

**Evidence.** `kit.tsx:333-340` `wake()` sets `wakeTurn = true` inside `$.clock.after(0, …)` and then
submits the prompt; `turn.complete` (548-555) clears it for *any* main turn. When a wake lands while the main
session is mid-turn (the coordinator answering, a `/loop` tick), the prompt queues, the *current* turn's tool
calls are ignored by `noteActivity('main')`, that turn's completion clears the flag, and the wake's own turn
then counts as real activity: `job:main` strikes reset and the 2x/4x reminders for a forgotten main-session
background command may never come. `kit.test.tsx:321-341` covers only the idle case. Not probed against the
engine (reasoned from the code), so medium confidence.

**Change.** Remember the wake's text and flip `wakeTurn` in the `prompt.submit` handler when `e.text` is
that text (or on the engine's turn-start event if one exists), not in the timer. Cost **S/M**. Confidence
**medium**.

---

## 10. Duplication that belongs in kitlib, and parameters nobody passes — **low**

- `git()` in `guard.py:532` and `auto_mode_sync.py:127` duplicate `kitlib.git_out` (different timeouts 10/5
  vs 30; guard's could take `timeout=`).
- `ensure_excluded` in `gate.py:83` and `items.py:57` are the same function with a different line.
- `slug` (`subagent_start.py:48`) = `cc_slug` (`lessons.py:164`); `index_lines` (`subagent_start.py:53`)
  reimplements `lessons.index_entries`; `main_checkout` (`subagent_start.py:36`) reimplements
  `auto_mode_sync.identify`'s common-dir logic.
- `is_ai` in `session_start.py:82` is a second, shorter copy of `guard.is_ai_identity` (lacks
  `claude-code`); `temp_roots()` exists in both `guard.py:301` and `lessons.py:108`; `config_dir()` in
  `auto_mode_sync.py:77` and `kitlib.py:77`.
- `gate.status(branch=, head_ref=, exclude=)` (gate.py:153): only `test_gate.py:90` passes them; the CLI
  cannot. `items.list_items(archived=)`, `lessons.render(header=)` and `items.STATUSES` are never used.
- `lessons.repo()` runs three git subprocesses and is called about five times per SessionStart (capture,
  harvest, take_news, review_due, deliver) and twice per SubagentStart; a per-process `lru_cache` on
  `auto_mode_sync.identify` would remove ~10 subprocesses per session start.

Cost **M** overall, each item S. Confidence **high** (grep).

---

## Hot-path cost (measured, Linux tmpfs, 40 001 tracked + 20 000 untracked files, index 3.1 MB)

| Hook | What runs | Time |
|---|---|---|
| guard.py on a Bash call (kit project) | python start + `git rev-parse` + `git status -z -uall` + stat per dirty file (≤5000) + the shell parser | 0.18 s |
| guard.py on Read/Grep/Glob | python start + `git rev-parse` + two JSON reads | 0.07 s |
| bash_edits.py (protect/onEdit set) | the same `git status` again + `git ls-files` per changed file (≤40) | ~0.15 s |
| stop_check.py | `gate.tree_hash` (copy of the index + `git add -A` into a scratch index + `write-tree`), `changed_env` (merge-base, diff, ls-files) | 0.4-0.7 s per Stop; `check` only when the tree changed |
| session_start.py | ~15 git subprocesses (see 10), two ledger locks (≤1 s wait) | well under its 20 s |
| kit.tsx tick | `$.agent.list()` twice, 4-5 file reads, `git worktree list` subprocess (`liveOvernightRuns`) | every 15 s, forever |

All bounded: `dirty_snapshot` caps at 5000 stats, `changed_files` at 400, every git call has a timeout, and
hooks.json sets explicit timeouts. Two notes: (a) a guard that times out (15 s) lets the command through
(hooks reference: a timed-out PreToolUse hook "doesn't block the tool call"), which is consistent with the
owner's no-fail-closed decision, but means the guard silently stops guarding on a repo where `git status
-uall` is slow (a huge unignored build tree): finding 3's gating removes that call from projects that do not
need it; (b) `liveOvernightRuns` spawns a git process every 15 s for a value that changes once a night; a
60 s cache would do.

## Robustness checks that passed (probed)

Repo with no commits (stop_check, `gate check`, `gate status` → `no-branch`, session_start), detached HEAD
(`detached-<sha>` record path), a linked worktree with a space in its path (subagent_start names the main
checkout and the right gate), a non-git cwd (guard allows `rm -rf ./x`, project_root falls back), paths with
spaces through `git -C`, the wait rule (sleep 90 denied; `timeout 300 npm test`, `while read`, `npm run dev
& sleep 5` pass), the gate's evidence file does not change the Stop fingerprint (`.git/info/exclude` gets
`/.claude/evidence/`), concurrent `items.py new` on the same slug (no collision in three parallel runs).
Python 3.9: all tests and `compileall` pass on 3.9.25; no `match`, PEP 604 unions, PEP 585 generics in
evaluated positions, or PEP 701 f-strings. macOS: `install.sh` is POSIX `sh` (`grep -A2`, `read -r`,
`printf`), no `sed -i`, `date -d` or `realpath` anywhere; `fcntl` is imported lazily; `/private/tmp` and
`/var/folders` are in both temp-root lists.

## What is solid

The shell parser in guard.py (quote mask, heredocs, `$(…)`, `sh -c`, brace expansion, `cd` tracking,
resolved symlinks) is far better than the usual regex guard and is well tested; its crash path degrades to
"ask", never to "allow". The ledger's write discipline (flock with a bounded wait, `mkstemp` + `os.replace`,
before-images for undo, caps on every append-only file, `once_per` dedup) is careful, and the daily caps and
headless checks keep the model pass from ever costing the owner money unattended. Every hook's JSON output
and exit code matches the current hooks reference, every subprocess has a timeout, hooks.json sets explicit
timeouts, and the tests (17 Python files, 24 engine tests) run in under a minute with no tokens. The evidence
record (`tree_hash` through a scratch index) is a genuinely good idea and it handles the no-commit, detached
and worktree cases.
