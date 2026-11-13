#!/usr/bin/env python3
"""Self-check for migrate_state.py: an older project's state moves from .claude/ to .kit/ and
back, refuses while a thread or run is at work, leaves tracked entries where they are, finishes
a move that died half-way, and finds nothing to do the second time.

Run: python3 plugins/kit/hooks/tests/test_migrate_state.py   (exit 0 = all good)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = SCRIPTS / "migrate_state.py"
sys.path.insert(0, str(SCRIPTS))
import kitlib  # noqa: E402

GIT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
STATE_FILES = {
    "lead/board.md": "B1 | ship | a | DONE WHEN x | queued | agent - | - | from lead\n",
    "lead/items/B1/LOG.md": "- 2026-11-01 10:00 | queued | from lead\n",
    "evidence/main/gate-verify.json": "{}\n",
    "agent-memory/kit-verifier/MEMORY.md": "verifier notes\n",
    "overnight/run1/state.json": json.dumps({"stop_reason": "done"}),
}
STAYS = {"kit.json": '{"verify": "true"}\n', "agent-memory/other/MEMORY.md": "theirs\n", "loop.md": "loop\n"}
EXCLUDE = ["/.claude/lead/", "/.claude/evidence/", "/.claude/agent-memory/", "/.claude/overnight/"]


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *GIT, *args], check=True, capture_output=True, text=True).stdout


def run(repo, *args):
    out = subprocess.run([sys.executable, str(SCRIPT), *args, "--root", str(repo)], capture_output=True, text=True)
    return out.returncode, out.stdout + out.stderr


def project(tmp, name="p"):
    """A project from before the move: kit state in .claude/, excluded line by line, a commit."""
    repo = Path(tmp) / name
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("x\n")
    (repo / ".claude").mkdir()
    for rel, text in STAYS.items():
        (repo / ".claude" / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / rel).write_text(text)
    sh(repo, "add", "README.md", ".claude/kit.json", ".claude/loop.md")
    sh(repo, "commit", "-qm", "init")
    for rel, text in STATE_FILES.items():
        (repo / ".claude" / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / rel).write_text(text)
    (repo / ".git" / "info" / "exclude").write_text("# git's own comment\n" + "\n".join(EXCLUDE) + "\n")
    return repo


def exclude_lines(repo):
    return (repo / ".git" / "info" / "exclude").read_text().splitlines()


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL:", msg)

    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        before = sh(repo, "status", "--porcelain")
        code, out = run(repo, "migrate", "--dry-run")
        check(code == 0 and "would move" in out, f"dry run says what it would do: {out}")
        check(not (repo / ".kit").exists() and (repo / ".claude" / "lead").is_dir(), "a dry run moves nothing")

        code, out = run(repo, "migrate")
        check(code == 0, f"migrate succeeds: {code} {out}")
        for rel, text in STATE_FILES.items():
            check((repo / ".kit" / rel).read_text() == text, f"{rel} moved whole")
            check(not (repo / ".claude" / rel).exists(), f"{rel} left .claude")
        for rel, text in STAYS.items():
            check((repo / ".claude" / rel).read_text() == text, f"{rel} stays in .claude")
        check(not (repo / ".kit.migrating").exists(), "no staging folder left")
        check(kitlib.state_dir_name(repo) == ".kit", "kitlib now answers .kit")
        lines = exclude_lines(repo)
        for name in ("lead", "evidence", "overnight", "agent-memory/kit-verifier"):
            check(f"/.kit/{name}/" in lines, f"{name} excluded under .kit: {lines}")
        check("/.claude/lead/" not in lines and "/.claude/evidence/" not in lines, f"old lines replaced: {lines}")
        check("/.claude/agent-memory/" in lines, "the agent-memory line stays: other agents' memory is there")
        check("# git's own comment" in lines and "/.kit/" not in lines, f"other lines kept, no blanket line: {lines}")
        check((repo / ".claude" / "kit-state-moved.txt").is_file(), "a note says where the state went")
        manifest = json.loads((repo / ".kit" / "migration.json").read_text())
        check(len(manifest["runs"]) == 1 and len(manifest["runs"][0]["moved"]) == 4, f"manifest: {manifest}")
        check(sh(repo, "status", "--porcelain") == before, f"git status unchanged: {sh(repo, 'status', '--porcelain')}")

        code, out = run(repo, "migrate")
        check(code == 0 and "nothing to move" in out, f"second run is a no-op: {out}")
        check(len(json.loads((repo / ".kit" / "migration.json").read_text())["runs"]) == 1, "no second manifest run")

        code, out = run(repo, "status")
        check(code == 0 and ".kit/lead" in out, f"status lists the moved state: {out}")

        code, out = run(repo, "undo")
        check(code == 0, f"undo succeeds: {out}")
        for rel, text in STATE_FILES.items():
            check((repo / ".claude" / rel).read_text() == text, f"{rel} moved back")
        check(not (repo / ".kit").exists(), f"undo leaves no .kit: {list((repo / '.kit').rglob('*')) if (repo / '.kit').exists() else ''}")
        check(exclude_lines(repo) == ["# git's own comment"] + EXCLUDE, f"exclude restored: {exclude_lines(repo)}")
        check(not (repo / ".claude" / "kit-state-moved.txt").exists(), "undo removes the note")
        check(sh(repo, "status", "--porcelain") == before, "git status unchanged after undo")
        code, out = run(repo, "undo")
        check(code == 0 and "nothing to undo" in out, f"a second undo is a no-op: {out}")

    # a thread at work: an item still `working`, a board row `landing`, a live overnight run
    for case in ("working", "landing", "overnight"):
        with tempfile.TemporaryDirectory() as tmp:
            repo = project(tmp)
            if case == "working":
                with open(repo / ".claude/lead/items/B1/LOG.md", "a") as f:
                    f.write("- 2026-11-01 10:05 | working | feat/a\n- 2026-11-01 10:06 | cost | $0.10\n")
            elif case == "landing":
                (repo / ".claude/lead/board.md").write_text("| B2 | ship | b | DONE WHEN y | landing | agent x | - | from lead |\n")
            else:
                (repo / ".claude/overnight/run2").mkdir()
                (repo / ".claude/overnight/run2/state.json").write_text("{}")
            code, out = run(repo, "migrate")
            check(code == 2 and "in progress" in out, f"{case}: refused with a reason: {code} {out}")
            check((repo / ".claude/lead/board.md").exists() and not (repo / ".kit").exists(), f"{case}: nothing moved")
            check(exclude_lines(repo) == ["# git's own comment"] + EXCLUDE, f"{case}: exclude untouched")
            check(kitlib.state_entry(repo, "lead") == repo / ".claude" / "lead", f"{case}: the old layout still works")
            code, out = run(repo, "migrate", "--force")
            check(code == 0 and (repo / ".kit/lead/board.md").exists(), f"{case}: --force moves it: {out}")

    # a tracked entry stays, with the git mv to run; the rest moves
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        sh(repo, "add", "-f", ".claude/evidence")
        sh(repo, "commit", "-qm", "evidence in git")
        code, out = run(repo, "migrate")
        check(code == 0 and "git mv .claude/evidence .kit/evidence" in out, f"tracked entry: the command to run: {out}")
        check((repo / ".claude/evidence/main/gate-verify.json").exists(), "the tracked entry stayed")
        check((repo / ".kit/lead/board.md").exists(), "the untracked entries moved")
        check(kitlib.state_entry(repo, "evidence") == repo / ".claude" / "evidence", "kitlib still finds it")
        check(sh(repo, "status", "--porcelain") == "", f"git clean: {sh(repo, 'status', '--porcelain')}")

    # an entry in both places is a conflict: nothing is overwritten
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        (repo / ".kit/lead").mkdir(parents=True)
        (repo / ".kit/lead/board.md").write_text("newer\n")
        code, out = run(repo, "migrate")
        check(code == 3 and "both places" in out, f"conflict refused: {code} {out}")
        check((repo / ".kit/lead/board.md").read_text() == "newer\n", "the newer board is kept")
        check((repo / ".claude/lead/board.md").exists(), "the older board is kept")

    # a move that died after staging: the next run finishes it
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        (repo / ".kit.migrating").mkdir()
        (repo / ".claude/lead").rename(repo / ".kit.migrating/lead")
        code, out = run(repo, "migrate")
        check(code == 0, f"interrupted move finished: {out}")
        check((repo / ".kit/lead/board.md").exists() and (repo / ".kit/evidence").is_dir(), "both parts in .kit")
        check(not (repo / ".kit.migrating").exists(), "staging gone")
        moved = [d["name"] for d in json.loads((repo / ".kit/migration.json").read_text())["runs"][0]["moved"]]
        check("lead" in moved, f"the staged entry is in the manifest, so undo brings it back: {moved}")

    # overnight runs in a linked worktree move inside that worktree
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        tree = Path(tmp) / "wt"
        sh(repo, "worktree", "add", "-q", "-b", "side", str(tree))
        (tree / ".claude/overnight/r9").mkdir(parents=True)
        (tree / ".claude/overnight/r9/end-state.json").write_text("{}")
        (tree / ".claude/lead").mkdir()  # only the main checkout's lead is state
        code, out = run(tree, "migrate")
        check(code == 0, f"run from a worktree: {out}")
        check((tree / ".kit/overnight/r9/end-state.json").exists(), "the worktree's runs moved in place")
        check((tree / ".claude/lead").is_dir() and not (tree / ".kit/lead").exists(), "a worktree's lead is not moved")
        check((repo / ".kit/lead/board.md").exists(), "the main checkout's lead moved")
        check(sh(tree, "status", "--porcelain") == "", f"worktree clean: {sh(tree, 'status', '--porcelain')}")
        code, out = run(repo, "undo")
        check(code == 0 and (tree / ".claude/overnight/r9").is_dir(), f"undo brings the worktree's runs back: {out}")

    # a fresh project: nothing to move, nothing made
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "fresh"
        repo.mkdir()
        sh(repo, "init", "-q")
        code, out = run(repo, "migrate")
        check(code == 0 and "nothing to move" in out and not (repo / ".kit").exists(), f"fresh: {out}")

    print("migrate_state: all checks passed" if not failed else f"migrate_state: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
