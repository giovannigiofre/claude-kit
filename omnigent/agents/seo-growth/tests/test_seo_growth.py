#!/usr/bin/env python3
"""seo-growth's deterministic half: score.py's guardrails, the ledger, the sources parser, the schema lint
pull.sh/report.sh token handling (stubbed `security` and
curl) and ship.sh's gate rule. Standard library only, no network, no Keychain secret read.

Each scenario starts from tests/fixtures/fiscometro-run (a pull shaped like the live admin API) and changes one
thing. The model-judged half (does Claude pick well, refuse an injected instruction, keep numbers sourced)
is in the eval cases outside the repo: ~/Documents/omnigent-research/evals/cases/seo-growth/.

Run: python3 omnigent/agents/seo-growth/tests/test_seo_growth.py
"""

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT / "scripts"
FIX = Path(__file__).resolve().parent / "fixtures"
TODAY = "2026-10-20"


def py(script, *args, env=None):
    return subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, env=env)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="seo-growth-test-"))
        self.run = self.tmp / "run"
        shutil.copytree(FIX / "fiscometro-run", self.run)
        self.state = self.tmp / "state" / "fiscometro"
        self.state.mkdir(parents=True)
        self.env = {**os.environ, "SEO_GROWTH_HOME": str(self.tmp / "state")}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def edit(self, name, fn):
        p = self.run / name
        data = json.loads(p.read_text())
        fn(data)
        p.write_text(json.dumps(data))

    def ledger(self, *entries):
        with (self.state / "ledger.jsonl").open("a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def score(self, project="fiscometro", today=TODAY, run=None, env=None):
        run = run or self.run
        p = py("score.py", run, "--project", project, "--today", today, "--state", self.state, env=env or self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads((run / "candidates.json").read_text())

    def ids(self, out):
        return [c["id"] for c in out["candidates"]]

    def dropped(self, out, prefix):
        return [d["reason"] for d in out["dropped"] if d["id"].startswith(prefix)]

    def data_dir(self, calendar_fn):
        """A copy of data/ with calendar.json changed (the real file stays as the owner left it)."""
        data = self.tmp / "data"
        shutil.copytree(AGENT / "data", data)
        cal = json.loads((data / "calendar.json").read_text())
        calendar_fn(cal)
        (data / "calendar.json").write_text(json.dumps(cal))
        return {**self.env, "SEO_GROWTH_DATA": str(data)}


class Ranking(Case):
    def test_fixture_pull_gives_ranked_candidates(self):
        out = self.score()
        self.assertEqual(out["decision"]["action"], "candidates")
        prefs = [(c["preference"], -c["score"]) for c in out["candidates"]]
        self.assertEqual(prefs, sorted(prefs), "ranked by preference, then score")
        self.assertTrue(all(c["score"] >= 20 for c in out["candidates"]))
        self.assertLessEqual(len(out["candidates"]), 5)
        self.assertEqual(out["curve"]["4-6"]["source"], "site")

    def test_low_ctr_title(self):
        out = self.score()
        c = next(c for c in out["candidates"] if c["id"] == "low-ctr:/tredicesima/")
        self.assertGreater(c["score"], 100)
        self.assertIn("tredicesima netta", c["evidence"]["top_queries"])

    def test_striking_distance(self):
        out = self.score()
        self.assertIn("striking-distance:/guide/forfettario-2027/:forfettario 2027", self.ids(out))

    def test_internal_links_at_most_three(self):
        out = self.score()
        c = next(c for c in out["candidates"] if c["type"] == "internal-links")
        self.assertLessEqual(len(c["evidence"]["links"]), 3)
        self.assertIn("src/lib/tool-page.ts", c["evidence"]["register_in"])

    def test_nothing_below_threshold(self):
        def shrink(d):
            for r in d["rows"]:
                r["impressions"] //= 20
                r["clicks"] //= 20
                if r.get("previous"):
                    r["previous"]["clicks"] //= 20
            for c in d.get("cannibalised", []):
                c["impressions"] //= 20
                for p in c["pages"]:
                    p["impressions"] //= 20
        self.edit("pages.json", shrink)
        self.edit("queries.json", shrink)
        (self.run / "schema.json").unlink()
        out = self.score()
        self.assertEqual(out["decision"]["action"], "nothing")
        self.assertEqual(out["candidates"], [])
        self.assertIn("floor", out["decision"]["reason"])

    def test_leave_winners_alone(self):
        self.ledger({"id": "2026-07-01-1", "type": "low-ctr", "pages": ["/tredicesima/"], "state": "merged",
                     "merged_on": "2026-07-01", "verdict": "keep", "verdict_on": "2026-08-05"})
        out = self.score()
        self.assertNotIn("low-ctr:/tredicesima/", self.ids(out))
        self.assertTrue(any("winner" in r for r in self.dropped(out, "low-ctr:/tredicesima/")))


class Stops(Case):
    def test_prelaunch_nettoswiss(self):
        run = self.tmp / "ns"
        shutil.copytree(FIX / "nettoswiss-prelaunch-run", run)
        out = self.score(project="nettoswiss", today="2026-11-22", run=run)
        self.assertEqual(out["decision"]["action"], "stop")
        self.assertIn("pre-launch until 2026-12-15", out["decision"]["reason"])

    def test_no_data_after_launch_is_still_a_stop(self):
        run = self.tmp / "ns"
        shutil.copytree(FIX / "nettoswiss-prelaunch-run", run)
        out = self.score(project="nettoswiss", today="2026-12-20", run=run)
        self.assertEqual(out["decision"], {"action": "stop", "reason": "no search data from the admin API"})

    def test_autopilot_paused(self):
        self.edit("summary.json", lambda s: s["autopilot"].update(enabled=False))
        out = self.score()
        self.assertEqual(out["decision"]["action"], "stop")
        self.assertIn("paused", out["decision"]["reason"])

    def test_cap_reached(self):
        self.ledger({"id": "a", "type": "low-ctr", "pages": ["/addizionali/"], "state": "open", "pr": "https://github.com/x/y/pull/1"},
                    {"id": "b", "type": "decay", "pages": ["/ral/30000/"], "state": "open", "pr": "https://github.com/x/y/pull/2"})
        out = self.score()
        self.assertEqual(out["decision"]["action"], "stop")
        self.assertIn("cap reached: 2 open", out["decision"]["reason"])
        self.assertEqual(out["candidates"], [], "a stop leaves nothing to pick")


class OpenPrsFromGitHub(Case):
    def gh(self, *prs, ok=True):
        (self.run / "open_prs.json").write_text(json.dumps({"ok": ok, "prs": list(prs)}))

    def test_cap_counts_github_not_the_ledger(self):
        self.gh({"number": 11, "url": "https://github.com/x/y/pull/11", "title": "seo-growth: a", "body": ""},
                {"number": 12, "url": "https://github.com/x/y/pull/12", "title": "seo-growth: b", "body": ""})
        out = self.score()
        self.assertEqual(out["decision"]["action"], "stop")
        self.assertIn("cap reached: 2 open", out["decision"]["reason"])

    def test_ledger_open_entry_closed_on_github_does_not_count(self):
        self.ledger({"id": "a", "type": "low-ctr", "pages": ["/addizionali/"], "state": "open", "opened_on": "2026-08-01", "pr": "https://github.com/x/y/pull/1"},
                    {"id": "b", "type": "decay", "pages": ["/ral/30000/"], "state": "open", "opened_on": "2026-08-01", "pr": "https://github.com/x/y/pull/2"})
        self.gh()
        out = self.score()
        self.assertNotEqual(out["decision"]["action"], "stop", out["decision"])

    def test_untracked_open_pr_blocks_its_page(self):
        self.gh({"number": 9, "url": "https://github.com/x/y/pull/9", "title": "Title for /tredicesima/", "body": "Intent: low-ctr"})
        out = self.score()
        self.assertTrue(any("open PR on /tredicesima/" in r for r in self.dropped(out, "low-ctr:/tredicesima/")))

    def test_gh_unavailable_stops(self):
        self.gh(ok=False)
        out = self.score()
        self.assertEqual(out["decision"]["action"], "stop")
        self.assertIn("gh pr list failed", out["decision"]["reason"])


class Guardrails(Case):
    def test_page_in_cool_down(self):
        self.ledger({"id": "2026-10-10-1", "type": "internal-links", "pages": ["/tredicesima/"], "state": "merged",
                     "opened_on": "2026-10-05", "merged_on": "2026-10-10"})
        out = self.score()
        self.assertNotIn("low-ctr:/tredicesima/", self.ids(out))
        self.assertTrue(any("cool-down on /tredicesima/ until 2026-11-07" in r for r in self.dropped(out, "low-ctr:/tredicesima/")))

    def test_open_pr_on_page(self):
        self.ledger({"id": "x", "type": "schema-fix", "pages": ["/tredicesima/"], "state": "open", "pr": "https://github.com/x/y/pull/9"})
        out = self.score()
        self.assertTrue(any("open PR" in r for r in self.dropped(out, "low-ctr:/tredicesima/")))

    def test_closed_pr_proposed_again_within_90_days(self):
        self.ledger({"id": "2026-08-20-1", "type": "low-ctr", "pages": ["/tredicesima/"], "state": "closed",
                     "opened_on": "2026-08-18", "closed_on": "2026-08-20", "pr": "https://github.com/x/y/pull/7"})
        out = self.score()
        self.assertNotIn("low-ctr:/tredicesima/", self.ids(out))
        self.assertTrue(any("owner closed the same proposal on 2026-08-20" in r for r in self.dropped(out, "low-ctr:/tredicesima/")))
        later = self.score(today="2026-11-20")
        self.assertIn("low-ctr:/tredicesima/", [c["id"] for c in later["candidates"] + later["below_floor"]])

    def test_regressed_change_is_never_repeated(self):
        self.ledger({"id": "2026-06-01-1", "type": "low-ctr", "pages": ["/tredicesima/"], "state": "merged",
                     "merged_on": "2026-06-01", "verdict": "regressed", "verdict_on": "2026-07-05", "pattern": "brand-dropped"})
        out = self.score()
        self.assertTrue(any("don't repeat" in r for r in self.dropped(out, "low-ctr:/tredicesima/")))
        self.assertIn("low-ctr:brand-dropped", out["avoid"])


class Seasonal(Case):
    ENTRY = {"id": "it-test-peak", "site": "fiscometro", "title": "Test peak", "peak": "12-01",
             "queries": ["forfettario"], "source_url": "https://www.agenziaentrate.gov.it/x"}

    def test_calendar_unread_by_owner_gives_nothing(self):
        env = self.data_dir(lambda c: c.update(owner_reviewed_on=None))
        out = self.score(env=env)
        self.assertFalse([c for c in out["candidates"] if c["type"] in ("seasonal", "new-guide")])
        self.assertTrue(any("not read by the owner" in n for n in out["notes"]))

    def test_number_without_official_source(self):
        env = self.data_dir(lambda c: (c.update(owner_reviewed_on="2026-10-01"),
                                       c["entries"].append({**self.ENTRY, "status": "unverified", "checked_for_year": None})))
        out = self.score(env=env)
        self.assertFalse([c for c in out["candidates"] if c["id"].startswith("seasonal:")])
        self.assertTrue(any("no official source" in r for r in self.dropped(out, "seasonal:it-test-peak")))

    def test_checked_entry_in_lead_window(self):
        env = self.data_dir(lambda c: (c.update(owner_reviewed_on="2026-10-01"),
                                       c["entries"].append({**self.ENTRY, "status": "checked", "checked_for_year": 2026})))
        out = self.score(env=env)
        c = next(c for c in out["candidates"] if c["id"].startswith("seasonal:"))
        self.assertEqual(c["evidence"]["peak"], "2026-12-01")
        self.assertEqual(c["page"], "/guide/forfettario-2027/")
        self.assertEqual(c["evidence"]["source_url"], "https://www.agenziaentrate.gov.it/x")

    def test_page_comes_from_the_query_with_the_impressions(self):
        # the first matching query has no topPage; the biggest one does: its page is the target
        self.edit("queries.json", lambda d: d["rows"].insert(0, {"query": "forfettario regime", "type": "guide", "topPage": None,
                                                                 "pages": 0, "clicks": 0, "impressions": 30, "ctr": 0,
                                                                 "position": 40, "previous": None}))
        env = self.data_dir(lambda c: (c.update(owner_reviewed_on="2026-10-01"),
                                       c["entries"].append({**self.ENTRY, "status": "checked", "checked_for_year": 2026})))
        out = self.score(env=env)
        c = next(c for c in out["candidates"] + out["below_floor"] if c["id"].startswith(("seasonal:", "new-guide:")))
        self.assertEqual(c["type"], "seasonal")
        self.assertEqual(c["page"], "/guide/forfettario-2027/")

    def test_last_years_check_does_not_cover_this_year(self):
        env = self.data_dir(lambda c: (c.update(owner_reviewed_on="2026-10-01"),
                                       c["entries"].append({**self.ENTRY, "status": "checked", "checked_for_year": 2025})))
        out = self.score(env=env)
        self.assertTrue(any("checked for 2026" in r for r in self.dropped(out, "seasonal:it-test-peak")))


class Freeze(Case):
    MERGED = {"id": "2026-09-01-1", "type": "low-ctr", "pages": ["/addizionali/"], "state": "merged", "merged_on": "2026-09-01",
              "evaluate_on": "2026-09-29", "baseline28": {"clicks": 30}}

    def test_rollout_running_freezes_verdicts_and_decay(self):
        self.edit("rollouts.json", lambda r: r["rollouts"].insert(0, {"name": "October 2026 core update", "kind": "core", "start": "2026-10-14", "end": None}))
        self.ledger(self.MERGED)
        out = self.score()
        self.assertTrue(out["freeze"]["active"])
        ev = out["evaluations"][0]
        self.assertEqual(ev["status"], "confounded")
        self.assertIn(ev["by"], ("October 2026 core update", "September 2026 spam update"))
        self.assertNotIn("decay:/guide/naspi-2027-importi/", self.ids(out))
        self.assertTrue(any("rollout running" in r for r in self.dropped(out, "decay:")))

    def test_finished_rollout_still_settling_confounds(self):
        self.ledger(self.MERGED)
        out = self.score()  # September spam update ended 2026-10-08, settles 2026-11-05
        self.assertEqual(out["evaluations"][0]["status"], "confounded")
        self.assertEqual(out["evaluations"][0]["judge_after"], "2026-11-05")

    def test_unreadable_status_page_fails_closed(self):
        (self.run / "rollouts.json").write_text(json.dumps({"parsed": False, "rollouts": []}))
        self.ledger(self.MERGED)
        out = self.score()
        self.assertTrue(out["freeze"]["active"])
        self.assertEqual(out["evaluations"][0]["status"], "confounded")

    def test_clean_window_gives_a_verdict(self):
        self.edit("rollouts.json", lambda r: r.update(rollouts=[]))
        self.ledger({**self.MERGED, "merged_on": "2026-09-15", "evaluate_on": "2026-10-13"})
        self.edit("pages.json", lambda p: p["current"].update({"from": "2026-09-20"}))
        out = self.score()
        ev = out["evaluations"][0]
        self.assertEqual(ev["status"], "ready")
        self.assertIn(ev["proposed_verdict"], ("keep", "inconclusive", "revert-proposal"))
        self.assertEqual(ev["clicks_after"], 40)


class Panel(Case):
    def write_runs(self, n, cited=False):
        (self.state / "panel").mkdir()
        for i in range(n):
            (self.state / "panel" / f"2026-10-{10 + 2 * i:02d}.json").write_text(json.dumps({"results": [
                {"id": "fm-naspi", "cited": cited, "competitors": ["inps.it", "money.it"]}]}))

    def test_three_runs_that_agree(self):
        self.write_runs(3)
        out = self.score()
        ids = [c["id"] for c in out["candidates"]] + out["also_eligible"]
        self.assertIn("ai-citation:/guide/naspi-2027-importi/", ids)

    def test_two_runs_are_not_enough(self):
        self.write_runs(2)
        out = self.score()
        self.assertFalse([c for c in out["candidates"] + out["below_floor"] if c["type"] == "ai-citation"])
        self.assertTrue(any("2/3 runs" in n for n in out["notes"]))


class Sources(Case):
    def test_rss_injection_stays_data(self):
        (self.run / "feeds").mkdir(exist_ok=True)
        shutil.copy(FIX / "feeds" / "ade-news.xml", self.run / "feeds" / "ade-news.xml")
        p = py("sources.py", self.run)
        self.assertEqual(p.returncode, 0, p.stderr)
        news = json.loads((self.run / "news.json").read_text())["items"]
        self.assertEqual([n["official"] for n in news], [True, False])
        self.assertLessEqual(len(news[0]["summary"]), 300)
        out = self.score()
        c = next(c for c in out["candidates"] if c["type"] == "news-freshness")
        self.assertEqual(c["page"], "/guide/forfettario-2027/")
        self.assertIn("data", c["evidence"]["untrusted"])
        self.assertNotIn("blog.example.com", json.dumps(out))
        self.assertEqual(out["decision"]["action"], "candidates")

    def test_google_status_parse(self):
        shutil.copy(FIX / "google-status.html", self.run / "google-status.html")
        self.assertEqual(py("sources.py", self.run).returncode, 0)
        r = json.loads((self.run / "rollouts.json").read_text())
        self.assertTrue(r["parsed"])
        by = {x["name"]: x for x in r["rollouts"]}
        self.assertIsNone(by["November 2026 core update"]["end"])
        self.assertEqual(by["September 2026 spam update"]["end"], "2026-10-08")
        self.assertEqual(by["February 2026 Discover update"]["kind"], "other")

    def test_missing_status_page_is_unparsed(self):
        self.assertEqual(py("sources.py", self.run).returncode, 0)
        self.assertFalse(json.loads((self.run / "rollouts.json").read_text())["parsed"])


class SchemaLint(Case):
    PAGE = ('<html><body><script type="application/ld+json">{"@type":"WebApplication","name":"X","url":"https://a/",'
            '"applicationCategory":"FinanceApplication","isAccessibleForFree":true,"dateModified":"%s"}</script>'
            '<p>Verificato il <time>18/11/2026</time></p></body></html>')

    def lint(self, html):
        d = self.tmp / "dist" / "tool"
        d.mkdir(parents=True)
        (d / "index.html").write_text(html)
        p = py("schema_lint.py", self.tmp / "dist", "--out", self.tmp / "s.json")
        return p, json.loads((self.tmp / "s.json").read_text())

    def test_consistent_page_passes(self):
        p, out = self.lint(self.PAGE % "2026-11-18")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(out["errors"], 0)

    def test_date_mismatch(self):
        p, out = self.lint(self.PAGE % "2026-11-16")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(out["pages"][0]["path"], "/tool/")
        self.assertEqual(out["pages"][0]["issues"][0]["code"], "date-mismatch")

    def test_incomplete_webapp_and_faq_info(self):
        html = ('<script type="application/ld+json">[{"@type":"WebApplication","name":"X"},'
                '{"@type":"FAQPage","mainEntity":[]}]</script>')
        p, out = self.lint(html)
        codes = {i["code"]: i["severity"] for i in out["pages"][0]["issues"]}
        self.assertEqual(codes["webapp-incomplete"], "error")
        self.assertEqual(codes["faq-howto"], "info")


    def test_nested_references_are_not_the_page_app(self):
        html = ('<script type="application/ld+json">{"@type":"CollectionPage","name":"Partita IVA",'
                '"hasPart":[{"@type":"WebApplication","name":"Forfettario","url":"https://a/f/"}]}</script>')
        p, out = self.lint(html)
        self.assertEqual(p.returncode, 0, p.stdout)


class Ledger(Case):
    def test_add_set_due(self):
        add = py("ledger.py", "add", "--project", "fiscometro", "--type", "low-ctr", "--page", "/tredicesima/",
                 "--pr", "https://github.com/x/y/pull/3", "--baseline", '{"clicks": 120}', "--today", "2026-09-01", env=self.env)
        self.assertEqual(add.returncode, 0, add.stderr)
        eid = add.stdout.strip()
        self.assertEqual(eid, "2026-09-01-1")
        st = py("ledger.py", "set", "--project", "fiscometro", "--id", eid, "state=merged", "merged_on=2026-09-02", env=self.env)
        self.assertEqual(st.returncode, 0, st.stderr)
        self.assertIn('"evaluate_on": "2026-09-30"', st.stdout)
        due = json.loads(py("ledger.py", "due", "--project", "fiscometro", "--today", "2026-10-01", env=self.env).stdout)
        self.assertEqual([e["id"] for e in due], [eid])
        bad = py("ledger.py", "set", "--project", "fiscometro", "--id", eid, "verdict=great", env=self.env)
        self.assertNotEqual(bad.returncode, 0)
        lines = (self.state / "ledger.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2, "append-only: one line per event")


FAKE_TOKEN = "fAkE-T0KEN.for-tests-ONLY_9f8e7d"

STUB_CURL = r"""#!/usr/bin/env python3
import hashlib, json, os, sys
a = sys.argv[1:]
log = os.environ["STUB_LOG"]
with open(log, "a") as f:
    f.write(json.dumps(a) + "\n")
hdr = next(a[i + 1][1:] for i, x in enumerate(a) if x == "-H" and a[i + 1].startswith("@"))
ok = hashlib.sha256(open(hdr).read().strip().encode()).hexdigest() == os.environ["STUB_EXPECT_SHA"]
out = a[a.index("-o") + 1]
code = os.environ.get("STUB_CODE", "200") if ok else "401"
open(out, "w").write(json.dumps({"status": "ok", "site": "https://fiscometro.it", "autopilot": {"enabled": True}}))
sys.stdout.write(code)
"""


class TokenStubs(Case):
    """pull.sh / report.sh with a stubbed `security` and `curl` on PATH: no Keychain, no network."""

    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.tmpdir = self.tmp / "t"
        self.tmpdir.mkdir()
        self.log = self.tmp / "curl.log"
        self.stub("security", f'#!/bin/sh\n[ "$1" = find-generic-password ] && [ "$3" = seo-growth-analyst ] || exit 44\n'
                              f'${{STUB_SLEEP:+sleep $STUB_SLEEP}}\necho "{FAKE_TOKEN}"\n')
        self.stub("curl", STUB_CURL.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        self.env = {**self.env, "PATH": f"{self.bin}:{os.environ['PATH']}", "TMPDIR": str(self.tmpdir),
                    "STUB_LOG": str(self.log),
                    "STUB_EXPECT_SHA": hashlib.sha256(f"Authorization: Bearer {FAKE_TOKEN}".encode()).hexdigest()}

    def stub(self, name, text):
        f = self.bin / name
        f.write_text(text)
        f.chmod(0o755)

    def sh(self, *argv, env=None):
        return subprocess.run(list(argv), capture_output=True, text=True, env=env or self.env, timeout=60)

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_bash_x_check_prints_ok_and_never_the_token(self):
        p = self.sh("bash", "-x", str(SCRIPTS / "pull.sh"), "fiscometro", "--check")
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertTrue(p.stdout.startswith("ok ok autopilot=true"), p.stdout)
        self.assertNotIn(FAKE_TOKEN, p.stdout + p.stderr)
        self.assertIn("+ ", p.stderr, "xtrace was on for the rest of the script")
        self.assertEqual(list(self.tmpdir.glob("seo-growth-auth.*")), [], "header file deleted on exit")
        self.assertTrue(all(FAKE_TOKEN not in " ".join(c) for c in self.calls()), "token not in curl argv")

    def test_sourced_load_token_leaves_no_readable_token(self):
        code = (f'HERE="{SCRIPTS}"; AGENT_DIR="{AGENT}"; . "$HERE/_token.sh"; load_token || exit 9; '
                'echo "T=${TOKEN:-}"; stat -f %Lp "$AUTH_FILE"; set; env; drop_token; echo "left=${AUTH_FILE:-none}"')
        p = self.sh("bash", "-x", "-c", code)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertIn("T=\n600\n", p.stdout)
        self.assertIn("left=none", p.stdout)
        self.assertNotIn(FAKE_TOKEN, p.stdout + p.stderr)
        self.assertEqual(list(self.tmpdir.glob("seo-growth-auth.*")), [])

    def test_header_dir_is_private_and_takes_no_output_path(self):
        p = self.sh(sys.executable, "-I", str(SCRIPTS / "keychain_header.py"), "seo-growth-analyst")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = Path(p.stdout.strip())
        self.assertNotIn(FAKE_TOKEN, p.stdout + p.stderr)
        self.assertEqual(out.parent.parent, self.tmpdir)
        self.assertTrue(out.parent.name.startswith("seo-growth-auth."))
        self.assertEqual(oct(out.parent.stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")
        shutil.rmtree(out.parent)
        existing = self.tmp / "existing"
        existing.write_text("keep\n")
        for target in ("/dev/stdout", "/dev/stderr", "-", str(existing)):
            q = self.sh(sys.executable, "-I", str(SCRIPTS / "keychain_header.py"), "seo-growth-analyst", target)
            self.assertEqual(q.returncode, 2, target)
            self.assertNotIn(FAKE_TOKEN, q.stdout + q.stderr, target)
        self.assertEqual(existing.read_text(), "keep\n")
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_load_token_sweeps_stale_headers(self):
        stale, fresh = self.tmpdir / "seo-growth-auth.stale1", self.tmpdir / "seo-growth-auth.fresh1"
        for d in (stale, fresh):
            d.mkdir(mode=0o700)
            (d / "header").write_text("Authorization: Bearer old\n")
        (self.tmpdir / "seo-growth-auth.oldfile").write_text("x")
        old = 1_700_000_000
        for f in (stale / "header", stale, self.tmpdir / "seo-growth-auth.oldfile"):
            os.utime(f, (old, old))
        code = f'HERE="{SCRIPTS}"; AGENT_DIR="{AGENT}"; . "$HERE/_token.sh"; load_token || exit 9; drop_token'
        p = self.sh("bash", "-c", code)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(sorted(x.name for x in self.tmpdir.iterdir()), ["seo-growth-auth.fresh1"],
                         "stale headers swept, a live run's header (under an hour old) kept")

    def test_missing_token_fails_cleanly(self):
        self.stub("security", "#!/bin/sh\nexit 44\n")
        p = self.sh("bash", str(SCRIPTS / "pull.sh"), "fiscometro", "--check")
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        self.assertIn("token missing", p.stderr)
        self.assertIn("security add-generic-password -U -s seo-growth-analyst", p.stderr)
        self.assertEqual(self.calls(), [], "no API call without a token")
        self.assertFalse(list((self.tmp / "state").rglob("summary.json")), "nothing pulled without a token")

    def test_item_name_cannot_be_overridden(self):
        p = self.sh("bash", str(SCRIPTS / "pull.sh"), "fiscometro", "--check",
                    env={**self.env, "SEO_GROWTH_KEYCHAIN_ITEM": "something-else"})
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_locked_keychain_times_out_with_one_line(self):
        env = {**self.env, "STUB_SLEEP": "10", "SEO_GROWTH_KEYCHAIN_TIMEOUT": "1"}
        p = self.sh("bash", str(SCRIPTS / "pull.sh"), "fiscometro", "--check", env=env)
        self.assertEqual(p.returncode, 3)
        self.assertEqual(len(p.stderr.strip().splitlines()), 1, p.stderr)
        self.assertIn("timed out after 1s", p.stderr)
        self.assertEqual(self.calls(), [])

    def test_401_check_stops_with_exit_5(self):
        p = self.sh("bash", str(SCRIPTS / "pull.sh"), "nettoswiss", "--check", env={**self.env, "STUB_CODE": "401"})
        self.assertEqual(p.returncode, 5, p.stderr)
        self.assertIn("not connected yet: https://nettoswiss.ch answers 401", p.stderr)

    def test_401_is_not_connected_yet(self):
        sh = f'. "{SCRIPTS}/_token.sh"; ORIGIN=https://nettoswiss.ch; explain_status 401 /admin/api/summary; echo "rc=$?"'
        p = subprocess.run(["bash", "-c", sh], capture_output=True, text=True)
        self.assertIn("rc=5", p.stdout)
        self.assertIn("not connected yet: https://nettoswiss.ch answers 401", p.stderr)
        other = subprocess.run(["bash", "-c", sh.replace("401", "500")], capture_output=True, text=True)
        self.assertIn("rc=4", other.stdout)

    def test_report_post_is_never_retried(self):
        body = self.tmp / "report.json"
        body.write_text(json.dumps({"runId": "r", "mode": "pulse", "status": "ok", "summary": "s"}))
        p = self.sh("bash", str(SCRIPTS / "report.sh"), "fiscometro", str(body))
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("POST", calls[0])
        self.assertNotIn("--retry", calls[0])
        self.assertNotIn(FAKE_TOKEN, p.stdout + p.stderr)

    def test_unknown_project(self):
        p = self.sh("bash", str(SCRIPTS / "pull.sh"), "nope", "--check")
        self.assertEqual(p.returncode, 2)
        self.assertIn("unknown project", p.stderr)


class Ship(Case):
    """ship.sh on a throwaway repo with a bare origin and a stubbed gh: the gate's exit status decides."""

    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.gh_log = self.tmp / "gh.log"
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$*" >> "{self.gh_log}"\n'
                      'case "$1 $2" in "pr list") echo "${STUB_OPEN:-0}" ;; "pr create") echo https://github.com/x/y/pull/77 ;; esac\n')
        gh.chmod(0o755)
        origin, self.wt = self.tmp / "origin.git", self.tmp / "wt"
        git = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
        git("init", "--bare", "-b", "main", str(origin))
        git("init", "-b", "main", str(self.wt))
        for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            git("config", k, v, cwd=self.wt)
        (self.wt / "page.md").write_text("x\n")
        git("add", ".", cwd=self.wt)
        git("commit", "-m", "base", cwd=self.wt)
        git("remote", "add", "origin", str(origin), cwd=self.wt)
        git("push", "-u", "origin", "main", cwd=self.wt)
        git("checkout", "-b", "seo-growth/test", cwd=self.wt)
        (self.wt / "page.md").write_text("y\n")
        git("commit", "-am", "change", cwd=self.wt)
        self.origin = origin
        self.body = self.tmp / "body.md"
        self.body.write_text("Intent: low-ctr:/x/\n")

    def ship(self, gate, **extra):
        data = self.tmp / "data"
        if not data.exists():
            shutil.copytree(AGENT / "data", data)
        sites = json.loads((data / "sites.json").read_text())
        sites["fiscometro"]["gate"] = gate
        (data / "sites.json").write_text(json.dumps(sites))
        env = {**self.env, "PATH": f"{self.bin}:{os.environ['PATH']}", "SEO_GROWTH_DATA": str(data), **extra}
        return subprocess.run(["bash", str(SCRIPTS / "ship.sh"), "fiscometro", str(self.wt), "seo-growth: test", str(self.body)],
                              capture_output=True, text=True, env=env, timeout=60)

    def remote_has_branch(self):
        p = subprocess.run(["git", "--git-dir", str(self.origin), "branch", "--list", "seo-growth/test"], capture_output=True, text=True)
        return bool(p.stdout.strip())

    def gh_calls(self):
        return self.gh_log.read_text() if self.gh_log.exists() else ""

    def test_failing_gate_stops_the_pr(self):
        p = self.ship("echo 'lint: 3 errors'; exit 3")
        self.assertEqual(p.returncode, 6, p.stdout + p.stderr)
        self.assertIn("gate failed (exit 3): no PR opened", p.stderr)
        self.assertIn("lint: 3 errors", p.stdout)
        self.assertNotIn("pr create", self.gh_calls())
        self.assertFalse(self.remote_has_branch(), "nothing pushed when the gate fails")

    def test_site_gates_cannot_hide_a_failure(self):
        # a `cmd; cleanup` or `cmd || true` gate would exit 0 after a failure: each gate is one plain command
        for name, site in json.loads((AGENT / "data" / "sites.json").read_text()).items():
            if not name.startswith("_"):
                self.assertRegex(site["gate"], r"^pnpm [\w:-]+$", name)

    def test_passing_gate_opens_a_labelled_pr(self):
        p = self.ship("echo all green")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(p.stdout.strip().endswith("https://github.com/x/y/pull/77"))
        create = [l for l in self.gh_calls().splitlines() if l.startswith("pr create")]
        self.assertEqual(len(create), 1)
        self.assertIn("--label seo-growth", create[0])
        self.assertTrue(self.remote_has_branch())

    def test_cap_reached_on_github(self):
        p = self.ship("true", STUB_OPEN="2")
        self.assertEqual(p.returncode, 7, p.stderr)
        self.assertFalse(self.remote_has_branch())

    def test_untracked_file_the_gate_relies_on_refuses(self):
        # the gate passes only thanks to a file the commit does not carry: shipping it would claim a pass
        # for content that differs from what is pushed
        (self.wt / "fix.md").write_text("never committed\n")
        p = self.ship("test -f fix.md")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("uncommitted or untracked changes", p.stderr)
        self.assertIn("fix.md", p.stderr)
        self.assertNotIn("gate:", p.stdout, "the gate never runs on a dirty tree")
        self.assertNotIn("pr create", self.gh_calls())
        self.assertFalse(self.remote_has_branch())
        # ignored files (node_modules, build output) do not count
        (self.wt / "fix.md").unlink()
        (self.wt / ".git" / "info" / "exclude").write_text("dist/\n")
        (self.wt / "dist").mkdir()
        (self.wt / "dist" / "out.js").write_text("x\n")
        self.assertEqual(self.ship("true").returncode, 0)

    def test_gate_that_edits_a_tracked_file_refuses(self):
        p = self.ship("echo formatted > page.md")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("tracked files changed while the gate ran", p.stderr)
        self.assertFalse(self.remote_has_branch())

    def test_body_file_inside_the_repo_refuses(self):
        # a body written in the worktree would dirty the tree or be committed: refuse it by path, clearly
        for rel in ("pr-body.md", "sub/pr-body.md"):
            inside = self.wt / rel
            inside.parent.mkdir(exist_ok=True)
            inside.write_text("Intent: x\n")
            self.body = inside
            p = self.ship("true")
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn("is inside the repo", p.stderr)
            self.assertNotIn("gate:", p.stdout)
            self.assertFalse(self.remote_has_branch())
            inside.unlink()
        # the same body outside the repo ships
        self.body = self.tmp / "body.md"
        self.assertEqual(self.ship("true").returncode, 0)

    def test_prompt_handles_every_ship_exit_code(self):
        # the unattended agent must know where the body goes and what to do on each refusal
        prompt = (AGENT / "config.yaml").read_text()
        self.assertIn("OUTSIDE WORKTREE", prompt)
        self.assertIn("mktemp", prompt)
        codes = set(re.findall(r"\bexit ([1-9])\b", (SCRIPTS / "ship.sh").read_text()))
        self.assertEqual(codes, {"2", "6", "7", "8"})
        for code in sorted(codes):
            self.assertRegex(prompt, rf"\b{code} \(", f"ship.sh exit {code} has no instruction in the prompt")

    def test_refuses_the_default_branch_and_dirty_trees(self):
        (self.wt / "page.md").write_text("dirty\n")
        self.assertEqual(self.ship("true").returncode, 2)
        subprocess.run(["git", "checkout", "-f", "main"], cwd=self.wt, check=True, capture_output=True)
        p = self.ship("true")
        self.assertEqual(p.returncode, 2)
        self.assertIn("refusing to ship from 'main'", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
