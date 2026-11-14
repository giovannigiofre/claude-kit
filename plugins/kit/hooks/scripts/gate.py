#!/usr/bin/env python3
"""Run a kit gate (`check` or `verify` from .claude/kit.json) and keep the result as evidence.

    python3 gate.py verify [--timeout N]      run it, print its output, exit with its code
    python3 gate.py check
    python3 gate.py status [verify|check]     does the last record cover the tree as it is now?

A gate that ran is a claim until something records what it ran on. The record,
<state>/evidence/<branch>/gate-<name>.json (<state> is `.kit`, or `.claude` in a project the kit
has not moved yet: kitlib.state_entry), holds the command, its exit code, how long it took, the hash of the tree it ran on (committed and uncommitted content, ignored files left out) and the
last lines of its output: the evidence a PR body and a reviewer can cite, and `status` tells
whether the last run still covers the tree as it is now. Threads, /kit:go and the verifier run
the gate through this script for that reason. Nothing blocks on it. Run from a linked worktree,
the gate runs on that worktree's tree and branch, and the record is written under the main
checkout's evidence folder, so it outlives the worktree.

The gate command gets KIT_CHANGED_FILES (the files this branch touched, shell-quoted) and
KIT_CHANGED_COUNT, so a `check` can be diff-aware. Its timeout is kit.json `checkTimeout` /
`verifyTimeout`, else kitlib.GATE_TIMEOUTS (540 s for check, 1800 s for verify). Standard
library only, Python 3.9+.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

TAIL_LINES = 25
NAMES = ("check", "verify")


def branch_name(root):
    name = kitlib.git_out(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not name or name == "HEAD":
        sha = kitlib.git_out(root, "rev-parse", "--short", "HEAD")
        return f"detached-{sha}" if sha else "no-branch"
    return name


def tree_hash(root, exclude=()):
    """The hash git would give the tree of the working directory: tracked content as it is on
    disk plus untracked files that are not ignored, through a scratch copy of the index so the
    real index is never touched. `exclude`: paths (relative to root) left out, such as the file
    that holds a PR body. None when git cannot tell (not a repository, or no git)."""
    root = Path(root)
    index = kitlib.git_out(root, "rev-parse", "--git-path", "index")
    if not index:
        return None
    index = Path(index) if Path(index).is_absolute() else root / index
    fd, scratch = tempfile.mkstemp(prefix="kit-index-")
    os.close(fd)
    try:
        env = {**os.environ, "GIT_INDEX_FILE": scratch}
        if index.is_file():
            shutil.copyfile(index, scratch)  # keeps the stat cache: files unchanged are not rehashed
        else:
            os.unlink(scratch)
            if kitlib.git_out(root, "rev-parse", "--verify", "--quiet", "HEAD"):
                subprocess.run(["git", "-C", str(root), "read-tree", "HEAD"], env=env, capture_output=True, timeout=60)
        subprocess.run(["git", "-C", str(root), "add", "-A", "--", "."], env=env, capture_output=True, timeout=600)
        if exclude:
            subprocess.run(["git", "-C", str(root), "rm", "-q", "--cached", "--ignore-unmatch", "--", *exclude],
                           env=env, capture_output=True, timeout=60)
        out = subprocess.run(["git", "-C", str(root), "write-tree"], env=env, capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or None
    except Exception:
        return None
    finally:
        try:
            os.unlink(scratch)
        except OSError:
            pass


def head_tree(root, ref="HEAD"):
    return kitlib.git_out(root, "rev-parse", "--verify", "--quiet", ref + "^{tree}") or None


def ensure_excluded(root):
    """Evidence stays out of git: its line (`/.kit/evidence/`, or `/.claude/evidence/` before the
    move) in .git/info/exclude unless the project ignores it already (the overnight runner does the
    same for its run files)."""
    kitlib.exclude_state(root, "evidence", per_checkout=False)


def evidence_root(root):
    """Where the records live: the main checkout, also for a linked worktree of it."""
    return kitlib.main_checkout(root) or Path(root)


def record_path(root, name, branch=None):
    # the main checkout's, also from a worktree: the record outlives the worktree (kitlib.PER_CHECKOUT_STATE)
    return kitlib.state_entry(root, "evidence", per_checkout=False) / (branch or branch_name(root)) / f"gate-{name}.json"


def read_record(root, name, branch=None):
    try:
        data = json.loads(record_path(root, name, branch).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def run(root, name, config, timeout=None):
    """Run the gate, print its output, write the record, return its exit code."""
    command = config.get(name)
    if not command:
        print(f"kit gate: .claude/kit.json has no `{name}` command", file=sys.stderr)
        return 3
    root = Path(root)
    ensure_excluded(root)
    tree_before = tree_hash(root)
    env = {"KIT_GATE": name, **kitlib.changed_env(root)}
    started = time.time()
    code, out = kitlib.run_shell(command, root, env, timeout=int(timeout or kitlib.gate_timeout(config, name)))
    duration = round(time.time() - started, 1)
    tree_after = tree_hash(root)
    tail = out.strip().splitlines()[-TAIL_LINES:]
    record = {
        "gate": name, "command": command, "ok": code == 0, "exit": code, "duration_s": duration,
        "branch": branch_name(root), "head": kitlib.git_out(root, "rev-parse", "HEAD") or None,
        "tree": tree_after, "tree_changed_by_gate": bool(tree_before and tree_after and tree_before != tree_after),
        "changed_files": int(env["KIT_CHANGED_COUNT"]), "ended": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tail": tail,
    }
    path = record_path(root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        where = path.relative_to(root) if evidence_root(root) == root else path  # a worktree: the main checkout's
    except OSError as exc:
        where = f"(not written: {exc})"
    sys.stdout.write(kitlib.tail(out, 200) + ("\n" if out.strip() else ""))
    verdict = "passed" if code == 0 else f"failed (exit {code})"
    note = " - the gate changed files in the tree (a formatter?): commit them" if record["tree_changed_by_gate"] else ""
    print(f"kit gate {name}: {verdict} in {duration}s on tree {(tree_after or '?')[:12]}; recorded in {where}{note}")
    return code


def status(root, name, branch=None, head_ref=None, exclude=()):
    """(ok, reason): whether the last record of `name` covers the tree the PR would carry.
    With `branch` naming another local branch, its committed tree is compared instead of the
    working tree (a PR opened for a branch that is not checked out). `exclude`: untracked files
    that are not part of the work (the PR body file) and do not make the tree dirty."""
    root = Path(root)
    rec = read_record(root, name, branch)
    path = record_path(root, name, branch)
    try:
        where = path.relative_to(evidence_root(root)).as_posix()
    except ValueError:
        where = str(path)
    if not rec:
        return False, f"no record of `{name}` for this branch ({where})"
    if not rec.get("ok"):
        return False, f"the last `{name}` run failed (exit {rec.get('exit')}, {rec.get('ended')}; {where})"
    if head_ref:
        current = head_tree(root, head_ref)
        what = f"the committed tree of {head_ref}"
    else:
        current = tree_hash(root, exclude)
        what = "the working tree"
        committed = head_tree(root)
        if current and committed and current != committed:
            dirty = [line for line in kitlib.git_out(root, "status", "--porcelain", "--untracked-files=all").splitlines()
                     if line[3:] not in exclude]
            names = ", ".join(line[3:] for line in dirty[:6]) + (" ..." if len(dirty) > 6 else "")
            return False, f"the working tree differs from HEAD (uncommitted or untracked: {names}): commit or ignore them"
    if not current:
        return False, "cannot hash the current tree (is this a git checkout?)"
    if rec.get("tree") != current:
        return False, f"`{name}` last ran on another tree ({str(rec.get('tree'))[:12]} at {rec.get('ended')}), not on {what} ({current[:12]})"
    return True, f"`{name}` passed on this exact tree ({current[:12]}, {rec.get('duration_s')}s, {rec.get('ended')})"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    root = kitlib.project_root({"cwd": os.getcwd()})
    config, err = kitlib.load_config(root)
    if err:
        print(err, file=sys.stderr)
        return 3
    if cmd == "status":
        name = rest[0] if rest and rest[0] in NAMES else "verify"
        ok, reason = status(root, name)
        print(("kit gate: " if ok else "kit gate: not ready: ") + reason)
        return 0 if ok else 1
    if cmd not in NAMES:
        print(f"kit gate: unknown gate `{cmd}` (check, verify, status)", file=sys.stderr)
        return 3
    if config is None:
        print("kit gate: this project has no .claude/kit.json (run /kit:init)", file=sys.stderr)
        return 3
    if not config.get(cmd) and kitlib.config_missing(root):  # the kit's state is here, its kit.json is not
        print(f"kit gate: there is no `{cmd}` gate: .claude/kit.json is missing in this project although it "
              "uses the kit. Tell the coordinator; the session start says how to restore the file.", file=sys.stderr)
        return 3
    timeout = None
    if "--timeout" in rest:
        try:
            timeout = int(rest[rest.index("--timeout") + 1])
        except (IndexError, ValueError):
            print("kit gate: --timeout needs a number of seconds", file=sys.stderr)
            return 3
    return run(root, cmd, config, timeout)


if __name__ == "__main__":
    sys.exit(main())
