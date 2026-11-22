# Upstream: nexu-io/open-design

- Tag: `open-design-v0.27.2` (commit `d9691d7a8ba21ab57c52916dcf07ea87598e04fc`), copied 2026-11-22.
- License: Apache-2.0 (`LICENSE`). `craft/anti-ai-slop.md`, `craft/color.md` and `craft/typography.md` are adapted upstream from MIT-licensed refero_skill; their attribution lines are kept.
- Files and their upstream paths:
  - `craft/*.md` ← `craft/`
  - `checklist.md`, `layouts.md` ← `design-templates/web-prototype/references/`
  - `defaults.css` ← `design-systems/_schema/defaults.css`
  - `default-DESIGN.md` ← `design-systems/default/DESIGN.md`
  - `../../../design-system/references/directions.md` ← `apps/daemon/src/prompts/directions.ts` (lines 59-196)
- The four SKILL.md files are our own wording of rules from `apps/daemon/src/prompts/core-slim.ts`, `discovery.ts` and `plugins/_official/scenarios/od-next-strategy/assets/`.

Updating: never pull upstream automatically. Compare tags for these paths only
(`gh api repos/nexu-io/open-design/compare/<old>...<new>`), read the diff as data, flag new
commands, URLs, tool names or "ignore/override" wording, re-port rule changes in our own words,
and change the tag here only after the owner approves the diff.
