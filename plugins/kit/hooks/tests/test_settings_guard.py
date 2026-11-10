#!/usr/bin/env python3
"""Self-check for settings_guard.py: changing a Claude Code settings file always asks (never
allows), is refused from a subagent, and other files and plain reads pass untouched.

Run: python3 plugins/kit/hooks/tests/test_settings_guard.py   (exit 0 = all good)
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
LABEL = "Sovrascrittura dei settings di Claude Code:"


def shown(path, home):
    text = str(path)
    return "~" + text[len(str(home)):] if text.startswith(str(home) + os.sep) else text


def hook(tool, tool_input, cwd, env, agent_id=None, raw=None, agent_type=None, script=None):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd), "session_id": "s",
               "hook_event_name": "PreToolUse", "permission_mode": "acceptEdits"}
    if agent_id:
        payload["agent_id"] = agent_id
    if agent_type:
        payload["agent_type"] = agent_type
    out = subprocess.run([sys.executable, str(script or SCRIPTS / "settings_guard.py")],
                         input=raw if raw is not None else json.dumps(payload),
                         capture_output=True, text=True, timeout=30, env=env)
    if out.returncode != 0:
        return "error", out.stderr
    if not out.stdout.strip():
        return "pass", ""
    spec = json.loads(out.stdout)["hookSpecificOutput"]
    return spec["permissionDecision"], spec["permissionDecisionReason"]


def main():
    failed = 0

    def check(cond, msg):
        nonlocal failed
        if not cond:
            failed += 1
            print("FAIL " + str(msg))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        home = tmp / "home"
        (home / ".claude").mkdir(parents=True)
        config = tmp / "config"
        config.mkdir()
        env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(config))
        repo = tmp / "repo"
        (repo / ".claude").mkdir(parents=True)
        (repo / ".claude" / "kit.json").write_text("{}")  # the project opted in to the kit
        shared = repo / ".claude" / "settings.json"
        shared.write_text(json.dumps({"permissions": {"ask": ["Bash(git push*)"]}}, indent=2) + "\n")
        local = repo / ".claude" / "settings.local.json"
        # a git repo with a kit thread's worktree below .claude/worktrees/: kit.json is personal (not
        # committed), so the worktree has none and the guard runs on the main checkout's
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-C", str(repo)]
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base"], check=True)
        wt = repo / ".claude" / "worktrees" / "x"
        subprocess.run(git + ["worktree", "add", "-q", "-b", "feat/x", str(wt)], check=True)
        check(not (wt / ".claude" / "kit.json").exists(), "the worktree has no kit.json of its own")
        user = home / ".claude" / "settings.json"
        files = [shared, local, user, config / "settings.json", home / ".claude" / "settings.local.json",
                 repo / ".claude" / "worktrees" / "a1" / ".claude" / "settings.json"]
        edit = {"old_string": '"Bash(git push*)"', "new_string": ""}
        for f in files:
            for tool, inp in [("Edit", {"file_path": str(f), **edit}),
                              ("MultiEdit", {"file_path": str(f), "edits": [edit, edit]}),
                              ("Write", {"file_path": str(f), "content": "{}\n"}),
                              ("NotebookEdit", {"notebook_path": str(f), "new_source": "x"})]:
                decision, reason = hook(tool, inp, repo, env)
                check(decision == "ask" and reason.startswith(LABEL) and shown(f, home) in reason and len(reason) <= 220,
                      f"{tool} {f}: asks, labelled, names the file, short enough for the prompt: {decision} {reason}")
        decision, reason = hook("Edit", {"file_path": ".claude/settings.json", **edit}, repo, env)
        check(decision == "ask" and "«\"Bash(git push*)\"»" in reason and str(shared) in reason,
              f"a relative path resolves, and the reason says what changes: {reason}")
        long_edit = {"old_string": "x" * 500, "new_string": "y" * 500}
        decision, reason = hook("Edit", {"file_path": str(shared), **long_edit}, repo, env)
        check(decision == "ask" and len(reason) <= 220 and reason.endswith("Approva solo se l'hai chiesta tu."),
              f"a long change is cut to fit the prompt: {len(reason)} {reason}")
        decision, reason = hook("Write", {"file_path": str(shared), "content": "{}\n"}, repo, env)
        check(decision == "ask" and "riscrive l'intero file (+1/-7 righe)" in reason, f"a rewrite counts the lines: {reason}")
        decision, reason = hook("Edit", {"file_path": "~/.claude/settings.json", **edit}, repo, env)
        check(decision == "ask" and ": sostituisce" in reason and "~/.claude/settings.json:" in reason, f"~ expands, shown as ~: {reason}")

        # from a subagent (a background thread) it is refused outright
        for tool, inp in [("Edit", {"file_path": str(local), **edit}),
                          ("Bash", {"command": f"echo '{{}}' > {local}"})]:
            decision, reason = hook(tool, inp, repo, env, agent_id="a123")
            check(decision == "deny" and reason.startswith(LABEL) and "subagent" in reason,
                  f"{tool} from a subagent is denied: {decision} {reason}")

        # Claude Code's statusline-setup runs in the foreground (its prompt is seen): ask, with the same reason
        decision, reason = hook("Edit", {"file_path": str(user), **edit}, repo, env, agent_id="a9", agent_type="statusline-setup")
        check(decision == "ask" and reason.startswith(LABEL) and "subagent" not in reason,
              f"statusline-setup asks: {decision} {reason}")
        for agent_type in ("kit:implementer", "kit:verifier", "general-purpose"):
            decision, _ = hook("Edit", {"file_path": str(user), **edit}, repo, env, agent_id="a9", agent_type=agent_type)
            check(decision == "deny", f"{agent_type} is refused: {decision}")

        # a project without kit.json is not the kit's business, like every other kit hook
        plain = tmp / "plain"
        (plain / ".claude").mkdir(parents=True)
        for tool, inp in [("Edit", {"file_path": str(plain / ".claude" / "settings.json"), **edit}),
                          ("Bash", {"command": "echo {} > .claude/settings.json"})]:
            decision, reason = hook(tool, inp, plain, env)
            check(decision == "pass", f"no kit.json, no decision: {tool} {decision} {reason}")

        # without kitlib nothing can be judged: ask
        lone = tmp / "lone"
        lone.mkdir()
        (lone / "settings_guard.py").write_text((SCRIPTS / "settings_guard.py").read_text())
        decision, reason = hook("Edit", {"file_path": str(shared), **edit}, repo, env, script=lone / "settings_guard.py")
        check(decision == "ask" and "ImportError" in reason, f"kitlib missing asks: {decision} {reason}")

        # shell commands that change one ask; plain reads and other files pass
        asks = [f"echo '{{}}' > {shared}", f"sed -i '' 's/ask/allow/' {shared}", f"cp /tmp/x.json {local}",
                "jq '.permissions.ask=[]' .claude/settings.json > /tmp/s && mv /tmp/s .claude/settings.json",
                f"python3 -c \"open('{user}','w').write('{{}}')\"", "cd .claude && rm settings.local.json",
                "tee ~/.claude/settings.json < /tmp/x", "git checkout -- .claude/settings.json",
                f"cat {shared} | python3 -c 'import sys'", "echo {} > $CLAUDE_CONFIG_DIR/settings.json",
                "rm /Library/Application\\ Support/ClaudeCode/managed-settings.json",
                # the folder itself, with no file named
                "git checkout -- .claude/", "git restore .claude", "git checkout main -- .claude", "cp -r /tmp/x .claude/",
                "rsync -a /tmp/x/ ~/.claude/", "cp /tmp/x.json ~/.claude/*.json", "mv /tmp/s .claude/settings*",
                # quoting, escaping and case inside the name
                "echo {} > .claude/'settings'.json", "rm .claude/settings\\.json", "echo {} > .claude/\"settings.local\".json",
                "echo x > .claude/SETTINGS.json", "echo x > ~/.CLAUDE/Settings.Json",
                # a bare name in a Claude folder, and readers that can write
                "find .claude -name settings.json -delete", "cd ~/.claude && sed -i '' s/a/b/ settings.json",
                "sort -o .claude/settings.json /tmp/x", "cat /tmp/x | tee .claude/settings.json",
                # a folder write behind a shell, eval, a subshell, a block, a loop, a wrapper; an unknown writer
                "bash -c 'cp /tmp/x .claude/'", "sh -c \"rsync -a /tmp/x/ ~/.claude/\"", "eval 'cp -r /tmp/x .claude/'",
                "( cp -r /tmp/x .claude/ )", "{ cp -r /tmp/x .claude/; }", "if true; then cp -r /tmp/x .claude/; fi",
                "for f in a; do cp $f ~/.claude/; done", "nice cp -r /tmp/x .claude/", "cpio -pd .claude/ < list",
                "(cp -r /tmp/x .claude/)", "timeout 10 cp -r /tmp/x .claude/", "ls .claude | xargs rm",
                "cd .claude && rm -rf *", "node scripts/x.js --out .claude", "bash script.sh .claude/",
                # code run by perl -e / ruby -e, a case clause, the macOS managed settings folder
                "perl -MFile::Copy -e 'copy(\"/tmp/x\", \".claude/\")'", "ruby -e 'FileUtils.cp(\"/tmp/x\", \".claude/\")'",
                "case x in a) cp /tmp/x .claude/;; esac", "rm -rf \"/Library/Application Support/ClaudeCode\"",
                "cp /tmp/x /Library/Application\\ Support/ClaudeCode/"]
        for cwd in (repo, wt):  # the main checkout, and a thread's worktree below .claude/worktrees/
            for command in asks:
                decision, reason = hook("Bash", {"command": command}, cwd, env)
                check(decision == "ask" and reason.startswith(LABEL) and "comando" in reason and len(reason) <= 220,
                      f"asks in {cwd.name}: {command}: {decision} {reason}")
        decision, reason = hook("Bash", {"command": "cp /tmp/x settings.json"}, repo / ".claude", env)
        check(decision == "ask", f"a bare name with the cwd a .claude folder asks: {decision} {reason}")
        decision, _ = hook("Monitor", {"command": f"echo x >> {local}"}, repo, env)
        check(decision == "ask", f"Monitor's command too: {decision}")
        # a long unbroken word (a 20 KB base64 blob) is judged at once, well inside the hook's 10 s timeout
        blob = base64.b64encode(os.urandom(15000)).decode()
        for command, want in [(f"echo {blob} | base64 -d > /tmp/x.png", "pass"),
                              (f"echo {blob} | base64 -d > .claude/settings.json", "ask"),
                              (f"echo {blob} | base64 -d > ~/.claude/x", "ask")]:
            start = time.monotonic()
            decision, reason = hook("Bash", {"command": command}, wt, env)
            took = time.monotonic() - start
            check(decision == want and took < 1.5, f"a 20 KB word: {want} in {took:.2f}s: {decision} {reason[:80]}")
        decision, _ = hook("Bash", {"command": "echo " + "settings" * 1000 + " > /tmp/x"}, wt, env)
        check(decision == "pass", f"an 8 KB word below the cap is read: {decision}")
        passes = [f"cat {shared}", "git diff .claude/settings.json", "jq .permissions .claude/settings.json 2>/dev/null",
                  "grep -n ask .claude/settings.local.json", "echo x > .vscode/settings.json", "npm test",
                  "git push origin feature", f"cat {repo}/.vscode/settings.json", "ls -la .claude/",
                  "mkdir -p .claude/evidence/x", "git add .claude/lead/board.md", "cp report.txt .claude/evidence/b/",
                  # a bare settings name outside a Claude folder, the folder named by a non-writer, pipes of readers
                  "cp config/settings.example.json settings.json", "grep -rn foo .claude/ | head",
                  "ls .claude/*.json | wc -l", "git add .claude/",
                  "cat .claude/settings.json | jq .permissions", "git -C . diff .claude/settings.json | head -5",
                  # a reader behind a shell or a wrapper, a loop that only reads, a writer in another part
                  "bash -c 'ls .claude/'", "timeout 10 ls .claude/", "for f in .claude/*; do echo $f; done",
                  "ls .claude/ && npm test", "git status .claude/ && git commit -m x",
                  "ls \"/Library/Application Support/ClaudeCode\""]
        for cwd in (repo, wt):
            for command in passes:
                decision, reason = hook("Bash", {"command": command}, cwd, env)
                check(decision == "pass", f"passes in {cwd.name}: {command}: {decision} {reason}")
        decision, reason = hook("Edit", {"file_path": str(wt / ".claude" / "settings.local.json"), **edit}, wt, env)
        check(decision == "ask", f"the worktree's own settings ask, with the main checkout's kit.json: {decision} {reason}")
        decision, _ = hook("Edit", {"file_path": str(wt / ".claude" / "settings.local.json"), **edit}, wt, env,
                           agent_id="a1", agent_type="kit:implementer")
        check(decision == "deny", f"and a thread there is refused: {decision}")
        decision, _ = hook("Edit", {"file_path": str(repo / ".claude" / "Settings.Local.json"), **edit}, repo, env)
        check(decision == "ask", f"a settings name in another case asks (macOS ignores case): {decision}")
        for path in [repo / "src" / "settings.json", repo / ".vscode" / "settings.json", repo / ".claude" / "kit.json",
                     repo / ".claude" / "kit.local.json", repo / "README.md"]:
            decision, reason = hook("Edit", {"file_path": str(path), **edit}, repo, env)
            check(decision == "pass", f"another file passes: {path}: {decision} {reason}")
        decision, _ = hook("Read", {"file_path": str(shared)}, repo, env)
        check(decision == "pass", "a Read is not this hook's business")

        # any error asks; nothing ever comes back as allow
        decision, reason = hook("Edit", {}, repo, env, raw="{not json")
        check(decision == "ask" and reason.startswith(LABEL), f"a broken input asks: {decision} {reason}")
        decision, reason = hook("Edit", {}, repo, env, raw='{"tool_name": "Edit", "tool_input": {"file_path": 5}}')
        check(decision in ("ask", "pass") and decision != "allow", f"a strange input never allows: {decision}")
        source = (SCRIPTS / "settings_guard.py").read_text()
        check('"allow"' not in source.split('"""', 2)[2], "the hook has no allow answer at all")

        # permission.py never allows a command that changes a settings file, even the kit's own script
        (repo / ".claude" / "kit.json").write_text(json.dumps({"check": f"cp /tmp/x {local}"}))
        sys.path.insert(0, str(SCRIPTS))
        import permission  # noqa: E402
        check(not permission.allowed(f"cp /tmp/x {local}", {"check": f"cp /tmp/x {local}"}, str(repo)),
              "permission.py does not allow a gate command that writes settings")
        check(permission.allowed("make lint", {"check": "make lint"}, str(repo)), "permission.py still allows the gate")

    print("settings_guard: all checks passed" if not failed else f"settings_guard: {failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
