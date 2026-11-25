#!/bin/sh
# Installs or updates the kit's Orca side on this machine. Safe to re-run; pass --dry-run to see it.
# Copies the specialists to ~/.claude/agents, Studio's skills to ~/Documents/studio, keeps a clean
# checkout of origin/main for the routines, and moves nothing that belongs to Omnigent (it copies).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
D="$HOME/.local/share/claude-kit"; S="$HOME/Documents/studio"; KIT="${KIT_REPO:-$HOME/Documents/repositories/claude-kit}"
[ "$1" = --dry-run ] && { echo "agents -> ~/.claude/agents; studio -> $S/.claude/skills, $S/CLAUDE.md; state -> $D"; exit 0; }
mkdir -p "$HOME/.claude/agents" "$D/bin" "$D/lessons" "$S/.claude/skills"
cp "$HERE"/agents/*.md "$HOME/.claude/agents/"
cp "$HERE"/scripts/*.sh "$D/bin/" && chmod +x "$D"/bin/*.sh
cp -R "$HERE"/studio/skills/. "$S/.claude/skills/"; cp "$HERE/studio/CLAUDE.md" "$S/CLAUDE.md"
[ -e "$D/main/.git" ] || git -C "$KIT" worktree add -q --detach "$D/main" origin/main
# First install only: state from Omnigent. Never overwrites what is already here.
if [ -d "$HOME/.omnigent/seo-growth" ] && [ ! -d "$D/seo-growth" ]; then cp -Rp "$HOME/.omnigent/seo-growth" "$D/seo-growth"; fi
for f in "$HOME"/.omnigent/lessons/*.md; do [ -f "$f" ] && [ ! -e "$D/lessons/$(basename "$f")" ] && cp -p "$f" "$D/lessons/" || true; done
echo "installed: $(ls "$HERE"/agents | wc -l | tr -d ' ') agents, Studio, $D"
