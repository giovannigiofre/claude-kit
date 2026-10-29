#!/usr/bin/env python3
"""PostToolUse (Write|Edit|MultiEdit): run kit.json `onEdit` commands for the edited file.

Each rule: {"glob": "**/*.py", "run": "uv run ruff format \"$FILE\""}.
The command runs from the checkout root with FILE (absolute) and REL (relative) set.
A failing command exits 2 so its output goes back to Claude as feedback.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def main():
    data = kitlib.read_input()
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path or not Path(file_path).exists():
        return 0
    root = kitlib.project_root(data, file_path)
    config, err = kitlib.load_config(root)
    if err:
        print(err, file=sys.stderr)
        return 2
    if not config:
        return 0
    rel = kitlib.relpath(root, file_path)
    if rel is None:
        return 0
    failures = run_rules(config, root, file_path, rel)
    if failures:
        print(f"kit onEdit checks failed for {rel}:\n\n" + "\n\n".join(failures), file=sys.stderr)
        return 2
    return 0


def run_rules(config, root, file_path, rel):
    """Run every onEdit rule whose glob matches `rel`; the failures, one text each. The whole
    output is kept (up to 60 lines): a checker's full message is what makes the fix right."""
    failures = []
    for rule in config.get("onEdit", []):
        glob, cmd = rule.get("glob"), rule.get("run")
        if not glob or not cmd or not kitlib.matches(glob, rel):
            continue
        code, out = kitlib.run_shell(
            cmd, root, {"FILE": str(Path(file_path).resolve()), "REL": rel},
            timeout=int(rule.get("timeout", 120)),
        )
        if code != 0:
            failures.append(f"$ {cmd}\n{kitlib.tail(out, 60)}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
