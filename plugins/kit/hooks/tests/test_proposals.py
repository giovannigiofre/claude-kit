#!/usr/bin/env python3
"""Self-check for proposals.py: cards are deduplicated by fingerprint, classed, taken into items
and retired when stale.

Run: python3 plugins/kit/hooks/tests/test_proposals.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import proposals  # noqa: E402


def run(repo, *args, stdin=None):
    out = subprocess.run([sys.executable, str(SCRIPTS / "proposals.py"), *args], cwd=str(repo), input=stdin,
                         capture_output=True, text=True, timeout=60)
    return out.returncode, out.stdout.strip(), out.stderr.strip()


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL " + str(msg))

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        (repo / "docs").mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / ".claude" / "lead").mkdir(parents=True)  # a project from before the move to .kit
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "true"}))
        (repo / "docs" / "setup.md").write_text("run make install\n")
        (repo / "src").mkdir()
        (repo / "src" / "api.py").write_text("x\n")
        cards = [
            {"origin": "docs/setup.md", "summary": "setup.md says `make install` but the Makefile has no install target",
             "rationale": "a new contributor follows a dead instruction", "evidence": ["docs/setup.md:1", "Makefile"],
             "confidence": "high", "class": "A"},
            {"origin": "src/api.py", "summary": "retry loop has no cap", "rationale": "a 5xx storm loops forever",
             "evidence": ["src/api.py:40"], "confidence": "medium", "class": "B"},
            {"origin": "src/api.py", "summary": "retry loop   has no cap", "rationale": "a 5xx storm loops forever",
             "evidence": [], "confidence": "low", "class": "B"},
            {"origin": "", "summary": "nothing", "class": "A"},
            {"origin": "x", "summary": "y", "class": "Z"},
            {"origin": "config/.env.example", "summary": "token=abc123def456 committed", "class": "A"},
        ]
        code, out, err = run(repo, "add", "-", stdin=json.dumps(cards))
        check(code == 0 and out.startswith("added 2 (A: 1, B: 1)") and "skipped 4" in out, f"{out} {err}")
        pdir = repo / ".claude" / "lead" / "proposals"
        files = sorted(p.name for p in pdir.glob("*.md"))
        check(len(files) == 2 and files[0].startswith("api-retry-loop-has-no-cap") and files[1].startswith("setup-setup-md-says"), files)
        card = proposals.parse(pdir / files[1])
        check(card["class"] == "A" and card["evidence"] == ["docs/setup.md:1", "Makefile"] and card["confidence"] == "high", card)
        check(len(card["fingerprint"]) == 64, "sha256 fingerprint")

        # re-running adds nothing
        code, out, _ = run(repo, "add", "-", stdin=json.dumps(cards[:2]))
        check(out.startswith("added 0 (") and "duplicate" in out, out)
        code, out, _ = run(repo, "list", "--class", "A")
        check(out.startswith("A | setup-setup-md-says") and "api-retry" not in out, out)

        # take: a queued item with a brief from the card; the card is retired; a re-scan still skips it
        setup_id = files[1][:-3]
        code, out, _ = run(repo, "take", setup_id)
        check(code == 0 and out.startswith("item "), out)
        item_id = out.split()[1]
        brief = (repo / ".claude" / "lead" / "items" / item_id / "BRIEF.md").read_text()
        check(brief.startswith(f"ITEM: {item_id}") and "BRIEF: setup.md says" in brief and "DONE WHEN:" in brief
              and "docs/setup.md:1" in brief, brief)
        check(not (pdir / files[1]).exists() and (pdir / "retired" / files[1]).exists(), "card retired after take")
        check("taken as item" in (pdir / "retired" / files[1]).read_text(), "retired reason recorded")
        code, out, _ = run(repo, "add", "-", stdin=json.dumps(cards[:1]))
        check("added 0" in out and ("duplicate" in out or "already an item" in out), out)
        code, out, err = run(repo, "take", setup_id)
        check(code == 1 and "no open card" in err, "taking twice fails")

        # retire: by age or when the origin is gone
        code, out, _ = run(repo, "retire", "--days", "30")
        check(out == "proposals: nothing to retire", out)
        text = (pdir / files[0]).read_text().replace(f"created: {proposals.today()}", "created: 2020-01-01")
        (pdir / files[0]).write_text(text)
        code, out, _ = run(repo, "retire", "--days", "30")
        check(out.startswith(f"retired {files[0][:-3]}: older than 30 days"), out)
        code, out, _ = run(repo, "add", "-", stdin=json.dumps([{"origin": "gone.py", "summary": "dead file", "class": "A"}]))
        code, out, _ = run(repo, "retire")
        check("origin no longer exists" in out, out)
        code, out, _ = run(repo, "list")
        check(out == "proposals: none", out)

    print("proposals: all checks passed" if not failed else f"proposals: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
