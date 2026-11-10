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
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "commit", "-q", "--allow-empty", "-m", "init"], check=True)

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

        # the hooks file the thread's report and the verifier's verdict under the item. The hand-back is
        # the report; the closing text after it (last_assistant_message) is not
        t1 = Path(tmp) / "thread.jsonl"
        transcript(t1, brief, final_text="Report delivered to the coordinator.",
                   handback="STATUS: done\nCHANGED: login.py\nDECISION: used cookies, not JWT\nOPEN: none")
        code, err = hook(repo, {"cwd": str(repo), "agent_type": "kit:implementer", "agent_id": "a1",
                               "agent_transcript_path": str(t1),
                               "last_assistant_message": "Report delivered to the coordinator."}, env)
        check(code == 0, f"implementer hook exits 0: {err}")
        report = (folder / "REPORT.md").read_text()
        check(report.startswith("STATUS: done") and "DECISION: used cookies" in report and "delivered to" not in report,
              f"REPORT.md holds the hand-back, not the closing line: {report!r}")
        check("| reported | done, 1 decision(s), agent a1" in (folder / "LOG.md").read_text(), (folder / "LOG.md").read_text())

        t2 = Path(tmp) / "verifier.jsonl"
        transcript(t2, f"ITEM: login-page\nReview branch `feat/login` against: e2e passes",
                   handback="VERDICT: FAIL scope=local:login.py\nEVIDENCE:\n- ran it\nPROBLEMS:\n1. login.py:3 wrong redirect\n")
        code, err = hook(repo, {"cwd": str(repo), "agent_type": "kit:verifier", "agent_id": "v1",
                               "agent_transcript_path": str(t2), "last_assistant_message": ""}, env)
        check(code == 0, f"verifier hook exits 0: {err}")
        check((folder / "VERDICT.md").read_text().startswith("VERDICT: FAIL scope=local:login.py"), "VERDICT.md filed")
        check("| verdict | FAIL scope=local:login.py, agent v1" in (folder / "LOG.md").read_text(),
              "verdict logged with its scope and agent")
        # a verifier that states the commit it reviewed: noted, not compared
        transcript(t2, "ITEM: login-page\nReview branch `feat/login`",
                   handback="VERDICT: PASS\nREVIEWED: `4a24c23f0e1d`\nEVIDENCE:\n- gate ok\nPROBLEMS:\n- none\n")
        hook(repo, {"cwd": str(repo), "agent_type": "kit:verifier", "agent_id": "v2",
                    "agent_transcript_path": str(t2), "last_assistant_message": ""}, env)
        check("| verdict | PASS, reviewed 4a24c23f0e1d, agent v2" in (folder / "LOG.md").read_text(),
              (folder / "LOG.md").read_text())

        # a thread stopping in its worktree (the hook's cwd) files under the main checkout's item
        tree = Path(tmp) / "repo-wt"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat/wt", str(tree)], check=True)
        t4 = Path(tmp) / "wt-thread.jsonl"
        transcript(t4, "ITEM: login-page-2\nfooter", handback="STATUS: blocked\nOPEN: needs the design")
        code, err = hook(repo, {"cwd": str(tree), "agent_type": "kit:implementer", "agent_id": "a3",
                               "agent_transcript_path": str(t4), "last_assistant_message": ""}, env)
        folder2 = repo / ".claude" / "lead" / "items" / "login-page-2"
        check(code == 0 and (folder2 / "REPORT.md").read_text().startswith("STATUS: blocked"), f"filed from a worktree: {err}")
        check("| reported | blocked, agent a3" in (folder2 / "LOG.md").read_text(), (folder2 / "LOG.md").read_text())
        check(not (tree / ".claude" / "lead").exists(), "nothing created in the worktree")

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
        check("login-page | verdict | BRIEF: a login page" in out and "login-page-2 | reported" in out, out)
        run(repo, "log", "login-page-2", "queued", "re-queued")
        run(repo, "log", "login-page", "review", "PR #7 open")
        code, out, _ = run(repo, "list", "--status", "review")
        check(out.startswith("login-page | review |") and "login-page-2" not in out, out)
        code, out, _ = run(repo, "show", "login-page")
        check("===== BRIEF.md" in out and "===== VERDICT.md" in out and "===== LOG.md" in out, "show prints the files")
        lead = repo / ".claude" / "lead"
        (lead / "board.md").write_text("SHIP: pr\nlogin-page | ship | login | DONE WHEN e2e | review | -\n"
                                       "login-page-2 | ship | footer | DONE WHEN e2e | queued | -\n")
        code, out, _ = run(repo, "done", "login-page")
        check(code == 0 and not folder.exists() and (folder.parent / "done" / "login-page" / "LOG.md").exists(), "done archives")
        check("login-page |" not in (lead / "board.md").read_text() and "login-page-2 |" in (lead / "board.md").read_text()
              and (lead / "archive.md").read_text().startswith("login-page | ship | login"), "done moves the board row")
        check(items.find(repo, "login-page") is not None, "an archived item is still found")
        code, out, err = run(repo, "path", "nope")
        check(code == 1 and "no item" in err, "a missing item is an error")

        # the board exists now: a new item gets a queued row in the lead's format (DONE WHEN from the brief)
        code, out, _ = run(repo, "new", "Search box", "--brief", "-", "--from", "scout", "--kind", "scout",
                           stdin="GOAL: a search box\n- DONE WHEN: results in 200ms\nSCOPE: ui\n")
        rows = (lead / "board.md").read_text().splitlines()
        check(rows[-1] == "search-box | scout | Search box | DONE WHEN results in 200ms | queued | agent - | - | from scout", rows)
        run(repo, "new", "No done line", "--brief", "-", stdin="GOAL: just a goal\n")
        check((lead / "board.md").read_text().splitlines()[-1]
              == "no-done-line | ship | No done line | DONE WHEN see BRIEF.md | queued | agent - | - | from lead",
              (lead / "board.md").read_text())
        check("login-page-2 | ship | footer" in (lead / "board.md").read_text(), "existing rows are kept")

        # done when done/<id> already exists (an item folder made by hand, or from another checkout
        # of the same lead folder): the earlier archive is kept, the new one lands at done/<id>-2, -3
        archived = folder.parent / "done" / "login-page"
        (archived / "REPORT.md").write_text("the first round\n")
        for n in (2, 3):
            folder.mkdir()
            (folder / "BRIEF.md").write_text("ITEM: login-page\nround two\n")
            (folder / "LOG.md").write_text("- 2026-01-01T00:00:00Z | working\n")
            code, out, _ = run(repo, "done", "login-page")
            check(code == 0 and not folder.exists(), f"done round {n}: {code} {out}")
            check((archived / "REPORT.md").read_text() == "the first round\n", "the first archive is untouched")
            check((folder.parent / "done" / f"login-page-{n}" / "LOG.md").read_text().endswith("| done\n"),
                  f"the next archive lands at done/login-page-{n}")

        # unattended git preferences: per repo, in the main checkout's gitignored kit.local.json
        local = repo / ".claude" / "kit.local.json"
        code, out, _ = run(repo, "unattended")
        check(code == 0 and out.startswith("UNATTENDED: push=ask rebase=ask merge=ask") and "not set" in out
              and not local.exists(), f"unattended defaults to ask, unset, and writes nothing: {out}")
        local.write_text("{ broken")
        code, out, _ = run(repo, "unattended")
        check(out.startswith("UNATTENDED: push=ask rebase=ask merge=ask") and "not set" in out, f"a broken file reads as ask: {out}")
        code, _, err = run(repo, "unattended", "push=allow")
        check(code == 1 and local.read_text() == "{ broken", f"a broken file is never rewritten: {err}")
        local.write_text(json.dumps({"other": 1, "lead": {"unattended": {"push": "ALLOW", "merge": "sometimes"}}}))
        prefs, is_set, _ = items.kitlib.unattended_prefs(repo)
        check(prefs == {"push": "allow", "rebase": "ask", "merge": "ask"} and is_set, f"a misspelt value is ask: {prefs}")
        local.unlink()
        code, out, err = run(repo, "unattended", "push=allow", "merge=ask")
        saved = json.loads(local.read_text())
        check(code == 0 and saved["lead"]["unattended"] == {"push": "allow", "rebase": "ask", "merge": "ask"}, f"saved: {saved} {err}")
        check("(from " in out and '"Bash(git push:*)"' in out and "settings.local.json" in out
              and "rebase:*" not in out, f"allow names the exact rule and where, for the owner to add: {out}")
        code, out, _ = run(repo, "unattended", "rebase=allow")
        check(json.loads(local.read_text())["lead"]["unattended"] == {"push": "allow", "rebase": "allow", "merge": "ask"},
              "a later answer keeps the earlier ones")
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", ".claude/kit.local.json"],
                                capture_output=True, text=True).stdout
        check(status == "", f"kit.local.json stays out of git: {status!r}")
        code, _, err = run(repo, "unattended", "push=yes")
        check(code == 2 and "ask or allow" in err, f"a wrong value is refused: {err}")
        # a worktree reads and writes the main checkout's file (a worktree has no kit.local.json of its own)
        wt = Path(tmp) / "wt"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "t", str(wt)], check=True, capture_output=True)
        code, out, _ = run(wt, "unattended")
        check("push=allow rebase=allow merge=ask" in out and str(local) in out, f"a worktree reads the main checkout's: {out}")
        settings = repo / ".claude" / "settings.local.json"
        check(not settings.exists(), "the kit never writes permission settings")

    print("items: all checks passed" if not failed else f"items: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
