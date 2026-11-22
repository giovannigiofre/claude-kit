#!/usr/bin/env bash
# pull.sh <project> [--check] [--date YYYY-MM-DD]
#
# Writes one run's raw data to $SEO_GROWTH_HOME/<project>/run/<date>/ (default ~/.omnigent/seo-growth):
#   summary.json pages.json queries.json   admin API, analyst token (read-only + agent-report)
#   feeds/<id>.xml  watch/<id>.html        official news (public, no auth)
#   google-status.html                     Google Search Status ranking history (rollout freeze)
#   html/<n>.html + html/_paths.json       the top pages' live HTML, for the schema lint
# then normalises them (sources.py -> news.json, rollouts.json, watch.json; schema_lint.py -> schema.json)
# and syncs the ledger with GitHub (ledger.py sync).
#
# --check: only read the token and call /admin/api/summary; prints "ok <status> autopilot=<bool>".
# Exit codes: 0 ok, 2 usage, 3 token missing, 4 admin API refused or unreachable.
# Claude runs this script; it never runs `security` itself and never sees the token.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(dirname "$HERE")"
# shellcheck source=_token.sh
. "$HERE/_token.sh"

project="${1:-}"
[ -n "$project" ] || { echo "usage: pull.sh <project> [--check] [--date YYYY-MM-DD]" >&2; exit 2; }
shift
check=0
day="$(TZ=Europe/Rome date +%F)"
while [ $# -gt 0 ]; do
  case "$1" in
    --check) check=1 ;;
    --date) day="$2"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

ORIGIN="$(site_field "$project" origin)" || exit 2
STATE="${SEO_GROWTH_HOME:-$HOME/.omnigent/seo-growth}/$project"
RUN="$STATE/run/$day"

load_token || exit 3

if [ "$check" = 1 ]; then
  tmp="$(mktemp)"
  code="$(admin_call GET /admin/api/summary "$tmp")"
  explain_status "$code" /admin/api/summary || { rm -f "$tmp"; exit 4; }
  python3 -I -c '
import json, sys
s = json.load(open(sys.argv[1]))
print("ok", s.get("status"), "autopilot=" + str(s.get("autopilot", {}).get("enabled")).lower(), "site=" + str(s.get("site")))
' "$tmp"
  rm -f "$tmp"
  exit 0
fi

mkdir -p "$RUN/feeds" "$RUN/watch" "$RUN/html"
: > "$RUN/fetch-errors.txt"

for route in summary "pages?limit=1000" "queries?limit=1000"; do
  name="${route%%\?*}"
  code="$(admin_call GET "/admin/api/$route" "$RUN/$name.json")"
  explain_status "$code" "/admin/api/$route" || exit 4
done
TOKEN=""  # not needed past this point

fetch_public() {  # fetch_public URL OUT
  curl -sSfL --max-time 30 -A 'seo-growth/1 (+site owner monitoring)' -o "$2" "$1" 2>>"$RUN/fetch-errors.txt" \
    || echo "fetch failed: $1" >>"$RUN/fetch-errors.txt"
}

python3 -I -c '
import json, sys
for f in json.loads(sys.argv[1]) or []:
    print(f["id"], f["url"])
' "$(site_field "$project" feeds)" | while read -r id url; do fetch_public "$url" "$RUN/feeds/$id.xml"; done

python3 -I -c '
import json, sys
for f in json.loads(sys.argv[1]) or []:
    print(f["id"], f["url"])
' "$(site_field "$project" watch_pages)" | while read -r id url; do fetch_public "$url" "$RUN/watch/$id.html"; done

fetch_public "https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history" "$RUN/google-status.html"

# The top 20 pages by impressions, for the schema lint.
python3 -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
rows = sorted(d.get("rows") or [], key=lambda r: -r.get("impressions", 0))[:20]
for i, r in enumerate(rows):
    print(i, r["path"])
' "$RUN/pages.json" | while read -r n path; do
  fetch_public "$ORIGIN$path" "$RUN/html/$n.html"
  printf '%s\t%s\n' "$n.html" "$path"
done > "$RUN/html/_paths.tsv"

python3 -I "$HERE/sources.py" "$RUN" --state "$STATE"
python3 -I "$HERE/schema_lint.py" "$RUN/html" --out "$RUN/schema.json" >/dev/null || true
python3 -I "$HERE/ledger.py" sync --project "$project" >/dev/null 2>>"$RUN/fetch-errors.txt" \
  || echo "ledger sync failed (gh?): open-PR counts come from the ledger as last recorded" >>"$RUN/fetch-errors.txt"

echo "pulled $project into $RUN"
[ -s "$RUN/fetch-errors.txt" ] && echo "with fetch notes: $RUN/fetch-errors.txt"
exit 0
