#!/usr/bin/env python3
"""Self-check for subagent_stop.py's missing-report nudge (the verdict parsing is in test_lessons.py).

Run: python3 plugins/kit/hooks/tests/test_subagent_stop.py   (exit 0 = all good)
"""

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# run alone or through tests/run_all.py, the hooks' opt-in records (kitlib.latch_opt_in) go to a
# temp folder, never the user's config dir: running the test files alone once left 84 records there
if not os.environ.get("KIT_OPT_IN_DIR"):
    os.environ["KIT_OPT_IN_DIR"] = tempfile.mkdtemp(prefix="kit-opt-in-")
    atexit.register(shutil.rmtree, os.environ["KIT_OPT_IN_DIR"], True)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "subagent_stop.py"
REMINDER = "<system-reminder>\nYour final report is delivered through SubagentHandback: when your work is complete...</system-reminder>"


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def call(tid, name, args):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": args}]}}


def result(tid, text, is_error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
                                                     "content": [{"type": "text", "text": text}]}]}}


DELIVERED = '{"success":true,"message":"Report delivered to your caller."}'
REFUSED = '{"success":false,"message":"Nothing was sent: your report was already delivered."}'


def stop(tmp, entries, active=False, agent_type="general-purpose", said=None, late=None, after=0.0):
    """Run the hook on a transcript of `entries`. `late` entries are appended by a thread `after`
    seconds from the hook's start, as Claude Code does when a hand-back lands while the hook reads."""
    path = Path(tmp) / "agent.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    payload = {"cwd": tmp, "agent_type": agent_type, "agent_id": "a1", "stop_hook_active": active,
               "agent_transcript_path": str(path)}
    if said is not None:
        payload["last_assistant_message"] = said
    proc = subprocess.Popen([sys.executable, str(SCRIPT)], cwd=tmp, text=True, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    writer = None
    if late:
        def append():
            time.sleep(after)
            with open(path, "a") as f:
                f.write("".join(json.dumps(e) + "\n" for e in late))
        writer = threading.Thread(target=append)
        writer.start()
    out, err = proc.communicate(json.dumps(payload), timeout=30)
    if writer:
        writer.join()
    assert proc.returncode == 0, err
    return json.loads(out) if out.strip() else {}


def stamped(when, entry):
    return dict(entry, timestamp=when)


def used(tid="m1"):
    return {"type": "assistant", "message": {"id": tid, "content": [{"type": "text", "text": "working"}],
                                             "usage": {"input_tokens": 10, "output_tokens": 5}}}


def item_checks(tmp):
    """The filing side of the stop: a hand-back that lands while the hook reads is filed, a report
    only in the payload is filed, no report blocks once with the cost kept, a repeat is filed once."""
    sys.path.insert(0, str(SCRIPT.parent))
    import items
    root = Path(tmp)
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "kit.json").write_text("{}")

    def lines(item_id, status):
        log = (items.find(root, item_id) / "LOG.md").read_text()
        return [l for l in log.splitlines() if f"| {status} |" in l]

    # the hook read too early and gave up after about 0.6 s (review of 2.0.1): a hand-back that
    # lands 0.5, 1.0 or 1.4 s after the hook starts is filed, and nothing blocks
    for delay in (0.5, 1.0, 1.4):
        item_id = items.new(root, f"late {int(delay * 10)}")
        brief = [user(f"ITEM: {item_id}\nbrief"), user(REMINDER), used()]
        late = [call("h1", "SubagentHandback", {"message": f"STATUS: done\nITEM: {item_id}"}), result("h1", DELIVERED)]
        got = stop(tmp, brief, agent_type="kit:implementer", late=late, after=delay)
        assert got == {}, (delay, got)
        assert lines(item_id, "reported"), f"a hand-back {delay} s late is filed"

    # a report only in the stop's payload is taken as delivered and filed, for both kinds
    for kind, text, name in (("kit:verifier", "VERDICT: PASS\nREVIEWED: main, abc1234\n", "VERDICT.md"),
                             ("kit:implementer", "STATUS: done\nCHANGED: a.py\n", "REPORT.md")):
        item_id = items.new(root, f"payload {kind[4:]}")
        got = stop(tmp, [user(f"ITEM: {item_id}\nbrief"), user(REMINDER), used()], agent_type=kind, said=text)
        assert got == {}, (kind, got)
        assert (items.find(root, item_id) / name).read_text() == text, kind

    # no report anywhere: one block, and the cost line is kept for a thread that never stops again
    item_id = items.new(root, "silent")
    run = [user(f"ITEM: {item_id}\nbrief"), user(REMINDER), used()]
    assert stop(tmp, run, agent_type="kit:implementer").get("decision") == "block"
    assert lines(item_id, "cost"), "the cost line is written before the block"
    assert stop(tmp, run, agent_type="kit:implementer", active=True) == {}, "blocked once only"

    # the same report seen on two stops leaves one LOG line
    item_id = items.new(root, "twice")
    run = [user(f"ITEM: {item_id}\nbrief"), user(REMINDER), used(),
           call("h2", "SubagentHandback", {"message": "STATUS: done"}), result("h2", DELIVERED)]
    assert stop(tmp, run, agent_type="kit:implementer") == {}
    assert stop(tmp, run, agent_type="kit:implementer") == {}
    assert len(lines(item_id, "reported")) == 1, "one LOG line per report"


def minutes_checks(tmp):
    """Active minutes: each gap between entries counts up to five minutes, whatever their order,
    and a missing or unparsable stamp is skipped instead of zeroing the line."""
    sys.path.insert(0, str(SCRIPT.parent))
    import subagent_stop as ss
    path = Path(tmp) / "minutes.jsonl"

    def minutes(stamps):
        rows = [stamped(t, used(f"m{n}")) if t is not None else used(f"m{n}") for n, t in enumerate(stamps)]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return ss.usage_of(path)["minutes"]

    a, b, c = "2026-11-14T10:00:00Z", "2026-11-14T10:01:00Z", "2026-11-14T11:01:00Z"
    assert minutes([a, b, c]) == 6.0, "a one-hour hole counts five minutes"
    assert minutes([c, a, b]) == 6.0, "stamps out of order are sorted"
    assert minutes([a, None, b, c]) == 6.0, "an entry without a stamp is skipped"
    assert minutes([a, "not a time", b, c]) == 6.0, "one unparsable stamp leaves the other gaps counted"
    assert minutes([a, "2026-11-14T10:01:00", c]) == 6.0, "a stamp without a zone is read as UTC"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        server = dict(result("t0", "Command running in background"), toolUseResult={"backgroundTaskId": "bsrv"})
        run1 = [user("ITEM: B2. brief"), user(REMINDER), call("t0", "Bash", {"command": "npm run dev"}), server,
                call("t1", "SubagentHandback", {"message": "r1"}), result("t1", DELIVERED)]
        # the B2 case: resumed by the coordinator, the second hand-back refused, the run ends in plain text
        # while its dev server still runs
        resumed = run1 + [user("The coordinator sent a message while you were working: fix 1-6"), user(REMINDER),
                          call("t2", "SubagentHandback", {"message": "r2"}), result("t2", REFUSED)]
        assert stop(tmp, resumed) == {}, "a project without .claude/kit.json gets no nudge: every hook is a no-op there"
        (Path(tmp) / ".claude").mkdir()
        (Path(tmp) / ".claude" / "kit.json").write_text("{}")  # present, even empty: opted in
        assert stop(tmp, run1) == {}, "a delivered report: the stop goes through"
        nudge = stop(tmp, resumed)
        assert nudge.get("decision") == "block" and "SendMessage" in nudge["reason"], nudge
        assert stop(tmp, resumed, active=True) == {}, "nudged once: the second stop is the hooks module's"
        assert stop(tmp, resumed + [call("t3", "SendMessage", {"to": "main", "message": "r2"}), result("t3", "sent")]) == {}, \
            "a report sent to main after the refusal counts"
        assert stop(tmp, [user("look something up")]) == {}, "a foreground subagent's final text is its report"

        # paused on its own reviewer: its notification resumes it, so no nudge; the person's interrupt is theirs
        waiting = [user("ITEM: B2. brief"), user(REMINDER), call("t4", "Agent", {"prompt": "review"}),
                   dict(result("t4", "launched"), toolUseResult={"status": "async_launched", "agentId": "r1"})]
        assert stop(tmp, waiting) == {}, "a thread waiting on its own subagent has not ended"
        assert stop(tmp, waiting + [user("<task-notification><task-id>r1</task-id></task-notification>")]).get("decision") == "block"
        assert stop(tmp, [user("ITEM: B2. brief"), user(REMINDER), user("[Request interrupted by user]")]) == {}, "an interrupted run is the person's"
    with tempfile.TemporaryDirectory() as tmp:
        item_checks(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        minutes_checks(tmp)
    # the verifier's report since 1.16: a QUESTIONS block ends the PROBLEMS block (a question is not a
    # problem), and a preflight stop carries its reason after CANNOT_VERIFY
    sys.path.insert(0, str(SCRIPT.parent))
    import subagent_stop as _ss
    got = _ss.parse("VERDICT: FAIL scope=local:src/a.py\nREVIEWED: main, abc123\nEVIDENCE: pytest: 3 passed\n"
                    "PROBLEMS:\n1. src/a.py:10 - empty list - returns None - no test covers it\n"
                    "QUESTIONS:\n1. is the retry meant to be unbounded?\nNOT CHECKED: none\n")
    assert got == ("FAIL", ["src/a.py:10 - empty list - returns None - no test covers it"]), got
    got = _ss.parse("VERDICT: CANNOT_VERIFY: ci-red\nREVIEWED: main, abc\nEVIDENCE: gh pr view: 2 failing\n"
                    "PROBLEMS:\nQUESTIONS:\nNOT CHECKED: everything\n")
    assert got == ("CANNOT_VERIFY", []), got
    with tempfile.TemporaryDirectory() as tmp:
        reread_checks(tmp, _ss)
    print("subagent_stop: all checks passed")


def reread_checks(tmp, ss):
    """The re-reads read the whole transcript, and only when its size or mtime changed (review round
    3: a read of its last 2 MB gave other answers than the whole file, in the F2 and C cases)."""
    (Path(tmp) / ".claude").mkdir()
    (Path(tmp) / ".claude" / "kit.json").write_text("{}")
    work = [user("y" * 10000)] * 300  # 3 MB of a run's own lines
    # F2: a refused hand-back near the start, 3 MB of work, then a background task; the whole read
    # says no report reached the caller, so the stop is blocked
    started = dict(result("b1", "started"), toolUseResult={"backgroundTaskId": "t9"})
    f2 = [user("ITEM: B2. brief"), user(REMINDER), call("h1", "SubagentHandback", {"message": "STATUS: done"}),
          result("h1", "refused: servers running", is_error=True)] + work + [started]
    assert stop(tmp, f2).get("decision") == "block", "F2: a refused hand-back far back is still no report"
    # C: a 3 MB hand-back lands while the hook re-reads; its call line starts more than 2 MB before the end
    big = call("h1", "SubagentHandback", {"message": "STATUS: done " + "r" * (3 * 1024 * 1024)})
    c = [user("ITEM: B2. brief"), user(REMINDER)] + [user("y" * 10000)] * 100
    assert stop(tmp, c, late=[big, result("h1", DELIVERED)], after=0.8) == {}, "C: a large hand-back that lands late counts"

    path = Path(tmp) / "agent.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in [user("ITEM: B2. brief"), user(REMINDER)] + work))
    calls, whole, sleep = [], ss.missing_report, ss.time.sleep
    ss.missing_report = lambda p: calls.append(p) or whole(p)
    try:
        assert ss.still_missing(path, tries=3, pause=0), "no report over the re-reads"
        assert len(calls) == 1, f"an unchanged file is read once: {len(calls)} reads"
        calls.clear()
        appended = []

        def grow(_):  # the file grows during the first pause only
            if not appended:
                appended.append(1)
                with open(path, "a") as f:
                    f.write(json.dumps(user("more work")) + "\n")
        ss.time.sleep = grow
        assert ss.still_missing(path, tries=3, pause=0)
        assert len(calls) == 2, f"read again once after the file changed: {len(calls)} reads"
    finally:
        ss.missing_report, ss.time.sleep = whole, sleep


if __name__ == "__main__":
    main()
