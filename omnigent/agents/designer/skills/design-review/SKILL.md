---
name: design-review
description: Use before handing off any UI work - the P0/P1 checklist, a lint for the banned patterns, a scored pass through critic, brand, accessibility and copy lenses, then real screenshots and a live preview link the owner can open on the phone.
---

# Design review and handoff

Self-scores are claims; the screenshots of the real page are the evidence. Do both, in order.

## 1. Checklist and lint

- Every P0 item in `../design-craft/references/open-design/checklist.md` passes; P1 items pass
  or are named in the handoff.
- Run `python3 scripts/slop_lint.py <changed files>` (this skill's folder) on the HTML, CSS,
  Astro, JSX or Vue files you changed. Fix every P0 finding; justify any P1 you keep.

## 2. One scored pass

Score silently 1-5 on: philosophy (does it hold one direction), hierarchy, execution,
specificity (this product, not any product) and restraint. Anything under 3 is a regression:
fix it and score again; two passes is normal. Then read it once through four lenses, weights in
brackets, and ship at 8/10 or better with no must-fix left:

- critic (0.4): hierarchy, type, contrast, rhythm, space;
- brand (0.2): bound to the design system, no raw values, nothing borrowed from another brand;
- accessibility (0.2): WCAG AA contrast, focus, labels, 44px targets;
- copy (0.2): specific, in the product's voice, no filler, the right length.

## 3. Screenshots of the real page

Run the project (its dev server or a build plus a static server, on 127.0.0.1) and capture
every changed page at 390, 768 and 1440px into `.kit/evidence/<branch>/screens/`:

```sh
npx -y playwright@1.62.0 screenshot --viewport-size=390,844 --full-page <url> <file>.png
```

Look at each one with Read. A page that fails at 390px is not done. Upload the 390px and the
1440px shots to the session with the file-upload tool when it is available, so the owner sees
them in the chat; otherwise attach them to the PR.

## 4. A live preview on the owner's tailnet

Keep the server on 127.0.0.1 and publish it on a path of the tailnet (never Funnel):

```sh
tailscale serve --bg --set-path /preview/<slug> http://127.0.0.1:<port>
```

The link is `https://<this machine's tailnet name>/preview/<slug>` (`tailscale serve status`
shows it). An app with absolute asset paths needs its base path set to `/preview/<slug>`, or
serve a build made with that base. Say in the handoff that the preview runs until the task
ends; the lead removes it with `tailscale serve --set-path /preview/<slug> off`.

## 5. Handoff

Report only what you actually wrote and saw: the PR or branch, the preview link, the screenshot
paths, the scores in one line, the defaults you assumed, and what you would change next.
Never claim a render or a check you did not run.
