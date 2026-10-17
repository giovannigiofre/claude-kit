#!/bin/sh
# A tiny chatbot repo: a system prompt, a chat() wrapper, no evals yet.
set -e
git init -q .
git config user.email eval@example.invalid
git config user.name eval
cat > prompt.py <<'PY'
SYSTEM_PROMPT = """You are a helpful assistant for a Swiss health-insurance comparison site.
Answer questions about premiums and supplementary cover. Be concise."""
PY
cat > bot.py <<'PY'
from prompt import SYSTEM_PROMPT


def chat(llm, history, user_msg):
    """One turn: system prompt + history + the user's message."""
    return llm.complete(system=SYSTEM_PROMPT, messages=history + [{"role": "user", "content": user_msg}])
PY
git add -A && git commit -qm "chatbot v1"
