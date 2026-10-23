#!/usr/bin/env python3
"""SessionStart: tell Claude which kit gates this project has, make the user the git author when
kit.json names them, offer the kit's machine settings once, and after a compaction put the
coordinator's board back into context (stdout is added to context)."""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import machine_setup  # noqa: E402

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


def ensure_author(root, config):
    """kit.json `author` ("Name <email>") is who commits in this project. When git's identity in
    the checkout is missing or an AI's (a cloud container's default), set the repo's own config to
    it, so every commit, the threads' included (worktrees share it), carries the user's name."""
    author = config.get("author") if isinstance(config, dict) else None
    m = re.match(r"^\s*(.+?)\s*<([^<>@\s]+@[^<>\s]+)>\s*$", author or "")
    if not m:
        return None
    name, email = m.group(1), m.group(2)
    _, current_name = kitlib.run_shell("git config user.name", root, timeout=10)
    _, current_email = kitlib.run_shell("git config user.email", root, timeout=10)
    current_name, current_email = current_name.strip(), current_email.strip()
    is_ai = current_name.lower() in ("claude", "claude code", "claude[bot]") or \
        current_email.lower().endswith("anthropic.com")
    if (current_name and current_email and not is_ai) or (current_name, current_email) == (name, email):
        return None
    code_n, _ = kitlib.run_shell(f"git config user.name {quote(name)}", root, timeout=10)
    code_e, _ = kitlib.run_shell(f"git config user.email {quote(email)}", root, timeout=10)
    if code_n or code_e:
        return None
    was = f"{current_name} <{current_email}>" if current_name or current_email else "unset"
    return f"- git author for this repo set to {name} <{email}> (kit.json author; was {was})"


def quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def offer_machine_setup():
    """Until the user says yes or no on this machine, ask Claude to offer the kit's user settings."""
    todo = machine_setup.pending()
    if not todo:
        return
    script = Path(__file__).resolve().parent / "machine_setup.py"
    print("kit: this machine's ~/.claude/settings.json is missing the kit's settings:\n"
          + "\n".join(f"  - {line}" for line in todo) + "\n"
          "Before the user's first request, explain this in two or three plain lines (what changes, "
          "why: they are the only author of commits and PRs; agents may rewrite only the branches "
          "they created) and ask once with AskUserQuestion, header \"Kit setup\": apply them "
          f"(Recommended) or not. Yes: run `python3 \"{script}\" --apply`. No: run "
          f"`python3 \"{script}\" --decline`. Then carry on with the request. Without "
          "AskUserQuestion (a headless run), ignore this.")


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, err = kitlib.load_config(root)
    if data.get("source") == "compact":
        print_board(root, config)
    elif not os.environ.get("KIT_HEADLESS"):
        offer_machine_setup()
    if err:
        print(err)
        return 0
    if not config:
        return 0  # project has not opted in: stay silent
    lines = ["kit harness active for this project (.claude/kit.json):"]
    author_line = ensure_author(root, config)
    if author_line:
        lines.append(author_line)
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
