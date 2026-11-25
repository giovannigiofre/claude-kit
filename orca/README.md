# The kit on Orca

[Orca](https://orca.dev) runs the real Claude Code CLI with your plugins, CLAUDE.md and the kit's
hooks, so here the kit is already the orchestrator: nothing in `plugins/` changes.

| On Omnigent | On Orca |
|---|---|
| `lead` | `kit:lead`, in any chat in a kit project's main workspace |
| `engineer`, `reviewer` | `kit:implementer`, `kit:verifier` |
| `researcher`, `designer`, `seo`, `seo-growth` | the agent files in `agents/`, in `~/.claude/agents/` |
| Studio and lead's three skills | the folder project `~/Documents/studio`, skills in its `.claude/skills/`; a bot named Studio with the same rules (`studio/SOUL.md`) is the phone entry point |
| routines, inbox | Orca automations; the run's last message is the notification |
| `~/.omnigent/seo-growth`, `lessons` | `~/.local/share/claude-kit/` (copied once) |

Install or update: `sh orca/install.sh` (`--dry-run` shows what it writes).

Add a project: `orca repo add --path <path>`. Routines (the prompts are in `routines/`):

```sh
# weekly check, Monday 08:00, in the main workspace, skipped without tokens when nothing can need you
orca automations create --name "Controllo settimanale <repo>" --provider claude --workspace path:<path> \
  --trigger "0 8 * * 1" --timezone Europe/Rome --prompt "$(cat orca/routines/weekly-check.md)" \
  --precheck "$HOME/.local/share/claude-kit/bin/weekly_precheck.sh <path>"
# seo-growth, a new worktree per run from origin/main (@SITE@ replaced)
orca automations create --name "seo-growth <site>" --provider claude --repo path:<path> \
  --base-branch origin/main --setup skip --trigger "17 6 */2 * *" --timezone Europe/Rome \
  --prompt "$(sed 's/@SITE@/<site>/g' orca/routines/seo-growth.md)"
```

Phone: Orca Mobile on the tailnet; `orca pair --mobile --address <this Mac's Tailscale IP>` prints
the QR. No Relay, nothing public. The Mac must be awake.

Also: a weekly scout per project (`routines/scout.md`, one project a day, `scripts/scout_precheck.sh`
skips it when five cards wait or nothing was committed that week) and a lesson review on the 1st and
15th (`routines/learn.md`, ledger only).
