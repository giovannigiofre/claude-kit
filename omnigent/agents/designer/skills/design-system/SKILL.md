---
name: design-system
description: Use when a design task needs the project's visual system - find or derive its tokens and DESIGN.md, keep them bound on every edit, and never introduce raw colours or fonts outside them.
---

# Design system

A design system is what keeps the second page looking like the first. Once one is active the
direction is locked: every later edit uses it.

## Find it first

Look for an existing system before making one: `DESIGN.md`, a tokens file, CSS custom
properties in a global stylesheet, a Tailwind theme, a components folder. The project's own
tokens always win over anything in this skill; when you depart from them, say why in the PR.

## Derive one when there is none

Write `DESIGN.md` at the place the project keeps design docs (or the repo root), with these
sections (Open Design's schema, at least seven filled in substance):

1. Visual theme (the one-sentence direction and its mood)
2. Colour palette and roles (`--bg`, `--surface`, `--fg`, `--muted`, `--border`, `--accent`,
   plus success, warn, danger), in `oklch()`
3. Typography (display, body, mono; the scale; line heights)
4. Component styles (buttons and their states, inputs, cards, nav)
5. Layout (container width, grid, section spacing on a 4/8px rhythm)
6. Depth and elevation (shadows, borders, radii)
7. Do's and don'ts for this project
8. Responsive behaviour (what changes at 390px, 768px, 1440px)
9. A short guide for the next agent

Map the tokens onto the project's own mechanism (its CSS variables or Tailwind theme), not a
parallel file nobody imports. Fallbacks for the tokens a brand rarely sets (hover via
`color-mix`, state colours, a spacing scale) are in
`../design-craft/references/open-design/defaults.css`; a neutral example is
`../design-craft/references/open-design/default-DESIGN.md`. With no brand at all, start from
the closest direction in `references/directions.md` and bind its palette verbatim.

## Keep it bound

- No raw hex or new font outside the tokens; derived colours come from `oklch()` of a token.
- A redesign changes the system first (DESIGN.md and tokens), then the pages.
- The directions' references (Linear, Monocle, ...) set a mood. Never copy a brand's palette,
  typefaces or layout.
