---
name: design-brief
description: Use at the start of any design task, before writing UI code - decide what to ask and what to assume, lock the brand source and one visual direction, and write DESIGN-BRIEF.md.
---

# Design brief

Good design work starts with the gaps that would change the result, not with a questionnaire.
Method from Open Design's discovery phase (see `../design-craft/references/open-design/UPSTREAM.md`).

## 1. Ask only what changes the outcome

- Skip questions entirely for a local edit, or when the brief says to start now.
- Otherwise ask 1-3 questions (5 at most), in this priority: task type, audience, goal,
  platform, scale, constraints. Each question offers choices with your recommended answer
  first. Never ask about style when the project already has a design system: it is bound.
- You run headless for the lead: put the questions in your report as OPEN and stop, unless
  the brief already answers them or says to assume. When you assume, say which defaults you
  applied.

## 2. Lock the brand source

- A source was given (the project's CSS, a brand guide, a URL, a screenshot): extract its
  real values, never guess colours. In a repo that means the CSS custom properties, the
  Tailwind theme, the layouts and the font-family declarations: rank colour literals by how
  often they appear, assign the roles (`--bg`, `--surface`, `--fg`, `--muted`, `--border`,
  `--accent`), record the display, body and mono stacks and 3-5 posture rules you observe.
- A source type was named but nothing supplied: ask for it (OPEN) and stop.
- Otherwise: use the project's design system (skill `design-system`), or pick the closest of
  the five directions in `../design-system/references/directions.md` yourself.

## 3. State the direction in one sentence, then write the brief

Before any code, write `DESIGN-BRIEF.md` in the task's evidence folder
(`.kit/evidence/<branch>/`), under 60 lines:

- who it is for and what the page must make them do;
- the sections in order, with the real words where they matter;
- the direction in one sentence ("editorial, serif display, paper and ink, one plum accent");
- the tokens it binds (from the project, or the chosen direction);
- phone first: what the 390px layout is, not a squeezed desktop;
- the defaults you assumed.

When the lead asked for options, write 2-3 directions that differ on purpose (type, palette,
layout posture), each a short paragraph, and build each on its own branch.
