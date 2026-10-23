#!/usr/bin/env python3
"""Self-check for session_start.py.

Run: python3 plugins/kit/hooks/tests/test_session_start.py   (exit 0 = all good)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "session_start.py"


def run(payload):
    out = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
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

        (repo / ".claude" / "kit.json").write_text("{broken")
        out = run({"cwd": str(repo), "source": "startup"})
        assert "cannot read" in out, "a broken kit.json is reported, not ignored"
    print("session_start: all checks passed")


if __name__ == "__main__":
    main()
