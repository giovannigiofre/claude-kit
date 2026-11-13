#!/usr/bin/env python3
"""Move a project's kit working state from `.claude/` to `.kit/`, and back.

    python3 migrate_state.py status  [--root DIR]
    python3 migrate_state.py migrate [--root DIR] [--dry-run] [--force] [--again]
    python3 migrate_state.py undo    [--root DIR] [--dry-run] [--force]

Why: Claude Code treats `.claude` as a protected path (only `.claude/worktrees/` is exempt), so
a background thread that logged on the board or wrote evidence there stalled on a write prompt
nobody was watching. The kit's state now lives in `.kit/`; this moves an older project's.

What moves (kitlib.STATE_NAMES, an allowlist): lead/, evidence/, overnight/ and
agent-memory/kit-verifier/ of the main checkout, and evidence/ and overnight/ of every linked
worktree (kitlib.PER_CHECKOUT_STATE: a run and a thread's proof live in the checkout they were
made in). Nothing else in `.claude/` is touched: kit.json and kit.local.json stay, because
permission.py lets kit.json's commands run unasked and the protected path is what keeps a thread
from rewriting them; so do settings, skills, agents, worktrees, loop.md and other agents' memory.

How, one entry at a time, so a run that dies half-way leaves nothing unreadable:
  - refuses (exit 2) while a thread or run is at work: an item whose LOG.md ends in `working`
    or `landing`, a board row in one of those statuses, an overnight run with no stop_reason
    and no end-state.json. `--force` overrides (a thread that died leaves `working` behind);
  - the exclude lines are computed once and added in one call (kitlib.add_exclude_lines, which
    locks, appends and never removes a line) before anything moves: `/.kit/<entry>/` and the
    old `/.claude/<entry>/`, so a leftover or later-made `.claude/evidence/` stays out of
    `git status`, where `git add -A` or the overnight runner's `git clean -fd` would catch it.
    An entry tracked in git gets no line in either layout. An entry still to move whose line
    git does not see is reported as not moved (exit 1), never as "nothing to move";
  - each entry is one `os.rename` from `.claude/<entry>` to `.kit/<entry>` (across filesystems:
    copy, compare, then delete the source). kitlib.state_entry looks for each entry in `.kit/`
    first and then in `.claude/`, so between two renames every entry is read from wherever it
    is, and the next run carries on. Two session starts at once: the one that finds the source
    gone says nothing about it; `.kit/migration.json` (the log of runs) is merged under a lock;
  - an entry with files tracked in git stays where it is and the `git mv` to run is printed;
    an entry that is a symlink, or is reached through one (`.claude` itself, or a linked
    `.claude/agent-memory` shared by several checkouts), is left where it is, said once, and
    gets no exclude line of its own; a checkout
    whose `.kit` is a symlink is not moved, nothing is written through the link (no log, no
    note), and only `/.kit` is excluded, so the link stays out of `git status`;
  - an entry in both places is a conflict: both stay, the other entries move anyway, and
    `status` lists it with the two paths. The session start says it, and why a move waits,
    once, and again only when that changes (what it said is kept in the git dir);
  - a `.kit.migrating/` folder left by an older version of this script is emptied into `.kit/`
    by the same rule and removed once empty;
  - `undo` moves the known entries found under `.kit/` back and sets kit.local.json
    `lead.state` to ".claude": the session start then leaves the project alone and `migrate`
    refuses; the owner moves it again with `migrate --again`. Undo reads nothing from
    `.kit/migration.json` and never edits the exclude file.
Exit: 0 done or nothing to do, 1 error, 2 refused (at work, or after undo), 3 conflicts left.
Standard library only.
"""

import argparse
import errno
import filecmp
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import items  # noqa: E402
import kitlib  # noqa: E402

STATE, LEGACY = kitlib.STATE_DIR, kitlib.LEGACY_STATE_DIR
OLD_STAGING = ".kit.migrating"  # the staging folder of the first version of this script
MANIFEST = "migration.json"
NOTE = "kit-state-moved.txt"
SAID = "kit-migration-said.json"  # in the git dir: what the session start said last
BUSY = ("working", "landing")
SCRIPT = Path(__file__).resolve()


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
        found = lead / "items"
        for item in sorted(found.iterdir()) if found.is_dir() else []:
            status = items.status_of(item)[0] if item.is_dir() and item.name != "done" else None
            if status in BUSY:
                why.append(f"item {item.name} is {status} ({item / 'LOG.md'})")
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


def same_tree(a, b):
    """True when the folders a and b hold the same files with the same bytes."""
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    return not mismatch and not errors and all(same_tree(Path(a) / d, Path(b) / d) for d in cmp.common_dirs)


def present(path):
    return path.exists() or path.is_symlink()


def move(src, dst):
    """Move one entry: "moved", "gone" (the source is not there: another session moved it first)
    or "conflict" (source and destination both there, checked again after a refused rename, so a
    session that lost the race is never told about a conflict). os.rename never replaces a folder
    that has files in it, so nothing is overwritten. Across filesystems: copy beside dst, compare,
    rename it into place, and only then delete src."""
    if not present(src):
        return "gone"
    if present(dst):
        return "conflict" if present(src) else "gone"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
        return "moved"
    except FileNotFoundError:
        return "gone"
    except OSError as exc:
        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
            return "conflict" if present(src) and present(dst) else "gone"
        if exc.errno != errno.EXDEV:
            raise
    tmp = dst.with_name(dst.name + ".copying")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp, symlinks=True)
    if not same_tree(src, tmp):
        shutil.rmtree(tmp)
        raise OSError(f"the copy of {src} did not match it; nothing was deleted")
    try:
        os.rename(tmp, dst)
    except OSError:
        shutil.rmtree(tmp)
        return "conflict" if present(src) and present(dst) else "gone"
    shutil.rmtree(src)
    return "moved"


def prune(folder, stop):
    """Remove `folder` and its parents while empty, never `stop` or above."""
    folder, stop = Path(folder), Path(stop)
    while folder != stop and stop in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def ignored(checkout, rel):
    """True when git ignores a file in the folder `rel` of `checkout`."""
    try:
        return subprocess.run(["git", "-C", str(checkout), "check-ignore", "-q", f"{rel}/probe"],
                              capture_output=True, timeout=10, env=kitlib.git_env()).returncode == 0
    except Exception:
        return False


def plan(main, src_dir, dst_dir):
    """(moves, skipped, conflicts): moves are (checkout, name, src, dst); skipped (src, reason);
    conflicts (src, dst), both present."""
    moves, skipped, conflicts = [], [], []
    for checkout in checkouts(main):
        link = checkout / dst_dir
        if dst_dir == STATE and link.is_symlink():
            if checkout == main or any(present(checkout / src_dir / name) for name in names_for(checkout, main)):
                skipped.append((checkout / src_dir, f"{link} is a symlink (to {os.readlink(link)}), so it is not the "
                                f"kit's folder: this checkout stays on {LEGACY}/ and nothing is written through "
                                f"the link; replace it with a folder to move"))
            continue
        sources = [checkout / src_dir]
        if src_dir == LEGACY and checkout == main:
            sources.append(checkout / OLD_STAGING)
        for name in names_for(checkout, main):
            for base in sources:
                src, dst = base / name, checkout / dst_dir / name
                if not present(src):
                    continue
                rel = src.relative_to(checkout).as_posix()
                link = kitlib.linked_part(checkout, rel) or kitlib.linked_part(checkout, dst.relative_to(checkout))
                if link == src:
                    skipped.append((src, "a symlink: move what it points to by hand"))
                elif link:
                    skipped.append((src, f"{link} is a symlink (to {os.readlink(link)}), maybe shared with other "
                                    f"checkouts, so what is under it is not the kit's to move; it is read where it is"))
                elif tracked(checkout, rel):
                    skipped.append((src, f"tracked in git: run `git mv {rel} {dst_dir}/{name}` and commit"))
                elif present(dst):
                    conflicts.append((src, dst))
                else:
                    moves.append((checkout, name, src, dst))
    return moves, skipped, conflicts


def conflict_lines(conflicts):
    return [f"  - {src} and {dst}: both hold {dst.name}; merge what you need into {dst}, then delete {src}"
            for src, dst in conflicts]


def read_manifest(main):
    try:
        value = json.loads((Path(main) / STATE / MANIFEST).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def add_run(main, done):
    """Append this run to `.kit/migration.json` under the lock, read and merged there, so two
    sessions moving at once each keep the other's entries. Nothing when the main checkout's
    `.kit` is a symlink (only worktrees moved): nothing is written through a link."""
    if kitlib.kit_dir_linked(main):
        return
    with kitlib.git_lock(main, "kit-migration.lock"):
        record = read_manifest(main)
        runs = record.get("runs") if isinstance(record.get("runs"), list) else []
        record.update(version=2, runs=runs + [{"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "moved": done}])
        record.pop("reported", None)  # kept in the git dir now (tell_once)
        kitlib.write_text_atomic(Path(main) / STATE / MANIFEST, json.dumps(record, indent=2) + "\n")


def tell_once(main, lines):
    """`lines` when they differ from what the session start said last, else []. What was said is
    kept in the git dir (`kit-migration-said.json`), not in the project, so saying it never makes
    a `.kit/` or writes into one that is not the kit's yet."""
    path = kitlib.git_common_path(main, SAID)
    if path is None:
        return lines
    try:
        with kitlib.git_lock(main, SAID + ".lock"):
            try:
                before = json.loads(path.read_text(encoding="utf-8")).get("said")
            except Exception:
                before = None
            if before == sorted(lines) or (before is None and not lines):
                return []
            kitlib.write_text_atomic(path, json.dumps({"said": sorted(lines)}, indent=2) + "\n")
            return lines
    except kitlib.Busy:
        return []  # another session start is saying it now
    except OSError:
        return lines


def exclude_wanted(main, with_files):
    """Every exclude line the move needs, computed once: `/.kit/<entry>/` and `/.claude/<entry>/`
    for each entry found in either place, except one tracked in git (it is not the kit's to hide)
    and an entry that is a symlink or under one (never probed: it is the owner's, and left in
    place). A
    checkout whose `.kit` is a symlink gets only `/.kit`, so the link does not show in `git
    status`. With `with_files`, the manifest's, the note's and kit.local.json's too (undo writes
    it later)."""
    lines = []
    for checkout in checkouts(main):
        # the note's line serves every worktree: the exclude file is shared
        files = [kitlib.LOCAL_CONFIG, f"{LEGACY}/{NOTE}"] if with_files and checkout == main else []
        if kitlib.kit_dir_linked(checkout):
            lines += kitlib.exclude_lines(checkout, files=files + [STATE])
            continue
        dirs = []
        for name in names_for(checkout, main):
            paths = [(folder, checkout / folder / name) for folder in (STATE, LEGACY, OLD_STAGING)]
            found = [f"{folder}/{name}" for folder, path in paths if present(path)]
            if any(kitlib.linked_part(checkout, f"{folder}/{name}") for folder, _ in paths):
                continue
            if found and not any(tracked(checkout, rel) for rel in found):
                dirs += [f"{STATE}/{name}", f"{LEGACY}/{name}"]
        if with_files and checkout == main:
            files.append(f"{STATE}/{MANIFEST}")
        lines += kitlib.exclude_lines(checkout, files=files, dirs=dirs)
    return list(dict.fromkeys(lines))


def nothing_to_move(main, skipped):
    """The line for a run that moved nothing: where the state is, and why it stays there."""
    if kitlib.kit_dir_linked(main):
        return (f"nothing to move: the state stays in {LEGACY}/, because {main / STATE} is a symlink "
                f"(to {os.readlink(main / STATE)}) and nothing is written through it")
    if skipped:
        return f"nothing to move: what is left in place above stays in {LEGACY}/, read where it is"
    return "nothing to move" + (f": the state is in {STATE}/" if (main / STATE).is_dir() else "")


def migrate(main, dry=False, force=False, out=print, again=False):
    """Move what can move; returns (exit code, the entries moved, the conflicts left, the entries
    that failed with their error)."""
    main = Path(main)
    if kitlib.lead_local(main, "state") == LEGACY and not again:
        raise Refused(2, [f"not moving: the owner moved the state back to {LEGACY}/ with `undo` "
                          f"(kit.local.json lead.state); the owner moves it again with: "
                          f"python3 {SCRIPT} migrate --again"])
    why = busy(main)
    if why and not force:
        raise Refused(2, ["not moving: work is in progress. Wait for it, or --force if it is gone:"]
                      + [f"  - {w}" for w in why])
    moves, skipped, conflicts = plan(main, LEGACY, STATE)
    for src, reason in skipped:
        out(f"left in place: {src} ({reason})")
    for _, _, src, dst in moves:
        out(f"{'would move' if dry else 'move'} {src} -> {dst}")
    if dry:
        if conflicts:
            out("would leave in both places:")
            for line in conflict_lines(conflicts):
                out(line)
        return (3 if conflicts else 0), [], conflicts, []
    if again:
        kitlib.save_lead_local(main, "state", None)
    # the new line first, so the entry is never visible to git, and the old one kept (added if a
    # .gitignore covered it before), so a later write to the old place stays hidden too; one call
    kitlib.add_exclude_lines(main, exclude_wanted(main, with_files=bool(moves)))
    ready = []
    done, failed = [], []
    for move_ in moves:
        checkout, name, src, _ = move_
        if ignored(checkout, f"{STATE}/{name}"):
            ready.append(move_)
        else:  # still to move: said as a failure, so the exit code and `status` agree
            failed.append((src, f"git would see {STATE}/{name}/: .git/info/exclude could not take its line"))
    for checkout, name, src, dst in ready:
        try:
            how = move(src, dst)
        except OSError as exc:
            failed.append((src, exc))
            continue
        if how == "conflict":
            conflicts.append((src, dst))
        elif how == "moved":
            prune(src.parent, checkout)
            done.append({"checkout": str(checkout), "name": name, "from": str(src), "to": str(dst)})
    prune(main / OLD_STAGING, main)
    if done:
        try:
            add_run(main, done)
        except OSError as exc:  # the log only; the entries are where kitlib looks for them
            out(f"note: {main / STATE / MANIFEST} not updated ({exc})")
        for checkout in {Path(d["checkout"]) for d in done}:
            if not (checkout / LEGACY).is_dir() or kitlib.kit_dir_linked(checkout):
                continue  # its .claude/ held only kit state and is gone: no folder made for a note
            names = ", ".join(d["name"] for d in done if d["checkout"] == str(checkout))
            try:
                (checkout / LEGACY / NOTE).write_text(
                    f"kit: this checkout's working state ({names}) moved to {checkout / STATE}/ on "
                    f"{time.strftime('%Y-%m-%d')}, out of the folder Claude Code protects.\n"
                    f"undo: python3 {SCRIPT} undo --root {main}\n", encoding="utf-8")
            except OSError:
                pass
    for src, exc in failed:
        out(f"not moved: {src} ({exc}); it is read where it is, and the next run tries again")
    if conflicts:
        out("left in both places, nothing overwritten:")
        for line in conflict_lines(conflicts):
            out(line)
    if done or not (conflicts or failed):
        out(f"moved {len(done)} entr{'y' if len(done) == 1 else 'ies'} to {STATE}/" if done
            else nothing_to_move(main, skipped))
    try:
        text = (main / ".gitignore").read_text(encoding="utf-8")
        if done and (f"{LEGACY}/lead" in text or f"{LEGACY}/evidence" in text):
            out(f"note: .gitignore names {LEGACY}/ state paths; add the {STATE}/ ones there if the team shares it")
    except OSError:
        pass
    return (1 if failed else 3 if conflicts else 0), done, conflicts, failed


def undo(main, dry=False, force=False, out=print):
    """Move the known entries under `.kit/` back to `.claude/`, and keep them there."""
    main = Path(main)
    why = busy(main)
    if why and not force:
        raise Refused(2, ["not moving back: work is in progress:"] + [f"  - {w}" for w in why])
    moves, skipped, conflicts = plan(main, STATE, LEGACY)
    for src, reason in skipped:
        out(f"left in place: {src} ({reason})")
    for _, _, src, dst in moves:
        out(f"{'would move' if dry else 'move'} {src} -> {dst}")
    if dry:
        return 0
    # first, so a session start in the middle of this does not move them straight back
    kitlib.save_lead_local(main, "state", LEGACY)
    back = 0
    for checkout, _, src, dst in moves:
        how = move(src, dst)
        if how == "conflict":
            conflicts.append((src, dst))
        elif how == "moved":
            back += 1
            prune(src.parent, checkout)
    for checkout in checkouts(main):
        (checkout / LEGACY / NOTE).unlink(missing_ok=True)
    (main / STATE / MANIFEST).unlink(missing_ok=True)
    for checkout in checkouts(main):
        prune(checkout / STATE, checkout)
    if conflicts:
        out("left in both places, nothing overwritten:")
        for line in conflict_lines(conflicts):
            out(line)
    out(f"moved {back} entr{'y' if back == 1 else 'ies'} back to {LEGACY}/; the session start leaves them "
        f"there until you run `python3 {SCRIPT} migrate --again`")
    return 3 if conflicts else 0


def auto(root):
    """session_start.py's call. Returns the lines to print: the "moved" line whenever entries
    moved, and what needs the owner (why the move waits, conflicts, entries left in place or that
    failed to move, and why), said once and again only when it changes."""
    main = Path(kitlib.main_checkout(root) or root)
    if kitlib.lead_local(main, "state") == LEGACY:  # the owner ran undo
        return []
    moves, skipped, conflicts = plan(main, LEGACY, STATE)
    said = kitlib.git_common_path(main, SAID)
    if not moves and not skipped and not conflicts and not (said and said.exists()):
        return []  # the common case, nothing to do: no file is written
    lines, told, done, failed = [], [], [], []
    if not moves and any(kitlib.kit_dir_linked(c) for c in checkouts(main)):
        kitlib.add_exclude_lines(main, exclude_wanted(main, with_files=False))  # the link's `/.kit`
    if moves:
        try:
            _, done, conflicts, failed = migrate(main, out=lambda _line: None)
        except Refused as exc:
            why = "; ".join(line.strip().lstrip("- ") for line in exc.lines[1:]) or exc.lines[0]
            told.append(f"kit: the kit's state waits to move from {LEGACY}/ to {STATE}/ ({why}); it moves at a "
                        f"session start when nothing is at work, or: python3 {SCRIPT} migrate")
        except OSError as exc:
            failed = [(main / LEGACY, exc)]
    if done:  # nothing here when another session moved them first
        names = ", ".join(sorted({d["name"] for d in done}))
        lines.append(f"kit: moved this project's kit state ({names}) from {LEGACY}/ to {STATE}/, out of the "
                     f"folder Claude Code protects; undo: python3 {SCRIPT} undo")
    conflicts = [(src, dst) for src, dst in conflicts if present(src) and present(dst)]
    told += [f"kit: {src} did not move to {STATE}/ ({exc}); it is read where it is, and each session "
             f"start tries again" for src, exc in failed] + [f"kit: {src} was not moved to {STATE}/: {reason}" for src, reason in skipped] + \
            [f"kit: {src} and {dst} both exist, so neither was moved or changed; merge what you need into "
             f"{dst} and delete {src} (`python3 {SCRIPT} status` lists them)" for src, dst in conflicts]
    return lines + tell_once(main, told)


def status(main, out=print):
    main = Path(main)
    out(f"main checkout: {main}")
    out(f"state folder:  {kitlib.state_dir(main)}")
    if kitlib.lead_local(main, "state") == LEGACY:
        out(f"  kept in {LEGACY}/ by `undo` (kit.local.json lead.state); `migrate --again` moves it again")
    for checkout in checkouts(main):
        for name in names_for(checkout, main):
            for folder in (STATE, LEGACY, OLD_STAGING):
                if (checkout / folder / name).exists():
                    out(f"  {checkout / folder / name}")
    moves, skipped, conflicts = plan(main, LEGACY, STATE)
    for _, _, src, dst in moves:
        out(f"  to move: {src} -> {dst}")
    for src, reason in skipped:
        out(f"  left in place: {src} ({reason})")
    if conflicts:
        out("  in both places, nothing moved or overwritten:")
        for line in conflict_lines(conflicts):
            out("  " + line)
    for w in busy(main):
        out(f"  at work: {w}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("migrate", "undo", "status"))
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="move even if work looks in progress")
    ap.add_argument("--again", action="store_true", help="migrate: move the state again after `undo`")
    args = ap.parse_args(argv)
    root = kitlib.main_checkout(args.root)
    if not root:
        print(f"kit migrate: {args.root} is not in a git repository", file=sys.stderr)
        return 1
    try:
        if args.command == "status":
            return status(root)
        if args.command == "undo":
            return undo(root, args.dry_run, args.force)
        return migrate(root, args.dry_run, args.force, again=args.again)[0]
    except Refused as exc:
        print("kit migrate: " + "\n".join(exc.lines), file=sys.stderr)
        return exc.code
    except (OSError, ValueError) as exc:
        print(f"kit migrate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
