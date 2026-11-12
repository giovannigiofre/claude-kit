#!/usr/bin/env python3
"""Self-check for permission.py: only the project's exact gate commands, the kit's own scripts, and
the plain git steps the owner saved as `allow` are allowed without a prompt.

The git commands are the shapes a coordinator and its threads really ran (a personal hook's log,
Nov 2026), with this test's own paths and branch names.

Run: python3 plugins/kit/hooks/tests/test_permission.py   (exit 0 = all good)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def ask(repo, command, env=None, agent=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo), "session_id": "s",
               "hook_event_name": "PermissionRequest"}
    if agent:
        payload.update({"agent_id": "a1", "agent_type": agent})
    out = subprocess.run([sys.executable, str(SCRIPTS / "permission.py")], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=60, env=env)
    if not out.stdout.strip():
        return "prompt"
    return json.loads(out.stdout)["hookSpecificOutput"]["decision"]["behavior"]


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def main():
    failed = 0

    def expect(repo, cases, env=None, agent=None, label=""):
        nonlocal failed
        for command, want in cases:
            got = ask(repo, command, env, agent)
            if got != want:
                failed += 1
                print(f"FAIL {label}{want} expected, got {got}: {command!r}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = os.path.realpath(tmp)
        repo = Path(tmp) / "repo"
        (repo / ".claude").mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": "make lint", "verify": "make test"}))
        gate = SCRIPTS / "gate.py"
        elsewhere = Path(tmp) / "gate.py"
        elsewhere.write_text("print('not the kit')\n")
        (Path(tmp) / "items.py").write_text("print('not the kit')\n")
        cases = [
            ("make lint", "allow"), ("make test", "allow"), ("  make test\n", "allow"),
            ("make lint && rm -rf x", "prompt"), ("make", "prompt"), ("make test; echo", "prompt"),
            (f"python3 {gate} verify", "allow"), (f'python3 "{gate}" status', "allow"),
            (f"python3 {gate} verify > out.txt", "prompt"), (f"python3 {elsewhere} verify", "prompt"),
            (f'python3 "{SCRIPTS / "items.py"}" list --status queued', "allow"),
            (f"python3 {SCRIPTS / 'items.py'} new \"Login page\" --brief - --from lead", "allow"),
            (f"python3 {SCRIPTS / 'proposals.py'} take readme-install", "allow"),
            (f"python3 {Path(tmp) / 'items.py'} list", "prompt"),  # a script of that name elsewhere is not the kit's
            (f"python3 {SCRIPTS / 'machine_setup.py'} --apply", "prompt"), ("rm -rf /", "prompt"),
        ]
        expect(repo, cases)
        (repo / ".claude" / "kit.json").unlink()
        expect(repo, [("make lint", "prompt")], label="without kit.json nothing is allowed: ")

        # ---- the unattended git steps, in a repo with no kit.json (the saved answer is the opt-in)
        home = Path(tmp) / "home"
        (home / ".claude").mkdir(parents=True)
        env = {**os.environ, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude")}
        env.pop("CLAUDE_PROJECT_DIR", None)
        site = Path(tmp) / "site"
        (site / ".claude" / "worktrees").mkdir(parents=True)
        git(site, "init", "-q", "-b", "main")
        git(site, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "one")
        git(site, "remote", "add", "origin", "git@github.com:example-org/shop.git")
        git(site, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(site, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        git(site, "checkout", "-q", "-b", "docs/diary-1111")
        wt = site / ".claude" / "worktrees" / "records"
        git(site, "worktree", "add", "-q", "-b", "docs/records-1112", str(wt))
        local = site / ".claude" / "kit.local.json"

        def prefs(**steps):
            local.write_text(json.dumps({"lead": {"unattended": {k: steps.get(k, "ask") for k in ("push", "rebase", "merge")}}}))

        approved = [
            "git push -u origin docs/diary-1111",
            "git push origin docs/diary-1111",
            "git push --set-upstream origin docs/diary-1111",
            f"git -C {wt} push -u origin docs/records-1112",
            "gh pr merge 209 --squash --delete-branch",
            "gh pr merge 211 --repo example-org/shop --squash --delete-branch",
            "gh pr merge 212 -R example-org/shop --merge -d",
            "git push -u origin docs/finance-open-points 2>&1 | tail -6",
            "gh pr merge 236 --squash --delete-branch 2>&1 | tail -3",
            "GIT_EDITOR=true git rebase --continue 2>&1 | tail -1",
            "git rebase --abort",
            "git rebase origin/main",
            'git push -u origin docs/diary-1111c 2>&1 | grep -E "docs-only|\\->" | tail -2',
            f"cd {wt} && git push -u origin docs/records-1112",
            "gh pr merge 245 --squash 2>&1 | tail -2; gh pr view 245 --json state -q .state",
            f"git push -u origin docs/records-1112 > {site}/.claude/worktrees/records-push.log 2>&1; echo exit=$?",
            f"git push -u origin docs/x > {tmp}/push.log 2>&1; echo exit=$?; tail -5 {tmp}/push.log",
        ]
        refused = [
            # compound commands with other effects (logged shapes)
            'git commit -q -m "notes" && git push -u origin docs/x',
            "git add notes.md && GIT_EDITOR=true git rebase --continue 2>&1 | tail -1; git diff --name-only --diff-filter=U",
            "gh pr comment 245 --body done",
            # force, the default branch, and other pushes that do more
            "git push", "git push origin", "git push --force-with-lease origin docs/x", "git push -f origin docs/x",
            "git push --force origin docs/x", "git push origin +docs/x", "git push origin docs/x:main",
            "git push origin main", "git push -u origin master", "git push origin HEAD", "git push --no-verify origin docs/x",
            "git push --delete origin docs/x", "git push origin --tags", "git push --mirror origin",
            "git push --all origin", "git push upstream docs/x", "EDITOR=x git push origin docs/x",
            # around the step
            "git push origin docs/x && rm -rf build", "git push origin docs/x; git reset --hard",
            "git push origin docs/x | sh", "git push origin docs/x > ~/.zshrc", "git push origin docs/x > notes.md",
            "git push origin docs/x > .git/push.log", "git push origin docs/x > .claude/settings.local.json",
            "git push origin docs/x > .claude/push.log", "git push origin docs/x &", "git push origin docs/x || true",
            "git push origin docs/x\ngit push origin main", "git push origin $(git branch --show-current)",
            "git push origin `git branch --show-current`", "(git push origin docs/x)", "git push origin docs/x 2>&1 | tee x.log",
            "git push origin docs/x | tail -f", "git push origin docs/x; tail -f push.log", "cd $WT && git push origin docs/x",
            "git push origin docs/x 2>&1 | grep -E x notes.md", "git push origin docs/x >> $LOG",
            # merges and rebases that do more
            "gh pr merge 12", "gh pr merge 12 --admin --squash", "gh pr merge 12 --auto --squash",
            "gh pr merge 12 --squash --body x", "gh pr merge 12 --squash --merge", "gh pr merge --squash --delete-branch",
            "gh pr merge 12 --squash --repo someone/else", "git merge origin/main",
            "git rebase main", "git rebase -i origin/main", "git rebase origin/other", "git rebase --skip",
            "GIT_EDITOR=vim git rebase --continue", "git rebase --onto origin/main docs/x",
        ]
        expect(site, [(c, "prompt") for c in approved], env, label="no saved answer: ")
        prefs(push="allow", rebase="allow", merge="allow")
        expect(site, [(c, "allow") for c in approved], env, label="all allowed: ")
        expect(site, [(c, "prompt") for c in refused], env, label="all allowed: ")
        prefs(push="allow", rebase="ask", merge="allow")
        expect(site, [("git push -u origin docs/x", "allow"), ("git rebase origin/main", "prompt"),
                      ("GIT_EDITOR=true git rebase --continue", "prompt"), ("gh pr merge 1 --squash", "allow")], env,
               label="rebase ask: ")
        prefs(push="allow", rebase="allow", merge="allow")
        # a worktree reads the main checkout's answer; on the default branch a rebase onto it is refused
        expect(wt, [("git push -u origin docs/records-1112", "allow"), ("git rebase origin/main", "allow")], env, label="worktree: ")
        git(site, "checkout", "-q", "main")
        expect(site, [("git rebase origin/main", "prompt"), ("git push origin docs/diary-1111", "allow")], env,
               label="on main: ")
        git(site, "checkout", "-q", "docs/diary-1111")
        # threads: a kit:implementer pushes and rebases, never merges; other subagents get nothing
        expect(wt, [("git push -u origin docs/records-1112", "allow"), ("GIT_EDITOR=true git rebase --continue", "allow"),
                    ("gh pr merge 209 --squash --delete-branch", "prompt")], env, agent="kit:implementer", label="thread: ")
        expect(wt, [("git push -u origin docs/records-1112", "prompt")], env, agent="kit:verifier", label="verifier: ")
        expect(wt, [("git push -u origin docs/records-1112", "prompt")], env, agent="general-purpose", label="other agent: ")
        # the kit guard's rules win: a project askCommands, a protected branch of its own
        (site / ".claude" / "kit.json").write_text(json.dumps({"guard": {"askCommands": [{"pattern": "docs/secret"}],
                                                                         "protectedBranches": ["release"]}}))
        expect(site, [("git push origin docs/secret", "prompt"), ("git push origin release", "prompt"),
                      ("git push origin docs/diary-1111", "allow")], env, label="guard: ")
        (site / ".claude" / "kit.json").unlink()
        # a broken or missing answer is ask
        local.write_text("{ broken")
        expect(site, [("git push origin docs/diary-1111", "prompt")], env, label="broken answer: ")
        local.unlink()
        expect(site, [("gh pr merge 209 --squash", "prompt")], env, label="no answer: ")
        # outside git: nothing
        expect(Path(tmp), [("git push origin docs/x", "prompt")], env, label="outside git: ")
    print("permission: all checks passed" if not failed else f"permission: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
