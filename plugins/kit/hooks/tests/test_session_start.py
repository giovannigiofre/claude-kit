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

        assert run({"cwd": str(repo), "source": "startup"}) == "", "no kit.json, no board: silent"

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

        # a kit.json that exists is the opt-in, even `{}`: the header line always prints
        (repo / ".claude" / "kit.json").write_text("{}")
        out = run({"cwd": str(repo), "source": "startup"})
        assert out.strip() == "kit harness active for this project (.claude/kit.json):", out
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
        notice = "kit updated to 9.9.9: restart Claude Code (or /reload-plugins)"
        assert notice in run({"cwd": str(repo), "source": "startup", "session_id": "upd"}, TMPDIR=tmp)
        assert notice not in run({"cwd": str(repo), "source": "compact", "session_id": "upd"}, TMPDIR=tmp), "said once"
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
    print("session_start: all checks passed")


if __name__ == "__main__":
    main()
