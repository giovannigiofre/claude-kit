#!/usr/bin/env python3
"""PostToolUse (Write|Edit|MultiEdit): when an edited code file is LLM code, point Claude to kit:llm-build.

A file counts as LLM code when it sits under a `prompts/` directory, or is a code file whose
content imports an LLM SDK, calls a provider endpoint, or defines a system prompt or tool schema.
Fires once per session (per subagent). No model call, regex only.

Mode: `llm` in the project's .claude/kit.json ("on" by default when kit.json exists, "off" to
silence), else `llm` in ~/.claude/kit.json, else off.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rb", ".java", ".kt",
            ".rs", ".cs", ".php", ".swift"}
MAX_BYTES = 512_000
PATTERNS = re.compile(
    "|".join([
        # Python imports
        r"^\s*(?:from|import)\s+(?:anthropic|openai|google\.genai|google\.generativeai|mistralai|"
        r"cohere|ollama|litellm|langchain\w*|llama_index|dspy|instructor)\b",
        # JS/TS imports and requires
        r"""(?:from|require\(|import\()\s*['"](?:@anthropic-ai/[\w-]+|openai|@google/genai|"""
        r"""@google/generative-ai|@mistralai/[\w-]+|cohere-ai|ollama|langchain|@langchain/[\w-]+|"""
        r"""ai|@ai-sdk/[\w-]+|@openrouter/[\w-]+)['"]""",
        # provider endpoints (raw HTTP)
        r"api\.anthropic\.com|api\.openai\.com|openrouter\.ai/api|generativelanguage\.googleapis\.com|"
        r"api\.mistral\.ai|api\.cohere\.(?:ai|com)|/chat/completions\b|/v1/messages\b",
        # prompt and tool definitions
        r"\bSYSTEM_PROMPT\b|\bsystem_prompt\b|\bsystemPrompt\b|\binput_schema\b|\btool_choice\b",
    ]),
    re.M,
)


def mode_for(root):
    config, _ = kitlib.load_config(root)
    if config is not None:
        return config.get("llm", "on") if isinstance(config, dict) else "on"
    try:
        return json.loads((Path.home() / ".claude" / "kit.json").read_text()).get("llm", "off")
    except Exception:
        return "off"


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
    data = kitlib.read_input()
    file_path = (data.get("tool_input") or {}).get("file_path")
    if not file_path or not Path(file_path).is_file():
        return 0
    root = kitlib.project_root(data, file_path)
    if mode_for(root) != "on":
        return 0
    rel = kitlib.relpath(root, file_path) or Path(file_path).name
    key = f"{data.get('session_id') or 'nosession'}.{data.get('agent_id') or 'main'}"
    state = kitlib.load_state(key, "llm")
    if state.get("fired") or not is_llm_code(Path(file_path), rel):
        return 0
    kitlib.save_state(key, "llm", {"fired": rel})
    ctx = (
        f"kit: this change touches LLM code ({rel}). Load the kit:llm-build skill if it is not "
        "loaded yet and work its checklist for the touched items (security and evals always). "
        "The done-criterion includes hard-check evals that record the prompt hash and model ids."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
