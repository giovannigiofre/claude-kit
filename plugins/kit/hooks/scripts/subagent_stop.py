#!/usr/bin/env python3
"""SubagentStop (kit:verifier): count the verifier's verdict, and turn each FAIL problem into a
candidate lesson in the kit's ledger (lessons.py). The same problem in a later round or review
makes it active, and so does a PASS after that FAIL (the problem was real and is fixed now; the
distiller then runs in the background). One seen again after it was delivered to a thread
counts as a miss.

The verdict is parsed from the verifier's report (`VERDICT:` and the numbered items under PROBLEMS):
its final message, else, since a worker hands its report back through the SubagentHandback tool,
the last such call in its transcript, else the last text there that holds a verdict. Only the
problem's headline is kept, never the evidence. A verdict is tied to the branch its brief names
(else a PR number), and a PASS confirms only the last FAIL on that same branch; with neither named
it confirms nothing. Silent, and never blocks the verifier from stopping. A project without
.claude/kit.json records nothing. Standard library only.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SECTIONS = ("VERDICT", "EVIDENCE", "PROBLEMS", "NOT CHECKED")
HAS_VERDICT = re.compile(r"^\W*VERDICT:", re.M)
BRANCH = re.compile(r"\bbranch:?\s+(?:`([^`\s]+)`|\*\*([^*\s]+)\*\*|([A-Za-z0-9][\w.-]*/[\w./-]*\w))", re.I)
BASES = ("main", "master", "develop", "trunk")
PULL = re.compile(r"(?:\bPR\s*#|/pull/)(\d+)")


def parse(message):
    """(verdict or None, [problem headlines])."""
    text = re.sub(r"[*`]{2,}", "", message or "")
    m = re.search(r"^\W*VERDICT:\s*(PASS|FAIL|CANNOT_VERIFY)\b", text, re.M)
    verdict = m.group(1) if m else None
    # the heading comes as "PROBLEMS:", "PROBLEMS", "## PROBLEMS" or "PROBLEMS (most severe first):"
    block = re.search(r"^[#\s]*PROBLEMS\b[ \t]*(?:\([^)\n]*\))?[ \t]*(?::([^\n]*))?$(.*?)"
                      r"(?=^[#\s]*(?:" + "|".join(SECTIONS) + r")\b|\Z)", text, re.M | re.S)
    problems, current = [], None
    lines = ((block.group(1) or "") + "\n" + block.group(2)).splitlines() if block else []
    # numbered problems with bullet details under them: only the numbers start a problem
    starts = r"\d+[.)]" if any(re.match(r"^\s*\d+[.)]\s", line) for line in lines) else r"[-*]"
    indent = None  # items indented deeper than the first one are details of it
    for line in lines:
        item = re.match(r"^(\s*)" + starts + r"\s+(.*)", line)
        if item and indent is None:
            indent = len(item.group(1))
        if item and len(item.group(1)) <= indent:
            current = item.group(2).strip()
            problems.append(current)
        elif current is not None and line.strip() and len(problems[-1]) < 300 \
                and not re.match(r"^\s*(?:[-*]|\d+[.)])\s", line):  # a wrapped headline, not a detail bullet
            problems[-1] += " " + line.strip()
        elif not line.strip():
            current = None  # a blank line ends the headline
    headlines = [re.split(r"(?<=[.;])\s", p, maxsplit=1)[0] for p in problems if p and p.lower() not in ("none", "-")]
    headlines = [re.sub(r"\s*\([^)]*$", "", h) or h for h in headlines]  # no parenthesis cut open
    return verdict, headlines[:10]


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text")


def from_transcript(path):
    """(brief, report) from a subagent transcript: the first user message, and the last
    SubagentHandback message, else the last assistant text that holds a verdict."""
    brief, handback, said = "", "", ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if brief and "SubagentHandback" not in line and "VERDICT" not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                message = row.get("message") or {}
                if row.get("type") == "user" and not brief:
                    brief = text_of(message.get("content"))
                elif row.get("type") == "assistant" and isinstance(message.get("content"), list):
                    for c in message["content"]:
                        if c.get("type") == "tool_use" and c.get("name") == "SubagentHandback":
                            handback = str((c.get("input") or {}).get("message") or "")
                        elif c.get("type") == "text" and HAS_VERDICT.search(c.get("text", "")):
                            said = c["text"]
    except OSError:
        pass
    return brief, handback or said


def scope_of(*texts):
    """The branch a verifier reviewed, from its brief (else its report), or a PR number."""
    for text in texts:  # "branch `develop`" is the base it is compared with, not the branch reviewed
        names = [next(g for g in m.groups() if g) for m in BRANCH.finditer(text or "")]
        names = [n for n in names if n not in BASES] or names
        if names:
            return names[0]
    for text in texts:
        m = PULL.search(text or "")
        if m:
            return "pr-" + m.group(1)
    return ""


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, _ = kitlib.load_config(root)
    if not config:
        return 0
    report = data.get("last_assistant_message") or ""
    brief = ""
    if data.get("agent_transcript_path"):
        brief, handed = from_transcript(data["agent_transcript_path"])
        report = report if HAS_VERDICT.search(report) else handed
    verdict, problems = parse(report)
    if not verdict:
        return 0
    try:
        import lessons
        agent = data.get("agent_id") or data.get("session_id") or ""
        # one event per report, not per agent: a verifier resumed with SendMessage reports again
        report_id = f"{agent}:{hashlib.sha1(report.encode()).hexdigest()[:12]}"
        scope = scope_of(brief, report)
        lessons.capture(root, f"verdict-{verdict.lower()}", f"verdict-{agent}", "", ref=agent, once_per=report_id,
                        scope=scope)
        if verdict == "PASS" and scope:  # the last FAIL on this branch is fixed: its problems were real
            import distill
            info = lessons.repo(root)
            if info and distill.confirm(info["slug"], distill.fixed_fail_keys(info["slug"], report_id, scope)):
                distill.spawn(root)
        if verdict == "FAIL":
            for problem in problems:
                lessons.capture(root, "verifier-fail", lessons.key_of(problem, "verifier"),
                                f"The verifier failed a branch here for: {problem}",
                                kind="pitfall", agents=("implementer", "verifier"), ref=agent, once_per=report_id)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
