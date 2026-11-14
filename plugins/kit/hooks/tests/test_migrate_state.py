#!/usr/bin/env python3
"""Self-check for migrate_state.py: an older project's state moves from .claude/ to .kit/ one
entry at a time and back (and stays back), refuses while a thread or run is at work, leaves
tracked and conflicting entries where they are, carries on after a run killed half-way, and
finds nothing to do the second time.

Run: python3 plugins/kit/hooks/tests/test_migrate_state.py   (exit 0 = all good)
"""

import errno
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = SCRIPTS / "migrate_state.py"
sys.path.insert(0, str(SCRIPTS))
import kitlib  # noqa: E402
import migrate_state  # noqa: E402

GIT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
STATE_FILES = {
    "lead/board.md": "B1 | ship | a | DONE WHEN x | queued | agent - | - | from lead\n",
    "lead/items/B1/LOG.md": "- 2026-11-01 10:00 | queued | from lead\n",
    "evidence/main/notes.txt": "pass\n",
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
        check(kitlib.state_dir_name(repo) == ".kit", "kitlib now answers .kit")
        lines = exclude_lines(repo)
        for name in ("lead", "evidence", "overnight", "agent-memory/kit-verifier"):
            check(f"/.kit/{name}/" in lines, f"{name} excluded under .kit: {lines}")
        check(all(line in lines for line in EXCLUDE), f"the old lines are kept, for anything written there later: {lines}")
        check("# git's own comment" in lines and "/.kit/" not in lines, f"other lines kept, no blanket line: {lines}")
        check((repo / ".claude" / "kit-state-moved.txt").is_file(), "a note says where the state went")
        manifest = json.loads((repo / ".kit" / "migration.json").read_text())
        check(len(manifest["runs"]) == 1 and len(manifest["runs"][0]["moved"]) == 4, f"manifest: {manifest}")
        check(sh(repo, "status", "--porcelain") == before, f"git status unchanged: {sh(repo, 'status', '--porcelain')}")
        moved_lines = exclude_lines(repo)

        code, out = run(repo, "migrate")
        check(code == 0 and "nothing to move" in out, f"second run is a no-op: {out}")
        check(len(json.loads((repo / ".kit" / "migration.json").read_text())["runs"]) == 1, "no second manifest run")
        code, out = run(repo, "status")
        check(code == 0 and ".kit/lead" in out, f"status lists the moved state: {out}")

        # undo sticks: the entries go back, the session start leaves them, `migrate` by hand moves them again
        code, out = run(repo, "undo")
        check(code == 0, f"undo succeeds: {out}")
        for rel, text in STATE_FILES.items():
            check((repo / ".claude" / rel).read_text() == text, f"{rel} moved back")
        check(not (repo / ".kit").exists(), f"undo leaves no .kit: {sorted((repo / '.kit').rglob('*')) if (repo / '.kit').exists() else ''}")
        check(exclude_lines(repo) == moved_lines, f"undo leaves the exclude file alone: {exclude_lines(repo)}")
        check(not (repo / ".claude" / "kit-state-moved.txt").exists(), "undo removes the note")
        check(kitlib.lead_local(repo, "state") == ".claude", "undo records lead.state in kit.local.json")
        check(sh(repo, "status", "--porcelain") == before, "git status unchanged after undo")
        check(migrate_state.auto(repo) == [] and not (repo / ".kit").exists(), "a session start after undo: silent, nothing moved")
        code, out = run(repo, "migrate")
        check(code == 2 and "migrate --again" in out and not (repo / ".kit").exists(),
              f"a bare migrate, which runs unasked, refuses after undo and names --again: {code} {out}")
        check(kitlib.lead_local(repo, "state") == ".claude", "and leaves lead.state")
        code, out = run(repo, "migrate", "--again", "--dry-run")
        check(code == 0 and kitlib.lead_local(repo, "state") == ".claude", f"a dry --again changes nothing: {out}")
        code, out = run(repo, "migrate", "--again")
        check(code == 0 and (repo / ".kit/lead/board.md").exists(), f"migrate --again moves it again: {out}")
        check(kitlib.lead_local(repo, "state") is None, "and clears lead.state")
        check(json.loads((repo / ".claude/kit.local.json").read_text()) == {"lead": {}}, "kit.local.json kept as JSON")

    # undo moves back only the known entries it finds, whatever the manifest claims
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        run(repo, "migrate")
        (repo / ".kit" / "notes").mkdir()
        (repo / ".kit" / "notes" / "mine.md").write_text("mine\n")
        crafted = {"version": 2, "runs": [{"moved": [
            {"checkout": str(repo), "name": "README.md", "from": str(repo / ".claude" / "README.md"), "to": str(repo / "README.md")},
            {"checkout": str(repo), "name": "notes", "from": str(repo / ".claude" / "notes"), "to": str(repo / ".kit" / "notes")}]}]}
        (repo / ".kit" / "migration.json").write_text(json.dumps(crafted))
        code, out = run(repo, "undo")
        check(code == 0 and (repo / "README.md").read_text() == "x\n", f"README stays where it is: {out}")
        check((repo / ".kit/notes/mine.md").read_text() == "mine\n" and not (repo / ".claude/notes").exists(),
              "a folder the manifest names but the kit does not own stays")
        check((repo / ".claude/lead/board.md").exists(), "the known entries went back")

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
            said = migrate_state.auto(repo)
            check(len(said) == 1 and "waits to move" in said[0] and "stays in" not in said[0], f"{case}: the session start says why: {said}")
            code, out = run(repo, "migrate", "--force")
            check(code == 0 and (repo / ".kit/lead/board.md").exists(), f"{case}: --force moves it: {out}")

    # an item left `working` after its branch was merged is stale, not at work: the move goes on.
    # One whose branch is not merged, has no commit of its own yet, or cannot be found stays at work
    for case in ("merged", "deleted", "unmerged", "fresh", "gone"):
        with tempfile.TemporaryDirectory() as tmp:
            repo = project(tmp)
            sh(repo, "checkout", "-qb", "feat/m")
            if case != "fresh":
                (repo / "m.txt").write_text("m\n")
                sh(repo, "add", "m.txt")
                sh(repo, "commit", "-qm", "m")
            tip = sh(repo, "rev-parse", "HEAD").strip()
            sh(repo, "checkout", "-q", "main")
            if case in ("merged", "deleted"):
                sh(repo, "merge", "-q", "--no-ff", "-m", "merge feat/m", "feat/m")
            if case in ("deleted", "gone"):
                sh(repo, "branch", "-q", "-D", "feat/m")
            note = f"PASS, reviewed {tip[:12]}, agent v1" if case in ("deleted", "gone") else "branch feat/m"
            with open(repo / ".claude/lead/items/B1/LOG.md", "a") as f:
                f.write(f"- 2026-11-01T10:05:00Z | working | branch feat/m\n- 2026-11-01T10:06:00Z | verdict | {note}\n"
                        "- 2026-11-01T10:07:00Z | working | fixing\n")
            (repo / ".claude/lead/board.md").write_text("| B1 | ship | a | DONE WHEN x | working | agent x | - | from lead |\n")
            code, out = run(repo, "migrate")
            if case in ("merged", "deleted"):
                check(code == 0 and (repo / ".kit/lead/board.md").exists(), f"{case}: a merged item does not hold the move: {code} {out}")
            else:
                check(code == 2 and "item B1 is working" in out and "board row" not in out, f"{case}: still at work: {code} {out}")

    # a tracked entry stays, with the git mv to run; the rest moves
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        sh(repo, "add", "-f", ".claude/evidence")
        sh(repo, "commit", "-qm", "evidence in git")
        before = exclude_lines(repo)
        code, out = run(repo, "migrate")
        check(code == 0 and "git mv .claude/evidence .kit/evidence" in out, f"tracked entry: the command to run: {out}")
        added = [l for l in exclude_lines(repo) if l not in before]
        check("/.kit/lead/" in added and not any("evidence" in l for l in added),
              f"a tracked entry gets no exclude line in either layout: {added}")
        check((repo / ".claude/evidence/main/notes.txt").exists(), "the tracked entry stayed")
        check((repo / ".kit/lead/board.md").exists(), "the untracked entries moved")
        check(kitlib.state_entry(repo, "evidence") == repo / ".claude" / "evidence", "kitlib still finds it")
        check(sh(repo, "status", "--porcelain") == "", f"git clean: {sh(repo, 'status', '--porcelain')}")

    # one entry in both places, one movable: the conflict keeps both, the other moves; said once
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        (repo / ".kit/lead").mkdir(parents=True)
        (repo / ".kit/lead/board.md").write_text("newer\n")
        said = migrate_state.auto(repo)
        check(any("both exist" in s and str(repo / ".claude/lead") in s and str(repo / ".kit/lead") in s for s in said),
              f"the session start names both paths: {said}")
        check(any(s.startswith("kit: moved") for s in said), f"and says what moved: {said}")
        check((repo / ".kit/lead/board.md").read_text() == "newer\n", "the newer board is kept")
        check((repo / ".claude/lead/board.md").read_text() == STATE_FILES["lead/board.md"], "the older board is kept")
        check((repo / ".kit/evidence/main/notes.txt").exists() and (repo / ".kit/overnight/run1").is_dir(),
              "the other entries moved anyway")
        check(migrate_state.auto(repo) == [], "the next session start says nothing: the same conflict")
        code, out = run(repo, "status")
        check(str(repo / ".claude/lead") in out and str(repo / ".kit/lead") in out and "merge what you need" in out,
              f"status always lists it, with what to do: {out}")
        code, out = run(repo, "migrate")
        check(code == 3 and "both places" in out, f"migrate by hand exits 3 on a conflict left: {code} {out}")
        (repo / ".claude/evidence/main").mkdir(parents=True)  # a second conflict changes the set
        said = migrate_state.auto(repo)
        check(len([s for s in said if "both exist" in s]) == 2, f"a changed set is said again: {said}")
        check(sh(repo, "status", "--porcelain") == "", f"git clean with a conflict left: {sh(repo, 'status', '--porcelain')}")

    # killed after one entry moved: every step after it reads and writes what is there; the next start finishes
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        kill = ("import os, sys; sys.path.insert(0, sys.argv[1]); import migrate_state\n"
                "real = os.rename\n"
                "def once(a, b):\n    real(a, b)\n    os._exit(9)\n"
                "os.rename = once\nmigrate_state.migrate(sys.argv[2])\n")
        died = subprocess.run([sys.executable, "-c", kill, str(SCRIPTS), str(repo)], capture_output=True, text=True)
        check(died.returncode == 9, f"the run died after its first rename: {died.returncode} {died.stderr}")
        check((repo / ".kit/lead/board.md").exists() and (repo / ".claude/evidence").is_dir(), "half moved")
        check(kitlib.state_entry(repo, "lead") == repo / ".kit/lead", "lead read from .kit")
        check(kitlib.state_entry(repo, "evidence") == repo / ".claude/evidence", "evidence read from .claude")
        new = subprocess.run([sys.executable, str(SCRIPTS / "items.py"), "new", "Later"], cwd=str(repo),
                             capture_output=True, text=True, timeout=60)
        check(new.returncode == 0 and (repo / ".kit/lead/items/later/BRIEF.md").exists(), f"items.py new: {new.stdout}{new.stderr}")
        gate = subprocess.run([sys.executable, str(SCRIPTS / "gate.py"), "verify"], cwd=str(repo),
                              capture_output=True, text=True, timeout=120)
        check(gate.returncode == 0 and (repo / ".claude/evidence/main/gate-verify.json").exists(),
              f"gate.py verify records where evidence is: {gate.stdout}{gate.stderr}")
        check(sh(repo, "status", "--porcelain") == "", f"clean while half moved: {sh(repo, 'status', '--porcelain')}")
        said = migrate_state.auto(repo)
        check(any(s.startswith("kit: moved") for s in said), f"the next session start carries on: {said}")
        for rel, text in STATE_FILES.items():  # the board has the new item's row added
            check((repo / ".kit" / rel).read_text().startswith(text), f"{rel} not lost")
        check((repo / ".kit/lead/items/later/BRIEF.md").exists() and (repo / ".kit/evidence/main/gate-verify.json").exists(),
              "what was written half-way moved too")
        check(not (repo / ".claude/lead").exists() and not (repo / ".claude/evidence").exists(), "nothing left behind")
        check(sh(repo, "status", "--porcelain") == "", f"clean after: {sh(repo, 'status', '--porcelain')}")

    # state written in the old place after the move: hidden from git, and a conflict, not a loss
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        run(repo, "migrate")
        (repo / ".claude/evidence/main").mkdir(parents=True)
        (repo / ".claude/evidence/main/late.txt").write_text("late\n")
        (repo / ".claude/overnight/r5").mkdir(parents=True)
        check(sh(repo, "status", "--porcelain") == "", f"a late write stays out of git: {sh(repo, 'status', '--porcelain')}")
        check(kitlib.state_entry(repo, "evidence") == repo / ".kit/evidence", "kitlib keeps reading .kit")
        said = migrate_state.auto(repo)
        check(any("both exist" in s and "evidence" in s for s in said), f"named as a conflict: {said}")
        check((repo / ".claude/evidence/main/late.txt").exists() and (repo / ".kit/evidence/main/notes.txt").exists(),
              "both kept")

    # a .kit.migrating/ left by the first version of this script is emptied into .kit/
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        (repo / ".kit.migrating").mkdir()
        (repo / ".claude/lead").rename(repo / ".kit.migrating/lead")
        code, out = run(repo, "migrate")
        check(code == 0, f"the old staging folder drained: {out}")
        check((repo / ".kit/lead/board.md").exists() and (repo / ".kit/evidence").is_dir(), "both parts in .kit")
        check(not (repo / ".kit.migrating").exists(), "the empty staging folder removed")
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        (repo / ".kit.migrating/lead").mkdir(parents=True)
        (repo / ".kit.migrating/lead/board.md").write_text("staged\n")
        (repo / ".kit.migrating/other.txt").write_text("?\n")
        code, out = run(repo, "migrate")
        check(code == 3 and (repo / ".kit.migrating/lead/board.md").read_text() == "staged\n",
              f"a staged entry beside a moved one is a conflict, kept: {code} {out}")
        check((repo / ".kit.migrating/other.txt").exists(), "a folder still holding files stays")

    # across filesystems: copy, compare, then delete the source
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "a" / "lead", Path(tmp) / "b" / "lead"
        (src / "items").mkdir(parents=True)
        (src / "items" / "x.md").write_text("x\n")
        real = os.rename
        calls = []

        def exdev(a, b):
            calls.append(a)
            if len(calls) == 1:
                raise OSError(errno.EXDEV, "cross-device link")
            real(a, b)
        os.rename = exdev
        try:
            how = migrate_state.move(src, dst)
        finally:
            os.rename = real
        check(how == "moved" and (dst / "items/x.md").read_text() == "x\n" and not src.exists(), f"copied then deleted: {how}")
        check(not dst.with_name("lead.copying").exists(), "no copy left beside it")
        check(migrate_state.move(src, dst) == "gone", "a source already gone was moved by someone else: no conflict")

    # the custom board path inside .claude/lead follows the move
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        (repo / ".claude/kit.json").write_text('{"verify": "true", "lead": {"board": ".claude/lead/BOARD.md"}}\n')
        (repo / ".claude/lead/BOARD.md").write_text("| C1 | ship | c | DONE WHEN z | ready | - | - | from lead |\n")
        run(repo, "migrate")
        config, _ = kitlib.load_config(repo)
        check(kitlib.board_file(repo, config) == repo / ".kit/lead/BOARD.md", kitlib.board_file(repo, config))
        listed = subprocess.run([sys.executable, str(SCRIPTS / "items.py"), "list"], cwd=str(repo),
                                capture_output=True, text=True, timeout=60)
        check(listed.returncode == 0 and "b1" in listed.stdout.lower(), f"items.py finds the items: {listed.stdout}{listed.stderr}")

    # a linked worktree's evidence and runs move inside that worktree; git stays clean in both
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        tree = Path(tmp) / "wt"
        sh(repo, "worktree", "add", "-q", "-b", "side", str(tree))
        (tree / ".claude/overnight/r9").mkdir(parents=True)
        (tree / ".claude/overnight/r9/end-state.json").write_text("{}")
        (tree / ".claude/evidence/side").mkdir(parents=True)
        (tree / ".claude/evidence/side/e2e.txt").write_text("pass\n")
        (tree / ".claude/lead").mkdir()  # only the main checkout's lead is state
        clean = (sh(repo, "status", "--porcelain"), sh(tree, "status", "--porcelain"))
        check(clean == ("", ""), f"clean before: {clean}")
        code, out = run(tree, "migrate")
        check(code == 0, f"run from a worktree: {out}")
        check((tree / ".kit/overnight/r9/end-state.json").exists(), "the worktree's runs moved in place")
        check((tree / ".kit/evidence/side/e2e.txt").read_text() == "pass\n", "the worktree's evidence moved in place")
        check((tree / ".claude/lead").is_dir() and not (tree / ".kit/lead").exists(), "a worktree's lead is not moved")
        check((repo / ".kit/lead/board.md").exists(), "the main checkout's lead moved")
        clean = (sh(repo, "status", "--porcelain"), sh(tree, "status", "--porcelain"))
        check(clean == ("", ""), f"clean after: {clean}")
        code, out = run(repo, "undo")
        check(code == 0 and (tree / ".claude/overnight/r9").is_dir() and (tree / ".claude/evidence/side").is_dir(),
              f"undo brings the worktree's state back: {out}")

    # a fresh project: nothing to move, nothing made, and a session start writes nothing
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "fresh"
        repo.mkdir()
        sh(repo, "init", "-q")
        code, out = run(repo, "migrate")
        check(code == 0 and "nothing to move" in out and not (repo / ".kit").exists(), f"fresh: {out}")
        check(migrate_state.auto(repo) == [] and not (repo / ".kit").exists(), "auto: silent, nothing made")

    # a project already on .kit/ with evidence tracked there: no exclude line hides it
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "new"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        (repo / ".kit/evidence/main").mkdir(parents=True)
        (repo / ".kit/evidence/main/proof.txt").write_text("pass\n")
        (repo / ".kit/lead").mkdir()
        (repo / ".kit/lead/board.md").write_text("")
        sh(repo, "add", ".kit/evidence")
        sh(repo, "commit", "-qm", "evidence in git")
        wanted = migrate_state.exclude_wanted(repo, with_files=False)
        check("/.kit/lead/" in wanted and not any("evidence" in l for l in wanted), f"new layout, tracked: {wanted}")

    # a .claude/ that holds only kit state: it goes, no note is written, the moved line is said
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "only"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        (repo / "README.md").write_text("x\n")
        sh(repo, "add", "README.md")
        sh(repo, "commit", "-qm", "init")
        (repo / ".claude/evidence/main").mkdir(parents=True)
        (repo / ".claude/evidence/main/notes.txt").write_text("pass\n")
        lines = migrate_state.auto(repo)
        check(any("moved this project's kit state (evidence)" in l for l in lines), f"moved line: {lines}")
        check(not any("did not move" in l for l in lines), f"no false failure: {lines}")
        check((repo / ".kit/evidence/main/notes.txt").exists() and not (repo / ".claude").exists(),
              "the emptied .claude/ is gone and not made again for a note")
        check(sh(repo, "status", "--porcelain") == "", f"git clean: {sh(repo, 'status', '--porcelain')}")

    # .kit is a symlink in the main checkout: it is not the kit's folder; nothing is written
    # through it, the link is excluded, a worktree's own state still moves, and it is said once
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        tree = Path(tmp) / "wt"
        sh(repo, "worktree", "add", "-q", "-b", "side", str(tree))
        (tree / ".claude/evidence/side").mkdir(parents=True)
        (tree / ".claude/evidence/side/e2e.txt").write_text("pass\n")
        elsewhere = Path(tmp) / "elsewhere"
        elsewhere.mkdir()
        (repo / ".kit").symlink_to(elsewhere)
        check(kitlib.state_dir(repo) == repo / ".claude", f"a linked .kit is not where new state goes: {kitlib.state_dir(repo)}")
        check(kitlib.state_entry(repo, "lead") == repo / ".claude/lead", "nor where state is read")
        first = migrate_state.auto(repo)
        check(any("is a symlink" in l and "stays on .claude/" in l for l in first), f"said why: {first}")
        check(list(elsewhere.iterdir()) == [], f"nothing written through the link: {list(elsewhere.iterdir())}")
        check((repo / ".claude/lead/board.md").exists() and (tree / ".kit/evidence/side/e2e.txt").exists(),
              "the main checkout stays, the worktree's evidence moved")
        check("/.kit" in exclude_lines(repo), "the link itself is excluded")
        clean = (sh(repo, "status", "--porcelain"), sh(tree, "status", "--porcelain"))
        check(clean == ("", ""), f"git clean in both: {clean}")
        check(migrate_state.auto(repo) == [], "said once")
        code, out = run(repo, "migrate")
        check(code == 0 and "is a symlink" in out and list(elsewhere.iterdir()) == [], f"by hand too: {out}")
        _, out = run(repo, "status")
        check("to move:" not in out, f"status agrees: {out}")

    # a fresh project whose .kit is a symlink: it stays on .claude/, the link is excluded, said once
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "fresh"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        elsewhere = Path(tmp) / "elsewhere"
        elsewhere.mkdir()
        (repo / ".kit").symlink_to(elsewhere)
        check(kitlib.state_dir(repo) == repo / ".claude", "fresh, linked .kit: new state goes to .claude/")
        first = migrate_state.auto(repo)
        check(len(first) == 1 and "stays on .claude/" in first[0], f"said: {first}")
        check(migrate_state.auto(repo) == [] and list(elsewhere.iterdir()) == [], "once, nothing written through it")
        check(sh(repo, "status", "--porcelain") == "", f"git clean: {sh(repo, 'status', '--porcelain')}")

    # .claude/lead is a symlink (to a shared folder) beside movable entries: the others move and
    # are excluded, the link gets no line of its own and is said once; migrate and status agree
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        shared = Path(tmp) / "shared-lead"
        os.rename(repo / ".claude/lead", shared)
        (repo / ".claude/lead").symlink_to(shared)
        before_status = sh(repo, "status", "--porcelain")
        first = migrate_state.auto(repo)
        check(any("moved this project's kit state" in l and "kit-verifier" in l for l in first), f"moved: {first}")
        check(any(".claude/lead was not moved" in l and "a symlink" in l for l in first), f"the link said: {first}")
        check((repo / ".kit/agent-memory/kit-verifier/MEMORY.md").exists() and (repo / ".kit/evidence").is_dir()
              and (repo / ".kit/overnight").is_dir(), "every other entry moved")
        check((repo / ".claude/lead").is_symlink() and (shared / "board.md").exists(), "the link left as it was")
        lines = exclude_lines(repo)
        check(all(l in lines for l in ("/.kit/evidence/", "/.kit/overnight/", "/.kit/agent-memory/kit-verifier/",
                                       "/.kit/migration.json", "/.claude/kit-state-moved.txt")), f"excluded: {lines}")
        check(not any("lead" in l for l in lines if l not in EXCLUDE), f"no line of the link's own: {lines}")
        check(sh(repo, "status", "--porcelain") == before_status, f"git status as before: {sh(repo, 'status', '--porcelain')!r}")
        check(migrate_state.auto(repo) == [], "said once")
        code, out = run(repo, "migrate")
        _, listed = run(repo, "status")
        check(code == 0 and "to move:" not in listed, f"nothing left to move, and status agrees: {code} {out} {listed}")

    # .claude/agent-memory is a symlink to a folder several checkouts share: lead and the rest
    # move, the shared folder keeps kit-verifier, the link is said once over three starts, and
    # gets no line of its own; the owner ignores the link (as before any move): git stays clean
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        shared = Path(tmp) / "shared-memory"
        os.rename(repo / ".claude/agent-memory", shared)
        (repo / ".claude/agent-memory").symlink_to(shared)
        with (repo / ".git/info/exclude").open("a") as f:
            f.write("/.claude/agent-memory\n")
        check(sh(repo, "status", "--porcelain") == "", "clean before")
        starts = [migrate_state.auto(repo) for _ in range(3)]
        check(any("moved this project's kit state" in l and "lead" in l and "kit-verifier" not in l
                  for l in starts[0]), f"lead moved, not the shared memory: {starts[0]}")
        check(any("kit-verifier was not moved" in l and "agent-memory is a symlink" in l for l in starts[0]),
              f"the link said: {starts[0]}")
        check(starts[1:] == [[], []], f"said once over three starts: {starts}")
        check((shared / "kit-verifier/MEMORY.md").read_text() == "verifier notes\n"
              and (shared / "other/MEMORY.md").exists(), f"the shared folder keeps it: {list(shared.iterdir())}")
        check((repo / ".kit/lead/board.md").exists() and not (repo / ".kit/agent-memory").exists(), "only lead's side moved")
        lines = exclude_lines(repo)
        check(not any("agent-memory" in l for l in lines if l not in EXCLUDE + ["/.claude/agent-memory"]),
              f"no line of the link's own: {lines}")
        check(sh(repo, "status", "--porcelain") == "", f"git clean: {sh(repo, 'status', '--porcelain')!r}")
        code, out = run(repo, "migrate")
        check(code == 0 and "agent-memory is a symlink" in out, f"migrate says why it stays: {code} {out}")
        code, out = run(repo, "undo")
        check(code == 0 and (shared / "kit-verifier/MEMORY.md").exists(), f"undo leaves the shared folder: {out}")

    # .claude itself is a symlink: nothing moves, nothing is written through it, said once
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        shared = Path(tmp) / "shared-claude"
        os.rename(repo / ".claude", shared)
        (repo / ".claude").symlink_to(shared)
        before = sorted(str(p.relative_to(shared)) for p in shared.rglob("*"))
        starts = [migrate_state.auto(repo) for _ in range(3)]
        check(not any("moved this project" in l for l in starts[0])
              and any("/.claude is a symlink" in l for l in starts[0]), f"said why: {starts[0]}")
        check(starts[1:] == [[], []], f"said once: {starts}")
        check(not (repo / ".kit").exists() and sorted(str(p.relative_to(shared)) for p in shared.rglob("*")) == before,
              "nothing moved or written")
        code, out = run(repo, "migrate")
        check(code == 0 and "nothing to move: what is left in place above stays in .claude/" in out, f"migrate: {out}")

    # migrate with the main checkout's .kit a symlink says where the state is and why it stays
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        elsewhere = Path(tmp) / "elsewhere"
        elsewhere.mkdir()
        (repo / ".kit").symlink_to(elsewhere)
        code, out = run(repo, "migrate")
        check(code == 0 and "the state stays in .claude/, because" in out and ".kit is a symlink" in out
              and "the state is in .kit/" not in out and list(elsewhere.iterdir()) == [], f"migrate: {out}")

    # when the exclude line cannot be added, an entry still to move is a failure: migrate does
    # not say "nothing to move" or exit 0, status lists it, and a session start says it once
    with tempfile.TemporaryDirectory() as tmp:
        repo = project(tmp)
        real = kitlib.add_exclude_lines
        kitlib.add_exclude_lines = lambda root, lines: []
        try:
            lines = []
            code, _, _, failed_ = migrate_state.migrate(repo, out=lines.append)
            told = migrate_state.auto(repo)
            again = migrate_state.auto(repo)
        finally:
            kitlib.add_exclude_lines = real
        check(code == 1 and failed_ and not any("nothing to move" in l for l in lines), f"migrate: {code} {lines}")
        check(not (repo / ".kit/lead").exists() and (repo / ".claude/lead/board.md").exists(), "nothing moved unhidden")
        _, listed = run(repo, "status")
        check("to move:" in listed, f"status lists them: {listed}")
        check(any("did not move" in l and "could not take its line" in l for l in told), f"said: {told}")
        check(again == [], f"said once: {again}")

    # a shared .gitignore that listed the old places: the note names the .kit/ line for each of
    # those, and says the exclude covers only this machine; it never edits .gitignore
    for name, ignore, want in (
            ("gi-some", "# kit\n.claude/lead/\n/.claude/evidence\n.claude/settings.local.json\n",
             ".kit/lead/ .kit/evidence/."),
            ("gi-whole", ".claude/\n", ".kit/lead/ .kit/evidence/ .kit/overnight/ .kit/agent-memory/kit-verifier/."),
            ("gi-none", "node_modules/\n", None)):
        with tempfile.TemporaryDirectory() as tmp:
            repo = project(tmp, name)
            (repo / ".gitignore").write_text(ignore)
            said = []
            code, _, _, _ = migrate_state.migrate(repo, out=said.append)
            notes = [l for l in said if l.startswith("note: .gitignore")]
            if want is None:
                check(code == 0 and notes == [], f"{name}: no note: {said}")
            else:
                check(code == 0 and len(notes) == 1 and f"add these lines there for the team (the kit does not "
                      f"edit .gitignore): {want}" in notes[0]
                      and "only on this machine, through .git/info/exclude" in notes[0], f"{name}: {said}")
            check((repo / ".gitignore").read_text() == ignore, f"{name}: .gitignore untouched")

    # two session starts at once, many times: the owner's lines stay, no line is cut, no false
    # conflict, and the runs log keeps the winner's entry
    session_start = SCRIPTS / "session_start.py"
    lost, cut, false_conflict, no_run, dirty = 0, 0, 0, 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env.update(HOME=tmp, KIT_HEADLESS="1")
        for i in range(20):
            repo = project(tmp, f"race{i}")
            (repo / ".claude/kit.json").write_text('{"verify": "true"}\n')
            ex = repo / ".git/info/exclude"
            with ex.open("a") as f:
                f.write("/owner-secret.env\n/notes-private/\n")
            (repo / "owner-secret.env").write_text("k\n")
            before = ex.read_text().splitlines()
            payload = json.dumps({"cwd": str(repo), "source": "startup", "session_id": "s", "hook_event_name": "SessionStart"})
            procs = [subprocess.Popen([sys.executable, str(session_start)], cwd=str(repo), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
                     for _ in range(2)]
            outs = [p.communicate(payload, timeout=60)[0] for p in procs]
            text = ex.read_text()
            after = text.splitlines()
            lost += any(l not in after for l in before)
            cut += not text.endswith("\n") or any(l and not (l.startswith(("/", "#"))) for l in after)
            false_conflict += any("both exist" in o for o in outs)
            runs = json.loads((repo / ".kit/migration.json").read_text()).get("runs", [])
            no_run += not any(r.get("moved") for r in runs)
            dirty += sh(repo, "status", "--porcelain") != ""
    check((lost, cut, false_conflict, no_run, dirty) == (0, 0, 0, 0, 0),
          f"of 20 races: lost {lost}, cut {cut}, false conflict {false_conflict}, no run logged {no_run}, dirty {dirty}")

    print("migrate_state: all checks passed" if not failed else f"migrate_state: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
