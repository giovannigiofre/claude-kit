#!/usr/bin/env python3
"""Self-check for session_start.py.

Run: python3 plugins/kit/hooks/tests/test_session_start.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "session_start.py"


HOME = Path(tempfile.mkdtemp())  # a machine that already has the kit's settings
(HOME / ".claude").mkdir()
(HOME / ".claude" / "kit.json").write_text(json.dumps({"machineSetup": "declined"}))


def run(payload, home=HOME, **env):
    out = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30,
                         env={**os.environ, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(Path(home) / ".claude"), **env})
    assert out.returncode == 0, out.stderr
    return out.stdout


def main():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        (repo / ".claude" / "lead").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)

        assert run({"cwd": str(repo), "source": "startup"}) == "", "no kit.json, no board: silent, no coordinator"

        board = "SHIP: pr | PARALLEL: 3 | BUDGET: none\nA1 | ship | login | DONE WHEN e2e | working | agent A1 | feat/login | -\n"
        (repo / ".claude" / "lead" / "board.md").write_text(board)
        assert run({"cwd": str(repo), "source": "startup"}) == "", "the board comes back only after a compaction"
        out = run({"cwd": str(repo), "source": "compact"})
        assert "just compacted" in out and "A1 | ship | login" in out, out
        rows = "".join(f"B{i} | ship | goal {i} | DONE WHEN ok | done | - | - | -\n" for i in range(70))
        (repo / ".claude" / "lead" / "board.md").write_text("SHIP: pr\nRULES: " + "x; " * 3000 + "\n" + board + rows)
        out = run({"cwd": str(repo), "source": "compact"})
        assert "A1 | ship | login" in out and "B69 | ship" in out and "(cut: RULES" in out, "rows come back, RULES is cut"
        assert "over its 60-line" in out, "an oversized board is flagged"
        (repo / ".claude" / "lead" / "board.md").write_text(board)

        (repo / ".claude" / "kit.json").write_text(json.dumps({
            "check": "make lint", "verify": "make test",
            "protect": [{"glob": "data/raw/**", "mode": "no-overwrite", "reason": "immutable"}],
            "lead": {"board": "docs/board.md", "notes": "one group per worker"},
        }))
        out = run({"cwd": str(repo), "source": "startup"})
        assert "make lint" in out and "make test" in out and "data/raw/**" in out and "one group per worker" in out, out
        out = run({"cwd": str(repo), "source": "compact"})
        assert "A1 | ship" not in out, "lead.board moves the board; the default path is not read"
        (repo / "docs").mkdir()
        (repo / "docs" / "board.md").write_text("SHIP: local | PARALLEL: 1 | BUDGET: none\n")
        assert "SHIP: local" in run({"cwd": str(repo), "source": "compact"})

        # a permission rule that asks before push, rebase or merge is named, with its file, once
        assert "permission rules ask" not in out, "no ask rule, no line"
        settings = repo / ".claude" / "settings.json"
        settings.write_text(json.dumps({"permissions": {
            "allow": ["Bash(git status*)"], "deny": ["Bash(git push --force*)"],
            "ask": ["Bash(git push*)", "Bash(git reset --hard*)", "Bash(git rebase *)", "Bash(gh pr merge*)"]}}))
        out = run({"cwd": str(repo), "source": "startup"})
        line = next(l for l in out.splitlines() if "permission rules ask" in l)
        assert "push, rebase, merge here" in line and "`Bash(git push*)`" in line and "`Bash(gh pr merge*)`" in line, line
        assert "in .claude/settings.json" in line and "reset" not in line and "force" not in line, line
        settings.write_text(json.dumps({"permissions": {"ask": ["Bash(git reset --hard*)"], "allow": ["Bash(git push*)"]}}))
        assert "permission rules ask" not in run({"cwd": str(repo), "source": "startup"}), "an ask on another command is not named"
        settings.write_text("{ not json")
        assert "permission rules ask" not in run({"cwd": str(repo), "source": "startup"}), "a broken settings file is not this line's business"
        settings.unlink()

        # kit.json author: an AI identity (a cloud container's default) becomes the user's
        def ident():
            return [subprocess.run(["git", "-C", str(repo), "config", k], capture_output=True, text=True).stdout.strip()
                    for k in ("user.name", "user.email")]
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Claude"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "noreply@anthropic.com"], check=True)
        (repo / ".claude" / "kit.json").write_text(json.dumps({"author": "Ada O'Hara <ada@example.org>"}))
        out = run({"cwd": str(repo), "source": "startup"})
        assert ident() == ["Ada O'Hara", "ada@example.org"], ident()
        assert "git author for this repo set to Ada O'Hara" in out, out
        assert "set to" not in run({"cwd": str(repo), "source": "startup"}), "already right: says nothing"
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Bob"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "bob@example.org"], check=True)
        run({"cwd": str(repo), "source": "startup"})
        assert ident() == ["Bob", "bob@example.org"], "a human identity someone chose is left alone"
        (repo / ".claude" / "kit.json").write_text(json.dumps({"author": "not an identity"}))
        run({"cwd": str(repo), "source": "startup"})
        assert ident() == ["Bob", "bob@example.org"]

        # the machine settings: offered until the user answers, never in a headless run or a cloud container
        fresh = Path(tmp) / "fresh-home"
        fresh.mkdir()
        local = {"CLAUDE_CODE_REMOTE": ""}  # this test may itself run in a cloud container
        out = run({"cwd": str(repo), "source": "startup"}, home=fresh, **local)
        assert "Kit setup" in out and "--apply" in out and "--decline" in out, out
        assert "Kit setup" not in run({"cwd": str(repo), "source": "startup"}, home=fresh, KIT_HEADLESS="1", **local)
        assert "Kit setup" not in run({"cwd": str(repo), "source": "startup"}, home=fresh, CLAUDE_CODE_REMOTE="true"), \
            "a cloud container's ~/.claude does not outlive the session: nothing to offer"
        assert "Kit setup" not in run({"cwd": str(repo), "source": "compact"}, home=fresh, **local)
        script = SCRIPT.parent / "machine_setup.py"
        subprocess.run([sys.executable, str(script), "--apply"], env={**os.environ, "HOME": str(fresh)},
                       capture_output=True, check=True)
        assert "Kit setup" not in run({"cwd": str(repo), "source": "startup"}, home=fresh, **local), "applied: silent"
        second = Path(tmp) / "second-account"  # another CLAUDE_CONFIG_DIR on the machine that said yes
        out = run({"cwd": str(repo), "source": "startup"}, home=fresh, CLAUDE_CONFIG_DIR=str(second), **local)
        assert "kit: applied the kit's machine settings" in out and "Kit setup" not in out, out
        assert json.loads((second / "settings.json").read_text())["attribution"]["commit"] == "", "written"
        assert "applied the kit" not in run({"cwd": str(repo), "source": "startup"}, home=fresh,
                                            CLAUDE_CONFIG_DIR=str(second), **local), "said once"

        # a kit.json that exists is the opt-in, even `{}`: the header line always prints
        (repo / ".claude" / "kit.json").write_text("{}")
        out = run({"cwd": str(repo), "source": "startup"})
        # this project's legacy board still has A1 working, so its state waits in .claude/, saying why
        coordinator, *waiting, header = out.strip().splitlines()
        assert header == "kit harness active for this project (.claude/kit.json):", out
        assert len(waiting) == 1 and "waits to move from .claude/ to .kit/ (board row A1 is working" in waiting[0], out
        # the coordinator line: on every interactive start and after a compaction, routed without the mod
        assert coordinator.startswith("kit: this session coordinates this project") and "kit:lead" in coordinator, out
        assert "PushNotification" in coordinator and "none for progress" in coordinator, coordinator
        assert coordinator in run({"cwd": str(repo), "source": "compact"}).splitlines(), "back after a compaction"
        assert coordinator in run({"cwd": str(repo), "source": "resume"}).splitlines()
        assert "coordinates" not in run({"cwd": str(repo), "source": "startup"}, KIT_HEADLESS="1"), "not headless"
        assert "coordinates" not in run({"cwd": str(repo), "source": "startup", "agent_id": "a1"}), "not a subagent"
        light = Path(tmp) / "light-home"
        (light / ".claude").mkdir(parents=True)
        (light / ".claude" / "kit.json").write_text(json.dumps({"machineSetup": "declined", "mode": "Light"}))
        out = run({"cwd": str(repo), "source": "startup"}, home=light)
        assert "coordinates" not in out and "kit harness active" in out, "the personal light mode is the off switch"
        assert "coordinates" not in run({"cwd": str(repo), "source": "compact"}, home=light)

        # a long-lived session with away on: after a compaction or a /clear the coordinator line is
        # followed by one saying since when, and that the coordinator turns it off when the user writes
        away = Path(tmp) / "away-home"
        (away / ".claude").mkdir(parents=True)
        (away / ".claude" / "kit.json").write_text(json.dumps({"machineSetup": "declined"}))
        (away / ".claude" / "settings.json").write_text(json.dumps({"model": "opus"}))
        items = SCRIPT.parent / "items.py"
        env = {**os.environ, "HOME": str(away), "CLAUDE_CONFIG_DIR": str(away / ".claude")}
        on = subprocess.run([sys.executable, str(items), "away", "on"], cwd=str(repo), env=env,
                            capture_output=True, text=True)
        assert on.returncode == 0 and on.stdout.strip().splitlines()[-1].startswith("The owner is back when he writes"), on.stdout
        for source in ("compact", "clear"):
            lines = run({"cwd": str(repo), "source": source}, home=away).splitlines()
            at = [i for i, line in enumerate(lines) if line.startswith("kit: away is on since ")]
            assert at and lines[at[0] - 1] == coordinator, (source, lines)
            assert lines[at[0]].endswith(": turn it off with `I away off` when the user writes."), lines[at[0]]
        assert "away is on" not in run({"cwd": str(repo), "source": "compact", "agent_id": "a1"}, home=away), \
            "a thread is not the one to turn it off"
        out = run({"cwd": str(repo), "source": "startup"}, home=away)
        assert "away is off again" in out and "away is on since" not in out, out
        assert "away is on" not in run({"cwd": str(repo), "source": "compact"}, home=away), "off: no line"
        # an account whose settings.json is not JSON: one line, and the file is left as it is
        (away / ".claude" / "settings.json").write_text("{bad")
        out = run({"cwd": str(repo), "source": "startup"}, home=away, CLAUDE_CODE_REMOTE="")
        assert "kit: declined" not in out and "not valid JSON" not in out, "declined on this machine: silent"
        (away / ".claude" / "kit.json").write_text("{}")
        out = run({"cwd": str(repo), "source": "startup"}, home=away, CLAUDE_CODE_REMOTE="")
        assert out.count("not valid JSON") == 1 and "left alone" in out and "Kit setup" not in out, out
        assert (away / ".claude" / "settings.json").read_text() == "{bad"
        # a typo is named with the closest known key, at the top level and inside a section
        (repo / ".claude" / "kit.json").write_text(json.dumps({"chek": "make lint", "verfy": "make test",
                                                               "lead": {"baord": "docs/b.md", "notes": "n"},
                                                               "guard": {"allowCommand": ["x"]}, "watchdog": {"silentMin": 5}}))
        out = run({"cwd": str(repo), "source": "startup"})
        assert "kit harness active" in out and "make lint" not in out.split("unknown key")[0], out
        assert "- unknown key `chek` in .claude/kit.json (did you mean `check`?): the kit ignores it" in out, out
        assert "- unknown key `verfy` in .claude/kit.json (did you mean `verify`?): the kit ignores it" in out, out
        assert "- unknown key `lead.baord` in .claude/kit.json (did you mean `lead.board`?): the kit ignores it" in out, out
        assert "- unknown key `guard.allowCommand` in .claude/kit.json (did you mean `guard.allowCommands`?)" in out, out
        assert "silentMin" not in out and "`notes`" not in out, "known keys are not flagged"
        # a value of the wrong type is named, and does not crash the start
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": ["make", "lint"], "protect": {"glob": "data/**"},
                                                               "onEdit": "ruff"}))
        out = run({"cwd": str(repo), "source": "startup"})
        assert "- `check` in .claude/kit.json should be a string (the shell command); it is ignored" in out, out
        assert "- `protect` in .claude/kit.json should be a list of rules; it is ignored" in out, out
        assert "- `onEdit` in .claude/kit.json should be a list of rules; it is ignored" in out, out
        assert "fast check" not in out and "protected:" not in out, out

        # items still queued on disk (a hand-off, a taken card) are counted, with the command that lists them
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "make lint"}))
        items = SCRIPT.parent / "items.py"
        for name in ("First handoff", "Second handoff"):
            subprocess.run([sys.executable, str(items), "new", name, "--from", "handoff"], cwd=str(repo),
                           capture_output=True, check=True)
        out = run({"cwd": str(repo), "source": "startup"})
        assert f'- 2 queued item(s) on disk: python3 "{items}" list --status queued' in out, out
        subprocess.run([sys.executable, str(items), "log", "first-handoff", "working", "thread A"], cwd=str(repo),
                       capture_output=True, check=True)
        assert "1 queued item(s)" in run({"cwd": str(repo), "source": "startup"})
        subprocess.run([sys.executable, str(items), "log", "second-handoff", "done"], cwd=str(repo),
                       capture_output=True, check=True)
        assert "queued item" not in run({"cwd": str(repo), "source": "startup"}), "nothing queued: no line"

        # a newer kit installed than the one this session runs: one restart line per session
        plugin = SCRIPT.resolve().parents[2]
        (HOME / ".claude" / "plugins").mkdir(exist_ok=True)
        (HOME / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
            "kit@claude-kit": [{"scope": "user", "installPath": str(plugin.parent / "9.9.9"), "version": "9.9.9"}]}}))
        notice = "kit updated to 9.9.9: when you're at the Mac, /reload-plugins (or a restart) loads it"
        out = run({"cwd": str(repo), "source": "startup", "session_id": "upd"}, TMPDIR=tmp, CLAUDE_CODE_BRIDGE_SESSION_ID="")
        assert notice in out and "nothing waits on it" in out, out
        assert notice not in run({"cwd": str(repo), "source": "compact", "session_id": "upd"}, TMPDIR=tmp), "said once"
        # over Remote Control the user is on the phone: the line is said once and nothing stops for it
        out = run({"cwd": str(repo), "source": "startup", "session_id": "upd-rc"}, TMPDIR=tmp,
                  CLAUDE_CODE_BRIDGE_SESSION_ID="bridge-1")
        assert notice in out and "carry on" in out, out
        (HOME / ".claude" / "plugins" / "installed_plugins.json").unlink()

        # kit.json is personal (kept out of git), so a linked worktree has none: the main checkout's turns it on
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org"]
        subprocess.run(git + ["-C", str(repo), "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        tree = Path(tmp) / "wt"
        subprocess.run(git + ["-C", str(repo), "worktree", "add", "-q", "-b", "feat/x", str(tree)], check=True)
        assert not (tree / ".claude" / "kit.json").exists()
        out = run({"cwd": str(tree), "source": "startup"})
        assert "kit harness active" in out and "make lint" in out, f"worktree uses the main checkout's: {out}"
        bare = Path(tmp) / "bare"
        subprocess.run(["git", "init", "-q", str(bare)], check=True)
        subprocess.run(git + ["-C", str(bare), "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        subprocess.run(git + ["-C", str(bare), "worktree", "add", "-q", "-b", "feat/y", str(Path(tmp) / "bare-wt")], check=True)
        assert run({"cwd": str(Path(tmp) / "bare-wt"), "source": "startup"}) == "", "no kit.json anywhere: off"

        (repo / ".claude" / "kit.json").write_text("{broken")
        out = run({"cwd": str(repo), "source": "startup"})
        assert "cannot read" in out, "a broken kit.json is reported, not ignored"

    # an older project's state leaves .claude/ at a session start, unless a thread is at work
    with tempfile.TemporaryDirectory() as tmp:
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org"]
        repo = Path(tmp) / "old"
        (repo / ".claude" / "lead" / "items" / "A1").mkdir(parents=True)
        (repo / ".claude" / "evidence" / "main").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".claude" / "kit.json").write_text("{}")
        (repo / ".claude" / "lead" / "board.md").write_text("A1 | ship | a | DONE WHEN x | queued | - | - | -\n")
        log = repo / ".claude" / "lead" / "items" / "A1" / "LOG.md"
        log.write_text("- 2026-11-01 10:00 | working | feat/a\n")
        (repo / ".claude" / "evidence" / "main" / "gate-verify.json").write_text("{}")
        (repo / ".git" / "info" / "exclude").write_text("/.claude/lead/\n/.claude/evidence/\n")
        out = run({"cwd": str(repo), "source": "startup"})
        assert "waits to move from .claude/ to .kit/ (item A1 is working" in out and "stays in" not in out, out
        assert (repo / ".claude" / "lead" / "board.md").exists() and not (repo / ".kit").exists(), "nothing moved"
        assert "moved this project" not in run({"cwd": str(repo), "source": "compact"}), "never mid-session"
        log.write_text(log.read_text() + "- 2026-11-01 11:00 | done | merged\n")
        out = run({"cwd": str(repo), "source": "startup"})
        moved = [l for l in out.splitlines() if "moved this project's kit state" in l]
        assert len(moved) == 1 and "(evidence, lead) from .claude/ to .kit/" in moved[0] and "undo" in moved[0], out
        assert (repo / ".kit" / "lead" / "board.md").exists() and not (repo / ".claude" / "lead").exists(), "moved"
        assert "/.kit/lead/" in (repo / ".git" / "info" / "exclude").read_text()
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout
        assert status == "?? .claude/\n", f"only kit.json, which was never excluded, shows: {status!r}"
        assert "kit state" not in run({"cwd": str(repo), "source": "startup"}), "once moved, silent"
        # a tracked entry is never moved for the owner: the command to run is printed instead
        (repo / ".claude" / "overnight" / "r1").mkdir(parents=True)
        (repo / ".claude" / "overnight" / "r1" / "end-state.json").write_text("{}")
        subprocess.run(git + ["-C", str(repo), "add", "-f", ".claude/overnight"], check=True)
        subprocess.run(git + ["-C", str(repo), "commit", "-qm", "runs"], check=True)
        out = run({"cwd": str(repo), "source": "startup"})
        assert "run `git mv .claude/overnight .kit/overnight` and commit" in out, out
        assert (repo / ".claude" / "overnight" / "r1").is_dir(), "the tracked entry stayed"
        assert "git mv" not in run({"cwd": str(repo), "source": "startup"}), "said once, not at every start"
        # undo sticks: the next session start leaves the state in .claude/ and says nothing
        script = Path(__file__).resolve().parent.parent / "scripts" / "migrate_state.py"
        undo = subprocess.run([sys.executable, str(script), "undo", "--root", str(repo)], capture_output=True, text=True)
        assert undo.returncode == 0 and (repo / ".claude" / "lead" / "board.md").exists(), undo.stdout + undo.stderr
        out = run({"cwd": str(repo), "source": "startup"})
        assert "kit:" not in "\n".join(l for l in out.splitlines() if "state" in l) and not (repo / ".kit" / "lead").exists(), out
        again = subprocess.run([sys.executable, str(script), "migrate", "--root", str(repo)], capture_output=True, text=True)
        assert (repo / ".kit" / "lead" / "board.md").exists(), "migrate by hand moves it again: " + again.stdout + again.stderr
        # a fresh project has nothing to move and makes no .kit/ by starting a session
        fresh = Path(tmp) / "fresh"
        (fresh / ".claude").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(fresh)], check=True)
        (fresh / ".claude" / "kit.json").write_text("{}")
        out = run({"cwd": str(fresh), "source": "startup"})
        assert "kit state" not in out and not (fresh / ".kit").exists(), out
    print("session_start: all checks passed")


if __name__ == "__main__":
    main()
