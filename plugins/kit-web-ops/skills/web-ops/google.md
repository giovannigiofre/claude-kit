# Google: Search Console, Site Verification, CrUX, PageSpeed

Checked 2026-11-17. Sources are in `../../docs/research.md`.

## Which tool

| Job | Tool |
|---|---|
| Cloud project, enabling APIs, service accounts, IAM, API keys | `gcloud` (`brew install --cask gcloud-cli`) |
| Search Console: properties, sitemaps, search analytics, URL inspection | curl to `https://searchconsole.googleapis.com` / `https://www.googleapis.com/webmasters/v3` |
| Proving ownership (DNS TXT) | Site Verification API with curl, plus the TXT record through Cloudflare |
| Adding a user to a property | UI only (no API): the owner, from a deep link |
| CrUX, PageSpeed Insights | curl with an API key restricted to that API |

There is no Google-made Search Console MCP server; Google's remote MCP servers cover Cloud
products (IAM, Resource Manager, API keys, logging and others), not Search Console, Site
Verification, CrUX or PageSpeed. Community Search Console MCP servers exist; they add a token-holding
process for what one curl call does, so the kit does not use them.

## Accounts first

The owner may have several Google accounts. `gcloud auth list` shows them with the active one
starred; `gcloud config get-value account` and `gcloud config get-value project` say what the next
command will use. Name the project's account in its docs and check it before every change; use
`--account=<email> --project=<id>` on writes instead of relying on the active one. A separate
named configuration per site keeps them apart: `gcloud config configurations create <site>`.

Owner commands: `! gcloud auth login` (opens the browser) and, once, `! gcloud config set account
<email>`, `! gcloud config set project <id>`.

## Tokens for the REST APIs

The Search Console scope (`https://www.googleapis.com/auth/webmasters[.readonly]`) is not one that
gcloud's own OAuth client may request for a user. Two clean paths:

1. **Impersonate the site's service account (recommended, keyless).** The owner grants himself
   `roles/iam.serviceAccountTokenCreator` on the service account once. `gcloud auth
   print-access-token --impersonate-service-account=<sa-email>` gives an SA token with the
   cloud-platform scope only; for the Search Console scope ask the IAM Credentials API, with the
   owner's gcloud token, for a one-hour SA token:
   `POST https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/<sa-email>:generateAccessToken`
   with `{"scope":["https://www.googleapis.com/auth/webmasters.readonly"]}` (or `webmasters`), and
   read `.accessToken` straight into the next call's header. The SA must be a user of the property.
2. **The owner's own user token**, through his own OAuth desktop client:
   `! gcloud auth application-default login --client-id-file=<client.json> --scopes=openid,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/webmasters`.

Use a token inline in a header from a command substitution, never echoed or saved:
`curl -s -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" ...`.
A helper script that fetches the SA token and makes the call keeps the token out of the
transcript; write it to the session scratchpad, not the repo.
Add `-H "x-goog-user-project: <project>"` when a call complains about quota project.

## Search Console API

Base `https://www.googleapis.com/webmasters/v3` (sites, sitemaps, search analytics) and
`https://searchconsole.googleapis.com/v1` (URL inspection). The property id is
`sc-domain:example.com` for a domain property or `https://example.com/` for a URL prefix,
URL-encoded in paths.

- `GET sites` lists properties and the caller's permission level; `PUT sites/<site>` adds one.
- `PUT sites/<site>/sitemaps/<feed>` submits a sitemap, `GET .../sitemaps` lists them with errors.
- `POST sites/<site>/searchAnalytics/query` with `{"startDate","endDate","dimensions":["query"|"page"|"date"|...],"rowLimit"}`.
- `POST /v1/urlInspection/index:inspect` with `{"inspectionUrl","siteUrl"}`: index status of one URL.
  Quota is per property per day and per minute; check the limits page before a batch.

The API has no method for users or permissions: adding a user stays in the UI.

## Giving a service account access to a property

- **UI (one click for the owner):** open
  `https://search.google.com/search-console/users?resource_id=<URL-encoded property>`, Add user,
  paste the SA e-mail, permission Full (or Restricted for read-only use).
- **Site Verification as the SA (no UI, needs DNS):** with the SA's token
  (scope `https://www.googleapis.com/auth/siteverification`): `POST
  https://www.googleapis.com/siteVerification/v1/token` with
  `{"site":{"type":"INET_DOMAIN","identifier":"example.com"},"verificationMethod":"DNS_TXT"}`,
  add the returned TXT record (Cloudflare, owner-authorized), then `POST
  .../webResource?verificationMethod=DNS_TXT` with the same `site`. The SA becomes a verified
  owner; then `PUT sites/sc-domain:example.com` as the SA. Test once per site before relying on it.

## Service account, key and secret

```bash
gcloud services enable searchconsole.googleapis.com --project <id>
gcloud iam service-accounts create <site>-gsc --display-name "<site> Search Console reader" --project <id>
gcloud iam service-accounts keys create <private-tmp>/sa.json --iam-account <sa-email>
gh secret set GSC_SERVICE_ACCOUNT_JSON < <private-tmp>/sa.json
rm <private-tmp>/sa.json
```

Each is an owner-authorized change. The SA needs no project IAM role to call Search Console: its
access comes from the property's user list. A key file is a long-lived secret: prefer Workload
Identity Federation for GitHub Actions when the consumer supports it, and delete old keys
(`gcloud iam service-accounts keys list/delete`). An org policy may block key creation
(`iam.disableServiceAccountKeyCreation`); the error says so.

## CrUX and PageSpeed API keys

```bash
gcloud services enable chromeuxreport.googleapis.com apikeys.googleapis.com --project <id>
gcloud services api-keys create --display-name "<site> CrUX" --api-target=service=chromeuxreport.googleapis.com --project <id> --format json > <private-tmp>/key.json
gcloud services api-keys get-key-string <key-resource-name> --format "value(keyString)" | gh secret set CRUX_API_KEY
```

The create output holds the key string: keep it in the private temp file, read the resource name
from it with `jq -r .response.name` (or `gcloud services api-keys list`), then delete the file.
PageSpeed is the same with `pagespeedonline.googleapis.com`. Query:
`POST https://chromeuxreport.googleapis.com/v1/records:queryRecord?key=$CRUX_API_KEY` with
`{"origin":"https://example.com","formFactor":"PHONE"}` (404 = not enough traffic yet).

## Not for websites

The Indexing API accepts only pages with JobPosting or BroadcastEvent (livestream) markup. For an
ordinary site, submit sitemaps; Google does not take part in IndexNow.
