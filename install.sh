#!/bin/sh
# One-time setup of claude-kit on a machine. Re-running is safe.
#   ./install.sh            register this clone as the marketplace (edits are live after /reload-plugins)
#   ./install.sh --github   register the private GitHub repo instead (needs `gh auth login` or git credentials)
set -e
cd "$(dirname "$0")"
if [ "$1" = "--github" ]; then SRC="giovannigiofre/claude-kit"; else SRC="$(pwd)"; fi
command -v claude >/dev/null || { echo "Claude Code CLI not found"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required by the kit hooks"; exit 1; }
claude plugin marketplace list 2>/dev/null | grep -q "claude-kit" || claude plugin marketplace add "$SRC"
claude plugin marketplace update claude-kit >/dev/null 2>&1 || true
claude plugin list 2>/dev/null | grep -q "kit@claude-kit" || claude plugin install kit@claude-kit --scope user
claude plugin list | grep -A2 "kit@claude-kit"
echo
echo "Done. In each project: open claude, run /kit:init (writes .claude/kit.json; commit it). From then on you talk to the coordinator (loop mode)."
