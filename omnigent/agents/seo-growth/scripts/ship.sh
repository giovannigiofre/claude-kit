#!/usr/bin/env bash
# ship.sh <project> <worktree> <title> <body.md>
#
# The only way seo-growth opens a PR. Runs the site's gate (`gate` in data/sites.json) in the worktree
# on the committed branch; the gate's exit status alone decides: non-zero, nothing is pushed and no PR
# is opened. On exit 0: re-checks the open-PR cap on GitHub, pushes the branch (never the default
# branch, never forced) and opens the PR labelled `seo-growth`, with the gate's tail appended to the body.
# Prints the PR URL on the last line.
#
# Exit codes: 0 PR opened, 2 usage or unsafe state (default branch, uncommitted or untracked changes),
#             6 gate failed (no PR), 7 cap of open seo-growth PRs reached, 8 push or gh failed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(dirname "$HERE")"
# shellcheck source=_token.sh
. "$HERE/_token.sh"   # for site_field; ship.sh never loads the token

project="${1:-}"; wt="${2:-}"; title="${3:-}"; body="${4:-}"
[ -n "$project" ] && [ -d "$wt" ] && [ -n "$title" ] && [ -f "$body" ] \
  || { echo "usage: ship.sh <project> <worktree> <title> <body.md>" >&2; exit 2; }
body="$(cd "$(dirname "$body")" && pwd)/$(basename "$body")"
gate="$(site_field "$project" gate)" || exit 2
repo="$(site_field "$project" repo)" || exit 2
max_open="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["max_open_prs"])' \
  "${SEO_GROWTH_DATA:-$AGENT_DIR/data}/thresholds.json")"

cd "$wt"
branch="$(git rev-parse --abbrev-ref HEAD)"
default="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
case "$branch" in
  HEAD|main|master|"${default:-main}") echo "refusing to ship from '$branch': work on a seo-growth branch" >&2; exit 2 ;;
esac
# Any change not in HEAD, untracked files included (ignored ones excepted), would let the gate pass on
# content the PR never carries. Refuse before the gate. After it, a changed tracked file also refuses
# (the gate may have checked edited content); new untracked build output does not, HEAD is unchanged.
dirty() { [ -n "$(git status --porcelain --untracked-files="${1:-all}")" ]; }
if dirty; then
  echo "uncommitted or untracked changes in $wt: commit or remove them first, the gate runs only on what the PR will carry" >&2
  git status --short --untracked-files=all | head -n 10 >&2
  exit 2
fi
sha="$(git rev-parse HEAD)"

log="$(mktemp "${TMPDIR:-/tmp}/seo-growth-gate.XXXXXX")"
trap 'rm -f "$log" "${full:-}"' EXIT
echo "gate: $gate (in $wt at ${sha:0:12})"
set +e
bash -c "$gate" >"$log" 2>&1 </dev/null
rc=$?
set -e
tail -n 40 "$log"
if [ "$rc" != 0 ]; then
  echo "gate failed (exit $rc): no PR opened" >&2
  exit 6
fi
if [ "$(git rev-parse HEAD)" != "$sha" ]; then
  echo "HEAD moved while the gate ran: no PR opened" >&2; exit 2
fi
if dirty no; then
  echo "tracked files changed while the gate ran (the tree no longer matches $sha): no PR opened" >&2
  git status --short --untracked-files=no | head -n 10 >&2
  exit 2
fi

open="$(gh pr list --repo "$repo" --label seo-growth --state open --limit 100 --json number --jq length)" \
  || { echo "gh pr list failed: cannot check the cap, no PR opened" >&2; exit 8; }
if [ "$open" -ge "$max_open" ]; then
  echo "cap reached: $open open seo-growth PRs (max $max_open): no PR opened" >&2; exit 7
fi

git push -u origin "HEAD:refs/heads/$branch" || { echo "push failed: no PR opened" >&2; exit 8; }
gh label create seo-growth --repo "$repo" --color 0E8A16 --description "opened by the seo-growth agent" >/dev/null 2>&1 || true
full="$(mktemp "${TMPDIR:-/tmp}/seo-growth-body.XXXXXX")"
{ cat "$body"; printf '\n\n### Gate\n`%s` exit 0 on %s\n\n```\n' "$gate" "$sha"; tail -n 15 "$log"; printf '```\n'; } >"$full"
gh pr create --repo "$repo" --head "$branch" ${default:+--base "$default"} --title "$title" \
  --body-file "$full" --label seo-growth || { echo "gh pr create failed" >&2; exit 8; }
