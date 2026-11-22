---
name: design-craft
description: Use while building or changing any UI - the concrete numeric rules, banned "AI look" patterns and layout-integrity rules that make a page look designed rather than generated.
---

# Design craft

These rules are applied while writing, not checked afterwards: that is where Open Design's
quality comes from. Conflicts resolve in this order: accessible and readable > usable >
clear hierarchy > style > decoration.

## Baseline numbers

- Contrast: body text at least 4.5:1, large text and icons 3:1; check dark mode separately.
- Body text at least 16px on screen, line height 1.5-1.75, line length 65-75 characters.
- Spacing on multiples of 4 or 8. Touch targets at least 44px.
- Motion 150-300ms; exits take 60-70% of the entrance.

## Colour and type

- The palette comes from the brand, the domain or the chosen direction. Derived colours via
  `oklch()` from tokens; no invented hex.
- One accent colour, at most twice per screen. A complete palette has primary, a
  domain-relevant accent and state colours.
- Display and body typefaces differ (one family only for utilitarian, data-dense work).
- One decisive visual flourish per design; three is noise.

## Banned unless the brand requires it (the "AI look")

Purple gradient washes; emoji as icons; the rounded card with a coloured left border; hover
that makes text grey or lighter; hand-drawn SVG people; an icon beside every heading; Inter,
Roboto, Arial or Fraunces as display type (fine for body); beige or cream backgrounds by
default; invented metrics and filler copy; controls that only exist for the designer.
Details and the reasons: `references/open-design/craft/anti-ai-slop.md`.

## Actions and states

- One primary button per action per viewport; a long page may repeat it once at the end.
  Other entry points are secondary, ghost or links, with different words.
- Every state (hover, focus, active, disabled) defines foreground and background as a pair;
  contrast never drops below the default state (only disabled may). Hover moves the
  background 0.06-0.12 in OKLch lightness, or the border, shadow or position. Every
  focusable element has a visible `:focus-visible` ring.

## Layout integrity (hard rules)

- No accidental overlaps, no clipped text, no `white-space: nowrap` forcing text into
  neighbours, no 1-2 word orphan on a last line (fix the container first).
- Mobile never scrolls horizontally; the 390px layout is a redesign, not a squeeze.
- Images keep their intrinsic ratio (`width`/`height` or `aspect-ratio`); `object-fit: cover`
  only for decorative fills. Overlays sit in one corner, inside the image, off faces.

## Real content

Real things use their real images and names; no generated stand-ins, no invented products or
numbers. When a value is missing, an honest labelled placeholder, named in the handoff.
Images live in the project, never hotlinked.

## When to read more

| Working on | Read |
|---|---|
| any page | `references/open-design/craft/anti-ai-slop.md`, `color.md`, `typography.md` |
| headings, long text | `references/open-design/craft/typography-hierarchy.md` |
| empty, loading, error states | `references/open-design/craft/state-coverage.md` |
| forms | `references/open-design/craft/form-validation.md` |
| accessibility | `references/open-design/craft/accessibility-baseline.md` |
| motion | `references/open-design/craft/animation-discipline.md` |
| flows, navigation, choices | `references/open-design/craft/laws-of-ux.md` |
| section layouts for a landing page | `references/open-design/layouts.md` |
