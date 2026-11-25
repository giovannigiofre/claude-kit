#!/bin/sh
# Precheck of a weekly check: exit 0 runs it, 1 skips it (nothing can need the owner, no tokens spent).
# Run by Orca in the project's checkout. Anything it cannot read counts as "run".
cd "${1:-.}" || exit 0
board=.kit/lead/board.md
if [ -f "$board" ] && grep -Eqi '(^|[^a-z])(working|review|needs-you|needs you)([^a-z]|$)' "$board"; then exit 0; fi
prs=$(gh pr list --state open --limit 1 --json number -q 'length' 2>/dev/null) || exit 0
[ "$prs" = 0 ] || exit 0
red=$(gh run list --branch main --limit 1 --json conclusion -q '.[0].conclusion' 2>/dev/null) || exit 0
[ "$red" = failure ] && exit 0
exit 1
