#!/usr/bin/env python3
"""Self-check for gate.py: the record names the tree the gate ran on, and `status` tells a PR
whose tree was verified from one that changed since.

Run: python3 plugins/kit/hooks/tests/test_gate.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import gate  # noqa: E402
import kitlib  # noqa: E402


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def gate_cmd(repo, *args):
    out = subprocess.run([sys.executable, str(SCRIPTS / "gate.py"), *args], cwd=str(repo),
                         capture_output=True, text=True, timeout=120)
    return out.returncode, out.stdout + out.stderr


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL " + str(msg))

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        sh(repo, "config", "user.email", "t@example.invalid")
        sh(repo, "config", "user.name", "t")
        (repo / "a.txt").write_text("a\n")
        (repo / ".claude" / "evidence").mkdir(parents=True)  # a project from before the move to .kit
        (repo / ".claude" / "kit.json").write_text(json.dumps({
            "check": "echo changed=$KIT_CHANGED_COUNT files=$KIT_CHANGED_FILES > check.log",
            "verify": "test -f a.txt"}))
        (repo / ".gitignore").write_text("check.log\n")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "init")
        sh(repo, "checkout", "-q", "-b", "feat/x")

        # no record yet: not ready
        ok, why = gate.status(repo, "verify")
        check(not ok and "no record" in why, f"no record -> not ready: {why}")

        # a passing verify on a dirty tree: the record carries that tree; the PR check wants it committed
        (repo / "b.txt").write_text("b\n")
        code, out = gate_cmd(repo, "verify")
        check(code == 0 and "passed" in out and "recorded in .claude/evidence/feat/x/gate-verify.json" in out, out)
        rec = json.loads((repo / ".claude" / "evidence" / "feat" / "x" / "gate-verify.json").read_text())
        check(rec["ok"] and rec["gate"] == "verify" and rec["tree"] == gate.tree_hash(repo), "record matches the tree")
        check(rec["changed_files"] == 1, f"b.txt is the one changed file: {rec}")
        ok, why = gate.status(repo, "verify")
        check(not ok and "differs from HEAD" in why and "b.txt" in why, f"dirty tree is not ready: {why}")
        # evidence is kept out of git without touching .gitignore
        check(sh(repo, "status", "--porcelain") == "?? b.txt", "evidence folder excluded: " + sh(repo, "status", "--porcelain"))

        # committed as verified: ready. The commit does not change the content hash
        sh(repo, "add", "b.txt")
        sh(repo, "commit", "-qm", "b")
        ok, why = gate.status(repo, "verify")
        check(ok, f"committed tree equals the verified one: {why}")
        check(gate.tree_hash(repo) == gate.head_tree(repo), "clean tree hashes like HEAD")

        # a change after the run: not ready, and `status` from the command line exits 1
        (repo / "b.txt").write_text("b2\n")
        sh(repo, "commit", "-qam", "b2")
        ok, why = gate.status(repo, "verify")
        check(not ok and "another tree" in why, f"changed since: {why}")
        code, out = gate_cmd(repo, "status")
        check(code == 1 and "not ready" in out, out)
        code, out = gate_cmd(repo, "verify")
        check(code == 0 and gate_cmd(repo, "status")[0] == 0, "re-run makes it ready again")

        # another branch, compared by its committed tree (a PR for a branch not checked out)
        ok, why = gate.status(repo, "verify", branch="feat/x", head_ref="feat/x")
        check(ok, f"by ref: {why}")

        # a failing gate: exit code passes through, the record says so
        (repo / ".claude" / "kit.json").write_text(json.dumps({"verify": "test -f missing.txt"}))
        code, out = gate_cmd(repo, "verify")
        check(code == 1 and "failed (exit 1)" in out, out)
        ok, why = gate.status(repo, "verify")
        check(not ok and "failed" in why, why)

        # check gets the changed files, shell-quoted; a committed branch file counts too
        (repo / ".claude" / "kit.json").write_text(json.dumps({
            "check": "echo count=$KIT_CHANGED_COUNT files=$KIT_CHANGED_FILES > check.log", "verify": "true"}))
        (repo / "sp ace.txt").write_text("x\n")
        code, out = gate_cmd(repo, "check")
        log = (repo / "check.log").read_text().strip()
        check(code == 0 and log == "count=3 files=.claude/kit.json b.txt 'sp ace.txt'", f"changed files env: {log!r}")
        env = kitlib.changed_env(repo)
        check(env["KIT_CHANGED_FILES"] == ".claude/kit.json b.txt 'sp ace.txt'", f"quoted: {env}")
        # a gate that writes into the tree is noticed
        (repo / ".claude" / "kit.json").write_text(json.dumps({"verify": "echo new > made.txt"}))
        code, out = gate_cmd(repo, "verify")
        check("changed files in the tree" in out, out)

        # unknown gate, missing command
        check(gate_cmd(repo, "nope")[0] == 3, "unknown gate exits 3")
        (repo / ".claude" / "kit.json").write_text(json.dumps({"verify": "true"}))
        check(gate_cmd(repo, "check")[0] == 3, "missing command exits 3")

        # from a linked worktree: the gate runs on the worktree's tree and branch, the record lands
        # under the main checkout, where it outlives the worktree
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "gate config")
        tree = Path(tmp) / "wt"
        sh(repo, "worktree", "add", "-q", "-b", "feat/wt", str(tree))
        code, out = gate_cmd(tree, "verify")
        record = repo / ".claude" / "evidence" / "feat" / "wt" / "gate-verify.json"
        check(code == 0 and record.is_file() and str(record) in out, f"worktree record under the main checkout: {out}")
        check(not (tree / ".claude" / "evidence").exists(), "nothing written under the worktree")
        rec = json.loads(record.read_text())
        check(rec["branch"] == "feat/wt" and rec["tree"] == gate.tree_hash(tree), f"the worktree's branch and tree: {rec}")
        ok, why = gate.status(tree, "verify")
        check(ok, f"status from the worktree reads the same record: {why}")
        check(gate_cmd(tree, "status")[0] == 0, "status from the command line in the worktree")
        check(sh(tree, "status", "--porcelain") == "", "the worktree stays clean: " + sh(tree, "status", "--porcelain"))

    # a fresh project (kit.json only): the record goes to .kit/evidence and git stays clean
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "fresh"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        sh(repo, "config", "user.email", "t@example.invalid")
        sh(repo, "config", "user.name", "t")
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text(json.dumps({"verify": "true"}))
        (repo / ".gitignore").write_text(".claude/kit.json\n")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "init")
        code, out = gate_cmd(repo, "verify")
        check(code == 0 and "recorded in .kit/evidence/main/gate-verify.json" in out, out)
        check(not (repo / ".claude" / "evidence").exists(), "nothing new under .claude")
        check(gate.status(repo, "verify")[0], "status reads the .kit record")
        check(sh(repo, "status", "--porcelain") == "", "evidence excluded: " + sh(repo, "status", "--porcelain"))
        check("/.kit/evidence/" in (repo / ".git" / "info" / "exclude").read_text().splitlines(), "its own line")

    print("gate: all checks passed" if not failed else f"gate: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
