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


def run(script, payload, home, *args):
    env = dict(os.environ, HOME=str(home))
    env.pop("CLAUDE_CODE_AUTO_COMPACT_WINDOW", None)
    out = subprocess.run([sys.executable, str(SCRIPTS / script), *args], input=json.dumps(payload),
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
        for bad in ([], {"context": True}, {"context": 300000}, {"context": {"window": "abc", "warnAt": "x"}},
                    {"context": {"window": "nan"}}, {"context": {"window": 0.5, "handoff": 5}}):
            kit.write_text(json.dumps(bad))
            run("context_guard.py", dict(base, session_id=uuid.uuid4().hex), home)  # must not crash
            run("session_start.py", {"cwd": str(repo), "source": "compact"}, home)

        kit.write_text(json.dumps({"context": {"window": 300_000}}))
        handoff = repo / ".claude" / "handoff.md"
        write_transcript(transcript, 100_000)
        assert run("context_guard.py", base, home) == "", "below warnAt: silent"

        def guard():
            out = run("context_guard.py", base, home)
            return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

        def should(tokens):
            payload = {"cwd": str(repo), "session_id": base["session_id"], "tokens": tokens}
            return json.loads(run("context_guard.py", payload, home, "--should-compact"))

        write_transcript(transcript, 225_000)
        ctx = guard()
        assert "75%" in ctx and "REWRITE .claude/handoff.md" in ctx and "does not exist" in ctx, ctx
        assert [guard() for _ in range(4)] == [""] * 4, "quiet between reminders"
        assert "ACTION REQUIRED" in guard(), "nags again after NAG_EVERY calls"
        assert should(250_000) == {"compact": False, "reason": "missing"}, "no note, no compaction"

        handoff.write_text("GOAL: ship it\n")
        assert "is current" in guard(), "a fresh rewrite is acknowledged once"
        assert guard() == "", "current note: silent"
        assert should(200_000) == {"compact": False}, "below compactAt"
        assert should(250_000)["compact"] is True

        handoff.write_text("GOAL: ship it\nmore notes\n")
        ctx = guard()
        assert "only appended" in ctx, ctx
        assert should(250_000) == {"compact": False, "reason": "appended"}
        handoff.write_text("\n".join(f"line {i}" for i in range(150)))
        assert "over 100 lines" in guard()
        handoff.write_text("GOAL: ship it v2\nNEXT: deploy\n")
        assert "is current" in guard()

        write_transcript(transcript, 270_000)  # 90 %: every call nags while stale
        for _ in range(61):
            guard()
        assert "more than 60 tool calls" in guard() and "ACTION REQUIRED" in guard(), "stale again, nags every call"

        start = {"cwd": str(repo), "session_id": base["session_id"], "source": "compact"}
        out = run("session_start.py", start, home)
        assert "WARNING: the note was not current" in out and "deploy" in out, out

        write_transcript(transcript, 40_000)  # after a compaction
        assert run("context_guard.py", base, home) == ""
        assert should(250_000) == {"compact": False}, "not armed after the compaction"
        write_transcript(transcript, 230_000)
        assert "has not been rewritten" in guard(), "re-armed: the old note must be rewritten again"

        sub = dict(base, agent_id="a1", session_id=uuid.uuid4().hex)
        assert run("context_guard.py", sub, home) == "", "subagents are skipped"

        fresh = {"cwd": str(repo), "session_id": uuid.uuid4().hex, "source": "compact"}
        handoff.unlink()
        assert "Handoff note" not in run("session_start.py", fresh, home), "no file, nothing injected"
        handoff.write_text("GOAL: ship it\n")
        out = run("session_start.py", fresh, home)
        assert "GOAL: ship it" in out and "WARNING" not in out, "no guard state: no warning"
        assert "GOAL: ship it" not in run("session_start.py", dict(fresh, source="startup"), home)
    print("context hooks: all checks passed")


if __name__ == "__main__":
    main()
