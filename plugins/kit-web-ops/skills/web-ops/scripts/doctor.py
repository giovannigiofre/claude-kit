#!/usr/bin/env python3
"""Web-ops doctor: which CLIs are installed, which account each is signed in as, where gh would
write secrets, which credential variables are set (names only) and which MCP servers are there.

Standard library only. It runs read-only status commands and never prints a secret: every line
passes through redact(), and environment variables are reported as set or unset.

Run:  python3 doctor.py [--json] [--expect-google EMAIL] [--expect-cloudflare EMAIL_OR_ACCOUNT_ID]
      [--project-dir DIR] [--no-mcp]
Exit: 0 all good, 10 something needs the owner (a login, an install, a wrong account).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

NEEDS_OWNER = 10
CF_NODE = ((22, 23), (24, 22), (26, 12))  # the cf CLI's engines field, checked 2026-11-17
CREDENTIAL_VARS = (
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CF_ANALYTICS_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS",
    "GSC_SERVICE_ACCOUNT_JSON", "CRUX_API_KEY", "BING_API_KEY",
)
MCP_HINTS = ("cloudflare", "search console", "search-console", "searchconsole", "gsc", "bing", "webmaster",
             "pagespeed", "crux", "google cloud", "gcloud")
# (pattern, keep group 1): a prefix such as "Bearer " stays, the value goes
SECRET_PATTERNS = (
    (re.compile(r"\bgh[opusr]_[A-Za-z0-9]{8,}"), False),  # GitHub tokens
    (re.compile(r"\bya29\.[A-Za-z0-9._-]{8,}"), False),  # Google OAuth access tokens
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"), False),  # Google API keys
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), True),
    (re.compile(r"(?i)((?:token|apikey|api_key|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',]{6,}"), True),
    (re.compile(r"\b[A-Za-z0-9_-]{41,}\b"), False),  # any long opaque string (account ids are 32 hex)
)


def redact(text):
    """Mask anything that looks like a token or key; keep e-mails, account ids and names."""
    for pattern, keep in SECRET_PATTERNS:
        text = pattern.sub((lambda m: m.group(1) + "[redacted]") if keep else (lambda m: "[redacted]"), text)
    return text


def run(cmd, cwd=None, timeout=30):
    """Run one status command; return (exit code, stdout+stderr) and never raise."""
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL, env={**os.environ, "NO_COLOR": "1", "CLOUDSDK_CORE_DISABLE_PROMPTS": "1"})
        return out.returncode, (out.stdout + out.stderr).strip()
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def find_emails(text):
    """E-mail addresses in a CLI's output, lower-cased and without duplicates."""
    return sorted({e.lower() for e in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")})


def version_tuple(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def node_ok_for_cf(version):
    """True when a Node version satisfies cf's engines (^22.23 || ^24.22 || ^26.12)."""
    if not version:
        return False
    return any(version[0] == major and version[1:2] >= (minor,) for major, minor in CF_NODE)


def check(name, ok, detail, fix=""):
    return {"name": name, "ok": bool(ok), "detail": redact(detail), "fix": fix}


def tool_checks(runner, which):
    results = []
    node = which("node")
    node_v = version_tuple(runner([node, "--version"])[1]) if node else None
    for tool, cmd, fix in (
        ("gcloud", ["gcloud", "--version"], "brew install --cask gcloud-cli"),
        ("gh", ["gh", "--version"], "brew install gh"),
        ("jq", ["jq", "--version"], "brew install jq"),
        ("curl", ["curl", "--version"], "brew install curl"),
        ("node", ["node", "--version"], "brew install node"),
    ):
        path = which(tool)
        first = (runner(cmd)[1].splitlines() or [""])[0] if path else ""
        results.append(check(f"installed: {tool}", path, first or "not found", "" if path else fix))
    cf = which("cf")
    if cf:
        results.append(check("installed: cf", True, (runner(["cf", "--version"])[1].splitlines() or ["cf"])[0]))
    else:
        fix = "npm install --global cf"
        if node_v and not node_ok_for_cf(node_v):
            fix = "upgrade Node to >=22.23, >=24.22 or >=26.12 (cf's engines), then " + fix
        results.append(check("installed: cf", False, "not found (official Cloudflare CLI, optional; curl works without it)", fix))
    if node_v:
        upgrade = "nvm install 24 then nvm alias default 24" if "/.nvm/" in (node or "") else "brew upgrade node"
        results.append(check("node satisfies cf engines", node_ok_for_cf(node_v), ".".join(map(str, node_v)),
                             "" if node_ok_for_cf(node_v) else upgrade))
    return results


def gcloud_checks(runner, which, expect):
    if not which("gcloud"):
        return []
    code, out = runner(["gcloud", "auth", "list", "--format=json"])
    try:
        accounts = json.loads(out) if code == 0 else []
    except ValueError:
        accounts = []
    active = [a.get("account", "") for a in accounts if a.get("status") == "ACTIVE"]
    others = [a.get("account", "") for a in accounts if a.get("status") != "ACTIVE"]
    project = runner(["gcloud", "config", "get-value", "project"])[1].splitlines()
    project = next((p for p in project if p and "(unset)" not in p and not p.startswith("Your active")), "")
    detail = f"active={active[0] if active else 'none'}; other logins={', '.join(others) or 'none'}; project={project or 'unset'}"
    results = [check("gcloud login", active, detail, "" if active else "! gcloud auth login")]
    if expect and active:
        same = active[0].lower() == expect.lower()
        results.append(check("gcloud account is the project's", same, f"active={active[0]} expected={expect}",
                             "" if same else f"! gcloud config set account {expect}"))
    adc = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
    results.append(check("gcloud application-default credentials (info)", True,
                         "present" if os.path.isfile(adc) else "none (only needed for ADC-based tools)"))
    return results


def cf_checks(runner, which, expect):
    if not which("cf"):
        return []
    code, out = runner(["cf", "auth", "whoami"])
    emails = find_emails(out)
    ids = sorted(set(re.findall(r"\b[0-9a-f]{32}\b", out)))
    ok = code == 0 and (emails or ids or "token" in out.lower())
    results = [check("cf login", ok, f"user={', '.join(emails) or '?'}; accounts={', '.join(ids) or '?'}" if ok else (out.splitlines() or ["not logged in"])[0],
                     "" if ok else "! cf auth login")]
    if expect and ok:
        same = expect.lower() in [e.lower() for e in emails + ids]
        results.append(check("cf account is the project's", same, f"expected={expect}", "" if same else "! cf auth login --force (pick the right account)"))
    return results


def wrangler_dir(project_dir):
    """The folder with a Wrangler config: the project root or a workspace package two levels down
    (apps/worker), so a monorepo's Worker is found too."""
    names = ("wrangler.toml", "wrangler.json", "wrangler.jsonc")
    candidates = [project_dir] + sorted(
        os.path.join(project_dir, a, b) for a in ("apps", "packages", "workers") if os.path.isdir(os.path.join(project_dir, a))
        for b in os.listdir(os.path.join(project_dir, a)))
    return next((d for d in candidates if any(os.path.isfile(os.path.join(d, n)) for n in names)), "")


def wrangler_checks(runner, which, project_dir, expect):
    config_dir = wrangler_dir(project_dir)
    has_config = bool(config_dir)
    rel = os.path.relpath(config_dir, project_dir) if config_dir else "."
    login = "! pnpm exec wrangler login" if rel == "." else f"! pnpm --dir {rel} exec wrangler login"
    project_dir = config_dir or project_dir
    local = os.path.join(project_dir, "node_modules", ".bin", "wrangler")
    binary = local if os.path.isfile(local) else which("wrangler")
    if not binary:
        return [check("wrangler", not has_config, "not installed" + (" but this project has a wrangler config" if has_config else " (only needed in a Workers project)"),
                      "pnpm install (the project pins wrangler)" if has_config else "")]
    code, out = runner([binary, "whoami"], cwd=project_dir, timeout=60)
    emails = find_emails(out)
    ids = sorted(set(re.findall(r"\b[0-9a-f]{32}\b", out)))
    ok = code == 0 and "not authenticated" not in out.lower() and (emails or ids)
    via = "CLOUDFLARE_API_TOKEN" if os.environ.get("CLOUDFLARE_API_TOKEN") else "OAuth login"
    results = [check("wrangler login", ok, f"via={via}; user={', '.join(emails) or '?'}; accounts={', '.join(ids) or '?'}" if ok else "not authenticated",
                     "" if ok else login)]
    if expect and ok:
        same = expect.lower() in [e.lower() for e in emails + ids]
        results.append(check("wrangler account is the project's", same, f"expected={expect}", "" if same else login))
    return results


def gh_checks(runner, which, project_dir):
    if not which("gh"):
        return []
    code, out = runner(["gh", "auth", "status", "--active"])
    if code != 0:
        code, out = runner(["gh", "auth", "status"])
    user = re.search(r"account (\S+)", out)
    results = [check("gh login", code == 0 and user, f"user={user.group(1) if user else '?'}", "" if code == 0 else "! gh auth login")]
    code, out = runner(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=project_dir)
    results.append(check("gh repo for secrets", code == 0 and out, out if code == 0 else "not a GitHub repo here", ""))
    return results


def env_checks():
    found = [v for v in CREDENTIAL_VARS if os.environ.get(v)]
    return [check("credential variables set (names only)", True, ", ".join(found) or "none", "")]


def mcp_checks(runner, which):
    if not which("claude"):
        return [check("mcp servers", True, "claude command not found; skipped", "")]
    code, out = runner(["claude", "mcp", "list"], timeout=60)
    lines = []
    for line in out.splitlines():
        name = line.split(":", 1)[0].strip()
        if ":" in line and any(h in name.lower() for h in MCP_HINTS):
            status = line.rsplit(" - ", 1)[-1].strip() if " - " in line else "?"
            lines.append(f"{name} ({status})")
    return [check("mcp servers (web ops)", True, "; ".join(lines) or "none configured (optional: the CLIs cover every task)", "")]


def collect(args, runner=run, which=shutil.which):
    results = tool_checks(runner, which)
    results += gcloud_checks(runner, which, args.expect_google)
    results += cf_checks(runner, which, args.expect_cloudflare)
    results += wrangler_checks(runner, which, args.project_dir, args.expect_cloudflare)
    results += gh_checks(runner, which, args.project_dir)
    results += env_checks()
    if not args.no_mcp:
        results += mcp_checks(runner, which)
    return results


def main(argv=None, runner=run, which=shutil.which):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--expect-google", default="")
    parser.add_argument("--expect-cloudflare", default="")
    parser.add_argument("--project-dir", default=os.getcwd())
    parser.add_argument("--no-mcp", action="store_true")
    args = parser.parse_args(argv)
    results = collect(args, runner, which)
    failing = [r for r in results if not r["ok"]]
    if args.json:
        print(json.dumps({"ok": not failing, "checks": results}, indent=2))
    else:
        for r in results:
            print(f"{'ok  ' if r['ok'] else 'NEED'} {r['name']}: {r['detail']}" + (f"\n     fix: {r['fix']}" if r["fix"] and not r["ok"] else ""))
        print(f"doctor: {len(results)} checks, {len(failing)} need the owner")
    return NEEDS_OWNER if failing else 0


if __name__ == "__main__":
    sys.exit(main())
