#!/usr/bin/env python3
"""Self-check for context_guard.py and the handoff re-injection in session_start.py.

Run: python3 plugins/kit/hooks/tests/test_context.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def run(script, payload, home):
    env = dict(os.environ, HOME=str(home))
    env.pop("CLAUDE_CODE_AUTO_COMPACT_WINDOW", None)
    out = subprocess.run([sys.executable, str(SCRIPTS / script)], input=json.dumps(payload),
                         capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def write_transcript(path, tokens):
    rows = [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": tokens - 10,
                                                    "cache_creation_input_tokens": 0}}},
        {"type": "assistant", "isSidechain": True, "message": {"usage": {"input_tokens": 999_999}}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        repo, home = tmp / "repo", tmp / "home"
        (repo / ".claude").mkdir(parents=True)
        home.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        transcript = tmp / "t.jsonl"
        base = {"cwd": str(repo), "transcript_path": str(transcript), "session_id": uuid.uuid4().hex,
                "hook_event_name": "PostToolUse"}

        write_transcript(transcript, 250_000)
        assert run("context_guard.py", base, home) == "", "no kit.json, no user config: must stay off"

        kit = repo / ".claude" / "kit.json"
        kit.write_text(json.dumps({"check": "true"}))
        assert run("context_guard.py", base, home) == "", "kit.json without context: off"
        (home / ".claude").mkdir()
        (home / ".claude" / "kit.json").write_text(json.dumps({"context": {}}))
        assert "83%" in run("context_guard.py", base, home), "user-level context applies"
        (home / ".claude" / "kit.json").unlink()
        for bad in ([], {"context": True}, {"context": 300000}, {"context": {"window": "abc", "warnAt": "x"}}):
            kit.write_text(json.dumps(bad))
            run("context_guard.py", dict(base, session_id=uuid.uuid4().hex), home)  # must not crash
            run("session_start.py", {"cwd": str(repo), "source": "compact"}, home)

        kit.write_text(json.dumps({"context": {"window": 300_000}}))
        write_transcript(transcript, 100_000)
        assert run("context_guard.py", base, home) == "", "below warnAt: silent"

        write_transcript(transcript, 225_000)
        out = json.loads(run("context_guard.py", base, home))["hookSpecificOutput"]
        assert out["hookEventName"] == "PostToolUse" and "75%" in out["additionalContext"], out
        assert ".claude/handoff.md" in out["additionalContext"]
        assert run("context_guard.py", base, home) == "", "same level fires once"

        write_transcript(transcript, 280_000)
        assert "Compaction is close" in run("context_guard.py", base, home), "90% level fires"

        write_transcript(transcript, 40_000)  # after a compaction
        assert run("context_guard.py", base, home) == ""
        write_transcript(transcript, 230_000)
        assert run("context_guard.py", base, home) != "", "re-armed after the context shrank"

        sub = dict(base, agent_id="a1", session_id=uuid.uuid4().hex)
        assert run("context_guard.py", sub, home) == "", "subagents are skipped"

        start = {"cwd": str(repo), "session_id": base["session_id"], "source": "compact"}
        assert "Handoff note" not in run("session_start.py", start, home), "no file, nothing injected"
        (repo / ".claude" / "handoff.md").write_text("GOAL: ship it\n")
        assert "GOAL: ship it" in run("session_start.py", start, home)
        assert "GOAL: ship it" not in run("session_start.py", dict(start, source="startup"), home)
    print("context hooks: all checks passed")


if __name__ == "__main__":
    main()
