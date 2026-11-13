#!/usr/bin/env python3
"""Self-check for subagent_start.py.

Run: python3 plugins/kit/hooks/tests/test_subagent_start.py   (exit 0 = all good)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "subagent_start.py"
sys.path.insert(0, str(SCRIPT.parent))
import subagent_start  # noqa: E402


def run(cwd, config_dir, agent="kit:implementer"):
    out = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=30,
                         input=json.dumps({"cwd": str(cwd), "agent_type": agent}),
                         env={**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir)})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] if out.stdout.strip() else ""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(os.path.realpath(tmp))
        repo, tree, config = tmp / "app", tmp / "app-t1", tmp / "config"
        repo.mkdir()
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                      "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", "-C", str(repo), *args], check=True)
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "t1", str(tree)], check=True)
        assert run(tree, config) == "", "no kit.json: nothing"
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text('{}')
        assert run(tree, config) == "", "no gate, no memory files: nothing, and no error"
        (repo / ".claude" / "kit.json").write_text('{"check": "true"}')
        gate_only = run(tree, config)
        assert gate_only.startswith(f"kit: in {repo} and its worktrees, run the project's gate with `python3 ") and "gate.py\" check`" in gate_only \
            and gate_only.count("\n") == 0, gate_only
        # with items on the board, a thread is told how to log without writing in .claude itself
        (repo / ".claude" / "lead" / "items").mkdir(parents=True)
        both = run(tree, config).splitlines()
        assert len(both) == 2 and both[0] == gate_only and "items.py\" log <id> <status>" in both[1] \
            and f"any write inside {repo}/.claude" in both[1] and "put <id> <file>" in both[1] and len(both[1]) < 640, both
        (repo / ".claude" / "lead" / "items").rmdir()
        (repo / ".claude" / "lead").rmdir()
        (repo / ".claude" / "kit.json").write_text('{"check": "true", "verify": "make test"}')
        assert "gate.py\" verify` (kit.json `verify`: `make test`)" in run(tree, config), "verify wins over check"

        pitfalls = repo / ".claude" / "agent-memory" / "kit-verifier" / "MEMORY.md"
        pitfalls.parent.mkdir(parents=True)
        pitfalls.write_text("".join(f"- [Pitfall {i}](pitfall_{i}.md) — {'detail ' * 25}\n" for i in range(40))
                            + "- [Key](ref.md) — staging token: ghp_" + "a1B2" * 9 + "\n")
        memory = config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(repo)) / "memory" / "MEMORY.md"
        memory.parent.mkdir(parents=True)
        memory.write_text("- [Lean tests](feedback_lean-tests.md) — one test per behaviour\n"
                          "- [Deploy notes](project_deploy.md) — not a preference\n")

        delivered = run(tree, config)
        assert "one test per behaviour" in delivered, "the hook imports the memories and delivers them"
        assert delivered.startswith(f"kit: in {repo} and"), "the gate line comes first"
        assert f"past sessions in {repo} (" in delivered, "the lessons name their repo too"
        text = subagent_start.lessons(tree, config)  # the fallback reading, from a worktree: the main checkout's
        assert len(text) <= subagent_start.MAX_CHARS, len(text)
        assert "- feedback_lean-tests.md: one test per behaviour" in text and "pitfall_39.md" in text, text
        assert "pitfall_0.md" not in text, "the oldest pitfalls are the ones cut"
        assert "project_deploy" not in text and "ghp_" not in text, "feedback lines only, no secrets"
        assert re.search(r"\(cut \d+ of 41 lines", text), "the cut is said"

        # the verifier's memory: one absolute folder in the main checkout, named from a worktree's
        # subfolder too, in a repo without kit.json, made and kept out of git; nothing at the cwd
        other, otree = tmp / "site", tmp / "site-wt"
        other.mkdir()
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                      "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", "-C", str(other), *args], check=True)
        subprocess.run(["git", "-C", str(other), "worktree", "add", "-q", "-b", "w", str(otree)], check=True)
        (otree / "services" / "api").mkdir(parents=True)
        folder = other / ".claude" / "agent-memory" / "kit-verifier"
        for cwd in (otree / "services" / "api", otree, other):
            got = run(cwd, config, "kit:verifier")
            assert got.startswith(f"kit: your memory folder is {folder} (") and "is empty so far" in got, got
        assert folder.is_dir() and not (otree / ".claude").exists() and not (otree / "services" / "api" / ".claude").exists()
        assert not list(other.glob("MEMORY.md")) and not list(otree.rglob("MEMORY.md")), "nothing written at a cwd"
        status = subprocess.run(["git", "-C", str(other), "status", "--porcelain", "--untracked-files=all"],
                                capture_output=True, text=True).stdout
        assert status == "", f"the folder stays out of git: {status!r}"
        (folder / "MEMORY.md").write_text("".join(f"- [Trap {i}](trap_{i}.md) — {'detail ' * 25}\n" for i in range(60)))
        got = run(otree, config, "kit:verifier")
        assert "- trap_59.md: detail" in got and "trap_0.md" not in got and f"read {folder / 'MEMORY.md'})" in got, got
        assert len(got) < subagent_start.MEMORY_CHARS + 1000, len(got)
        assert run(otree, config) == "", "an implementer in a repo without kit.json still gets nothing"
        assert "kit: your memory folder is" not in run(tree, config), "nor in a repo with one"
        assert run(tmp, config, "kit:verifier") == "", "outside git: nothing"
        assert "memory:" not in (SCRIPT.parents[2] / "agents" / "verifier.md").read_text().split("---")[1], \
            "the verifier no longer asks Claude Code for a cwd-relative memory folder"
    print("subagent_start: all checks passed")


if __name__ == "__main__":
    main()
