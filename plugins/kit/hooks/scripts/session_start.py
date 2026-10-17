#!/usr/bin/env python3
"""SessionStart: tell Claude which kit gates this project has, and after a compaction re-inject
the handoff note (stdout is added to context)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_guard  # noqa: E402
import kitlib  # noqa: E402


def print_handoff(root):
    """After a compaction, put the handoff note (see context_guard.py) back into context."""
    cfg = context_guard.context_config(root)
    if cfg is None:
        return
    path = Path(root) / (cfg.get("handoff") or context_guard.DEFAULT_HANDOFF)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return
    if text:
        print(f"kit: the conversation was just compacted. Handoff note from {path} (keep it current):\n"
              + text[:9000] + "\n")


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    if data.get("source") == "compact":
        print_handoff(root)
    config, err = kitlib.load_config(root)
    if err:
        print(err)
        return 0
    if not config:
        return 0  # project has not opted in: stay silent
    lines = ["kit harness active for this project (.claude/kit.json):"]
    if config.get("check"):
        lines.append(f"- fast check (runs automatically before you stop): {config['check']}")
    if config.get("verify"):
        lines.append(f"- full verify (run before claiming done, used by kit:verifier): {config['verify']}")
    for rule in config.get("protect", []):
        lines.append(f"- protected: {rule.get('glob')} ({rule.get('mode', 'read-only')}) {rule.get('reason', '')}")
    if config.get("onEdit"):
        lines.append("- onEdit commands run after each edit of: " + ", ".join(r.get("glob", "?") for r in config["onEdit"]))
    lead = config.get("lead") or {}
    if lead.get("notes"):
        lines.append(f"- lead notes: {lead['notes']}")
    if len(lines) > 1:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
