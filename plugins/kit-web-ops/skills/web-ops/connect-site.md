# Playbook: connect a site to the search engines

From "the domain is on Cloudflare and the site is live" to "Google and Bing know the site, and the
project's automation can read their data". Each step says who acts. The agent prepares every
owner step as one command or one link, waits, then reads the result back.

Fill in first, from the project's docs or by asking once: domain, Cloudflare account and zone id,
Google account and Cloud project id, GitHub repo (`gh repo view --json nameWithOwner`), and the
secret and variable names the project's code reads (grep its workflows for `secrets.` and `vars.`).

## 0. Doctor (agent)

`python3 <skill>/scripts/doctor.py --expect-google <email> --expect-cloudflare <account>`.
Every login it reports missing becomes an owner command (step list below). Do not continue on a
wrong active account.

## 1. Search Console property (agent, or owner if DNS is not authorized)

Prefer a domain property (`sc-domain:example.com`): it covers every scheme and subdomain.

- Already verified? `GET sites` with the owner's or the SA's token lists it. If so, skip to 2.
- Otherwise: Site Verification `getToken` (INET_DOMAIN, DNS_TXT) -> add the TXT record with `cf`
  (owner-authorized) -> `webResource.insert` -> `PUT sites/sc-domain:example.com`. Leave the TXT
  record in place.
- UI alternative: `https://search.google.com/search-console/welcome` -> Domain; Cloudflare offers
  to add the record automatically ("Verify with Cloudflare").

## 2. Sitemap (agent)

`PUT sites/<property>/sitemaps/<URL-encoded sitemap URL>`, then `GET .../sitemaps` and save it.
Make sure `robots.txt` names the sitemap too: crawlers other than Google find it there.

## 3. Service account for automation (owner-authorized, agent runs it)

1. `gcloud services enable searchconsole.googleapis.com` (plus `siteverification.googleapis.com`
   if the SA will verify itself).
2. `gcloud iam service-accounts create <site>-gsc`.
3. Give it access to the property: the owner opens
   `https://search.google.com/search-console/users?resource_id=sc-domain%3Aexample.com`, Add user,
   the SA e-mail, Restricted for reading or Full when it submits sitemaps; or the SA verifies itself
   (google.md).
4. Into the repo's secrets, without the key passing through chat: the block in google.md
   ("Service account, key and secret"), which removes the key file even on failure. Then `gh variable set GSC_SITE_URL --body
   sc-domain:example.com`.
5. Check: an SA token lists the property in `GET sites` with the expected permission level.

## 4. CrUX and PageSpeed keys (owner-authorized, agent runs it)

Run the block in google.md ("CrUX and PageSpeed API keys") as it is, once per API
(`chromeuxreport.googleapis.com`, and `pagespeedonline.googleapis.com` if used): `api-keys create`
prints the key on stderr, so do not shorten it to a bare command or a stdout-only redirect.
Check with one `records:queryRecord` call (404 = too little traffic yet, which is fine).

## 5. Bing (owner, then agent)

1. Owner: `https://www.bing.com/webmasters` -> sign in -> Add site -> Import from Google Search
   Console, with the project's Google account. Two clicks, no DNS.
2. Owner: Settings -> API Access -> Generate API Key, then `! pbpaste | gh secret set BING_API_KEY`.
3. Agent: `GetUserSites` shows the site verified; `GetFeeds` shows the sitemap (else `SubmitFeed`).

## 6. IndexNow (agent prepares; the deploy is owner-authorized)

1. Agent: generate a key (`python3 -c "import secrets; print(secrets.token_hex(16))"`; it is
   public, not a secret) and prepare the change that serves `/<key>.txt` and submits the changed
   URLs from the deploy step.
2. Owner authorizes the production deploy (SKILL.md section 5), or runs it; without that, stop with
   the change ready.
3. Agent, after the deploy: fetch `/<key>.txt` back and check the submission's response code
   (200/202).

## 7. Cloudflare analytics for dashboards (owner, then agent)

1. Owner creates a token at `https://dash.cloudflare.com/profile/api-tokens` -> Custom token:
   Zone - Analytics - Read and Account - Account Analytics - Read, resources limited to this zone and
   this account, named `<site>-analytics-read`. Never the deploy token.
2. Owner: `! pbpaste | gh secret set CF_ANALYTICS_TOKEN`; agent: `gh variable set CF_ZONE_ID
   --body <zone-id>`.
3. Agent: one GraphQL query for the last 7 days with that token returns data.

## 8. Read back and record (agent)

`gh secret list` and `gh variable list` (names and dates only), the saved outputs of steps 1-7,
and a note in the project's ops doc: each secret's name, what it can do, who made it, and when to
rotate it.

## Owner commands, typed with `!` in the Claude Code prompt

```
! gcloud auth login
! gcloud config set account <email>
! gcloud config set project <project-id>
! cf auth login
! pnpm exec wrangler login
! pbpaste | gh secret set BING_API_KEY
! pbpaste | gh secret set CF_ANALYTICS_TOKEN
```

Clear the clipboard after each paste (`! pbcopy < /dev/null`).
