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


def run(cwd, config_dir):
    out = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=30,
                         input=json.dumps({"cwd": str(cwd), "agent_type": "kit:implementer"}),
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
        text = subagent_start.lessons(tree, config)  # the fallback reading, from a worktree: the main checkout's
        assert len(text) <= subagent_start.MAX_CHARS, len(text)
        assert "- feedback_lean-tests.md: one test per behaviour" in text and "pitfall_39.md" in text, text
        assert "pitfall_0.md" not in text, "the oldest pitfalls are the ones cut"
        assert "project_deploy" not in text and "ghp_" not in text, "feedback lines only, no secrets"
        assert re.search(r"\(cut \d+ of 41 lines", text), "the cut is said"
    print("subagent_start: all checks passed")


if __name__ == "__main__":
    main()
