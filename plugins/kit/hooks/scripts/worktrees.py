#!/usr/bin/env python3
"""Every linked worktree of this repository, classified, with a clean-up plan it only prints.

A coordinator leaves one worktree per thread behind, and after a few days nobody remembers which
hold work that is not merged anywhere. This says, for each linked worktree (the main checkout is
never listed):

    merged    its branch has nothing ahead of the default branch
    stale     unmerged, and no commit or file change for 7 days
    active    uncommitted changes, one of them made in the last hour
    dirty     uncommitted changes, none that recent
    conflict  committed work that would not merge cleanly into the default branch
    ready     committed work that merges cleanly
    unknown   committed work whose merge could not be tested (an old git, say)

and the plan: `remove` only for a merged worktree with nothing uncommitted, `salvage` (push the
branch or bundle it first) for stale unmerged work, `keep` for the rest. It removes nothing.
git runs with GIT_DIR, GIT_WORK_TREE and the like cleared (kitlib.hermetic_env), so a run from
inside a git hook reads this repository and not the one the hook was started for.

    python3 worktrees.py [--json]
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

STALE_DAYS = 7
ACTIVE_MINUTES = 60


def git(cwd, *args):
    code, out, _ = kitlib.git_run(cwd, *args)
    return out if code == 0 else ""


def linked(root):
    """[{"path", "head", "branch", "prunable"}] of the linked worktrees, from `git worktree list
    --porcelain`; the first entry is the main checkout and is left out."""
    entries, current = [], None
    for line in git(root, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line.strip():
            if current:
                entries.append(current)
            current = None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = {"path": value, "head": "", "branch": "", "prunable": False, "bare": False}
        elif current is not None and key == "HEAD":
            current["head"] = value
        elif current is not None and key == "branch":
            current["branch"] = value[len("refs/heads/"):] if value.startswith("refs/heads/") else value
        elif current is not None and key == "prunable":
            current["prunable"] = True
        elif current is not None and key == "bare":
            current["bare"] = True
    return [e for e in entries[1:] if not e["bare"]]


def uncommitted(path):
    """[(relative path, mtime)] of the modified and untracked files in a worktree."""
    files = []
    for entry in git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"):
        if len(entry) < 4:
            continue
        rel = entry[3:]
        try:
            files.append((rel, os.stat(Path(path) / rel).st_mtime))
        except OSError:
            files.append((rel, 0.0))  # deleted: the change has no time of its own
    return files


def classify(root, entry, base, now=None):
    now = time.time() if now is None else now
    head = entry["head"]
    row = {"path": entry["path"], "branch": entry["branch"] or "(detached)", "head": head[:12],
           "ahead": None, "dirty": 0, "last_change_days": None, "class": "", "plan": "keep",
           "reason": "", "files": []}
    if entry["prunable"] or not Path(entry["path"]).is_dir():
        row.update({"class": "unknown", "reason": "its folder is gone (git worktree prune clears the entry)"})
        return row
    files = uncommitted(entry["path"])
    row["dirty"] = len(files)
    committed = git(entry["path"], "log", "-1", "--format=%ct", "HEAD").strip()
    last = max([float(committed or 0)] + [t for _, t in files])
    row["last_change_days"] = round((now - last) / 86400, 1) if last else None
    if not base:
        row.update({"class": "unknown", "reason": "no default branch (origin/HEAD, main or master) here"})
        return row
    ahead = git(root, "rev-list", "--count", f"{base}..{head}").strip()
    if not ahead.isdigit():
        row.update({"class": "unknown", "reason": f"cannot compare {head[:12]} with {base}"})
        return row
    row["ahead"] = int(ahead)
    if row["ahead"] == 0:
        row["class"] = "merged"
        if files:
            row["reason"] = f"merged, but {len(files)} uncommitted file(s) would be lost"
        else:
            row.update({"plan": "remove", "reason": f"nothing ahead of {base}"})
        return row
    if last and now - last > STALE_DAYS * 86400:
        row.update({"class": "stale", "plan": "salvage",
                    "reason": f"{row['ahead']} commit(s) not in {base}, untouched for {int((now - last) // 86400)} days"
                              + (f", {len(files)} uncommitted file(s)" if files else "")})
        return row
    if files:
        recent = any(now - t < ACTIVE_MINUTES * 60 for _, t in files)
        row.update({"class": "active" if recent else "dirty",
                    "reason": f"{len(files)} uncommitted file(s)" + (", changed in the last hour" if recent else "")})
        return row
    state, conflicted, why = kitlib.merge_tree(root, base, head)
    if state == "conflict":
        row.update({"class": "conflict", "files": conflicted,
                    "reason": f"would not merge into {base}: {', '.join(conflicted) or '(no file named)'}"})
    elif state == "clean":
        row.update({"class": "ready", "reason": f"{row['ahead']} commit(s), merges cleanly into {base}"})
    else:
        row.update({"class": "unknown", "reason": f"merge not tested: {why}"})
    return row


def main_root(cwd):
    """The main checkout of the repository cwd is in, found hermetically; None outside git."""
    top = git(cwd, "rev-parse", "--show-toplevel").strip()
    if not top:
        return None
    common = Path(git(top, "rev-parse", "--path-format=absolute", "--git-common-dir").strip() or ".")
    return str(common.parent) if common.name == ".git" and common.parent.is_dir() else top


def plan(root, now=None):
    base = kitlib.git_base(root)
    return {"repo": str(root), "base": base, "worktrees": [classify(root, e, base, now) for e in linked(root)]}


def how(row, base):
    """The command a person would run for a plan, printed, never run."""
    path, branch = row["path"], row["branch"]
    if row["plan"] == "remove":
        return f"git worktree remove {path}" + (f" && git branch -d {branch}" if branch != "(detached)" else "")
    if row["plan"] == "salvage":
        if branch == "(detached)":
            return f"git -C {path} branch salvage/{row['head']} (then push or bundle it)"
        return f"git push -u origin {branch}  (or: git bundle create {branch.replace('/', '-')}.bundle {base}..{branch})"
    return ""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    root = main_root(os.getcwd())
    if not root:
        print("worktrees: not inside a git repository", file=sys.stderr)
        return 2
    result = plan(root)
    if "--json" in argv:
        print(json.dumps(result, indent=2))
        return 0
    rows = result["worktrees"]
    if not rows:
        print("worktrees: no linked worktrees")
        return 0
    print(f"worktrees of {result['repo']} against {result['base'] or '(no default branch)'}:")
    for r in rows:
        print(f"{r['plan']:<8} {r['class']:<9} {r['path']}  [{r['branch']}]  {r['reason']}")
        cmd = how(r, result["base"])
        if cmd:
            print(f"         {cmd}")
    print("Nothing was removed: this only prints the plan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
