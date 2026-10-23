#!/usr/bin/env python3
"""SessionStart: tell Claude which kit gates this project has, and after a compaction put the
coordinator's board back into context (stdout is added to context)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

BOARD = ".claude/lead/board.md"
MAX_BOARD_CHARS = 6000


def print_board(root, config):
    """After a compaction, the board is the coordinator's memory of every thread it started."""
    lead = (config or {}).get("lead") if isinstance(config, dict) else None
    rel = lead.get("board") if isinstance(lead, dict) and isinstance(lead.get("board"), str) else BOARD
    path = Path(rel) if Path(rel).is_absolute() else Path(root) / rel
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return
    if text:
        print(f"kit: the conversation was just compacted. The coordinator's board ({rel}):\n"
              + text[:MAX_BOARD_CHARS] + "\n")


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, err = kitlib.load_config(root)
    if data.get("source") == "compact":
        print_board(root, config)
    if err:
        print(err)
        return 0
    if not config:
        return 0  # project has not opted in: stay silent
    lines = ["kit harness active for this project (.claude/kit.json):"]
    if config.get("check"):
        lines.append(f"- fast check (runs automatically before you stop): {config['check']}")
    if config.get("verify"):
        lines.append(f"- full verify (the gate for finished work): {config['verify']}")
    for rule in config.get("protect", []):
        lines.append(f"- protected: {rule.get('glob')} ({rule.get('mode', 'read-only')}) {rule.get('reason', '')}")
    if config.get("onEdit"):
        lines.append("- onEdit commands run after each edit of: " + ", ".join(r.get("glob", "?") for r in config["onEdit"]))
    lead = config.get("lead") or {}
    if isinstance(lead, dict) and lead.get("notes"):
        lines.append(f"- lead notes: {lead['notes']}")
    if len(lines) > 1:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
