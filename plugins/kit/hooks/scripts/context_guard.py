#!/usr/bin/env python3
"""UserPromptSubmit + PostToolUse: make the handoff note current before compaction.

Once the context passes `warnAt` of the window, the handoff file must be REWRITTEN (not appended
to) and kept under ~80 lines. Until it is, every `NAG_EVERY`-th tool call (every call from 85 %)
gets an imperative reminder that names what is wrong (missing, only appended, too long, stale).
session_start.py re-injects the file after the compaction and says whether it was current.

No command hook can start a compaction. The kit's hooks module (hooks/compact.ts) can: at the end
of a main-loop turn it runs this script with `--should-compact`, and compacts when the context is
past `compactAt` and the note is current. Without it, Claude Code's own auto-compact still runs.

Config, `context` in the project's .claude/kit.json, else in ~/.claude/kit.json, else off:
  {"window": 300000, "warnAt": 0.7, "compactAt": 0.8, "handoff": ".claude/handoff.md"}
$CLAUDE_CODE_AUTO_COMPACT_WINDOW, if set, beats `window` (as in Claude Code); default 300000.
Subagents are skipped: they compact on their own window and report to the lead.
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
NAG_EVERY = 5  # tool calls between reminders while the note is not current (every call from 85 %)
STALE_AFTER = 60  # tool calls after a rewrite before the note counts as stale again
MAX_LINES = 100  # the note should be ~80 lines; past this it is an append log, not a handoff


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


def read_handoff(root, cfg):
    try:
        return (Path(root) / handoff_for(cfg)).read_text(encoding="utf-8")
    except Exception:
        return None


def track(state, text):
    """Advance the per-session handoff state by one tool call; returns the new state.

    state: calls (tool calls since the threshold), seen (the note's text at the last call),
    changed (call of the last change), problem (why the last change does not count) and
    nagged (call of the last reminder).
    """
    state = dict(state)
    if not state.get("armed"):  # first call past warnAt: what is there now is not yet current
        state = {"armed": True, "calls": 0, "seen": text, "changed": None, "problem": None, "nagged": None}
    state["calls"] += 1
    if text != state.get("seen"):
        old = (state.get("seen") or "").rstrip()
        if not text or not text.strip():
            state["problem"] = "missing"
        elif old and text.startswith(old):
            state["problem"] = "appended"
        elif len(text.splitlines()) > MAX_LINES:
            state["problem"] = "too_long"
        else:
            state["problem"] = None
        state["seen"], state["changed"] = text, state["calls"]
    return state


def status(state):
    """'fresh', or why the note is not current: missing, appended, too_long, stale, unchanged."""
    if state.get("changed") is None:
        return "missing" if not (state.get("seen") or "").strip() else "unchanged"
    if state.get("problem"):
        return state["problem"]
    return "stale" if state["calls"] - state["changed"] > STALE_AFTER else "fresh"


WHY = {
    "missing": "it does not exist yet.",
    "unchanged": "it has not been rewritten since the context passed the threshold.",
    "appended": "the last change only appended lines; the note must be rewritten as a whole.",
    "too_long": f"it is over {MAX_LINES} lines; cut it to the current state.",
    "stale": f"it was last rewritten more than {STALE_AFTER} tool calls ago.",
}


def head(tokens, window, compact_at):
    return (f"kit: context is ~{tokens // 1000}k tokens, {round(100 * tokens / window)}% of the "
            f"{window // 1000}k auto-compact window (kit compacts from ~{int(window * compact_at) // 1000}k).")


def nag(tokens, window, compact_at, handoff, why):
    return (f"{head(tokens, window, compact_at)} ACTION REQUIRED before any other work: REWRITE "
            f"{handoff} now with one Write of the whole file (do not append, do not Edit a section): "
            f"the note is not current because {WHY[why]} Content, max ~80 lines, facts only: goal and "
            "done-criterion; decisions and user preferences; in-flight work (background agents, "
            "branches, worktrees, PRs, deploy state); failing checks with file:line; rules in play; "
            "next steps. Drop finished items and history. This reminder repeats until it is done.")


def done_message(tokens, window, compact_at, handoff):
    return (f"{head(tokens, window, compact_at)} {handoff} is current. Finish the step you are on; "
            "the conversation is compacted at the end of this turn once the context is past the "
            "kit threshold (or by Claude Code's own auto-compact). Rewrite the note again if the "
            "plan changes before then.")


def settings(root):
    cfg = context_config(root)
    if cfg is None:
        return None
    window = window_for(cfg)
    warn_at = number(cfg.get("warnAt"), 0.7)
    compact_at = number(cfg.get("compactAt"), 0.8)
    return cfg, window, warn_at, compact_at


def should_compact(data):
    """For hooks/compact.ts: {"compact": bool, "instructions": str} for the main loop's context."""
    root = kitlib.project_root(data)
    found = settings(root)
    tokens = number(data.get("tokens"), 0)
    if found is None or not tokens:
        return {"compact": False}
    cfg, window, _, compact_at = found
    state = kitlib.load_state(data.get("session_id"), "context")
    if tokens < compact_at * window or not state.get("armed"):
        return {"compact": False}
    state = track(state, read_handoff(root, cfg))  # sees a rewrite made since the last tool call
    kitlib.save_state(data.get("session_id"), "context", state)
    if status(state) != "fresh":
        return {"compact": False, "reason": status(state)}
    return {"compact": True, "instructions": (
        f"The handoff note {handoff_for(cfg)} holds the current goal, decisions, in-flight work and "
        "next steps and is re-injected after compaction; keep the summary consistent with it.")}


def main():
    data = kitlib.read_input()
    if "--should-compact" in sys.argv:
        print(json.dumps(should_compact(data)))
        return 0
    if data.get("agent_id"):
        return 0
    root = kitlib.project_root(data)
    found = settings(root)
    if found is None:
        return 0
    cfg, window, warn_at, compact_at = found
    tokens = context_tokens(data.get("transcript_path") or "")
    if not tokens:
        return 0
    session = data.get("session_id")
    state = kitlib.load_state(session, "context")
    ratio = tokens / window
    if ratio < warn_at:
        if state.get("armed"):  # context shrank (compaction): re-arm for the next round
            kitlib.save_state(session, "context", {})
        return 0
    before = status(state) if state.get("armed") else None
    state = track(state, read_handoff(root, cfg))
    now = status(state)
    handoff = handoff_for(cfg)
    ctx = None
    if now == "fresh":
        if before != "fresh":
            ctx = done_message(tokens, window, compact_at, handoff)
    else:
        every = 1 if ratio >= 0.85 else NAG_EVERY
        if now != before or state["nagged"] is None or state["calls"] - state["nagged"] >= every:
            state["nagged"] = state["calls"]
            ctx = nag(tokens, window, compact_at, handoff, now)
    kitlib.save_state(session, "context", state)
    if ctx:
        event = data.get("hook_event_name") or "PostToolUse"
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": ctx}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
