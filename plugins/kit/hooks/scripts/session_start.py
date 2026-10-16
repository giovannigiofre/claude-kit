#!/usr/bin/env python3
"""SessionStart: tell Claude which kit gates this project has (stdout is added to context)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
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
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
