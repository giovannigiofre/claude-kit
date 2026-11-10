#!/usr/bin/env python3
"""Self-check for llm_detect.py.

Run: python3 plugins/kit-llm/hooks/tests/test_llm_detect.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "llm_detect.py"


def run(payload, home):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    out = subprocess.run([sys.executable, str(SCRIPT)], input=raw,
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
            "gg.py": "from google import genai\n",
            "bedrock.py": 'import boto3\nclient = boto3.client("bedrock-runtime")\n',
            "converse.py": "resp = client.converse(modelId=MODEL, messages=msgs)\n",
            "bedrock.ts": "await client.send(new InvokeModelCommand(input));\n",
            "raw_anthropic.py": 'URL = BASE + "/v1/messages"  # anthropic\n',
            "anthropic_header.py": 'HEADERS = {"anthropic-version": "2023-06-01"}\n',
            "route.ts": 'app.get("/api/v1/messages", listMessages);\n',
        }
        for name, body in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(body)

        def payload(name, sid=None, **extra):
            return dict({"cwd": str(repo), "session_id": sid or uuid.uuid4().hex,
                         "hook_event_name": "PostToolUse", "tool_name": "Edit",
                         "tool_input": {"file_path": str(repo / name)}}, **extra)

        assert run(payload("llm.py"), home) != "", "on wherever the plugin is enabled, kit.json or not"

        kit = repo / ".claude" / "kit.json"
        kit.write_text(json.dumps({"check": "true"}))
        for name in ("llm.py", "sdk.py", "client.ts", "vercel.ts", "tools.py", "prompts/advisor.md",
                     "gg.py", "bedrock.py", "converse.py", "bedrock.ts", "raw_anthropic.py", "anthropic_header.py"):
            out = run(payload(name), home)
            assert out, f"{name} must match"
            ctx = json.loads(out)["hookSpecificOutput"]
            assert ctx["hookEventName"] == "PostToolUse" and "kit-llm:llm-build" in ctx["additionalContext"], ctx
            assert name in ctx["additionalContext"]
        for name in ("plain.py", "docs.md", "aid.ts", "missing.py", "route.ts"):
            assert run(payload(name), home) == "", f"{name} must not match"

        sid = uuid.uuid4().hex
        assert run(payload("plain.py", sid), home) == "", "no match does not use up the session"
        assert run(payload("llm.py", sid), home) != ""
        assert run(payload("sdk.py", sid), home) == "", "fires once per session"
        assert run(payload("sdk.py", sid, agent_id="a1"), home) != "", "a subagent gets its own hint"
        assert run(payload("sdk.py", sid, agent_id="a1"), home) == ""

        for bad_stdin in ("[]", "not json", "", json.dumps({"tool_input": {"file_path": 5}}),
                          json.dumps({"tool_input": "x"}), json.dumps({"cwd": 3, "tool_input": {"file_path": ["a"]}})):
            assert run(bad_stdin, home) == "", f"malformed stdin must exit 0 silently: {bad_stdin!r}"
        kit.write_text(json.dumps({"llm": "off"}))
        assert run(payload("llm.py"), home) == "", '"llm": "off" in kit.json silences it'
        for other in (["not", "a", "dict"], "on", 3, {"llm": "on"}):
            kit.write_text(json.dumps(other))
            assert run(payload("llm.py"), home) != "", f"{other!r} in kit.json: still on"
        kit.write_text("{broken")
        assert run(payload("llm.py"), home) != "", "a broken kit.json does not silence it"

        # kit.json is personal (kept out of git), so a linked worktree has none: the main checkout's applies
        kit.write_text(json.dumps({"llm": "off"}))
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-C", str(repo)]
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base"], check=True)
        wt = tmp / "wt"
        subprocess.run(git + ["worktree", "add", "-q", "-b", "feat/x", str(wt)], check=True)
        (wt / "llm.py").write_text(files["llm.py"])
        in_wt = dict(payload("llm.py"), cwd=str(wt), tool_input={"file_path": str(wt / "llm.py")})
        assert run(in_wt, home) == "", "the main checkout's \"llm\": \"off\" silences a worktree without kit.json"
        kit.unlink()
        assert run(dict(in_wt, session_id=uuid.uuid4().hex), home) != "", "no kit.json anywhere: on, as everywhere"
    print("llm_detect: all checks passed")


if __name__ == "__main__":
    main()
