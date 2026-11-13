#!/usr/bin/env python3
"""Self-check for kitlib.py: the secret filter against paths and real keys, the -z rename
parsing of dirty_snapshot, the gate timeouts, the per-agent state key, the worktree-to-main
mapping and load_config's opt-in rule.

Run: python3 plugins/kit/hooks/tests/test_kitlib.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import kitlib  # noqa: E402

GIT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]

# A-code finding 2 and E-ux finding 3: paths, migrations and digests are not secrets
NOT_SECRETS = [
    "The verifier failed a branch here for: src/api/v2/handlers/user_profile.py returns 500 on empty body",
    "fix src/app/v2/routes/user_settings_handler.py",
    "tests/integration/test_payment_flow_v2.py flaky",
    "run migrations/0042_add_user_settings_table.py before verify",
    "evidence sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "supabase/migrations/20260101120000_profiles_rls.sql",
    "The update policy lets any authenticated user update any profile (supabase/migrations/0042_profiles_rls.sql:18)",
    "MyComponentHandlerFactoryBuilderV2Impl.ts drops the timezone",
    "see https://example.com/acme/app/commit/4a24c23f0e1d2c3b4a5968778695a4b3c2d1e0f9 for the fix",
]
SECRETS = [
    "aws key AKIAIOSFODNN7EXAMPLE in the env",
    "token ghp_" + "a1B2" * 9,
    "OPENAI key sk-" + "Zx9kQ2mP" * 4,
    # a 40-char random base64 string, with a slash in it, as a key dumped into a log line
    "signing key Qm9yaW5nU3RyaW5n/X8Kd3+mZ2L0pQ9sT4vW7yB2 was printed",
    "export DB_PASSWORD=Sup3rS3cret!",
]


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *GIT, *args], check=True, capture_output=True, text=True).stdout


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL " + str(msg))

    for text in NOT_SECRETS:
        check(not kitlib.looks_secret(text), f"a path is not a secret: {text!r}")
    for text in SECRETS:
        check(kitlib.looks_secret(text), f"a key stays a secret: {text!r}")

    check(kitlib.GATE_TIMEOUTS == {"check": 540, "verify": 1800}, kitlib.GATE_TIMEOUTS)
    check(kitlib.gate_timeout({}, "check") == 540 and kitlib.gate_timeout({}, "verify") == 1800, "defaults")
    check(kitlib.gate_timeout({"checkTimeout": 60, "verifyTimeout": "90"}, "check") == 60
          and kitlib.gate_timeout({"checkTimeout": 60, "verifyTimeout": "90"}, "verify") == 90, "kit.json overrides")
    check(kitlib.gate_timeout({"checkTimeout": "soon"}, "check") == 540, "a bad value falls back")

    check(kitlib.state_key({"session_id": "s1", "agent_id": "a7"}) == "s1.a7", "session and agent")
    check(kitlib.state_key({"session_id": "s1"}) == "s1.main", "the main session has no agent id")
    check(kitlib.state_key({}) == "nosession.main", "no session at all")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        (repo / "src").mkdir()
        (repo / "src" / "old_name.py").write_text("x\n")
        (repo / "keep.txt").write_text("k\n")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "init")

        # a rename in -z output is two entries: the new name, then the old one; neither is garbage
        sh(repo, "mv", "src/old_name.py", "src/new_name.py")
        (repo / "keep.txt").write_text("k2\n")
        snap = kitlib.dirty_snapshot(repo)
        check(set(snap) == {"src/new_name.py", "keep.txt"}, f"rename parsed: {sorted(snap)}")
        sh(repo, "commit", "-qam", "renamed")
        check(kitlib.dirty_snapshot(repo) == {}, "clean tree, empty snapshot")

        # a linked worktree maps to its main checkout
        tree = Path(tmp) / "wt"
        sh(repo, "worktree", "add", "-q", "-b", "feat/wt", str(tree))
        check(kitlib.main_checkout(tree) == repo.resolve() or kitlib.main_checkout(tree) == repo,
              f"worktree -> main: {kitlib.main_checkout(tree)}")
        check(kitlib.main_checkout(repo) in (repo, repo.resolve()), "the main checkout maps to itself")
        check(kitlib.main_checkout(Path(tmp)) is None, "outside git: None")

        # kit.json present is the opt-in, even empty; missing is None; not an object is an error
        check(kitlib.load_config(repo) == (None, None), "no kit.json: (None, None)")
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text("{}")
        check(kitlib.load_config(repo) == ({}, None), "an empty kit.json: ({}, None)")
        (repo / ".claude" / "kit.json").write_text(json.dumps(["check"]))
        config, err = kitlib.load_config(repo)
        check(config is None and err and "JSON object" in err, f"a list is an error: {err}")
        (repo / ".claude" / "kit.json").write_text("{broken")
        config, err = kitlib.load_config(repo)
        check(config is None and err and "cannot read" in err, f"broken JSON is an error: {err}")

        # kit.json is personal (kept out of git), so the worktree has none: the main checkout's applies
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "make lint"}))
        check(not (tree / ".claude" / "kit.json").exists(), "the worktree has no kit.json of its own")
        check(kitlib.load_config(tree) == ({"check": "make lint"}, None), f"worktree -> main's: {kitlib.load_config(tree)}")
        (tree / ".claude").mkdir(exist_ok=True)
        (tree / ".claude" / "kit.json").write_text(json.dumps({"check": "own"}))
        check(kitlib.load_config(tree) == ({"check": "own"}, None), "a worktree's own kit.json wins")
        (tree / ".claude" / "kit.json").unlink()
        (repo / ".claude" / "kit.json").unlink()
        check(kitlib.load_config(tree) == (None, None), "no kit.json in the worktree or the main checkout: off")
        check(kitlib.config_file(Path(tmp)) == Path(tmp) / ".claude" / "kit.json", "outside git: its own path")

    # hermetic git: inside a git hook GIT_DIR and friends point at the hook's repository; the helpers
    # still answer for the folder they were asked about
    with tempfile.TemporaryDirectory() as tmp:
        one, two = Path(tmp) / "one", Path(tmp) / "two"
        for repo, branch in ((one, "main"), (two, "other")):
            repo.mkdir()
            sh(repo, "init", "-q", "-b", branch)
            sh(repo, "commit", "-q", "--allow-empty", "-m", "init")
        check(set(kitlib.GIT_LOCATION_VARS) == {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                                                "GIT_PREFIX"}, kitlib.GIT_LOCATION_VARS)
        saved = {k: os.environ.get(k) for k in kitlib.GIT_LOCATION_VARS}
        os.environ.update(GIT_DIR=str(two / ".git"), GIT_WORK_TREE=str(two), GIT_INDEX_FILE=str(two / ".git" / "index"),
                          GIT_PREFIX="sub/")
        try:
            check(not set(kitlib.git_env()) & set(kitlib.GIT_LOCATION_VARS), "git_env drops the location variables")
            check(kitlib.git_env().get("PATH") == os.environ.get("PATH"), "git_env keeps the rest")
            branch = kitlib.git_out(one, "rev-parse", "--abbrev-ref", "HEAD")
            check(branch == "main", f"git_out answers for its folder, not GIT_DIR: {branch!r}")
            root = kitlib.git_root(one)
            check(root is not None and root.resolve() == one.resolve(), f"git_root answers for its folder: {root}")
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    # where the kit's working state lives: .kit for a fresh project, .claude until it is moved,
    # decided on the main checkout so a worktree finds the same board
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        sh(repo, "init", "-q", "-b", "main")
        sh(repo, "commit", "-q", "--allow-empty", "-m", "init")
        tree = Path(tmp) / "wt"
        sh(repo, "worktree", "add", "-q", "-b", "w", str(tree))
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text("{}")
        check(kitlib.state_dir_name(repo) == ".kit", "kit.json alone is not state: a fresh project uses .kit")
        check(kitlib.state_entry(tree, "lead") == repo / ".kit" / "lead", kitlib.state_entry(tree, "lead"))
        check(kitlib.state_entry(tree, "overnight") == tree / ".kit" / "overnight", "overnight is per checkout")
        check(kitlib.board_file(tree, {}) == repo / ".kit" / "lead" / "board.md", kitlib.board_file(tree, {}))
        legacy = {"lead": {"board": ".claude/lead/board.md"}}
        check(kitlib.board_file(repo, legacy) == repo / ".kit" / "lead" / "board.md", "the old default follows the move")
        check(kitlib.board_file(repo, {"lead": {"board": "docs/board.md"}}) == repo / "docs" / "board.md", "a custom board stays")
        (repo / ".claude" / "evidence").mkdir()
        check(kitlib.state_dir_name(repo) == ".claude", "legacy state keeps the project in .claude")
        check(kitlib.state_entry(tree, "lead") == repo / ".claude" / "lead", "a new entry joins the old layout")
        check(kitlib.board_file(repo, legacy) == repo / ".claude" / "lead" / "board.md", "the legacy board")
        kitlib.exclude_state(tree, "lead")
        lines = (repo / ".git" / "info" / "exclude").read_text().splitlines()
        check("/.claude/lead/" in lines, f"one line per entry: {lines}")
        (repo / ".kit" / "lead").mkdir(parents=True)
        check(kitlib.state_dir_name(repo) == ".kit", ".kit wins once it exists")
        check(kitlib.state_entry(repo, "lead") == repo / ".kit" / "lead", "lead moved")
        check(kitlib.state_entry(repo, "evidence") == repo / ".claude" / "evidence", "a half-moved entry is still found")
        kitlib.exclude_state(repo, "lead")
        lines = (repo / ".git" / "info" / "exclude").read_text().splitlines()
        check("/.kit/lead/" in lines and "/.kit/" not in lines, f"never a blanket .kit line: {lines}")

    print("kitlib: all checks passed" if not failed else f"kitlib: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
