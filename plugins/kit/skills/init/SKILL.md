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
6. **lead**: `read` = the 1-3 files a lead should read before planning (backlog, decision log),
   `backlog` = where the next work item comes from, `notes` = one line of project-specific
   orchestration advice.
7. Write `.claude/kit.json`, show it to the user, and explain that it is committed with the repo
   so every clone and every session gets the same gates.
8. **Permissions.** Propose (do not silently add) allow rules in `.claude/settings.json` for the
   read-only and check/verify commands, so long runs are not interrupted. If the built-in
   `/fewer-permission-prompts` skill is available, suggest running it.
9. Confirm the hooks fire: make a trivial edit to a file matching an `onEdit` glob and revert
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
  "lead": {"read": ["docs/backlog.md"], "backlog": "docs/backlog.md", "notes": "..."}
}
```
