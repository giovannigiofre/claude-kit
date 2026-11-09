#!/usr/bin/env python3
"""PostToolUse (Bash): protect and onEdit for the edits a shell command made.

In auto mode Claude is told to change files with sed, heredocs and short scripts rather than
the Edit tool, so a hook matched on Write|Edit never sees those edits. Before each Bash command
in a project with `protect` or `onEdit` the guard notes which files are modified or untracked
and their mtimes (kitlib.dirty_snapshot), per session and agent (kitlib.state_key: threads
running in parallel never share one); after it, this hook compares. A file the command changed gets the
onEdit commands for its glob (formatters, validators), and a protected one is reported:
read-only on any change, no-overwrite on a change to a file that existed before. The hook
reverts nothing: Claude gets the report and restores the file. Silent when nothing changed,
and when there is no snapshot to compare with. Standard library only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import on_edit  # noqa: E402
import protect  # noqa: E402

MAX_FILES = 40  # a command that rewrites more than this (a generator, a mass rename) is reported, not checked


def changed_files(root, before, after):
    """Files whose content changed since the snapshot: new since, or a later mtime."""
    return sorted(rel for rel, mtime in after.items() if before.get(rel) != mtime)


def main():
    data = kitlib.read_input()
    if data.get("tool_name") != "Bash":
        return 0
    root = kitlib.project_root(data)
    config, err = kitlib.load_config(root)
    if err:
        print(err, file=sys.stderr)
        return 0
    if config is None or not (config.get("protect") or config.get("onEdit")):
        return 0
    key = kitlib.state_key(data)  # per session and agent: parallel threads never share a snapshot
    before = kitlib.load_state(key, "bash-snapshot")
    if not isinstance(before, dict) or "files" not in before:
        return 0
    kitlib.save_state(key, "bash-snapshot", {})  # used once: the next command gets a fresh one
    after = kitlib.dirty_snapshot(root)
    changed = changed_files(root, before.get("files") or {}, after)
    if not changed:
        return 0
    if len(changed) > MAX_FILES:
        print(f"kit: this command changed {len(changed)} files; protect and onEdit were not run on "
              "them. Run the project's check yourself.", file=sys.stderr)
        return 0
    problems = []
    for rel in changed:
        existed = rel in (before.get("files") or {}) or bool(kitlib.git_out(root, "ls-files", "--", rel))
        found = protect.violation(config, rel, existed)
        if found:
            glob, mode, why = found
            problems.append(f"kit protect: {rel} matches '{glob}' ({mode}). {why} This command changed it; "
                            f"restore it (git checkout -- '{rel}', or delete it if it is new) and write "
                            "elsewhere, or ask the user to change .claude/kit.json.")
    for rel in changed:
        for failure in on_edit.run_rules(config, root, str(Path(root) / rel), rel):
            problems.append(f"kit onEdit checks failed for {rel}:\n{failure}")
    if problems:
        print("\n\n".join(problems), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
