# E — claude-kit 1.9.0 as the owner meets it

Read-only walk-through of `/home/user/claude-kit` at `776ac45` (kit 1.9.0, Claude Code 2.1.319).
Every hook was fed the stdin Claude Code sends (per the hooks reference) against two scratch repos
under `scratchpad/analysis/e-probe/`: `next-app` (Next.js + Supabase, opted in with `check`,
`verify`, `onEdit`, `protect`, `author`, `lead.notes`) and `py-svc` (FastAPI, no kit.json), with
`HOME`/`CLAUDE_CONFIG_DIR` pointed at a fake home. Scripts and raw output: `e-probe/setup.sh`,
`e-probe/probe1.sh`, `e-probe/probe2.sh`. The kit's own self-tests (`test_budget`, `test_items`,
`test_subagent_stop`, `test_gate`, `test_stop_check`, `test_proposals`) pass on this machine.

## Install path, in short

- **Manual steps** (README:138-187, install.sh): clone, run `install.sh` (registers the clone as a
  local-path marketplace, installs `kit` at user scope, offers the two `~/.claude/settings.json`
  keys), then per project `cd && claude`, `/kit:init`, read and commit `.claude/kit.json`. The
  domain plugins are a second manual install per project. Optional by hand: two lines in
  `~/.claude/CLAUDE.md`, `CLAUDE.local.md`, `.worktreeinclude`, `/kit-safety`, `/kit-mode`.
- **macOS**: nothing found that differs. `install.sh` is POSIX `sh`, the hooks need only
  Python 3.9 stdlib (`fcntl` exists), `tempfile.gettempdir()`/`/var/folders` are in the temp-root
  lists, `claude plugin marketplace add "$(pwd)"` takes the clone path. The one machine-specific
  thing is the kit's install path, which `/kit:init` bakes into a committed file (finding 6).
- **Update**: with the local-clone marketplace Claude Code loads the plugin **in place** (docs,
  create-marketplace "Test an edit"): `git pull` + `/reload-plugins` is complete and `version` is
  ignored. With `install.sh --github` the plugin is a cache copy: changes arrive only after a
  `version` bump and `claude plugin update kit@claude-kit` / `/plugin marketplace update`, or
  marketplace auto-update turned on in `/plugin`. `session_start.update_notice` (session_start.py:122-138)
  can only fire in the cache case. **An existing project needs nothing**: every script reads
  kit.json with `.get()` and a default; `{}`, a kit.json from 1.6, or one with typos crashes
  nothing (probe A5-A7). The cost of a missing key is silence, not breakage (finding 4).
- **Cloud (claude.ai/code)**: not covered anywhere. In this very cloud container the kit is not
  installed (`claude plugin list`: only synced plugins), `~/.claude/settings.json` and
  `~/.claude/kit.json` do not exist, so a kit install there would re-offer "Kit setup" every
  session and the lesson ledger would be wiped with the container (finding 2).

## Flows

| Flow | Verdict | One line |
|---|---|---|
| First session, no kit.json | works | silent; the one-time "Kit setup" offer is printed for Claude to ask (A1), silent after `--apply`/`--decline` (A3) |
| `/kit:init` | friction | 14 steps and about 7 questions (ship, merge, author, host/sandbox, permissions, auto-mode env, plugins); kit.json is shown and explained (step 14) but the owner's standing answers are asked again in every project |
| SessionStart with kit.json | works | 5-7 context lines: gates, protected globs, onEdit globs, lead notes (A4); after a compaction the board comes back, NEEDS YOU and rows first, RULES cut last (A8) |
| kit.json with a typo or `{}` | broken (silent) | `{}` = "no kit.json" for every hook except the guard (A5); `chek`/`verfy` prints nothing at all (A6); only invalid JSON is reported (A7) |
| `/kit:go` | works | gate run through `gate.py verify` is recorded and `status` tells whether the tree still matches (D1); merge policy asked once when `lead.merge` is unset, same wording as the lead |
| `kit:lead` loop mode | works | every typed prompt gets one context line; board, items, briefs with `ITEM:` and `EXPECT:`; `items.py new/list/log/path/show/done` all behave (B1, B5) |
| Thread report filed (`REPORT.md`) | **broken for worktree threads** | a thread stopping with `cwd` = its worktree files nothing: `subagent_stop.py` looks for the item in the worktree, where `.claude/lead/` does not exist (C2); works from the main checkout (B2) |
| Thread with no hand-back | works | told once to call SubagentHandback, then the coordinator is woken (B3; kit.tsx:490-512) |
| Verifier verdict → item + ledger | friction | `VERDICT.md` and the LOG line land (B4); a FAIL problem that names a long migration path is refused as "secret-shaped" and never becomes a lesson (B4, finding 3) |
| Merge policy question | works | asked by the lead at the first PR, written to `lead.merge`; `agent` still leaves high-risk PRs to the owner |
| `/kit-mode ask` + `/kit:handoff` | works | instruction-only read-only mode (owner's choice); `lead`, `session`, `bg` (`claude --bg --name`, `claude attach` exist on 2.1.319), `save`, `card` all have a real path; a queued item is not on the board, so nothing shows it until `next` (finding 8) |
| `/kit:scout` + proposals.py | friction | dedupe, classes, `take` → queued item, `retire` work (I1); ids double the origin stem (`readme-readme-install-step-names-npm`); a card whose evidence cites a Supabase migration is dropped as a secret (finding 3) |
| Nightly `/kit:learn` | works (cadence unclear) | nothing is nightly: capture is automatic, SessionEnd distills at 5 events, the haiku pass runs at most once a day, the review is suggested every 14 days and previewed with `--dry-run` first (C1); README says "weekly sweep", reference says 14 days |
| Stop hook with `check` | works | silent on an unchanged tree, clear message on failure, lets go after 3 (E1); the failure shape becomes a gate lesson |
| Stop hook / gate without commands | works | no `check`: silent (E2); no `verify`: `gate.py verify` exits 3 with a clear line and SubagentStart names `check` instead (D2) |
| Guard (host, minimal) | works, over-documented | blocks push to main, stash drop, AI attribution, `curl \| sh`, foreground `sleep 90` and `gh pr checks --watch`; lets deploys, `rm -rf ../wt`, `git reset --hard` through (G1); stacks.md claims it asks before `supabase db push`/`vercel --prod`/`wrangler deploy` and it does not (finding 7) |
| Mod: modes, status line, notifications | friction | `loop · host · $1.20 · 2 running · 1 waiting · 1 ready · 1 need you`; a board written as a Markdown table counts 0 (K1); the mod and the lead can both notify for the same event (findings 9, 10) |
| Two writers | works (one checkout) | 20 parallel `items.py log` appends: 21/21 lines; two concurrent `done`: both rows archived (J1); board whole-rewrites by two leads have no lock; cloud and local never share `.claude/lead/` (excluded from git) |

## Findings, by value over cost

**1. A thread in a worktree never gets its REPORT.md filed.** Value L, cost S.
Evidence: `subagent_stop.py:282` resolves the project with `kitlib.project_root(data)` (the hook's
`cwd`), and `file_report` (`:252-269`) calls `items.find(root, …)` there. The hooks reference says
`cwd` "is the worktree root after Claude enters a worktree", and the kit's own `subagent_start.py:36-45`
already maps a worktree back to the main checkout for the same reason. Probe C2: SubagentStop with
`cwd` = `next-app-wt` on item `second-item` left the LOG at `queued` and no REPORT.md; the same
stop with `cwd` = the main checkout filed it (B2). `gate.py` from the worktree also writes its
evidence under the worktree's `.claude/evidence/feat/wt/` (C2), which the lead removes after merge.
Owner: the 1.8/1.9 promise ("cat what the agents said from any session") holds only for threads
that run in the main checkout; every `isolation: "worktree"` thread, the default, leaves an empty
item folder, and `items.py list` shows them as `working` forever. Change: in `subagent_stop.py`
use `subagent_start.main_checkout(cwd)` for the items root (fallback: the checkout of `cwd`); have
`gate.py` write evidence under the main checkout too, or copy the record at report time.

**2. Cloud sessions: no kit, or a "Kit setup" question every session, and no lessons.** Value L, cost M.
Evidence: this cloud container (`claude plugin list`) has no kit; `~/.claude/settings.json` and
`~/.claude/kit.json` are absent, so `machine_setup.pending()` returns both lines (A1) and
`session_start.py:98-111` tells Claude to ask with AskUserQuestion before the first request;
`--decline` writes `~/.claude/kit.json` (machine_setup.py:95-105) and the ledger lives in
`~/.claude/kit-lessons` (lessons.py:100-101): both die with the container. README has no cloud
section (grep: no "cloud"/"setup script" install text). Owner: in the cloud the gates, guard, board
and threads' lessons are simply not there; after adding the kit to an environment setup script,
every cloud session opens with the setup question, and the `autoMode.allow` force-push rule it
offers does nothing useful there. A second cloud effect: this container sets
`CLAUDE_CODE_ENTRYPOINT=remote_mobile` (with `CLAUDE_CODE_REMOTE=true` and
`CLAUDE_CODE_SESSION_ATTENDED=1`), and `lessons.headless()` (lessons.py:156-161) treats every
entrypoint outside `cli`/`claude-vscode`/`claude-desktop*` as "nobody at the keyboard": in an
attended cloud session the review-due line is never shown (lessons.py:749), the haiku pass is
skipped (distill.py:259-260) and `/kit:learn promote` refuses (promote.py:283-284), while the
"Kit setup" offer, which checks only `KIT_HEADLESS` (session_start.py:147), still fires. Change: a
README "Cloud" recipe (attach the kit repo, `claude plugin marketplace add <checkout>` and
`install` in the environment's setup script, run `machine_setup.py --apply` there
non-interactively); treat `CLAUDE_CODE_SESSION_ATTENDED=1` as interactive and
`CLAUDE_CODE_REMOTE=true` as "skip the machine-settings offer"; point the ledger at a
committed-or-synced place for cloud, or say plainly that cloud threads learn nothing.

**3. The secret filter eats the owner's Supabase lessons and cards.** Value L, cost S.
Evidence: `kitlib.OPAQUE` (`kitlib.py:96,105-107`) flags any 32+ run of `[A-Za-z0-9+/_=-]` with a
letter and a digit unless it holds `word-word`. `looks_secret("supabase/migrations/20260101120000_profiles_rls.sql")`
is True; so is the verifier's headline "The update policy lets any authenticated user update any
profile (supabase/migrations/0042_profiles_rls.sql:18)…". Probe B4: two FAIL problems, two
`verifier-fail` events, one lesson (`L2 … No policy for delete;`), the RLS one gone; probe I1/last:
a class-A card about a migration skipped as "looks like it holds a secret"; `lessons.py add … supabase/migrations/…`
refused. Every Supabase migration path matches, and snake_case long names too. Owner: the
verifier's best finding never reaches the next thread; scout output about migrations vanishes
behind a "skipped 1" count. Change: in `looks_secret`, do not treat a token as opaque when it
contains `/` or `.` followed by a known extension, or `word_word`; keep the explicit `SECRET`
patterns. Add the migration path to `test_lessons`/`test_proposals`.

**4. A kit.json with no recognised key is silent, including a typo.** Value M, cost S.
Evidence: `kitlib.load_config` returns `{}` for `{}` and every hook does `if not config: return 0`
(stop_check.py:65, gate.py:203 prints "no .claude/kit.json (run /kit:init)" though the file
exists, A5) while `guard.settings()` (guard.py:324) treats the same `{}` as opted in and blocks a
push (A5). With `{"chek": …, "verfy": …, "lead": {"shipp": …}}` SessionStart prints nothing because
`len(lines) > 1` fails (session_start.py:182, A6). Owner: edits kit.json by hand, misspells a key,
and the Stop gate quietly stops running; nothing ever says so. Change: SessionStart always prints
the "kit harness active" line when the file exists and appends "unknown key: `chek` (did you mean
`check`?)" from a known-key set (top level, `lead`, `guard`, `watchdog`); make `{}` count as
opted in everywhere or nowhere.

**5. `/kit:init` re-asks the owner's standing decisions in every project.** Value M, cost M.
Evidence: init/SKILL.md steps 5 (ship, merge, author), 10 (host or sandbox), 11 (permission
rules), 12 (auto-mode lines), 13 (plugins), 14 (hook test): about seven AskUserQuestion rounds.
The mod already reads a personal default from `~/.claude/kit.json` (`mode`, kit.tsx:108-121).
Owner: "host, pr, I review, my git identity, English" typed again for Polizzen, Ciao Guest and
every service. Change: one multi-select round with the recommended answers preselected, and a
personal `~/.claude/kit.json` `"init": {"ship": "pr", "merge": "user", "safety": "host"}` that init
reads and only confirms in one line.

**6. `.claude/loop.md` commits the kit's absolute install path.** Value M, cost S.
Evidence: init/SKILL.md:63-67 and init/loop.md:5-7,19 fill `<kit>` from `claude plugin marketplace list --json`
and commit the file. The path differs between the owner's Mac (the clone under
`~/Documents/repositories`), a `--github` install (`~/.claude/plugins/cache/…`) and a cloud
container (`/root/.claude/…`). Owner: `/loop` in the other environment fails at
`python3 "<kit>/hooks/scripts/gate.py" verify`. Change: have loop.md run the project's `verify`
command itself (permission.py already allows the exact string) and mention `gate.py` only as
"if the kit is installed"; or resolve the path at run time.

**7. The docs promise a deploy guard that does not exist.** Value M, cost S.
Evidence: init/stacks.md:43-44 "The guard asks before `supabase db push`, `vercel --prod`,
`wrangler deploy` and the other remote changes"; `guard.py` has no such rule (grep: only
`~/.config/gcloud` as a credential path); probe G1: all four deploy commands exit 0. Owner: with
a minimal guard that is the wanted behaviour, but the belief is wrong, and a thread in `pr+fix`
mode can run `vercel --prod` on its own. Change: delete the sentence, or have init propose (not
write) `guard.askCommands` for the stack's deploy commands so the owner decides once.

**8. A handed-off or taken item is queued where nothing shows it.** Value M, cost S.
Evidence: `items.py new` writes only the folder (items.py:133-151); the board is the lead's
(lead/SKILL.md:18-21), the status line counts board rows (kit.tsx:182-195), the lead resumes "from
the board" and takes disk items only on `next` (lead/SKILL.md:9-11). handoff/SKILL.md:43-45 tells
the owner to switch to loop mode. Owner: after `/kit:handoff lead` and `/kit-mode loop`, a plain
"ok go" may answer in place and leave the item queued; `/kit:scout take` the same. Change:
SessionStart and the LOOP_CONTEXT line add "N queued item(s) on disk: `items.py list --status queued`"
when any exist; or `items.py new` appends a `queued` row to the board.

**9. The status line and notifications depend on the exact row format.** Value M, cost S.
Evidence: `countBoard` (kit.tsx:182-195) needs `c[4] === 'review'` and reads NEEDS YOU only from
the header line. Probe K1: a Markdown table with leading `|` → `{ready: 0}`; `Review` → 0; a
row missing the DONE WHEN cell → 0; a `needs-you` row without a NEEDS YOU line → 0. Models render
tables readily. Owner: the line stays quiet and no notification arrives while a PR is ready.
Change: strip leading/trailing `|`, skip header/separator rows, match a known status word in any
cell case-insensitively, count `needs-you` rows as well.

**10. Two notifications for one event; notifications while the owner is typing.** Value S-M, cost S.
Evidence: `notifyBoardChange` fires on every tick where ready/needs rose (kit.tsx:259-268), the
lead skill also sends a PushNotification "when a wake-up the user didn't cause leaves something
for them" (lead/SKILL.md:131-132), and the watchdog's third strike notifies too (watchdog.ts:82).
Owner: a desktop ping for a board row they are reading in the same terminal, twice. Change: in
the mod, skip the board notification when `activity.get('main')` is within the last minute; tell
the lead not to PushNotification when the mod is loaded (the mod is the backstop).

**11. Guard denials become lessons.** Value S, cost S.
Evidence: `record_denial` (guard.py:1117-1128) captures each denial as a pitfall; one probe run
(G1) produced seven candidates ("The kit guard blocks this (wait): sleep … in the foreground.
Plan another way"), active on a second sighting and delivered inside the 400/600-token budgets
(lessons.py:580-590). Owner: lesson budget spent on rules a hook already enforces, read at every
thread start. Change: keep the event (stats) and drop the lesson, or deliver guard lessons to the
lead only.

**12. Docs vs code, small but owner-facing.** Value S, cost S.
- README:53 shows the status line as `kit: loop · host …`; kit.tsx:301-311 and kit.test.tsx:176 have no `kit:` prefix.
- README:31 "Weekly `/kit:learn sweep`" vs reference:370 "from 14 days after the last review"; the
  owner's "nightly learn" needs one paragraph: capture and distil are automatic, the model pass is
  ≤1/day, `/kit:learn` when the session says the review is due, `sweep` is a separate transcript read.
- `checkTimeout` default 540 in stop_check.py:73 and the docs, but 1800 for `gate.py check`
  (gate.py:128), and `verifyTimeout` (same line) is read and documented nowhere.
- reference.md:18-19 and guard.py:51 show `"agentsAsk": 15, "agentsDeny": 40` in the example;
  copied as is, a loop-mode day (threads, verifiers, fresh-eyes, scouts) starts prompting at the
  16th subagent. Mark them optional in the example or drop them.

**13. Things the owner types by hand that could be native.** Value S, cost S.
- `permission.py` allows `gate.py`, `lessons.py`, `compact_logs.py` by path (permission.py:21,
  F1) but not `items.py` or `proposals.py`: in default mode each board action is a prompt. Add them.
- Card ids repeat the origin stem (`readme-readme-install-step-names-npm`, I1), and `/kit:scout take <id>`
  and `/kit:learn undo L7` are typed by the owner. Use `<origin-stem>-<first words>` once, and let
  `take` accept a class letter or a prefix.
- Every skill spells `python3 <kit>/hooks/scripts/items.py` for the model with the path from
  `claude plugin marketplace list --json`; a tiny `/kit:items` command (or `${CLAUDE_PLUGIN_ROOT}`
  in the skill text, which hooks.json already uses) would remove the lookup.

**14. Multi-session reality, as documented.** Value S, cost S (docs).
`.claude/lead/` is excluded from git (items.py:57-80), so the cloud session and the Mac never see
each other's board, items, evidence or proposals; two local leads on one checkout both rewrite
`board.md` whole (lead/SKILL.md:19) with no lock, last writer wins; LOG appends and `done` are
safe (J1). The lessons ledger is per machine. Say so in the README's multi-session paragraph, and
offer `lead.board` under a committed path for an owner who wants the board shared through git.

## kit.json keys

Legend: doc = README/reference/skill text; read = script or mod that reads it; model = read only by Claude following a skill.

| Key | doc | read by | note |
|---|---|---|---|
| `check` | yes | stop_check, gate, permission, session_start, subagent_start, overnight | |
| `verify` | yes | gate, permission, session_start, subagent_start, overnight | |
| `checkTimeout` | yes (540) | stop_check (540), gate check (**1800**) | default differs between readers |
| `verifyTimeout` | **no** | gate verify (1800) | read, undocumented |
| `maxStopRetries` | yes (3) | stop_check | |
| `onEdit[].glob/run/timeout` | yes | on_edit, bash_edits, session_start | `timeout` default 120 |
| `protect[].glob/mode/reason` | yes | protect, bash_edits, session_start | |
| `guard` = `"off"` / object | yes | guard | `{}` kit.json still activates it |
| `guard.protectedBranches` | yes | guard | default main, master, remote HEAD |
| `guard.agentsAsk/agentsDeny` | yes (optional) | guard | present in both examples |
| `guard.allowCommands/denyCommands/askCommands` | yes | guard | |
| `guard.attribution` | yes | guard | `"allow"` turns off |
| `guard.waits`, `guard.sleepMaxSec` | yes | guard | 60 s |
| `watchdog.silentMin/bashDeadlineMin/permissionMin` | yes | kit.tsx via watchdog.ts | 20/30/2 |
| `llm` | yes | kit-llm `llm_detect` | only `"off"` matters |
| `learn.model` | yes | distill | only `false` matters |
| `author` | yes | session_start | |
| `lead.board` | yes | items, session_start, kit.tsx | |
| `lead.notes` | yes | session_start | |
| `lead.read`, `lead.backlog` | yes | model only | no script validates the paths |
| `lead.ship`, `lead.merge`, `lead.parallel`, `lead.budget`, `lead.loops` | yes | model only | defaults live in lead/SKILL.md:50-51 |
| `~/.claude/kit.json` `mode` | yes | kit.tsx | |
| `~/.claude/kit.json` `guard` | yes | guard | `"on"` or an object |
| `~/.claude/kit.json` `machineSetup` | **name not documented** | machine_setup | README says "never asks again" without the key |
| env `KIT_CHANGED_FILES/COUNT`, `KIT_GATE`, `KIT_HEADLESS`, `KIT_LEARN_MODEL`, `KIT_TEMP_ROOTS` | yes | kitlib, gate, stop_check, lessons, distill | |
| env `KIT_LEARN_CLAUDE`, `KIT_LESSONS_DIR`, `KIT_LESSONS_TODAY`, `KIT_LESSONS_PREVIEW` | docstrings only | distill, lessons | internal, fine |

Unknown or misspelt keys at any level: accepted silently (finding 4). Init's schema block
(init/SKILL.md:100-111) omits `watchdog`, `llm`, `learn`, `verifyTimeout`, `lead.board`,
`lead.budget`, `lead.loops`.

## What already feels good

The deterministic middle is solid and quiet: the Stop hook costs nothing on a question turn and
gives a clear, bounded failure message; `gate.py` turns "tests passed" into a record a PR can cite
and `status` catches a tree that moved; `items.py` and `proposals.py` are small, scriptable, safe
under concurrent appends, and the `ITEM:` line is a simple contract that ties a thread's hand-back
to a folder the owner can `cat`; a thread that forgets to report is nudged once and then the
coordinator is woken rather than left waiting; the lesson ledger is capture-first, undo-everything,
and never asks the owner to curate (the review is a dry run first, with one line per change); the
guard's messages name the way out, and the kit's skills are short, in English, and consistent
about effort, evidence and authorship. The pieces fit; the gaps are at the seams the owner
crosses most, a worktree, a second machine, a hand-edited kit.json.
