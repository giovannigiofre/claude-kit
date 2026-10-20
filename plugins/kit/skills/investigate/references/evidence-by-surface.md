# Evidence by failure surface

Used by `kit:investigate` step 1. For each surface: what to collect yourself, what to ask the
user for (with exact steps), and what to check first. Ask for everything in **one** batched
request, and always pair a failing instance with a working one.

Files from the user go in `.debug/` (gitignored) or are attached in chat. Remind them to redact
tokens, cookies and personal data.

---

## Local code / tests

**Yourself:** run the failing command or test (or the project's `check` from `.claude/kit.json`); full output; `git status`, `git diff`, `git log`; runtime/dependency versions; env vars the code reads (names only).
**Ask:** usually nothing. At most the exact command and environment they used.
**Check the plug:** stale build/cache, wrong virtualenv/node version, uncommitted changes, test order dependence.

---

## Backend / cloud / production

**Yourself:** if a CLI or MCP for the platform is connected and authorized, query directly — narrow time window, then widen. Otherwise the user exports.
**Ask (UI-only access):**
- Export of the **failing** window/run as JSON (not screenshots), time range ±15 min around the failure
- Export of a **successful** window/run with the same filter
- The ID of one failing request/run (trace ID, request ID, execution name, insertId)
- Deploy/revision that was live, and any config/secret change around the start time
**Check the plug:** wrong project/region/revision, missing env var or secret in that revision, IAM/permission changes, quota/limits, cold start / timeout settings, dependency service down.

Platform guides:
- **GCP (Logs Explorer UI)** → `gcp-logs-manual-export.md`
- **AWS CloudWatch:** Logs Insights → run query (`fields @timestamp, @message | filter @message like /ERROR|Exception/ | sort @timestamp asc`) → Export results → JSON/CSV.
- **Azure:** Log Analytics → KQL query → Export → CSV.
- **Vercel / Netlify / Render / Supabase / similar:** dashboard logs filtered by deployment/function and time; download if offered, else copy the relevant block as text.

---

## Frontend / browser

**Yourself:** if browser tools exist (Claude in Chrome, Chrome DevTools MCP, Playwright), reproduce the steps and read console errors, failed network requests and a screenshot. Run the local dev build and compare with the production build.
**Ask:**
- Exact steps, URL, account/role, browser + version, device, prod or staging
- **Console:** DevTools → Console → right-click → "Save as…" (or copy all errors with stack traces)
- **Network:** DevTools → Network → reproduce with "Preserve log" on → right-click → "Save all as HAR". Warn: HAR contains cookies/auth headers, redact or generate it with a test account.
- Screenshot or short screen recording of the wrong state
- Does it happen in an incognito window / another browser? (rules out extensions, cache, stored state)
**Check the plug:** cached old bundle / service worker, env var not baked into the build, CORS, feature flag, source maps missing, different API base URL between envs, local storage state.

---

## CI / build / deploy

**Yourself:** with `gh` or the CI CLI, fetch the failed job log and the last green job log; diff them. Compare runner image, tool versions, lockfile, cache keys.
**Ask (UI only):** raw log of the failed job and of the last green one (download "raw logs"), plus the commit SHAs.
**Check the plug:** cache poisoned/stale, unpinned dependency released a new version, secret missing on that branch/fork, runner image updated, path/case sensitivity (macOS vs Linux).

---

## Data / ML / LLM pipelines

**Yourself:** run the pipeline on a tiny failing sample; log row counts, schema and a sample record at each step boundary; model/prompt/version and parameters.
**Ask:** a failing input sample and a working one (redacted), the run ID, the trace from the observability tool if any (Langfuse/LangSmith/OTel export as JSON), expected vs actual output.
**Check the plug:** schema drift, nulls/encoding/timezones, silent truncation, model or prompt version changed, nondeterminism (temperature, retries), rate limits returning partial results.

---

## Third-party integrations / APIs

**Yourself:** reproduce the call with a minimal script (curl or code) using test credentials; capture status, headers, body.
**Ask:** the sanitized request/response of a failing call and a working one, the provider's dashboard error log, API version, whether the provider status page showed an incident.
**Check the plug:** expired/rotated credentials, API version deprecation, rate limiting, webhook signature/clock skew, sandbox vs live keys.

---

## Performance

**Yourself:** measure before touching anything: timings, profiler (py-spy, cProfile, Node --prof, browser Performance panel or DevTools trace), query plans (`EXPLAIN ANALYZE`).
**Ask:** when it got slow, metrics dashboard export or screenshot with time axis, a slow request ID vs a normal one.
**Rule:** no optimization without a measurement that shows where time goes, and the same measurement after the fix.
