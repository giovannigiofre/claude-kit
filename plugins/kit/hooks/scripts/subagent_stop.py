#!/usr/bin/env python3
"""SubagentStop (kit:verifier, kit:implementer): file a thread's report and a verifier's verdict under
the coordinator's item when the brief names one (items.py), count the verifier's verdict, and turn each FAIL problem into a
candidate lesson in the kit's ledger (lessons.py). The same problem in a later round or review
makes it active, and so does a PASS after that FAIL (the problem was real and is fixed now; the
distiller then runs in the background). One seen again after it was delivered to a thread
counts as a miss.

The verdict is parsed from the verifier's report (`VERDICT:` and the items under PROBLEMS):
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

SECTIONS = ("VERDICT", "EVIDENCE", "PROBLEMS", "NOT CHECKED", "SUMMARY", "OPEN", "RISK")
NOTE = r"[ \t]*(?:\([^)\n]*\))?[ \t]*"  # an optional "(most severe first)" after a heading word
# "PROBLEMS:", "PROBLEMS", "## Problems", "PROBLEMS (most severe first):"; in another case than
# PROBLEMS only alone on its line, so a sentence starting "Problems: ..." is not one
PROBLEMS_HEAD = re.compile(r"^(?:#+[ \t]*)?(?:PROBLEMS\b" + NOTE + r"(?::([^\n]*))?|(?i:problems)\b" + NOTE + r":?[ \t]*)$",
                           re.M)
# what ends the PROBLEMS block: a known section in any case, or a WORDS IN CAPS: label alone on its
# line or after a blank line (an unindented "TODO: ..." wrapped inside a problem goes on)
BLOCK_END = re.compile(r"^(?:#+[ \t]*)?(?:(?i:" + "|".join(SECTIONS) + r")\b" + NOTE + r"(?::|$)"
                       r"|[A-Z][A-Z _/-]{2,}" + NOTE + r":[ \t]*$)|(?<=\n\n)[A-Z][A-Z _/-]{2,}" + NOTE + ":", re.M)
ITEM = re.compile(r"^(\s*)(?:(\d+[.)])|[-*])\s+(.*)")
NOT_DEFECTS = re.compile(r"\binformational\b|\bnot (?:a )?defects?\b|\bnits?\b(?!-)", re.I)
HAS_VERDICT = re.compile(r"^\W*VERDICT:", re.M)
BRANCH = re.compile(r"\bbranch:?\s+(?:`([^`\s]+)`|\*\*([^*\s]+)\*\*|([A-Za-z0-9][\w.-]*/[\w./-]*\w))", re.I)
BASES = ("main", "master", "develop", "trunk")
PULL = re.compile(r"(?:\bPR\s*#|/pull/)(\d+)")


def headline(problem):
    """The first sentence of a problem, a parenthesis kept whole (an "e.g." in it ends nothing)."""
    depth = 0
    for i, ch in enumerate(problem):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth <= 0 and ch in ".;" and problem[i + 1:i + 2].isspace():
            return problem[:i + 1]
    return re.sub(r"\s*\([^)]*$", "", problem) or problem  # no parenthesis cut open


def block_items(text, head):
    """The item lines of the PROBLEMS block that starts at `head`."""
    body = text[head.end():]
    end = BLOCK_END.search(body)
    lines = ((head.group(1) or "") + "\n" + body[:end.start() if end else None]).splitlines()
    return lines if any(map(ITEM.match, lines)) else []


def parse(message):
    """(verdict or None, [problem headlines])."""
    text = re.sub(r"\*{2,}|`{3,}", "", message or "")
    m = re.search(r"^\W*VERDICT:\s*(PASS|FAIL|CANNOT_VERIFY)\b", text, re.M)
    verdict = m.group(1) if m else None
    # the last PROBLEMS heading with items under it: one quoted in EVIDENCE, or a later "PROBLEMS: see
    # above", does not count
    blocks = [lines for lines in (block_items(text, h) for h in PROBLEMS_HEAD.finditer(text)) if lines]
    lines = blocks[-1] if blocks else []
    first = next((m for m in map(ITEM.match, lines) if m), None)
    if not first:
        return verdict, []
    numbered, indent = bool(first.group(2)), len(first.group(1))  # the first item sets the style
    problems, current = [], None  # [headline text, its detail items]
    for line in lines:
        item = ITEM.match(line)
        if item and bool(item.group(2)) == numbered and len(item.group(1)) <= indent:
            current = item.group(3).strip()
            problems.append([current, []])
        elif item and problems:
            problems[-1][1].append(item.group(3).strip())
            current = None
        elif current is not None and line.strip() and not line.rstrip().endswith(":") \
                and len(problems[-1][0]) < 300:
            problems[-1][0] += " " + line.strip()  # a wrapped headline
        elif not line.strip() or line.rstrip().endswith(":"):
            current = None  # a blank line or a sub-heading ends the headline
    found = []
    for text, details in problems:
        h = headline(text)
        if text.lower() in ("none", "-") or sub_heading(h, numbered and details):
            continue
        h = h.rstrip(":")
        if details and len(re.sub(r"\([^)]*\)", "", h).split()) <= 3:  # "Scope and naming." says nothing
            h = h.rstrip(".") + ": " + headline(details[0])
        found.append(h)
    return verdict, found[:10]


def sub_heading(h, has_details=False):
    """A sub-heading ("Docs nits:", "Remaining notes (informational)") is not a problem. A
    numbered problem that introduces its details with a colon ("1. Typecheck fails:") is, and so
    is one whose own parenthesis only mentions such a word ("Token leak (informational endpoint
    ...)")."""
    outside = re.sub(r"\([^)]*\)", "", h)
    notes = re.findall(r"\(([^)]*)\)", h)
    if NOT_DEFECTS.search(outside) or any(NOT_DEFECTS.search(n) and len(n.split()) <= 3 for n in notes):
        return h.endswith((":", ")")) or not has_details
    return h.endswith(":") and len(h.split()) <= 4 and not has_details


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


def from_transcript_any(path):
    """(brief, report) for a thread: the first user message and the last SubagentHandback message,
    else the last assistant text (a thread's report has no VERDICT line)."""
    brief, handback, said = "", "", ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
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
                        elif c.get("type") == "text" and c.get("text", "").strip():
                            said = c["text"]
    except OSError:
        pass
    return brief, handback or said


def file_report(root, brief, report, agent_type):
    """A thread briefed with `ITEM: <id>` gets its report filed under the item (REPORT.md for a
    kit:implementer, VERDICT.md for a kit:verifier), with one LOG line: the mailbox the
    coordinator and the user read on disk. Silent when the brief names no item."""
    try:
        import items
        item_id = items.find_id(brief)
        if not item_id or not items.find(root, item_id):
            return
        if agent_type.endswith("verifier"):
            m = re.search(r"^\W*VERDICT:\s*([A-Z_]+(?:\s+scope=\S+)?)", report, re.M)
            items.write(root, item_id, "VERDICT.md", report, "verdict", m.group(1) if m else "no verdict line")
        else:
            status = re.search(r"^\W*STATUS:\s*(\w+)", report, re.M)
            decisions = len(re.findall(r"^\s*(?:-\s*)?DECISION:", report, re.M))
            note = (status.group(1) if status else "no status line") + (f", {decisions} decision(s)" if decisions else "")
            items.write(root, item_id, "REPORT.md", report, "reported", note)
    except Exception:
        pass


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, _ = kitlib.load_config(root)
    if not config:
        return 0
    agent_type = str(data.get("agent_type") or "")
    report = data.get("last_assistant_message") or ""
    brief = ""
    if not agent_type.endswith("verifier"):  # a thread: file its report, nothing else to parse
        if data.get("agent_transcript_path"):
            brief, handed = from_transcript_any(data["agent_transcript_path"])
            report = report or handed
        file_report(root, brief, report, agent_type)
        return 0
    if data.get("agent_transcript_path"):
        brief, handed = from_transcript(data["agent_transcript_path"])
        report = report if HAS_VERDICT.search(report) else handed
    file_report(root, brief, report, agent_type)
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
