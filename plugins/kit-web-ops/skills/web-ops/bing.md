# Bing Webmaster Tools and IndexNow

Checked 2026-11-17. Sources are in `../../docs/research.md`.

## What is UI-only

- **Signing in and the API key.** Bing Webmaster Tools -> Settings (gear) -> API Access -> API Key
  -> Generate. One key per user, valid for all of that user's sites; regenerating revokes the old
  one. The owner copies it and stores it with `! pbpaste | gh secret set BING_API_KEY`.
- **Import from Google Search Console.** "Add a site" -> Import from GSC signs in with Google and
  copies the verified properties, their sitemaps and verification, so no DNS change is needed. The
  owner picks the same Google account the project uses (the doctor names it).

Everything after that is the API.

## The API

JSON endpoint `https://ssl.bing.com/webmaster/api.svc/json/<Method>?apikey=<key>` (the host in
Microsoft's API-key samples; its OAuth sample uses `www.bing.com`; docs read 2026-11-24, no call made)
(GET for reads with query parameters; POST with a JSON body for writes). Errors come back as
HTTP 400 with `{"ErrorCode": n, "Message": "..."}`; 3 = InvalidApiKey. Keep the key in an
environment variable or a gh secret; it is part of the URL (the only
documented place for it), so pass the URL to curl on stdin and do not log full request URLs.

| Task | Method |
|---|---|
| List the user's sites and their verification | `GetUserSites` |
| Add a site / verify it | `AddSite` `{"siteUrl"}`, `VerifySite` (after the DNS or file proof) |
| Sitemaps | `SubmitFeed` `{"siteUrl","feedUrl"}`, `GetFeeds?siteUrl=` |
| Submit URLs (quota per day) | `GetUrlSubmissionQuota?siteUrl=`, `SubmitUrlBatch` `{"siteUrl","urlList"}` |
| Search performance | `GetQueryStats`, `GetPageStats`, `GetRankAndTrafficStats` (`?siteUrl=`) |
| Crawl health | `GetCrawlStats`, `GetCrawlIssues`, `GetUrlInfo?siteUrl=&url=` |
| Users on a site | `GetSiteRoles`, `AddSiteRoles` (owner-authorized) |

`siteUrl` is the URL form Bing shows (`https://example.com/`), even for a site imported from a GSC
domain property. Check a method's parameters on the interface reference before the first call.

Example, without printing the key or putting it in curl's arguments:

```bash
printf 'url = "https://ssl.bing.com/webmaster/api.svc/json/GetUserSites?apikey=%s"\n' "$BING_API_KEY" \
  | curl -sS --config - | jq '.d[] | {Url, IsVerified}'
```

## IndexNow

IndexNow tells Bing, Yandex, Seznam, Naver, Yep and other participants that URLs changed; one
submission is shared among them. Google does not participate.

- A key of 8-128 characters `[a-zA-Z0-9-]`, served as `https://<host>/<key>.txt` containing the key
  (or at `keyLocation` on the same host). The key is public by design, not a secret.
- `POST https://api.indexnow.org/indexnow` with
  `{"host","key","keyLocation","urlList":[...]}` (up to 10,000 URLs), or a GET with `?url=&key=`.
- 200/202 accepted; 400 bad request; 403 key not found at the location; 422 URLs not on the host;
  429 too many requests.
- Submit only URLs that changed (new, updated, deleted), from the deploy step, not on every build.
  Bing Webmaster Tools shows IndexNow submissions under its IndexNow report.

## Community MCP servers

Several community Bing Webmaster MCP servers exist (MIT, single maintainers). They wrap the same
JSON API and need the same key; curl does it without another process holding the key, so the kit
does not use them.
