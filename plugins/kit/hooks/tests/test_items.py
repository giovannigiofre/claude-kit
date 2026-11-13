#!/usr/bin/env python3
"""Self-check for items.py and the SubagentStop filing: an item is a folder the hooks fill.

Run: python3 plugins/kit/hooks/tests/test_items.py   (exit 0 = all good)
"""

import json
import re
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import items  # noqa: E402
import permission  # noqa: E402


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


def git(repo, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def commit_file(repo, branch, name, text, start="main"):
    git(repo, "checkout", "-q", "-B", branch, start)
    (Path(repo) / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-qm", f"{branch}: {name}")
    git(repo, "checkout", "-q", "main")


def usage_row(mid, stamp, tokens, tool=None):
    content = [{"type": "tool_use", "id": tool, "name": "Bash", "input": {}}] if tool else [{"type": "text", "text": "hm"}]
    return {"type": "assistant", "timestamp": stamp, "requestId": "req_" + mid,
            "message": {"id": mid, "content": content,
                        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1],
                                  "cache_read_input_tokens": tokens[2], "cache_creation_input_tokens": tokens[3]}}}


def snapshot_checks(tmp, check):
    """cost lines, status, conflicts, DEPENDS and done's merge check, on a real repository."""
    home = tmp / "home"
    (home / ".claude").mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), TMPDIR=str(tmp))
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / ".claude" / "lead").mkdir(parents=True)  # a project from before the move to .kit
    (repo / ".claude" / "kit.json").write_text("{}")
    (repo / "app.py").write_text("x = 1\n")
    git(repo, "add", "app.py")
    git(repo, "commit", "-qm", "init")
    lead = repo / ".claude" / "lead"

    run(repo, "new", "Login", "--brief", "-", stdin="GOAL: login\nDONE WHEN: e2e\n", env=env)
    run(repo, "new", "Footer", "--brief", "-", stdin="GOAL: footer\nDEPENDS: login, `search`\n", env=env)
    run(repo, "new", "Search", env=env)

    # the token ledger: a reply written as two lines (one per content block) counts once
    t1 = tmp / "agent-a1.jsonl"
    rows = [{"type": "user", "timestamp": "2026-11-13T10:00:00.000Z", "message": {"role": "user", "content": "ITEM: login\ngo"}},
            usage_row("m1", "2026-11-13T10:00:05.100Z", (3, 100, 1000, 500), tool="t1"),
            usage_row("m1", "2026-11-13T10:00:06.000Z", (3, 100, 1000, 500)),
            usage_row("m2", "2026-11-13T10:12:30.000Z", (2, 50, 2000, 10), tool="t2"),
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "SubagentHandback",
                                                           "input": {"message": "STATUS: done\nBRANCH / PR: `feat/login`, PR #12"}}]}}]
    t1.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    hook(repo, {"cwd": str(repo), "agent_type": "kit:implementer", "agent_id": "a1",
                "agent_transcript_path": str(t1), "last_assistant_message": ""}, env)
    log = (lead / "items" / "login" / "LOG.md").read_text()
    check("| cost | in=5 out=150 cache_read=3000 cache_write=510 tools=3 minutes=12.5 agent=a1\n" in log, log)
    check(log.rstrip().splitlines()[-1].split(" | ")[1] == "reported", f"the report stays the last event: {log}")
    # a transcript without usage records: no cost line, the hook still files the report
    t2 = tmp / "agent-a2.jsonl"
    transcript(t2, "ITEM: search\ngo", handback="STATUS: partial\nOPEN: needs push")
    code, err = hook(repo, {"cwd": str(repo), "agent_type": "kit:implementer", "agent_id": "a2",
                            "agent_transcript_path": str(t2), "last_assistant_message": ""}, env)
    log2 = (lead / "items" / "search" / "LOG.md").read_text()
    check(code == 0 and "| cost |" not in log2 and "| reported | partial" in log2, f"no usage, no cost line: {log2} {err}")
    # the same thread resumed: its transcript grew, the new line is its total and replaces the old one
    t1.write_text(t1.read_text() + json.dumps(usage_row("m3", "2026-11-13T10:20:00.000Z", (1, 10, 0, 0))) + "\n")
    hook(repo, {"cwd": str(repo), "agent_type": "kit:implementer", "agent_id": "a1",
                "agent_transcript_path": str(t1), "last_assistant_message": ""}, env)
    snap = items.snapshot(repo)
    login = next(r for r in snap["items"] if r["id"] == "login")
    check(login["cost"] == {"in": 6, "out": 160, "cache_read": 3000, "cache_write": 510, "tools": 3, "minutes": 20.0,
                            "threads": 1}, f"status counts a thread's latest cost line only: {login['cost']}")
    check(login["agent"] == "a1" and login["branch"] == "feat/login" and login["pr"] == "#12",
          f"agent, branch and PR from the LOG and REPORT.md: {login}")
    check(login["status"] == "reported" and login["last_event"] == "reported" and login["kind"] == "ship"
          and 0 <= login["age_minutes"] < 5, login)

    # DEPENDS: blocked while a dependency is not done
    footer = next(r for r in snap["items"] if r["id"] == "footer")
    check(footer["blocked_by"] == ["login", "search"], footer)
    code, out, _ = run(repo, "list", env=env)
    check("footer | queued | GOAL: footer | from lead | blocked-by login, search" in out, out)
    check(snap["counts"] == {"queued": 1, "reported": 2} and snap["questions"] is None, f"no board, no questions: {snap}")

    # NEEDS YOU: a `;` inside a question stays in it; entries split only where a known id starts
    (lead / "board.md").write_text("SHIP: pr\nNEEDS YOU: login: eu-west; or us-east?; footer: merge now; note: it is big\n"
                                   "pr-9 | ship | x | DONE WHEN y | review | agent - | - | -\n")
    code, out, _ = run(repo, "status", "--json", env=env)
    data = json.loads(out)
    check(data["questions"] == [{"id": "login", "question": "eu-west; or us-east?"},
                                {"id": "footer", "question": "merge now; note: it is big"}], data["questions"])
    code, out, _ = run(repo, "status", env=env)
    check(code == 0 and "login | ship | reported |" in out and "feat/login #12" in out
          and "footer | ship | queued blocked-by login, search |" in out and "counts: queued 1, reported 2" in out
          and "- login: eu-west; or us-east?" in out, out)
    (lead / "board.md").write_text("NEEDS YOU: none\n")
    check(items.snapshot(repo)["questions"] == [], "NEEDS YOU: none is no question")

    # conflicts: login and search both change app.py, footer changes another file
    commit_file(repo, "feat/login", "app.py", "x = 2\n")
    commit_file(repo, "feat/search", "app.py", "x = 3\n")
    commit_file(repo, "feat/footer", "footer.py", "y = 1\n")
    run(repo, "log", "search", "working", "branch feat/search", env=env)
    run(repo, "log", "footer", "working", "branch `feat/footer`", env=env)
    code, out, _ = run(repo, "conflicts", "login", "footer", env=env)
    check(code == 0 and "clean    login (feat/login) with main" in out
          and "clean    login (feat/login) with footer (feat/footer)" in out, f"two branches that do not conflict: {code} {out}")
    code, out, _ = run(repo, "conflicts", env=env)
    check(code == 1 and "conflict login (feat/login) with search (feat/search): app.py" in out
          and "clean    search (feat/search) with main" in out, f"two that do: {code} {out}")
    git(repo, "checkout", "-q", "-B", "main-moved", "main")
    commit_file(repo, "main", "app.py", "x = 9\n", start="main")
    code, out, _ = run(repo, "conflicts", "footer", "search", env=env)
    check(code == 1 and "conflict search (feat/search) with main: app.py" in out, f"a conflict with the default branch: {out}")
    run(repo, "log", "footer", "working", "branch feat/gone", env=env)
    code, out, _ = run(repo, "conflicts", "footer", env=env)
    check(code == 2 and "no such branch" in out, f"a branch that is not here: could not tell: {code} {out}")
    code, out, _ = run(repo, "conflicts", "nope", env=env)
    check(code == 2 and "no open item nope" in out, out)

    # done: no gh on PATH says the merge state is unknown and archives as before
    bare = tmp / "bin"
    bare.mkdir()
    (bare / "git").symlink_to(subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip())
    nogh = dict(env, PATH=str(bare))
    run(repo, "log", "search", "review", "PR #20 open", env=env)
    code, out, err = run(repo, "done", "search", env=nogh)
    check(code == 0 and "merge state unknown (gh is not installed)" in out and items.find(repo, "search") is not None
          and not (lead / "items" / "search").exists(), f"done without gh: {code} {out} {err}")
    snap = items.snapshot(repo)
    footer = next(r for r in snap["items"] if r["id"] == "footer")
    check(footer["blocked_by"] == ["login"], f"a dependency archived as done no longer blocks: {footer}")
    # a fake gh: an open PR is refused, --force archives it, a merged one goes through
    fake = tmp / "fakebin"
    fake.mkdir()
    (fake / "git").symlink_to(bare / "git")
    (fake / "gh").write_text('#!/bin/sh\nwhile IFS= read -r l || [ -n "$l" ]; do echo "$l"; done < "$FAKE_GH"\n')  # shell builtins only
    (fake / "gh").chmod(0o755)
    answer = tmp / "gh.json"
    withgh = dict(env, PATH=str(fake), FAKE_GH=str(answer))
    answer.write_text('{"state": "OPEN", "mergedAt": null}')
    code, out, err = run(repo, "done", "login", env=withgh)
    check(code == 1 and "PR #12 is open" in err and (lead / "items" / "login").is_dir(), f"an open PR is refused: {code} {err}")
    answer.write_text('{"state": "CLOSED", "mergedAt": null}')
    code, out, err = run(repo, "done", "login", env=withgh)
    check(code == 1 and "closed, not merged" in err, err)
    answer.write_text('{"state": "MERGED", "mergedAt": "2026-11-13T10:00:00Z"}')
    code, out, err = run(repo, "done", "login", env=withgh)
    check(code == 0 and "PR #12 merged." in out and not (lead / "items" / "login").exists(), f"a merged PR: {code} {out} {err}")
    footer = next(r for r in items.snapshot(repo)["items"] if r["id"] == "footer")
    check(footer["blocked_by"] == [], f"every dependency done: unblocked: {footer}")
    run(repo, "log", "footer", "review", "PR #13 open", env=env)
    answer.write_text("not json")
    code, out, _ = run(repo, "done", "footer", env=withgh)
    check(code == 0 and "merge state unknown (gh gave no JSON)" in out, f"a failed check is unknown, never merged: {out}")
    run(repo, "new", "Forced", env=env)
    run(repo, "log", "forced", "review", "PR #14", env=env)
    answer.write_text('{"state": "OPEN"}')
    code, out, _ = run(repo, "done", "--force", "forced", env=withgh)
    check(code == 0 and "is open, archived with --force" in out, out)


def fresh_project_checks(tmp, check):
    """A project with only kit.json: every command writes under .kit/, from a worktree too, and
    git status stays clean."""
    home = tmp / "home"
    (home / ".claude").mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), TMPDIR=str(tmp))
    repo = tmp / "fresh"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "kit.json").write_text("{}")
    (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (repo / ".git" / "info" / "exclude").write_text("/.claude/kit.json\n")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    tree = tmp / "fresh-wt"
    git(repo, "worktree", "add", "-q", "-b", "feat/a", str(tree))
    (tree / "plan.md").write_text("plan\n")
    code, out, err = run(repo, "new", "Alpha", "--brief", "-", stdin="GOAL: a\n", env=env)
    lead = repo / ".kit" / "lead"
    check(code == 0 and (lead / "items" / "alpha" / "BRIEF.md").is_file(), f"new under .kit: {code} {out} {err}")
    code, _, err = run(tree, "log", "alpha", "working", "branch feat/a", env=env)
    code2, _, err2 = run(tree, "put", "alpha", "plan.md", env=env)
    check(code == 0 and code2 == 0 and (lead / "items" / "alpha" / "out" / "plan.md").is_file(), f"log, put: {err} {err2}")
    code, out, _ = run(repo, "status", env=env)
    check(code == 0 and "alpha" in out and "feat/a" in out, f"status: {out}")
    code, out, err = run(repo, "done", "--force", "alpha", env=env)
    check(code == 0 and (lead / "items" / "done" / "alpha").is_dir(), f"done: {code} {out} {err}")
    check(not (repo / ".claude" / "lead").exists() and not (tree / ".kit").exists(), "nothing under .claude or the worktree")
    lines = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    check("/.kit/lead/" in lines and "/.kit/" not in lines, f"one exclude line for lead: {lines}")
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True).stdout
    check(status == "", f"git status clean of kit state: {status!r}")


def away_checks(tmp, check):
    """`away on|off|status` against a temporary config dir, and the session start that clears it."""
    home = tmp / "home"
    cfg = home / ".claude"
    cfg.mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(cfg), TMPDIR=str(tmp))
    env.pop("KIT_HEADLESS", None)
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    settings = cfg / "settings.json"
    settings.write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Bash(npm test)"]}}))

    def start(source="startup", **extra):
        payload = {"cwd": str(repo), "source": source, "session_id": "s1"}
        out = subprocess.run([sys.executable, str(SCRIPTS / "session_start.py")], input=json.dumps(payload),
                             capture_output=True, text=True, timeout=60, env=dict(env, **extra))
        return out.stdout

    code, out, _ = run(repo, "away", "status", env=env)
    check(code == 0 and out == "Away: off.", f"away status off: {out}")
    code, out, _ = run(repo, "away", "on", env=env)
    saved = json.loads(settings.read_text())
    check(code == 0 and out.startswith("Away on") and saved["permissions"]["denyInsteadOfPrompting"] is True
          and saved["permissions"]["allow"] == ["Bash(npm test)"] and saved["model"] == "opus",
          f"away on sets the key beside the others: {out} {saved}")
    check((cfg / "settings.json.kit-away-backup").exists() and (cfg / "kit-away.json").exists(), "backup and marker")
    status = run(repo, "away", "status", env=env)[1]
    check("set by the kit" in status and re.search(r"on since \d{4}-\d\d-\d\d \d\d:\d\d", status), f"away status says since when: {status}")
    check(out.splitlines()[-1] == "The owner is back when he writes: the coordinator runs `I away off` at the user's "
          "next message, before anything else.", f"away on ends with who turns it off: {out}")

    # a compaction, a headless run and a subagent are not the owner coming back
    for source, extra in (("compact", {}), ("startup", {"KIT_HEADLESS": "1"})):
        out = start(source, **extra)
        check("away is off again" not in out and json.loads(settings.read_text())["permissions"].get("denyInsteadOfPrompting"),
              f"away stays on at {source} {extra}: {out}")
    out = start("startup")
    saved = json.loads(settings.read_text())
    check("away is off again" in out and "denyInsteadOfPrompting" not in saved["permissions"]
          and saved["permissions"]["allow"] == ["Bash(npm test)"] and not (cfg / "kit-away.json").exists(),
          f"the next interactive start clears it: {out} {saved}")

    # a stale marker: the owner takes the key out by hand while the marker stays, then sets it again
    # himself. The first read of the state drops the marker, so his later true is his and stays.
    run(repo, "away", "on", env=env)
    marker = cfg / "kit-away.json"
    check({"settings", "since", "hash"} <= set(json.loads(marker.read_text())), f"the marker: {marker.read_text()}")
    mine = json.loads(settings.read_text())
    mine["permissions"].pop("denyInsteadOfPrompting")
    settings.write_text(json.dumps(mine))
    check(run(repo, "away", "status", env=env)[1] == "Away: off." and not marker.exists(), "status drops a marker without its key")
    mine["permissions"]["denyInsteadOfPrompting"] = True
    settings.write_text(json.dumps(mine))
    code, out, _ = run(repo, "away", "off", env=env)
    start("startup")
    check("stays on" in out and json.loads(settings.read_text())["permissions"].get("denyInsteadOfPrompting") is True,
          f"the owner's value set after a stale marker is kept by off and by session start: {out}")
    # a marker that does not match the value written (copied in, or for another settings file) is not the kit's
    marker.write_text(json.dumps({"settings": str(settings), "since": 1, "hash": "0" * 64}))
    check("you set it" in run(repo, "away", "status", env=env)[1], "a marker whose hash differs: the owner's")
    run(repo, "away", "off", env=env)
    check(json.loads(settings.read_text())["permissions"].get("denyInsteadOfPrompting") is True, "and off leaves it")
    marker.unlink()
    settings.write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Bash(npm test)"]}}))

    # a symlinked user settings.json: on and off write through the link, which stays a link
    dot = tmp / "dot-user"
    dot.mkdir()
    (dot / "settings.json").write_text(settings.read_text())
    (dot / "settings.json").chmod(0o640)
    settings.unlink()
    settings.symlink_to(dot / "settings.json")
    run(repo, "away", "on", env=env)
    check(settings.is_symlink() and json.loads((dot / "settings.json").read_text())["permissions"].get("denyInsteadOfPrompting")
          and ((dot / "settings.json").stat().st_mode & 0o777) == 0o640, "away on writes the link's target")
    run(repo, "away", "off", env=env)
    check(settings.is_symlink() and "denyInsteadOfPrompting" not in json.loads((dot / "settings.json").read_text())["permissions"],
          "away off too")
    settings.unlink()
    settings.write_text((dot / "settings.json").read_text())

    # away off after the kit set it; then the owner's own true is never removed
    run(repo, "away", "on", env=env)
    code, out, _ = run(repo, "away", "off", env=env)
    saved = json.loads(settings.read_text())
    check(code == 0 and out.startswith("Away off") and "denyInsteadOfPrompting" not in saved["permissions"], f"away off: {out}")
    settings.write_text(json.dumps({"permissions": {"denyInsteadOfPrompting": True}}))
    code, out, _ = run(repo, "away", "on", env=env)
    check("set permissions.denyInsteadOfPrompting" in out and not (cfg / "kit-away.json").exists(), f"own true: {out}")
    code, out, _ = run(repo, "away", "off", env=env)
    start("startup")
    check("stays on" in out and json.loads(settings.read_text()) == {"permissions": {"denyInsteadOfPrompting": True}},
          f"the owner's own value is kept by off and by session start: {out}")
    check("you set it" in run(repo, "away", "status", env=env)[1], "away status names the owner's value")

    # a settings.json that does not parse is left alone
    settings.write_text('{ "permissions": ')
    code, out, _ = run(repo, "away", "on", env=env)
    check(code == 1 and "nothing was changed" in out and settings.read_text() == '{ "permissions": ', f"broken: {out}")
    check(run(repo, "away", "bogus", env=env)[0] == 2, "away takes on, off or status")

    # sandbox on writes the kit's block beside other keys; a block of the owner's stays; off only says the edit
    local = repo / ".claude" / "settings.local.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps({"permissions": {"allow": ["Bash(make)"]}}))
    code, out, _ = run(repo, "sandbox", "on", env=env)
    block = json.loads(local.read_text())
    sb = block.get("sandbox", {})
    check(code == 0 and out.startswith("Sandbox on") and block["permissions"] == {"allow": ["Bash(make)"]}
          and sb.get("enabled") is True and sb.get("autoAllowBashIfSandboxed") is True
          and sb.get("excludedCommands") == ["git push", "git push *", "git fetch", "git fetch *", "git pull", "git pull *"],
          f"sandbox on: {out} {block}")
    deny = sb.get("filesystem", {}).get("denyRead", [])
    check({"~/.ssh", "~/.config/gh", "~/.netrc", "~/.aws"} <= set(deny), f"denyRead keeps the git credentials too: {deny}")
    check("already on" in run(repo, "sandbox", "on", env=env)[1], "sandbox on twice")
    check("the kit's block" in run(repo, "sandbox", "status", env=env)[1], "sandbox status")
    before = local.read_text()
    code, out, _ = run(repo, "sandbox", "off", env=env)
    check(code == 0 and local.read_text() == before and 'remove the "sandbox" key' in out and str(local) in out,
          f"sandbox off changes nothing and prints the edit: {out}")
    local.write_text(json.dumps({"sandbox": {"enabled": True, "network": {"allowedDomains": ["example.com"]}}}))
    before = local.read_text()
    code, out, _ = run(repo, "sandbox", "on", env=env)
    check("left it as it is" in out and local.read_text() == before, f"an own sandbox block stays: {out}")
    local.write_text("{ broken")
    check(run(repo, "sandbox", "on", env=env)[0] == 1 and local.read_text() == "{ broken", "broken local file left alone")
    # a symlinked settings.local.json (kept in a dotfiles folder): the link stays, its target gets the block
    dot = tmp / "dotfiles"
    dot.mkdir()
    (dot / "local.json").write_text(json.dumps({"model": "opus"}))
    (dot / "local.json").chmod(0o600)
    local.unlink()
    local.symlink_to(dot / "local.json")
    code, out, _ = run(repo, "sandbox", "on", env=env)
    check(code == 0 and local.is_symlink() and json.loads((dot / "local.json").read_text()).get("sandbox", {}).get("enabled")
          and json.loads((dot / "local.json").read_text())["model"] == "opus" and ((dot / "local.json").stat().st_mode & 0o777) == 0o600,
          f"sandbox on writes through the link: {out}")
    local.unlink()


def hold_lock(lock, seconds=10):
    """Another process holding the kit's settings lock file `lock`; returns it once it holds."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen([sys.executable, "-c", "import fcntl, sys, time\n"
                               "f = open(sys.argv[1], 'w'); fcntl.flock(f, fcntl.LOCK_EX)\n"
                               "print('held', flush=True); time.sleep(float(sys.argv[2]))", str(lock), str(seconds)],
                              stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    return holder


def lock_of(target, tmp):
    """The settings lock items.py takes for `target` with TMPDIR=tmp: the kit's temp state folder."""
    import kitlib
    return tmp / "claude-kit" / kitlib.settings_lock_file(target).name


def lock_checks(tmp, check):
    """A busy or unwritable settings lock ends an owner command in one line and exit 1, never a
    traceback. Each file has its own lock in the kit's temp state folder, so a read-only home does
    not stop a write in the config dir or the project, and nothing is left in either."""
    cfg = tmp / "cfg"
    cfg.mkdir()
    settings = cfg / "settings.json"
    settings.write_text(json.dumps({"model": "opus"}))
    repo = tmp / "lockrepo"
    (repo / ".claude").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    local = repo / ".claude" / "settings.local.json"
    env = dict(os.environ, HOME=str(tmp / "home"), CLAUDE_CONFIG_DIR=str(cfg), TMPDIR=str(tmp))
    env.pop("KIT_HEADLESS", None)

    def one_line(code, out, err, want):
        text = out + err
        return code == 1 and "Traceback" not in text and len(text.strip().splitlines()) == 1 and want in text

    # settings.json's lock held for longer than the wait: away on and off say so and change nothing
    holder = hold_lock(lock_of(settings, tmp))
    for action in ("on", "off"):
        code, out, err = run(repo, "away", action, env=env)
        check(one_line(code, out, err, "Try again") and "was not changed" in out, f"away {action} busy: {code} {out} {err}")
    check(json.loads(settings.read_text()) == {"model": "opus"}, "busy: settings.json untouched")
    # settings.local.json has a lock of its own: sandbox on goes ahead while settings.json's is held
    code, out, _ = run(repo, "sandbox", "on", env=env)
    check(code == 0 and json.loads(local.read_text())["sandbox"]["enabled"], f"sandbox's lock is its own: {out}")
    holder.kill()
    holder.wait()
    local.unlink()
    holder = hold_lock(lock_of(local, tmp))
    code, out, err = run(repo, "sandbox", "on", env=env)
    check(one_line(code, out, err, "Try again") and not local.exists(), f"sandbox on busy: {code} {out} {err}")
    holder.kill()
    holder.wait()

    # a home folder where ~/.claude cannot be made: the config dir and the project are written all the same
    ro = dict(env, HOME="/proc/self")
    code, out, err = run(repo, "away", "on", env=ro)
    check(code == 0 and json.loads(settings.read_text())["permissions"]["denyInsteadOfPrompting"] is True,
          f"read-only home, writable config dir: away on: {out} {err}")
    code, out, err = run(repo, "away", "off", env=ro)
    check(code == 0 and "permissions" not in json.loads(settings.read_text()), f"away off: {out} {err}")
    code, out, err = run(repo, "sandbox", "on", env=ro)
    check(code == 0 and local.exists(), f"read-only home: sandbox on: {out} {err}")
    # no config dir of its own either: one line naming the folder that cannot be written
    bare = {k: v for k, v in ro.items() if k != "CLAUDE_CONFIG_DIR"}
    code, out, err = run(repo, "away", "on", env=bare)
    check(one_line(code, out, err, "/.claude cannot be written"), f"away on, no ~/.claude: {code} {out} {err}")
    code, out, err = run(repo, "away", "off", env=bare)
    check(code == 0 and "Away is off" in out, f"away off, no ~/.claude: nothing to change, nothing written: {code} {out} {err}")
    # a lock file that cannot be opened (a folder in its place): one line naming it, the settings untouched
    local.unlink()
    lock = lock_of(local, tmp)
    lock.unlink()
    lock.mkdir()
    code, out, err = run(repo, "sandbox", "on", env=env)
    check(one_line(code, out, err, f"{lock} cannot be written") and not local.exists(),
          f"sandbox on, lock cannot be opened: {code} {out} {err}")
    lock.rmdir()
    # a temp state folder that cannot be made (a file in its place): the same one line
    odd = tmp / "oddtmp"
    odd.mkdir()
    (odd / "claude-kit").write_text("")
    code, out, err = run(repo, "sandbox", "on", env=dict(env, TMPDIR=str(odd)))
    check(one_line(code, out, err, "claude-kit cannot be written") and not local.exists(),
          f"sandbox on, temp state folder cannot be made: {code} {out} {err}")
    # nothing is written beside the files for locking: not in the project, not in the config dir
    check(not list(cfg.glob("*.lock")) and not list((repo / ".claude").glob("*.lock")), "no lock beside the settings")


def lock_place_checks(tmp, check):
    """sandbox on leaves the checkout clean, so an overnight run starts after it; a symlinked
    settings file leaves nothing new in its target's folder; a lock an earlier version left beside
    a settings file goes when the kit next writes that file."""
    repo = tmp / "clean"
    (repo / ".claude").mkdir(parents=True)
    git = ["git", "-C", str(repo), "-c", "user.email=a@b.c", "-c", "user.name=A"]
    subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
    (repo / ".gitignore").write_text(".claude/settings.local.json\n")
    (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "true"}))
    (repo / "f").write_text("x\n")
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "i"], check=True)
    cfg = tmp / "cfg2"
    cfg.mkdir()
    env = dict(os.environ, HOME=str(tmp / "home2"), CLAUDE_CONFIG_DIR=str(cfg), TMPDIR=str(tmp / "t"))
    env.pop("KIT_HEADLESS", None)
    (tmp / "t").mkdir()
    code, out, err = run(repo, "sandbox", "on", env=env)
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--ignored"], capture_output=True, text=True).stdout
    check(code == 0 and status.strip() == "!! .claude/settings.local.json", f"git status after sandbox on: {status!r} {out} {err}")
    overnight = SCRIPTS.parent.parent / "skills" / "overnight" / "scripts" / "overnight.py"
    got = subprocess.run([sys.executable, str(overnight), "tidy the readme", "--dry-run"], cwd=str(repo),
                         capture_output=True, text=True, timeout=60, env=env)
    check(got.returncode == 0 and "not clean" not in got.stdout + got.stderr,
          f"overnight --dry-run starts after sandbox on: {got.returncode} {got.stdout[-300:]} {got.stderr[-300:]}")

    # symlinked settings.local.json and settings.json kept in a dotfiles folder: nothing new beside them
    dot = tmp / "dot2"
    dot.mkdir()
    (dot / "local.json").write_text("{}")
    (dot / "settings.json").write_text("{}")
    local = repo / ".claude" / "settings.local.json"
    local.unlink()
    local.symlink_to(dot / "local.json")
    (cfg / "settings.json").symlink_to(dot / "settings.json")
    code, out, _ = run(repo, "sandbox", "on", env=env)
    check(code == 0, f"sandbox on through the link: {out}")
    for action in ("on", "off"):
        code, out, _ = run(repo, "away", action, env=env)
        check(code == 0, f"away {action} through the link: {out}")
    left = sorted(p.name for p in dot.iterdir())
    check(set(left) <= {"local.json", "settings.json", "settings.json.kit-away-backup"} and "local.json" in left,
          f"only the targets (and away's own backup) in the dotfiles folder: {left}")

    # a kit-settings.lock left beside a file by an earlier version goes at the next write of it
    local.unlink()
    for folder in (repo / ".claude", dot):
        (folder / "kit-settings.lock").write_text("")
    local.symlink_to(dot / "local.json")
    (dot / "local.json").write_text("{}")
    code, out, _ = run(repo, "sandbox", "on", env=env)
    check(code == 0 and not (repo / ".claude" / "kit-settings.lock").exists() and not (dot / "kit-settings.lock").exists(),
          f"the old lock beside the file and beside its target is removed: {out}")


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
        (repo / ".claude" / "lead").mkdir(parents=True)  # a project from before the move to .kit
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

        # put: files copied into the item's out/, by name, logged; from a thread's worktree too
        tree = Path(tmp) / "tree"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "t-put", str(tree)], check=True)
        (tree / "docs").mkdir()
        (tree / "docs" / "plan.py").write_text("print(1)\n")
        code, out, err = run(tree, "put", "login-page", "docs/plan.py")
        check(code == 0 and out == str(folder.resolve() / "out" / "plan.py") or out == str(folder / "out" / "plan.py"),
              f"put from a worktree lands in the main checkout's item: {code} {out} {err}")
        check((folder / "out" / "plan.py").read_text() == "print(1)\n" and not (tree / ".claude").exists(), "copied, nothing made in the worktree")
        check("| note | out: plan.py" in (folder / "LOG.md").read_text(), "put is logged")
        code, _, _ = run(tree, "log", "login-page", "working", "from the worktree")
        check(code == 0 and "| working | from the worktree" in (folder / "LOG.md").read_text(), "log from a worktree reaches the item")
        (tree / "link").symlink_to(home / ".claude")
        for bad in (["put", "login-page", "docs"], ["put", "login-page", "link"], ["put", "nope", "docs/plan.py"], ["put", "login-page"]):
            code, _, err = run(tree, *bad)
            check(code != 0 and err.startswith("items:"), f"refused: {bad} {code} {err}")
        (folder / "out" / "evil").symlink_to(home / ".claude" / "settings.json")
        (tree / "evil").write_text("x")
        code, _, err = run(tree, "put", "login-page", "evil")
        check(code == 1 and not (home / ".claude" / "settings.json").exists(), f"a symlink in out/ is never followed: {code} {err}")
        (folder / "out" / "evil").unlink()
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)], check=True)
        check(permission.allowed(f'python3 "{SCRIPTS / "items.py"}" put login-page docs/plan.py', {}, str(repo)),
              "permission.py lets put run unasked")
        check(not permission.allowed(f'python3 "{SCRIPTS / "items.py"}" put login-page $W/plan.py', {}, str(repo)),
              "a variable in the command keeps the prompt")

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

        # unattended git preferences: per repo, in the main checkout's gitignored kit.local.json.
        # Every run gets the test HOME, so the user's real ~/.claude/settings.json never counts.
        local = repo / ".claude" / "kit.local.json"
        check(items.kitlib.unattended_prefs(repo)[:2] == ({"push": "allow", "rebase": "allow", "merge": "ask"}, False),
              "unset, push and rebase default to allow and merge to ask")
        code, out, _ = run(repo, "unattended", env=env)
        check(code == 0 and out.startswith("UNATTENDED: push=ask rebase=ask merge=ask") and "not set" in out
              and "the defaults" in out and "push: allow by default, but it stays ask until" in out
              and "PROPOSAL" not in out and "ask the user" not in out and not local.exists(),
              f"unset, the defaults print (effective: no allow rule yet), nothing is asked or proposed, nothing written: {out}")
        code, out, _ = run(repo, "unattended", "--proposal", env=env)
        check(code == 0 and "PROPOSAL, not applied" in out and '+      "Bash(git push:*)"' in out
              and "gh pr merge:*" not in out and not local.exists(),
              f"--proposal prints the change for the default allow steps only, and writes nothing: {out}")
        local.write_text("{ broken")
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=ask rebase=ask merge=ask") and "not set" in out, f"a broken file reads as unset: {out}")
        code, _, err = run(repo, "unattended", "push=allow", env=env)
        check(code == 1 and local.read_text() == "{ broken", f"a broken file is never rewritten: {err}")
        local.write_text(json.dumps({"other": 1, "lead": {"unattended": {"push": "ALLOW", "merge": "sometimes"}}}))
        prefs, is_set, _ = items.kitlib.unattended_prefs(repo)
        check(prefs == {"push": "allow", "rebase": "allow", "merge": "ask"} and is_set,
              f"a misspelt or missing value takes its default: {prefs}")
        local.unlink()
        code, out, err = run(repo, "unattended", "rebase=ask", "merge=ask", env=env)
        saved = json.loads(local.read_text())
        check(code == 0 and saved["lead"]["unattended"] == {"push": "allow", "rebase": "ask", "merge": "ask"}, f"saved: {saved} {err}")
        settings = repo / ".claude" / "settings.local.json"
        check(out.startswith("UNATTENDED: push=ask ") and "(from " in out and '"Bash(git push:*)"' in out
              and str(settings) in out and "rebase:*" not in out,
              f"allow without an allow rule stays ask and names the exact rule and file to add: {out}")
        code, out, _ = run(repo, "unattended", "rebase=allow", env=env)
        check(json.loads(local.read_text())["lead"]["unattended"] == {"push": "allow", "rebase": "allow", "merge": "ask"},
              "a later answer keeps the earlier ones")
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", ".claude/kit.local.json"],
                                capture_output=True, text=True).stdout
        check(status == "", f"kit.local.json stays out of git: {status!r}")
        code, _, err = run(repo, "unattended", "push=yes", env=env)
        check(code == 2 and "ask or allow" in err, f"a wrong value is refused: {err}")
        check(not settings.exists(), "the kit never writes permission settings")

        # the owner's allow rules make it allow, unless a deny or ask rule in any scope matches:
        # Claude Code checks deny, then ask, then allow, so settings.local.json cannot override one
        local_rules = json.dumps({"permissions": {"allow": ["Bash(git push:*)", "Bash(git rebase:*)"],
                                                  "deny": ["Bash(git push --force:*)"]}})
        settings.write_text(local_rules)
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=allow rebase=allow merge=ask") and "stays ask" not in out,
              f"allow rules present, a narrower deny not matching: allow: {out}")
        shared = repo / ".claude" / "settings.json"
        rshared = str(shared.resolve().parent / "settings.json")  # the report names the resolved checkout
        shared.write_text(json.dumps({"permissions": {"ask": ["Bash(git push*)", "Bash(git rebase *)", "Bash(gh pr merge*)"]}}))
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=ask rebase=ask merge=ask"), f"a project ask rule wins over the local allow: {out}")
        check('"Bash(git push*)" in ' + rshared in out and '"Bash(git rebase *)" in ' + rshared in out
              and "cannot override" in out and "merge: allow saved" not in out,
              f"it names the ask rule, its file, and that settings.local.json cannot override it: {out}")
        shared.write_text(json.dumps({"permissions": {"deny": ["Bash(git push:*)"]}}))
        user = home / ".claude" / "settings.json"
        user.write_text(json.dumps({"permissions": {"ask": ["Bash(git rebase:*)"]}}))
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=ask rebase=ask") and str(user) in out and '"Bash(git push:*)" in ' + rshared in out,
              f"a deny rule, and an ask rule in the user's settings, keep it at ask too: {out}")
        user.write_text("{ broken")
        shared.unlink()
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=ask rebase=ask") and "does not parse" in out,
              f"a settings file that does not parse keeps it at ask: {out}")
        user.unlink()
        # a home that is a file: settings.json could not be read, which is not the same as not parsing
        homefile = home.parent / "homefile"
        homefile.write_text("")
        odd = {k: v for k, v in env.items() if k != "CLAUDE_CONFIG_DIR"}
        code, out, err = run(repo, "unattended", "push=allow", env=dict(odd, HOME=str(homefile)))
        note = [line for line in out.splitlines() if line.startswith("push:")]
        check(code == 0 and "Traceback" not in out + err and len(note) == 1 and "could not be read" in note[0]
              and "does not parse" not in out, f"an unusable home says settings.json could not be read: {out} {err}")
        check(settings.read_text() == local_rules and json.loads(local.read_text())["lead"]["unattended"]["push"] == "allow",
              "the kit changed no permission settings, and the owner's saved answer stands")
        # the forms the kit prescribes count: an ask rule on just --force-with-lease or --delete-branch blocks the step
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git push:*)", "Bash(git rebase:*)", "Bash(gh pr merge:*)",
                                                                  "Bash(git merge:*)"]}}))
        # merge=allow is the owner's to write: the command refuses it, says where, and changes nothing
        before = local.read_text()
        code, _, err = run(repo, "unattended", "merge=allow", env=env)
        check(code == 2 and "the owner merges" in err and str(local) in err and local.read_text() == before,
              f"unattended merge=allow is refused: {err}")
        code, _, err = run(repo, "unattended", "push=ask", "merge=allow", env=env)
        check(code == 2 and local.read_text() == before, "refused as a whole: push=ask is not saved alongside")
        owner = json.loads(local.read_text())
        owner["lead"]["unattended"]["merge"] = "allow"  # the owner writes it himself
        local.write_text(json.dumps(owner))
        run(repo, "unattended", "rebase=allow", env=env)
        check(json.loads(local.read_text())["lead"]["unattended"]["merge"] == "allow", "a later save keeps the owner's merge=allow")
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=allow rebase=allow merge=allow"), f"all three allowed first: {out}")
        for rules, line in [(["Bash(git push --force*)"], "push=ask rebase=allow merge=allow"),
                            (["Bash(gh pr merge * --delete-branch)"], "push=allow rebase=allow merge=ask"),
                            (["*"], "push=ask rebase=ask merge=ask")]:
            shared.write_text(json.dumps({"permissions": {"ask": rules}}))
            code, out, _ = run(repo, "unattended", env=env)
            check(out.startswith("UNATTENDED: " + line) and f'"{rules[0]}" in {rshared}' in out,
                  f"an ask rule {rules} on a prescribed form keeps that step at ask: {out}")
        # a deny refuses without a prompt, so one on some forms only (a project that forbids force pushes) names them
        shared.write_text(json.dumps({"permissions": {"deny": ["Bash(git push --force*)", "Bash(git push * --force*)"]}}))
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=allow rebase=allow merge=allow") and "refuses git push --force-with-lease" in out
              and "PROPOSAL" not in out, f"a deny on some forms names them and keeps allow, proposing nothing: {out}")
        shared.unlink()
        kit_json = repo / ".claude" / "kit.json"
        kit_before = kit_json.read_text()
        kit_json.write_text(json.dumps({"check": "true", "guard": {"askCommands": [{"pattern": "--force-with-lease"}]}}))
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=ask rebase=allow merge=allow") and "guard.askCommands" in out,
              f"the kit guard's own askCommands counts as an ask: {out}")
        kit_json.write_text(json.dumps({"check": "true", "guard": {"askCommands": [{"pattern": "--force-with-lease"}],
                                                                   "allowCommands": ["^git push"]}}))
        code, out, _ = run(repo, "unattended", env=env)
        check(out.startswith("UNATTENDED: push=allow"), f"unless the guard's allowCommands lets it through: {out}")
        kit_json.write_text(kit_before)
        run(repo, "unattended", "merge=ask", env=env)
        settings.write_text(local_rules)
        for rule, command, want in [("*", "git push", True), ("B*(git push:*)", "git push -u origin b", True),
                                    ("mcp__*", "git push", False), ("Edit", "git push", False),("Bash(git push*)", "git push -u origin b", True), ("Bash(git push:*)", "git push", True),
                                    ("Bash(git push *)", "git push", True), ("Bash(git *)", "git rebase origin/main", True),
                                    ("Bash", "gh pr merge 1", True), ("Bash(*)", "git push", True),
                                    ("Bash(git push:*)", "git pushx", False), ("Bash(git status)", "git push", False),
                                    ("Read(./x)", "git push", False), ("Bash(git push --force:*)", "git push", False)]:
            check(items.kitlib.bash_rule_matches(rule, command) == want, f"rule {rule} vs {command!r}: want {want}")

        # the PROPOSAL for a project that commits ask rules (as one real repo does): printed, never applied
        repo2 = Path(tmp) / "repo2"
        (repo2 / ".claude").mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo2), "init", "-q"], check=True)
        committed = repo2 / ".claude" / "settings.json"
        committed.write_text(json.dumps({"permissions": {"ask": ["Bash(git push*)", "Bash(git reset --hard*)",
                                                                 "Bash(git rebase *)", "Bash(gh pr merge*)"],
                                                         "deny": ["Bash(git push --force*)"]}}, indent=2) + "\n")
        subprocess.run(["git", "-C", str(repo2), "add", ".claude/settings.json"], check=True)
        subprocess.run(["git", "-C", str(repo2), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "commit", "-qm", "settings"], check=True)
        before = committed.read_bytes()
        # the owner allowed all three himself (merge=allow is his to write)
        (repo2 / ".claude" / "kit.local.json").write_text(json.dumps(
            {"lead": {"unattended": {"push": "allow", "rebase": "allow", "merge": "allow"}}}))
        code, out, err = run(repo2, "unattended", env=env)
        check(code == 0 and "PROPOSAL" not in out, f"without --proposal nothing is proposed: {out}")
        code, out, err = run(repo2, "unattended", "--proposal", env=env)
        r2 = str(committed.resolve())
        r2local = str(committed.resolve().parent / "settings.local.json")
        check(code == 0 and out.startswith("UNATTENDED: push=ask rebase=ask merge=ask") and "PROPOSAL, not applied" in out,
              f"blocked steps print a proposal: {out} {err}")
        check(f"- {r2} (committed" in out and 'remove "Bash(git push*)" from permissions.ask' in out
              and 'remove "Bash(git rebase *)" from permissions.ask' in out
              and 'remove "Bash(gh pr merge*)" from permissions.ask' in out and "git reset" not in out.split("PROPOSAL")[1].split("@@")[0],
              f"the proposal names the committed file and each rule to remove, and leaves the others: {out}")
        check(f"--- {r2}" in out and '-      "Bash(git push*)",' in out
              and any(l in out.splitlines() for l in ['       "Bash(git reset --hard*)"', '+      "Bash(git reset --hard*)"']),
              f"the proposal carries the JSON diff: {out}")
        check(f"- {r2local}: add " in out and '+      "Bash(git push:*)"' in out and '+      "Bash(gh pr merge:*)"' in out,
              f"and the allow rules settings.local.json needs: {out}")
        check("from permissions.deny" not in out and '-      "Bash(git push --force*)"' not in out,
              f"a deny rule is never proposed for removal: {out}")
        check(committed.read_bytes() == before and not (repo2 / ".claude" / "settings.local.json").exists(),
              "the proposal changes no settings file")

        # record places: where the project records finished work, saved in the same kit.local.json
        before = json.loads(local.read_text())
        code, out, _ = run(repo, "records", env=env)
        check(code == 0 and out.startswith("RECORDS: not set") and "AGENTS.md" in out and "records set" in out,
              f"records unset says how to find and save them: {out}")
        run(repo, "new", "Records item", env=env)
        code, out, _ = run(repo, "done", "records-item", env=env)
        check(code == 0 and "record places are not set" in out, f"done without records points at them: {out}")
        code, _, err = run(repo, "records", "set", env=env)
        check(code == 2 and "needs the places" in err, f"records set with nothing is refused: {err}")
        code, _, err = run(repo, "records", "add", "x", env=env)
        check(code == 2, f"an unknown records verb is refused: {err}")
        code, out, _ = run(repo, "records", "set", "GitHub issue: status label off, closing comment",
                           "  plans/progress.json:   the item's state ", env=env)
        check(code == 0 and out.splitlines() == [f"RECORDS (from {local.resolve()}):", "- GitHub issue: status label off, closing comment",
                                                 "- plans/progress.json: the item's state"], f"records set saves and prints: {out}")
        saved = json.loads(local.read_text())
        check({k: v for k, v in saved.items() if k != "lead"} == {k: v for k, v in before.items() if k != "lead"}
              and saved["lead"].get("unattended") == before["lead"].get("unattended") and before["lead"].get("unattended"),
              f"records set keeps the file's other settings: {saved}")
        run(repo, "new", "Records item two", env=env)
        code, out, _ = run(repo, "done", "records-item-two", env=env)
        check(code == 0 and out.splitlines()[1:] == ["- [ ] GitHub issue: status label off, closing comment",
                                                     "- [ ] plans/progress.json: the item's state"],
              f"done lists the records as a checklist: {out}")
        code, out, _ = run(repo, "records", "set", "only one", env=env)
        check(items.kitlib.records(repo)[0] == ["only one"], "records set replaces the list")
        text = local.read_text()
        local.write_text("[1]")
        code, _, err = run(repo, "records", "set", "x", env=env)
        check(code == 1 and local.read_text() == "[1]", f"a file that is not an object is never rewritten: {err}")
        local.write_text(text)

        # a worktree reads and writes the main checkout's files (a worktree has no kit.local.json of its own)
        wt = Path(tmp) / "wt"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "t", str(wt)], check=True, capture_output=True)
        code, out, _ = run(wt, "unattended", env=env)
        check("push=allow rebase=allow merge=ask" in out and str(local) in out, f"a worktree reads the main checkout's: {out}")
        code, out, _ = run(wt, "records", env=env)
        check(out == f"RECORDS (from {local.resolve()}):\n- only one", f"a worktree reads the main checkout's records: {out}")

    with tempfile.TemporaryDirectory() as tmp:
        snapshot_checks(Path(tmp), check)

    with tempfile.TemporaryDirectory() as tmp:
        away_checks(Path(os.path.realpath(tmp)), check)
    with tempfile.TemporaryDirectory() as tmp:
        lock_checks(Path(os.path.realpath(tmp)), check)

    with tempfile.TemporaryDirectory() as tmp:
        lock_place_checks(Path(os.path.realpath(tmp)), check)

    with tempfile.TemporaryDirectory() as tmp:
        fresh_project_checks(Path(os.path.realpath(tmp)), check)

    print("items: all checks passed" if not failed else f"items: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
