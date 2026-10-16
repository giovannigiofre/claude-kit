#!/usr/bin/env python3
"""UserPromptSubmit: spot brain-dump prompts and route them to /kit:shape.

Mode comes from `shape` in the project's .claude/kit.json, else from ~/.claude/kit.json, else off:
  auto  tell Claude to run kit:shape before anything else
  ask   tell Claude to ask once (yes/no) whether to shape first
  off   do nothing
Skipped for slash commands, "!go" / "just do it" / "no questions", and prompts that are mostly
pasted logs or code. The heuristic is deliberately simple; tune the thresholds after real use.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SKIP_MARKERS = re.compile(
    r"!go\b|just do it|no questions|senza domande|fallo e basta|non chiedere", re.I
)
FORCE_MARKERS = re.compile(r"\b(shape this|clarify this|grill me)\b", re.I)
# cues that a new idea starts (English and Italian, the owner's languages)
IDEA_CUES = re.compile(
    r"\b(also|another (thing|idea)|and then|what if|maybe|i (want|would like|think)|"
    r"anche|inoltre|un'altra|magari|e poi|vorrei|potremmo|idea)\b",
    re.I,
)
MIN_WORDS_ALONE = 120   # this long and prose: shape candidate on length alone
MIN_WORDS_CUES = 45     # shorter but with several idea cues


def mode_for(root):
    config, _ = kitlib.load_config(root)
    if config and config.get("shape"):
        return config["shape"]
    user_cfg = Path.home() / ".claude" / "kit.json"
    try:
        return json.loads(user_cfg.read_text()).get("shape", "off")
    except Exception:
        return "off"


def looks_like_paste(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    codeish = sum(
        1 for ln in lines
        if re.search(r"[{};<>]|^\s{4,}|^\s*(at |File \"|Traceback|\d{2}:\d{2}:\d{2})", ln)
    )
    return codeish / len(lines) > 0.4


def is_brain_dump(text):
    if FORCE_MARKERS.search(text):
        return True
    words = re.findall(r"[^\W\d_]+", text)
    n = len(words)
    if n < MIN_WORDS_CUES or looks_like_paste(text):
        return False
    cues = len(IDEA_CUES.findall(text)) + text.count("?") // 2
    bullets = len(re.findall(r"^\s*(?:[-*•]|\d+[.)])\s", text, re.M))
    return n >= MIN_WORDS_ALONE or cues + bullets >= 2


def main():
    data = kitlib.read_input()
    prompt = (data.get("prompt") or "").strip()
    if not prompt or prompt.startswith(("/", "!")) or SKIP_MARKERS.search(prompt):
        return 0
    mode = mode_for(kitlib.project_root(data))
    if mode not in ("auto", "ask") or not is_brain_dump(prompt):
        return 0
    if mode == "auto":
        ctx = (
            "kit: this prompt looks like a brain-dump (several ideas, goal not yet checkable). "
            "Before doing anything else, invoke the kit:shape skill on it. If it is in fact clear, "
            "kit:shape says so and goes straight to the brief. If AskUserQuestion is not available "
            "(a non-interactive run), proceed normally instead."
        )
    else:
        ctx = (
            "kit: this prompt looks like a brain-dump (several ideas, goal not yet checkable). "
            "Before doing anything else, ask once with AskUserQuestion (header 'Shape'): "
            "'Shape this into a brief first?' with options 'Shape first (Recommended)' and "
            "'Just do it'. On 'Shape first' invoke the kit:shape skill; on 'Just do it' proceed "
            "normally. If the prompt is clearly a single precise task, or AskUserQuestion is not available (a "
            "non-interactive run), skip the question and proceed."
        )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
