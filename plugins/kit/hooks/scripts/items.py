#!/usr/bin/env python3
"""The coordinator's items on disk: one folder per piece of work, written mostly by hooks.

    .claude/lead/items/<id>/BRIEF.md     the goal, DONE WHEN, scope: written when the item is
                                         made (by the lead, /kit:handoff or a proposal card),
                                         editable by the user to steer the next round
    .claude/lead/items/<id>/REPORT.md    the thread's final report (SubagentStop, kit:implementer)
    .claude/lead/items/<id>/VERDICT.md   the verifier's report (SubagentStop, kit:verifier)
    .claude/lead/items/<id>/LOG.md       one line per event, append-only
    .claude/lead/items/done/<id>/        archived when the item is done; its board row moves
                                         to .claude/lead/archive.md

The board stays the index; these files are what survives a compaction, a restart or a look from
another session (`cat` them). BRIEF.md starts with `ITEM: <id>`: a thread briefed with its text
carries the id, and the hooks file its report under it. Standard library only.

    python3 items.py new <slug> [--brief FILE|-] [--from lead|handoff|scout] [--kind ship|scout]
    python3 items.py list [--status queued|working|review|needs-you|done]
    python3 items.py log <id> <status> [note]
    python3 items.py report|verdict <id> [FILE|-]
    python3 items.py show|path <id>
    python3 items.py done <id>
"""

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

ITEM_LINE = re.compile(r"^\s*ITEM:\s*([a-z0-9][a-z0-9._-]*)\s*$", re.M | re.I)
STATUSES = ("queued", "working", "review", "needs-you", "landing", "done", "parked", "reported", "verdict")


def board_file(root):
    """`.claude/lead/board.md`, or kit.json `lead.board`."""
    config, _ = kitlib.load_config(root)
    lead = (config or {}).get("lead") if isinstance(config, dict) else None
    board = lead.get("board") if isinstance(lead, dict) and isinstance(lead.get("board"), str) else ".claude/lead/board.md"
    return Path(board) if Path(board).is_absolute() else Path(root) / board


def lead_dir(root):
    """`.claude/lead` or the folder of kit.json `lead.board`."""
    return board_file(root).parent


def items_dir(root):
    return lead_dir(root) / "items"


def ensure_excluded(root):
    """The lead's folder stays out of git unless the project ignores it already."""
    import subprocess
    root = Path(root)
    rel = lead_dir(root)
    try:
        rel = rel.relative_to(root).as_posix()
    except ValueError:
        return
    probe = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", f"{rel}/probe"], capture_output=True)
    if probe.returncode == 0:
        return
    exclude = kitlib.git_out(root, "rev-parse", "--git-path", "info/exclude")
    if not exclude:
        return
    exclude = Path(exclude) if Path(exclude).is_absolute() else root / exclude
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        line = f"/{rel}/"
        if line not in text.splitlines():
            exclude.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n", encoding="utf-8")
    except OSError:
        pass


def slug(text, limit=40):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:limit].strip("-") or "item"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def item_path(root, item_id, done=False):
    base = items_dir(root)
    return (base / "done" / item_id) if done else (base / item_id)


def find(root, item_id):
    """The item's folder, open or archived, or None."""
    for done in (False, True):
        p = item_path(root, item_id, done)
        if p.is_dir():
            return p
    return None


def find_id(text):
    """The item an `ITEM: <id>` line names, in a brief or a report."""
    m = ITEM_LINE.search(text or "")
    return m.group(1).lower() if m else None


def log(root, item_id, status, note=""):
    p = find(root, item_id)
    if not p:
        return False
    with open(p / "LOG.md", "a", encoding="utf-8") as f:
        f.write(f"- {now()} | {status} | {note.strip()}\n" if note else f"- {now()} | {status}\n")
    return True


def status_of(path):
    """(last status, last note) from LOG.md."""
    try:
        lines = [ln for ln in (path / "LOG.md").read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
    except OSError:
        return "", ""
    if not lines:
        return "", ""
    parts = [x.strip() for x in lines[-1][2:].split("|", 2)]
    return (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else "")


def new(root, name, brief="", source="lead", kind="ship"):
    """Make an item: the folder, BRIEF.md headed by `ITEM: <id>`, the first LOG line. Returns the id."""
    root = Path(root)
    base = items_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    ensure_excluded(root)
    item_id = slug(name)
    n = 2
    while find(root, item_id):
        item_id = f"{slug(name, 36)}-{n}"
        n += 1
    folder = base / item_id
    folder.mkdir()
    body = (brief or "").strip()
    if find_id(body) != item_id:
        body = f"ITEM: {item_id}\nKIND: {kind}\n\n" + ITEM_LINE.sub("", body).strip()
    (folder / "BRIEF.md").write_text(body + "\n", encoding="utf-8")
    log(root, item_id, "queued", f"from {source}")
    return item_id


def write(root, item_id, name, text, status, note=""):
    """REPORT.md or VERDICT.md: the latest text, and a LOG line saying so."""
    p = find(root, item_id)
    if not p or name not in ("REPORT.md", "VERDICT.md"):
        return False
    (p / name).write_text((text or "").rstrip() + "\n", encoding="utf-8")
    log(root, item_id, status, note)
    return True


def archive_row(root, item_id):
    """Move the item's board row to archive.md beside the board, so the board keeps only live work."""
    board = board_file(root)
    try:
        lines = board.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    row = re.compile(rf"^\s*{re.escape(item_id)}\s*\|", re.I)
    gone = [ln for ln in lines if row.match(ln)]
    if not gone:
        return
    tmp = board.with_name(f".{board.name}.tmp")
    tmp.write_text("\n".join(ln for ln in lines if not row.match(ln)) + "\n", encoding="utf-8")
    os.replace(tmp, board)
    with open(board.parent / "archive.md", "a", encoding="utf-8") as f:
        f.write("".join(f"{ln} | archived {now()[:10]}\n" for ln in gone))


def done(root, item_id):
    p = item_path(root, item_id)
    if not p.is_dir():
        return False
    log(root, item_id, "done")
    archive_row(root, item_id)
    target = item_path(root, item_id, done=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(p), str(target))
    return True


def list_items(root, status=None, archived=False):
    base = items_dir(root) / "done" if archived else items_dir(root)
    rows = []
    if not base.is_dir():
        return rows
    for p in sorted(base.iterdir()):
        if not p.is_dir() or p.name == "done":
            continue
        st, note = status_of(p)
        if status and st != status:
            continue
        head = ""
        try:
            lines = [ln for ln in (p / "BRIEF.md").read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.startswith(("ITEM:", "KIND:"))]
            head = lines[0][:100] if lines else ""
        except OSError:
            pass
        rows.append({"id": p.name, "status": st, "note": note, "brief": head, "path": str(p)})
    return rows


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    root = kitlib.project_root({"cwd": str(Path.cwd())})
    cmd, rest = argv[0], argv[1:]

    def opt(flag, default=None):
        if flag in rest:
            i = rest.index(flag)
            value = rest[i + 1] if i + 1 < len(rest) else default
            del rest[i:i + 2]
            return value
        return default

    def read_text(arg):
        if arg == "-":
            return sys.stdin.read()
        return Path(arg).read_text(encoding="utf-8") if arg else ""

    if cmd == "new":
        source, kind = opt("--from", "lead"), opt("--kind", "ship")
        brief = read_text(opt("--brief"))
        if not rest:
            print("items: new needs a name", file=sys.stderr)
            return 2
        item_id = new(root, " ".join(rest), brief, source, kind)
        print(f"{item_id}\t{item_path(root, item_id)}")
        return 0
    if cmd == "list":
        status = opt("--status")
        rows = list_items(root, status)
        for r in rows:
            print(f"{r['id']} | {r['status'] or '?'} | {r['brief']} | {r['note']}")
        if not rows:
            print("items: none" + (f" with status {status}" if status else ""))
        return 0
    if cmd in ("log", "report", "verdict", "done", "show", "path"):
        if not rest:
            print(f"items: {cmd} needs an item id", file=sys.stderr)
            return 2
        item_id = rest[0]
        if cmd == "log":
            ok = log(root, item_id, rest[1] if len(rest) > 1 else "note", " ".join(rest[2:]))
        elif cmd in ("report", "verdict"):
            text = read_text(rest[1] if len(rest) > 1 else "-")
            name = "REPORT.md" if cmd == "report" else "VERDICT.md"
            ok = write(root, item_id, name, text, "reported" if cmd == "report" else "verdict")
        elif cmd == "done":
            ok = done(root, item_id)
        elif cmd == "path":
            p = find(root, item_id)
            ok = bool(p)
            if ok:
                print(p)
        else:
            p = find(root, item_id)
            ok = bool(p)
            if ok:
                for name in ("BRIEF.md", "REPORT.md", "VERDICT.md", "LOG.md"):
                    f = p / name
                    if f.is_file():
                        print(f"===== {name}\n" + f.read_text(encoding="utf-8").rstrip())
        if not ok:
            print(f"items: no item {item_id}", file=sys.stderr)
            return 1
        return 0
    print(f"items: unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
