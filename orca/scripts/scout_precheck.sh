#!/bin/sh
# Precheck of a weekly scout: exit 0 runs it, 1 skips it (5 cards still waiting, or no commit in 7 days).
cd "${1:-.}" || exit 1
cards=$(find .kit/lead/proposals -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
[ "$cards" -ge 5 ] && exit 1
git fetch -q origin 2>/dev/null || true
[ -n "$(git log --remotes=origin --since='7 days ago' -1 --format=%h 2>/dev/null)" ]
