#!/usr/bin/env python3
"""The per-page experiment ledger: every change seo-growth proposed, what happened to its PR, and its verdict.

Stored outside the repo, like the boards: $SEO_GROWTH_HOME/<project>/ledger.jsonl (default
~/.omnigent/seo-growth). Append-only: each line is an event {id, ...fields}; the entry is the merge of its
events in order, so the history of every change stays readable.

  ledger.py add  --project P --type T --page /a/ [--page /b/] [--query Q] [--pr URL] [--pattern P]
                 [--calendar-id ID] [--new-guide] [--baseline JSON] [--note TEXT] [--today D]
  ledger.py set  --project P --id ID key=value ...      (state, merged_on, deployed_on, closed_on, verdict, ...)
  ledger.py sync --project P                            (PR state from GitHub via gh: open, merged, closed)
  ledger.py list --project P [--json]
  ledger.py due  --project P [--today D]                (merged changes whose evaluate_on has come, no verdict)

Fields: id, opened_on, type, key (type:first page), pages, query, pr, state (open|merged|closed),
merged_on, deployed_on, closed_on, pattern (e.g. a title pattern), calendar_id, new_guide,
baseline28 {clicks, impressions, ctr, position}, evaluate_on, verdict (keep|revert-proposal|inconclusive|
regressed), verdict_on, note. `regressed` and `revert-proposal` mean: never repeat this change on this page.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

EVALUATE_AFTER_DAYS = 28
STATES = ("open", "merged", "closed")
VERDICTS = ("keep", "revert-proposal", "inconclusive", "regressed")


def home() -> Path:
    return Path(os.environ.get("SEO_GROWTH_HOME") or Path.home() / ".omnigent" / "seo-growth")


def path_for(project: str) -> Path:
    return home() / project / "ledger.jsonl"


def load(path: Path) -> list[dict]:
    """Entries folded from events, in first-seen order."""
    entries: dict[str, dict] = {}
    if not path.exists():
        return []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            print(f"ledger: line {n} is not JSON, skipped", file=sys.stderr)
            continue
        if "id" in ev:
            entries.setdefault(ev["id"], {}).update(ev)
    return list(entries.values())


def append(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def day(s: str | None) -> dt.date | None:
    return dt.date.fromisoformat(s[:10]) if s else None


def evaluate_on(entry: dict) -> str | None:
    start = day(entry.get("deployed_on")) or day(entry.get("merged_on"))
    return (start + dt.timedelta(days=EVALUATE_AFTER_DAYS)).isoformat() if start else None


def coerce(value: str):
    if value in ("null", ""):
        return None
    if value in ("true", "false"):
        return value == "true"
    if value[:1] in "{[":
        return json.loads(value)
    return value


def cmd_add(a) -> int:
    path = path_for(a.project)
    today = a.today or dt.date.today().isoformat()
    n = sum(1 for e in load(path) if e["id"].startswith(today)) + 1
    entry = {"id": f"{today}-{n}", "opened_on": today, "type": a.type, "key": f"{a.type}:{a.page[0]}",
             "pages": a.page, "query": a.query, "pr": a.pr, "state": "open", "pattern": a.pattern,
             "calendar_id": a.calendar_id, "new_guide": a.new_guide,
             "baseline28": json.loads(a.baseline) if a.baseline else None, "note": a.note}
    append(path, {k: v for k, v in entry.items() if v not in (None, False)} | {"state": "open"})
    print(entry["id"])
    return 0


def cmd_set(a) -> int:
    path = path_for(a.project)
    if a.id not in {e["id"] for e in load(path)}:
        sys.exit(f"no entry {a.id}")
    ev = {"id": a.id}
    for kv in a.pairs:
        k, sep, v = kv.partition("=")
        if not sep:
            sys.exit(f"expected key=value, got {kv!r}")
        ev[k] = coerce(v)
    if "state" in ev and ev["state"] not in STATES:
        sys.exit(f"state must be one of {STATES}")
    if "verdict" in ev and ev["verdict"] not in VERDICTS:
        sys.exit(f"verdict must be one of {VERDICTS}")
    merged = {**next(e for e in load(path) if e["id"] == a.id), **ev}
    if ("merged_on" in ev or "deployed_on" in ev) and evaluate_on(merged):
        ev["evaluate_on"] = evaluate_on(merged)
    append(path, ev)
    print(json.dumps(ev))
    return 0


def cmd_sync(a) -> int:
    path = path_for(a.project)
    changed = 0
    for e in load(path):
        if e.get("state") != "open" or not e.get("pr"):
            continue
        p = subprocess.run(["gh", "pr", "view", e["pr"], "--json", "state,mergedAt,closedAt"],
                           capture_output=True, text=True, timeout=60)
        if p.returncode:
            print(f"sync {e['id']}: gh failed: {p.stderr.strip()[:200]}", file=sys.stderr)
            continue
        pr = json.loads(p.stdout)
        if pr["state"] == "MERGED":
            ev = {"id": e["id"], "state": "merged", "merged_on": pr["mergedAt"][:10]}
            ev["evaluate_on"] = evaluate_on({**e, **ev})
        elif pr["state"] == "CLOSED":
            ev = {"id": e["id"], "state": "closed", "closed_on": (pr.get("closedAt") or "")[:10] or None}
        else:
            continue
        append(path, ev)
        changed += 1
    print(f"ledger sync: {changed} updated")
    return 0


def cmd_list(a) -> int:
    entries = load(path_for(a.project))
    if a.json:
        print(json.dumps(entries, ensure_ascii=False, indent=1))
    else:
        for e in entries:
            print(f"{e['id']:13} {e.get('state', ''):7} {e.get('type', ''):18} {','.join(e.get('pages', [])):40} "
                  f"{e.get('verdict') or ''} {e.get('pr') or ''}")
    return 0


def cmd_due(a) -> int:
    today = a.today or dt.date.today().isoformat()
    due = [e for e in load(path_for(a.project))
           if e.get("state") == "merged" and not e.get("verdict") and (e.get("evaluate_on") or "9999") <= today]
    print(json.dumps(due, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--project", required=True)
    add.add_argument("--type", required=True)
    add.add_argument("--page", action="append", required=True)
    add.add_argument("--query")
    add.add_argument("--pr")
    add.add_argument("--pattern")
    add.add_argument("--calendar-id")
    add.add_argument("--new-guide", action="store_true")
    add.add_argument("--baseline")
    add.add_argument("--note")
    add.add_argument("--today")
    st = sub.add_parser("set")
    st.add_argument("--project", required=True)
    st.add_argument("--id", required=True)
    st.add_argument("pairs", nargs="+")
    for name in ("sync", "list", "due"):
        p = sub.add_parser(name)
        p.add_argument("--project", required=True)
        if name == "list":
            p.add_argument("--json", action="store_true")
        if name == "due":
            p.add_argument("--today")
    a = ap.parse_args()
    return {"add": cmd_add, "set": cmd_set, "sync": cmd_sync, "list": cmd_list, "due": cmd_due}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
