#!/usr/bin/env python3
"""Move a project's kit working state from `.claude/` to `.kit/`, and back.

    python3 migrate_state.py status  [--root DIR]
    python3 migrate_state.py migrate [--root DIR] [--dry-run] [--force]
    python3 migrate_state.py undo    [--root DIR] [--dry-run] [--force]

Why: Claude Code treats `.claude` as a protected path (only `.claude/worktrees/` is exempt), so
a background thread that logged on the board or wrote evidence there stalled on a write prompt
nobody was watching. The kit's state now lives in `.kit/`; this moves an older project's.

What moves (kitlib.STATE_NAMES, an allowlist): lead/, evidence/ and agent-memory/kit-verifier/
of the main checkout, and overnight/ of the main checkout and of every linked worktree (a run
lives in the checkout it ran in). Nothing else in `.claude/` is touched: kit.json and
kit.local.json stay, because permission.py lets kit.json's commands run unasked and the
protected path is what keeps a thread from rewriting them; so do settings, skills, agents,
worktrees, loop.md and other agents' memory.

How:
  - one run at a time: a lock file in the repository's common git dir, holding its pid;
  - refuses (exit 2) while a thread or run is at work: an item whose LOG.md ends in `working`
    or `landing`, a board row in one of those statuses, an overnight run with no stop_reason
    and no end-state.json. `--force` overrides (a thread that died leaves `working` behind);
  - an entry with files tracked in git stays where it is and the `git mv` to run is printed
    (moving it is a commit the owner makes); kitlib.state_entry keeps finding it in `.claude/`;
  - an entry present in both places is a conflict: nothing is overwritten (exit 3);
  - the exclude lines change first (`/.claude/lead/` becomes `/.kit/lead/`), so a folder is
    never visible to git even if the run dies half-way;
  - the main checkout's entries are renamed into `.kit.migrating/`, the manifest is written
    there, then the folder becomes `.kit` in one rename, so the layout flips once. A copy, then
    delete, across filesystems. A run that died half-way is finished by the next one;
  - `.claude/kit-state-moved.txt` says where things went, and `.kit/migration.json` records
    what was done, which `undo` reads;
  - run twice, the second run finds nothing to do (exit 0).
Exit: 0 done or nothing to do, 1 error, 2 refused (at work, or locked), 3 conflict.
Standard library only.
"""

import argparse
import errno
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import items  # noqa: E402
import kitlib  # noqa: E402

STATE, LEGACY = kitlib.STATE_DIR, kitlib.LEGACY_STATE_DIR
STAGING = ".kit.migrating"
MANIFEST = "migration.json"
NOTE = "kit-state-moved.txt"
BUSY = ("working", "landing")


class Refused(Exception):
    def __init__(self, code, lines):
        super().__init__("\n".join(lines))
        self.code, self.lines = code, lines


def checkouts(main):
    """The main checkout first, then each linked worktree that still exists."""
    found = [Path(main)]
    for line in kitlib.git_out(main, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            p = Path(line[9:].strip())
            if p.is_dir() and p.resolve() != Path(main).resolve():
                found.append(p)
    return found


def names_for(checkout, main):
    return kitlib.STATE_NAMES if checkout == main else kitlib.PER_CHECKOUT_STATE


def tracked(checkout, rel):
    return bool(kitlib.git_out(checkout, "ls-files", "--", rel))


def last_status(item):
    return items.status_of(item)[0]


def board_status(row):
    """(id, status) of a board row, or None; a Markdown table row has outer pipes."""
    row = row.strip()
    if "|" not in row:
        return None
    cells = [c.strip() for c in row.strip("|").split("|")]
    return (cells[0], cells[4].lower()) if len(cells) >= 5 else None


def busy(main):
    """Why the state must not move now: one line per thread or run still at work."""
    why, boards = [], set()
    for folder in (LEGACY, STATE):
        lead = Path(main) / folder / "lead"
        boards.add(lead / "board.md")
        items = lead / "items"
        for item in sorted(items.iterdir()) if items.is_dir() else []:
            if item.is_dir() and item.name != "done" and last_status(item) in BUSY:
                why.append(f"item {item.name} is {last_status(item)} ({item / 'LOG.md'})")
    config, _ = kitlib.load_config(main)
    if config:  # a board kept elsewhere (kit.json lead.board)
        boards.add(kitlib.board_file(main, config))
    for board in sorted(boards):
        try:
            rows = board.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for row in rows:
            got = board_status(row)
            if got and got[1] in BUSY and not any(f"item {got[0]} " in w for w in why):
                why.append(f"board row {got[0]} is {got[1]} ({board})")
    for checkout in checkouts(main):
        for folder in (LEGACY, STATE):
            runs = checkout / folder / "overnight"
            for run in sorted(runs.iterdir()) if runs.is_dir() else []:
                if not run.is_dir() or (run / "end-state.json").exists():
                    continue
                try:
                    state = json.loads((run / "state.json").read_text(encoding="utf-8"))
                except Exception:
                    state = {}
                if not state.get("stop_reason"):
                    why.append(f"overnight run {run.name} has not stopped ({run})")
    return why


def move(src, dst):
    """Rename; across filesystems copy, then delete the source only once the copy is whole."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
        return "renamed"
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    tmp = dst.with_name(dst.name + ".copying")
    if tmp.exists():
        shutil.rmtree(tmp) if tmp.is_dir() else tmp.unlink()
    shutil.copytree(src, tmp, symlinks=True) if src.is_dir() else shutil.copy2(src, tmp)
    os.rename(tmp, dst)
    shutil.rmtree(src) if src.is_dir() else src.unlink()
    return "copied"


def prune(folder, stop):
    """Remove `folder` and its parents while empty, never `stop` or above."""
    folder, stop = Path(folder), Path(stop)
    while folder != stop and stop in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def exclude_file(main):
    info = kitlib.git_out(main, "rev-parse", "--git-path", "info/exclude")
    if not info:
        return None
    return Path(info) if Path(info).is_absolute() else Path(main) / info


def _write_exclude(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".kit-tmp")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(tmp, path)


def rewrite_exclude(main, pairs, extra=(), dry=False):
    """Replace each old line with its new one in place (the old one with or without its
    slashes); add the new line when the old one was not there; add `extra`. Other lines stay.
    Returns the ops, [{"old", "new"}] and [{"add"}], for revert_exclude."""
    path = exclude_file(main)
    if not path:
        return []
    lines = (path.read_text(encoding="utf-8") if path.exists() else "").splitlines()
    ops = []
    for old, new in pairs:
        forms = {old, old.lstrip("/"), old.rstrip("/"), old.strip("/")}
        hits = [i for i, line in enumerate(lines) if line.strip() in forms]
        if hits and new not in lines:
            ops.append({"old": lines[hits[0]], "new": new})
            lines[hits[0]] = new
        elif new not in lines:
            ops.append({"add": new})
            lines.append(new)
    for line in extra:
        if line not in lines:
            ops.append({"add": line})
            lines.append(line)
    if ops and not dry:
        _write_exclude(path, lines)
    return ops


def revert_exclude(main, ops):
    """Undo rewrite_exclude's ops, newest first; a line someone changed since is left alone."""
    path = exclude_file(main)
    if not path or not path.exists():
        return 0
    lines, n = path.read_text(encoding="utf-8").splitlines(), 0
    for op in reversed(ops):
        line = op.get("new") or op.get("add")
        if line not in lines:
            continue
        i = lines.index(line)
        lines[i:i + 1] = [op["old"]] if "old" in op else []
        n += 1
    if n:
        _write_exclude(path, lines)
    return n


class Lock:
    """One migration at a time. A lock whose process is gone (a run killed mid-move) is taken
    over, so the next run can finish that move."""

    def __init__(self, main):
        common = kitlib.git_out(main, "rev-parse", "--path-format=absolute", "--git-common-dir")
        self.path = Path(common or Path(main) / ".git") / "kit-migrate.lock"

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    os.kill(int(self.path.read_text().strip() or 0), 0)
                except (ValueError, ProcessLookupError, OSError):
                    self.path.unlink(missing_ok=True)
                    continue
                break
        raise Refused(2, [f"another migration is running ({self.path})"])

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def plan(main, src_dir, dst_dir, staged=False):
    """(moves, skipped, conflicts); each move is (checkout, name, from, via, final)."""
    moves, skipped, conflicts = [], [], []
    for checkout in checkouts(main):
        for name in names_for(checkout, main):
            src, final = checkout / src_dir / name, checkout / dst_dir / name
            if not (src.exists() or src.is_symlink()):
                continue
            if src.is_symlink():
                skipped.append((src, "a symlink: move what it points to by hand"))
            elif tracked(checkout, f"{src_dir}/{name}"):
                skipped.append((src, f"tracked in git: run `git mv {src_dir}/{name} {dst_dir}/{name}` and commit"))
            elif final.exists() or (staged and checkout == main and (checkout / STAGING / name).exists()):
                conflicts.append((src, final))
            else:
                via = checkout / STAGING / name if staged and checkout == main and not (checkout / dst_dir).exists() \
                    else final
                moves.append((checkout, name, src, via, final))
    return moves, skipped, conflicts


def read_manifest(folder):
    try:
        return json.loads((Path(folder) / MANIFEST).read_text(encoding="utf-8"))
    except Exception:
        return None


def migrate(main, dry=False, force=False, out=print):
    main = Path(main)
    why = busy(main)
    if why and not force:
        raise Refused(2, ["not moving: work is in progress. Wait for it, or --force if it is gone:"]
                      + [f"  - {w}" for w in why])
    staging = main / STAGING
    resumed = staging.is_dir() and not (main / STATE).exists()
    moves, skipped, conflicts = plan(main, LEGACY, STATE, staged=True)
    if conflicts:
        raise Refused(3, ["not moving: these exist in both places, merge them by hand first:"]
                      + [f"  - {a} and {b}" for a, b in conflicts])
    for src, reason in skipped:
        out(f"left in place: {src} ({reason})")
    if not moves and not resumed:
        out("nothing to move" + (f": the state is in {STATE}/" if (main / STATE).is_dir() else ""))
        return 0
    for _, name, src, _, final in moves:
        out(f"{'would move' if dry else 'move'} {src} -> {final}")
    present = [n for n in kitlib.STATE_NAMES if any(m[1] == n for m in moves)
               or (main / STATE / n).exists() or (staging / n).exists()]
    # the kit's old line for the whole folder, `/.claude/agent-memory/`, stays: other agents' memory is there
    pairs = [(f"/{LEGACY}/{n}/", f"/{STATE}/{n}/") for n in present]
    extra = [f"/{LEGACY}/{NOTE}", f"/{STATE}/{MANIFEST}", f"/{STAGING}/"]
    if dry:
        for op in rewrite_exclude(main, pairs, extra, dry=True):
            out("would change .git/info/exclude: " + (f"{op['old']} -> {op['new']}" if "old" in op else f"+ {op['add']}"))
        return 0
    changes = rewrite_exclude(main, pairs, extra)  # first: nothing moved is ever visible to git
    done = []
    for checkout, name, src, via, final in moves:
        how = move(src, via)
        prune(src.parent, checkout / LEGACY)
        done.append({"checkout": str(checkout), "name": name, "from": str(src), "to": str(final), "how": how})
    if resumed:  # what an interrupted run had already staged
        done += [{"checkout": str(main), "name": n, "from": str(main / LEGACY / n), "to": str(main / STATE / n),
                  "how": "finished"} for n in kitlib.STATE_NAMES
                 if (staging / n).exists() and not any(d["name"] == n and d["checkout"] == str(main) for d in done)]
    target = staging if staging.is_dir() and not (main / STATE).exists() else main / STATE
    target.mkdir(exist_ok=True)
    record = read_manifest(main / STATE) or read_manifest(staging) or {"version": 1, "runs": []}
    record["runs"].append({"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "moved": done, "exclude": changes})
    (target / MANIFEST).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if staging.is_dir():
        if (main / STATE).exists():  # made meanwhile: fold the staged entries in
            for entry in sorted(p for p in staging.rglob("*") if p.is_file() or p.is_symlink()):
                dst = main / STATE / entry.relative_to(staging)
                if not dst.exists():
                    move(entry, dst)
            shutil.rmtree(staging)
        else:
            os.rename(staging, main / STATE)  # the flip: kitlib.state_dir_name answers .kit from here on
    for checkout in {Path(d["checkout"]) for d in done}:
        names = ", ".join(d["name"] for d in done if d["checkout"] == str(checkout))
        (checkout / LEGACY).mkdir(exist_ok=True)
        (checkout / LEGACY / NOTE).write_text(
            f"kit: this checkout's working state ({names}) moved to {checkout / STATE}/ on "
            f"{time.strftime('%Y-%m-%d')}, out of the folder Claude Code protects.\n"
            f"undo: python3 {Path(__file__).resolve()} undo --root {main}\n", encoding="utf-8")
    out(f"moved {len(done)} entr{'y' if len(done) == 1 else 'ies'} to {STATE}/; .git/info/exclude: "
        f"{len(changes)} line(s) changed; undo with `undo`")
    try:
        if f"{LEGACY}/lead" in (main / ".gitignore").read_text(encoding="utf-8") or \
                f"{LEGACY}/evidence" in (main / ".gitignore").read_text(encoding="utf-8"):
            out(f"note: .gitignore names {LEGACY}/ state paths; add the {STATE}/ ones there if the team shares it")
    except OSError:
        pass
    return 0


def undo(main, dry=False, force=False, out=print):
    main = Path(main)
    manifest = read_manifest(main / STATE)
    if not manifest:
        if (main / STATE).is_dir():
            raise Refused(1, [f"no {STATE}/{MANIFEST}: this project was not moved by this command"])
        out("nothing to undo")
        return 0
    why = busy(main)
    if why and not force:
        raise Refused(2, ["not moving back: work is in progress:"] + [f"  - {w}" for w in why])
    moves, skipped, conflicts = plan(main, STATE, LEGACY)
    if conflicts:
        raise Refused(3, ["not moving back: these exist in both places:"] + [f"  - {a} and {b}" for a, b in conflicts])
    for src, reason in skipped:
        out(f"left in place: {src} ({reason})")
    for _, name, src, _, final in moves:
        out(f"{'would move' if dry else 'move'} {src} -> {final}")
    if dry:
        return 0
    for checkout, name, src, _, final in moves:
        move(src, final)
        prune(src.parent, checkout)
    changes = sum(revert_exclude(main, run.get("exclude") or []) for run in reversed(manifest.get("runs", [])))
    for checkout in checkouts(main):
        (checkout / LEGACY / NOTE).unlink(missing_ok=True)
        if checkout != main:
            prune(checkout / STATE, checkout)
    (main / STATE / MANIFEST).unlink(missing_ok=True)
    prune(main / STATE, main)
    left = sorted(p.name for p in (main / STATE).iterdir()) if (main / STATE).is_dir() else []
    out(f"moved {len(moves)} entr{'y' if len(moves) == 1 else 'ies'} back to {LEGACY}/; .git/info/exclude: "
        f"{changes} line(s) restored" + (f"; {STATE}/ still holds {', '.join(left)}" if left else ""))
    return 0


def status(main, out=print):
    main = Path(main)
    out(f"main checkout: {main}")
    out(f"state folder:  {kitlib.state_dir(main)}" + ("  (moved by this command)" if read_manifest(main / STATE) else ""))
    for checkout in checkouts(main):
        for name in names_for(checkout, main):
            for folder in (STATE, LEGACY):
                if (checkout / folder / name).exists():
                    out(f"  {checkout / folder / name}")
    for w in busy(main):
        out(f"  at work: {w}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("migrate", "undo", "status"))
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="move even if work looks in progress")
    args = ap.parse_args(argv)
    root = kitlib.main_checkout(args.root)
    if not root:
        print(f"kit migrate: {args.root} is not in a git repository", file=sys.stderr)
        return 1
    try:
        if args.command == "status":
            return status(root)
        with Lock(root):
            if args.command == "migrate":
                return migrate(root, args.dry_run, args.force)
            return undo(root, args.dry_run, args.force)
    except Refused as exc:
        print("kit migrate: " + "\n".join(exc.lines), file=sys.stderr)
        return exc.code
    except OSError as exc:
        print(f"kit migrate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
