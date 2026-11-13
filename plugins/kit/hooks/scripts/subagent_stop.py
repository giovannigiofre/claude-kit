#!/usr/bin/env python3
"""SubagentStop (every subagent): first, a background thread whose run delivered no report (its
SubagentHandback refused as a duplicate, never called, or a crash before it) is stopped once and
told to hand its report back; the kit's hooks module wakes the coordinator if it still does not.
Then, for kit:verifier and kit:implementer: file a thread's report and a verifier's verdict under
the coordinator's item when the brief names one (items.py), count the verifier's verdict, and turn each FAIL problem into a
candidate lesson in the kit's ledger (lessons.py). The same problem in a later round or review
makes it active, and so does a PASS after that FAIL (the problem was real and is fixed now; the
distiller then runs in the background). One seen again after it was delivered to a thread
counts as a miss.

Any subagent briefed with `ITEM: <id>` also gets a `cost` line on that item: the input, output,
cache read and cache write tokens its transcript records, its tool calls, and the minutes from
its first to its last line (usage_of).

The verdict is parsed from the verifier's report (`VERDICT:` and the items under PROBLEMS):
its final message, else, since a worker hands its report back through the SubagentHandback tool,
the last such call in its transcript, else the last text there that holds a verdict. A thread's
report is the last SubagentHandback message of its transcript (its closing text, in
`last_assistant_message`, is not the delivered report), else that text. Only the problem's
headline is kept, never the evidence. A verdict is tied to the branch its brief names (else a PR
number), and a PASS confirms only the last FAIL on that same branch; with neither named it
confirms nothing. The LOG line of a filed report names the agent (`..., agent <id>`) and, for a
verifier, the `REVIEWED: <sha>` its report states. Items are looked up in the main checkout: a
thread stopping in its worktree (the hook's cwd) has no `lead/` folder of its own. Apart from
the missing report, silent and never blocks a stop. A project without .claude/kit.json does
nothing, the nudge included. Standard library only. `subagent_stop.py --missing <transcript>`
exits 1 when that transcript's last run delivered no report (the hooks module asks).
"""

import hashlib
import json
import os
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


KIT_TYPES = ("kit:implementer", "kit:verifier")
# re-sent at the start of each run of a background thread (the brief, each message that resumes it)
RUN_START = "Your final report is delivered through SubagentHandback"
NO_REPORT = ("kit: no report reached your caller from this run. Call SubagentHandback with your full report "
             "now; if it answers that a report was already delivered, send the report with SendMessage to "
             "\"main\" instead. Then stop.")


def missing_report(path):
    """True when the transcript is a background thread's and its last run delivered no report:
    no SubagentHandback that succeeded and no SendMessage to main that went through. A
    transcript that cannot be read, a foreground subagent (its final text is the report), a run
    the person interrupted and one paused on its own background work are never missing one."""
    try:
        return scan_runs(Path(path).read_text(errors="replace").splitlines())
    except Exception:  # an unreadable or odd transcript: never a false "no report"
        return False


def scan_runs(lines):
    is_thread, delivered, calls, pending, tried, stopped = False, False, {}, set(), False, False
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("message"), dict):
            continue
        content = entry["message"].get("content")
        if entry.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name, args = block.get("name"), block.get("input") or {}
                    if name == "SubagentHandback" or (name == "SendMessage" and args.get("to") == "main"):
                        calls[block.get("id")] = name
                        tried = True
        elif entry.get("type") == "user":
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and RUN_START in str(block.get("text")):
                    is_thread, delivered, calls, tried, stopped = True, False, {}, False, False
                elif block.get("type") == "text":
                    pending -= {x for x in pending if x in str(block.get("text"))}  # its task notification
                    stopped = stopped or str(block.get("text")).startswith("[Request interrupted by user")
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                    text = text_of(block.get("content"))
                    ok = not block.get("is_error") and (calls[block["tool_use_id"]] == "SendMessage"
                                                        or re.search(r'"success"\s*:\s*true', text))
                    delivered = delivered or bool(ok)
                    calls.pop(block["tool_use_id"])
            res = entry.get("toolUseResult") if isinstance(entry.get("toolUseResult"), dict) else {}
            task = res.get("backgroundTaskId") or res.get("taskId") or (res.get("status") == "async_launched" and res.get("agentId"))
            if task:  # a background command, a Monitor or a subagent: its notification wakes the thread
                pending.add(str(task))
    # a call whose result is not written yet may have gone through: never nudge on a guess. A thread
    # paused on its own background work has not ended, unless it tried to hand back (B2: refused,
    # with its dev servers still running); one the person interrupted is theirs
    return is_thread and not delivered and not calls and not stopped and (tried or not pending)


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


def usage_of(path):
    """A thread's token use from its transcript: {"in", "out", "cache_read", "cache_write", "tools",
    "minutes"}, or None when the transcript holds no usage record. Claude Code writes one line per
    content block of a reply, each carrying the whole reply's usage, so a reply is counted once by
    its message id (else its request id). Tokens only: prices change, so no money figure."""
    replies, tools, stamps = {}, set(), []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                stamp = row.get("timestamp")
                if isinstance(stamp, str):
                    stamps.append(stamp)
                message = row.get("message")
                if row.get("type") != "assistant" or not isinstance(message, dict):
                    continue
                if isinstance(message.get("usage"), dict):
                    replies[message.get("id") or row.get("requestId") or n] = message["usage"]
                for c in message.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        tools.add(c.get("id") or f"{n}:{len(tools)}")
    except OSError:
        return None
    if not replies:
        return None

    def total(key):
        return sum(u.get(key) for u in replies.values() if isinstance(u.get(key), int))

    minutes = 0.0
    try:
        from datetime import datetime
        times = sorted(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in stamps)
        minutes = round((times[-1] - times[0]).total_seconds() / 60, 1) if times else 0.0
    except (ValueError, TypeError):
        pass
    return {"in": total("input_tokens"), "out": total("output_tokens"), "cache_read": total("cache_read_input_tokens"),
            "cache_write": total("cache_creation_input_tokens"), "tools": len(tools), "minutes": minutes}


def file_cost(root, transcript, agent_id=""):
    """One `cost` LOG line on the item the thread's brief names: its token use so far (a resumed
    thread's transcript grows, so each line is its total to date; items.py status counts the
    latest line per agent). Nothing when the brief names no item or the transcript has no usage."""
    try:
        import items
        brief, _ = from_transcript_any(transcript)
        item_id = items.find_id(brief)
        use = usage_of(transcript) if item_id and items.find(root, item_id) else None
        if not use:
            return
        note = " ".join(f"{k}={use[k]}" for k in ("in", "out", "cache_read", "cache_write", "tools", "minutes"))
        items.log(root, item_id, "cost", note + (f" agent={agent_id}" if agent_id else ""))
    except Exception:
        pass


def file_report(root, brief, report, agent_type, agent_id=""):
    """A thread briefed with `ITEM: <id>` gets its report filed under the item (REPORT.md for a
    kit:implementer, VERDICT.md for a kit:verifier), with one LOG line that names the agent: the
    mailbox the coordinator and the user read on disk. A verifier's `REVIEWED: <sha>` line is
    noted too. Silent when the brief names no item."""
    try:
        import items
        item_id = items.find_id(brief)
        if not item_id or not items.find(root, item_id):
            return
        who = f", agent {agent_id}" if agent_id else ""
        if agent_type.endswith("verifier"):
            m = re.search(r"^\W*VERDICT:\s*([A-Z_]+(?:\s+scope=\S+)?)", report, re.M)
            sha = re.search(r"^\W*REVIEWED:\s*`?([0-9a-fA-F]{7,40})\b", report, re.M)
            note = (m.group(1) if m else "no verdict line") + (f", reviewed {sha.group(1)}" if sha else "") + who
            items.write(root, item_id, "VERDICT.md", report, "verdict", note)
        else:
            status = re.search(r"^\W*STATUS:\s*(\w+)", report, re.M)
            decisions = len(re.findall(r"^\s*(?:-\s*)?DECISION:", report, re.M))
            note = (status.group(1) if status else "no status line") + (f", {decisions} decision(s)" if decisions else "") + who
            items.write(root, item_id, "REPORT.md", report, "reported", note)
    except Exception:
        pass


def main():
    if sys.argv[1:2] == ["--missing"]:
        return 1 if len(sys.argv) > 2 and missing_report(sys.argv[2]) else 0
    data = kitlib.read_input()
    # the items live in the main checkout: a thread stopping in its worktree (cwd) has no lead/ of its own
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    root = kitlib.main_checkout(cwd) or kitlib.project_root(data)
    config, _ = kitlib.load_config(root)
    if config is None:  # not opted in: no nudge, nothing filed
        return 0
    transcript = data.get("agent_transcript_path")
    # once per stop: the second stop (stop_hook_active) is the hooks module's to report
    if transcript and not data.get("stop_hook_active") and missing_report(transcript):
        print(json.dumps({"decision": "block", "reason": NO_REPORT}))
        return 0
    agent_type = str(data.get("agent_type") or "")
    if transcript:  # before the report line, so the item's last event stays the report
        file_cost(root, transcript, str(data.get("agent_id") or ""))
    if agent_type not in KIT_TYPES:
        return 0
    report = data.get("last_assistant_message") or ""
    agent_id = str(data.get("agent_id") or "")
    brief = ""
    if not agent_type.endswith("verifier"):  # a thread: file its report, nothing else to parse
        if data.get("agent_transcript_path"):
            brief, handed = from_transcript_any(data["agent_transcript_path"])
            report = handed or report  # the hand-back is the report; the closing text is not
        file_report(root, brief, report, agent_type, agent_id)
        return 0
    if data.get("agent_transcript_path"):
        brief, handed = from_transcript(data["agent_transcript_path"])
        report = report if HAS_VERDICT.search(report) else handed
    file_report(root, brief, report, agent_type, agent_id)
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
