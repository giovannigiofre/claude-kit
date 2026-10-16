#!/usr/bin/env python3
"""PreToolUse (Write|Edit|MultiEdit|NotebookEdit): enforce kit.json `protect` rules.

Modes:
  read-only     no Write/Edit at all under the glob
  no-overwrite  new files may be created; existing files may not be edited or rewritten
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def main():
    data = kitlib.read_input()
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return 0
    root = kitlib.project_root(data, file_path)
    config, err = kitlib.load_config(root)
    if err:
        print(err, file=sys.stderr)
        return 0
    if not config:
        return 0
    rel = kitlib.relpath(root, file_path)
    if rel is None:
        return 0
    exists = Path(file_path).exists()
    for rule in config.get("protect", []):
        glob, mode = rule.get("glob"), rule.get("mode", "read-only")
        if not glob or not kitlib.matches(glob, rel):
            continue
        why = rule.get("reason", "")
        if mode == "read-only" or (mode == "no-overwrite" and exists):
            print(
                f"kit protect: {rel} matches '{glob}' ({mode}). {why} "
                "Write a new file instead, or ask the user to change .claude/kit.json.",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
