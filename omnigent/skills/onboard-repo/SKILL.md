---
name: onboard-repo
description: Use when the owner wants to start working on a repo in Omnigent (an existing one, or one new-project just created), or when a conversation's first message starts with HANDOFF. Studio side - find or clone the repo, collect the project's choices, register it and open its first conversation with a handoff. Project side - set up the kit, write the project card, board and lessons.
---

# Onboard a repo

Two halves: the first runs in Studio, the second in the new project's own conversation.

## In Studio: register and hand off

1. **Find the repo.** A path, `owner/name` or URL. Not on this Mac: `gh repo clone <owner>/<name>
   ~/Documents/repositories/<name>`. Already registered (the script below reuses a project by
   workspace)? Then just say so and give the project's name.
2. **One message to the owner**, with every choice the project needs, so they answer once:
   - who merges in this project: `user` (always the owner) or `agent` (the lead merges PRs that
     are green, PASSed by the reviewer and not high risk);
   - whether it gets the weekday morning check;
   - anything Studio work left open for this repo.
   An existing `.claude/kit.json` already answers the merge question (`lead.merge`); show it
   instead of asking.
3. **Write the handoff** to `~/Documents/studio/handoffs/<name>.md`:

   ```
   HANDOFF from Studio, approved by the owner on <date>.
   REPO: <absolute path> (<owner/name> on GitHub, <visibility>)
   KIT: present | missing
   SCAFFOLD: <stack, for a new repo with only a README> | none
   MERGE: user | agent
   MORNING CHECK: yes | no
   STUDIO NOTES: ~/Documents/studio/ideas/<slug>/ (files to bring into docs/, or none)
   BRIEF: <the approved brief, or "existing repo, no brief">
   OPEN: <anything the owner still has to decide>
   ```
4. **Register and open the conversation:**

   ```sh
   python3 <this skill's dir>/scripts/omni_project.py register <name> <path> \
     --handoff ~/Documents/studio/handoffs/<name>.md --title "Start <name>"
   ```

   It prints the project and session ids. Post one item to the owner's inbox: the project is
   ready, continue in its "Start <name>" conversation. Tell them the same in Studio, in one line.
   From here, work on that repo happens in its project, not in Studio.

## In the project: the first conversation

A first message starting with `HANDOFF` comes from Studio with the owner's approval: do not ask
again for anything it settles. Dispatch in the same turn, in parallel, since they touch
different things:

- **`engineer`, the kit setup** (skip when KIT is present). Worktree as usual, SHIP `pr`. GOAL:
  set the kit up in this repo by following the kit's init procedure; read it at
  `$(ls -d ~/.claude/plugins/cache/claude-kit/kit/*/ | sort -V | tail -1)skills/init/SKILL.md`,
  since it is user-only as a slash command. Put the answers in the brief so it never stops to
  ask: `lead.merge` from MERGE, `ship` `pr`, the author from the owner's own recent commits, the
  Host profile, no loops. With a SCAFFOLD, the same PR first creates the app with the stack's
  official generator, a CI workflow that runs its check and build, and a README from the
  brief; it must build and pass its check. When STUDIO NOTES has files, the same PR copies
  them into `docs/` (keep their names; a `docs/README.md` line per file).
- **`researcher`, the project card.** Read-only, 10 to 15 lines: stack, the real check and
  build commands (from CI and the manifests), how it deploys, open PRs and issues, CI state on
  the default branch, the rules in CLAUDE.md or AGENTS.md, whether there is a design system.

When both are back:
1. Send the owner the card and ask them to confirm or correct it. What they confirm goes into
   `~/.omnigent/lessons/<repo>.md`.
2. Start `~/.omnigent/boards/<repo>.md` from the open PRs and issues, plus the kit PR.
3. Have `reviewer` check the kit PR, then merge it or hand it to the owner, per MERGE.
4. MORNING CHECK yes: create the weekday 08:00 Europe/Rome schedule for this project (same
   wording as the others, `session_mode: continue`, no cost cap), then run it once now, so the
   owner sees the project's first report before giving it real work.
