#!/usr/bin/env python3
"""Self-check for items.py and the SubagentStop filing: an item is a folder the hooks fill.

Run: python3 plugins/kit/hooks/tests/test_items.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import items  # noqa: E402


def run(repo, *args, stdin=None, env=None):
    out = subprocess.run([sys.executable, str(SCRIPTS / "items.py"), *args], cwd=str(repo), input=stdin,
                         capture_output=True, text=True, timeout=60, env=env or os.environ)
    return out.returncode, out.stdout.strip(), out.stderr.strip()


def hook(repo, payload, env):
    out = subprocess.run([sys.executable, str(SCRIPTS / "subagent_stop.py")], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=60, env=env)
    return out.returncode, out.stderr


def transcript(path, brief, final_text=None, handback=None):
    rows = [{"type": "user", "message": {"role": "user", "content": brief}}]
    content = []
    if handback:
        content.append({"type": "tool_use", "name": "SubagentHandback", "input": {"message": handback}})
    if final_text:
        content.append({"type": "text", "text": final_text})
    rows.append({"type": "assistant", "message": {"content": content}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL " + str(msg))

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        (home / ".claude").mkdir(parents=True)
        env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), TMPDIR=str(tmp))
        repo = Path(tmp) / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "true"}))

        # new: a folder, BRIEF.md headed by ITEM, the first LOG line; the lead folder is excluded from git
        code, out, err = run(repo, "new", "Login page", "--brief", "-", "--from", "handoff",
                             stdin="BRIEF: a login page\nDONE WHEN: e2e passes\n")
        check(code == 0 and out.startswith("login-page\t"), f"new: {code} {out} {err}")
        folder = repo / ".claude" / "lead" / "items" / "login-page"
        brief = (folder / "BRIEF.md").read_text()
        check(brief.startswith("ITEM: login-page\nKIND: ship\n\nBRIEF: a login page"), brief)
        check("| queued | from handoff" in (folder / "LOG.md").read_text(), "first log line")
        check("/.claude/lead/" in (repo / ".git" / "info" / "exclude").read_text(), "lead folder excluded")
        code, out, _ = run(repo, "new", "Login page")
        check(out.startswith("login-page-2\t"), f"a second item with the same name gets a suffix: {out}")
        check(items.find_id("hello\nITEM: Login-Page\nmore") == "login-page", "find_id is case-insensitive")
        check(items.find_id("no item here") is None, "no id when absent")

        # the hooks file the thread's report and the verifier's verdict under the item
        t1 = Path(tmp) / "thread.jsonl"
        transcript(t1, brief, handback="STATUS: done\nCHANGED: login.py\nDECISION: used cookies, not JWT\nOPEN: none")
        code, err = hook(repo, {"cwd": str(repo), "agent_type": "kit:implementer", "agent_id": "a1",
                               "agent_transcript_path": str(t1), "last_assistant_message": ""}, env)
        check(code == 0, f"implementer hook exits 0: {err}")
        report = (folder / "REPORT.md").read_text()
        check("STATUS: done" in report and "DECISION: used cookies" in report, "REPORT.md filed from the handback")
        check("| reported | done, 1 decision(s)" in (folder / "LOG.md").read_text(), (folder / "LOG.md").read_text())

        t2 = Path(tmp) / "verifier.jsonl"
        transcript(t2, f"ITEM: login-page\nReview branch `feat/login` against: e2e passes",
                   handback="VERDICT: FAIL scope=local:login.py\nEVIDENCE:\n- ran it\nPROBLEMS:\n1. login.py:3 wrong redirect\n")
        code, err = hook(repo, {"cwd": str(repo), "agent_type": "kit:verifier", "agent_id": "v1",
                               "agent_transcript_path": str(t2), "last_assistant_message": ""}, env)
        check(code == 0, f"verifier hook exits 0: {err}")
        check((folder / "VERDICT.md").read_text().startswith("VERDICT: FAIL scope=local:login.py"), "VERDICT.md filed")
        check("| verdict | FAIL scope=local:login.py" in (folder / "LOG.md").read_text(), "verdict logged with its scope")

        # a thread whose brief names no item files nothing
        t3 = Path(tmp) / "other.jsonl"
        transcript(t3, "Implement the footer", final_text="STATUS: done")
        before = sorted(p.name for p in (repo / ".claude" / "lead" / "items").iterdir())
        hook(repo, {"cwd": str(repo), "agent_type": "kit:implementer", "agent_id": "a2",
                    "agent_transcript_path": str(t3), "last_assistant_message": ""}, env)
        after = sorted(p.name for p in (repo / ".claude" / "lead" / "items").iterdir())
        check(before == after, "no item named, nothing filed")

        # list, log, show, done
        code, out, _ = run(repo, "list")
        check("login-page | verdict | BRIEF: a login page" in out and "login-page-2 | queued" in out, out)
        run(repo, "log", "login-page", "review", "PR #7 open")
        code, out, _ = run(repo, "list", "--status", "review")
        check(out.startswith("login-page | review |") and "login-page-2" not in out, out)
        code, out, _ = run(repo, "show", "login-page")
        check("===== BRIEF.md" in out and "===== VERDICT.md" in out and "===== LOG.md" in out, "show prints the files")
        code, out, _ = run(repo, "done", "login-page")
        check(code == 0 and not folder.exists() and (folder.parent / "done" / "login-page" / "LOG.md").exists(), "done archives")
        check(items.find(repo, "login-page") is not None, "an archived item is still found")
        code, out, err = run(repo, "path", "nope")
        check(code == 1 and "no item" in err, "a missing item is an error")

    with tempfile.TemporaryDirectory() as tmp:  # sweep: only clean kit-thread worktrees at a merged PR's head go
        tmp = Path(tmp)

        def g(cwd, *a):
            return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()

        g(tmp, "init", "-q", "--bare", "-b", "main", "origin.git")
        g(tmp, "clone", "-q", str(tmp / "origin.git"), "repo")
        repo = tmp / "repo"
        g(repo, "config", "user.email", "t@example.invalid")
        g(repo, "config", "user.name", "t")
        g(repo, "commit", "-q", "--allow-empty", "-m", "init")
        g(repo, "push", "-q", "origin", "HEAD:main")
        g(repo, "remote", "set-head", "origin", "main")
        (repo / ".git" / "info" / "exclude").write_text(".claude/evidence/\n.claude/lead/\nbuild/\n")
        heads = []

        def wt(name, branch=None, commit=True, where=None, item=True):
            path = where or tmp / f"repo-{name}"  # the kit's <repo>-<id> naming
            if item:  # a done item of that id: the worktree is the kit's
                run(repo, "new", name)
                run(repo, "done", name)
            g(repo, "worktree", "add", "-q", "-b", branch or name, str(path), "origin/main")
            if commit:
                g(path, "commit", "-q", "--allow-empty", "-m", name)
                heads.append({"headRefName": branch or name, "headRefOid": g(path, "rev-parse", "HEAD")})
            return path

        landed = wt("landed")
        fresh = wt("fresh", commit=False)  # a thread that has not committed yet: its tip is main's
        dirty = wt("dirty")
        (dirty / "notes.txt").write_text("unsaved\n")
        hidden = wt("hidden")  # a repo that hides untracked files from git status
        g(repo, "config", "status.showUntrackedFiles", "no")
        (hidden / "notes.txt").write_text("unsaved\n")
        lsfail = wt("lsfail")
        built = wt("built")
        (built / "build").mkdir()
        (built / "build" / "notes.md").write_text("hand-written\n")
        develop = wt("develop", branch="develop")  # gitflow's long-lived branch, at a merged PR's head
        other = wt("other", where=tmp / "elsewhere", item=False)  # not the kit's naming, no item
        experiment = wt("experiment", item=False)  # a hand-made <repo>-x sibling, no item behind it
        run(repo, "new", "k1")  # an isolation worktree whose thread's item is still open: no done item names it
        isolated = wt("agent-ab12", branch="worktree-agent-ab12", where=repo / ".claude" / "worktrees" / "agent-ab12",
                      item=False)
        run(repo, "new", "k2", "--brief", "-", stdin="BRIEF: x\n")  # a done item whose report records its branch
        run(repo, "report", "k2", "-", stdin="STATUS: done\nBRANCH / PR: feat/recorded, PR #3\n")
        run(repo, "done", "k2")
        recorded = wt("agent-cd34", branch="feat/recorded", where=repo / ".claude" / "worktrees" / "agent-cd34",
                      item=False)
        run(repo, "new", "k9")
        opened = wt("k9", item=False)  # its item is still open
        busy = wt("busy")
        proof = Path(".claude", "evidence", "landed", "run.log")
        (landed / proof).parent.mkdir(parents=True)
        (landed / proof).write_text("passed\n")
        fake_gh = tmp / "gh"  # squash-merged PRs: their heads never reach main
        fake_gh.write_text(f"#!/bin/sh\necho '{json.dumps(heads)}'\n")
        fake_gh.chmod(0o755)
        shim = tmp / "bin"
        shim.mkdir()
        real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
        (shim / "git").write_text(f'#!/bin/sh\ncase "$*" in *repo-lsfail*ls-files*) exit 1;; esac\nexec {real} "$@"\n')
        (shim / "git").chmod(0o755)
        env = dict(os.environ, KIT_GH=str(fake_gh), PATH=f"{shim}:{os.environ['PATH']}")
        code, out, err = run(repo, "sweep", "--dry-run", env=env)
        check(code == 0 and "would remove | landed" in out and landed.is_dir(), f"dry run: {out} {err}")
        sleeper = subprocess.Popen(["sleep", "30"], cwd=str(busy))
        try:
            code, out, _ = run(repo, "sweep", env=env)
        finally:
            sleeper.kill()
        branches = g(repo, "branch")
        check("removed | landed" in out and not landed.exists() and "landed" not in branches,
              f"a clean worktree at a merged PR's head goes, with its branch: {out}")
        check((repo / proof).read_text() == "passed\n", "its evidence is copied to the main checkout")
        check("removed | feat/recorded" in out and not recorded.exists(), f"a worktree a done item's report records goes: {out}")
        for name, path, reason in [("fresh", fresh, "kept: no PR merged into main at this tip"),
                                   ("dirty", dirty, "kept: uncommitted or untracked files"),
                                   ("hidden", hidden, "kept: uncommitted or untracked files"),
                                   ("lsfail", lsfail, "kept: ignored file not in the main checkout ((git ls-files failed))"),
                                   ("built", built, "kept: ignored file not in the main checkout (build/notes.md)"),
                                   ("develop", develop, "kept: a long-lived branch"),
                                   ("other", other, "kept: no done item names this worktree"),
                                   ("experiment", experiment, "kept: no done item names this worktree"),
                                   ("worktree-agent-ab12", isolated, "kept: no done item names this worktree"),
                                   ("k9", opened, "kept: item k9 is not done yet"),
                                   ("busy", busy, "kept: a running process works in it")]:
            check(f"{reason} | {name} |" in out and path.is_dir(), f"{name} stays ({reason}): {out}")

    print("items: all checks passed" if not failed else f"items: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
