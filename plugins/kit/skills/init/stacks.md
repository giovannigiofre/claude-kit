# Gates by stack: what `/kit:init` proposes, and why

Read by `/kit:init` step 1. Each row is a check a machine runs; propose only the ones the repo
has the tools for, time each once, and say what the repo lacks. Sources: the evidence collected
for kit 2.0 (`docs/proposta-kit-2.0.md`): agent PRs leave 27 % of changed Python lines and 61 %
of changed Java lines executed by a test (Dipongkor et al. 2026), duplicated blocks grew 81 % in
AI-era commits (GitClear 2026), a planted-test study found suites with 100 % line coverage that
missed a fifth of planted bugs. Hence diff coverage and duplication in `verify`, affected tests
in `check`, and secrets scanning in both.

Principle: `check` under about 30 s and diff-scoped (`KIT_CHANGED_FILES` holds the files this
branch touched, shell-quoted: `echo "$KIT_CHANGED_FILES" | xargs -r <tool>` keeps names with
spaces whole); `verify` is the whole truth and may take minutes; `onEdit` only formats or runs a
single-file checker; `protect` covers what a thread should never rewrite.

## Next.js (App Router) + Supabase, deployed on Vercel or Cloudflare

| Gate | Command | Catches | Note |
|---|---|---|---|
| check | `npx next typegen && npx tsc --noEmit` | type errors, route types | `"incremental": true` in tsconfig; `next build` no longer lints in Next 16 |
| check | `npx eslint --cache $KIT_CHANGED_FILES` with `eslint-config-next/core-web-vitals` (+ `/typescript`) | `<img>`, `<a>` to pages, hooks rules | `next lint` is gone in Next 16: flat `eslint.config.mjs` |
| check | `npx vitest run --changed origin/main --passWithNoTests` | regressions on the diff | affected tests only; the full suite is in verify |
| check | `gitleaks protect --staged --no-banner` | secrets about to be committed | under a second; the guard blocks `.env` and key files anyway |
| verify | `npx next build` | server/client boundaries, build errors | the gate for "done" |
| verify | `npx vitest run --coverage && diff-cover coverage/lcov.info --compare-branch origin/main --fail-under 80` | untested changed lines | diff-cover is a Python tool (`uvx diff-cover`) |
| verify | `npx knip` | unused files, exports, dependencies | pin its version; medium false positives on dynamic imports |
| verify | `npx jscpd src --threshold 3 --min-tokens 50` | duplicated blocks | the cheapest answer to copy-paste growth |
| verify | `npx playwright test --grep @smoke` | the flows a user takes | keep to a smoke set; the `verify` skill says how to drive the app |
| verify | `supabase test db && supabase db lint --fail-on warning` | RLS policies (pgTAP), PL/pgSQL errors | needs the local stack (`supabase start`) |
| verify | `supabase gen types typescript --local > src/types/database.ts && git diff --exit-code -- src/types/database.ts` | stale committed types | the committed types are what the app compiles against |
| onEdit | `**/*.{ts,tsx,js,jsx,json,css,md}` → `npx prettier --write "$FILE"` | formatting | or `biome format --write` |
| onEdit | `supabase/migrations/*.sql` → `squawk "$FILE"` | lock hazards (an index without `concurrently`, a `not valid` constraint) | about 1 s; `.squawk.toml` for the Postgres version |
| onEdit | `supabase/migrations/*.sql` → a 5-line script: `CREATE TABLE` without `ENABLE ROW LEVEL SECURITY` in the same file fails | tables created without RLS | the defect `get_advisors` reports after the fact |
| protect | `supabase/migrations/**` no-overwrite | applied migrations are immutable: add a new file | |
| protect | `src/types/database.ts` (or `types.gen.ts`) read-only | generated: run the types script | |
| protect | `.env*` read-only | secrets are set by hand | |

Worktrees: `.worktreeinclude` lists `.env.local`, `.env`, `supabase/.env`;
`"worktree": {"symlinkDirectories": ["node_modules"]}` in `.claude/settings.json`. A thread needs
its own database: Supabase CLI 2.119+ `supabase stack` (experimental: `[experimental] stack =
true` in `config.toml`, fixed ports removed) gives each worktree its own ports and data, then
`supabase status --env --override-name API_URL=NEXT_PUBLIC_SUPABASE_URL,ANON_KEY=NEXT_PUBLIC_SUPABASE_ANON_KEY > .env.local`;
several stacks cost a few GB of RAM each, so `lead.parallel` of 2 or 3. The guard asks before
`supabase db push`, `vercel --prod`, `wrangler deploy` and the other remote changes.

Evidence for a thread: a headless browser (`playwright-cli`, or Playwright MCP `--headless
--isolated`), the Next.js dev server's MCP at `/_next/mcp` (routes, compilation issues, server
logs), `logging.browserToTerminal` in `next.config`; Supabase logs through the read-only MCP
(`?project_ref=<dev ref>&read_only=true`) or the local container. Never a production project ref.

## Python (FastAPI, pipelines, data), on GCP

| Gate | Command | Catches | Note |
|---|---|---|---|
| check | `uv run ruff check $KIT_CHANGED_FILES && uv run ruff format --check $KIT_CHANGED_FILES` | style, bugbear, security basics | rule sets `E,F,I,UP,B,SIM,C4,PT,RUF,S`, `C901` at 15; `S101` ignored in tests; never `ALL` |
| check | `uv run pyright` | types | strict where the code is typed; `basedpyright` is the same engine |
| check | `uv run pytest --testmon -q -x` | regressions on the diff | can miss an affected test; the full suite is in verify |
| check | `gitleaks protect --staged --no-banner` | secrets | |
| verify | `uv run pytest -q --cov=src --cov-report=xml && uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 80` | untested changed lines | |
| verify | `uv run lint-imports` | layer contracts (import-linter) | a `[tool.importlinter]` with 2-3 contracts is enough |
| verify | `uv run vulture src --min-confidence 80` | dead code | whitelist FastAPI routes and fixtures |
| verify | `uv run deptry . && uv run pip-audit` | missing, unused, vulnerable dependencies | |
| verify | `uv run bandit -q -r src -c pyproject.toml` | injection, subprocess, yaml.load | medium false positives: configure, don't disable |
| onEdit | `**/*.py` → `uv run ruff format -q "$FILE" && uv run ruff check -q --fix "$FILE"` | formatting, autofixable rules | the full checker output goes back to Claude: keep it readable |
| protect | `alembic/versions/**` no-overwrite | applied migrations are immutable | |
| protect | `data/raw/**` no-overwrite | raw data is immutable | |
| protect | `.env*` read-only | secrets are set by hand | |

Property tests (`hypothesis`) for parsers, pricing and date logic belong in the suite, not in a
gate line. Mutation testing (`mutmut`, `cosmic-ray`; `stryker --since` for TypeScript) is a
nightly CI job, not a gate: minutes to hours, and the evidence for it is thin.

## A mixed monorepo

- `check`: `turbo run check --affected && gitleaks protect --staged` (each package defines `check`
  as above); without turbo, the union of the two `check` lines, each run from its package.
- `verify`: `turbo run verify`, then root-level `knip`, `jscpd`, `osv-scanner -L pnpm-lock.yaml -L
  services/api/uv.lock`.
- `onEdit`: the globs from both stacks, each command run from the package that owns `$REL`.
- `protect`: the union of both.

## What not to put in a gate

- A linter's full rule set turned on at once: start from `E,F`, add `B`, then what the repo's
  failures justify.
- Generic SAST presets (`semgrep --config p/default`): on LLM-written code they mislabel a large
  share; keep 4-6 in-repo rules that name real defects (service-role key in client code, a
  `"use server"` export with no auth call, `allow_origins=["*"]`).
- Lighthouse CI and bundle budgets: noisy on preview deploys; CI-only, on a schedule.
- Anything that needs a prompt or a paid model: deterministic gates only.
