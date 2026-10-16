---
name: brand
description: Creates a new brand or rebrands an existing app as three brand-board options on a Design canvas, then applies the chosen one to the code. Uses the impeccable skill for the method and the Artifact "Design" type for the canvas. Use when the user says "rebrand", "new brand", "brand options", "logo and palette", or runs /kit:brand.
argument-hint: "[product or app name; empty = the current repo]"
---

# /kit:brand: brand options to an applied design system

Input: $ARGUMENTS (if empty, the app in the current repo).

This recipe is how the myinsurance → Polizzen rebrand was run on 2026-10-16. It orders other
tools; it never overrides the project's CLAUDE.md, AGENTS.md or the impeccable skill itself.

## 0. Preconditions

- `impeccable` must be available (project skill in `.claude/skills/impeccable`, Apache-2.0,
  status `adopted-project` in the kit CATALOG). If the repo lacks it, copy the vendored folder
  from a repo that has it (with its LICENSE and UPSTREAM_COMMIT) and ask the user before committing it.
- Background session: call EnterWorktree before the first file write.
- Scratch files go in a gitignored folder **inside the repo** (e.g. `.impeccable/tmp/brand/`):
  the Artifact tool refuses files outside the working directory, so a system tmp dir fails.

## 1. Brief: two AskUserQuestion rounds, before any design work

Round 1:
- Scope: full rebrand / refresh / logo only.
- Personality (multi-select), e.g. "Bold & modern", "Warm & human", "Calm & trustworthy", "Playful".
- Name: fixed or open; mark + wordmark or wordmark only.
- Colour: free choice, or constraints to keep.

Round 2:
- Delivery: brand-board artifact (recommended) or files only.
- Fonts: Google Fonts only, or licensed allowed.
- Mark concept: let the designs decide, or a given idea.
- Modes: light only, or light + dark.

## 2. Method: impeccable

1. Invoke the `impeccable` skill. Run `scripts/impeccable context --target <main stylesheet>`
   once (loads PRODUCT.md and DESIGN.md), then read `reference/new-work.md` and
   `reference/craft-floor.md`.
2. Derive seven directions from things the target audience already knows from daily life
   (for Polizzen: hiking signposts, Swiss Post letters, Migros price tags, 9th-series banknotes,
   Swiss posters, SBB clock, Jass cards). Rank them.
3. Run `scripts/impeccable concept-seed --scope direction --mode persuade` and follow the roll:
   - option A = the direction the roll assigns,
   - option B = impeccable's own top pick,
   - option C = the challenger the roll deals.
4. Respect the craft-floor bans (no eyebrow labels, no gradient text, AA contrast) and avoid
   the over-used fonts list.

## 3. Canvas: Artifact "Design" type

1. `Artifact action: quickstart, intent: design`, then create the canvas from the Design type.
2. One overview board plus one 1200×3100 board per option. Each board holds:
   logo on light and dark; app icons at 160/88/48/32; palette with a role per colour
   (base, paper, values, action, source, links/focus); type pairing; core components;
   a homepage mock that uses real product content.
3. Give the user the canvas link and ask which option, and what to change.

## 4. Iterate on the chosen option

Make the requested changes on the chosen board only and republish. Typical feedback from
the Polizzen run: use the small-size mark at every size if the detailed one reads worse;
loosen a display font that feels too tight (width up, letter-spacing towards 0).

## 5. Apply (only after the user says "apply it")

- New DESIGN.md (tokens, type, mark geometry, usage rules).
- CSS tokens in the main stylesheet; font loading (e.g. `next/font`).
- Favicon, app icons, OG image generated from the mark.
- Verify in the running app (impeccable's bounded inspect pass: desktop + mobile once, fix, one confirm).

## Done when

- The user has picked an option and its changes are on the canvas.
- After "apply it": tokens, fonts and icons are in the code, the app builds, and the inspect pass is clean.
