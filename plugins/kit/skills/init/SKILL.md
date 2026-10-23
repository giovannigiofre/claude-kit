---
name: init
description: Sets up the kit in the current project - writes .claude/kit.json (fast check, full verify, per-file onEdit commands, protected paths, coordinator settings) from what the repo actually uses, a project e2e skill that says how to exercise the app, and proposes permissions and a safety profile. Use when starting to use the kit in a project or when the SessionStart notice says kit.json is missing.
disable-model-invocation: true
---

# /kit:init: opt this project into the kit

The kit's hooks do nothing until `.claude/kit.json` exists. Build it from evidence: what the repo
and its CI actually run, not guesses.

1. **Find the real commands.** Read CLAUDE.md or AGENTS.md, the README, CI config
   (`.github/workflows/*`, `.gitlab-ci.yml`), `package.json` scripts, `pyproject.toml`,
   `Makefile` or `justfile`, `Cargo.toml`, `go.mod`, pre-commit config. Prefer what CI runs.
2. **Time them** (run each once):
   - `check`: lint, format check and type check that together take under about 30 s. It runs
     before Claude stops whenever files changed.
   - `verify`: the full gate (tests, evals, build): what "done" means for a thread, `/kit:go`
     and the overnight runner.
3. **onEdit**: per glob, a fast (< 5 s) formatter or validator for one file, using `$FILE`
   (absolute) or `$REL` (repo-relative), e.g.
   `{"glob": "**/*.py", "run": "uv run ruff format -q \"$FILE\""}`.
4. **protect**: paths that must never be edited (`read-only`) or never overwritten once written
   (`no-overwrite`), each with a `reason`, from the repo's rules (raw data, generated files,
   vendored code, applied migrations).
5. **lead** (the coordinator): `read` (1-3 files to read before planning: backlog, decision
   log), `backlog`, `notes` (one line of project-specific advice), and optionally `ship`
   (`local`, `pr` or `pr+fix`), `parallel` (default 3), `budget` (`{"items": N}` or `"none"`),
   `loops` (`[{"name", "every", "run"}]`). Writing `ship` here is the user's standing go-ahead
   for threads to push and open PRs, so ask before setting it to `pr` or `pr+fix`.
6. **An e2e skill.** Write `.claude/skills/e2e/SKILL.md` (about 20 lines, description "How to run
   and exercise <project> end to end to verify a change"): how to start the app or services
   (commands, ports, env, seed data), how to exercise each surface the way a user does (the
   CLI command, the API call, the page and the browser tool to drive it), what output or
   screenshot counts as proof, and the known traps. This is the knowledge a model can't infer,
   and threads, `/kit:go` and the verifier rely on it. Try each step once while writing it.
   Threads start in a fresh worktree: the skill says how to set one up (install dependencies,
   migrate a local database), and untracked files the app needs to run (`.env`, local config)
   go in `.worktreeinclude` (gitignore syntax), which Claude Code copies into every new
   worktree.
7. **gitignore**: `.claude/evidence/` (proof from `/kit:go` and threads), `.claude/overnight/`
   (run logs) and `.claude/lead/` (the board), unless the user wants the board shared.
   `.claude/review-decisions.md` stays committed so every clone skips declined findings.
8. **Compaction**: add a short `# Compact instructions` section to CLAUDE.md (keep the goal,
   decisions and user preferences, in-flight work and branches, failing checks and file paths;
   drop tool output already acted on), unless there is one.
9. **Safety**, in three lines: the kit guard is on with `kit.json` (blocks deletes outside the
   repo, pushes to main, discarding uncommitted work, `sudo`, `curl | sh`, reading credentials;
   best effort, it reads shell text). Then ask which profile the project uses: **Host** (no OS
   sandbox) or **Sandbox** (`/kit-safety sandbox` or the kit panel).
10. **Permissions and authorship**: propose (never write silently) allow rules in
    `.claude/settings.json` for the read-only, check and verify commands; suggest the built-in
    `/fewer-permission-prompts`. The user is the only author of commits and PRs: in the same file
    set `"attribution": {"commit": "", "pr": "", "sessionUrl": false}` (merge, never drop keys), and
    check that `git config user.name` and `user.email` are the user's own, not an AI's. The guard
    blocks AI credits and AI identities anyway; the setting keeps Claude from writing them.
11. **Domain plugins**: if the repo has a frontend, or code that calls an LLM, offer `kit-ui` or
    `kit-llm` for this project now (`kit:extras` explains the install).
12. Write `.claude/kit.json`, show it, and explain that it is committed so every clone and session
    gets the same gates. Confirm the hooks fire: make a trivial edit to a file matching an
    `onEdit` glob, revert it, and report what ran.

Schema:

```json
{
  "check": "fast command, exit 0 = ok",
  "verify": "full command",
  "checkTimeout": 540,
  "maxStopRetries": 3,
  "onEdit": [{"glob": "**/*.py", "run": "...\"$FILE\"...", "timeout": 120}],
  "protect": [{"glob": "data/raw/**", "mode": "no-overwrite", "reason": "raw files are immutable"}],
  "guard": {"protectedBranches": ["main"], "allowCommands": []},
  "lead": {"read": ["docs/backlog.md"], "backlog": "docs/backlog.md", "notes": "...", "ship": "pr", "parallel": 3}
}
```
