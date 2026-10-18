#!/usr/bin/env python3
"""Self-check for llm_detect.py.

Run: python3 plugins/kit/hooks/tests/test_llm_detect.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "llm_detect.py"


def run(payload, home):
    out = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                         capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        repo, home = tmp / "repo", tmp / "home"
        (repo / ".claude").mkdir(parents=True)
        (home / ".claude").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)

        files = {
            "llm.py": 'import httpx\nURL = "https://openrouter.ai/api/v1/chat/completions"\n',
            "sdk.py": "from anthropic import Anthropic\n",
            "client.ts": 'import OpenAI from "openai";\n',
            "vercel.ts": "import { generateText } from 'ai';\n",
            "tools.py": 'TOOLS = [{"name": "premium", "input_schema": {"type": "object"}}]\n',
            "prompts/advisor.md": "You are an advisor.\n",
            "plain.py": "def add(a, b):\n    return a + b\n",
            "docs.md": "We call api.openai.com and import anthropic.\n",
            "aid.ts": "import { x } from './ai';\n",
        }
        for name, body in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(body)

        def payload(name, sid=None, **extra):
            return dict({"cwd": str(repo), "session_id": sid or uuid.uuid4().hex,
                         "hook_event_name": "PostToolUse", "tool_name": "Edit",
                         "tool_input": {"file_path": str(repo / name)}}, **extra)

        assert run(payload("llm.py"), home) == "", "no kit.json and no user config: off"
        (home / ".claude" / "kit.json").write_text(json.dumps({"llm": "on"}))
        assert run(payload("llm.py"), home) != "", "user-level llm=on applies without kit.json"
        (home / ".claude" / "kit.json").unlink()

        kit = repo / ".claude" / "kit.json"
        kit.write_text(json.dumps({"check": "true"}))
        for name in ("llm.py", "sdk.py", "client.ts", "vercel.ts", "tools.py", "prompts/advisor.md"):
            out = run(payload(name), home)
            assert out, f"{name} must match"
            ctx = json.loads(out)["hookSpecificOutput"]
            assert ctx["hookEventName"] == "PostToolUse" and "kit:llm-build" in ctx["additionalContext"], ctx
            assert name in ctx["additionalContext"]
        for name in ("plain.py", "docs.md", "aid.ts", "missing.py"):
            assert run(payload(name), home) == "", f"{name} must not match"

        sid = uuid.uuid4().hex
        assert run(payload("plain.py", sid), home) == "", "no match does not use up the session"
        assert run(payload("llm.py", sid), home) != ""
        assert run(payload("sdk.py", sid), home) == "", "fires once per session"
        assert run(payload("sdk.py", sid, agent_id="a1"), home) != "", "a subagent gets its own hint"
        assert run(payload("sdk.py", sid, agent_id="a1"), home) == ""

        for bad in ({"llm": "off"}, ["not", "a", "dict"]):
            kit.write_text(json.dumps(bad))
            out = run(payload("llm.py"), home)
            assert (out == "") == (bad == {"llm": "off"}), (bad, out)
        kit.write_text("{broken")
        assert run(payload("llm.py"), home) == "", "a broken kit.json falls back to the user config (off)"
    print("llm_detect: all checks passed")


if __name__ == "__main__":
    main()
