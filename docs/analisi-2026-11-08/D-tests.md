# D. Test and evaluation coverage of claude-kit 1.9.0

Read-only assessment of `/home/user/claude-kit` at `776ac45` (main, 2026-11-08). Everything below
was measured on this machine; scratch files are under
`(scratch)/d-probe/`
(`coverage.txt`, `merges/summary.txt`, `merges/summary2.txt`, `modtest-*.log`, the tracer).

## 1. Summary

- Everything green today: budget, 16 Python self-checks, 24 mod tests, `plugin validate`, under
  Python 3.13.17 **and** 3.9.25 (the floor the README promises; nothing enforces it).
- Measured line coverage of the hook scripts by running the self-checks under a stdlib tracer that
  follows the subprocesses: **85.8 %** overall (4,111 of 4,792 executable lines), but the main
  entry points of three hooks never run in any test: `protect.py` 37 % (the PreToolUse protect
  hook's `main()` is not executed), `on_edit.py` 46 % (same), `session_end.py` 4.5 % (no test at
  all). The `--missing` contract between `kit.tsx` and `subagent_stop.py` is mocked on both sides.
- One mod test is flaky: `kit.test.tsx:321` runs 1,920 watchdog ticks and takes 4.2-5.0 s against
  the kit's 5,000 ms per-test timeout; over 16 runs here it timed out 5 times (`timed out after
  5000 ms`), including 1 of 3 runs on an otherwise idle machine, and once on a replayed merge.
- The eight eval cases cover eight flows; none covers ask mode, `/kit:handoff`, `/kit:scout`,
  the implementer's DECISION lines and gate use, fresh-eyes, `items.py` by the lead, or effort per
  thread. Six cases are drafted below in the documented format, plus five graders to add to an
  existing case at no extra run cost.
- Replaying the proposed CI on the last ten merge commits: see §6.3 (table filled from the replay).
- A minimal GitHub Actions workflow costs about 4-5 billed minutes per run (about 2 min wall) and
  needs no credentials: `claude plugin test` and `plugin validate` both run with an empty HOME.

## 2. Timings (one run each, this machine, 2 vCPU container)

| Check | Python 3.13.17 | Python 3.9.25 (uv) | Notes |
|---|---:|---:|---|
| `tests/test_budget.py` | 0.07 s | 0.1 s | kit 2531/2600 always-on chars (97 %), kit-llm 969/1200, kit-ui 987/1200 |
| `hooks/tests/test_auto_mode_sync.py` | 0.80 s | 0.9 s | |
| `hooks/tests/test_bash_edits.py` | 1.11 s | 1.1 s | prints a stray `hi` (test_bash_edits.py:64 runs `echo hi` unredirected) |
| `hooks/tests/test_gate.py` | 1.12 s | 1.2 s | |
| `hooks/tests/test_guard.py` | 14.31 s | 14.2 s | ~190 subprocess launches of guard.py; 35 % of the Python wall time |
| `hooks/tests/test_items.py` | 0.63 s | 0.6 s | |
| `hooks/tests/test_lessons.py` | 4.29 s | 4.8 s | 10 sub-tests, shared global state |
| `hooks/tests/test_machine_setup.py` | 0.39 s | 0.3 s | |
| `hooks/tests/test_permission.py` | 0.61 s | 0.6 s | |
| `hooks/tests/test_proposals.py` | 0.62 s | 0.6 s | |
| `hooks/tests/test_session_start.py` | 1.49 s | 1.5 s | |
| `hooks/tests/test_stop_check.py` | 0.75 s | 0.8 s | |
| `hooks/tests/test_subagent_start.py` | 0.70 s | 0.8 s | |
| `hooks/tests/test_subagent_stop.py` | 0.48 s | 0.5 s | |
| `skills/investigate/tests/test_compact_logs.py` | 0.42 s | 0.4 s | |
| `skills/overnight/tests/test_overnight.py` | 11.19 s | 11.2 s | 21 sub-tests, fake agent |
| `kit-llm/hooks/tests/test_llm_detect.py` | 1.51 s | 1.3 s | |
| **Python total** | **~40.5 s** | **~41 s** | all exit 0 |
| `claude plugin test plugins/kit` | 7.84 s | | 24 tests, 2 files; one test 4.7 s (see §4.1) |
| `claude plugin validate plugins/kit` | 0.90 s | | passes; the directory profile would refuse (no LICENSE), and warns: no icon |

Python 3.9 was installed with `uv python install 3.9` (1.9 s download) and every script also
passes `py_compile` under it. No test reaches the network: `claude` is replaced by a fake script
(test_lessons.py:271-275, 318-321), `promote.merged` is monkeypatched (test_lessons.py:384, 387).

## 3. Findings ranked by value over cost

Value: what breaks for the owner if the untested thing regresses. Cost: S under an hour, M an
afternoon, L a day or more.

| # | Finding | Evidence | Proposed change | Cost |
|---|---|---|---|---|
| 1 | The PreToolUse **protect** hook's entry point is never executed by a test: payload parsing (`file_path`/`notebook_path`), `relpath` outside the root, the exit-2 message, the broken-config branch. Only `violation()` is reached, from `bash_edits`. A regression here silently removes the "protected paths" promise (README:77). | `protect.py:27-52` all unhit (coverage.txt: 37.5 %); `test_bash_edits.py` imports `protect` only indirectly | New `tests/test_protect.py`: feed Write/Edit/NotebookEdit payloads for a read-only glob, a no-overwrite glob on an existing and on a new file, a path outside the repo, no kit.json, broken kit.json; assert exit 2 and the message | S |
| 2 | The PostToolUse **on_edit** hook's entry point is never executed: missing file → 0, broken config → exit 2, failure message. Same silent-loss risk for the formatter loop. | `on_edit.py:16-36` unhit (46 %) | Add to the same new test file: an `onEdit` rule that fails on a TODO, one that passes, a non-existent `file_path`, broken kit.json | S |
| 3 | `session_end.py` has no test and `distill.pending()`/`spawn()` are unhit: the "distiller runs after 5 events" promise (README:97) is unverified end to end. | `session_end.py` 4.5 %; `distill.py:462-478` unhit | Test: write 5 events into a temp ledger, run `session_end.py`, assert a detached `distill.py` was started (replace `sys.executable` via `PATH`, or assert `distilled_ts` in `_repos.json` after a short wait) | S |
| 4 | **Flaky mod test**: 1,920 ticks in a loop take 4.2-5.0 s against the 5 s per-test cap; 16 measured durations here: 4188, 4590, 4595, 4602, 4668, 4723, 4736, 4757, 4791, 4885, 4892, 5004, 5004, 5004, 5006, 5010 ms, so 5 of 16 timed out (1 of 3 on an idle machine). In CI this fails roughly one run in three and will train the owner to re-run. | `kit.test.tsx:321-341` (`for (let i = 0; i < 8 * 60; i++) await clock.advance(60_000)`), `modtest-idle-1.log`, `modtest-home-1.log`, `merges/8bc9db9.modtest.log`: `timed out after 5000 ms` | Give the world a kit.json `{"watchdog": {"bashDeadlineMin": 2, "silentMin": 1}}` so the scenario is 8 minutes, not 8 hours (≈ 40 ticks); the three wakes and one notification are the same assertions | S |
| 5 | `subagent_stop.py --missing` (the exit-code contract `kit.tsx` calls through `$.process.run`) is mocked in the mod test and has no Python test: both halves pass with the real thing never run. | `kit.tsx:500-501`; `kit.test.tsx:277` (`argv.includes('--missing') ? missing : 0`); `subagent_stop.py:274-275` unhit | In `test_subagent_stop.py`, run `subagent_stop.py --missing <path>` on the `resumed` and `run1` transcripts already built there and assert exit 1 / 0 | S |
| 6 | **kit.json has no schema check**: a typo (`"cheque"`, `"protcet"`, `"lead": {"baord": ...}`) silently turns a gate off; every hook does `config.get(...)`. The README promises "deterministic checks". | `kitlib.py:66-74` (parses only), `session_start.py:141-187` (lists what it finds, warns on nothing unknown) | `session_start.py`: print one line for unknown top-level or `lead`/`guard` keys and wrong types (`check` not a string, `protect` not a list) using the schema already in `skills/init/SKILL.md:100-111`; test it | S |
| 7 | Lenient assertions that pass either way: the "one native notification" promise is not asserted; a `or` accepts both branches; the "already an item" dedupe branch is never pinned. | `kit.test.tsx:212-217` (`toBeLessThanOrEqual(1)` + `if (notices.length)`); `test_bash_edits.py:86` (`code == 0 or "src/app.py" in err`); `test_proposals.py:82` (`"duplicate" in out or "already an item" in out`); `proposals.py:141-143` unhit | Pin each: expect exactly one notice with the text; split the bash_edits case into the two orders; add a card whose summary is already an item's BRIEF and assert `already an item` | S |
| 8 | **CLI surfaces the skills tell Claude to run are untested**: `items.py report|verdict <id> -` and `items.py new` without a name; `proposals.py show`, non-JSON input; `lessons.py list|render|add|import|news|stats|promote|promoted|scrub` dispatch; `auto_mode_sync.py --preview|--show` (what `/kit:init` step 12 runs). | `items.py:243-244, 264-266, 286-287`; `proposals.py:218-220, 259-267`; `lessons.py:787-860`; `promote.py:363-395`; `auto_mode_sync.py:356-366` all unhit | One `test_cli.py` (or cases in the existing files) that runs each command once against the fixtures already built and asserts exit code + first line. These are the owner's own commands; a broken one shows up as a confused Claude, not an error | M |
| 9 | Gate record edge cases unhit: `--timeout` parsing, detached HEAD naming, a repo with no index/HEAD, the record that cannot be written, `status check` (only `status` → verify tested). The record is the PR's evidence. | `gate.py:39-40, 52, 61-63, 144-145, 178, 196, 204-212` | Extend `test_gate.py`: `--timeout x` → exit 3, `--timeout 5` ok; `git checkout --detach` → `detached-<sha>`; fresh `git init` with no commit; `status check` | S |
| 10 | Guard rules never exercised: `gh run watch` in the foreground, fork bomb, `> /dev/sdX`, `mkfs`/`shutdown`/`diskutil erase`, keychain words in `python -c`, `find -regex`, BSD `find -f`, `sleep inf`/`sleep $DELAY`, an invalid `allowCommands` regex, the **crash-to-ask safety net**. | `guard.py:1086, 933-938, 860-863, 695, 626-634, 644, 1017-1019, 1029-1030, 1156-1157` unhit | Add rows to `CASES`/`MORE` in `test_guard.py`; for the safety net, feed a payload whose `tool_input.command` is not a string and assert `permissionDecision: ask` | S |
| 11 | Lessons ledger upkeep paths unhit: `idle()` actually retiring (only the dry run and the empty case ran), the automatic "brought back" of a retired lesson seen again, the lock-busy path, `scan_reverts`, `cap_rows`, the model `merge` op, `harmful >= 2`, the preview-failure line. | `lessons.py:365-367, 215-218, 502-503, 279-281, 684-688, 734-736`; `distill.py:146, 161, 387-395, 413-414` | Extend `test_lessons.py::test_distill/test_upkeep`: a 91-day-old lesson through `review` (not dry run); a retired (not by hand) lesson observed again → status active + news line; a fake `claude` answering a `merge` op; hold the lock in a thread and assert `Busy` | M |
| 12 | `subagent_start`'s fallback trimming (`compose_within`) and the "no gate names" line are unhit: a repo with memories but no ledger and a long index could exceed the 2,400-char budget the budget test protects. | `subagent_start.py:151-156, 139` | In `test_subagent_start.py`, make the fallback text longer than `MAX_CHARS - len(gate)` and assert the output stays within `MAX_CHARS` | S |
| 13 | Tests leak and share machine state: fixtures under the real `~` (needed, since `/tmp` is an allowed delete target) and `mkdtemp` dirs never removed; state files pile up in `$TMPDIR/claude-kit` with nothing pruning them (200+ `*.main.llm.json` here). | `test_guard.py:21-22`; `test_lessons.py:19`, `test_auto_mode_sync.py:19`, `test_session_start.py:17`, `test_machine_setup.py:26-59`; `kitlib.py:233-250`; `plugins/kit-llm/hooks/llm_detect.py` | `atexit.register(shutil.rmtree, ...)` in the four tests; in `kitlib.state_path`, drop files older than 7 days once per run (cheap `scandir`) | S |
| 14 | Order-dependent monolith: `test_lessons.py` runs 10 sub-tests on one shared `TMP`/env; `test_promotion` monkeypatches `promote.merged` and never restores it, so `test_upkeep` runs with the patch. A new sub-test inserted earlier changes later results. | `test_lessons.py:384-387, 464-467` | Restore patched attributes in `finally`; or give each sub-test its own `CLAUDE_CONFIG_DIR` | S |
| 15 | Date dependence: `lessons.today()` is the local date while `items.now()` is UTC; the "3 activations a day" assertion and `test_upkeep` straddle midnight. Rare, but the hook already supports `KIT_LESSONS_TODAY`. | `lessons.py:89-90`, `items.py:88-89`, `test_lessons.py:134, 440` | Set `KIT_LESSONS_TODAY` in the test env | S |
| 16 | `run_shell` timeout path (exit 124, the `checkTimeout` promise) and `dirty_snapshot` rename/limit are unhit. | `kitlib.py:224-225, 205-211` | `test_stop_check.py`: `check: sleep 5`, `checkTimeout: 1` → exit 2 with `timed out`; a `git mv` before the snapshot | S |
| 17 | No single command runs the suite; 16 files are run one by one and nothing runs in CI. | no `.github/`, no `Makefile`/`tests/run.sh` | `tests/run.sh` (loop, non-zero on any failure) and the workflow in §6 | S |
| 18 | Eval suite is not runnable as committed without knowing the flags: every case needs `--scaffold`; six cases list `Bash`/`Write`/`Edit` in `allowed_tools`, which the docs say are removed unless granted with `--allow-tools`; all cases set `runs: 1` (the docs recommend 3 and default to it). | `evals/*/prompt.md` (`runs: 1`, `allowed_tools: [... Bash, Edit, Write ...]`), `evals/*/case.yaml` (`scaffold_script`) | Record the command in the README or a `evals/README.md`: `claude plugin eval plugins/kit --scaffold --trust-plugin --allow-tools Bash Write Edit --ablation none --no-publish`; raise `runs` to 3 for the two lead cases | S |
| 19 | `lead-dispatches-threads` asserts the board through `tool_used: Write` only; a lead that writes `board.md` with a Bash heredoc (Bash is allowed there) scores a false FAIL; and nothing in any case checks the 1.5+ items contract (`items.py new`, `ITEM:` in the brief, `log working`) or the 1.6/1.9 effort contract. | `evals/lead-dispatches-threads/graders/board.md`; `skills/lead/SKILL.md:36-45, 96-99` | Replace the grader with a `regex` on `target: trace` and add the five graders in §5.3 (no new runs) | S |
| 20 | Important flows with no eval: ask mode read-only, `/kit:handoff`, `/kit:scout`, implementer DECISION + gate, fresh-eyes. Three of them shipped in the last two weeks (1.5, 1.6/1.9). | `evals/` has 8 cases; `kit.tsx:53-57` (ask), `skills/handoff`, `skills/scout`, `agents/implementer.md:53-64`, `skills/lead/fresh-eyes.md` | The six drafted cases in §5.3 | M |

## 4. Coverage of the scripts

### 4.1 Line coverage (stdlib tracer following subprocesses; `d-probe/coverage.txt`)

| Script | Exec lines | Hit | Cov % | Notable unhit lines |
|---|---:|---:|---:|---|
| `guard.py` | 922 | 822 | 89.1 | 626-634, 644, 695, 860-863, 933-938, 1017-1019, 1029-1030, 1086, 1095, 1113-1114, 1127-1128, 1152-1157 |
| `lessons.py` | 635 | 546 | 85.8 | 215-218, 279-281, 365-367, 502-503, 684-688, 734-736, 771-782, 787-860 |
| `overnight.py` (skill) | 373 | 328 | 87.7 | 142-150, 408-410, 475-484 |
| `distill.py` | 332 | 288 | 86.5 | 146, 161, 217, 271, 387-395, 413-414, 434-435, 464-478, 486-490 |
| `promote.py` | 294 | 237 | 80.3 | 168-172 (`attach`), 263-270 (`merged`), 363-395 (CLI) |
| `auto_mode_sync.py` | 287 | 234 | 81.2 | 99-102, 255-256, 276-291, 295, 304, 324-331, 356-366, 380-387 |
| `compact_logs.py` (skill) | 275 | 259 | 93.8 | 80-88, 141-142 |
| `subagent_stop.py` | 243 | 220 | 90.2 | 139-140, 206-209, 223, 269-270, 275, 301 |
| `items.py` | 218 | 187 | 85.4 | 169-174, 185, 191, 243-244, 264-266, 286-287 |
| `proposals.py` | 218 | 187 | 85.4 | 107-109, 142-148, 193-194, 218-220, 259-267 |
| `session_start.py` | 169 | 158 | 92.9 | 118-119, 164-166, 178, 200-201 |
| `kitlib.py` | 168 | 144 | 85.2 | 34-35, 50-51, 137-140, 205-211, 224-225 |
| `gate.py` | 164 | 135 | 81.8 | 39-40, 52, 61-63, 70-71, 144-145, 178, 204-212 |
| `subagent_start.py` | 129 | 112 | 86.2 | 136-139, 151-156, 173-180 |
| `machine_setup.py` | 81 | 79 | 96.3 | 99-100 |
| `stop_check.py` | 68 | 56 | 81.2 | 32-38, 54-55, 63-66 |
| `bash_edits.py` | 52 | 46 | 86.8 | 33, 37-38, 51-53 |
| `permission.py` | 43 | 38 | 86.4 | 29-30, 36-37, 50 |
| `on_edit.py` | 40 | 19 | **46.3** | 17-36 (`main`) |
| `protect.py` | 39 | 15 | **37.5** | 28-52 (`main`) |
| `session_end.py` | 21 | 1 | **4.5** | everything |
| **Total** | **4,792** | **4,111** | **85.8** | |

Method: `sitecustomize.py` on `PYTHONPATH` installs a `sys.settrace` line counter for files under
`plugins/kit` in every Python process (the hook scripts the tests launch with `subprocess`), pickles
counts per pid, `merge.py` combines them against `trace._find_executable_linenos`. Lines inside
`except` handlers that never fire count as unhit, which is right: those are the paths that matter in
a hook.

### 4.2 Behaviours per script (yes = a test asserts it; risk = what the owner loses if it breaks)

**stop_check.py** (Stop: run `check` before Claude stops)

| Behaviour | Tested | Risk if broken |
|---|---|---|
| no kit.json → silent | yes (via other tests) | — |
| kit.json without `check` → silent (`:66`) | no | low |
| broken kit.json → message, exit 0 (`:63-64`) | no | a broken config silently disables the gate |
| fingerprint through `gate.tree_hash`; unchanged tree skips the check | yes | check runs every turn (cost) or never (quality) |
| fallback fingerprint when git index trick fails (`:32-38`) | no | same, on odd repos |
| `KIT_CHANGED_FILES`/`COUNT` reach the check; clean main → 0 | yes | diff-aware checks see nothing |
| failure → exit 2 with `attempt n/limit` and the tail | yes | Claude stops with a red check |
| `maxStopRetries` reached → let it stop, fresh count | yes | a check Claude cannot fix traps the session |
| per-session counters (`s1` vs `s2`) | yes | |
| failure recorded in the ledger once per session | yes (test_lessons.py:120-124) | |
| `checkTimeout` → exit 124 handled (`kitlib.py:224-225`) | no | a hung check blocks the stop for 540 s |

**gate.py** (`verify`/`check` with a record; `status`)

| Behaviour | Tested | Risk |
|---|---|---|
| run, print tail, write `.claude/evidence/<branch>/gate-<name>.json` with tree hash, head, changed files | yes | PR evidence wrong |
| `status`: no record / failed run / dirty tree names files / another tree / ready / by `head_ref` | yes | stale evidence accepted by `/kit:go` |
| evidence folder added to `.git/info/exclude` | yes | evidence committed |
| gate that changes the tree → note | yes | |
| unknown gate → 3; missing command → 3 | yes | |
| `--timeout N` and a bad `--timeout` (`:206-212`) | no | medium |
| detached HEAD → `detached-<sha>` (`:39-40`) | no | records land under `HEAD` |
| repo without index or HEAD (`:52, 61-63`) | no | overnight's first iteration |
| record not writable (`:144-145`); `status` cannot hash (`:178`) | no | low |
| `status check` (name argument) | no | low |

**items.py** (the coordinator's items on disk)

| Behaviour | Tested | Risk |
|---|---|---|
| `new`: slug, `-2` suffix, `ITEM:`/`KIND:` header, first LOG line, `/.claude/lead/` excluded | yes | threads' reports file nowhere |
| `find_id` case-insensitive, absent | yes | |
| `list`, `--status`, `log`, `show`, `path` (missing → 1) | yes | |
| `done`: LOG, board row to `archive.md`, folder moved | yes | board grows past its contract |
| `done` when the archive target exists → `rmtree` then move (`:191`) | no | **deletes a previous archive silently** |
| `report`/`verdict` **from the CLI** (`:264-266`) | no | the lead's manual filing path |
| `new` without a name → 2; unknown command → 2 | no | low |
| `lead.board` custom path moves the items dir too | no | items written to the wrong folder |
| `archive_row` with no board / no row (`:169-174`) | no | low |

**proposals.py** (scout cards)

| Behaviour | Tested | Risk |
|---|---|---|
| `add`: validation (origin, summary, class), secret refusal, fingerprint dedupe, same-run dedupe, per-class count | yes | duplicate or leaking cards |
| `list --class`, `take` (brief with DONE WHEN, card retired, re-scan skipped, second take fails) | yes | |
| `retire` by age and by missing origin | yes | |
| "already an item" skip (`:141-143`) | not pinned (test accepts either reason) | cards for work already queued |
| id collision suffix (`:147-148`); summary truncation; bad confidence (`:107-109`) | no | low |
| `show` (`:259-267`); non-JSON input → 2 (`:218-220`) | no | `/kit:scout` cannot show a card |

**subagent_stop.py** (SubagentStop: missing-report nudge, filing, verdict capture)

| Behaviour | Tested | Risk |
|---|---|---|
| delivered report → stop; refused second hand-back → block once; `stop_hook_active` → silent; SendMessage to main counts; foreground subagent; waiting on own child; interrupted by the person | yes (test_subagent_stop.py) | lost thread reports / nudge loops |
| REPORT.md / VERDICT.md filed under the item, LOG notes (`done, 1 decision(s)`, `FAIL scope=...`); brief without `ITEM:` files nothing | yes (test_items.py) | the mailbox |
| verdict parsing (sections, bullets, sub-headings, numbered details, informational notes) | yes (test_lessons.py:189-206) | wrong lessons |
| FAIL → candidate lessons; PASS confirms only the same branch; resumed verifier | yes | |
| `--missing <transcript>` CLI exit code (`:274-275`) | no (mocked in kit.test.tsx:277) | the watchdog's wake never fires |
| final text holding `VERDICT:` when no hand-back (`:206-209`); PR-number scope (`:223`); unreadable transcript (`:139-140`) | no | medium |

**permission.py** (PermissionRequest: gate commands without a prompt)

| Behaviour | Tested | Risk |
|---|---|---|
| exact `check`/`verify` (with whitespace) → allow; compound/redirected → prompt; `rm -rf /` → prompt | yes | a shell injection through the allowlist |
| own scripts by real path (`gate.py status`); a `gate.py` elsewhere → prompt; `machine_setup.py` → prompt | yes | |
| no kit.json → prompt | yes | |
| non-Bash tool (`:50`), unparsable command (`:29-30`), nonexistent script path (`:36-37`) | no | low |

**protect.py** (PreToolUse: protected paths) — `violation()` is tested through bash_edits
(read-only, no-overwrite on existing and new); **the hook itself (`main`, `:27-52`) is never run**:
payload keys, `notebook_path`, a path outside the root, the exit-2 text, broken kit.json → 0.
Risk: high; this is the only guard for Edit/Write on protected paths.

**on_edit.py** (PostToolUse: formatters) — `run_rules()` tested through bash_edits (glob match,
`$FILE`/`$REL`, failure text); **`main` (`:16-36`) never run**: missing file → 0, broken kit.json
→ exit 2, failures message. Risk: high for the same reason.

**bash_edits.py** — snapshot compare, sed edit runs onEdit, failing onEdit → 2, no-overwrite and
read-only through a shell, new file under no-overwrite ok, no snapshot → silent, no kit.json →
silent: yes. Unhit: `> MAX_FILES` report (`:51-53`), broken kit.json (`:37-38`), non-Bash tool.

**session_start.py** — silent without kit.json; board only after `compact`; rows first, RULES cut,
oversize warning; gates/protect/notes lines; `lead.board`; author set when AI or missing, left when
human, invalid ignored; machine-setup offer / headless / compact / applied; update notice once per
session; broken kit.json reported; lessons delivered to `lead`: all yes. Unhit: onEdit globs line
(`:178`), unparsable version (`:118-119`), the two `except` lines (`:164-166, 200-201`).

**subagent_start.py** — nothing without kit.json or with `{}`; gate line, `verify` over `check`;
ledger delivery with budget, ranking, verifier excludes its own memory; fallback indexes (feedback
only, secrets dropped, oldest pitfalls cut, cut note); worktree → main checkout; repo named: yes.
Unhit: `compose_within` trimming (`:151-156`), no gate names (`:139`), the `except` lines.

**guard.py** — 37 allow/block cases + 54 verdict cases + waits (20) + attribution (14) + symlinks,
worktrees, other repos, Read/Grep/Glob, allowCommands, protectedBranches, off switch, user-level
on, agent cap, project deny/ask rules: yes. Unhit rules listed in finding 10; the most valuable are
`gh run watch` (`:1086`), the `> /dev/sd*` and fork-bomb lines (`:933-938`), `mkfs`/`shutdown`
(`:860-863`) and the crash-to-ask net (`:1156-1157`).

**lessons.py / distill.py / promote.py** — see findings 8, 11; the automatic capture → candidate →
active → delivered → miss → harden chain, import, promotion with a judge, scrub, prune, review on a
copy, model pass with a fake `claude` are all asserted. Unhit: the CLI (`lessons.py:787-860`,
`promote.py:363-395`), `idle()` retiring for real, lock-busy, `scan_reverts`, `attach`, the model
`merge` op, `pending`/`spawn`.

**auto_mode_sync.py** — set/rebuild scoped lines, user lines kept, idempotent, repo files never
read, hostile origin refused, remove, deleted block cleaned, non-list left alone, 8 parallel
writers: yes. Unhit: `--preview`/`--show` (`:356-366`), read-only settings (`:291`), invalid
settings (`:276-279`), bad block warnings (`:255-256`), `read_lines` refusals (`:324-331`).

**machine_setup.py** — 96 %; only `--decline` on a broken kit.json unhit.

**session_end.py** — untested (finding 3).

**kit.tsx / watchdog.ts** (mod) — mode light/loop/ask with the context lines, off-once, personal
defaults, headless origins, sandbox write/remove/leave-alone/broken JSON, status line, board
notification, pane cleanup, silence watchdog (20/40/80 min), Monitor deadline, nudge → wake,
API failure retry/notify, wake turn not activity, answered permission not a prompt: yes.
`watchdog.ts` pure functions: 6 tests. Not covered: `kit-mode` with no argument (the status
reply), `kit-safety` with no argument, `liveOvernightRuns` counting (`fs.list` is always denied in
the world), the `(server)` label exemption through the full module (unit-tested in watchdog.test.ts
only), `expectedMs` parsing (`EXPECT: 2h`).

## 5. Evals

### 5.1 Map of the eight cases

| Case | Flow it protects | Graders (type) | Fixture | Runs |
|---|---|---|---|---|
| `lead-dispatches-threads` | lead dispatches threads | `tool_used Write board.md`; `tool_used Agent implementer`; `llm` (3 items, ≤2 parallel, short replies) | calc.py with buggy `add` | 1 |
| `lead-verifies-before-done` | lead verifies before done | `tool_used Skill lead`; `tool_used Agent implementer`; `llm` (done-criterion + evidence) | same | 1 |
| `verifier-catches-bug` | verifier catches a bug | `llm` weight 2 (rejects); `tool_used Agent verifier` with-only | same | 2 |
| `go-reports-risk-and-evidence` | go reports risk and evidence | `tool_used Bash greet.py --upper`; `llm` (intent, live evidence, risk, no PR) | greet.py on `feat/upper`, kit.json check/verify | 1 |
| `investigate-asks-for-evidence` | investigate asks for evidence | `llm` weight 2 (console steps, query, export, working run); `tool_used Skill investigate` with-only | Cloud Run job repo, no logs | 1 |
| `investigate-logs-root-cause` | investigate logs root cause | `llm` weight 2 (schema v2, fix at parse, v1 kept, new test); `llm` (regression test run); `tool_used Skill investigate` with-only | `.debug/ok.json`/`fail.json` exports | 1 |
| `offers-domain-plugin` | offers domain plugin | `tool_used Skill extras` with-only; `llm` (offers Kit UI, concrete checks) | static landing page | 1 |
| `overnight-sets-budget` | overnight sets budget | `llm` (runner command, gate, stop, budget); `tool_used Skill overnight` with-only | calc.py with kit.json | 1 |

The format matches the docs (`case.yaml` with `schema_version: "1.1"`, `name`, `context.scaffold_script`;
`prompt.md` frontmatter `max_turns`, `timeout_seconds`, `allowed_tools`, `runs`; `graders/*.md`
with `type`, `weight`, `arm`, `input_match`). Two things to know when running it: `fixture.sh`
runs only with `--scaffold`, and `Bash`, `Write`, `Edit` are removed from a run unless granted with
`--allow-tools` whatever `allowed_tools` says, so six of the eight cases need
`--allow-tools Bash Write Edit`. With the default `--ablation with-without` the suite is about
8 cases × 2 arms × (1 or 2 runs) = 18 agent runs plus judge calls; `--ablation none` halves it.

### 5.2 Important flows with no case

| Flow | Why it matters | Today |
|---|---|---|
| ask mode stays read-only | the README's "changes no code" promise for `/kit-mode ask`; a discussion that edits code is a trust break | `kit.test.tsx:63-81` checks the context line is injected; nothing checks that Claude obeys it |
| `/kit:handoff` destinations | the bridge from ask mode to work; a brief that lands nowhere is lost | none |
| `/kit:scout` producing cards | read-only promise + the JSON contract that feeds `proposals.py` | `test_proposals.py` tests the script, not the scouts' output or the "never change anything" rule |
| implementer DECISION lines and gate use | the user vetoes decisions from the report; the gate record is the PR's evidence | `test_items.py` files a hand-written report; no case makes an implementer produce one |
| fresh-eyes | new in 1.6/1.9; costs a subagent, must fire only for large/ambiguous briefs | none |
| `items.py` used by the lead | the 1.5 contract (`ITEM:` in the brief) is what makes REPORT.md land | `lead-dispatches-threads` checks `board.md` only |
| effort passed per thread | new in 1.6/1.9; `low` for a small clear brief, `medium` otherwise | none |

### 5.3 Drafted cases (add as directories under `plugins/kit/evals/`)

Every draft below follows the documented layout. `tool_used` regexes are JavaScript, run over the
JSON-encoded tool input; `regex` graders default to `last_message`. Graders of kind
`tool_used: Skill` are plugin-fired indicators (`arm: with-only`).

#### 5.3.1 `ask-mode-stays-read-only/`

The mod's store cannot be set from an eval, so the case tests the contract text itself
(`ASK_CONTEXT`, `kit.tsx:53-57`) through `append_system_prompt`; the switch is covered by
`kit.test.tsx`.

`case.yaml`
```yaml
schema_version: "1.1"
name: ask-mode-stays-read-only
description: In ask mode a request that asks for a code change is answered with reasoning and an offer of /kit:handoff; no code file is edited or written, documentation may be.
tags: [ask-mode, routing]
context:
  scaffold_script: fixture.sh
```

`prompt.md`
```markdown
---
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Edit, Write, Bash]
append_system_prompt: "Kit ask mode: this session is a discussion about the repository. Explore, explain, reason and propose; change no code. Documentation files (Markdown, docs/) may be edited when the user asks. When something worth doing emerges, offer /kit:handoff: it turns the conclusion into a brief and hands it to the coordinator, another session or a new background session."
runs: 3
---

add() in calc.py returns a - b. Fix it and add a test for it.
```

`fixture.sh`: the shared `calc.py`/`test_calc.py` fixture from `lead-dispatches-threads/fixture.sh`.

`graders/no-code-edit.md`
```markdown
---
type: tool_used
tool: Edit
min: 0
max: 0
arm: both
---
```

`graders/no-code-write.md`
```markdown
---
type: tool_used
tool: Write
input_match: '"file_path"\s*:\s*"[^"]*\.py"'
min: 0
max: 0
arm: both
---
```

`graders/offers-handoff.md`
```markdown
---
type: llm
weight: 2
---

PASS if the reply explains the bug (add returns a - b) and says the fix is not applied in this
discussion session, and offers /kit:handoff (or names the coordinator / another session) as the way
to turn it into work.
FAIL if the reply says it fixed the code, or shows a diff as applied, or never mentions handing the
work off.
```

#### 5.3.2 `handoff-saves-item/`

`case.yaml`: `name: handoff-saves-item`, `tags: [handoff]`, `context.scaffold_script: fixture.sh`.

`prompt.md`
```markdown
---
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Bash, AskUserQuestion]
runs: 3
---

We discussed it: login attempts should be rate limited to 5 per minute per account, counted in the
existing Redis client in auth/limiter.py, with a 429 after that; done when `python3 -m pytest
tests/test_limiter.py` passes with a new test for the 6th attempt. Out of scope: IP-based limits.

/kit:handoff save rate limit login
```

`fixture.sh`: `git init`, a `.claude/kit.json` with `{"check": "true", "verify": "python3 -m pytest -q"}`,
`auth/limiter.py` with a stub `Limiter` class, an empty `tests/`.

`graders/items-new.md`
```markdown
---
type: tool_used
tool: Bash
input_match: 'items\.py[^"]*\bnew\b[^"]*--brief'
---
```

`graders/brief-on-disk.md`
```markdown
---
type: regex
target: { source: file, path: .claude/lead/items/rate-limit-login/BRIEF.md }
pattern: '^ITEM: rate-limit-login[\s\S]*^BRIEF:[\s\S]*^DONE WHEN:[\s\S]*^SCOPE:'
flags: m
---
```

`graders/skill.md`: `type: tool_used`, `tool: Skill`, `input_match: '"skill"\s*:\s*"(?:[\w-]+:)?handoff"'`, `arm: with-only`.

`graders/reply.md`
```markdown
---
type: llm
---

PASS if the reply is at most about three lines, names the item id (rate-limit-login) and its
BRIEF.md path, and says it waits on disk (no thread started, no session messaged).
FAIL if the reply starts implementing the change, claims a thread or session was started, or does
not name the item.
```

#### 5.3.3 `handoff-card-for-an-idea/`

Same fixture. `prompt.md` (runs 3, same tools):

```markdown
An idea from our discussion, nothing checkable yet: the onboarding emails feel cold; maybe a warmer
tone or a founder note. /kit:handoff card
```

`graders/proposals-add.md`: `tool_used`, `tool: Bash`, `input_match: 'proposals\.py[^"]*\badd\b'`.
`graders/no-item.md`: `tool_used`, `tool: Bash`, `input_match: 'items\.py[^"]*\bnew\b'`, `min: 0`, `max: 0`, `arm: both`.
`graders/card-written.md`: `regex`, `target: files`, `pattern: '\.claude/lead/proposals/[^/\n]+\.md'`.
`graders/class.md` (`llm`): PASS if the reply names the card id and a class B or C (judgment or a
human decision) with one line of rationale; FAIL if it makes an item or starts work.

#### 5.3.4 `scout-writes-cards/`

`case.yaml`: `name: scout-writes-cards`, `tags: [scout]`, scaffold.

`prompt.md`
```markdown
---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, Bash]
runs: 3
---

/kit:scout docs and configuration
```

`fixture.sh`: `git init`; `docs/setup.md` saying "run `make install`" while the `Makefile` has only a
`test` target; `.github/workflows/ci.yml` running `npm test` in a repo with no `package.json`;
`.claude/kit.json` `{"check": "true"}`; three `TODO` comments in `src/api.py`.

`graders/explorers.md`: `tool_used`, `tool: Agent`, `input_match: '"subagent_type"\s*:\s*"Explore"'`, `min: 1`.
`graders/cards-added.md`: `tool_used`, `tool: Bash`, `input_match: 'proposals\.py[^"]*\badd\b'`.
`graders/cards-on-disk.md`: `regex`, `target: files`, `pattern: '\.claude/lead/proposals/[^/\n]+\.md'`.
`graders/no-edit.md`: `tool_used`, `tool: Edit`, `min: 0`, `max: 0`, `arm: both`; `graders/no-write.md` the same for `Write`.
`graders/report.md`
```markdown
---
type: llm
---

PASS if the final reply is at most five lines, gives what `proposals.py add` printed (added per
class, skipped, total), the proposals folder, and one or two class A cards to take with
`/kit:scout take <id>`; the dead `make install` instruction should be among the findings.
FAIL if the reply pastes file contents or scout prose, changes any file, or has no card ids.
```

#### 5.3.5 `implementer-decides-and-records/`

`case.yaml`: `name: implementer-decides-and-records`, `tags: [implementer, threads]`, scaffold.

`prompt.md`
```markdown
---
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Agent, Bash]
runs: 3
---

Start one kit:implementer thread in the foreground with the brief below and relay its report to me
verbatim, nothing else.

ITEM: greet-config
BRIEF: greet.py reads the default name from a config file at the repo root instead of "world".
WHY: the team wants to brand the greeting per deployment.
DONE WHEN: `python3 greet.py` prints the greeting for the name in the config file, and the project
gate passes.
SCOPE: greet.py, the config file, one test | OUT: the --upper flag
NOTES: JSON or TOML for the file is your call; say which and why.
EXPECT: 20m
```

`fixture.sh`: the `greet.py` + `test_greet.py` + `.claude/kit.json` (check and verify = pytest) from
`go-reports-risk-and-evidence/fixture.sh`, committed on `main`.

`graders/thread.md`: `tool_used`, `tool: Agent`, `input_match: 'implementer'`, `arm: with-only`.
`graders/report-shape.md`
```markdown
---
type: regex
pattern: '^STATUS: done[\s\S]*^CHECKS:[\s\S]*^EVIDENCE:[\s\S]*^RISK: (low|medium|high)[\s\S]*^DECISION:'
flags: m
---
```
`graders/gate-cited.md`: `regex`, `pattern: 'gate\.py[^\n]*(verify|check)|gate-(verify|check)\.json|kit gate (verify|check): passed'`.
`graders/decision.md`
```markdown
---
type: llm
---

PASS if the relayed report has a DECISION line that names the file format chosen (JSON or TOML)
with a reason, its CHECKS quote the gate's result line, and nothing under CHANGED touches the
--upper flag.
FAIL if there is no DECISION line, the report says done without a gate result, or the thread
widened the scope.
```

#### 5.3.6 `lead-fresh-eyes-on-a-large-brief/`

`case.yaml`: `name: lead-fresh-eyes-on-a-large-brief`, `tags: [lead, fresh-eyes]`, scaffold.

`prompt.md`
```markdown
---
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Agent, Skill, Bash, Write]
runs: 3
---

/kit:lead — ship local, 1 in parallel. Item: move session handling out of src/auth/session.py into
a new SessionStore service with its own table, keep the old API working through an adapter, and
make the login flow use the store. Done when the auth tests pass. It should also probably clean up
the old cookie code while at it.
```

`fixture.sh`: `git init`; `src/auth/login.py` (uses an in-memory dict of sessions), `tests/test_auth.py`
(two passing tests), **no** `src/auth/session.py`, `.claude/kit.json` `{"check": "python3 -m pytest -q", "verify": "python3 -m pytest -q"}`.

`graders/fresh-eyes-asked.md`: `tool_used`, `tool: Agent`, `input_match: 'PARAPHRASE[\s\S]*MISSING[\s\S]*NOT NEEDED[\s\S]*REUSE[\s\S]*WRONG REFERENCES'`.
`graders/before-the-thread.md`
```markdown
---
type: tool_order
before: { tool: Agent, input_match: 'WRONG REFERENCES' }
after: { tool: Agent, input_match: 'implementer' }
---
```
`graders/logged.md`: `tool_used`, `tool: Bash`, `input_match: 'items\.py[^"]*\blog\b[^"]*checked'`.
`graders/brief-fixed.md`
```markdown
---
type: llm
---

PASS if, before the implementer thread started, the lead's brief was corrected: src/auth/session.py
does not exist (the fresh-eyes WRONG REFERENCES finding) and the "clean up the old cookie code"
part was cut or put under NEEDS YOU as out of DONE WHEN; the reply to the user is at most four lines.
FAIL if the thread was briefed with the non-existent file as given, or the lead rewrote the brief
without having read the fresh-eyes answer, or the reply is a long plan.
```

#### 5.3.7 Graders to add to `lead-dispatches-threads/` (no new runs)

Replace `graders/board.md` with a trace regex, since the lead may write the board with Bash:
```markdown
---
type: regex
target: trace
pattern: 'board\.md'
---
```
Add:
- `graders/items-new.md`: `tool_used`, `tool: Bash`, `input_match: 'items\.py[^"]*\bnew\b'`, `min: 2`
- `graders/brief-carries-item.md`: `tool_used`, `tool: Agent`, `input_match: 'ITEM:\s*[a-z0-9][a-z0-9._-]*'`, `min: 2`
- `graders/log-working.md`: `tool_used`, `tool: Bash`, `input_match: 'items\.py[^"]*\blog\b[^"]*\bworking\b'`
- `graders/effort-per-thread.md`: `tool_used`, `tool: Agent`, `input_match: '"effort"\s*:\s*"(low|medium|high)"'`, `min: 2`
- `graders/scout-at-low.md`: `tool_used`, `tool: Agent`, `input_match: '"effort"\s*:\s*"low"'`, `min: 1`
  (the add() scout is a small read-only brief: `low` per `skills/lead/SKILL.md:96-98`)

And set `runs: 3` in `lead-dispatches-threads/prompt.md` and `lead-verifies-before-done/prompt.md`.

## 6. CI

### 6.1 What can run headless

- `python3 tests/test_budget.py` and the 16 self-checks: stdlib only, `git` on PATH; no network.
- `claude plugin validate plugins/kit`: ran with an empty `HOME`/`CLAUDE_CONFIG_DIR` (0.75 s, exit 0).
- `claude plugin test plugins/kit`: the docs say a test runs "without a session, a sign-in, or a
  network", and it ran here with an empty `HOME` and with the proxy variables unset (24 pass,
  8.1 s). It exits 1 on a failure. It is **not** credential-gated, so it belongs in CI; see finding 4
  for the one test that times out under load.
- `claude plugin eval`: real model calls on the owner's account; the docs' CI recipe needs
  `ANTHROPIC_API_KEY`, `--trust-plugin`, `--json`, pinned `--model`/`--judge-model`, `--max-cost-usd`.
  Keep it out of the per-push workflow (manual or weekly, below).

### 6.2 Minimal workflow (`.github/workflows/checks.yml`)

```yaml
name: checks
on:
  push:
    branches: [main]
  pull_request:

jobs:
  python:
    name: python ${{ matrix.python }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.9", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: budget ratchet
        run: python3 tests/test_budget.py
      - name: hook and skill self-checks
        run: |
          set -u; rc=0
          for t in plugins/kit/hooks/tests/test_*.py \
                   plugins/kit/skills/*/tests/test_*.py \
                   plugins/kit-llm/hooks/tests/test_*.py; do
            echo "== $t"; python3 "$t" || rc=1
          done
          exit $rc

  plugin:
    name: claude plugin validate + test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - name: install claude code (pinned)
        run: npm install -g @anthropic-ai/claude-code@2.1.319
      - name: validate every plugin
        run: |
          for p in plugins/kit plugins/kit-llm plugins/kit-ui; do claude plugin validate "$p"; done
      - name: mod tests
        run: claude plugin test plugins/kit

  # Optional, manual or weekly: real model calls on the owner's credential.
  evals:
    if: github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'
    runs-on: ubuntu-latest
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm install -g @anthropic-ai/claude-code@2.1.319
      - run: sudo apt-get install -y bubblewrap socat   # Bash grants need the sandbox backend
      - run: |
          claude plugin eval plugins/kit --trust-plugin --scaffold \
            --allow-tools Bash Write Edit --ablation none --runs 1 \
            --model claude-sonnet-5 --judge-model claude-haiku-4-5 \
            --threshold 0.8 --max-cost-usd 15 --no-publish --json results.json
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: eval-results, path: results.json }
```

Add `workflow_dispatch:` and `schedule: - cron: "0 6 * * 1"` under `on:` if the evals job is kept.
The pin `2.1.319` is the version measured here; bump it on purpose, since a CLI change is what the
mod tests are most likely to trip on.

Cost per run: `python` job ≈ 1.5 min each (checkout + setup ≈ 30 s, suite ≈ 45 s) × 2 = 3 billed
minutes; `plugin` job ≈ 1.5 min (npm install ≈ 40 s, validate + test ≈ 12 s). **≈ 4.5 billed
minutes, ≈ 2 min wall**, free on a public repo and well inside the 2,000 free minutes of a private
one at the current merge rate (10 merges in two weeks). The evals job is dollars, not minutes:
8 cases × 1 run × with-arm only ≈ $3-6 at list price plus judge calls (`--max-cost-usd 15` caps it).

### 6.3 What it would have caught in the last ten merges

Replayed on each merge commit's exported tree (`git archive`, nothing written into the repo):
budget, every self-check under 3.13 and 3.9, `plugin validate`, `plugin test`
(`merges/summary.txt`). First-push commits of recent PRs (the commit before each "self-review
fixes" commit) under 3.13 + budget + validate (`merges/summary2.txt`).

**Merge commits (what a CI on `main` would have shown):**

| Merge | Date | PR / content | budget | Python 3.13 | Python 3.9 | validate | mod tests |
|---|---|---|---|---|---|---|---|
| `776ac45` | 2026-11-08 | #23 effort precedence docs | ok | ok | ok | ok | ok |
| `b18bd79` | 2026-11-08 | 1.6 + 1.7-1.8.1 → 1.9.0 (the three parallel releases) | ok | ok | ok | ok | ok |
| `0810090` | 2026-11-05 | #22 kbp fixes (judge, malformed op) | ok | ok | ok | ok | ok |
| `8bc9db9` | 2026-11-05 | #21 kbp best practices (1.8) | ok | ok | ok | ok | **FAIL**: `kit.test.tsx:321` timed out at 5,010 ms (the flaky test, §3 #4) |
| `67dd8bb` | 2026-11-04 | #20 stall-proofing to main | ok | ok | ok | ok | ok |
| `7546ea4` | 2026-11-04 | #19 stall-proofing (1.7) | ok | ok | ok | ok | ok |
| `9ab7fff` | 2026-11-04 | #18 cc catch-up | ok | ok | ok | ok | ok |
| `078fe26` | 2026-10-31 | #17 1.5.0 reference pages | ok | ok | ok | ok | ok |
| `8a96782` | 2026-10-31 | #16 items on disk, ask mode, cards (1.5) | ok | ok | ok | ok | ok |
| `3bb9e7c` | 2026-10-30 | #15 gate record, shell edits (1.4) | ok | ok | ok | ok | ok |

**First-push commits of the same PRs (what a CI on pull requests would have shown one commit
before each "self-review fixes" commit):**

| Commit | Date | PR | budget | Python 3.13 | validate |
|---|---|---|---|---|---|
| `6439f50` | 2026-11-08 | kit 1.6 branch tip before the merge | ok | ok | ok |
| `d39cbea` | 2026-11-05 | #22 first commit | ok | ok | ok |
| `76870e0` | 2026-11-05 | #21 kit 1.8 before `637d24a` | ok | ok | ok |
| `1826c1f` | 2026-11-05 | #22 1.8.1 before `d8de922` | ok | ok | ok |
| `d5d2fd5` | 2026-11-03 | #19 kit 1.7 before `3d0efe1` | ok | ok | ok |
| `abb6074` | 2026-10-31 | #16 kit 1.5 | ok | ok | ok |
| `2162fe5` | 2026-10-29 | #15 kit 1.4 before `a5ef9d4` | ok | **FAIL** `test_lessons::test_delivery` | ok |

Reading:

- Nine of ten merged trees pass every proposed check, under 3.9 as well as 3.13; the merge of the
  three parallel releases (`b18bd79`) included. CI would not have blocked a merge in the last two
  weeks on a Python regression or a budget overrun.
- The one red merge (`8bc9db9`) is the flaky mod test (§3 #4) under the replay's CPU load, not a
  regression. In CI the same test would turn roughly one run in three red on unrelated changes
  until it is fixed; that is the first thing the workflow would surface.
- `2162fe5` is a real catch a per-push CI would have made: at that commit `subagent_start.py`
  printed the gate line on top of a full 2,400-character lessons budget (`subagent_start.py:158,
  162` at `2162fe5`), so the thread injection overflowed `MAX_CHARS`. The owner's test passed
  locally because the overflow depends on the length of the plugin's install path inside the gate
  line (`python3 "<absolute path>/gate.py" check`); the replay's longer path tripped it, and a
  GitHub runner's `/home/runner/work/claude-kit/claude-kit/plugins/kit/hooks/scripts/gate.py`
  is longer than a typical `~/code/claude-kit` checkout too. It was fixed the same day in
  `a5ef9d4` ("nothing blocks on the gate record": `budget = MAX_CHARS - (len(gate) + 1 ...)`),
  before the merge. Two lessons: CI would have found it one commit earlier than the self-review
  did; and the current test still asserts on text that embeds an absolute path
  (`test_lessons.py:156`), so it should run once with a deliberately long `TMPDIR`
  (or assert `len(text) <= MAX_CHARS` with a 200-character fake plugin path) to stay honest on
  every machine.
- The other "self-review fixes" commits (`637d24a`, `d8de922`, `3d0efe1`, `67d54d5`, `fe0bcea`)
  fixed defects found by reading, and added their tests in the same commit; the suite was green
  before and after each. For those, CI's value is forward-looking: the 3.9 floor, the mod tests
  against a pinned CLI, the budget ratchet on every push, and the flaky test made visible.

## 7. Prose that a script could check

Rules in SKILL.md/agent files that are deterministic enough to become a hook check or a test. Each
is listed with where it lives and the smallest mechanical home (README's rule: "few instructions,
deterministic checks").

| Rule (prose today) | Where | Mechanical home | Cost |
|---|---|---|---|
| "a typo-free kit.json": no rule says it, but every gate depends on it | `skills/init/SKILL.md:100-111` (the schema), `kitlib.py:66-74` | `session_start.py` warns on unknown keys / wrong types (finding 6) | S |
| "Brief a thread with the `ITEM: <id>` line" | `skills/lead/SKILL.md:42-44` | `subagent_stop.py`: when a `kit:implementer` ends with a report and its brief names no item while `.claude/lead/items/` has open items, append one LOG line to the lead folder (`.claude/lead/LOG.md`: "report from thread X filed nowhere") so the lead sees it | S |
| "Keep it to the format below" (STATUS/CHANGED/.../RISK) and the verifier's `VERDICT:` line | `agents/implementer.md:12, 55-64`; `agents/verifier.md:43-52` | `subagent_stop.py`: like the missing-report nudge, block once when a kit:implementer hand-back lacks `STATUS:`/`RISK:` or a kit:verifier one lacks `VERDICT:` (today a missing verdict only logs `no verdict line`, `subagent_stop.py:263`) | M |
| "Start queued items while fewer than PARALLEL are working" | `skills/lead/SKILL.md:80` | `kit.tsx` `tool.call{Agent}`: count running `kit:implementer` agents against kit.json `lead.parallel` and answer `ask` past it (the guard's `agentsAsk` is the same shape, `guard.py:1092-1103`) | M |
| "Stage only the files this work changed (no secrets, `.env`, large data or `.claude/evidence/`)" | `skills/go/SKILL.md:42-44` | a guard rule: `git add` of `.env*`, `*.pem`, `.claude/evidence/` or `-A` with such files untracked → ask | S |
| "Branch first if on the default branch" | `skills/go/SKILL.md:42`, `agents/implementer.md:36` | guard: `git commit` while HEAD is a protected branch → ask (push is already denied, `guard.py:717-721`; the commit on main is not) | S |
| "The gate passes on the starting commit: run it once" | `skills/overnight/SKILL.md:55-56` | `overnight.py`: run `run_gate` once before iteration 1 and refuse (or `--allow-red-start`) when it fails; today it only prints the gate (`overnight.py:335`) | S |
| "Don't edit any file of the change" (verifier) | `agents/verifier.md:40-41`, `disallowedTools` | `bash_edits.py` already sees shell edits; when `agent_type` is `kit:verifier` (if the payload carries it) report any changed tracked file as a violation | M |
| The brief format (`BRIEF`, `DONE WHEN`, `SCOPE`) | `skills/handoff/SKILL.md:20-29`, `skills/shape/SKILL.md:32-40` | `items.py new --brief`: warn when the brief has no `DONE WHEN:` line (proposals.take always writes one, `proposals.py:176-179`) | S |
| Script paths the skills quote (`${CLAUDE_SKILL_DIR}/../../hooks/scripts/items.py` and the like) | `skills/handoff/SKILL.md:14-15`, `scout:10`, `learn:15`, `go:26`, `investigate:52`, `overnight:63` | `tests/test_budget.py`: resolve each `${CLAUDE_SKILL_DIR}/...` reference and assert the file exists (it already checks `kit:x` names, `test_budget.py:128-131`) | S |
| Eval cases well-formed (every case has a grader, `schema_version`, `input_match` compiles, graders named with-only where the docs require) | `evals/*` | `tests/test_budget.py` or a sibling: parse `case.yaml`/`prompt.md` frontmatter and `graders/*.md`; zero credits | S |
| "Keep the board under 60 lines and 8 KB", "add `/.claude/lead/` to exclude", "no AI co-author", "never wait in the foreground", "evidence out of git" | lead/go/implementer | already mechanical (`session_start.board_warning`, `items.ensure_excluded`, `guard` attribution and wait rules, `gate.ensure_excluded`); nothing to do | — |

## 8. Notes on method and limits

- Coverage is line coverage of what the self-checks execute; it says nothing about assertion
  strength (hence §3 items 7, 14). A line hit inside a `try` whose exception never fired is a hit.
- The replay in §6.3 runs each merge's own tests on today's toolchain (git 2.4x, Claude Code
  2.1.319); a merge green here but red on the owner's machine at the time is possible only through
  the environment, which is one reason to pin the CLI in CI.
- `claude plugin eval` was not run (credits). The drafted cases follow the documented grammar but
  have not been executed; the two regex graders over `trace` and `files` should be checked once
  with `--runs 1 --ablation none` before they gate anything.
- The flaky-test figures: 16 runs of `claude plugin test` on this 2-vCPU container, 9 while the
  replay loaded the CPU and 3 on an idle machine, plus the 4 replays whose tree had the test. The
  fastest run was 4.19 s; the test has no margin under its 5 s cap on hardware like a CI runner.
