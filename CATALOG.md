# Catalog of third-party skills and tools

Every outside skill, plugin or tool that was considered for the setup gets one entry here,
whatever the outcome. The procedure is in [README §4](README.md#4-add-third-party-skills-and-tools).

Status values:

- `adopted-user`: installed at user scope through the kit
- `adopted-project`: enabled only in the projects that need it
- `vendored`: an unchanged copy inside the kit, with its LICENSE and UPSTREAM_COMMIT
- `trial`: local scope in one project, decision pending
- `rejected`: with the reason

| Tool | Source | Status | Scope / where | Decided | Reason |
|---|---|---|---|---|---|
| systematic-debugging | obra/superpowers `skills/systematic-debugging` (MIT) | vendored | kit (`kit:systematic-debugging`) | 2026-10-16 | Root-cause-first debugging process. Copied unchanged from myinsurance's vendored copy. |
| verification-before-completion | obra/superpowers `skills/verification-before-completion` (MIT) | vendored | kit | 2026-10-16 | "Evidence before assertions". Matches the kit's verifier principle. |
| impeccable | (frontend design skill; already vendored in myinsurance, Apache-2.0) | adopted-project | repos with a frontend only (myinsurance `web/`) | 2026-10-16 | Useful only for UI work. At user scope it would cost context in every backend-only session. |
| ponytail | DietrichGebert/ponytail, pinned at `f329330e` (v5.3.0, MIT) | trial | local scope in myinsurance from 2026-10-16, about one week; marketplace entry `ponytail@claude-kit` | 2026-10-16 | Reviewed 2026-10-16. Hooks: SessionStart injects the ruleset plus a repo map of at most 2,000 characters from `git ls-files`; SubagentStart injects the ruleset into subagents; UserPromptSubmit tracks the mode. No Stop/PostToolUse/PreToolUse hooks, so no clash with the kit. A "band" module writes one row per turn to `~/.config/ponytail/band/<project>.csv` and a local `board.html` (on by default, local only). An optional webhook is empty by default, so nothing leaves the machine unless configured. Needs node. To decide after the trial: is code smaller without lost correctness? What does `claude plugin details ponytail` show as the context cost? Keep the ledger, or turn it off with `/plugin configure ponytail`? |
| caveman | JuliusBrussee/caveman (skill: telegraphic output) | rejected | none | 2026-10-16 | Cuts output tokens only, a small share of cost; the project withdrew its 75 % claim, and one user reported about USD 1/week saved on a USD 100 plan. Makes reports and REPORT.md harder for a human to decide from. Kit workers already return compact structured results. |
| pi (pi.dev) | pi-mono monorepo (Mario Zechner), see pi.dev | rejected (not an addition) | none | 2026-10-16 | A separate coding agent with its own TypeScript extension system; it replaces Claude Code rather than plugging into it. Idea borrowed: minimal, visible context (check with `claude plugin details`). |
| anthropics/skills `pdf`, `docx`, `pptx`, `xlsx` | anthropics/skills | rejected for vendoring | marketplace install only if needed | 2026-10-12 | Source-available licence forbids copying (from myinsurance `docs/22-skills.md`). |
| playwright-stealth-verify | liarjsdev/liarjs-skills | rejected | none | 2026-10-16 | A bot-detection evasion skill; conflicts with polite-client rules (myinsurance AGENTS.md rule 5). |
