---
name: brand
description: Creates a new brand or rebrands an existing app as three brand-board options on a Design canvas, then applies the chosen one to the code and sweeps every leftover of the old brand. Uses the impeccable skill for the method, the Artifact "Design" type for the canvas, and the Vercel Web Interface Guidelines as a final review. Use when the user says "rebrand", "new brand", "brand options", "logo and palette", or runs /kit:brand.
argument-hint: "[product or app name; empty = the current repo]"
---

# /kit:brand: brand options to an applied design system

Input: $ARGUMENTS (if empty, the app in the current repo).

This recipe orders other tools. It never overrides the project's CLAUDE.md or AGENTS.md.
Where it departs from impeccable's or the Design type's own flow, the departure is written
here on purpose; say so in your reply.

## 0. Preconditions

- `impeccable` must be available as a project skill (`.claude/skills/impeccable`, Apache-2.0,
  `adopted-project` in the kit CATALOG). If the repo lacks it, copy the vendored folder from a repo
  that has it, with its LICENSE and UPSTREAM_COMMIT, and ask the user before committing it.
- Run impeccable's scripts with `IMPECCABLE_NO_TELEMETRY=1 DO_NOT_TRACK=1`. `concept-seed` calls an
  API and asks for a telemetry ping; never send it.
- Background session: call EnterWorktree before the first file write.
- Scratch files go in a gitignored folder **inside the repo** (e.g. `.impeccable/tmp/brand/`).
  The Artifact tool refuses files outside the working directory.

## 1. Brief: two AskUserQuestion rounds, before any design work

Round 1: scope (full rebrand / refresh / logo only); personality (multi-select, e.g. "Bold & modern",
"Warm & human", "Calm & trustworthy", "Playful"); name (fixed, open, or changing to a new one);
mark + wordmark or wordmark only; colour (free, or constraints to keep).

Round 2: delivery (brand-board artifact, recommended, or files only); fonts (Google Fonts only, or
licensed allowed); mark concept (let the designs decide, or a given idea); modes (light only, or light + dark).

If the brief is pre-filled (a test, a pinned brief), skip the questions and say so; that also
answers impeccable's `AUTONOMY_DIRECTIVE_CHECK`.

## 2. Method: impeccable

1. Invoke `impeccable`. Run `scripts/impeccable context --target <main stylesheet>` once (loads
   PRODUCT.md and DESIGN.md), then read `reference/new-work.md` and `reference/craft-floor.md`.
2. Derive seven directions from things the audience already knows from daily life, and rank them.
   The product name's literal reading may take at most one of the seven.
3. Run `scripts/impeccable concept-seed --scope direction --mode persuade` and follow the roll:
   - option A = the direction the roll assigns;
   - option B = impeccable's own top pick;
   - option C = the strongest of the challengers the roll deals (it deals up to six).
   Write a one-line verdict for every other challenger.
4. Respect the craft-floor bans (no eyebrow labels, no gradient text, AA contrast) and avoid the
   over-used fonts list.

For a brand job this replaces impeccable's decision page, direction contract and comp round.

## 3. Canvas: Artifact "Design" type

1. `Artifact action: quickstart, intent: design`, then create the canvas from the Design type.
   Write `canvas.json` first, then one board per publish.
2. One overview board (the three options side by side, challenger verdicts in one line each) plus
   one 1200-wide board per option, with the height fitted to the content. Each option board holds:
   logo on light and dark; app icons at 160/88/48/32; palette with a role per colour (base, paper,
   values, action, source, links/focus); type pairing; core components; a homepage mock using real
   product copy. Longer rationale goes in your reply, not on a board.
3. One inspect pass in a browser (zoom to fit: the canvas can open blank). Check every mark at 16
   and 32 px and for misreadings: flags, national or official symbols, competitors' logos. This
   recipe overrides the Design type's "never verify" rule for this one pass.
4. Give the user the canvas link and ask which option, and what to change.

## 4. Iterate on the chosen option

Change only the chosen board and republish. Make changes as tweakable values where the canvas
allows (e.g. wordmark weight) so the user can compare. Typical feedback: use the small-size mark
at every size when the detailed one reads worse; loosen a display font that feels too tight.

## 5. Apply (only after the user says "apply it")

1. **Design system.** New DESIGN.md (tokens, type, mark geometry, usage rules), and regenerate
   `.impeccable/design.json` with impeccable's `document` step, or delete it if stale. Update PRODUCT.md
   if the name or brand commitments changed.
2. **Code.** Tokens in the main stylesheet; font loading (e.g. `next/font`); the header mark component.
3. **Icons and OG from one geometry source.** Find the repo's icon generator, or write one. If the
   OG images are static files, add a generator (build fonts, text from the dictionaries). Running it
   twice must give byte-identical files.
4. **Brand sweep (mandatory).** Grep for the old hex values (and their `rgb()` triplets in shadows),
   the old font names, the old name and domain, and comments naming old colours. Typical hiding places:
   `themeColor`/`theme-color` meta, the web manifest, CSS modules, admin UI, the e-mail renderer and
   its generated templates (regenerate; flag templates the owner pastes into a dashboard by hand),
   `llms.txt`, SEO content, LLM prompts. Prefer importing tokens over copying hex values.
5. **Name change.** If the name changed, list every place it appears (dictionaries, metadata
   template, site config, e-mail copy, prompts, domain) and ask before renaming beyond the UI wordmark.
6. **Contrast of new tokens in inherited roles.** Old token names keep old usages alive: recheck
   every new colour in each role it now fills (e.g. a focus ring on the page ground needs 3:1).
7. **Verify.** Build, lint and tests (frontend and any backend that renders the brand, e.g. e-mails);
   `impeccable detect --json` on the changed files; screenshots at 1440 and 390 px wide, with a
   headless script (the Chrome extension cannot resize to 390). Data-driven pages need their API
   running; otherwise say which surfaces were not seen.
8. **Review: two checks that barely overlap; run both.**
   - impeccable `audit` (reference/audit.md): token contrast, touch targets, unused font weights, brand drift.
   - Vercel Web Interface Guidelines: fetch
     `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` and apply it
     to the changed files. It catches skip links under sticky headers, missing `scroll-margin-top`,
     safe-area insets and `translate="no"` on the wordmark. For non-English locales skip its Title Case,
     curly-quote, "…"-placeholder and "&" rules, and treat a brand-coloured `theme-color` as intended.
   Fix what the rebrand introduced; list older findings for the owner.

## Done when

- The user has picked an option and its changes are on the canvas.
- After "apply it": tokens, fonts, icons and OG are in the code; build, lint and tests pass; the
  brand-sweep grep returns nothing except leftovers the owner approved; both reviews ran, and the
  findings the rebrand introduced are fixed.

Origin: the myinsurance → Polizzen rebrand (2026-10-16), tested end to end with a fictional brand the same day.
