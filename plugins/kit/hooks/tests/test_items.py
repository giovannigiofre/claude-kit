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

    print("items: all checks passed" if not failed else f"items: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
