---
name: web-ops
description: Operates a website's outside services from the terminal - Cloudflare (DNS records, API tokens, Workers secrets, zone analytics), Google Search Console (verification, sitemaps, search analytics, URL inspection, service-account access), Google Cloud API keys for CrUX and PageSpeed, Bing Webmaster and IndexNow - and connects a new site to the search engines end to end. Use for any of these, or when a login, an account or a secret for them is in question.
argument-hint: "[task, e.g. 'connect example.com to search engines' or 'add a TXT record']"
---

# web-ops: Cloudflare, Google and Bing for a website, from the terminal

Task: $ARGUMENTS (if empty, the site operation this conversation is about).

The cheapest reliable path is a CLI or a plain REST call whose JSON goes to a file: no tool schemas
in context, the same command works in CI, and the output is evidence. An MCP server is the second
choice, for one-off exploration or when its OAuth click saves the owner from minting a token.
Browser clicking is the last resort, for the few steps the providers keep UI-only. The comparison
and its sources are in [../../docs/research.md](../../docs/research.md).

## 1. Doctor first

Run `python3 <this skill's folder>/scripts/doctor.py` (add `--json` for a file, `--expect-google
<email>` and `--expect-cloudflare <email or account id>` when the project names its accounts). It
lists the CLIs, which account each one is signed in as, the GitHub repo `gh` would write secrets
to, which credential variables are set (names only) and the MCP servers. Exit 10 means something
needs the owner. It never prints a secret.

When a login is missing, give the owner the exact command to type with `!` (for example
`! gcloud auth login`, `! cf auth login`) and wait. Logins, OAuth consent, passwords and 2FA are
the owner's: an agent does not run them, script them or click through them.

## 2. Confirm the account before acting

Most mistakes here are the right command on the wrong account: a second Google login, a Cloudflare
user with several accounts, `gh` pointed at a fork. Before any change, state in one line the
account, project or zone and repository the command will touch, from the doctor's output, and
compare them with what the project's docs name (CLAUDE.md, a HUMAN_TODO or ops doc). A mismatch
stops the task until the owner says which one is right.

## 3. Pick the path

| Service | Read the reference | Default tool |
|---|---|---|
| Cloudflare DNS, zones, tokens, analytics | [cloudflare.md](cloudflare.md) | `cf` CLI (JSON out, `--dry-run`), REST with curl for GraphQL analytics |
| Workers secrets, deploy, logs in a Wrangler project | [cloudflare.md](cloudflare.md) | the project's `wrangler` (`pnpm exec wrangler`, `npx wrangler`) |
| Search Console, Site Verification, CrUX, PageSpeed, service accounts | [google.md](google.md) | `gcloud` for the project, keys and tokens; curl for the REST APIs |
| Bing Webmaster, IndexNow | [bing.md](bing.md) | curl to the JSON API; IndexNow from the site's deploy |
| A new site end to end | [connect-site.md](connect-site.md) | the playbook, in order |

`cf cli search "<task>"` and `cf schema <command>` find Cloudflare commands; read the provider's
current page for anything not in the references rather than recalling API shapes.

## 4. What only the owner does

Some steps are UI-only or need the owner's identity. Prepare everything around them so each is one
link and one click, then wait:

- logins and OAuth consent (gcloud, `cf`, wrangler, an MCP server's "Authenticate");
- adding a user to a Search Console property (no API exists): give the deep link
  `https://search.google.com/search-console/users?resource_id=<property, URL-encoded>` and the
  e-mail to paste;
- the Bing Webmaster API key and "Import from Google Search Console" (UI only);
- creating a Cloudflare API token in the dashboard, with the permission list written out.

## 5. Guard rules

- **Authorized changes only.** DNS records, tokens, keys, service accounts, IAM bindings, enabled
  APIs, GitHub secrets, Workers secrets (`wrangler secret put` deploys immediately) and production
  deploys change what the site trusts or serves. Do each only when the owner asked for that
  change in this conversation or a brief states it; otherwise write the exact commands down as a
  plan and stop. A `--dry-run` or a GET is always fine.
- **No secret in chat, logs or files in the repo.** A secret moves from the command that makes it
  straight into its store: `<maker> | gh secret set NAME` (gh reads stdin, nothing is echoed), or
  a file in a private temp folder that is passed with `<` and deleted right after. Never
  `echo $TOKEN`, `cat key.json`, `set -x`, or a secret as a command-line argument (it lands in the
  shell history and `ps`); curl takes it on stdin (`-H @-`, `--config -`). When a command prints a
  secret by design, capture stdout **and stderr** (`> file 2>&1`) in a private (`umask 077`) temp
  folder removed on every exit, failures included.
- **Least privilege.** One token per job, scoped to one zone or account and to read when reading
  is the job; API keys restricted to the one API they serve; a service account with only the
  Search Console role it needs. Write the scope next to the secret's name in the project's docs.
- **Read back.** After a change, read the resource again (`cf dns records list`, `sites.get`,
  `gh secret list`) and save that output, without values, as evidence.
- **Quotas and politeness.** Respect the API's quotas (URL Inspection, Bing URL submission);
  batch, and never loop a write on failure.

## 6. Hand-off

Report: what changed and where (account, zone or property), the read-back evidence, the commands
left for the owner (each one line, typed with `!`), and the secrets set, by name only.
