---
name: init
description: Sets up the kit harness in the current project - writes .claude/kit.json (fast check, full verify, per-file onEdit commands, protected paths, lead notes) from what the repo actually uses, and proposes a permission allowlist. Use when starting to use the kit in a new project or when the SessionStart notice says kit.json is missing.
disable-model-invocation: true
---

# /kit:init - opt this project into the kit harness

The kit hooks do nothing until `.claude/kit.json` exists. Build it from evidence, not guesses.

1. **Discover the real commands.** Read, if present: CLAUDE.md/AGENTS.md, README, CI config
   (`.github/workflows/*`, `.gitlab-ci.yml`), `package.json` scripts, `pyproject.toml`,
   `Makefile`/`justfile`, `Cargo.toml`, `go.mod`, pre-commit config. Prefer the exact commands
   CI runs.
2. **Time them.** Run each candidate once and note the duration.
   - `check`: lint + format-check (+ type-check) that together run in under ~30 s. Runs before
     every stop when files changed.
   - `verify`: the full gate (tests, evals, build). Used by `kit:verifier` and `/kit:go`.
3. **onEdit**: per glob, the formatter/fixer for one file, using `$FILE` (absolute) or `$REL`
   (repo-relative), e.g. `{"glob": "**/*.py", "run": "uv run ruff format -q \"$FILE\""}`. Only
   fast commands (< 5 s). Add validators for structured files the repo has a validator for.
4. **protect**: paths that must never be edited (`read-only`) or never overwritten once written
   (`no-overwrite`), with a `reason`. Take them from the repo's rules (raw data, generated files,
   lockfiles, vendored code, migrations already applied).
5. **shape**: `"ask"` (default: on a brain-dump prompt Claude offers to shape it first),
   `"auto"` (shapes straight away) or `"off"`. A personal default for every project can live in
   `~/.claude/kit.json` as `{"shape": "ask"}`.
6. **context** (keeps long sessions lean): add `"context": {"window": 300000, "warnAt": 0.7,
   "compactAt": 0.8, "handoff": ".claude/handoff.md"}`, put `"autoCompactWindow": 300000` in the project's
   `.claude/settings.json` (create or merge, never drop existing keys), add `.claude/handoff.md`
   to `.gitignore`, and append a `# Compact instructions` section to CLAUDE.md (3-5 lines: keep
   the goal, decisions and user preferences, in-flight work, failing checks and file paths;
   drop tool output already acted on). Skip any part the project already has.
   Also add `.claude/evidence/` (live evidence from `/kit:go` and the verifier) and
   `.claude/overnight/` (run logs of `kit:overnight`) to `.gitignore`. `.claude/review-decisions.md`
   (findings the user declined) stays committed, so every clone's reviews skip them.
7. **lead**: `read` = the 1-3 files a lead should read before planning (backlog, decision log),
   `backlog` = where the next work item comes from, `notes` = one line of project-specific
   orchestration advice.
   For captain mode, optionally: `ship` (`local-only`, `pr` or `pr+babysit`), `parallel` (default
   3), `budget` (`{"items": N}` or `"none"`), `board` (default `.claude/lead/board.md`) and `loops`
   (`[{"name", "every", "run"}]`, e.g. PR babysitting every 10m). Add `.claude/lead/` to
   `.gitignore` unless the user wants the board shared.
8. **Safety.** Explain in three lines: the kit guard is on with `kit.json` (blocks deletes
   outside the repo, pushes to main, discarding uncommitted work, `sudo`, `curl | sh`, reading
   credentials); offer `{"guard": "on"}` in `~/.claude/kit.json` to cover every project, and a
   subagent cap (`guard.agentsAsk`/`agentsDeny`) only if the user wants one. Then ask which
   profile this project uses: **Host** (no OS sandbox) or **Sandbox** (Bash sandbox in
   `.claude/settings.local.json`, written by `/kit-safety sandbox` or the panel). Recommend auto
   mode in the user's `~/.claude/settings.json`; propose, never write it silently.
9. Write `.claude/kit.json`, show it to the user, and explain that it is committed with the repo
   so every clone and every session gets the same gates.
10. **Permissions.** Propose (do not silently add) allow rules in `.claude/settings.json` for the
   read-only and check/verify commands, so long runs are not interrupted. If the built-in
   `/fewer-permission-prompts` skill is available, suggest running it.
11. Confirm the hooks fire: make a trivial edit to a file matching an `onEdit` glob and revert
   it, and report what ran.

Schema:

```json
{
  "check": "fast command, exit 0 = ok",
  "verify": "full command",
  "checkTimeout": 540,
  "maxStopRetries": 3,
  "onEdit": [{"glob": "**/*.py", "run": "...\"$FILE\"...", "timeout": 120}],
  "protect": [{"glob": "data/raw/**", "mode": "no-overwrite", "reason": "raw files are immutable"}],
  "shape": "ask",
  "context": {"window": 300000, "warnAt": 0.7, "compactAt": 0.8, "handoff": ".claude/handoff.md"},
  "lead": {"read": ["docs/backlog.md"], "backlog": "docs/backlog.md", "notes": "..."}
}
```
