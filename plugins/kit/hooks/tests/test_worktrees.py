#!/usr/bin/env python3
"""Self-check for worktrees.py: each linked worktree classified on a real repository, a plan
printed, nothing removed.

Run: python3 plugins/kit/hooks/tests/test_worktrees.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "worktrees.py"
OLD = "2026-01-01T12:00:00Z"


def git(repo, *args, date=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid")
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def tree(repo, base, name, files=None, date=None, start="main"):
    path = base / name
    git(repo, "worktree", "add", "-q", "-b", name, str(path), start)
    for rel, text in (files or {}).items():
        (path / rel).write_text(text)
        git(path, "add", rel)
    if files:
        git(path, "commit", "-qm", name, date=date)
    return path


def run(cwd, *args, env=None):
    out = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(cwd), capture_output=True, text=True,
                         timeout=60, env=env or os.environ)
    return out.returncode, out.stdout, out.stderr


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL " + str(msg))

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        repo = base / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "app.py").write_text("x = 1\n")
        git(repo, "add", "app.py")
        git(repo, "commit", "-qm", "init")
        code, out, _ = run(repo)
        check(code == 0 and "no linked worktrees" in out, out)

        merged = tree(repo, base, "merged")  # nothing ahead of main
        merged_dirty = tree(repo, base, "merged-dirty")
        (merged_dirty / "notes.txt").write_text("keep me\n")
        ready = tree(repo, base, "ready", {"new.py": "y = 1\n"})
        conflict = tree(repo, base, "conflict", {"app.py": "x = 2\n"})
        active = tree(repo, base, "active", {"a.py": "a\n"})
        (active / "a.py").write_text("a changed\n")
        dirty = tree(repo, base, "dirty", {"d.py": "d\n"})
        (dirty / "d.py").write_text("d changed\n")
        two_hours = time.time() - 7200
        os.utime(dirty / "d.py", (two_hours, two_hours))
        stale = tree(repo, base, "stale", {"s.py": "s\n"}, date=OLD)
        (repo / "app.py").write_text("x = 3\n")  # main moves on: `conflict` no longer merges cleanly
        git(repo, "commit", "-qam", "main moves")
        gone = tree(repo, base, "gone")
        subprocess.run(["rm", "-rf", str(gone)], check=True)

        # run from inside a worktree, with GIT_DIR pointing at another repository: it is ignored
        other = base / "other"
        other.mkdir()
        git(other, "init", "-q")
        env = dict(os.environ, GIT_DIR=str(other / ".git"), GIT_WORK_TREE=str(other), GIT_INDEX_FILE=str(other / "x"))
        code, out, err = run(ready, "--json", env=env)
        check(code == 0, err)
        data = json.loads(out) if code == 0 else {"worktrees": []}
        by = {Path(r["path"]).name: r for r in data["worktrees"]}
        check(data.get("base") == "main" and str(repo) not in by and "repo" not in by, f"the main checkout is not listed: {data}")
        want = {"merged": ("merged", "remove"), "merged-dirty": ("merged", "keep"), "ready": ("ready", "keep"),
                "conflict": ("conflict", "keep"), "active": ("active", "keep"), "dirty": ("dirty", "keep"),
                "stale": ("stale", "salvage"), "gone": ("unknown", "keep")}
        for name, (cls, plan) in want.items():
            row = by.get(name, {})
            check((row.get("class"), row.get("plan")) == (cls, plan), f"{name}: want {cls}/{plan}, got {row}")
        check(by.get("conflict", {}).get("files") == ["app.py"], f"the files in conflict: {by.get('conflict')}")
        check("uncommitted" in by.get("merged-dirty", {}).get("reason", ""), by.get("merged-dirty"))

        code, out, _ = run(repo)
        check(code == 0 and f"remove   merged    {merged}" in out and f"git worktree remove {merged} && git branch -d merged" in out
              and f"salvage  stale     {stale}" in out and "git push -u origin stale" in out
              and "git bundle create stale.bundle main..stale" in out and "Nothing was removed" in out, out)
        listed = git(repo, "worktree", "list")
        check(all(str(p) in listed for p in (merged, stale, conflict)) and merged.is_dir(), "it removes nothing")
        code, _, err = run(base)
        check(code == 2 and "not inside a git repository" in err, err)

    print("worktrees: all checks passed" if not failed else f"worktrees: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
