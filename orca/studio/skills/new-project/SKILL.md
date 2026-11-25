---
name: new-project
description: Use in Studio when the owner has a new idea or wants a new product - shape it into a brief with research, get one approval with the repo choices, create the GitHub repo and a scaffold, then hand the project off to its own conversation (onboard-repo).
---

# New project, from idea to its own conversation

Studio is where ideas live before they are projects: `~/Documents/studio/ideas/<slug>/`, one
folder per idea, committed to Studio's local git as you go. An idea can stay there for weeks.
Becoming a project is the owner's call, never yours.

## 1. Shape the idea

- Ask one or two rounds of multiple-choice questions (who it is for, the one job it does, what
  is out), as the kit's shape method does. Stop asking when you could write the brief.
- In parallel, read-only: `researcher` on competitors, prior art, stack options, and names
  with free domains; `seo` on what people search for in this space and how hard it is.
  Their reports go to the idea folder (`research.md`, `search.md`), with sources.
- Write `brief.md` in the idea folder: problem, user, the first version and what is out of
  it, how we will know it is done, stack, name candidates.

## 2. One approval

When the owner wants to make it a project, send one message with everything that needs them,
each with your suggestion:
- the brief, in five lines (the full file is in Studio);
- the name;
- where the repo goes: list the owner's account and their orgs (`gh api user --jq .login`,
  `gh org list`). Always ask, there is no default;
- visibility: private or public. Always ask, there is no default;
- who merges (`user` or `agent`) and whether it gets the weekly check (onboard-repo needs
  both);
- whether to start the visual direction now.

## 3. Create it

On the owner's yes:
1. `gh repo create <owner>/<name> --<visibility> --add-readme --description "<one line from
   the brief>"`, then `gh repo clone <owner>/<name> ~/Documents/repositories/<name>`. The repo
   starts with only a README, so the scaffold goes through a PR like everything else.
2. Visual direction asked for: `designer` in parallel on two or three directions as static
   previews in the idea folder, with screenshots at 390 and 1440px. The chosen one becomes the
   project's DESIGN.md and tokens in a later PR, from the project's own conversation.

## 4. Hand off

Follow `onboard-repo` "In Studio" from step 3, with KIT missing, SCAFFOLD the chosen stack,
STUDIO NOTES the idea folder and BRIEF the approved brief. Record the outcome in the idea folder (`status: project <owner/name>`).
