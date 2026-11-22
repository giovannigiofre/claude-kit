#!/usr/bin/env bash
# report.sh <project> <report.json>
#
# Posts a run report to POST /admin/api/agent-report with the analyst token.
# The body is the Worker's AgentReport shape: {runId, mode: "pulse", status: ok|incident|no-data|stopped,
# summary, markdown?, findings?, actions?, ownerAsks?, period?, usage?}, at most 256 KB.
# Prints the HTTP code and the Worker's answer (which never contains the token).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(dirname "$HERE")"
# shellcheck source=_token.sh
. "$HERE/_token.sh"

project="${1:-}"; body="${2:-}"
[ -n "$project" ] && [ -f "$body" ] || { echo "usage: report.sh <project> <report.json>" >&2; exit 2; }
ORIGIN="$(site_field "$project" origin)" || exit 2

python3 -I -c '
import json, os, sys
p = sys.argv[1]
if os.path.getsize(p) > 256 * 1024:
    sys.exit("report larger than 256 KB")
r = json.load(open(p))
missing = [k for k in ("runId", "mode", "status", "summary") if k not in r]
if missing:
    sys.exit(f"report misses {missing}")
if r["mode"] not in ("pulse", "weekly") or r["status"] not in ("ok", "incident", "no-data", "stopped"):
    sys.exit("mode must be pulse|weekly, status ok|incident|no-data|stopped")
' "$body" || exit 2

load_token || exit 3
out="$(mktemp)"
code="$(admin_call POST /admin/api/agent-report "$out" "$body")"  # no retry: a report is posted at most once
drop_token
echo "HTTP $code $(head -c 500 "$out")"
rm -f "$out"
explain_status "$code" /admin/api/agent-report || exit $?
