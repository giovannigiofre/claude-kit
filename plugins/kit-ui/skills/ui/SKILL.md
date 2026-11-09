---
name: ui
description: Routes any UI or frontend design task between the impeccable and taste skills so they work as one team, with one precedence rule and one done-check - new page or screen, redesign, restyle, polish, critique, accessibility or design audit, landing page, dashboard, app screen. Use it before invoking impeccable or design-taste-frontend directly, whenever a task changes how an interface looks or behaves, even if the user only says "make it look better", "fix this page" or "it looks generic". Not for backend-only work or a new brand (that is kit-ui:brand).
argument-hint: "[what to design or improve; empty = ask]"
---

# kit-ui:ui: impeccable and taste as one team

Task: $ARGUMENTS

Two strong design skills overlap: both trigger on "design, redesign, polish, review". Run as
two full flows they fight (taste fails the monospace and small caps a design system may use on
purpose; it wants 8+ moving elements and 4+ photos; impeccable wants one authored moment). This
recipe gives each the job it is best at, so the result has taste's art direction and measuring
tools and impeccable's product sense, accessibility and critique. Load the skill each step names;
never run both skills' complete flows on the same task.

- **impeccable** leads product UI: app screens, forms, flows, accessibility, critique, audit,
  design-system work. It reads the project's PRODUCT.md and DESIGN.md first.
- **taste** leads art direction of public marketing pages (landing, product page, one-pager),
  and lends its real-browser inspector as a meter for any UI: screenshots at 1440/768/390,
  overflow, contrast, layout faults.

## 0. Preconditions

- Find the skills: impeccable is vendored per project (`.claude/skills/impeccable`, Apache-2.0);
  taste is the plugin `taste-skill@claude-kit` (MIT), installed per project. Say which are present.
  - impeccable missing: offer to copy the vendored folder from a repo that has it, with LICENSE and
    UPSTREAM_COMMIT, and ask before committing. Until then use taste for marketing pages and, for app
    UI, the Vercel Web Interface Guidelines plus a manual accessibility pass.
  - taste missing: skip its steps; impeccable alone covers every task type below.
- Run impeccable's scripts with `IMPECCABLE_NO_TELEMETRY=1 DO_NOT_TRACK=1`; never send the
  `concept-seed` telemetry ping. taste needs Node 22+ and a local Chrome/Edge for its inspector;
  its `assets.mjs` downloads pictures from open archives, so ask before running it in a project
  with a privacy or offline rule.
- Background session: EnterWorktree before the first file write. Scratch output (`.taste-skill/`,
  `.impeccable/`) stays gitignored.

## 1. Precedence when the two disagree

1. The user's words.
2. The project's CLAUDE.md / AGENTS.md.
3. The project's design system: DESIGN.md, tokens (e.g. `globals.css`), PRODUCT.md, brand fonts.
4. impeccable's craft floor and the surface's mode (Persuade, Operate, Read, Experience).
5. taste's house rules, as warnings only, and only on public marketing pages.
6. Either skill's defaults.

A rule from a lower level never overrides a deliberate choice from a higher one. Read the design system before calling anything a deliberate choice: quote the line. Example:
One project's DESIGN.md wants stamps in uppercase Schibsted 800 and monospace only for data
(dates, protocol numbers), so taste's micro-label rule is overridden for stamps while a mono label
used as decoration is a real defect. Run taste with `--allow` only for the rules the design system
breaks on purpose, and say so in the report. Never let a taste draw replace existing tokens: pass `--keep palette,type`.

**Name the defaults you reject.** Asked for design without direction, current models fall back on
a few house styles, and "avoid a generic AI look" only swaps one default for another. When a
result looks generic, list the specific patterns to drop (e.g. cream background, italic accent
words in headlines, numbered "01/02/03" section labels, monospace labels, pill buttons), check
which styles the next result used instead, and extend the list.

## 2. Pick the task type, then follow its row

| Task | Lead | Steps |
|---|---|---|
| **A. New public marketing page, no design system** | taste for direction, impeccable for product sense | impeccable `context` + `init` (writes PRODUCT.md) → taste run steps 1-5 (inventory, argument, `draw.mjs --options 3`, idea sentence, copy deck) → commit the chosen direction as DESIGN.md with impeccable `new-work` → build after reading impeccable `craft-floor.md` → done-check |
| **B. New page or screen in a product with a design system** (most app work) | impeccable | impeccable `context --target <main stylesheet>` → `new-work` "extend an existing surface" in the right mode → `shape` if the UX is unclear → build with project tokens only → optionally borrow patterns from taste `references/app-screens.md` (KPIs, tables, forms, empty and error states), design system first → done-check. No taste `draw`. |
| **C. Polish, critique or audit of existing UI** | impeccable | impeccable `critique` then `audit` → fix with the commands they name (`polish`, `layout`, `typeset`, `harden`, `clarify`, `adapt`) → for a marketing page add taste's before/after inspection (`inspect.mjs --out .taste-skill/before` and `after`) → done-check |
| **D. New brand or rebrand** | `kit-ui:brand` | Use kit-ui:brand unchanged. Optionally one taste `draw.mjs --options 3` as an extra source of palette and type candidates, labelled as such. |

Mockups and prototypes on a Design canvas (Artifact "Design" type) are task B or A by content:
the canvas is only the medium.

## 3. Done-check (every type except D, which has its own)

1. **Measure:** taste `inspect.mjs` (`--app` for app screens, with the `--allow` list from §1) at
   1440 and 390; read every screenshot. Without taste: Playwright or Chrome screenshots at the same widths.
2. **Fit the headings:** a heading sized by eye is the most common phone defect (a 48px title can
   fill three quarters of the first screen). Never guess it: run
   `node <this skill>/scripts/fit-heading.mjs <page> --max <design-system max px> --lines 3 --share 0.33`
   for each page or screen h1. It finds, in a real browser, the largest size that keeps the heading
   within 3 lines and a third of the first screen at 390 and 1440, and prints the `clamp()` to use.
   Exit 1 means the text is too long even at the minimum: shorten it. Content headings (a quiz
   question, an article title) may use `--lines 5`. taste's 2-line limit is a marketing-hero rule.
3. **Detect:** `impeccable detect --json` on the changed files.
4. **Review:** impeccable `critique` (design review, personas incl. an accessibility-dependent
   user) and `audit` (a11y, performance, theming, responsive); the health score must not drop.
5. **Guidelines:** the Vercel Web Interface Guidelines pass, as in kit-ui:brand.
6. **Project gate:** the project's own checks (`.claude/kit.json` `verify`, e2e flows).

Fix in one batched round, re-run the checks once. If something still fails, report it instead of
looping (impeccable's bound, not taste's three rounds).

## 4. Report

```
TYPE: A | B | C (lead: impeccable | taste)
PRECEDENCE CALLS: <each conflict and which level won, e.g. "kept mono stamps: DESIGN.md over taste">
CHANGED: <files or artboards>
CHECKS: inspect <n FAIL/WARN, allowed rules> · headings <px at 390/1440, lines> · detect <n> · critique <score> · audit <score> · guidelines <n issues> · verify <pass/fail>
SCREENSHOTS: <paths at 1440 and 390>
OPEN: <what is left for the user to decide>
```
