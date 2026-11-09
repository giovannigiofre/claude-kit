#!/usr/bin/env python3
"""Self-check for subagent_stop.py's missing-report nudge (the verdict parsing is in test_lessons.py).

Run: python3 plugins/kit/hooks/tests/test_subagent_stop.py   (exit 0 = all good)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

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


def stop(tmp, entries, active=False):
    path = Path(tmp) / "agent.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    out = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=30, cwd=tmp,
                         input=json.dumps({"cwd": tmp, "agent_type": "general-purpose", "agent_id": "a1",
                                           "stop_hook_active": active, "agent_transcript_path": str(path)}))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


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
    print("subagent_stop: all checks passed")


if __name__ == "__main__":
    main()
