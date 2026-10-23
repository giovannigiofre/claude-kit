#!/usr/bin/env python3
"""Self-check for overnight.py, with a fake agent instead of `claude -p`.

Run: python3 plugins/kit/skills/overnight/tests/test_overnight.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "overnight.py"

# The fake agent reads a plan (one action per iteration) and plays it:
#   change  -> edits work.txt, reports progress
#   bad     -> writes bad.txt (the gate rejects it), reports progress
#   noop    -> changes nothing, reports no-op
#   done    -> edits work.txt, reports done with stop_condition_met
#   blocked -> edits work.txt, reports blocked
#   error   -> exits 1
FAKE = r'''
import json, os, sys
from pathlib import Path
state = Path(os.environ["FAKE_STATE"])
plan = (state / ".fake_plan").read_text().split()
counter = state / ".fake_count"
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
action = plan[n] if n < len(plan) else "noop"
prompt = sys.argv[sys.argv.index("-p") + 1]
(state / ".fake_last_prompt").write_text(prompt)
if action == "error":
    print("boom", file=sys.stderr); sys.exit(1)
if action == "limit":
    print(json.dumps({"type": "result", "is_error": True, "result": "You've hit your session limit"})); sys.exit(1)
if action == "commitbad":
    import subprocess
    Path("bad.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "agent commit"], check=True)
if action in ("change", "done", "blocked", "blank"):
    with open("work.txt", "a") as fh: fh.write(f"step {n}\n")
if action == "bad":
    Path("bad.txt").write_text("x")
status = {"change": "progress", "bad": "progress", "noop": "no-op", "done": "done", "blocked": "blocked",
          "blank": "progress", "commitbad": "progress"}[action]
summary = "   " if action == "blank" else f"{action} {n}"
print(json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.5,
                  "usage": {"input_tokens": 100, "cache_creation_input_tokens": 50, "output_tokens": 10,
                            "cache_read_input_tokens": 9999},
                  "structured_output": {"status": status, "summary": summary,
                                        "stop_condition_met": action == "done"}}))
'''


def repo(plan):
    d = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q", "-b", "main", str(d)], check=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    (d / "work.txt").write_text("start\n")
    (d / ".gitignore").write_text(".fake_*\n")
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "init"], check=True)
    (d / ".fake_plan").write_text(" ".join(plan))
    fake = d.parent / f"fake_agent_{d.name}.py"
    fake.write_text(FAKE)
    return d, fake


def env(d):
    return {**os.environ, "FAKE_STATE": str(d)}


def run(d, fake, *args):
    out = subprocess.run([sys.executable, str(SCRIPT), "improve work.txt", "--agent-cmd",
                          f"{sys.executable} {fake}", "--gate", "test ! -e bad.txt",
                          "--rate-limit-wait", "0", *args],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0, out.stderr + out.stdout
    run_dir = sorted((d / ".claude" / "overnight").iterdir())[-1]
    return out.stdout, json.loads((run_dir / "end-state.json").read_text()), run_dir


def commits(d):
    return subprocess.run(["git", "-C", str(d), "log", "--oneline"], capture_output=True, text=True).stdout.splitlines()


def clean(d):
    return subprocess.run(["git", "-C", str(d), "status", "--porcelain"], capture_output=True, text=True).stdout.strip() == ""


def test_progress_until_done():
    d, fake = repo(["change", "change", "done"])
    out, end, run_dir = run(d, fake, "--stop-when", "work.txt has 3 steps")
    assert len(end["commits"]) == 3, end
    assert end["stop_reason"].startswith("stop condition met"), end
    assert end["branch"].startswith("overnight/improve-work-txt-")
    assert len(commits(d)) == 4 and clean(d)
    assert "WARNING no budget" in out
    notes = (run_dir / "notes.md").read_text()
    assert notes.count("[runner]") == 3, notes


def test_noop_and_gate_failures_stop_after_three():
    d, fake = repo(["noop", "bad", "noop", "change"])
    _, end, run_dir = run(d, fake)
    assert end["commits"] == [] and end["iteration"] == 3, end
    assert "3 consecutive" in end["stop_reason"]
    assert not (d / "bad.txt").exists() and clean(d)
    assert "gate failed" in (run_dir / "notes.md").read_text()


def test_failure_counter_resets_after_success():
    d, fake = repo(["noop", "noop", "change", "noop", "noop", "change", "done"])
    _, end, _ = run(d, fake)
    assert len(end["commits"]) == 3 and end["iteration"] == 7, end


def test_budget_cap():
    d, fake = repo(["change"] * 10)
    out, end, _ = run(d, fake, "--max-usd", "1.0")
    assert end["iteration"] == 2 and "budget" in end["stop_reason"], end
    assert "WARNING" not in out


def test_token_and_iteration_caps():
    d, fake = repo(["change"] * 10)
    _, end, _ = run(d, fake, "--max-tokens", "400")
    assert end["iteration"] == 3 and end["tokens"] == 480, end  # 160 per iteration, cache reads excluded
    d, fake = repo(["change"] * 10)
    _, end, _ = run(d, fake, "--max-iterations", "2")
    assert end["iteration"] == 2 and len(end["commits"]) == 2, end


def test_blocked_undoes_and_stops():
    d, fake = repo(["change", "blocked"])
    _, end, _ = run(d, fake)
    assert len(end["commits"]) == 1 and end["stop_reason"].startswith("blocked"), end
    assert clean(d)


def test_agent_error_counts_as_failure():
    d, fake = repo(["error", "error", "error"])
    _, end, _ = run(d, fake)
    assert end["commits"] == [] and "3 consecutive" in end["stop_reason"], end


def test_notes_reach_the_next_prompt():
    d, fake = repo(["change", "noop", "noop", "noop"])
    run(d, fake)
    assert "committed" in (d / ".fake_last_prompt").read_text()


def test_dirty_tree_refused():
    d, fake = repo(["change"])
    (d / "work.txt").write_text("edited\n")
    out = subprocess.run([sys.executable, str(SCRIPT), "x", "--agent-cmd", f"{sys.executable} {fake}"],
                         cwd=d, capture_output=True, text=True, env=env(d))
    assert out.returncode != 0 and "not clean" in (out.stderr + out.stdout)


def test_resume_continues_on_the_same_branch():
    d, fake = repo(["change", "change", "change", "done"])
    _, end, run_dir = run(d, fake, "--max-iterations", "2")
    assert len(end["commits"]) == 2
    out = subprocess.run([sys.executable, str(SCRIPT), "--resume", str(run_dir), "--max-iterations", "10",
                          "--agent-cmd", f"{sys.executable} {fake}", "--gate", "test ! -e bad.txt"],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0, out.stderr
    end2 = json.loads((run_dir / "end-state.json").read_text())
    assert len(end2["commits"]) == 4 and end2["stop_reason"].startswith("stop condition met"), end2


def test_worktree_leaves_main_checkout_alone():
    d, fake = repo(["change", "done"])
    wt = d.parent / f"{d.name}-wt"
    out = subprocess.run([sys.executable, str(SCRIPT), "improve", "--worktree", str(wt),
                          "--agent-cmd", f"{sys.executable} {fake}", "--gate", "true"],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0, out.stderr
    assert len(commits(d)) == 1, "main checkout must not get commits"
    assert len(commits(wt)) == 3, commits(wt)
    assert (wt / "work.txt").read_text().count("step") == 2


def test_blank_summary_still_commits():
    d, fake = repo(["blank", "done"])
    _, end, _ = run(d, fake)
    assert len(end["commits"]) == 2 and end["commits"][0]["summary"] == "", end


def test_agent_commit_goes_through_the_gate():
    d, fake = repo(["commitbad", "noop", "noop"])
    _, end, _ = run(d, fake)
    assert end["commits"] == [] and not (d / "bad.txt").exists(), end
    assert len(commits(d)) == 1 and clean(d), commits(d)


def test_commit_hook_refusal_is_a_failure():
    d, fake = repo(["change", "change", "change"])
    hook = d / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho refused by hook >&2\nexit 1\n")
    hook.chmod(0o755)
    _, end, run_dir = run(d, fake)
    assert end["commits"] == [] and "3 consecutive" in end["stop_reason"], end
    assert "commit refused" in (run_dir / "notes.md").read_text() and clean(d)


def test_session_limit_waits_instead_of_failing():
    d, fake = repo(["limit", "change", "done"])
    out = subprocess.run([sys.executable, str(SCRIPT), "x", "--agent-cmd", f"{sys.executable} {fake}",
                          "--gate", "true", "--rate-limit-wait", "1"],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0 and "waiting 1s" in out.stdout, out.stdout + out.stderr
    run_dir = sorted((d / ".claude" / "overnight").iterdir())[-1]
    end = json.loads((run_dir / "end-state.json").read_text())
    assert len(end["commits"]) == 2 and end["iteration"] == 2, end


def test_worktree_allowed_with_dirty_main_checkout():
    d, fake = repo(["change", "done"])
    (d / "work.txt").write_text("my uncommitted edit\n")
    wt = d.parent / f"{d.name}-wt2"
    out = subprocess.run([sys.executable, str(SCRIPT), "improve", "--worktree", str(wt),
                          "--agent-cmd", f"{sys.executable} {fake}", "--gate", "true"],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0, out.stderr
    assert (d / "work.txt").read_text() == "my uncommitted edit\n"
    assert len(commits(wt)) == 3


def test_resume_resets_the_failure_streak():
    d, fake = repo(["noop", "noop", "noop", "change", "done"])
    _, end, run_dir = run(d, fake)
    assert "3 consecutive" in end["stop_reason"]
    out = subprocess.run([sys.executable, str(SCRIPT), "--resume", str(run_dir),
                          "--agent-cmd", f"{sys.executable} {fake}"],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0, out.stderr
    end2 = json.loads((run_dir / "end-state.json").read_text())
    assert len(end2["commits"]) == 2 and end2["stop_reason"].startswith("stop condition met"), end2


def test_dry_run_creates_nothing():
    d, fake = repo(["change"])
    out = subprocess.run([sys.executable, str(SCRIPT), "x", "--dry-run", "--agent-cmd", "false"],
                         cwd=d, capture_output=True, text=True, env=env(d))
    assert out.returncode == 0 and "iteration 1" in out.stdout, out.stderr
    assert not (d / ".claude").exists() and len(commits(d)) == 1
    branch = subprocess.run(["git", "-C", str(d), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    assert branch == "main", branch


if __name__ == "__main__":
    os.environ.pop("KIT_OVERNIGHT_AGENT", None)
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failed else 0)
