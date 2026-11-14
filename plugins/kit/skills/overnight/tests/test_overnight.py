#!/usr/bin/env python3
"""Self-check for overnight.py, with a fake agent instead of `claude -p`.

Run: python3 plugins/kit/skills/overnight/tests/test_overnight.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "overnight.py"

# The fake agent reads a plan (one action per iteration) and plays it:
#   change  -> edits work.txt, reports progress
#   bad     -> writes bad.txt (the gate rejects it), reports progress
#   noop    -> changes nothing, reports no-op
#   done    -> edits work.txt, reports done with stop_condition_met
#   blocked -> edits work.txt, reports blocked
#   error   -> exits 1
#   stall   -> changes nothing but reports progress (an early stop the runner resumes)
#   nostart -> exits 1 the 2.1.314 way: nothing on stdout, the startup error on stderr
#   nodisk  -> exits 1 the 2.1.317 way: edits work.txt, prints the result, then the full-disk error on stderr
#   nocheck -> exits 1 the 2.1.319 way: auto mode refused every action for lack of a safety check
# FAKE_EXPIRES, when set, is reported as credential_expires_at on every result.
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
(state / ".fake_last_argv").write_text(json.dumps(sys.argv[1:]))
if action == "error":
    print("boom", file=sys.stderr); sys.exit(1)
if action == "limit":
    print(json.dumps({"type": "result", "is_error": True, "result": "You've hit your session limit"})); sys.exit(1)
if action == "nostart":
    print("Not logged in. Run claude auth login to authenticate.", file=sys.stderr); sys.exit(1)
if action == "nocheck":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "stopped_by_permission_check": True,
                      "safety_stops": 3, "permission_denials": [], "total_cost_usd": 0.1, "session_id": f"fake-{n}",
                      "result": "Auto mode is unavailable: the server returned no safety verdict for 3 responses "
                                "in a row, so this turn has ended."})); sys.exit(1)
if action == "commitbad":
    import subprocess
    Path("bad.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "agent commit"], check=True)
if action in ("change", "done", "blocked", "blank", "nodisk"):
    with open("work.txt", "a") as fh: fh.write(f"step {n}\n")
if action == "bad":
    Path("bad.txt").write_text("x")
status = {"change": "progress", "bad": "progress", "noop": "no-op", "done": "done", "blocked": "blocked",
          "blank": "progress", "commitbad": "progress", "stall": "progress", "nodisk": "progress"}[action]
summary = "   " if action == "blank" else f"{action} {n}"
expires = os.environ.get("FAKE_EXPIRES")
print(json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.5, "session_id": f"fake-{n}",
                  "usage": {"input_tokens": 100, "cache_creation_input_tokens": 50, "output_tokens": 10,
                            "cache_read_input_tokens": 9999},
                  "structured_output": {"status": status, "summary": summary,
                                        "stop_condition_met": action == "done"},
                  **({"credential_expires_at": expires} if expires else {})}))
if action == "nodisk":
    print("Error: Claude Code could not save this session's transcript under ~/.claude/projects because the disk "
          "is full (ENOSPC). If you resume this session, part of the conversation may be missing. Free up space "
          "on that disk before the next run.", file=sys.stderr)
    sys.exit(1)
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


def run(d, fake, *args, env_extra=None):
    out = subprocess.run([sys.executable, str(SCRIPT), "improve work.txt", "--agent-cmd",
                          f"{sys.executable} {fake}", "--gate", "test ! -e bad.txt",
                          "--rate-limit-wait", "0", *args],
                         cwd=d, capture_output=True, text=True, timeout=120, env={**env(d), **(env_extra or {})})
    assert out.returncode == 0, out.stderr + out.stdout
    run_dir = sorted(runs(d).iterdir())[-1]
    return out.stdout, json.loads((run_dir / "end-state.json").read_text()), run_dir


def runs(d):
    """Where the runs went: `.kit/overnight`, or `.claude/overnight` in a project not moved yet."""
    for name in (".kit", ".claude"):
        if (d / name / "overnight").is_dir():
            return d / name / "overnight"
    raise AssertionError(f"no run directory under {d}")


def excluded(d):
    return (d / ".git" / "info" / "exclude").read_text().splitlines()


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


def test_early_stop_is_resumed_then_counted():
    d, fake = repo(["stall", "change", "done"])
    _, end, run_dir = run(d, fake, "--effort", "medium")
    assert len(end["commits"]) == 2 and end["iteration"] == 2, end
    argv = json.loads((d / ".fake_last_argv").read_text())
    assert "--append-system-prompt" in argv and "--effort" in argv and argv[argv.index("--effort") + 1] == "medium"
    log = [json.loads(line) for line in (run_dir / "log.jsonl").read_text().splitlines()]
    resumed = [e for e in log if e.get("continuation")]
    assert len(resumed) == 1, log
    d, fake = repo(["stall", "stall", "stall", "noop", "noop"])
    _, end, run_dir = run(d, fake, "--max-continuations", "2", "--max-failures", "1")
    assert end["commits"] == [] and end["iteration"] == 1, end
    assert "no change" in end["stop_reason"] or "consecutive" in end["stop_reason"], end
    argv = json.loads((d / ".fake_last_argv").read_text())
    assert argv[argv.index("--resume") + 1] == "fake-1", argv
    assert "working tree has no change" in (d / ".fake_last_prompt").read_text()
    d, fake = repo(["stall", "change"])
    _, end, _ = run(d, fake, "--max-iterations", "1")
    assert len(end["commits"]) == 1 and end["iteration"] == 1, "the last iteration is resumed too"


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


def test_fatal_exit_reasons_stop_at_once():
    # 2.1.314 / 2.1.317 / 2.1.319: an exit 1 that no later iteration can recover from ends the run with the fix
    auto_fix = ("auto mode has no server check here: unset DISABLE_TELEMETRY / CLAUDE_CODE_DISABLE_FEATURE_FLAGS, "
                "or set CLAUDE_CODE_AUTO_MODE_SERVER=0")
    for action, expected in (("nocheck", auto_fix),
                             ("nodisk", "the disk is full or over quota and claude -p lost its transcript: "
                                        "free space on that disk, then --resume"),
                             ("nostart", "claude -p could not start (Not logged in. Run claude auth login to "
                                         "authenticate.): fix the login or settings it names, then --resume")):
        d, fake = repo([action, "change", "done"])
        out, end, run_dir = run(d, fake)
        assert end["iteration"] == 1 and end["commits"] == [], (action, end)
        assert end["stop_reason"] == expected, (action, end["stop_reason"])
        assert f"overnight: stopped - {expected}" in out, (action, out)
        assert clean(d) and "run stopped - " in (run_dir / "notes.md").read_text(), action
    # the plain `error` fake still fails three times (test_agent_error_counts_as_failure)


def test_fatal_reason_reads_the_text_too():
    sys.path.insert(0, str(SCRIPT.parent))
    import overnight
    assert overnight.fatal_reason({}, "Auto mode unavailable - stopped after repeated responses with no safety verdict") \
        == overnight.AUTO_MODE_FIX
    assert overnight.fatal_reason({"stopped_by_permission_check": True}, "") == overnight.AUTO_MODE_FIX
    assert "disk is full" in overnight.fatal_reason({}, "Error: Claude Code could not save changes this run made to "
                                                        "~/.claude.json because your disk quota is used up (EDQUOT).")
    assert "(config_file_invalid)" in overnight.fatal_reason({"startup_failure_reason": "config_file_invalid"}, "x")
    assert overnight.fatal_reason({}, "boom") is None
    assert overnight.fatal_reason({"result": "You've hit your session limit"}, "You've hit your session limit") is None
    assert overnight.parse_expiry("2026-11-20T08:00:00.000Z") == datetime(2026, 11, 20, 8, tzinfo=timezone.utc).timestamp()
    assert overnight.parse_expiry("2026-11-20T08:00:00+02:00") == datetime(2026, 11, 20, 6, tzinfo=timezone.utc).timestamp()
    assert overnight.parse_expiry("soon") is None and overnight.parse_expiry(None) is None and overnight.parse_expiry(0) is None


def test_login_expiry_stops_before_the_next_iteration():
    def iso(hours):
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d, fake = repo(["change", "change", "done"])
    out, end, run_dir = run(d, fake, env_extra={"FAKE_EXPIRES": iso(1)})
    assert end["iteration"] == 1 and len(end["commits"]) == 1, end  # the first step is kept, no second one starts
    assert end["stop_reason"].startswith("sign-in ends within 2 h"), end
    assert "overnight: WARNING the claude.ai sign-in ends at " in out and "--resume" in out, out
    # a resumed run reads the sign-in again (it may have been renewed)
    out = subprocess.run([sys.executable, str(SCRIPT), "--resume", str(run_dir), "--agent-cmd", f"{sys.executable} {fake}"],
                         cwd=d, capture_output=True, text=True, timeout=120, env={**env(d), "FAKE_EXPIRES": iso(24 * 30)})
    assert out.returncode == 0, out.stderr
    end2 = json.loads((run_dir / "end-state.json").read_text())
    assert len(end2["commits"]) == 3 and end2["stop_reason"].startswith("stop condition met"), end2
    d, fake = repo(["change", "change", "done"])
    _, end, _ = run(d, fake, env_extra={"FAKE_EXPIRES": iso(24 * 30)})
    assert end["iteration"] == 3 and len(end["commits"]) == 3, end
    d, fake = repo(["change", "done"])
    out, end, _ = run(d, fake, env_extra={"FAKE_EXPIRES": "not a date"})
    assert end["iteration"] == 2 and len(end["commits"]) == 2 and "WARNING the claude.ai" not in out, "unparsable: changes nothing"


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
    run_dir = sorted(runs(d).iterdir())[-1]
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


def test_resume_flag_with_default_value_wins():
    d, fake = repo(["noop"] * 12)
    _, end, run_dir = run(d, fake, "--max-failures", "5")
    assert end["iteration"] == 5, end
    out = subprocess.run([sys.executable, str(SCRIPT), "--resume", str(run_dir), "--max-failures", "3",
                          "--agent-cmd", f"{sys.executable} {fake}"],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0, out.stderr
    end2 = json.loads((run_dir / "end-state.json").read_text())
    assert end2["iteration"] == 8, end2  # 3 more, not 5


def test_project_sandbox_is_passed_to_iterations():
    d, fake = repo(["change", "done"])
    (d / ".claude").mkdir(exist_ok=True)
    block = {"enabled": True, "network": {"allowedDomains": ["github.com"]}}
    (d / ".claude" / "settings.local.json").write_text(json.dumps({"sandbox": block}))
    (d / ".gitignore").write_text(".fake_*\n.claude/settings.local.json\n")
    subprocess.run(["git", "-C", str(d), "commit", "-qam", "ignore local settings"], check=True)
    wt = d.parent / f"{d.name}-wt3"
    out = subprocess.run([sys.executable, str(SCRIPT), "x", "--worktree", str(wt), "--gate", "true",
                          "--agent-cmd", f"{sys.executable} {fake}"],
                         cwd=d, capture_output=True, text=True, timeout=120, env=env(d))
    assert out.returncode == 0 and "sandbox on" in out.stdout, out.stdout + out.stderr
    argv = json.loads((d / ".fake_last_argv").read_text())
    assert argv[argv.index("--settings") + 1] == json.dumps({"sandbox": block}), argv
    d2, fake2 = repo(["done"])
    out = subprocess.run([sys.executable, str(SCRIPT), "x", "--gate", "true", "--agent-cmd", f"{sys.executable} {fake2}"],
                         cwd=d2, capture_output=True, text=True, timeout=120, env=env(d2))
    assert "sandbox off" in out.stdout and "--settings" not in (d2 / ".fake_last_argv").read_text()


def test_dry_run_creates_nothing():
    d, fake = repo(["change"])
    out = subprocess.run([sys.executable, str(SCRIPT), "x", "--dry-run", "--agent-cmd", "false"],
                         cwd=d, capture_output=True, text=True, env=env(d))
    assert out.returncode == 0 and "iteration 1" in out.stdout, out.stderr
    assert not (d / ".claude").exists() and not (d / ".kit").exists() and len(commits(d)) == 1
    branch = subprocess.run(["git", "-C", str(d), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    assert branch == "main", branch


def test_worktree_gate_comes_from_the_main_checkout():
    # kit.json is personal (kept out of git), so a linked worktree has none: the main checkout's gate applies
    import importlib.util
    spec = importlib.util.spec_from_file_location("overnight_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d, _ = repo(["change"])
    (d / ".claude").mkdir()
    (d / ".claude" / "kit.json").write_text(json.dumps({"verify": "make test"}))
    wt = d.parent / f"{d.name}-wt"
    subprocess.run(["git", "-C", str(d), "worktree", "add", "-q", "-b", "feat/x", str(wt)], check=True)
    assert not (wt / ".claude" / "kit.json").exists()
    assert mod.kit_gate(wt) == "make test", mod.kit_gate(wt)
    (d / ".claude" / "kit.json").unlink()
    assert mod.kit_gate(wt) is None, "no kit.json anywhere: no gate"

def test_fresh_project_runs_under_kit_and_excludes_them_first():
    d, fake = repo(["bad", "done"])  # the failed first iteration undoes with git clean -fd
    _, end, run_dir = run(d, fake)
    assert run_dir.parent == d / ".kit" / "overnight" and not (d / ".claude").exists(), run_dir
    assert (run_dir / "notes.md").exists() and len(end["commits"]) == 1, end
    lines = excluded(d)
    assert "/.kit/overnight/" in lines and "/.kit/evidence/" in lines and "/.kit/" not in lines, lines
    assert clean(d)


def test_exclude_lines_are_appended_under_the_kits_lock():
    # the same rule as kitlib.add_exclude_lines, and the same lock file, so the two never race
    import fcntl
    import importlib.util
    spec = importlib.util.spec_from_file_location("overnight_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d = Path(tempfile.mkdtemp())
    info = d / "info" / "exclude"
    info.parent.mkdir()
    info.write_text("/owner-secret.env\n/notes-private/")  # no final newline
    info.chmod(0o640)
    mod.add_lines(info, ["/.kit/overnight/", "/owner-secret.env", "/.kit/evidence/"])
    assert info.read_text() == "/owner-secret.env\n/notes-private/\n/.kit/overnight/\n/.kit/evidence/\n", info.read_text()
    assert info.stat().st_mode & 0o777 == 0o640
    with open(info.parent / "exclude.kit-lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        try:
            mod.add_lines(info, ["/late/"], wait=0.2)
            assert False, "a held lock must stop it"
        except RuntimeError:
            pass
    assert "/late/" not in info.read_text()


def test_project_with_legacy_state_keeps_its_runs_in_claude():
    d, fake = repo(["change", "done"])
    (d / ".claude" / "lead").mkdir(parents=True)  # state from before the move to .kit
    _, end, run_dir = run(d, fake)
    assert run_dir.parent == d / ".claude" / "overnight" and not (d / ".kit").exists(), run_dir
    assert "/.claude/overnight/" in excluded(d) and len(end["commits"]) == 2 and clean(d)


def test_a_symlinked_kit_folder_is_not_where_runs_go():
    import importlib.util
    spec = importlib.util.spec_from_file_location("overnight_under_test", SCRIPT)
    overnight = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overnight)
    d = Path(tempfile.mkdtemp())
    elsewhere = Path(tempfile.mkdtemp())
    (d / ".kit").symlink_to(elsewhere)
    assert overnight.runs_dir(d) == d / ".claude" / "overnight", overnight.runs_dir(d)
    main = Path(tempfile.mkdtemp())
    (main / ".kit").symlink_to(elsewhere)
    tree = Path(tempfile.mkdtemp())
    assert overnight.runs_dir(tree, main) == tree / ".claude" / "overnight", "a worktree follows the main checkout"


def test_push_sends_the_branch_to_origin_once_at_the_end():
    d, fake = repo(["change", "done"])
    remote = Path(tempfile.mkdtemp()) / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "-C", str(d), "remote", "add", "origin", str(remote)], check=True)
    out, end, run_dir = run(d, fake, "--push")
    branch = end["branch"]
    assert end["pushed"] == f"pushed {branch} to origin", end
    on_remote = subprocess.run(["git", "-C", str(remote), "rev-parse", branch], capture_output=True, text=True).stdout.strip()
    here = subprocess.run(["git", "-C", str(d), "rev-parse", branch], capture_output=True, text=True).stdout.strip()
    assert on_remote == here and on_remote, (on_remote, here)
    assert "push: pushed" in (run_dir / "notes.md").read_text()
    d, fake = repo(["change", "done"])
    _, end, _ = run(d, fake, "--push")
    assert end["pushed"] == "skipped: no origin remote", end
    d, fake = repo(["noop", "noop", "noop"])
    _, end, _ = run(d, fake, "--push")
    assert "pushed" not in end and not end["commits"], end  # nothing to push: no push at all
    _, end, _ = run(*repo(["change", "done"]))
    assert "pushed" not in end, end  # without --push the run never pushes


def test_detach_returns_at_once_and_the_run_goes_on():
    d, fake = repo(["change", "change", "done"])  # a 3 s gate per step keeps it running past the launcher's wait
    started = time.monotonic()
    out = subprocess.run([sys.executable, str(SCRIPT), "improve work.txt", "--agent-cmd", f"{sys.executable} {fake}",
                          "--gate", "sleep 3", "--rate-limit-wait", "0", "--detach"],
                         cwd=d, capture_output=True, text=True, timeout=60, env=env(d))
    assert out.returncode == 0 and time.monotonic() - started < 20, out.stdout + out.stderr
    assert "started in the background, pid" in out.stdout and "overnight: branch overnight/" in out.stdout, out.stdout
    logs = list((runs(d) / "launch").iterdir())
    assert len(logs) == 1 and str(logs[0]) in out.stdout, logs
    deadline = time.monotonic() + 90
    ends = []
    while time.monotonic() < deadline and not ends:
        ends = [r / "end-state.json" for r in runs(d).iterdir() if (r / "end-state.json").exists()]
        time.sleep(0.5)
    assert ends, logs[0].read_text()
    end = json.loads(ends[0].read_text())
    assert len(end["commits"]) == 3 and "stop condition met" in end["stop_reason"], end
    assert "overnight: stopped" in logs[0].read_text()
    state = json.loads((ends[0].parent / "state.json").read_text())
    assert "detach" not in state["args"], state["args"]
    # no caps named: a detached run, which nobody watches, gets the skill's 40 iterations and USD 25
    assert state["args"]["max_iterations"] == 40 and state["args"]["max_usd"] == 25, state["args"]
    assert "stops at 40 iterations or USD 25" in out.stdout, out.stdout
    # it ended with nobody there: one line waits for the next interactive session start to say it
    untold = runs(d) / "untold.jsonl"
    while time.monotonic() < deadline and not untold.exists():
        time.sleep(0.2)
    lines = untold.read_text().splitlines()
    assert len(lines) == 1, lines
    told = json.loads(lines[0])
    assert told["run"] == state["run_id"] and told["iterations"] == 3 and told["cost"] == 1.5, told
    assert told["branch"] == state["branch"] and told["pushed"] is False and "stop condition" in told["stop_reason"], told
    assert state["detached"] is True and isinstance(state["pid"], int), state
    assert clean(d), "the marker sits in the excluded runs folder"


def test_a_foreground_run_leaves_nothing_to_tell():
    d, fake = repo(["change", "done"])
    _, _, run_dir = run(d, fake)
    assert not (run_dir.parent / "untold.jsonl").exists()
    state = json.loads((run_dir / "state.json").read_text())
    assert state["detached"] is False and isinstance(state["pid"], int), state


def dry(d, fake, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "improve work.txt", "--agent-cmd", f"{sys.executable} {fake}",
                           "--dry-run", *args], cwd=d, capture_output=True, text=True, timeout=60, env=env(d))


def test_detach_without_caps_gets_the_defaults():
    d, fake = repo(["change"])
    out = dry(d, fake, "--detach")
    assert out.returncode == 0 and "caps: 40 iterations, USD 25.00" in out.stdout, out.stdout + out.stderr
    out = dry(d, fake, "--detach", "--max-usd", "5")
    assert "caps: USD 5.00;" in out.stdout and "40 iterations" not in out.stdout, out.stdout  # a cap named wins
    out = dry(d, fake, "--detach", "--no-caps")
    assert "caps: NONE" in out.stdout and "WARNING no budget" in out.stdout, out.stdout
    out = dry(d, fake)
    assert "caps: NONE" in out.stdout, out.stdout  # in the foreground the user watches it: no default


def test_protected_branch_is_refused():
    d, fake = repo(["change"])
    for branch in ("main", "master"):
        out = dry(d, fake, "--branch", branch)
        assert out.returncode != 0 and f"{branch} is a protected branch" in out.stderr, out.stdout + out.stderr
    subprocess.run(["git", "-C", str(d), "update-ref", "refs/remotes/origin/trunk", "HEAD"], check=True)
    subprocess.run(["git", "-C", str(d), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk"],
                   check=True)
    out = dry(d, fake, "--branch", "trunk")
    assert out.returncode != 0 and "trunk is a protected branch" in out.stderr, out.stdout + out.stderr  # the remote's default
    (d / ".git" / "info" / "exclude").write_text(".claude/\n")
    (d / ".claude").mkdir()
    (d / ".claude" / "kit.json").write_text(json.dumps({"guard": {"protectedBranches": ["release"]}}))
    out = dry(d, fake, "--branch", "release")
    assert out.returncode != 0 and "release is a protected branch" in out.stderr, out.stdout + out.stderr
    out = dry(d, fake, "--branch", "overnight/mine")
    assert out.returncode == 0 and "branch overnight/mine" in out.stdout, out.stdout + out.stderr
    # nothing was created or checked out by a refusal
    head = subprocess.run(["git", "-C", str(d), "branch", "--show-current"], capture_output=True, text=True).stdout
    assert head.strip() == "main", head


def test_push_ask_keeps_the_branch_local():
    d, fake = repo(["change", "done"])
    remote = Path(tempfile.mkdtemp()) / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "-C", str(d), "remote", "add", "origin", str(remote)], check=True)
    (d / ".git" / "info" / "exclude").write_text(".claude/\n")
    (d / ".claude").mkdir()
    (d / ".claude" / "kit.local.json").write_text(json.dumps({"lead": {"unattended": {"push": "ask"}}}))
    out, end, run_dir = run(d, fake, "--push")
    assert end["pushed"].startswith("skipped: push=ask in ") and "git push -u origin" in end["pushed"], end
    assert len(end["commits"]) == 2, end
    on_remote = subprocess.run(["git", "-C", str(remote), "branch", "--list"], capture_output=True, text=True).stdout
    assert not on_remote.strip(), on_remote
    assert "push: skipped: push=ask" in (run_dir / "notes.md").read_text() and "push=ask" in out, out


def test_detach_reports_a_run_that_stops_at_once():
    d, fake = repo(["change"])
    (d / "work.txt").write_text("uncommitted\n")
    out = subprocess.run([sys.executable, str(SCRIPT), "improve work.txt", "--agent-cmd", f"{sys.executable} {fake}",
                          "--detach"], cwd=d, capture_output=True, text=True, timeout=60, env=env(d))
    assert out.returncode != 0 and "working tree not clean" in out.stdout and "ended at once" in out.stdout, out.stdout


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
