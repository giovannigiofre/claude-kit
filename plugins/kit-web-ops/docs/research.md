# Operating Cloudflare, Google and Bing for a website: CLI, MCP or REST

Research for `kit-web-ops`, 2026-11-17. Question: for each task a website owner meets, which way
of letting Claude Code act is cheapest in context, most reliable, and safest - a CLI, an MCP
server (or a claude.ai connector), or a plain REST call - and which steps stay with a human.

## Verdict

1. **CLI and REST first.** A CLI or curl call costs no context until it is used, works the same in
   CI, returns JSON that can be saved as evidence, and has a `--dry-run` or a GET to look first.
2. **MCP only where it is official and saves a token.** The Cloudflare API MCP (Code Mode, two
   tools, about 1k tokens) is a good optional extra: OAuth with scope selection means the owner
   clicks once instead of minting a token. It is not bundled; add it per project when wanted.
3. **No community MCP servers** for Search Console or Bing: single-maintainer wrappers around one
   REST endpoint, holding a long-lived credential in another process, for what curl does.
4. **Browser clicking only for UI-only steps**, prepared as one deep link each.

## Per task

| Task | Recommended path | Human step | Alternatives considered |
|---|---|---|---|
| DNS records (list, add TXT/CNAME, delete) | `cf dns records ...` (official CLI, JSON, `--dry-run`) | authorize the change | Cloudflare API MCP (good, OAuth); curl REST with a DNS-Edit token; dashboard (slow, permission blocks seen) |
| Least-privilege API token | owner creates in dashboard from a written recipe; agent stores it via `pbpaste \| gh secret set` | create + copy | API (`/user/tokens`) needs a token with "API Tokens Edit": too much power for an agent |
| Workers secrets / KV | project's `wrangler secret put` from stdin, `secret bulk`, `deploy --secrets-file` | authorize (secret put/bulk deploy immediately) | `cf` (covers the API too, but Wrangler reads the project config); Developer Platform connector (Workers/KV only) |
| Zone analytics | curl to `/client/v4/graphql` with a read-only token | create the token | MCP execute (works, but a fixed query is cheaper as a file) |
| GSC property + verification | Site Verification API (`getToken` DNS_TXT, then `webResource.insert`) + TXT via `cf`, then `sites.add` | authorize DNS, or click "Verify" in the UI | UI with Cloudflare's automatic record |
| GSC sitemaps | `PUT sites/{site}/sitemaps/{feed}` with curl | none | community MCPs (rejected) |
| GSC search analytics | `POST searchAnalytics/query` | none | Looker Studio / BigQuery export (heavier) |
| GSC URL inspection | `POST /v1/urlInspection/index:inspect`, within the daily/minute quota | none | UI |
| Service account as GSC user | UI "Add user" from a deep link; or the SA verifies itself through Site Verification + DNS TXT | one click (UI) or DNS authorization | none: the Search Console API has no users method |
| Keyless local access as the SA | IAM Credentials `generateAccessToken` with the webmasters scope, called with the owner's gcloud token (needs Token Creator on the SA) | grant the role once | SA key file locally (avoid); user ADC with own OAuth client |
| SA key for CI | `gcloud iam service-accounts keys create` to a private temp file, `gh secret set NAME < file`, delete | authorize | Workload Identity Federation (better, when the consumer supports it) |
| CrUX / PageSpeed keys | `gcloud services api-keys create --api-target=service=...`, both streams to a private temp folder (create prints the key on stderr), then `gh secret set NAME < file` | authorize | Console UI |
| Bing: add site | UI "Import from Google Search Console" (no DNS), or API `AddSite` + `VerifySite` | sign in, import | community MCPs (rejected) |
| Bing: API key | UI only (Settings -> API Access) | generate + copy | OAuth client (more setup, no gain for one site) |
| Bing: sitemaps, stats, URL submission | JSON API with curl (`SubmitFeed`, `GetQueryStats`, `SubmitUrlBatch`) | none | |
| IndexNow | key file on the site + POST `api.indexnow.org/indexnow` from the deploy | authorize the deploy | Bing `SubmitUrlBatch` (Bing only, quota) |
| Google Indexing API | not applicable: JobPosting and BroadcastEvent pages only | | |

## What only a human does, and how to make it one click

- **Logins and OAuth consent**: `! gcloud auth login`, `! cf auth login`, `! pnpm exec wrangler
  login`, `/mcp` -> Authenticate. Typed by the owner with `!` so the browser opens on his machine.
  Never scripted, never clicked by an agent: they carry passwords and 2FA.
- **Choosing the right account**: the doctor prints the active Google account and all others, the
  Cloudflare user and accounts, and the GitHub repo. The owner confirms once.
- **UI-only steps** get a prepared link and the value to paste: Search Console users page with
  `resource_id`, Bing API Access, Cloudflare Create Token with the permission list.
- **Copying a secret from a UI**: `! pbpaste | gh secret set NAME`, then clear the clipboard. The
  value never enters the transcript.

## Options in detail

**Cloudflare `cf` CLI.** Official, npm `cf`, repo cloudflare/cf, published by Cloudflare's Wrangler
team; 1.0.0-rc.0 on 2026-11-16 and rc.1 on 2026-11-17 (release candidate). Generated from the
API schema; JSON on stdout; `cf cli search`, `cf schema`, `--dry-run`; own login (`cf auth login`)
or `CLOUDFLARE_API_TOKEN`. Needs Node `^22.23 || ^24.22 || ^26.12`. Recommendation: the default
for account and zone operations once it leaves rc; until then pin the rc and fall back to curl.

**Wrangler.** The Workers tool; the project pins it. Best for deploy, secrets, tail, KV, D1, R2
in a Workers project. Not a general DNS or token tool.

**Cloudflare API MCP** (`https://mcp.cloudflare.com/mcp`). Official; Code Mode exposes `search` and
`execute` over the whole API (2,500+ endpoints) in about 1k tokens; `?codemode=false` gives one
tool per endpoint. OAuth with scope selection, or a token as bearer. Good for exploration and for
owners who prefer one OAuth click. Other official servers: docs, bindings, builds, observability,
radar, browser rendering and more.

**claude.ai "Cloudflare Developer Platform" connector** (`bindings.mcp.cloudflare.com`). Workers,
KV, R2, D1, Hyperdrive only; no DNS, tokens or analytics. Not enough for site operations.

**cloudflare/skills** (Apache-2.0; 22 skills including `cf-cli` and `wrangler`; ships an `.mcp.json`
for the API MCP). Useful upstream reading; installing it adds 22 always-on descriptions for a
project that needs two.

**gcloud.** Required for project, API enablement, service accounts, IAM and API keys. Its own OAuth
client is limited to Cloud scopes for users, so Search Console calls need the SA path or the
owner's own OAuth client.

**Google Cloud remote MCP servers.** Official for Cloud products (IAM, Resource Manager, API keys in
preview, logging, BigQuery and others). Search Console, Site Verification, CrUX and PageSpeed are
not among them. Nothing here that gcloud does not already do at zero context cost.

**Search Console API / Site Verification API.** Stable REST, well documented, OAuth scopes
`webmasters[.readonly]` and `siteverification`. No user-management methods.

**Bing Webmaster API.** API key (one per user, UI-generated) or OAuth; JSON and SOAP endpoints.
Covers sites, verification, feeds, URL submission and stats.

**IndexNow.** Open protocol; one submission is shared with Bing, Yandex, Seznam, Naver, Yep and
others. Google does not participate.

**Community MCP servers** checked as kit:intake would: Search Console (several, MIT, single
maintainers, OAuth or SA key held by the server process) and Bing Webmaster (isiahw1, others; MIT;
API key held by the process). Rejected: no official backing, a second place holding a credential,
and no capability beyond curl.

## Sources (read 2026-11-17; rechecked 2026-11-24 where noted)

- Cloudflare MCP servers: https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/ (updated 2026-10-27)
- Cloudflare `cf` CLI: https://developers.cloudflare.com/cf/ (updated 2026-11-17); https://github.com/cloudflare/cf; npm `cf` 1.0.0-rc.1
- `cf` DNS and account selection (2026-11-24; rc.4): https://developers.cloudflare.com/cf/get-started/resources/ and https://developers.cloudflare.com/cf/get-started/
- cloudflare/skills: https://github.com/cloudflare/skills (main 5108325, pushed 2026-11-17)
- Cloudflare API tokens: https://developers.cloudflare.com/fundamentals/api/get-started/create-token/
- Cloudflare GraphQL Analytics: https://developers.cloudflare.com/analytics/graphql-api/
- Wrangler `secret` deploys immediately (2026-11-24): https://developers.cloudflare.com/workers/wrangler/commands/workers/
- Wrangler commands: https://developers.cloudflare.com/workers/wrangler/commands/
- Google Cloud MCP supported products: https://docs.cloud.google.com/mcp/supported-products
- Search Console API reference: https://developers.google.com/webmaster-tools/v1/api_reference_index
- Search Console API limits: https://developers.google.com/webmaster-tools/limits
- Site Verification API: https://developers.google.com/site-verification/v1/invoking
- ADC troubleshooting (scopes and own client id): https://docs.cloud.google.com/docs/authentication/troubleshoot-adc
- IAM Credentials generateAccessToken: https://cloud.google.com/iam/docs/reference/credentials/rest/v1/projects.serviceAccounts/generateAccessToken
- API keys with gcloud: https://cloud.google.com/sdk/gcloud/reference/services/api-keys/create (also `--help`, SDK 594.0.0)
- API key as `x-goog-api-key` header (2026-11-24): https://docs.cloud.google.com/docs/authentication/api-keys-use
- `api-keys create` prints its response on stderr: installed SDK source, `services_util.PrintOperationWithResponse` (2026-11-24)
- CrUX API: https://developer.chrome.com/docs/crux/api
- Indexing API scope: https://developers.google.com/search/apis/indexing-api/v3/quickstart
- Bing Webmaster API access: https://learn.microsoft.com/en-us/bingwebmaster/getting-access
- Bing host with an API key (2026-11-24): https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.submiturlbatch
- Bing Webmaster API methods: https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi
- IndexNow: https://www.indexnow.org/documentation
