#!/usr/bin/env python3
"""Delete screenshots and videos older than N days from the Omnigent projects' evidence folders.

    clean_evidence.py [--days 3] [--dry-run]

Looks only at `.kit/evidence/` of: every Omnigent project's workspace (read from the local
server, so a new project is included without changes here), Studio, and the specialists'
worktrees under ~/.omnigent/worktrees. Only image and video files go; notes and logs stay.
An image deleted here shows as "Image not available" in the chat that sent it.
Run daily by the LaunchAgent ai.omnigent.evidence-cleanup (see omnigent/README.md).
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:6767/v1/projects"
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4", ".mov"}
HOME = Path.home()


def workspaces():
    roots = {HOME / "Documents/studio"}
    try:
        req = urllib.request.Request(URL, headers={"Origin": "omnigent://internal"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        for p in d.get("data", d) if isinstance(d, dict) else d:
            ws = (p.get("config") or {}).get("workspace")
            if ws:
                roots.add(Path(ws))
    except OSError as exc:
        print(f"server unreachable, projects skipped this run: {exc}")
    wt = HOME / ".omnigent/worktrees"
    if wt.is_dir():
        roots.update(d for d in wt.glob("*/*") if d.is_dir())
    return sorted(roots)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cutoff = time.time() - a.days * 86400
    n = size = 0
    for root in workspaces():
        ev = root / ".kit/evidence"
        if not ev.is_dir():
            continue
        for f in ev.rglob("*"):
            if f.is_file() and not f.is_symlink() and f.suffix.lower() in MEDIA and f.stat().st_mtime < cutoff:
                n += 1
                size += f.stat().st_size
                if not a.dry_run:
                    f.unlink()
        if not a.dry_run:
            for d in sorted((p for p in ev.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
                if not any(d.iterdir()):
                    d.rmdir()
    verb = "would delete" if a.dry_run else "deleted"
    print(f"{time.strftime('%Y-%m-%d %H:%M')} {verb} {n} files, {size / 1e6:.0f} MB, older than {a.days:g} days")


if __name__ == "__main__":
    main()
