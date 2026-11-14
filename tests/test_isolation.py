#!/usr/bin/env python3
"""Self-check for run_all's isolation: a test file that writes an opt-in record into the config dir
fails, so a new test cannot bring back the leak that once left 84 records in the user's account
folder. Standard library only.

Run: python3 tests/test_isolation.py   (exit 0 = all good)
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

if not os.environ.get("KIT_OPT_IN_DIR"):
    os.environ["KIT_OPT_IN_DIR"] = tempfile.mkdtemp(prefix="kit-opt-in-")
    atexit.register(shutil.rmtree, os.environ["KIT_OPT_IN_DIR"], True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_all  # noqa: E402

# what a hook does when nothing points it elsewhere (kitlib.opt_in_folder)
LEAKY = """import os, pathlib
folder = pathlib.Path(os.environ.get("KIT_OPT_IN_DIR") or pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / "kit-projects")
folder.mkdir(parents=True, exist_ok=True)
(folder / "abc.json").write_text('{"key": "/tmp/gone"}')
"""
# what a leak into the user's own folder looks like, whatever HOME says
TO_REAL = """import os, pathlib
(pathlib.Path(os.environ["REAL_RECORDS"]) / "def.json").write_text('{"key": "/tmp/gone"}')
"""
# a file that isolates itself, as every test file of the kit does
ISOLATED = """import os, tempfile
os.environ["KIT_OPT_IN_DIR"] = os.environ.get("KIT_OPT_IN_DIR") or tempfile.mkdtemp()
""" + LEAKY


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL:", msg)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        real = tmp / "real" / "kit-projects"
        real.mkdir(parents=True)
        (real / "old.json").write_text('{"key": "github.com/owner/repo"}')
        env = dict(os.environ, KIT_OPT_IN_DIR=str(tmp / "set-by-the-caller"), REAL_RECORDS=str(real))
        for name, body in (("leaky", LEAKY), ("to_real", TO_REAL), ("isolated", ISOLATED)):
            (tmp / f"test_{name}.py").write_text(body)

        out, leaked = run_all.run_isolated(tmp / "test_leaky.py", env, real)
        check(out.returncode == 0 and len(leaked) == 1 and leaked[0].name == "abc.json",
              f"a record under the fake config dir is caught, KIT_OPT_IN_DIR unset: {leaked} {out.stderr}")
        out, leaked = run_all.run_isolated(tmp / "test_to_real.py", env, real)
        check([p.name for p in leaked] == ["def.json"], f"a new record in the real folder is caught: {leaked}")
        (real / "def.json").unlink()
        out, leaked = run_all.run_isolated(tmp / "test_isolated.py", env, real)
        check(out.returncode == 0 and leaked == [], f"a file with its own folder passes: {leaked} {out.stderr}")
        check(not (tmp / "set-by-the-caller").exists(), "the caller's KIT_OPT_IN_DIR is not passed down")
        check(run_all.real_records_dir({"CLAUDE_CONFIG_DIR": "/c"}) == Path("/c/kit-projects")
              and run_all.real_records_dir({"HOME": "/h"}) == Path("/h/.claude/kit-projects"), "the real folder")

    print("isolation: all checks passed" if not failed else f"isolation: {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
