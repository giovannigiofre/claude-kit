#!/usr/bin/env python3
"""Proposal cards: candidate work found by read-only scouts, deduplicated, classed, on disk.

    .claude/lead/proposals/<id>.md          one card per finding (frontmatter + Suggestion + Rationale)
    .claude/lead/proposals/retired/<id>.md  taken into an item, or retired as stale

A card's fingerprint is the sha256 of its normalized `origin|summary|rationale`, so the same
finding never makes a second card and a scan can be re-run at any time. Classes: A, mechanical
and reversible (a thread can take it); B, needs judgment (ask first); C, a human decision only.
`take` turns a card into a coordinator item (items.py) and retires the card. Standard library only.

    echo '[{"origin": "docs/setup.md", "summary": "...", "rationale": "...", "evidence": ["docs/setup.md:12"],
            "confidence": "high", "class": "A"}]' | python3 proposals.py add -
    python3 proposals.py list [--class A|B|C]
    python3 proposals.py take <id>            # -> an item, queued for the lead
    python3 proposals.py retire [--days 30]   # cards older than N days, or whose origin is gone
    python3 proposals.py show <id>
"""

import datetime
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import items  # noqa: E402
import kitlib  # noqa: E402

CLASSES = ("A", "B", "C")
CONFIDENCE = ("low", "medium", "high")
MAX_SUMMARY = 300


def proposals_dir(root):
    return items.lead_dir(root) / "proposals"


def normalize(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def fingerprint(origin, summary, rationale):
    return hashlib.sha256("|".join(normalize(x) for x in (origin, summary, rationale)).encode()).hexdigest()


def today():
    return datetime.date.today().isoformat()


def parse(path):
    """A card's fields, or None when the file is not a card."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None
    card, evidence = {"path": str(path)}, []
    for line in m.group(1).splitlines():
        if line.startswith("  - "):
            evidence.append(line[4:].strip())
        elif ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            card[key.strip()] = value.strip()
    card["evidence"] = evidence
    body = m.group(2)
    for section, key in (("Suggestion", "summary"), ("Rationale", "rationale")):
        sm = re.search(r"^## " + section + r"\n(.*?)(?=^## |\Z)", body, re.S | re.M)
        card[key] = sm.group(1).strip() if sm else ""
    return card


def cards(root, retired=False):
    base = proposals_dir(root) / "retired" if retired else proposals_dir(root)
    if not base.is_dir():
        return []
    return [c for c in (parse(p) for p in sorted(base.glob("*.md"))) if c]


def render(card):
    ev = "".join(f"  - {e}\n" for e in card["evidence"])
    return (f"---\nid: {card['id']}\nfingerprint: {card['fingerprint']}\norigin: {card['origin']}\n"
            f"class: {card['class']}\nconfidence: {card['confidence']}\ncreated: {card['created']}\n"
            f"evidence:\n{ev}---\n\n# {card['id']}\n\n## Suggestion\n{card['summary']}\n\n## Rationale\n{card['rationale']}\n")


def clean(card):
    """A candidate as the scouts return it, checked and normalized; (card, problem)."""
    if not isinstance(card, dict):
        return None, "not an object"
    origin = str(card.get("origin") or "").strip()
    summary = re.sub(r"\s+", " ", str(card.get("summary") or "")).strip()
    rationale = re.sub(r"\s+", " ", str(card.get("rationale") or "")).strip()
    klass = str(card.get("class") or "").strip().upper()
    confidence = str(card.get("confidence") or "medium").strip().lower()
    evidence = card.get("evidence") or []
    evidence = [str(e).strip() for e in (evidence if isinstance(evidence, list) else [evidence]) if str(e).strip()]
    if not origin or not summary:
        return None, "origin and summary are required"
    if klass not in CLASSES:
        return None, f"class must be one of {', '.join(CLASSES)}"
    if confidence not in CONFIDENCE:
        confidence = "medium"
    if len(summary) > MAX_SUMMARY:
        summary = summary[:MAX_SUMMARY].rstrip() + "..."
    if kitlib.looks_secret(summary + " " + rationale + " " + " ".join(evidence)):
        return None, "looks like it holds a secret"
    return {"origin": origin, "summary": summary, "rationale": rationale or summary, "class": klass,
            "confidence": confidence, "evidence": evidence[:8]}, None


def add(root, candidates):
    """Write a card per new finding. Returns (added ids, skipped: list of (why, summary))."""
    root = Path(root)
    base = proposals_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    items.ensure_excluded(root)
    known = {c.get("fingerprint") for c in cards(root) + cards(root, retired=True)}
    ids = {c.get("id") for c in cards(root) + cards(root, retired=True)}
    briefs = []
    for row in items.list_items(root):
        try:
            briefs.append(normalize((Path(row["path"]) / "BRIEF.md").read_text(encoding="utf-8")))
        except OSError:
            pass
    seen_now, added, skipped = set(), [], []
    for raw in candidates:
        card, problem = clean(raw)
        if problem:
            skipped.append((problem, str(raw)[:80]))
            continue
        fp = fingerprint(card["origin"], card["summary"], card["rationale"])
        key = (normalize(card["origin"]), normalize(card["summary"]))
        if fp in known or key in seen_now:
            skipped.append(("duplicate", card["summary"]))
            continue
        if any(normalize(card["summary"]) in b for b in briefs):
            skipped.append(("already an item", card["summary"]))
            continue
        base_id = items.slug(Path(card["origin"]).name.split(".")[0] + " " + " ".join(card["summary"].split()[:5]), 48)
        card_id, n = base_id, 2
        while card_id in ids:
            card_id = f"{base_id}-{n}"
            n += 1
        card.update({"id": card_id, "fingerprint": fp, "created": today()})
        (base / f"{card_id}.md").write_text(render(card), encoding="utf-8")
        known.add(fp)
        ids.add(card_id)
        seen_now.add(key)
        added.append(card_id)
    return added, skipped


def retire_card(root, card_id, why):
    base = proposals_dir(root)
    src = base / f"{card_id}.md"
    if not src.is_file():
        return False
    (base / "retired").mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    (base / "retired" / f"{card_id}.md").write_text(text.rstrip() + f"\n\n## Retired\n{today()}: {why}\n", encoding="utf-8")
    src.unlink()
    return True


def take(root, card_id):
    """The card becomes a queued item for the lead; the card is retired."""
    card = next((c for c in cards(root) if c.get("id") == card_id), None)
    if not card:
        return None
    ev = "\n".join(f"- {e}" for e in card["evidence"]) or "- (none recorded)"
    brief = (f"BRIEF: {card['summary']}\nWHY: {card['rationale']}\n"
             f"DONE WHEN: the evidence below no longer reproduces, and the project's verify gate passes\n"
             f"SCOPE: {card['origin']} and what it directly needs | OUT: anything the evidence does not name\n"
             f"EVIDENCE:\n{ev}\nFROM: proposal card {card_id} (class {card['class']}, confidence {card['confidence']})\n")
    item_id = items.new(root, card_id, brief, source=f"proposal {card_id}")
    retire_card(root, card_id, f"taken as item {item_id}")
    return item_id


def retire_stale(root, days=30):
    """Cards older than `days`, or whose origin no longer exists. Returns the retired ids."""
    root = Path(root)
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    out = []
    for card in cards(root):
        try:
            created = datetime.date.fromisoformat(card.get("created", ""))
        except ValueError:
            created = cutoff
        origin = root / card.get("origin", "")
        why = None
        if created <= cutoff:
            why = f"older than {days} days"
        elif card.get("origin") and not origin.exists() and ":" not in card["origin"]:
            why = "origin no longer exists"
        if why and retire_card(root, card["id"], why):
            out.append((card["id"], why))
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    root = kitlib.project_root({"cwd": str(Path.cwd())})
    cmd, rest = argv[0], argv[1:]
    if cmd == "add":
        source = rest[0] if rest else "-"
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
        try:
            data = json.loads(text) if text.strip() else []
        except ValueError as exc:
            print(f"proposals: not JSON: {exc}", file=sys.stderr)
            return 2
        data = data if isinstance(data, list) else [data]
        added, skipped = add(root, data)
        by_class = {}
        for c in cards(root):
            if c["id"] in added:
                by_class[c["class"]] = by_class.get(c["class"], 0) + 1
        print(f"added {len(added)} (" + ", ".join(f"{k}: {v}" for k, v in sorted(by_class.items())) + ")"
              + (f"; skipped {len(skipped)}: " + "; ".join(f"{w} ({s[:50]})" for w, s in skipped[:6]) if skipped else ""))
        print(f"cards in {proposals_dir(root)}: {len(cards(root))}")
        return 0
    if cmd == "list":
        klass = None
        if "--class" in rest:
            klass = rest[rest.index("--class") + 1].upper()
        rows = [c for c in cards(root) if not klass or c.get("class") == klass]
        for c in rows:
            print(f"{c['class']} | {c['id']} | {c.get('origin')} | {c.get('summary')[:90]} | {c.get('confidence')} | {c.get('created')}")
        if not rows:
            print("proposals: none")
        return 0
    if cmd == "take":
        if not rest:
            print("proposals: take needs a card id", file=sys.stderr)
            return 2
        item_id = take(root, rest[0])
        if not item_id:
            print(f"proposals: no open card {rest[0]}", file=sys.stderr)
            return 1
        print(f"item {item_id}\t{items.item_path(root, item_id)}")
        return 0
    if cmd == "retire":
        days = int(rest[rest.index("--days") + 1]) if "--days" in rest else 30
        gone = retire_stale(root, days)
        for card_id, why in gone:
            print(f"retired {card_id}: {why}")
        if not gone:
            print("proposals: nothing to retire")
        return 0
    if cmd == "show":
        card = next((c for c in cards(root) if c.get("id") == (rest[0] if rest else "")), None)
        if not card:
            print("proposals: no such card", file=sys.stderr)
            return 1
        print(Path(card["path"]).read_text(encoding="utf-8").rstrip())
        return 0
    print(f"proposals: unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
