#!/usr/bin/env python3
"""Stop: run kit.json `check` before Claude may end its turn.

- Runs only when the working tree changed since the last passing check in this session,
  so question-and-answer turns cost nothing.
- On failure exits 2: Claude gets the output and keeps working.
- After `maxStopRetries` consecutive failures (default 3) it lets Claude stop, so a check
  Claude cannot fix never traps the session; Claude must then report the failure.
- Each failure is counted in the kit's lesson ledger (lessons.py) by its first error line, once
  per session; the same failure in a second session becomes a lesson.
"""

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def tree_fingerprint(root):
    code, status = kitlib.run_shell("git status --porcelain=v1 -uall", root, timeout=30)
    if code != 0:
        return None
    _, diff = kitlib.run_shell("git diff HEAD", root, timeout=30)
    return hashlib.sha256((status + "\0" + diff).encode()).hexdigest()


def first_error(out):
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return next((ln for ln in lines if re.search(r"error|fail|✖|✗|×", ln, re.I)), lines[0] if lines else "")


def record_failure(root, check, out, session):
    try:
        import lessons
        line = first_error(out)
        shape = re.sub(r"\d+", "N", line)
        key = "gate-" + hashlib.sha1(f"{check}\0{shape}".encode()).hexdigest()[:10]
        lessons.capture(root, "gate", key, f"The fast check `{check[:80]}` has failed before with: {line[:160]}",
                        kind="gate", agents=("lead", "implementer"), once_per=session)
    except Exception:
        pass


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, err = kitlib.load_config(root)
    if err:
        print(err, file=sys.stderr)
        return 0
    if not config or not config.get("check"):
        return 0
    session = data.get("session_id", "")
    state = kitlib.load_state(session, "stop")
    fp = tree_fingerprint(root)
    if fp is None or fp == state.get("passed_fp"):
        return 0
    code, out = kitlib.run_shell(config["check"], root, timeout=int(config.get("checkTimeout", 540)))
    if code == 0:
        kitlib.save_state(session, "stop", {"passed_fp": fp, "fails": 0})
        return 0
    record_failure(root, config["check"], out, session)
    fails = int(state.get("fails", 0)) + 1
    limit = int(config.get("maxStopRetries", 3))
    kitlib.save_state(session, "stop", {"passed_fp": state.get("passed_fp"), "fails": fails})
    if fails > limit:
        # let the session end; the next change starts a fresh count
        kitlib.save_state(session, "stop", {"passed_fp": fp, "fails": 0})
        return 0
    print(
        f"kit check failed (attempt {fails}/{limit}). Fix the cause, or if it cannot be fixed "
        f"in this task, say so explicitly in your final message.\n$ {config['check']}\n"
        + kitlib.tail(out, 60),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
