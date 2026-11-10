#!/usr/bin/env python3
"""PostToolUse (Write|Edit|MultiEdit): when an edited code file is LLM code, point Claude to
kit-llm:llm-build.

A file counts as LLM code when it sits under a `prompts/` directory, or is a code file whose
content imports an LLM SDK, calls a provider endpoint, or defines a system prompt or tool schema.
Fires once per session (per subagent). No model call, regex only.

On wherever the kit-llm plugin is enabled; `"llm": "off"` in the project's .claude/kit.json
silences it. Standard library only, Python 3.9+.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rb", ".java", ".kt",
            ".rs", ".cs", ".php", ".swift"}
MAX_BYTES = 512_000
PATTERNS = re.compile(
    "|".join([
        # Python imports
        r"^\s*(?:from|import)\s+(?:anthropic|openai|google\.genai|google\.generativeai|mistralai|"
        r"cohere|ollama|litellm|langchain\w*|llama_index|dspy|instructor)\b",
        r"^\s*from\s+google\s+import\s+(?:genai|generativeai)\b",
        # AWS Bedrock (boto3 / AWS SDK JS)
        r"bedrock-runtime|\binvoke_model(?:_with_response_stream)?\(|\bconverse(?:_stream)?\(|"
        r"\b(?:InvokeModel(?:WithResponseStream)?|Converse(?:Stream)?)Command\b",
        # JS/TS imports and requires
        r"""(?:from|require\(|import\()\s*['"](?:@anthropic-ai/[\w-]+|openai|@google/genai|"""
        r"""@google/generative-ai|@mistralai/[\w-]+|cohere-ai|ollama|langchain|@langchain/[\w-]+|"""
        r"""ai|@ai-sdk/[\w-]+|@openrouter/[\w-]+)['"]""",
        # provider endpoints (raw HTTP)
        r"api\.anthropic\.com|api\.openai\.com|openrouter\.ai/api|generativelanguage\.googleapis\.com|"
        r"api\.mistral\.ai|api\.cohere\.(?:ai|com)|/chat/completions\b|anthropic-version",
        # /v1/messages only next to an Anthropic name, so REST routes like /api/v1/messages don't match
        r"(?i:anthropic[^\n]*/v1/messages\b|/v1/messages\b[^\n]*anthropic)",
        # prompt and tool definitions
        r"\bSYSTEM_PROMPT\b|\bsystem_prompt\b|\bsystemPrompt\b|\binput_schema\b|\btool_choice\b",
    ]),
    re.M,
)


def read_input():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def project_root(data, file_path):
    """The git checkout holding the edited file (a worktree has its own), else the session cwd."""
    start = Path(file_path).parent
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    cwd = data.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else start


def kit_config(root):
    """The checkout's .claude/kit.json, else its main checkout's: kit.json is personal and kept out
    of git by default, so a linked worktree has none of its own."""
    path = Path(root) / ".claude" / "kit.json"
    if path.exists():
        return path
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=10)
        common = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        common = None
    if common and common.name == ".git" and (common.parent / ".claude" / "kit.json").exists():
        return common.parent / ".claude" / "kit.json"
    return path


def is_off(root):
    try:
        config = json.loads(kit_config(root).read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(config, dict) and config.get("llm") == "off"


def state_file(key):
    d = Path(tempfile.gettempdir()) / "claude-kit"
    d.mkdir(parents=True, exist_ok=True)
    return d / (re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".llm.json")


def is_llm_code(path, rel):
    if "prompts" in Path(rel).parts[:-1]:
        return True
    if path.suffix.lower() not in CODE_EXT:
        return False
    try:
        with open(path, "rb") as fh:
            text = fh.read(MAX_BYTES).decode("utf-8", "replace")
    except OSError:
        return False
    return bool(PATTERNS.search(text))


def main():
    data = read_input()
    if not isinstance(data, dict) or not isinstance(data.get("tool_input"), dict):
        return 0
    file_path = data["tool_input"].get("file_path")
    if not isinstance(file_path, str) or not file_path or not Path(file_path).is_file():
        return 0
    root = project_root(data, file_path)
    if is_off(root):
        return 0
    try:
        rel = Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        rel = Path(file_path).name
    marker = state_file(f"{data.get('session_id') or 'nosession'}.{data.get('agent_id') or 'main'}")
    if marker.exists() or not is_llm_code(Path(file_path), rel):
        return 0
    marker.write_text(json.dumps({"fired": rel}))
    ctx = (
        f"kit: this change touches LLM code ({rel}). Load the kit-llm:llm-build skill if it is not "
        "loaded yet and work its checklist for the touched items (security and evals always). "
        "The done-criterion includes hard-check evals that record the prompt hash and model ids."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception:  # a hint hook must never break or block an edit
        pass
    sys.exit(0)
