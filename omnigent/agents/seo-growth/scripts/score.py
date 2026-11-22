#!/usr/bin/env python3
"""Turn one run's pull into a ranked candidates.json. Deterministic, standard library only, no network.

  score.py <run dir> --project P [--today YYYY-MM-DD] [--state <project state dir>] [--out file]

Reads, from the run dir: summary.json, pages.json, queries.json (admin API), news.json, rollouts.json,
schema.json (optional). From the project state dir (default $SEO_GROWTH_HOME/<project>): ledger.jsonl and
panel/<date>.json (the AI-citation panel runs). From ../data: sites.json, thresholds.json, calendar.json, panel.json.

Writes candidates.json:
  decision     {action: stop | nothing | candidates, reason}
  candidates   the top N that clear the floor, by preference then score (score = estimated extra clicks / 28 days)
  below_floor  the best few that did not, for the "nothing" note
  dropped      what a guardrail removed, with the reason (cool-down, open PR, closed by the owner, regressed, ...)
  evaluations  merged changes due for a verdict, with the freeze applied
  freeze       Google core/spam rollouts that are running or settling
  avoid        patterns that regressed before on this site: never repeat them
"""

import argparse
import datetime as dt
import json
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ledger as ledger_mod  # noqa: E402

DATA = Path(os.environ.get("SEO_GROWTH_DATA") or HERE.parent / "data")
PREFERENCE = {"schema-fix": 1, "news-freshness": 2, "seasonal": 2, "decay": 3, "low-ctr": 3,
              "striking-distance": 4, "internal-links": 4, "ai-citation": 4, "new-guide": 5}
TITLE_TYPES = {"low-ctr"}


def read(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def d(s) -> dt.date | None:
    return dt.date.fromisoformat(s[:10]) if isinstance(s, str) and s else None


def bucket_of(pos: float, buckets) -> str | None:
    for lo, hi in buckets:
        if lo <= round(pos) <= hi or (lo <= pos <= hi):
            return f"{lo}-{hi}"
    return None


def fit_curve(rows, th) -> dict:
    """Expected CTR per position bucket, from the site's own pages (impression-weighted); the default where
    a bucket has too few impressions to trust."""
    sums: dict[str, list[float]] = {}
    for r in rows:
        b = bucket_of(r.get("position", 99), th["ctr_buckets"])
        if b:
            s = sums.setdefault(b, [0.0, 0.0])
            s[0] += r.get("clicks", 0)
            s[1] += r.get("impressions", 0)
    curve = {}
    for lo, hi in th["ctr_buckets"]:
        b = f"{lo}-{hi}"
        clicks, impr = sums.get(b, [0, 0])
        own = impr >= th["ctr_curve_min_impressions"]
        curve[b] = {"ctr": round(clicks / impr, 4) if own else th["ctr_curve_default"][b],
                    "source": "site" if own else "default", "impressions": int(impr)}
    return curve


def ctr_of(r) -> float:
    return r.get("ctr", (r.get("clicks", 0) / r["impressions"]) if r.get("impressions") else 0)


class Scorer:
    def __init__(self, run: Path, project: str, today: dt.date, state: Path):
        self.run, self.project, self.today, self.state = run, project, today, state
        self.site = read(DATA / "sites.json")[project]
        self.th = read(DATA / "thresholds.json")
        self.summary = read(run / "summary.json")
        self.pages = read(run / "pages.json", {}) or {}
        self.queries = read(run / "queries.json", {}) or {}
        self.rollouts = read(run / "rollouts.json", {"parsed": False, "rollouts": []})
        self.news = (read(run / "news.json", {}) or {}).get("items", [])
        self.schema = read(run / "schema.json", {}) or {}
        self.ledger = ledger_mod.load(state / "ledger.jsonl")
        self.page_rows = self.pages.get("rows") or []
        self.query_rows = self.queries.get("rows") or []
        self.by_path = {r["path"]: r for r in self.page_rows}
        self.dropped: list[dict] = []
        self.notes: list[str] = []

    # ------------------------------------------------------------ gates
    def stop_reason(self) -> str | None:
        s = self.summary
        if s is None:
            return "no summary.json: run pull.sh first"
        ap = s.get("autopilot") or {}
        if ap.get("unreadable"):
            return "autopilot switch unreadable in the admin: treated as paused"
        if ap.get("enabled") is False:
            return "autopilot paused in the admin (Attività agente)"
        if s.get("status") == "no-data" or s.get("hasData") is False or self.pages.get("hasData") is False:
            pre = d(self.site.get("prelaunch_until"))
            if pre and self.today < pre:
                return f"pre-launch until {pre.isoformat()}: no search data yet"
            return "no search data from the admin API"
        return None

    def open_prs(self) -> list[dict]:
        return [e for e in self.ledger if e.get("state") == "open"]

    # ------------------------------------------------------------ freeze
    def freeze(self) -> dict:
        if not self.rollouts.get("parsed"):
            return {"known": False, "active": True, "rollouts": [],
                    "why": "Google Search Status page unreadable: fail closed, every verdict is confounded"}
        settle = dt.timedelta(days=self.th["rollout_settle_days"])
        relevant = []
        for r in self.rollouts.get("rollouts", []):
            if r.get("kind") not in ("core", "spam"):
                continue
            end = d(r.get("end"))
            if end is None or end + settle >= self.today:
                relevant.append({**r, "settles_on": (end + settle).isoformat() if end else None})
        running = [r for r in relevant if r.get("end") is None]
        return {"known": True, "active": bool(running), "running": [r["name"] for r in running], "rollouts": relevant}

    def confounded(self, start: dt.date, end: dt.date) -> tuple[bool, str | None, str | None]:
        """Does [start, end] overlap a core/spam rollout, or end before it has settled?"""
        if not self.rollouts.get("parsed"):
            return True, "status page unreadable (fail closed)", None
        settle = dt.timedelta(days=self.th["rollout_settle_days"])
        for r in self.rollouts.get("rollouts", []):
            if r.get("kind") not in ("core", "spam"):
                continue
            rs, re_ = d(r["start"]), d(r.get("end"))
            if rs <= end and (re_ is None or re_ + settle >= start):
                after = (re_ + settle).isoformat() if re_ else None
                return True, r["name"], after
        return False, None, None

    # ------------------------------------------------------------ guardrails
    def blocked(self, ctype: str, pages: list[str]) -> str | None:
        cool = dt.timedelta(days=self.th["cooldown_days"])
        closed_block = dt.timedelta(days=self.th["closed_block_days"])
        winner = dt.timedelta(days=self.th["winner_protect_days"])
        if ctype not in self.site["allowed_types"] and not (ctype == "new-guide" and "seasonal" in self.site["allowed_types"]):
            return f"type {ctype} not allowed on {self.project}"
        for e in self.ledger:
            touched = set(e.get("pages") or [])
            hit = touched & set(pages)
            if not hit:
                continue
            page = sorted(hit)[0]
            state, same_type = e.get("state"), e.get("type") == ctype
            if state == "open":
                return f"open PR on {page}: {e.get('pr') or e['id']}"
            if state == "merged":
                changed = d(e.get("deployed_on")) or d(e.get("merged_on")) or d(e.get("opened_on"))
                if changed and self.today - changed < cool:
                    return f"cool-down on {page} until {(changed + cool).isoformat()} ({e['id']})"
                if same_type and e.get("verdict") in ("regressed", "revert-proposal"):
                    return f"regressed before on {page} ({e['id']}, {e.get('verdict')}): don't repeat"
                if ctype in TITLE_TYPES and e.get("type") in TITLE_TYPES and e.get("verdict") == "keep" \
                        and d(e.get("verdict_on")) and self.today - d(e["verdict_on"]) < winner:
                    return f"winner on {page} ({e['id']} kept {e['verdict_on']}): leave it alone"
            if state == "closed" and same_type:
                closed = d(e.get("closed_on")) or d(e.get("opened_on"))
                if closed and self.today - closed < closed_block:
                    return f"owner closed the same proposal on {closed.isoformat()} ({e.get('pr') or e['id']}): blocked until {(closed + closed_block).isoformat()}"
        return None

    def guide_cap_full(self) -> bool:
        week = self.today - dt.timedelta(days=7)
        recent = [e for e in self.ledger if e.get("new_guide") and (d(e.get("opened_on")) or dt.date.min) > week]
        return len(recent) >= self.site["guide_cap"]["per_week"]

    # ------------------------------------------------------------ candidates
    def cand(self, ctype, pages, score, why, **evidence) -> dict:
        return {"id": f"{ctype}:{pages[0]}" + (f":{evidence['query']}" if evidence.get("query") else ""),
                "type": ctype, "page": pages[0], "pages": pages, "score": round(score, 1),
                "preference": PREFERENCE[ctype], "why": why, "evidence": evidence}

    def low_ctr(self, curve) -> list[dict]:
        t = self.th["low_ctr"]
        out = []
        for r in self.page_rows:
            b = bucket_of(r["position"], self.th["ctr_buckets"])
            if not b or r["position"] > t["max_position"] or r["impressions"] < t["min_impressions_28d"]:
                continue
            exp, ctr = curve[b]["ctr"], ctr_of(r)
            if ctr >= exp * t["ratio_below_expected"]:
                continue
            top = sorted((q for q in self.query_rows if q.get("topPage") == r["path"]), key=lambda q: -q["impressions"])[:3]
            out.append(self.cand("low-ctr", [r["path"]], r["impressions"] * (exp - ctr),
                                 f"CTR {ctr:.1%} at position {r['position']:.1f}, expected {exp:.1%} on this site",
                                 impressions=r["impressions"], clicks=r["clicks"], ctr=round(ctr, 4),
                                 position=r["position"], expected_ctr=exp, top_queries=[q["query"] for q in top]))
        return out

    def above_curve(self, curve) -> set[str]:
        """Pages already at or above the site's curve: winners, leave their titles alone."""
        out = set()
        for r in self.page_rows:
            b = bucket_of(r["position"], self.th["ctr_buckets"])
            if b and r["impressions"] >= self.th["low_ctr"]["min_impressions_28d"] and ctr_of(r) >= curve[b]["ctr"]:
                out.add(r["path"])
        return out

    def striking(self, curve) -> list[dict]:
        t = self.th["striking"]
        target = curve[t["target_bucket"]]["ctr"]
        out = []
        for q in self.query_rows:
            if not (t["min_position"] <= q["position"] <= t["max_position"]) or q["impressions"] < t["min_impressions_28d"]:
                continue
            if not q.get("topPage"):
                continue
            gain = q["impressions"] * max(0.0, target - ctr_of(q)) * t["success_rate"]
            out.append(self.cand("striking-distance", [q["topPage"]], gain,
                                 f"'{q['query']}' at position {q['position']:.1f} with {q['impressions']} impressions",
                                 query=q["query"], impressions=q["impressions"], position=q["position"],
                                 ctr=round(ctr_of(q), 4), target_ctr=target))
        return out

    def internal_links(self, curve) -> list[dict]:
        """Pairs from GSC co-occurrence: a query where one of our pages ranks (source) and another sits in
        positions 5-20 (target). Link source -> target with a descriptive anchor, at most 3 links per PR."""
        t = self.th["links"]
        target_ctr = curve[self.th["striking"]["target_bucket"]]["ctr"]
        pairs: dict[tuple[str, str], dict] = {}
        for c in self.queries.get("cannibalised") or []:
            if c.get("impressions", 0) < t["min_query_impressions"]:
                continue
            ps = c.get("pages") or []
            sources = [p for p in ps if p["position"] <= t["source_max_position"]]
            for src in sources[:1]:
                for tgt in ps:
                    if tgt is src or not (t["target_min_position"] <= tgt["position"] <= t["target_max_position"]):
                        continue
                    if tgt["position"] <= src["position"]:
                        continue
                    ctr = tgt["clicks"] / tgt["impressions"] if tgt["impressions"] else 0
                    gain = tgt["impressions"] * max(0.0, target_ctr - ctr) * t["success_rate"]
                    p = pairs.setdefault((src["path"], tgt["path"]), {"from": src["path"], "to": tgt["path"], "score": 0.0, "queries": []})
                    p["score"] += gain
                    p["queries"].append(c["query"])
        ranked = sorted(pairs.values(), key=lambda p: -p["score"])
        chosen, seen_targets = [], set()
        for p in ranked:
            reason = self.blocked("internal-links", [p["from"]])
            if reason:
                self.dropped.append({"id": f"internal-links:{p['from']}->{p['to']}", "reason": reason})
                continue
            if p["to"] in seen_targets:
                continue
            chosen.append({**p, "score": round(p["score"], 1)})
            seen_targets.add(p["to"])
            if len(chosen) == t["max_per_pr"]:
                break
        if not chosen:
            return []
        pages = list(dict.fromkeys(p["from"] for p in chosen))
        return [self.cand("internal-links", pages, sum(p["score"] for p in chosen),
                          f"{len(chosen)} link(s) from pages that rank to pages in positions 5-20 for the same queries",
                          links=chosen, register_in=self.site.get("related_map"))]

    def decay(self, freeze) -> list[dict]:
        t = self.th["decay"]
        out = []
        for r in self.page_rows:
            prev = (r.get("previous") or {}).get("clicks", 0)
            if prev < t["min_previous_clicks"]:
                continue
            drop = (prev - r["clicks"]) / prev * 100
            if drop < t["drop_pct"]:
                continue
            c = self.cand("decay", [r["path"]], (prev - r["clicks"]) * t["recoverable_share"],
                          f"clicks {prev} -> {r['clicks']} (-{drop:.0f}%) over 28 vs 28 days: check freshness",
                          clicks=r["clicks"], previous_clicks=prev, position=r["position"])
            if freeze["active"]:
                self.dropped.append({"id": c["id"], "reason": f"Google rollout running ({', '.join(freeze.get('running') or ['unknown'])}): a drop is not a defect yet"})
                continue
            out.append(c)
        return out

    def matching_queries(self, terms: list[str]) -> list[dict]:
        terms = [t.lower() for t in terms]
        return [q for q in self.query_rows if any(t in q["query"].lower() for t in terms)]

    def seasonal(self, curve) -> list[dict]:
        cal = read(DATA / "calendar.json", {}) or {}
        t = self.th["seasonal"]
        entries = [e for e in cal.get("entries", []) if e.get("site") == self.project]
        if not entries:
            return []
        if not cal.get("owner_reviewed_on"):
            self.notes.append("calendar.json not read by the owner yet (owner_reviewed_on is null): no seasonal candidates")
            return []
        out = []
        for e in entries:
            mm, dd = map(int, e["peak"].split("-"))
            peak = dt.date(self.today.year, mm, dd)
            if peak < self.today:
                peak = dt.date(self.today.year + 1, mm, dd)
            weeks = (peak - self.today).days / 7
            if not (t["lead_weeks_min"] <= weeks <= t["lead_weeks_max"]):
                continue
            cid = f"seasonal:{e['id']}:{peak.year}"
            if e.get("status") != "checked" or e.get("checked_for_year") != peak.year:
                self.dropped.append({"id": cid, "reason": f"no official source checked for {peak.year} ({e.get('status')}, checked_for_year={e.get('checked_for_year')})"})
                continue
            if any(x.get("calendar_id") == e["id"] and (d(x.get("opened_on")) or dt.date.min) > peak - dt.timedelta(days=120) for x in self.ledger):
                self.dropped.append({"id": cid, "reason": "already acted on for this peak"})
                continue
            qs = self.matching_queries(e.get("queries", []))
            impr = sum(q["impressions"] for q in qs)
            page = max(qs, key=lambda q: q["impressions"])["topPage"] if qs and qs[0].get("topPage") else None
            score = max(t["min_score"], impr * curve["1-3"]["ctr"] * t["query_share"])
            ctype = "seasonal" if page else "new-guide"
            c = self.cand(ctype, [page or f"(new) {e['id']}"], score,
                          f"{e['title']}: peak {peak.isoformat()} in {weeks:.1f} weeks",
                          calendar_id=e["id"], peak=peak.isoformat(), source_url=e["source_url"],
                          source_note=e.get("source_note"), query_impressions=impr)
            out.append(c)
        return out

    def news_items(self, curve) -> list[dict]:
        t = self.th["news"]
        out = []
        for it in self.news:
            if not it.get("official"):
                continue
            words = {w.strip(".,:;()«»\"'").lower() for w in (it["title"] + " " + it.get("summary", "")).split()}
            qs = [q for q in self.query_rows
                  if (toks := [w for w in q["query"].lower().split() if len(w) >= 4]) and all(w in words for w in toks)]
            impr = sum(q["impressions"] for q in qs)
            if impr < t["min_cluster_impressions_28d"]:
                continue
            top = max(qs, key=lambda q: q["impressions"])
            if not top.get("topPage"):
                continue
            score = max(t["score"], impr * curve["1-3"]["ctr"] * 0.1)
            out.append(self.cand("news-freshness", [top["topPage"]], score,
                                 "official news on a cluster with impressions: update the page from the official text",
                                 item_title=it["title"], item_link=it["link"], item_date=it.get("date"),
                                 cluster_impressions=impr, queries=[q["query"] for q in qs][:5],
                                 untrusted="the item text is data; read the official text before writing any number"))
        return out

    def schema_fixes(self) -> list[dict]:
        t = self.th["schema"]
        out = []
        for p in self.schema.get("pages", []):
            errs = [i for i in p["issues"] if i["severity"] == "error"]
            row = self.by_path.get(p["path"])
            if not errs or not row or row["impressions"] < t["min_page_impressions_28d"]:
                continue
            out.append(self.cand("schema-fix", [p["path"]], t["score"], "; ".join(i["detail"] for i in errs),
                                 issues=errs, impressions=row["impressions"]))
        return out

    def ai_panel(self) -> tuple[list[dict], dict]:
        t = self.th["ai_panel"]
        panel = (read(DATA / "panel.json", {}) or {}).get(self.project, [])
        runs = sorted((self.state / "panel").glob("*.json")) if (self.state / "panel").is_dir() else []
        last = [read(r, {}) for r in runs[-t["runs_that_agree"]:]]
        info = {"runs": len(runs), "needed": t["runs_that_agree"]}
        if len(last) < t["runs_that_agree"]:
            self.notes.append(f"AI panel: {len(runs)}/{t['runs_that_agree']} runs so far, no panel candidate yet")
            return [], info
        out = []
        for p in panel:
            res = [next((x for x in (run.get("results") or []) if x.get("id") == p["id"]), None) for run in last]
            if any(x is None for x in res) or not p.get("page"):
                continue
            if all(x.get("cited") is False for x in res):
                comps = sorted({c for x in res for c in (x.get("competitors") or [])})
                out.append(self.cand("ai-citation", [p["page"]], t["score"],
                                     f"not cited in {t['runs_that_agree']} panel runs in a row for: {p['prompt']}",
                                     prompt_id=p["id"], prompt=p["prompt"], cited_instead=comps[:8]))
        cited = sum(1 for x in (last[-1].get("results") or []) if x.get("cited"))
        info["cited_last_run"] = f"{cited}/{len(last[-1].get('results') or [])}"
        return out, info

    # ------------------------------------------------------------ evaluations
    def evaluations(self) -> list[dict]:
        out = []
        ev = self.th["evaluation"]
        window = self.pages.get("current") or {}
        for e in self.ledger:
            if e.get("state") != "merged" or e.get("verdict"):
                continue
            start = d(e.get("deployed_on")) or d(e.get("merged_on"))
            due = d(e.get("evaluate_on")) or (start + dt.timedelta(days=self.th["evaluate_after_days"]) if start else None)
            item = {"id": e["id"], "type": e.get("type"), "pages": e.get("pages"), "pr": e.get("pr"), "evaluate_on": due.isoformat() if due else None}
            if not start or not due or self.today < due:
                out.append({**item, "status": "pending"})
                continue
            conf, by, after = self.confounded(start - dt.timedelta(days=28), due)
            if conf:
                out.append({**item, "status": "confounded", "by": by, "judge_after": after,
                            "why": "the before/after windows overlap a Google core/spam rollout: wait, or judge only against the control group"})
                continue
            if d(window.get("from")) and d(window["from"]) < start:
                out.append({**item, "status": "pending", "why": f"the admin's 28-day window starts {window['from']}, before the change"})
                continue
            base = (e.get("baseline28") or {}).get("clicks")
            rows = [self.by_path[p] for p in e.get("pages") or [] if p in self.by_path]
            now = sum(r["clicks"] for r in rows)
            touched = {p for x in self.ledger for p in (x.get("pages") or [])}
            types = {r.get("type") for r in rows}
            control = [(r["clicks"] - r["previous"]["clicks"]) / r["previous"]["clicks"] for r in self.page_rows
                       if r["path"] not in touched and r.get("type") in types and (r.get("previous") or {}).get("clicks", 0) >= 10]
            ctl = statistics.median(control) if control else 0.0
            if not base or base < ev["min_clicks_baseline"]:
                out.append({**item, "status": "ready", "proposed_verdict": "inconclusive", "why": f"baseline {base} clicks: too few to judge"})
                continue
            lift = ((now - base) / base - ctl) * 100
            verdict = "keep" if lift >= ev["keep_pct"] else "revert-proposal" if lift <= ev["revert_pct"] else "inconclusive"
            out.append({**item, "status": "ready", "proposed_verdict": verdict, "clicks_before": base, "clicks_after": now,
                        "control_change_pct": round(ctl * 100, 1), "lift_vs_control_pct": round(lift, 1)})
        return out

    # ------------------------------------------------------------ main
    def score(self) -> dict:
        out = {"project": self.project, "today": self.today.isoformat(), "generated_by": "score.py",
               "window": self.pages.get("current")}
        freeze = self.freeze()
        out["freeze"] = freeze
        out["evaluations"] = self.evaluations()
        reason = self.stop_reason()
        if reason:
            out.update(decision={"action": "stop", "reason": reason}, candidates=[], below_floor=[], dropped=[], notes=[])
            return out
        curve = fit_curve(self.page_rows, self.th)
        out["curve"] = curve
        kpis = (self.summary.get("kpis") or {}).get("cloudflare", {}).get("28d", {})
        out["ai_traffic_28d"] = {k: (kpis.get(k) or {}).get("value") if isinstance(kpis.get(k), dict) else kpis.get(k)
                                 for k in ("aiReferrals", "aiCrawls")}
        winners = self.above_curve(curve)
        panel_cands, out["ai_panel"] = self.ai_panel()
        raw = (self.schema_fixes() + self.news_items(curve) + self.seasonal(curve) + self.decay(freeze)
               + self.low_ctr(curve) + self.striking(curve) + self.internal_links(curve) + panel_cands)
        kept, seen = [], set()
        for c in raw:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            if c["type"] in TITLE_TYPES and c["page"] in winners:
                self.dropped.append({"id": c["id"], "reason": "page already at or above the site's CTR curve: leave winners alone"})
                continue
            if c["type"] == "new-guide" and self.guide_cap_full():
                self.dropped.append({"id": c["id"], "reason": f"guide cap: {self.site['guide_cap']['per_week']} new guide(s) a week already used"})
                continue
            if c["type"] != "internal-links":
                why = self.blocked(c["type"], [p for p in c["pages"] if not p.startswith("(new)")])
                if why:
                    self.dropped.append({"id": c["id"], "reason": why})
                    continue
            kept.append(c)
        floor = self.th["pr_floor_clicks_28d"]
        eligible = sorted((c for c in kept if c["score"] >= floor), key=lambda c: (c["preference"], -c["score"]))
        below = sorted((c for c in kept if c["score"] < floor), key=lambda c: -c["score"])
        out["avoid"] = sorted({f"{e.get('type')}:{e.get('pattern')}" for e in self.ledger
                               if e.get("verdict") in ("regressed", "revert-proposal") and e.get("pattern")})
        opened = self.open_prs()
        if len(opened) >= self.th["max_open_prs"]:
            action = {"action": "stop", "reason": f"cap reached: {len(opened)} open seo-growth PRs (max {self.th['max_open_prs']}): "
                                                  + ", ".join(e.get("pr") or e["id"] for e in opened)}
        elif eligible:
            action = {"action": "candidates", "reason": f"{len(eligible)} candidate(s) clear the floor of {floor} clicks / 28 days"}
        else:
            best = below[0] if below else None
            action = {"action": "nothing", "reason": f"nothing clears the floor of {floor} clicks / 28 days"
                      + (f" (best: {best['id']} at {best['score']})" if best else "")}
        top = [] if action["action"] == "stop" else eligible[: self.th["top_n_for_claude"]]
        out.update(decision=action, candidates=top, eligible=len(eligible),
                   also_eligible=[c["id"] for c in eligible if c not in top],
                   below_floor=below[:5], dropped=self.dropped, notes=self.notes)
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--project", required=True)
    ap.add_argument("--today")
    ap.add_argument("--state")
    ap.add_argument("--out")
    a = ap.parse_args()
    run = Path(a.run)
    state = Path(a.state) if a.state else ledger_mod.home() / a.project
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    result = Scorer(run, a.project, today, state).score()
    out = Path(a.out) if a.out else run / "candidates.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    dec = result["decision"]
    print(f"{a.project} {result['today']}: {dec['action']}: {dec['reason']}")
    for c in result["candidates"]:
        print(f"  {c['score']:7.1f}  p{c['preference']}  {c['id']}")
    print(f"  dropped {len(result['dropped'])}, evaluations {len(result['evaluations'])}, written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
