#!/bin/sh
# A tiny chatbot with tool calling, a FakeLLM for tests and a code-checked eval dir.
set -e
git init -q .
git config user.email eval@example.invalid
git config user.name eval
mkdir -p .claude evals
echo '{"check": "python3 -m pytest -q"}' > .claude/kit.json
cat > premiums.py <<'PY'
# Monthly premium in CHF per canton (adult, 300 deductible). Source: tariff table 2027.
MONTHLY_CHF = {"ZH": 412.30, "BE": 398.75, "TI": 455.10, "GE": 501.60}
PY
cat > bot.py <<'PY'
SYSTEM_PROMPT = """You help users compare Swiss health-insurance premiums. Use the tools for every
number; never estimate a premium yourself."""

TOOLS = [
    {
        "name": "monthly_premium",
        "description": "Monthly premium in CHF for a canton (two-letter code, e.g. ZH).",
        "input_schema": {
            "type": "object",
            "properties": {"canton": {"type": "string", "enum": ["ZH", "BE", "TI", "GE"]}},
            "required": ["canton"],
            "additionalProperties": False,
        },
    }
]


def run_tool(name, args):
    from premiums import MONTHLY_CHF
    if name == "monthly_premium":
        return {"canton": args["canton"], "monthly_chf": MONTHLY_CHF[args["canton"]]}
    raise ValueError(f"unknown tool {name}")


def chat(llm, history, user_msg):
    """One turn with tool calling; llm is any object with .complete(system, messages, tools)."""
    messages = history + [{"role": "user", "content": user_msg}]
    for _ in range(4):  # turn cap
        reply = llm.complete(system=SYSTEM_PROMPT, messages=messages, tools=TOOLS)
        if reply.get("tool") is None:
            return reply["text"]
        result = run_tool(reply["tool"], reply["args"])
        messages.append({"role": "tool", "content": result})
    return "Sorry, I could not finish this request."
PY
cat > fake_llm.py <<'PY'
class FakeLLM:
    """Replays scripted replies so tests never call a real model."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return self.replies.pop(0)
PY
cat > test_bot.py <<'PY'
from bot import chat
from fake_llm import FakeLLM


def test_monthly_premium_tool():
    llm = FakeLLM([{"tool": "monthly_premium", "args": {"canton": "ZH"}}, {"tool": None, "text": "CHF 412.30"}])
    assert chat(llm, [], "premium in Zurich?") == "CHF 412.30"
    assert llm.calls[1]["messages"][-1]["content"]["monthly_chf"] == 412.30
PY
cat > evals/cases.json <<'PY'
[
  {"id": "zh-monthly", "input": "What is the monthly premium in Zurich?", "expect_tool": "monthly_premium",
   "expect_args": {"canton": "ZH"}, "expect_number": 412.30}
]
PY
git add -A && git commit -qm "chatbot with monthly_premium tool"
