#!/usr/bin/env python3
"""The coordinator's items on disk: one folder per piece of work, written mostly by hooks.

    <state>/lead/items/<id>/BRIEF.md     the goal, DONE WHEN, scope: written when the item is
                                         made (by the lead, /kit:handoff or a proposal card),
                                         editable by the user to steer the next round
    <state>/lead/items/<id>/REPORT.md    the thread's final report (SubagentStop, kit:implementer)
    <state>/lead/items/<id>/VERDICT.md   the verifier's report (SubagentStop, kit:verifier)
    <state>/lead/items/<id>/LOG.md       one line per event, append-only
    <state>/lead/items/<id>/out/         files a thread leaves for the coordinator (`put`): a
                                         scout's outputs, which must outlive its worktree
    <state>/lead/items/done/<id>/        archived when the item is done; its board row moves
                                         to <state>/lead/archive.md (an earlier archive of the
                                         same id is kept: done/<id>-2, -3, ...)

<state> is `.kit` at the repo root, or `.claude` in a project the kit has not moved yet
(kitlib.state_entry; migrate_state.py moves it).

The board stays the index; these files are what survives a compaction, a restart or a look from
another session (`cat` them). BRIEF.md starts with `ITEM: <id>`: a thread briefed with its text
carries the id, and the hooks file its report under it. `new` also appends a `queued` row to the
board when it exists (`<id> | <kind> | <name> | DONE WHEN <first DONE WHEN line of the brief> |
queued | agent - | - | from <source>`), so a handed-off or taken item is seen. `new` refuses the
name of an item that is still open (exit 1, naming its status and when it was made: another
session has it); `--again` makes `<id>-2` on purpose, and an archived name gets its suffix as is. Standard library only.

    python3 items.py new <slug> [--brief FILE|-] [--from lead|handoff|scout] [--kind ship|scout] [--again]
    python3 items.py list [--status queued|working|review|needs-you|done]
    python3 items.py log <id> <status> [note]
    python3 items.py put <id> <file>...      copy files into the item's out/ folder (their names kept)
    python3 items.py report|verdict <id> [FILE|-]
    python3 items.py show|path <id>
    python3 items.py done <id> [--force]
    python3 items.py status [--json]
    python3 items.py conflicts [<id> ...]
    python3 items.py unattended [push=ask|allow] [rebase=ask|allow] [merge=ask] [--proposal]
    python3 items.py records [set "<place>: <what to update>" ...]
    python3 items.py away on|off|status
    python3 items.py sandbox on|off|status

`status` is one snapshot of the open items read from their folders: id, kind, status, last event
and its age, note, the agent, branch and PR the LOG or REPORT.md names, the summed `cost` lines
(subagent_stop.py writes one per finished thread), `blocked-by` dependencies, counts per status,
and the board's NEEDS YOU questions. `--json` for a script or a phone. Read-only.

`conflicts` tests, with `git merge-tree` (no checkout touched), whether each branch the open items
name merges cleanly into the default branch and into each other; it prints the files in conflict
and exits 0 clean, 1 on a conflict, 2 when it could not tell (an old git, a branch not here).

A brief's `DEPENDS: <id>[, <id>]` marks the item `blocked-by <id>` in `list` and `status` while
that item is not done. `done` on an item that names a PR asks `gh pr view` first and refuses an
open or closed-unmerged PR (`--force` archives anyway); without gh, or when the call fails, it
says the merge state is unknown and archives as before.

`records` prints where this project records finished work besides the code (the tracker's labels
and closing comment, progress or status files, a diary, a published page), saved once in the main
checkout's gitignored .claude/kit.local.json `lead.records` (kitlib.records); not set, it says how
to find them. `done` prints them as the item's checklist.

`unattended` prints this repo's unattended git preferences as the brief line `UNATTENDED: push=..
rebase=.. merge=..`; not set, they are the defaults push=allow rebase=allow merge=ask
(kitlib.UNATTENDED_DEFAULTS). With arguments it saves them in the main checkout's gitignored
.claude/kit.local.json (kitlib.unattended_prefs). The line carries the effective value: an `allow`
prints as `ask`, with the file and rule to change, while a deny or ask rule in any settings scope
matches the step or no allow rule covers it (kitlib.unattended_effective). With `--proposal`, for an
owner who asks how to change that, it also prints a PROPOSAL, the settings change per file as a JSON
diff, which it never applies (kitlib.unattended_proposal). It never sets merge=allow: the owner merges,
and only he can write that value into the file. A thread cannot run `unattended` with arguments, nor
`away` or `sandbox` but their status (guard.py): those are the coordinator's.

`away on` sets permissions.denyInsteadOfPrompting in the account's settings.json (backup first, other
keys kept, a file that does not parse left alone), so a permission prompt becomes a denial while
nobody is there to answer. The owner is back when he writes: the coordinator runs `away off` at his
next message, and the next interactive session start does it too (kitlib.away_on). A value the
owner set himself is left as it is. `away status` says since when it is on.

`sandbox on` writes SANDBOX into this checkout's .claude/settings.local.json beside its other keys
(through a symlink to its target, under the kit's settings lock: kitlib.update_settings);
a sandbox block the owner wrote is left as it is. Unless git tracks or ignores the file, it gets
a line in .git/info/exclude, so the overnight runner's clean-tree check passes. `sandbox off` changes nothing and prints the exact
edit: loosening a setting is the owner's to approve (settings_guard.py asks for it), not the kit's.
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
# The kit's sandbox (Claude Code's sandbox settings): the network the usual package registries and
# GitHub need, and no read of the stores that hold credentials, the ssh keys, gh's token and
# .netrc among them. git's own network commands run outside it (excludedCommands, each with and
# without arguments), so push, fetch and pull still reach the ssh agent, gh and .netrc; a command
# inside the sandbox cannot read them. Inside it Bash runs without a prompt (autoAllowBashIfSandboxed):
# the sandbox is the check.
SANDBOX = {
    "enabled": True,
    "failIfUnavailable": False,
    "allowUnsandboxedCommands": False,
    "autoAllowBashIfSandboxed": True,
    "excludedCommands": ["git push", "git push *", "git fetch", "git fetch *", "git pull", "git pull *"],
    "network": {"allowedDomains": [
        "github.com", "*.github.com", "*.githubusercontent.com", "registry.npmjs.org", "*.npmjs.org",
        "registry.yarnpkg.com", "pypi.org", "files.pythonhosted.org", "crates.io", "index.crates.io",
        "static.crates.io", "proxy.golang.org", "sum.golang.org", "rubygems.org", "api.anthropic.com"]},
    "filesystem": {"denyRead": ["~/.aws", "~/.docker", "~/.kube", "~/.gnupg", "~/.ssh", "~/.config/gh",
                                "~/.netrc"]},
}


def sandbox(here, action):
    """(exit code, message) for `sandbox on|off|status` in the checkout at `here`."""
    path = Path(here) / ".claude" / "settings.local.json"
    settings, ok = kitlib.read_json(path)
    if not ok:
        return 1, f"{path} is not a valid JSON object; nothing was changed."
    current = settings.get("sandbox")
    if action == "status":
        if current == SANDBOX:
            return 0, f"Sandbox: on (the kit's block, in {path})."
        if isinstance(current, dict) and current.get("enabled"):
            return 0, f"Sandbox: on (your own block, in {path})."
        return 0, "Sandbox: off for this checkout (the merged settings may still turn it on: /sandbox shows them)."
    if action == "on":
        if current == SANDBOX:
            kitlib.exclude_local_settings(here)  # a block written before the kit excluded the file
            return 0, f"Sandbox is already on ({path})."
        if current is not None:
            return 0, f"{path} already has a sandbox block of yours; the kit left it as it is."
        def add(settings):
            if settings.get("sandbox") is not None:  # written meanwhile: the owner's, left as it is
                return False
            settings["sandbox"] = SANDBOX

        try:
            result = kitlib.update_settings(path, add)
        except OSError as exc:
            return 1, kitlib.write_failed(exc, f"The sandbox in {path}")
        if result != "written":
            return 1, f"{path} changed while the kit wrote it; nothing was changed. Run sandbox on again."
        kitlib.exclude_local_settings(here)  # an untracked file would stop the overnight runner
        return 0, (f"Sandbox on: wrote the kit's block to {path}. Bash runs inside it without a prompt; "
                   "git push, fetch and pull run outside it. Check it with /sandbox; add a host under "
                   "sandbox.network.allowedDomains.")
    if current is None:
        return 0, f"Sandbox is not set in {path}; nothing to remove."
    return 0, (f"Not changed: turning the sandbox off loosens a setting, which is yours to approve. The edit: "
               f"remove the \"sandbox\" key from {path}, which now holds:\n"
               + json.dumps({"sandbox": current}, indent=2))


STATUSES = ("queued", "working", "review", "needs-you", "landing", "done", "parked", "reported", "verdict")


def board_file(root):
    """The board: `<state>/lead/board.md` (kitlib.state_entry), or kit.json `lead.board`."""
    config, _ = kitlib.load_config(root)
    return kitlib.board_file(root, config)


def lead_dir(root):
    """`<state>/lead` (`.kit/lead`, or `.claude/lead` before the move) or the folder of kit.json `lead.board`."""
    return board_file(root).parent


def items_dir(root):
    return lead_dir(root) / "items"


def ensure_excluded(root):
    """The lead's folder stays out of git unless the project ignores it already: the line for the
    state entry where it is now (`/.kit/lead/`), or for the folder of a board kit.json names."""
    root = Path(root)
    lead = lead_dir(root)
    if lead == kitlib.state_entry(root, "lead"):
        kitlib.exclude_state(root, "lead")
        return
    try:
        kitlib.exclude_dir(root, lead.relative_to(root).as_posix())
    except ValueError:
        return


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


def put(root, item_id, sources):
    """Copy files into the item's out/ folder and return where they went, or None without the item.
    `.claude` is a protected path of Claude Code, so a thread's own `mkdir` or `cp` there asked the
    owner before the state moved to `.kit`; this script, run by its real path, never does
    (permission.py), in either layout. Only regular files, by
    their own name, only into out/ itself: a symlink in the way is replaced, never followed."""
    p = find(root, item_id)
    if not p:
        return None
    out = p / "out"
    if out.is_symlink():
        raise ValueError(f"{out} is a symlink")
    out.mkdir(exist_ok=True)
    placed = []
    for src in sources:
        src = Path(src)
        if src.is_symlink() or not src.is_file():
            raise ValueError(f"{src} is not a regular file")
        dest = out / src.name
        if dest.is_symlink() or dest.is_dir():
            raise ValueError(f"{dest} is in the way")
        shutil.copyfile(src, dest)
        placed.append(dest)
    log(root, item_id, "note", "out: " + ", ".join(d.name for d in placed))
    return placed


def status_of(path):
    """(last status, last note) from LOG.md; a `cost` line is a measure, not an event."""
    try:
        lines = [ln for ln in (path / "LOG.md").read_text(encoding="utf-8").splitlines()
                 if ln.startswith("- ") and not re.match(r"^- [^|]*\|\s*cost\s*(\||$)", ln)]
    except OSError:
        return "", ""
    if not lines:
        return "", ""
    parts = [x.strip() for x in lines[-1][2:].split("|", 2)]
    return (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else "")


class ItemExists(Exception):
    """`new` with the name of an item that is still open: (id, status, created)."""


def created_at(path):
    """When the item was made: the time on the first line of its LOG.md, else ""."""
    try:
        for line in (path / "LOG.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("- "):
                return line[2:].split("|", 1)[0].strip()
    except OSError:
        pass
    return ""


def new(root, name, brief="", source="lead", kind="ship", again=False):
    """Make an item: the folder, BRIEF.md headed by `ITEM: <id>`, the first LOG line, and, when
    the board exists, a `queued` row on it (so the lead and the status line see it). Returns the id.

    An open item of the same id raises ItemExists unless `again`: two coordinator sessions on one
    project (2026-11) each made the item 40 seconds apart, the second silently as `<id>-2`, and
    worked the same issue twice. A name found only among the archived (done/) items, or `again`,
    gets the next free suffix."""
    root = Path(root)
    base = items_dir(root)
    item_id = slug(name)
    if not again and item_path(root, item_id).is_dir():
        path = item_path(root, item_id)
        raise ItemExists(item_id, status_of(path)[0] or "?", created_at(path) or "?")
    base.mkdir(parents=True, exist_ok=True)
    ensure_excluded(root)
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
    board_row(root, item_id, kind, name, body, source)
    return item_id


def done_when(brief):
    """The first `DONE WHEN` line of a brief, without its label, else "see BRIEF.md"."""
    m = re.search(r"^\s*(?:[-*]\s*)?DONE WHEN:?\s*(.+?)\s*$", brief or "", re.M | re.I)
    return m.group(1) if m else "see BRIEF.md"


def board_row(root, item_id, kind, name, brief, source):
    """Append the item's row to the board in the lead's row format, when the board exists."""
    board = board_file(root)
    if not board.is_file():
        return False
    row = f"{item_id} | {kind} | {' '.join(str(name).split())} | DONE WHEN {done_when(brief)} | queued | agent - | - | from {source}\n"
    try:
        text = board.read_text(encoding="utf-8")
        with open(board, "a", encoding="utf-8") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + row)
    except OSError:
        return False
    return True


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
    n = 2
    while target.exists():  # an earlier item of the same id is kept: done/<id>-2, -3, ...
        target = item_path(root, f"{item_id}-{n}", done=True)
        n += 1
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
                     if ln.strip() and not ln.startswith(("ITEM:", "KIND:", "DEPENDS:"))]
            head = lines[0][:100] if lines else ""
        except OSError:
            pass
        rows.append({"id": p.name, "status": st, "note": note, "brief": head, "path": str(p),
                     "blocked_by": [] if archived else blocked_by(root, p)})
    return rows


DEPENDS_LINE = re.compile(r"^\s*(?:[-*]\s*)?DEPENDS:\s*(.+?)\s*$", re.M | re.I)


def depends(path):
    """The ids a brief's `DEPENDS: <id>[, <id>]` lines name."""
    try:
        text = (path / "BRIEF.md").read_text(encoding="utf-8")
    except OSError:
        return []
    found = []
    for m in DEPENDS_LINE.finditer(text):
        for dep in re.split(r"[,\s]+", m.group(1)):
            dep = dep.strip("`").lower()
            if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", dep) and dep not in found and dep not in ("none", "-"):
                found.append(dep)
    return found


def blocked_by(root, path):
    """The dependencies of an item that are not done yet: archived under done/, or an open item
    whose last event is `done`. One that does not exist anywhere blocks too, since nothing says it
    is done."""
    waiting = []
    for dep in depends(path):
        if item_path(root, dep, done=True).is_dir():
            continue
        open_dep = item_path(root, dep)
        if open_dep.is_dir() and status_of(open_dep)[0] == "done":
            continue
        waiting.append(dep)
    return waiting


LOG_LINE = re.compile(r"^- (\S+) \| ([^|]+?)\s*(?:\| (.*))?$")
AGENT = re.compile(r"\bagent[ =]([A-Za-z0-9][\w-]*)")
PR_REF = re.compile(r"(https://\S+/pull/\d+)|\bPR\s*#(\d+)|/pull/(\d+)")
BRANCH_NOTE = re.compile(r"\bbranch:?\s+`?([A-Za-z0-9][\w./-]*[\w-])`?", re.I)
BRANCH_FIELD = re.compile(r"^\W*BRANCH(?:\s*/\s*PR)?:\s*`?([A-Za-z0-9][\w./-]*[\w-])`?", re.M | re.I)
COST_KEYS = ("in", "out", "cache_read", "cache_write", "tools", "minutes")
NOT_A_BRANCH = {"none", "n/a", "na", "pr", "local", "worktree", "branch", "unknown", "main", "master"}


def log_lines(path):
    """[(timestamp, status, note)] of an item's LOG.md, oldest first."""
    try:
        text = (path / "LOG.md").read_text(encoding="utf-8")
    except OSError:
        return []
    return [(m.group(1), m.group(2).strip(), (m.group(3) or "").strip())
            for m in map(LOG_LINE.match, text.splitlines()) if m]


def age_minutes(stamp, at=None):
    import calendar
    try:
        then = calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return None
    return max(0, int(((at if at is not None else time.time()) - then) // 60))


def costs(lines):
    """The summed `cost` lines. Each line is a thread's total so far (a resumed thread's transcript
    grows), so only the latest line per agent counts; lines that name no agent each count."""
    latest, total = {}, dict.fromkeys(COST_KEYS, 0)
    for n, (_, st, note) in enumerate(lines):
        if st != "cost":
            continue
        fields = dict(re.findall(r"(\w+)=(\S+)", note))
        latest[fields.get("agent") or f"#{n}"] = fields
    if not latest:
        return None
    for fields in latest.values():
        for k in COST_KEYS:
            try:
                total[k] += float(fields.get(k, 0)) if k == "minutes" else int(fields.get(k, 0))
            except ValueError:
                pass
    total["minutes"] = round(total["minutes"], 1)
    total["threads"] = len(latest)
    return total


def refs(path, lines):
    """(agent id, branch, PR) an item's LOG or REPORT.md names, the latest first; "" when none."""
    notes = [note for _, st, note in reversed(lines) if st != "cost"]
    try:
        report = (path / "REPORT.md").read_text(encoding="utf-8")
    except OSError:
        report = ""
    agent = next((m.group(1) for m in map(AGENT.search, notes) if m and m.group(1) != "-"), "")
    branch = ""
    for m in [BRANCH_NOTE.search(n) for n in notes] + [BRANCH_FIELD.search(report)]:
        if m and m.group(1).lower() not in NOT_A_BRANCH:
            branch = m.group(1)
            break
    pr = ""
    for text in notes + [report]:
        m = PR_REF.search(text)
        if m:
            pr = m.group(1) or "#" + (m.group(2) or m.group(3))
            break
    return agent, branch, pr


def needs_you(root, known=()):
    """[{"id", "question"}] from the board's NEEDS YOU line, or None without a board. An entry starts
    where `<id>:` follows a `;`, for an id the items or the board rows know (any id-like word
    when none are known), so a `;` inside a question stays in it."""
    try:
        text = board_file(root).read_text(encoding="utf-8")
    except OSError:
        return None
    line = next((ln.strip() for ln in text.splitlines() if re.match(r"^\s*NEEDS YOU:", ln, re.I)), "")
    rest = re.sub(r"^NEEDS YOU:\s*", "", line, flags=re.I).strip()
    if not rest or rest.lower() in ("none", "-", "nothing"):
        return []
    ids = set(known) | {ln.split("|")[0].strip().lower() for ln in text.splitlines()
                        if "|" in ln and not re.match(r"^\s*(SHIP|RULES|NEEDS YOU):", ln, re.I)}
    ids.discard("")
    start = ("(?:" + "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True)) + ")") if ids else r"[A-Za-z0-9][\w.-]*"
    entries = re.split(r";\s*(?=(?i:" + start + r")\s*:)", rest)
    out = []
    for entry in (e.strip() for e in entries):
        m = re.match(r"^([A-Za-z0-9][\w.-]*)\s*:\s*(.*)$", entry, re.S)
        if m:
            out.append({"id": m.group(1), "question": m.group(2).strip()})
        elif entry:
            out.append({"id": "", "question": entry})
    return out


def snapshot(root, at=None):
    """One snapshot of the open items, built from their folders (not from board.md)."""
    rows = []
    for item in list_items(root):
        p = Path(item["path"])
        lines = log_lines(p)
        events = [ln for ln in lines if ln[1] != "cost"]
        last = events[-1] if events else ("", "", "")
        agent, branch, pr = refs(p, lines)
        kind = ""
        try:
            m = re.search(r"^KIND:\s*(\S+)", (p / "BRIEF.md").read_text(encoding="utf-8"), re.M)
            kind = m.group(1) if m else ""
        except OSError:
            pass
        rows.append({"id": item["id"], "kind": kind, "status": item["status"], "last_event": last[1],
                     "last_at": last[0], "age_minutes": age_minutes(last[0], at), "note": item["note"],
                     "agent": agent, "branch": branch, "pr": pr, "cost": costs(lines),
                     "blocked_by": item["blocked_by"], "brief": item["brief"]})
    counts = {}
    for r in rows:
        counts[r["status"] or "?"] = counts.get(r["status"] or "?", 0) + 1
    return {"at": now(), "items": rows, "counts": counts, "questions": needs_you(root, [r["id"] for r in rows]),
            "overnight": overnight_ended(root)}


def overnight_ended(root):
    """The overnight runs that ended unseen, read only: the next interactive start says them."""
    try:
        return kitlib.overnight_news(root)[0]
    except Exception:  # status goes on without them; the session start says why
        return []


def print_status(snap):
    rows = snap["items"]
    if not rows:
        print("items: none open")
    for r in rows:
        cost = r["cost"]
        spent = (f"out={cost['out']} in={cost['in'] + cost['cache_read'] + cost['cache_write']} {cost['minutes']}m"
                 if cost else "-")
        age = f"{r['age_minutes']}m ago" if r["age_minutes"] is not None else "?"
        where = " ".join(x for x in (r["branch"], r["pr"]) if x) or "-"
        state = (r["status"] or "?") + (f" blocked-by {', '.join(r['blocked_by'])}" if r["blocked_by"] else "")
        print(f"{r['id']} | {r['kind'] or '-'} | {state} | {age} | {where} | agent {r['agent'] or '-'} | {spent} | {r['note']}")
    print("counts: " + (", ".join(f"{k} {v}" for k, v in sorted(snap["counts"].items())) or "none"))
    for run in snap.get("overnight") or ():
        print(kitlib.overnight_news_line(run).replace("kit: ", "", 1) + ": tell the user")
    if snap["questions"]:
        print("NEEDS YOU:")
        for q in snap["questions"]:
            print(f"- {q['id'] + ': ' if q['id'] else ''}{q['question']}")


def branch_ref(root, name):
    """The commit-ish for a branch an item names: the local branch, else origin's; None when neither."""
    for ref in (name, f"origin/{name}"):
        if kitlib.git_run(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")[0] == 0:
            return ref
    return None


def conflicts(root, ids=None):
    """Which open items' branches conflict with the default branch and with each other, from
    `git merge-tree` (kitlib.merge_tree). Returns (exit code, lines): 0 all clean, 1 a conflict,
    2 a merge that could not be tested and none that conflicts."""
    open_items = {r["id"]: Path(r["path"]) for r in list_items(root)}
    lines, unknown, found = [], False, False
    if ids:
        missing = [i for i in ids if i not in open_items]
        if missing:
            return 2, [f"items: no open item {', '.join(missing)}"]
        open_items = {i: open_items[i] for i in ids}
    branches = {}
    for item_id, p in open_items.items():
        _, branch, _ = refs(p, log_lines(p))
        if branch:
            branches[item_id] = branch
        elif ids:
            lines.append(f"{item_id}: names no branch in its LOG or REPORT.md")
            unknown = True
    if not branches:
        return (2 if unknown else 0), lines + ["conflicts: no open item names a branch"]
    base = kitlib.git_base(root)
    resolved = {}
    for item_id, branch in branches.items():
        ref = branch_ref(root, branch)
        if ref:
            resolved[item_id] = ref
        else:
            lines.append(f"unknown  {item_id} ({branch}): no such branch here")
            unknown = True

    def report(label, state, files, reason):
        nonlocal unknown, found
        if state == "conflict":
            found = True
            lines.append(f"conflict {label}: {', '.join(files) or '(no file named)'}")
        elif state == "unknown":
            unknown = True
            lines.append(f"unknown  {label}: {reason}")
        else:
            lines.append(f"clean    {label}")

    if base:
        for item_id, ref in resolved.items():
            report(f"{item_id} ({ref}) with {base}", *kitlib.merge_tree(root, base, ref))
    else:
        unknown = True
        lines.append("unknown  default branch: no origin/HEAD, main or master here")
    ordered = list(resolved.items())
    for i, (a, ra) in enumerate(ordered):
        for b, rb in ordered[i + 1:]:
            report(f"{a} ({ra}) with {b} ({rb})", *kitlib.merge_tree(root, ra, rb))
    return (1 if found else 2 if unknown else 0), lines


def merge_state(root, pr):
    """("merged" | "open" | "closed" | "unknown", detail) for the item's PR from `gh pr view`; unknown
    when gh is missing, not logged in or the call fails, never a guess."""
    gh = shutil.which("gh")
    if not gh:
        return "unknown", "gh is not installed"
    import subprocess
    target = pr.lstrip("#")
    try:
        out = subprocess.run([gh, "pr", "view", target, "--json", "state,mergedAt"], cwd=str(root),
                             capture_output=True, text=True, timeout=30, env=kitlib.hermetic_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "unknown", f"gh failed: {exc}"
    if out.returncode != 0:
        return "unknown", "gh: " + ((out.stderr or out.stdout).strip().splitlines() or [f"exit {out.returncode}"])[0]
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return "unknown", "gh gave no JSON"
    state = str(data.get("state") or "").upper() if isinstance(data, dict) else ""
    if state == "MERGED" and data.get("mergedAt"):
        return "merged", ""
    if state in ("OPEN", "CLOSED"):
        return state.lower(), ""
    return "unknown", f"gh said state {state or 'nothing'}"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    root = kitlib.project_root({"cwd": str(Path.cwd())})
    home = kitlib.main_checkout(root)
    if home and Path(home) != Path(root) and not items_dir(root).is_dir():
        root = Path(home)  # run from a thread's worktree: the items are the main checkout's
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
        again = "--again" in rest
        rest = [a for a in rest if a != "--again"]
        if not rest:
            print("items: new needs a name", file=sys.stderr)
            return 2
        try:
            item_id = new(root, " ".join(rest), brief, source, kind, again)
        except ItemExists as exc:
            item_id, status, created = exc.args
            print(f"items: {item_id} is already an open item ({status}, created {created}): another session may "
                  f"be working on it. Read its LOG.md ({item_path(root, item_id)}) first; `new --again` makes "
                  f"a second, numbered item on purpose.", file=sys.stderr)
            return 1
        print(f"{item_id}\t{item_path(root, item_id)}")
        return 0
    if cmd == "list":
        status = opt("--status")
        rows = list_items(root, status)
        for r in rows:
            blocked = f" | blocked-by {', '.join(r['blocked_by'])}" if r["blocked_by"] else ""
            print(f"{r['id']} | {r['status'] or '?'} | {r['brief']} | {r['note']}{blocked}")
        if not rows:
            print("items: none" + (f" with status {status}" if status else ""))
        return 0
    if cmd == "status":
        snap = snapshot(root)
        if "--json" in rest:
            print(json.dumps(snap, indent=2))
        else:
            print_status(snap)
        return 0
    if cmd == "conflicts":
        code, lines = conflicts(root, [a.lower() for a in rest])
        print("\n".join(lines))
        return code
    if cmd == "unattended":
        changes, want_proposal = {}, "--proposal" in rest
        for arg in [a for a in rest if a != "--proposal"]:
            step, _, value = arg.partition("=")
            if step not in kitlib.UNATTENDED_STEPS or value not in ("ask", "allow"):
                print(f"items: unattended takes push=, rebase=, merge= each ask or allow, not {arg!r}", file=sys.stderr)
                return 2
            if step == "merge" and value == "allow":
                print("items: merge=allow is not the kit's to set: the owner merges. To let unattended runs merge, "
                      f"set \"lead\": {{\"unattended\": {{\"merge\": \"allow\"}}}} in {kitlib.unattended_prefs(root)[2]} "
                      "yourself.", file=sys.stderr)
                return 2
            changes[step] = value
        if changes:
            try:
                kitlib.save_unattended(root, changes)
            except ValueError as exc:
                print(f"items: {exc}", file=sys.stderr)
                return 1
            except OSError as exc:
                print(kitlib.write_failed(exc, f"UNATTENDED in {kitlib.unattended_prefs(root)[2]}"), file=sys.stderr)
                return 1
        _, is_set, path = kitlib.unattended_prefs(root)
        effective, notes = kitlib.unattended_effective(root)
        line = "UNATTENDED: " + " ".join(f"{k}={effective[k]}" for k in kitlib.UNATTENDED_STEPS)
        print(line + (f"  (from {path})" if is_set else "  (not set for this repo: the defaults, push and rebase allowed, merge asked)"))
        for k in kitlib.UNATTENDED_STEPS:
            if k in notes:
                print(notes[k])
        proposal = kitlib.unattended_proposal(root) if want_proposal else []
        if want_proposal and not proposal:
            print("PROPOSAL: none (no rule to change, or a settings file above does not parse).")
        if proposal:
            print("PROPOSAL, not applied: this command never writes settings. Only when the owner asks, the "
                  "coordinator shows this diff and makes it with one Edit per file, which Claude Code asks the owner "
                  "to approve; the owner can also edit the file by hand.")
            for p in proposal:
                what = [f'remove "{r}" from permissions.{b}' for b, r in p["remove"]]
                what += [f'add "{r}" to permissions.allow' for r in p["add"]]
                print(f"- {p['file']}" + (" (committed: the change reaches everyone who works in this repo)"
                                          if p["committed"] else "") + ": " + "; ".join(what))
                for r in p["broad"]:
                    print(f'  "{r}" also asks for other commands: removing it drops that prompt too; '
                          f"a narrower rule may be what the owner wants")
                print(p["diff"])
        return 0
    if cmd in ("away", "sandbox"):
        action = rest[0] if rest else "status"
        if action not in ("on", "off", "status"):
            print(f"items: {cmd} takes on, off or status, not {action!r}", file=sys.stderr)
            return 2
        if cmd == "sandbox":
            code, message = sandbox(kitlib.project_root({"cwd": str(Path.cwd())}), action)
        elif action == "status":
            state, path = kitlib.away_state()
            code, message = (1 if state == "broken" else 0), {
                "kit": f"Away: on since {kitlib.away_since()} (set by the kit; the coordinator runs "
                       "`I away off` at the user's next message, and the next interactive session start turns it off).",
                "own": f"Away: on (you set it in {path}).", "off": "Away: off.",
                "broken": f"{path} is not a valid JSON object."}[state]
        else:
            try:
                code, message = (kitlib.away_on if action == "on" else kitlib.away_off)()
            except OSError as exc:  # kitlib.SettingsBusy, or a config dir that cannot be written
                code, message = 1, kitlib.write_failed(exc, f"Away (permissions.{kitlib.AWAY_KEY} in {kitlib.user_settings()})")
        print(message)
        return code
    if cmd == "records":
        if rest[:1] == ["set"]:
            if not rest[1:]:
                print('items: records set needs the places, each one quoted ("<place>: <what to update>")', file=sys.stderr)
                return 2
            try:
                kitlib.save_records(root, rest[1:])
            except ValueError as exc:
                print(f"items: {exc}", file=sys.stderr)
                return 1
        elif rest:
            print(f"items: records takes nothing or `set <place> ...`, not {rest[0]!r}", file=sys.stderr)
            return 2
        places, path = kitlib.records(root)
        if places:
            print(f"RECORDS (from {path}):")
            print("\n".join(f"- {p}" for p in places))
        else:
            print("RECORDS: not set for this repo. Read its guidance (AGENTS.md, CLAUDE.md, CONTRIBUTING, docs/) for "
                  "where finished work is recorded besides the code: the tracker (issue status, labels, closing "
                  "comment, a project board), progress or status files, a changelog or diary, a published page. "
                  "Confirm the list with the user once, then save it: items.py records set \"<place>: <what>\" ...")
        return 0
    if cmd == "put":
        if len(rest) < 2:
            print("items: put needs an item id and at least one file", file=sys.stderr)
            return 2
        try:
            placed = put(root, rest[0], rest[1:])
        except (ValueError, OSError) as exc:
            print(f"items: {exc}", file=sys.stderr)
            return 1
        if placed is None:
            print(f"items: no item {rest[0]}", file=sys.stderr)
            return 1
        print("\n".join(str(d) for d in placed))
        return 0
    if cmd in ("log", "report", "verdict", "done", "show", "path"):
        force = cmd == "done" and "--force" in rest
        if force:
            rest.remove("--force")
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
            p = item_path(root, item_id)
            pr = refs(p, log_lines(p))[2] if p.is_dir() else ""
            if pr:
                state, detail = merge_state(root, pr)
                if state in ("open", "closed") and not force:
                    print(f"items: {item_id} not archived: PR {pr} is {state}"
                          f"{', not merged' if state == 'closed' else ''}. `done {item_id} --force` archives it anyway.",
                          file=sys.stderr)
                    return 1
                print(f"items: PR {pr} " + ("merged." if state == "merged" else
                                            f"is {state}, archived with --force." if state in ("open", "closed") else
                                            f"merge state unknown ({detail})."))
            ok = done(root, item_id)
            places, _ = kitlib.records(root)
            if ok and places:
                print(f"items: {item_id} done. Its records, each updated before you tell the user it is done:")
                print("\n".join(f"- [ ] {p}" for p in places))
            elif ok:
                print(f"items: {item_id} done. This repo's record places are not set: `items.py records`.")
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
