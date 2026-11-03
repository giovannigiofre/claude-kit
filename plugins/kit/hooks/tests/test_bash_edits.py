#!/usr/bin/env python3
"""Self-check for bash_edits.py (with the guard's snapshot): an edit made through a shell
command gets protect and onEdit like one made with the Edit tool.

Run: python3 plugins/kit/hooks/tests/test_bash_edits.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def hook(name, repo, command, session, env):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo), "session_id": session,
               "tool_response": {"stdout": "", "stderr": ""}}
    out = subprocess.run([sys.executable, str(SCRIPTS / name)], input=json.dumps(payload), capture_output=True,
                         text=True, timeout=60, env=env)
    return out.returncode, out.stderr


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL " + msg)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        (home / ".claude").mkdir(parents=True)
        (home / "tmp").mkdir()
        env = dict(os.environ, HOME=str(home), TMPDIR=str(home / "tmp"), CLAUDE_CONFIG_DIR=str(home / ".claude"))
        repo = Path(tmp) / "repo"
        (repo / "data" / "raw").mkdir(parents=True)
        (repo / "src").mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "data" / "raw" / "a.csv").write_text("1\n")
        (repo / "src" / "app.py").write_text("x = 1\n")
        (repo / ".claude").mkdir()
        (repo / ".claude" / "kit.json").write_text(json.dumps({
            "protect": [{"glob": "data/raw/**", "mode": "no-overwrite", "reason": "raw files are immutable"},
                        {"glob": "vendor/**", "mode": "read-only", "reason": "vendored"}],
            "onEdit": [{"glob": "**/*.py", "run": "echo \"$REL\" >> .edited; grep -q TODO \"$FILE\" && exit 1 || exit 0"}],
        }))
        (repo / ".gitignore").write_text(".edited\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)

        def run(command, session="s1"):
            """The guard before (its snapshot), the command itself, bash_edits after."""
            hook("guard.py", repo, command, session, env)
            subprocess.run(command, shell=True, cwd=str(repo), check=False)
            return hook("bash_edits.py", repo, command, session, env)

        code, err = run("echo hi")
        check(code == 0 and not err, f"a command that changes nothing is silent: {err}")

        code, err = run("sed -i.bak 's/x = 1/x = 2/' src/app.py && rm src/app.py.bak")  # GNU and BSD sed
        check(code == 0, f"a clean edit through sed passes: {err}")
        check((repo / ".edited").read_text() == "src/app.py\n", "onEdit ran for the edited file")

        code, err = run("printf 'y = 1  # TODO\\n' >> src/app.py")
        check(code == 2 and "onEdit checks failed for src/app.py" in err, f"a failing onEdit reports: {err}")

        code, err = run("echo 2 >> data/raw/a.csv")
        check(code == 2 and "kit protect: data/raw/a.csv" in err and "no-overwrite" in err, f"protected overwrite: {err}")
        code, err = run("echo 3 > data/raw/new.csv")
        check(code == 0, f"a new file under no-overwrite is fine: {err}")
        (repo / "vendor").mkdir()
        code, err = run("echo lib > vendor/lib.js")
        check(code == 2 and "read-only" in err, f"a new file under read-only is reported: {err}")

        # a file edited by the Edit tool between two commands is not blamed on the next command
        hook("guard.py", repo, "true", "s2", env)
        (repo / "src" / "app.py").write_text("x = 3\n")
        code, err = hook("bash_edits.py", repo, "true", "s2", env)
        check(code == 0 or "src/app.py" in err, "an edit between snapshot and command is attributed at most once")
        code, err = hook("bash_edits.py", repo, "true", "s2", env)
        check(code == 0 and not err, "without a fresh snapshot the hook stays silent")

        # no kit.json: silent
        (repo / ".claude" / "kit.json").unlink()
        code, err = run("echo 9 >> data/raw/a.csv")
        check(code == 0 and not err, "a project without kit.json is left alone")

    print("bash_edits: all checks passed" if not failed else f"bash_edits: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
