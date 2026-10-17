#!/usr/bin/env python3
"""UserPromptSubmit + PostToolUse: ask for a handoff note before auto-compaction hits.

Claude Code compacts on its own when the context reaches the auto-compact window (set it lower
than the 1M default with `autoCompactWindow` in settings, see the README). No hook can start a
compaction, so this hook makes sure nothing important is lost when it happens: once the context
passes `warnAt` (and again at 85 %) of the window, it tells Claude to bring the handoff file up
to date. session_start.py puts that file back into context right after the compaction.

Config, `context` in the project's .claude/kit.json, else in ~/.claude/kit.json, else off:
  {"window": 300000, "warnAt": 0.7, "handoff": ".claude/handoff.md"}
$CLAUDE_CODE_AUTO_COMPACT_WINDOW, if set, beats `window` (as in Claude Code); default 300000. Subagents are skipped: they
compact on their own window and report to the lead, who keeps the handoff.
"""

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

DEFAULT_WINDOW = 300_000
DEFAULT_HANDOFF = ".claude/handoff.md"
# real transcripts have up to ~1.8 MB between assistant entries; if none is in the tail the
# call is skipped (no wrong number, just no check this time)
TAIL_BYTES = 2_500_000


def context_config(root):
    """The `context` object from the project's kit.json, else ~/.claude/kit.json; None = off."""
    config, _ = kitlib.load_config(root)
    if isinstance(config, dict) and isinstance(config.get("context"), dict):
        return config["context"]
    try:
        user = json.loads((Path.home() / ".claude" / "kit.json").read_text())
    except Exception:
        return None
    return user["context"] if isinstance(user, dict) and isinstance(user.get("context"), dict) else None


def number(value, default):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def window_for(cfg):
    # same precedence and range as Claude Code: the env var beats the setting, 100k-1M
    raw = number(os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW"), 0) or number(cfg.get("window"), 0)
    return int(min(max(raw, 100_000), 1_000_000)) if raw else DEFAULT_WINDOW


def handoff_for(cfg):
    path = cfg.get("handoff")
    return path if isinstance(path, str) and path.strip() else DEFAULT_HANDOFF


def context_tokens(transcript_path):
    """Input tokens of the newest main-thread assistant turn = current context size."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        usage = (entry.get("message") or {}).get("usage") or {}
        if "input_tokens" in usage:
            return (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0))
    return None


def level_for(ratio, warn_at):
    return 2 if ratio >= 0.85 else 1 if ratio >= warn_at else 0


def message(level, tokens, window, handoff):
    pct = round(100 * tokens / window)
    head = f"kit: context is ~{tokens // 1000}k tokens, {pct}% of the {window // 1000}k auto-compact window."
    what = (f"write or update {handoff} so the work survives compaction: goal and done-criterion; "
            "decisions and user preferences; in-flight work (background agents, branches, "
            "worktrees, PRs); next steps; rules for this session. Keep it under ~80 lines, facts "
            "only, overwrite stale parts. It is re-injected after compaction.")
    if level == 2:
        return f"{head} Compaction is close: before your next tool call, {what}"
    return (f"{head} At the next natural boundary (not mid-edit), {what} "
            "If the user is live, you may suggest `/compact` at that boundary.")


def main():
    data = kitlib.read_input()
    if data.get("agent_id"):
        return 0
    root = kitlib.project_root(data)
    cfg = context_config(root)
    if cfg is None:
        return 0
    window = window_for(cfg)
    warn_at = number(cfg.get("warnAt"), 0.7)
    tokens = context_tokens(data.get("transcript_path") or "")
    if not tokens:
        return 0
    level = level_for(tokens / window, warn_at)
    session = data.get("session_id")
    state = kitlib.load_state(session, "context")
    if level <= state.get("level", 0):
        if level < state.get("level", 0):  # context shrank (compaction): re-arm
            kitlib.save_state(session, "context", {"level": level})
        return 0
    kitlib.save_state(session, "context", {"level": level})
    ctx = message(level, tokens, window, handoff_for(cfg))
    event = data.get("hook_event_name") or "PostToolUse"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": ctx}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
