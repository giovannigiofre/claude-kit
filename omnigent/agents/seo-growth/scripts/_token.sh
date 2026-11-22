# Sourced by pull.sh and report.sh. The analyst token is read from macOS Keychain inside this
# process and handed to curl on stdin (-K -), so it never appears in argv, in a file, in the
# output or in Claude's transcript. Nothing here prints the token.
#
# One token for both sites (research-2.md, change a): Keychain item `seo-growth-analyst`.

KEYCHAIN_ITEM="${SEO_GROWTH_KEYCHAIN_ITEM:-seo-growth-analyst}"
TOKEN=""

token_help() {
  cat >&2 <<EOF
token missing: Keychain item '$KEYCHAIN_ITEM' not found (or Keychain is locked).
Owner, once, in a terminal (never in a chat):
  1. in the fiscometro checkout: pnpm admin:token --analyst   (prints the token and its SHA-256)
  2. fiscometro: put ANALYST_TOKEN_SHA256=<digest> in .admin-secrets.env, then pnpm admin:secrets
     nettoswiss: set the GitHub secret ANALYST_TOKEN_SHA256 to the same digest (it reaches the Worker at the next deploy)
  3. security add-generic-password -U -s $KEYCHAIN_ITEM -a "\$USER" -w     (paste the token at the prompt)
EOF
}

load_token() {
  if ! command -v security >/dev/null 2>&1; then
    echo "token missing: the 'security' command is not available (macOS Keychain is required)." >&2
    return 3
  fi
  TOKEN="$(security find-generic-password -s "$KEYCHAIN_ITEM" -w 2>/dev/null || true)"
  if [ -z "$TOKEN" ]; then
    token_help
    return 3
  fi
  case "$TOKEN" in
    *[!A-Za-z0-9._~+/=-]*) TOKEN=""; echo "token unusable: Keychain item '$KEYCHAIN_ITEM' holds characters a bearer token cannot have." >&2; return 3 ;;
  esac
  return 0
}

# admin_call METHOD PATH OUTFILE [BODYFILE] -> prints the HTTP status code (000 on a network error)
admin_call() {
  local method="$1" path="$2" out="$3" body="${4:-}"
  local args=(-sS -X "$method" -K - -o "$out" -w '%{http_code}' --max-time 45 --retry 2 --retry-delay 3)
  if [ -n "$body" ]; then
    args+=(-H 'Content-Type: application/json' --data-binary "@$body")
  fi
  printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl "${args[@]}" "$ORIGIN$path" 2>/dev/null || true
}

# explain_status CODE ROUTE -> a one-line reason on stderr; returns non-zero unless 2xx
explain_status() {
  case "$1" in
    2??) return 0 ;;
    401) echo "not connected yet: $ORIGIN answers 401 to the analyst token on $2 (its Worker's ANALYST_TOKEN_SHA256 does not match yet; nettoswiss picks the GitHub secret up at its next production deploy)." >&2; return 5 ;;
    403) echo "forbidden (403) on $2: the analyst token cannot call this endpoint." >&2 ;;
    429) echo "rate limited (429) on $2: 60 requests a minute per Worker; try the next run." >&2 ;;
    000) echo "network error on $2: could not reach $ORIGIN." >&2 ;;
    *)   echo "unexpected HTTP $1 on $2." >&2 ;;
  esac
  return 4
}

site_field() {  # site_field PROJECT FIELD -> value (JSON for objects/lists, text otherwise)
  python3 -I -c '
import json, sys
sites = json.load(open(sys.argv[1]))
site = sites.get(sys.argv[2])
if site is None:
    sys.exit(f"unknown project {sys.argv[2]!r}: one of {sorted(k for k in sites if not k.startswith(chr(95)))}")
v = site.get(sys.argv[3])
print(v if isinstance(v, str) else json.dumps(v))
' "$AGENT_DIR/data/sites.json" "$1" "$2"
}
