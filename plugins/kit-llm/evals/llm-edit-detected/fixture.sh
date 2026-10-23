#!/bin/sh
# A raw-HTTP client for an OpenAI-compatible endpoint (no SDK import) with a naive retry.
set -e
git init -q .
git config user.email eval@example.invalid
git config user.name eval
mkdir -p .claude
echo '{}' > .claude/kit.json
cat > llm.py <<'PY'
import json
import time
import urllib.error
import urllib.request

URL = "https://openrouter.ai/api/v1/chat/completions"


def complete(api_key, model, messages, post=None):
    """POST one request; `post` is injectable for tests."""
    post = post or _post
    body = json.dumps({"model": model, "messages": messages}).encode()
    for attempt in range(5):
        try:
            return post(URL, body, {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        except Exception:
            time.sleep(1)
    raise RuntimeError("gave up")


def _post(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())
PY
git add -A && git commit -qm "client with retry"
