#!/usr/bin/env python3
"""seo-growth's deterministic half: score.py's guardrails, the ledger, the sources parser, the schema lint
and pull.sh's missing-token path. Standard library only, no network, no Keychain secret read.

Each scenario starts from tests/fixtures/fiscometro-run (a pull shaped like the live admin API) and changes one
thing. The model-judged half (does Claude pick well, refuse an injected instruction, keep numbers sourced)
is in the eval cases outside the repo: ~/Documents/omnigent-research/evals/cases/seo-growth/.

Run: python3 omnigent/agents/seo-growth/tests/test_seo_growth.py
"""

import copy
import json
import os
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
        out = self.score()
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


class PullToken(Case):
    def test_missing_token_fails_cleanly(self):
        env = {**self.env, "SEO_GROWTH_KEYCHAIN_ITEM": "seo-growth-test-item-that-does-not-exist"}
        p = subprocess.run(["bash", str(SCRIPTS / "pull.sh"), "fiscometro", "--check"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        self.assertIn("token missing", p.stderr)
        self.assertIn("security add-generic-password -U -s seo-growth-test-item-that-does-not-exist", p.stderr)
        self.assertFalse(list((self.tmp / "state").rglob("summary.json")), "nothing pulled without a token")

    def test_401_is_not_connected_yet(self):
        sh = f'. "{SCRIPTS}/_token.sh"; ORIGIN=https://nettoswiss.ch; explain_status 401 /admin/api/summary; echo "rc=$?"'
        p = subprocess.run(["bash", "-c", sh], capture_output=True, text=True)
        self.assertIn("rc=5", p.stdout)
        self.assertIn("not connected yet: https://nettoswiss.ch answers 401", p.stderr)
        other = subprocess.run(["bash", "-c", sh.replace("401", "500")], capture_output=True, text=True)
        self.assertIn("rc=4", other.stdout)

    def test_unknown_project(self):
        p = subprocess.run(["bash", str(SCRIPTS / "pull.sh"), "nope", "--check"], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("unknown project", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
