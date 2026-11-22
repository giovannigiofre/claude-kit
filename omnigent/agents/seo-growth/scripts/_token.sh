# Sourced by pull.sh and report.sh. The analyst token never enters this shell: keychain_header.py reads
# the Keychain item (20 s timeout), checks it and writes the curl header line to AUTH_FILE (mode 600, in a
# mode-700 directory keychain_header.py creates itself; both deleted by the EXIT trap below). curl reads it
# with -H @file, so the token is never in argv, in a shell variable, in the environment, in the output or in an xtrace (`bash -x`) trace. Nothing here prints it.
#
# One token for every site: Keychain item `seo-growth-analyst`, fixed on purpose.

KEYCHAIN_ITEM="seo-growth-analyst"
AUTH_FILE=""

_auth_cleanup() {
  if [ -n "$AUTH_FILE" ]; then
    rm -f "$AUTH_FILE"
    rmdir "$(dirname "$AUTH_FILE")" 2>/dev/null || true
  fi
  AUTH_FILE=""
}

# A SIGKILL skips the traps and leaves a header behind. Runs last minutes, so anything of ours older than
# an hour is stale: one non-recursive find in $TMPDIR, no matter how many entries it has.
_auth_sweep() {
  find "${TMPDIR:-/tmp}" -maxdepth 1 -mindepth 1 -name 'seo-growth-auth.*' -user "$(id -u)" -mmin +60 \
    -exec rm -rf {} + 2>/dev/null || true
}
trap _auth_cleanup EXIT
trap '_auth_cleanup; exit 130' INT TERM HUP

# xtrace off around the token code, back on after if it was on. `{ ...; } 2>/dev/null` hides the toggle.
_xtrace_off() { case $- in *x*) _XTRACE_WAS=1 ;; *) _XTRACE_WAS=0 ;; esac; set +x; }
_xtrace_restore() { [ "${_XTRACE_WAS:-0}" = 1 ] && set -x; return 0; }

load_token() {
  { _xtrace_off; } 2>/dev/null
  local rc=0
  _auth_cleanup
  _auth_sweep
  AUTH_FILE="$(python3 -I "$HERE/keychain_header.py" "$KEYCHAIN_ITEM")" || rc=$?
  case "$AUTH_FILE" in */seo-growth-auth.*/header) ;; *) [ "$rc" = 0 ] && rc=3; AUTH_FILE="" ;; esac
  [ "$rc" = 0 ] || _auth_cleanup
  { _xtrace_restore; } 2>/dev/null
  return "$rc"
}

drop_token() { { _xtrace_off; _auth_cleanup; _xtrace_restore; } 2>/dev/null; }

# admin_call METHOD PATH OUTFILE [BODYFILE] -> prints the HTTP status code (000 on a network error).
# GETs retry twice; a POST never retries, so a report cannot be posted twice.
admin_call() {
  { _xtrace_off; } 2>/dev/null
  local method="$1" path="$2" out="$3" body="${4:-}"
  local args=(-sS -X "$method" -H "@$AUTH_FILE" -o "$out" -w '%{http_code}' --max-time 45)
  if [ "$method" = GET ]; then
    args+=(--retry 2 --retry-delay 3)
  fi
  if [ -n "$body" ]; then
    args+=(-H 'Content-Type: application/json' --data-binary "@$body")
  fi
  if [ -z "$AUTH_FILE" ] || [ ! -s "$AUTH_FILE" ]; then
    printf '000'
  else
    curl "${args[@]}" "$ORIGIN$path" </dev/null 2>/dev/null || true
  fi
  { _xtrace_restore; } 2>/dev/null
}

# explain_status CODE ROUTE -> a one-line reason on stderr; returns non-zero unless 2xx
explain_status() {
  case "$1" in
    2??) return 0 ;;
    401) echo "not connected yet: $ORIGIN answers 401 to the analyst token on $2 (its Worker's ANALYST_TOKEN_SHA256 does not match yet, e.g. a secret that a production deploy has not picked up)." >&2; return 5 ;;
    403) echo "forbidden (403) on $2: the analyst token cannot call this endpoint." >&2 ;;
    429) echo "rate limited (429) on $2: 60 requests a minute per Worker; try the next run." >&2 ;;
    000) echo "network error on $2: could not reach $ORIGIN." >&2 ;;
    *)   echo "unexpected HTTP $1 on $2." >&2 ;;
  esac
  return 4
}

# The site's own data lives in its repo, not in the kit: <repo>/.claude/seo-growth/ (site.json, calendar.json,
# panel.json). SEO_GROWTH_SITE names that folder (the agent points it at its worktree); else
# $SEO_GROWTH_REPOS/<project>/.claude/seo-growth, with SEO_GROWTH_REPOS defaulting to ~/Documents/repositories.
site_dir() {  # site_dir PROJECT -> the folder with the site's data
  printf '%s\n' "${SEO_GROWTH_SITE:-${SEO_GROWTH_REPOS:-$HOME/Documents/repositories}/$1/.claude/seo-growth}"
}

site_field() {  # site_field PROJECT FIELD -> value (JSON for objects/lists, text otherwise)
  python3 -I -c '
import json, sys
try:
    site = json.load(open(sys.argv[1]))
except FileNotFoundError:
    sys.exit(f"no site data for {sys.argv[2]!r}: {sys.argv[1]} is missing (the repo keeps it in .claude/seo-growth/)")
v = site.get(sys.argv[3])
print(v if isinstance(v, str) else json.dumps(v))
' "$(site_dir "$1")/site.json" "$1" "$2"
}
