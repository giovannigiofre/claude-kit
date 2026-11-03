#!/usr/bin/env python3
"""The coordinator's items on disk: one folder per piece of work, written mostly by hooks.

    .claude/lead/items/<id>/BRIEF.md     the goal, DONE WHEN, scope: written when the item is
                                         made (by the lead, /kit:handoff or a proposal card),
                                         editable by the user to steer the next round
    .claude/lead/items/<id>/REPORT.md    the thread's final report (SubagentStop, kit:implementer)
    .claude/lead/items/<id>/VERDICT.md   the verifier's report (SubagentStop, kit:verifier)
    .claude/lead/items/<id>/LOG.md       one line per event, append-only
    .claude/lead/items/done/<id>/        archived when the item is done

The board stays the index; these files are what survives a compaction, a restart or a look from
another session (`cat` them). BRIEF.md starts with `ITEM: <id>`: a thread briefed with its text
carries the id, and the hooks file its report under it. Standard library only.

    python3 items.py new <slug> [--brief FILE|-] [--from lead|handoff|scout] [--kind ship|scout]
    python3 items.py list [--status queued|working|review|needs-you|done]
    python3 items.py log <id> <status> [note]
    python3 items.py report|verdict <id> [FILE|-]
    python3 items.py show|path <id>
    python3 items.py done <id>
    python3 items.py sweep [--repo DIR] [--dry-run]   remove merged threads' worktrees and branches
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

ITEM_LINE = re.compile(r"^\s*ITEM:\s*([a-z0-9][a-z0-9._-]*)\s*$", re.M | re.I)
STATUSES = ("queued", "working", "review", "needs-you", "landing", "done", "parked", "reported", "verdict")


def lead_dir(root):
    """`.claude/lead` or the folder of kit.json `lead.board`."""
    config, _ = kitlib.load_config(root)
    lead = (config or {}).get("lead") if isinstance(config, dict) else None
    board = lead.get("board") if isinstance(lead, dict) and isinstance(lead.get("board"), str) else ".claude/lead/board.md"
    path = Path(board) if Path(board).is_absolute() else Path(root) / board
    return path.parent


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


def done(root, item_id):
    p = item_path(root, item_id)
    if not p.is_dir():
        return False
    log(root, item_id, "done")
    target = item_path(root, item_id, done=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(p), str(target))
    return True


# ignored folders that only an install or a tool writes, never a person: no reason to keep a worktree.
# Generic names (build, dist, target, .cache) are not here: a hand-written note can sit in them.
REBUILDABLE = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
               ".next", ".turbo"}
# branches a sweep never deletes, whatever their PR history (gitflow, release lines)
LONG_LIVED = re.compile(r"^(main|master|develop|development|dev|trunk|staging|production|release\b.*|hotfix\b.*)$")
UNKNOWN = object()


def git_try(cwd, *args):
    """stdout of a git command, or None when it fails: a sweep reads a failure as "keep it"."""
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def busy_dirs():
    """The working directories of running processes, or UNKNOWN when they cannot be read."""
    proc = Path("/proc")
    if (proc / "self" / "cwd").exists():
        found = set()
        for p in proc.iterdir():
            try:
                found.add(Path(os.readlink(p / "cwd")).resolve())
            except OSError:
                continue
        return found or UNKNOWN
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return UNKNOWN
    found = {Path(line[1:]).resolve() for line in out.splitlines() if line.startswith("n/")}
    return found or UNKNOWN


def merged_heads(repo, base):
    """{branch: head sha} of the PRs merged into `base` (gh, or $KIT_GH), {} when gh fails."""
    gh = os.environ.get("KIT_GH") or "gh"
    try:
        out = subprocess.run([gh, "pr", "list", "--state", "merged", "--base", base, "--limit", "200",
                              "--json", "headRefName,headRefOid"], cwd=str(repo), capture_output=True,
                             text=True, timeout=60)
        rows = json.loads(out.stdout) if out.returncode == 0 else []
    except Exception:
        rows = []
    return {r.get("headRefName"): r.get("headRefOid") for r in rows if isinstance(r, dict)}


EVIDENCE = (".claude", "evidence")  # the threads' evidence folders, saved to the main checkout on removal


def evidence_files(path):
    top = Path(path).joinpath(*EVIDENCE)
    return [f for f in top.rglob("*") if f.is_file()] if top.is_dir() else []


def unsaved_ignored(path, main):
    """The first ignored file in the worktree `path` that `git worktree remove` would delete and the
    main checkout does not hold identically (a copied .env is not lost; a local note is), or None.
    An evidence file the main checkout lacks is not lost: the sweep copies it there first."""
    out = git_try(path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z")
    if out is None:
        return "(git ls-files failed)"
    seen = 0
    for entry in filter(None, out.split("\0")):
        if any(part in REBUILDABLE for part in Path(entry).parts):
            continue
        top = Path(path) / entry
        files = [top] if top.is_file() else []
        for folder, dirs, names in os.walk(top) if top.is_dir() else ():
            dirs[:] = [d for d in dirs if d not in REBUILDABLE]
            files += [Path(folder) / n for n in names]
        for f in files:
            seen += 1
            rel = f.relative_to(path)
            twin = Path(main) / rel
            if seen > 2000:
                return rel.as_posix()
            if not twin.exists() and rel.parts[:2] == EVIDENCE:
                continue
            if not twin.is_file() or twin.read_bytes() != f.read_bytes():
                return rel.as_posix()
    return None


def save_evidence(path, main):
    """Copy the worktree's evidence files the main checkout lacks into it. False if one fails."""
    try:
        for f in evidence_files(path):
            twin = Path(main) / f.relative_to(path)
            if not twin.exists():
                twin.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, twin)
        return True
    except OSError:
        return False


def names_worktree(folder, branch, paths):
    """Whether an item's BRIEF, LOG or REPORT records this branch or worktree path (a report's
    BRANCH / PR line does)."""
    text = ""
    for name in ("BRIEF.md", "LOG.md", "REPORT.md"):
        try:
            text += (folder / name).read_text(encoding="utf-8", errors="replace") + "\n"
        except OSError:
            continue
    edge = r"(?<![\w/.-]){}(?![\w/-]|\.\w)"
    return any(re.search(edge.format(re.escape(t)), text) for t in {branch, *paths} if t)


def thread_item(path, branch, main, items_root):
    """(owned, open item id or None). Owned only when a done item names the worktree: it is
    <repo>-<id> for that id, or the item's files record its branch or path. Location alone is not
    ownership (a .claude/worktrees/agent-* or a hand-made <repo>-x stays). An open item naming it
    the same way means its thread may still be working there."""
    raw, resolved, main = str(path), Path(path).resolve(), Path(main).resolve()
    prefix = main.name + "-"
    named = resolved.name[len(prefix):].lower() if resolved.name.startswith(prefix) else None
    base = items_dir(items_root)
    done_dir = base / "done"
    open_items = [p for p in base.iterdir() if p.is_dir() and p.name != "done"] if base.is_dir() else []
    done_items = [p for p in done_dir.iterdir() if p.is_dir()] if done_dir.is_dir() else []
    paths = (raw, str(resolved))

    def names_it(folder):
        return folder.name == named or names_worktree(folder, branch, paths)

    active = next((p.name for p in sorted(open_items) if names_it(p)), None)
    owned = any(names_it(p) for p in done_items)
    return owned, active


def sweep(repo, dry_run=False, items_root=None):
    """Remove each linked worktree, and its branch, whose PR was merged into the default branch with
    the branch's current tip as its head, and that holds nothing it would lose: no uncommitted or
    untracked file, and no ignored file the main checkout lacks (rebuildable folders aside; evidence
    under .claude/evidence/ is copied to the main checkout first). The
    worktree removal is never forced; the branch goes with -D, since a squash merge leaves it
    unmerged in git's eyes and the PR head check stands in for that. A worktree with no merged PR,
    one with commits after the merge, a stacked PR's, and the one this runs in stay, each listed
    with its reason. Only worktrees a done item names are touched (see thread_item), never a long-lived
    branch, never one whose item is not done yet, and never one a running process has as its
    working directory; when git or the process list cannot be read, the worktree stays.
    Returns [(path, branch, action)]."""
    repo = Path(repo)
    kitlib.git_out(repo, "fetch", "--prune", "--quiet", timeout=120)
    if not dry_run:
        kitlib.git_out(repo, "worktree", "prune")
    base = (kitlib.default_branch(repo) or "").replace("origin/", "", 1)
    merged = merged_heads(repo, base) if base else {}
    main, rows, entry = None, [], {}
    for line in kitlib.git_out(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if line.startswith("worktree "):
            entry = {"path": line[9:].strip()}
        elif line.startswith("branch refs/heads/"):
            entry["branch"] = line[18:].strip()
        elif not line.strip() and entry:
            if main is None:
                main = entry["path"]  # the first entry is the main checkout
            else:
                rows.append(entry)
            entry = {}
    here = Path.cwd().resolve()
    items_root = items_root or repo
    busy = None
    results = []
    for wt in rows:
        path, branch = wt["path"], wt.get("branch")
        tip = kitlib.git_out(path, "rev-parse", "HEAD")
        if not branch or not tip:
            action = "kept: detached HEAD or unreadable"
        elif branch == base or LONG_LIVED.match(branch):
            action = "kept: a long-lived branch"
        elif (owned := thread_item(path, branch, main, items_root))[1]:
            action = f"kept: item {owned[1]} is not done yet"
        elif not owned[0]:
            action = "kept: no done item names this worktree"
        elif merged.get(branch) != tip:
            action = "kept: no PR merged into " + (base or "the default branch") + " at this tip"
        elif here == Path(path).resolve() or Path(path).resolve() in here.parents:
            action = "kept: the current directory"
        elif (status := git_try(path, "status", "--porcelain", "--untracked-files=all",
                                "--ignore-submodules=none")) is None or status.strip():
            action = "kept: uncommitted or untracked files" if status else "kept: git status failed"
        elif (lost := unsaved_ignored(path, main)):
            action = f"kept: ignored file not in the main checkout ({lost})"
        elif (busy := busy if busy is not None else busy_dirs()) is UNKNOWN:
            action = "kept: cannot tell whether a process works in it"
        elif any(d == Path(path).resolve() or Path(path).resolve() in d.parents for d in busy):
            action = "kept: a running process works in it"
        elif dry_run:
            action = "would remove"
        elif not save_evidence(path, main) or not kitlib.git_ok(main, "worktree", "remove", path):  # no --force: a locked one stays
            action = "kept: git refused to remove it"
        else:
            action = "removed" if kitlib.git_ok(main, "branch", "-D", branch) else "removed; branch kept"
        results.append((path, branch or "", action))
    return results


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
    if cmd == "sweep":
        repo = opt("--repo")
        dry = "--dry-run" in rest
        target = kitlib.git_root(repo or str(Path.cwd()))
        if not target:
            print("items: sweep needs a git repository", file=sys.stderr)
            return 2
        here = git_try(Path.cwd(), "worktree", "list", "--porcelain") or ""
        lead_root = here.splitlines()[0][9:] if here.startswith("worktree ") else target  # the items live there
        rows = sweep(target, dry, items_root=lead_root)
        for path, branch, action in rows:
            print(f"{action} | {branch or '-'} | {path}")
        if not rows:
            print("items: no linked worktrees")
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
