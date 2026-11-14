#!/usr/bin/env python3
"""Every self-check of the kit, in one command, before a pull request. No tokens, no network.

The repo has no CI (no Actions minutes), so this is the gate: run it on the branch you are about
to push, and put its last lines in the PR. It runs each standard-library test file and then the
mod's tests (`claude plugin test plugins/kit`: status line, watchdog, interim notices) when the
`claude` command is there; without it that step is reported as skipped, not as passed.

Each file runs as if alone (run_isolated): a file that writes an opt-in record into the config
dir fails, so a new test cannot bring back the leak that once left 84 records there.

Run: python3 tests/run_all.py        (exit 0 = all good)
     python3 tests/run_all.py -v     (print each test's own output)

To make it this repo's gate for the kit itself, put it in your own .claude/kit.json:
  {"verify": "python3 tests/run_all.py"}
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = ("tests/test_*.py", "plugins/*/hooks/tests/test_*.py", "plugins/*/skills/*/tests/test_*.py")


def records(folder):
    return {p for p in Path(folder).rglob("*") if p.is_file()} if Path(folder).is_dir() else set()


def real_records_dir(env):
    """Where a hook run by the user would keep its opt-in records (kitlib.opt_in_folder without
    the test override)."""
    config = env.get("CLAUDE_CONFIG_DIR") or str(Path(env.get("HOME") or Path.home()) / ".claude")
    return Path(config) / "kit-projects"


def run_isolated(path, env, real):
    """Run one test file the way a person runs it alone, with nothing set for it: KIT_OPT_IN_DIR
    and KIT_TEMP_ROOTS unset, HOME and CLAUDE_CONFIG_DIR at an empty temp folder. Running the test
    files alone once left 84 opt-in records in the real config dir; any record that appears under
    the fake config dir or the real one fails the file. Returns (process, leaked paths)."""
    # outside the system temp dir, as a person's HOME is: test_guard puts its repositories under
    # HOME to test the rules that differ for temp folders
    user_home = Path(env.get("HOME") or Path.home())
    home = Path(tempfile.mkdtemp(prefix=".kit-test-home-", dir=str(user_home)))
    env = {k: v for k, v in env.items() if k not in ("KIT_OPT_IN_DIR", "KIT_TEMP_ROOTS")}
    gitconfig = user_home / ".gitconfig"
    if "GIT_CONFIG_GLOBAL" not in env and gitconfig.is_file():
        env["GIT_CONFIG_GLOBAL"] = str(gitconfig)  # git's identity, not the Claude config dir
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"))
    before = records(real)
    try:
        out = subprocess.run([sys.executable, str(path)], cwd=str(ROOT), capture_output=True, text=True, env=env)
        leaked = sorted(records(home / ".claude" / "kit-projects")) + sorted(records(real) - before)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return out, leaked


def main(argv):
    verbose = "-v" in argv
    files = sorted(p for pattern in PATTERNS for p in ROOT.glob(pattern))
    failed = []
    real = real_records_dir(os.environ)
    for path in files:
        rel = path.relative_to(ROOT)
        out, leaked = run_isolated(path, os.environ, real)
        ok = out.returncode == 0 and not leaked
        print(f"{'ok  ' if ok else 'FAIL'} {rel}")
        if verbose or not ok:
            print((out.stdout + out.stderr).rstrip())
        if leaked:
            print(f"  wrote opt-in records outside a temp folder of its own: {', '.join(map(str, leaked))}")
        if not ok:
            failed.append(str(rel))
    mod = "skipped (no `claude` command here)"
    if shutil.which("claude"):
        out = subprocess.run(["claude", "plugin", "test", "plugins/kit"], cwd=str(ROOT), capture_output=True, text=True)
        tail = [line for line in (out.stdout + out.stderr).splitlines() if line.strip()][-3:]
        ok = out.returncode == 0
        mod = "ok" if ok else "FAIL"
        if verbose or not ok:
            print((out.stdout + out.stderr).rstrip())
        else:
            print("\n".join(tail))
        if not ok:
            failed.append("claude plugin test plugins/kit")
    print(f"{'ok  ' if mod == 'ok' else mod[:4] if mod == 'FAIL' else 'skip'} mod tests: {mod}")
    print(f"run_all: {len(files)} test files, {len(failed)} failed" + (": " + ", ".join(failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
