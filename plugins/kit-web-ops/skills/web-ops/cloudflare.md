# Cloudflare from the terminal

Checked 2026-11-17. Sources and the comparison with the MCP servers are in `../../docs/research.md`.

## Which tool

| Job | Tool | Why |
|---|---|---|
| DNS records, zones, settings, most account resources | `cf` (official CLI, npm `cf`) | covers the whole REST API, JSON on stdout, `--dry-run`, `cf schema` |
| Workers deploy, secrets, tail, KV in a Wrangler project | the project's `wrangler` | reads `wrangler.jsonc`/`wrangler.toml`, the version the project pins |
| Zone analytics | curl to the GraphQL API with a read-only token | one POST, nothing to install |
| Exploring an unfamiliar API area, or an owner who prefers OAuth to a token | Cloudflare API MCP `https://mcp.cloudflare.com/mcp` | two tools (search, execute) over 2,500+ endpoints, OAuth with scope selection |

The claude.ai "Cloudflare Developer Platform" connector covers Workers, KV, R2, D1 and Hyperdrive
only; it has no DNS or token tools. Use it only when the session already has it authenticated.

## Install and log in

- `cf` needs Node `^22.23 || ^24.22 || ^26.12` (its `engines` field). Install with
  `npm install --global cf` (pin the version the doctor recommends while it is a release
  candidate). The owner logs in: `! cf auth login` (add `--no-browser` on a remote machine).
  `cf auth whoami` shows the user and accounts. It does not reuse Wrangler's login.
- Wrangler: use the project's own (`pnpm exec wrangler whoami`). `! pnpm exec wrangler login` is
  the owner's.
- In CI or a headless run both read `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from the
  environment; set them from a secret store, never inline.
- The MCP: `claude mcp add --transport http --scope project cloudflare https://mcp.cloudflare.com/mcp`,
  then the owner runs `/mcp` and authenticates, choosing the narrowest scopes offered.

## DNS records

```bash
cf dns records list --zone <zone-id> > dns-before.json
cf dns records create --zone <zone-id> --type TXT --name example.com --content "google-site-verification=..." --dry-run
cf dns records create --zone <zone-id> --type TXT --name example.com --content "google-site-verification=..."
cf dns records list --zone <zone-id> > dns-after.json
```

Check flag names with `cf schema dns records create` before the first use; the CLI is young. A
record create or delete is owner-authorized (SKILL.md section 5). Deletes ask for confirmation;
`--force` skips it, so use it only with an explicit go-ahead for that record. Verification TXT
records stay in place after verification: Google and Bing re-check them.

REST fallback (no `cf`): `GET/POST https://api.cloudflare.com/client/v4/zones/<zone>/dns_records`
with `Authorization: Bearer` from an environment variable, never pasted.

## API tokens (least privilege)

Creating a token needs the dashboard, or a token that itself holds "API Tokens Edit", which an agent
should not hold. So the owner creates tokens; the agent writes the recipe:

- **Name** after the job (`<site>-analytics-read`, `<site>-deploy`), one token per job.
- **Permissions** only what the job uses. Analytics: Zone - Analytics - Read (plus Account -
  Account Analytics - Read for account-level datasets). DNS automation: Zone - DNS - Edit.
  Workers deploy: Account - Workers Scripts - Edit (plus KV, routes as the project uses).
- **Resources** a specific zone or account, never "All zones".
- **TTL / IP filter** when the token lives in CI only.
- Dashboard link: `https://dash.cloudflare.com/profile/api-tokens` -> Create Token -> Custom token.

The owner copies the value once and stores it without it passing through chat:
`! pbpaste | gh secret set CF_ANALYTICS_TOKEN` (macOS clipboard; gh reads stdin and echoes nothing),
then clears the clipboard. Check: `gh secret list` shows the name and date. Verify the token works
without printing it: `curl -s -H "Authorization: Bearer $CF_TOKEN" https://api.cloudflare.com/client/v4/user/tokens/verify | jq .result.status`
(account-owned tokens use `/accounts/<id>/tokens/verify`).

## Workers secrets and KV

- `pnpm exec wrangler secret put NAME` reads the value from stdin: pipe it from the maker
  (`<maker> | pnpm exec wrangler secret put NAME`), never type it as an argument. Add `--env` when
  the project uses environments. `wrangler secret list` shows names only.
- Many at once: `wrangler secret bulk <file.json>` or `wrangler deploy --secrets-file`, from a file
  in a private temp folder that is deleted right after.
- KV: `wrangler kv key list --binding <BINDING>`; writes are deploy-like changes, done only when asked.

## Zone analytics (GraphQL)

```bash
curl -s https://api.cloudflare.com/client/v4/graphql \
  -H "Authorization: Bearer $CF_ANALYTICS_TOKEN" -H "Content-Type: application/json" \
  --data @query.json > analytics.json
```

`query.json` holds `{"query": "...", "variables": {"zoneTag": "<zone-id>", ...}}`, for example
`httpRequests1dGroups(limit: 7, filter: {date_geq: $since}) { sum { requests pageViews } dimensions { date } }`
under `viewer { zones(filter: {zoneTag: $zoneTag}) { ... } }`. Datasets and their retention depend
on the plan; the schema is introspectable, and the docs list each dataset's limits.

## Pitfalls

- Several accounts under one login: pass `--account`/`CLOUDFLARE_ACCOUNT_ID` explicitly and read it
  back in the doctor before writing.
- Proxied records (orange cloud) change what verification and IndexNow key checks see; TXT records
  are never proxied.
- A Wrangler login token and a `cf` login are separate; a user-scoped OAuth login can do more than a
  scoped API token. Prefer the token for automation.
