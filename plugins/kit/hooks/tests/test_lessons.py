#!/usr/bin/env python3
"""Self-check for the kit's lesson ledger (lessons.py) and the hooks that feed and read it.
Synthetic repos and memories only, under a temporary CLAUDE_CONFIG_DIR.

Run: python3 plugins/kit/hooks/tests/test_lessons.py   (exit 0 = all good)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
TMP = Path(os.path.realpath(tempfile.mkdtemp()))
CONFIG = TMP / "config"
os.environ["CLAUDE_CONFIG_DIR"] = str(CONFIG)
os.environ["TMPDIR"] = str(TMP / "tmp")
(TMP / "tmp").mkdir()
sys.path.insert(0, str(SCRIPTS))
import lessons  # noqa: E402

GIT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def make_repo(name, origin=None, kit=True):
    repo = TMP / name
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), *GIT, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    if origin:
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", origin], check=True)
    if kit:
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "echo 'error: lint failed at 3' >&2; exit 1"}))
    return repo


def hook(script, payload, **env):
    out = subprocess.run([sys.executable, str(SCRIPTS / script)], input=json.dumps(payload), capture_output=True,
                         text=True, timeout=60, env={**os.environ, **env})
    return out


def rows(repo):
    return lessons.read_rows(lessons.file_of(lessons.repo(repo)["slug"]))


def test_ledger():
    repo = make_repo("ledger", "git@example.com:acme/ledger.git")
    slug = lessons.repo(repo)["slug"]
    assert lessons.observe(slug, "k1", "pitfall", "token: ghp_" + "a1B2" * 9, "user") is None, "secret refused"
    first = lessons.observe(slug, "k1", "pitfall", "Fixed in https://example.com/acme/ledger/commit/"
                            "4a24c23f0e1d2c3b4a5968778695a4b3c2d1e0f9; rerun", "gate")
    assert first and rows(repo)[0]["status"] == "candidate", "a commit SHA is not a secret; new = candidate"
    assert lessons.observe(slug, "k1", "pitfall", "same", "gate") == first
    assert rows(repo)[0]["status"] == "active" and rows(repo)[0]["seen"] == 2, "second sighting: active, counted"
    lessons.mark_delivered(slug, [first])
    lessons.observe(slug, "k1", "pitfall", "same", "verifier-fail")
    assert rows(repo)[0]["misses"] == 1, "a repeat after delivery is a miss"
    assert lessons.undo(slug, first) == [first] and rows(repo)[0]["seen"] == 2, "undo restores the last change"
    assert lessons.main(["retire", first, str(repo)]) == 0
    lessons.observe(slug, "k1", "pitfall", "same", "verifier-fail")
    assert rows(repo)[0]["status"] == "retired", "a lesson retired by hand stays retired"


def test_import():
    repo = make_repo("app", "https://example.com/acme/app.git")
    tree = TMP / "app-t1"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "t1", str(tree)], check=True)
    verifier = repo / ".claude" / "agent-memory" / "kit-verifier"
    verifier.mkdir(parents=True)
    (verifier / "MEMORY.md").write_text(
        "- [Docs claim](pitfall_docs-claim.md) — docs name codes from unmerged branches\n"
        "- [Kit normalizer](pitfall_kit-normalizer.md) — URL normalizer spoofed by #@\n"
        "- [Key](pitfall_key.md) — staging token: ghp_" + "a1B2" * 9 + "\n")
    (verifier / "pitfall_docs-claim.md").write_text("Seen 2026-10-19 and 2026-10-26.\n")
    (verifier / "pitfall_kit-normalizer.md").write_text("In claude-kit auto_mode_sync.py, 2026-10-26.\n")
    memory = CONFIG / "projects" / lessons.cc_slug(repo) / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("- [Lean tests](feedback_lean-tests.md) — one test per behaviour\n"
                                      "- [Deploy](project_deploy.md) — not a preference\n")
    before = {p: p.read_text() for p in list(verifier.iterdir()) + list(memory.iterdir())}

    first = lessons.harvest(tree)  # from a worktree: the main checkout's memories
    assert lessons.harvest(tree) == [], "a second run imports nothing"
    texts = {r["key"]: r for r in rows(repo)}
    assert set(texts) == {"docs-claim", "lean-tests"}, texts.keys()
    assert texts["docs-claim"]["last"] == "2026-10-26" and texts["lean-tests"]["kind"] == "preference"
    kit = lessons.read_rows(lessons.file_of(lessons.auto_mode_sync.slug_for(lessons.kit_origin())))
    assert [r["key"] for r in kit] == ["kit-normalizer"], "a pitfall about the kit goes to the kit's ledger"
    assert len(first) == 3
    assert all(p.read_text() == text for p, text in before.items()), "memory files are left as they are"
    assert not (verifier / ".kit-imported.json").exists(), "nothing written inside the repo"


def test_capture():
    repo = make_repo("cap", "https://example.com/acme/cap.git")
    command = "rm -rf /opt/other-project"
    for session in ("s1", "s1", "s2"):
        out = hook("guard.py", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo),
                                "session_id": session})
        assert out.returncode == 2, out.stderr
    guard = [r for r in rows(repo) if r["key"].startswith("guard-")]
    assert len(guard) == 1 and guard[0]["seen"] == 2 and guard[0]["status"] == "active", guard
    assert "/opt" not in guard[0]["text"], "the command shape, not the path"

    (repo / "x.txt").write_text("changed")
    for session in ("a", "b"):
        assert hook("stop_check.py", {"cwd": str(repo), "session_id": session}).returncode == 2
    gate = [r for r in rows(repo) if r["kind"] == "gate"]
    assert len(gate) == 1 and gate[0]["status"] == "active" and "lint failed" in gate[0]["text"], gate

    report = ("VERDICT: FAIL\nEVIDENCE: npm test passed\nPROBLEMS:\n1. src/a.ts:40 the retry label is wrong for "
              "abandoned scans. Details follow.\n2. docs/x.md names a code that exists only on a sibling branch\n"
              "NOT CHECKED: none\n")
    for agent in ("v1", "v2"):
        hook("subagent_stop.py", {"cwd": str(repo), "agent_type": "kit:verifier", "agent_id": agent,
                                  "last_assistant_message": report})
    found = [r for r in rows(repo) if r["key"].startswith("verifier-")]
    assert len(found) == 2 and all(r["seen"] == 2 for r in found), found
    assert [r["status"] for r in found] == ["active", "candidate"], "3 activations a day: guard, gate, one more"
    assert "Details follow" not in found[0]["text"], "the headline only"


def test_delivery():
    repo = make_repo("deliver", "https://example.com/acme/deliver.git")
    slug = lessons.repo(repo)["slug"]
    own = repo / ".claude" / "agent-memory" / "kit-verifier" / "pitfall_own.md"
    lessons.observe(slug, "old", "pitfall", "an old lesson " + "detail " * 20, "user", activate_at=1,
                    extra={"last": "2026-01-01"})
    for _ in range(2):
        lessons.observe(slug, "own", "pitfall", "from the verifier's own memory", "import", activate_at=1,
                        extra={"file": str(own)})
    for i in range(40):
        lessons.observe(slug, f"filler{i}", "pitfall", f"lesson {i} " + "detail " * 20, "import",
                        agents=("implementer", "verifier"), activate_at=1)
    for _ in range(3):
        lessons.observe(slug, "often", "pitfall", "the most repeated lesson", "user", activate_at=1)

    out = hook("subagent_start.py", {"cwd": str(repo), "agent_type": "kit:implementer"})
    text = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    import subagent_start
    assert len(text) <= subagent_start.MAX_CHARS and "the most repeated lesson [seen 3x]" in text, text
    assert text.index("the most repeated") < text.index("lesson 39") and "an old lesson" not in text
    assert re.search(r"\(\d+ more lessons not shown", text) and "pitfall_own.md" in text
    verifier = json.loads(hook("subagent_start.py", {"cwd": str(repo), "agent_type": "kit:verifier"}).stdout)
    assert "pitfall_own.md" not in verifier["hookSpecificOutput"]["additionalContext"], "not what it already has"
    assert any(r.get("delivered") for r in rows(repo)), "shown lessons are stamped delivered"

    lessons.observe(slug, "lead-only", "gate", "a gate lesson for the main session", "user", agents=("lead",),
                    activate_at=1)
    out = hook("session_start.py", {"cwd": str(repo), "source": "startup"}, KIT_HEADLESS="1")
    assert "a gate lesson for the main session" in out.stdout and "lesson 39" not in out.stdout, out.stdout


def main():
    for test in (test_ledger, test_import, test_capture, test_delivery):
        test()
    print("lessons: all checks passed")


if __name__ == "__main__":
    main()
