#!/usr/bin/env python3
"""Tests for the web-ops doctor: no secret reaches its output, accounts are compared, and the exit
code says when the owner must act. Fake runners only: no network, no real CLI calls."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import doctor  # noqa: E402

GOOD = {
    ("node", "--version"): (0, "v24.22.1"),
    ("gcloud", "--version"): (0, "Google Cloud SDK 560.0.0"),
    ("gh", "--version"): (0, "gh version 2.99.0"),
    ("jq", "--version"): (0, "jq-1.8.1"),
    ("curl", "--version"): (0, "curl 8.17.0"),
    ("cf", "--version"): (0, "1.0.0-rc.1"),
    ("gcloud", "auth", "list", "--format=json"): (0, json.dumps([
        {"account": "site-owner@example.com", "status": "ACTIVE"},
        {"account": "personal@example.com", "status": ""}])),
    ("gcloud", "config", "get-value", "project"): (0, "site-project"),
    ("cf", "auth", "whoami"): (0, '{"email": "site-owner@example.com", "accounts": [{"id": "0123456789abcdef0123456789abcdef"}]}'),
    ("wrangler", "whoami"): (0, "You are logged in with an OAuth Token, associated with the email site-owner@example.com.\n| Site | 0123456789abcdef0123456789abcdef |"),
    ("gh", "auth", "status", "--active"): (0, "github.com\n  Logged in to github.com account owner (keyring)\n  Token: gho_abcdefghijklmnopqrstuvwxyz0123"),
    ("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"): (0, "owner/site"),
    ("claude", "mcp", "list"): (0, "cloudflare: https://mcp.cloudflare.com/mcp (HTTP) - Connected\nother: x - Connected"),
}


def fake(table):
    def runner(cmd, cwd=None, timeout=30):
        key = tuple(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd))
        return table.get(key, (127, ""))
    return runner


def which_all(name):
    return "/usr/bin/" + name


def run_main(argv, table, which=which_all):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = doctor.main(argv, runner=fake(table), which=which)
    return code, buf.getvalue()


class Redaction(unittest.TestCase):
    def test_masks_tokens_and_keys(self):
        for secret in ("gho_abcdefghijklmnopqrstuvwxyz0123", "ya29.a0AfH6SMBexampletokenvalue",
                       "AIzaSyA1234567890abcdefghijklmnopq", "Bearer abcdefghijklmnop",
                       "token: s3cr3tvalue", "x" * 50):
            self.assertNotIn(secret.split()[-1], doctor.redact(f"before {secret} after"), secret)

    def test_keeps_emails_and_account_ids(self):
        text = "site-owner@example.com 0123456789abcdef0123456789abcdef"
        self.assertEqual(doctor.redact(text), text)


class Emails(unittest.TestCase):
    def test_dedupes_case_and_drops_trailing_dot(self):
        out = "associated with the email Owner@Example.com.\nowner@example.com"
        self.assertEqual(doctor.find_emails(out), ["owner@example.com"])


class NodeEngines(unittest.TestCase):
    def test_cf_engine_ranges(self):
        self.assertTrue(doctor.node_ok_for_cf((24, 22, 0)))
        self.assertTrue(doctor.node_ok_for_cf((26, 12, 1)))
        self.assertFalse(doctor.node_ok_for_cf((24, 18, 1)))
        self.assertFalse(doctor.node_ok_for_cf((25, 0, 0)))
        self.assertFalse(doctor.node_ok_for_cf(None))


class Doctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = {v: os.environ.pop(v) for v in doctor.CREDENTIAL_VARS if v in os.environ}

    def tearDown(self):
        os.environ.update(self.saved)

    def test_all_good_exits_zero_and_leaks_nothing(self):
        code, out = run_main(["--project-dir", self.tmp, "--expect-google", "site-owner@example.com",
                              "--expect-cloudflare", "0123456789abcdef0123456789abcdef"], GOOD)
        self.assertEqual(code, 0, out)
        self.assertNotIn("gho_", out)
        self.assertIn("active=site-owner@example.com", out)
        self.assertIn("other logins=personal@example.com", out)
        self.assertIn("cloudflare (Connected)", out)
        self.assertNotIn("other (", out)

    def test_wrong_google_account_needs_owner(self):
        code, out = run_main(["--project-dir", self.tmp, "--expect-google", "personal@example.com", "--no-mcp"], GOOD)
        self.assertEqual(code, doctor.NEEDS_OWNER)
        self.assertIn("! gcloud config set account personal@example.com", out)

    def test_missing_cf_with_old_node_names_the_upgrade(self):
        table = {**GOOD, ("node", "--version"): (0, "v24.18.1")}
        code, out = run_main(["--project-dir", self.tmp, "--no-mcp"], table,
                             which=lambda n: None if n in ("cf", "wrangler") else "/usr/bin/" + n)
        self.assertEqual(code, doctor.NEEDS_OWNER)
        self.assertIn("upgrade Node", out)

    def test_wrangler_project_without_login(self):
        Path(self.tmp, "wrangler.jsonc").write_text("{}")
        table = {**GOOD, ("wrangler", "whoami"): (1, "You are not authenticated. Please run `wrangler login`.")}
        code, out = run_main(["--project-dir", self.tmp, "--no-mcp"], table)
        self.assertEqual(code, doctor.NEEDS_OWNER)
        self.assertIn("! pnpm exec wrangler login", out)

    def test_wrangler_in_a_monorepo_package(self):
        Path(self.tmp, "apps", "worker").mkdir(parents=True)
        Path(self.tmp, "apps", "worker", "wrangler.jsonc").write_text("{}")
        table = {**GOOD, ("wrangler", "whoami"): (1, "You are not authenticated.")}
        code, out = run_main(["--project-dir", self.tmp, "--no-mcp"], table)
        self.assertEqual(code, doctor.NEEDS_OWNER)
        self.assertIn("! pnpm --dir apps/worker exec wrangler login", out)

    def test_env_vars_reported_by_name_only(self):
        os.environ["BING_API_KEY"] = "verysecretvalue123"
        try:
            code, out = run_main(["--project-dir", self.tmp, "--no-mcp", "--json"], GOOD)
        finally:
            del os.environ["BING_API_KEY"]
        self.assertIn("BING_API_KEY", out)
        self.assertNotIn("verysecretvalue123", out)
        json.loads(out)


if __name__ == "__main__":
    unittest.main()
