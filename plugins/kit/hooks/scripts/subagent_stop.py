#!/usr/bin/env python3
"""SubagentStop (kit:verifier): count the verifier's verdict, and turn each FAIL problem into a
candidate lesson in the kit's ledger (lessons.py). The same problem in a later round or review
makes it active, and so does a PASS after that FAIL (the problem was real and is fixed now; the
distiller then runs in the background). One seen again after it was delivered to a thread
counts as a miss.

The verdict is parsed from the verifier's final message (`VERDICT:` and the numbered `PROBLEMS:`
items). Only the problem's headline is kept, never the evidence. Silent, and never blocks the
verifier from stopping. A project without .claude/kit.json records nothing. Standard library only.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SECTIONS = ("VERDICT", "EVIDENCE", "PROBLEMS", "NOT CHECKED")


def parse(message):
    """(verdict or None, [problem headlines])."""
    text = re.sub(r"[*`]{2,}", "", message or "")
    m = re.search(r"^\s*VERDICT:\s*(PASS|FAIL|CANNOT_VERIFY)\b", text, re.M)
    verdict = m.group(1) if m else None
    block = re.search(r"^\s*PROBLEMS:(.*?)(?=^\s*(?:" + "|".join(SECTIONS) + r"):|\Z)", text, re.M | re.S)
    problems, current = [], None
    for line in (block.group(1) if block else "").splitlines():
        item = re.match(r"^\s*(?:\d+[.)]|[-*])\s+(.*)", line)
        if item:
            current = item.group(1).strip()
            problems.append(current)
        elif current is not None and line.strip() and len(problems[-1]) < 300:
            problems[-1] += " " + line.strip()
    headlines = [re.split(r"(?<=[.;])\s", p, maxsplit=1)[0] for p in problems if p and p.lower() not in ("none", "-")]
    return verdict, headlines[:10]


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, _ = kitlib.load_config(root)
    if not config:
        return 0
    verdict, problems = parse(data.get("last_assistant_message") or "")
    if not verdict:
        return 0
    try:
        import lessons
        agent = data.get("agent_id") or data.get("session_id") or ""
        lessons.capture(root, f"verdict-{verdict.lower()}", f"verdict-{agent}", "", ref=agent, once_per=agent)
        if verdict == "PASS":  # the fix for the last FAIL is known: its problems were real
            import distill
            info = lessons.repo(root)
            if info and distill.confirm(info["slug"], distill.fixed_fail_keys(info["slug"], agent)):
                distill.spawn(root)
        if verdict == "FAIL":
            for problem in problems:
                lessons.capture(root, "verifier-fail", lessons.key_of(problem, "verifier"),
                                f"The verifier failed a branch here for: {problem}",
                                kind="pitfall", agents=("implementer", "verifier"), ref=agent, once_per=agent)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
