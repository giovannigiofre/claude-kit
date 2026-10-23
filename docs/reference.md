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
  "guard": {"protectedBranches": ["main", "master"], "agentsAsk": 15, "agentsDeny": 40, "allowCommands": []},
  "llm": "on",
  "lead": {
    "read": ["docs/backlog.md"],
    "backlog": "docs/backlog.md",
    "notes": "one line of project-specific advice for the coordinator",
    "board": ".claude/lead/board.md",
    "ship": "pr",
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
- The Stop hook runs `check` only when the working tree changed since the last passing check,
  so question-and-answer turns cost nothing. After `maxStopRetries` failures in a row it lets
  Claude stop, and Claude must report the failure.
- `guard`: on by default in a project with `kit.json`; `"off"` turns it off. `protectedBranches`
  defaults to main, master and the remote's default branch. `agentsAsk` / `agentsDeny` are an
  optional per-session cap on subagents (ask past one, refuse past the other); the native
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` caps how many run at once. `allowCommands`: regexes the
  guard lets through. `attribution` (default `"block"`): blocks AI credits in commit messages, PR,
  issue and comment text (git, `gh`, GitHub MCP tools) and commits under an AI git identity
  (name "Claude", an `anthropic.com` email); `"allow"` turns that rule off. Pair it with
  `"attribution": {"commit": "", "pr": "", "sessionUrl": false}` in `settings.json`, so Claude
  doesn't write the credits in the first place. `{"guard": "on"}` in `~/.claude/kit.json` guards projects without a
  `kit.json` too.
- `llm` (read by the `kit-llm` plugin's hook): `"off"` silences the LLM-code hint in this project.
- `lead` configures the coordinator. `ship`: `local` (verified branches, you merge), `pr` (threads
  push and open PRs), `pr+fix` (they also keep CI green). Setting `pr` or `pr+fix` here is a
  standing go-ahead to push; without it the coordinator asks once per session. `parallel`:
  threads working at once (default 3). `budget`: `{"items": N}` or `"none"`. `loops`: standing
  loops the coordinator schedules (session-only, they expire after 7 days).

Also per project, committed: `CLAUDE.md` (the project's rules, which win over the kit),
`.claude/skills/e2e/SKILL.md` (how to exercise the app), `.claude/review-decisions.md` (findings
you declined, so reviews don't raise them again). Gitignored: `.claude/evidence/`,
`.claude/overnight/`, `.claude/lead/`.

## Modes and the panel

- **Light**: a normal session. `/kit:lead <work>` starts the coordinator when you want it.
- **Loop**: every message you type (terminal or Remote Control) gets one line of context sending
  it to the coordinator; headless runs, scheduled prompts and notifications never do. `/kit-mode
  loop|light`, or the panel buttons. Without a choice for the project, the personal default in
  `~/.claude/kit.json` (`{"mode": "light"}` or `"loop"`) applies, else loop in a project with
  `.claude/kit.json` and light elsewhere.
- **Board** (`.claude/lead/board.md`):

  ```
  SHIP: pr | PARALLEL: 3 | BUDGET: none
  RULES: <standing preferences you stated>
  NEEDS YOU: <id: question>; <id: question>
  <id> | <ship|scout|overnight> | <goal> | DONE WHEN <check> | <status> | agent <name> | <branch/PR> | <last event>
  ```

  Status: `queued`, `working`, `review`, `needs-you`, `landing`, `done`, `parked`. The panel lists
  NEEDS YOU first, then ready for review, then working.
- **Safety**: `/kit-safety host|sandbox` or the panel. Sandbox writes the kit's block into
  `.claude/settings.local.json`; check it with `/sandbox`, add hosts under
  `sandbox.network.allowedDomains`. Where the sandbox can't start, commands run unsandboxed with
  a warning rather than all failing.

The mod needs Claude Code with mods (2.1.287+). Without it, the skills and hooks still work; use
`/kit:lead` directly instead of loop mode.

## Overnight runner

```
python3 <kit>/skills/overnight/scripts/overnight.py "<objective>" --stop-when "<condition>" \
  --worktree ../app-overnight --max-iterations 40 --max-usd 25 --permission-mode auto --effort medium
```

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
python3 plugins/kit/hooks/tests/test_session_start.py
python3 plugins/kit/skills/investigate/tests/test_compact_logs.py
python3 plugins/kit/skills/overnight/tests/test_overnight.py
python3 plugins/kit-llm/hooks/tests/test_llm_detect.py
claude plugin test plugins/kit               # the mod (panel, modes, safety) against the engine
```

Test a hook by hand:

```bash
echo '{"cwd":"'$PWD'","tool_input":{"file_path":"'$PWD'/src/x.py"}}' \
  | python3 plugins/kit/hooks/scripts/on_edit.py; echo $?
```

### Evals

They spend real tokens; `--max-cost-usd` caps the estimate. Each runs the same case with and
without the plugin; look at which cases flip, not only the mean, and run more than once.

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

Results so far (one run per arm, on earlier kit versions): `verifier-catches-bug` 1.00 with the
kit and 1.00 without (the planted bug is obvious enough that Claude catches it either way);
`picks-llm-skill` 1.00 and 1.00; `optimize-needs-evals` 0.00 in both arms until the skill
description said "with or without an eval suite ... never rewrite a prompt blind", then 1.00
with the kit and 0.00 without. A case that tells the arms apart needs a defect you only find by
running the code.
