#!/usr/bin/env python3
"""Self-check for the kit's lesson ledger (lessons.py) and the hooks that feed and read it.
Synthetic repos and memories only, under a temporary CLAUDE_CONFIG_DIR.

Run: python3 plugins/kit/hooks/tests/test_lessons.py   (exit 0 = all good)
"""

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
TMP = Path(os.path.realpath(tempfile.mkdtemp()))
CONFIG = TMP / "config"
os.environ["CLAUDE_CONFIG_DIR"] = str(CONFIG)
os.environ["KIT_LEARN_MODEL"] = "0"  # no test reaches a real model, the detached distiller included
os.environ["TMPDIR"] = str(TMP / "tmp")
os.environ.pop("CLAUDE_CODE_SESSION_ATTENDED", None)  # an attended cloud session would make every entrypoint interactive
(TMP / "tmp").mkdir()
sys.path.insert(0, str(SCRIPTS))
import distill  # noqa: E402
import kitlib  # noqa: E402
import lessons  # noqa: E402
import subagent_stop  # noqa: E402

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
    for leak in ("PGPASSWORD=hunter2hunter2", "MY_API_KEY=abc123def456ghi", "Authorization: Bearer abcdef123456",
                 "DB_PASS=Sup3rS3cret!", "client_secret=0a1b2c3d4e5f"):
        assert kitlib.looks_secret(f"run it with {leak} set"), leak
    assert not kitlib.looks_secret("first_pass: always run lint, max_token=4096000"), "a setting is not a secret"
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
    slug = lessons.repo(repo)["slug"]
    denials = [e for e in lessons.read_rows(lessons.file_of(slug, ".events")) if e["key"].startswith("guard-")]
    assert len(denials) == 2 and {e["once"] for e in denials} == {"s1", "s2"}, denials
    assert not any(r["key"].startswith("guard-") for r in rows(repo)), \
        "a denial is an event for the statistics, once per session, never a lesson: the hook enforces the rule"
    assert "/opt" not in json.dumps(denials), "the command shape, not the path"
    for _ in range(2):  # an automatic lesson that uses up one of the day's activations
        lessons.observe(slug, "earlier", "pitfall", "an earlier automatic lesson", "gate")

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
    assert [r["status"] for r in found] == ["active", "candidate"], "3 activations a day: earlier, gate, one more"
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


def test_fail_then_pass():
    repo = make_repo("fixed", "https://example.com/acme/fixed.git")

    def verifier(agent, branch, verdict, *problems):
        """A verifier run shaped like the real transcript: the report goes back through SubagentHandback,
        its PROBLEMS heading has no colon, and the final text is small talk. The same agent again is
        one resumed with SendMessage: its transcript grows."""
        listed = "".join(f"{i}. **{p}** (src/app.ts:{i}0)\n   - where it shows\n" for i, p in enumerate(problems, 1))
        lines = [{"type": "user", "message": {"role": "user", "content":
                  f"Compared with branch `develop`, verify branch `{branch}` in its worktree."}},
                 {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "SubagentHandback",
                  "input": {"message": f"VERDICT: {verdict}\n\nEVIDENCE:\n- gate ok\n\n"
                                       f"PROBLEMS (most severe first)\n\n{listed or 'none'}\n"}}]}},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": "Cleanup next."}]}}]
        path = TMP / f"{agent}.jsonl"
        with path.open("a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in lines))
        hook("subagent_stop.py", {"cwd": str(repo), "agent_type": "kit:verifier", "agent_id": agent,
                                  "agent_transcript_path": str(path), "last_assistant_message": "Cleanup next."})

    # CLAUDE_CODE_SESSION_ATTENDED=1: someone is at the keyboard, whatever the entrypoint
    os.environ.pop("CLAUDE_CODE_SESSION_ATTENDED", None)  # this test may itself run in an attended cloud session
    os.environ["CLAUDE_CODE_ENTRYPOINT"] = "remote_mobile"
    assert lessons.headless(), "an unknown entrypoint alone is headless"
    os.environ["CLAUDE_CODE_SESSION_ATTENDED"] = "1"
    assert not lessons.headless(), "attended: a person is watching"
    os.environ["KIT_HEADLESS"] = "1"
    assert lessons.headless(), "the overnight flag still wins"
    for key in ("CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ATTENDED", "KIT_HEADLESS"):
        os.environ.pop(key, None)

    assert subagent_stop.parse("VERDICT: FAIL\nPROBLEMS:\n1. the real one\n\nNOT CHECKED:\n1. load test\n") == \
        ("FAIL", ["the real one"]), "a later section is not a problem"
    assert subagent_stop.parse("VERDICT: FAIL\nEVIDENCE:\nPROBLEMS\n- gate ok\n## Problems\n"
                               "- alpha breaks (see e.g. the log) in prod. More.\n  1. open the page\n  2. click export\n"
                               "- Docs nits:\n- the totals row is off\nTODO: on empty lists\nNot checked:\n- load test\n"
                               "PROBLEMS: see above\n") == \
        ("FAIL", ["alpha breaks (see e.g. the log) in prod.", "the totals row is off TODO: on empty lists"]), \
        "the heading after EVIDENCE in any case, bullet problems over their steps, no sub-heading, any-case end"
    assert subagent_stop.parse("VERDICT: FAIL\nPROBLEMS:\n1. Typecheck fails:\n   - src/a.ts:3 is untyped\n"
                               "2. Token leak (informational endpoint returns the API key)\n"
                               "3. Retry loop never ends (nit-picker job, worker.ts:9)\n4. Scope and naming.\n"
                               "   - the flag is x2 in api.ts\n5. **`parseDate`** drops the timezone.\n"
                               "6. Remaining notes (informational):\n   - a style point\n") == \
        ("FAIL", ["Typecheck fails: src/a.ts:3 is untyped", "Token leak (informational endpoint returns the API key)",
                  "Retry loop never ends (nit-picker job, worker.ts:9)", "Scope and naming: the flag is x2 in api.ts",
                  "`parseDate` drops the timezone."]), \
        "a numbered problem with details stays, a word in its own parenthesis does not make it a note, " \
        "an empty headline takes its first detail, code keeps its backtick"
    verifier("x1", "feat/x", "FAIL", "the export button ignores the date filter", "the totals row is off by one")
    verifier("y1", "feat/y", "FAIL", "the export button ignores the date filter", "the csv header is in German")
    verifier("z1", "feat/z", "FAIL", "the retry banner never clears")

    def status():
        return {r["text"].split(": ", 1)[1].split(" (")[0]: r["status"] for r in rows(repo)}
    assert list(status().values()) == ["active", "candidate", "candidate", "candidate"], status()
    verifier("x2", "feat/x", "PASS")
    assert status() == {"the export button ignores the date filter": "active", "the totals row is off by one": "active",
                        "the csv header is in German": "candidate", "the retry banner never clears": "candidate"}, \
        "a PASS confirms only its own branch's FAIL"
    verifier("z1", "feat/z", "FAIL", "the toast hides the save button")
    verifier("z1", "feat/z", "PASS")
    assert status()["the toast hides the save button"] == "active", \
        "a verifier resumed with SendMessage: its second FAIL is captured and its PASS confirms it"


def test_distill():
    repo = make_repo("tidy", "https://example.com/acme/tidy.git")
    slug = lessons.repo(repo)["slug"]
    a = lessons.observe(slug, "a", "recipe", "run the integration tests with a fresh database before pushing",
                        "user", activate_at=1)
    b = lessons.observe(slug, "b", "recipe", "run integration tests with a fresh database before you push",
                        "user", activate_at=1)
    old = lessons.observe(slug, "old", "gate", "the old lint step fails on generated files", "gate",
                          activate_at=1, extra={"last": "2026-01-01"})
    older = lessons.observe(slug, "older", "gate", "the type check times out on a cold cache", "gate",
                            activate_at=1, extra={"last": "2026-01-01"})
    miss = lessons.observe(slug, "miss", "pitfall", "docs name codes from unmerged sibling branches", "user",
                           activate_at=1)
    lessons.mark_delivered(slug, [miss])
    for _ in range(2):
        lessons.observe(slug, "miss", "pitfall", "same", "verifier-fail")

    lines, _ = distill.distill(repo, model=False)
    by_id = {r["id"]: r for r in rows(repo)}
    assert by_id[b]["status"] == "merged" and by_id[a]["seen"] == 2, "the same lesson told twice is one"
    assert by_id[old]["status"] == "active" and by_id[old]["retire_proposed"], "a stale lesson is only proposed"
    assert by_id[miss]["proposal"]["state"] == "proposed", by_id
    assert len(lines) == 4 and all("undo" in line or "Not applied" in line for line in lines), lines
    start = hook("session_start.py", {"cwd": str(repo), "source": "startup"}, KIT_HEADLESS="1").stdout
    assert f"merged {b} into {a}" in start and "proposal to retire" in start, start
    again = hook("session_start.py", {"cwd": str(repo), "source": "startup"}, KIT_HEADLESS="1").stdout
    assert f"merged {b} into" not in again, "news is told once"
    assert lessons.observe(slug, "b", "recipe", "again", "verifier-fail") == a, "a merged key counts on the kept one"
    for lesson_id in (old, miss):  # keep: undoing a proposal is not redone
        assert lessons.main(["undo", lesson_id, str(repo)]) == 0
    assert lessons.main(["retire", older, str(repo)]) == 0  # accept
    distill.distill(repo, model=False)
    by_id = {r["id"]: r for r in rows(repo)}
    assert not by_id[old].get("retire_proposed") and not by_id[miss].get("proposal"), by_id
    assert by_id[old]["status"] != "retired" and by_id[older]["status"] == "retired", "one line, one answer"


def test_model_pass():
    repo = make_repo("model", "https://example.com/acme/model.git")
    slug = lessons.repo(repo)["slug"]
    ids = [lessons.observe(slug, f"k{i}", "pitfall", text, "user", activate_at=1) for i, text in enumerate((
        "retry loops burn their attempts within minutes", "the export ignores the date filter",
        "status labels are inferred from the batch id"))]
    ops = [{"op": "edit", "id": ids[0], "text": "Retries need a backoff that outlasts an outage"},
           {"op": "edit", "id": "L99", "text": "an id that does not exist is ignored"},
           {"op": "edit", "id": ids[1], "text": "use token ghp_" + "a1B2" * 9},
           {"op": "retire", "id": ids[2], "why": "one-off"}]
    fake = TMP / "fake-claude"
    fake.write_text("#!/bin/sh\necho \"$@\" >> " + str(TMP / "fake-args") + "\ncat > /dev/null\n"
                    "echo '" + json.dumps({"result": json.dumps({"ops": ops}), "total_cost_usd": 0.0012}) + "'\n")
    fake.chmod(0o755)
    env = {"KIT_LEARN_MODEL": "1", "KIT_LEARN_CLAUDE": str(fake), "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}
    os.environ.update(env)
    try:
        assert "headless" in distill.model_pass(lessons.repo(repo))[1], "never in a `claude -p` session"
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
        before = lessons.file_of(slug).read_bytes()
        dry = lessons.review(repo, dry_run=True)
        assert any(x.startswith("would: reworded") for x in dry) and lessons.file_of(slug).read_bytes() == before, dry
        lines, status = distill.distill(repo)
        model_lines = [line for line in lines if line.startswith(("reworded", "retired"))]
        assert "2 change(s), the dry run's answer" in status and len(model_lines) == 2, (lines, status)
        args = (TMP / "fake-args").read_text()
        assert len(args.splitlines()) == 1, "the review applies the dry run's answer without a second call"
        assert "--max-budget-usd 0.05" in args and "--tools" in args and "--safe-mode" in args, args
        by_id = {r["id"]: r for r in rows(repo)}
        assert by_id[ids[0]]["text"].startswith("Retries need") and "ghp_" not in by_id[ids[1]]["text"]
        assert by_id[ids[2]]["status"] == "retired"
        assert "already ran today" in distill.distill(repo)[1], "one model run a day per repo"
        before = lessons.file_of(slug).read_bytes()
        assert distill.apply_model_ops(slug, [{"op": "edit", "id": [ids[0]], "text": 5}]) == [] \
            and lessons.file_of(slug).read_bytes() == before, "a malformed op is ignored, never raised"
    finally:
        for key in env:
            os.environ.pop(key, None)
        os.environ["KIT_LEARN_MODEL"] = "0"


def test_judge():
    import promote
    repos = [make_repo(f"j{i}", f"https://example.com/acme/j{i}.git") for i in range(2)]
    for r in repos:
        lessons.register(lessons.repo(r))
        for key, text in (("timeouts", "Timeouts belong on every network call."),
                          ("orm-bump", "an orm bump breaks the jest transform of generated clients")):
            lessons.observe(lessons.repo(r)["slug"], key, "pitfall", text, "user", activate_at=1)

    def machine_keys():
        return {r.get("key") for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) if r.get("status") == "active"}
    info = lessons.repo(repos[0])
    lines = promote.scan(info)
    assert not {"timeouts", "orm-bump"} & machine_keys() and any("genericity check" in x for x in lines), \
        "no model: a lesson in 2 repos stays local"
    fake = TMP / "fake-judge"
    fake.write_text("#!/usr/bin/env python3\nimport json, re, sys\nlines = re.findall(r'^(\\d+)\\. (.*)$', "
                    "sys.stdin.read(), re.M)\nv = [{'n': int(n), 'verdict': 'generic' if 'Timeouts' in t else "
                    "'specific'} for n, t in lines]\nprint(json.dumps({'result': json.dumps({'verdicts': v}), "
                    "'total_cost_usd': 0.001}))\n")
    fake.chmod(0o755)
    env = {"KIT_LEARN_MODEL": "1", "KIT_LEARN_CLAUDE": str(fake), "CLAUDE_CODE_ENTRYPOINT": "cli"}
    os.environ.update(env)
    try:
        bad = TMP / "fake-judge-bool"
        bad.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps({'result': json.dumps({'verdicts': "
                       "[{'n': True, 'verdict': 'generic'}]}), 'total_cost_usd': 0.001}))\n")
        bad.chmod(0o755)
        os.environ["KIT_LEARN_CLAUDE"] = str(bad)
        before = machine_keys()
        promote.scan(info)
        assert machine_keys() == before, "a lesson number of true is not lesson 1"
        os.environ["KIT_LEARN_CLAUDE"] = str(fake)
        promote.scan(info)
        runs = lessons.load_repos()[info["slug"]]["model_runs"][lessons.today()]
        assert runs == 1 and distill.model_allowed(info)[0], "the judge and the tidy pass share one counted run"
    finally:
        for key in env:
            os.environ.pop(key, None)
        os.environ["KIT_LEARN_MODEL"] = "0"
    assert "timeouts" in machine_keys(), "the judge says generic: every repo gets it"
    assert "orm-bump" not in machine_keys(), "the judge says specific: it stays in its repos"


def test_promotion():
    import promote
    judge, distill.judge = distill.judge, lambda info, texts: {t: True for t in texts}  # the judge: test_judge
    repos = [make_repo(f"p{i}", f"https://example.com/acme/p{i}.git") for i in range(3)]
    slugs = []
    for r in repos:
        info = lessons.repo(r)
        lessons.register(info)
        slugs.append(info["slug"])

    def teach(i, key, text):
        return lessons.observe(slugs[i], key, "preference", text, "user", activate_at=1)

    teach(0, "short-pr", "keep pull request descriptions to a short narrative")
    teach(1, "short-pr", "keep pull request descriptions to a short narrative")
    distill.distill(repos[0], model=False)
    machine = lessons.read_rows(lessons.file_of(lessons.MACHINE))
    m = next(r for r in machine if r.get("key") == "short-pr")
    assert m["status"] == "active" and len(m["from"]) == 2 and "promote" not in m, m
    assert "(all repos) keep pull request" in lessons.deliver(repos[2], "implementer", 2400), "every repo gets it"
    assert all(r["status"] == "promoted" for r in rows(repos[0]) if r.get("key") == "short-pr")
    assert lessons.main(["undo", m["id"], str(repos[0])]) == 0
    distill.distill(repos[0], model=False)
    assert [r["status"] for r in rows(repos[0]) if r.get("key") == "short-pr"] == ["active"], "undo sticks"

    for i in range(3):
        teach(i, "kit-worktree-bash", "the worktree guard blocks Bash cd into a sibling worktree")
    lines, _ = distill.distill(repos[0], model=False)
    assert any(line.startswith("kit candidate M") and "/kit:learn promote M" in line for line in lines), lines
    cand = next(r for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) if r.get("key") == "kit-worktree-bash")
    assert lessons.observe(slugs[0], "kit-worktree-bash", "preference", "seen again", "verifier-fail") == cand["id"], \
        "a promoted repo lesson is counted on its machine lesson"
    os.environ["CLAUDE_CODE_ENTRYPOINT"] = "claude-code-github-action"  # not sdk-*, still headless
    assert promote.brief(cand["id"], lessons.repo(repos[0]))[0] is None, "no promotion from a headless run"
    os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
    text = promote.brief(cand["id"], lessons.repo(repos[0]))[0]
    assert "Branch: learn/kit-worktree-bash" in text and "passes the scrub" in text, text
    assert promote.promoted(cand["id"], "0.0.1", "https://example.com/pr/1", lessons.repo(repos[0]))
    promote.merged = lambda url: False  # no network in tests: an open PR has not shipped anything
    distill.distill(repos[0], model=False)
    assert next(r for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) if r["id"] == cand["id"])["status"] == "active"
    promote.merged = lambda url: url == "https://example.com/pr/1"
    distill.distill(repos[0], model=False)
    cand = next(r for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) if r["id"] == cand["id"])
    assert cand["status"] == "retired" and "fixed in kit" in cand["retired"]["why"], "a shipped fix retires it"

    for i in range(3):
        teach(i, "kit-hook-cwd", "the subagent hook sees the parent checkout as its cwd")
    distill.distill(repos[0], model=False)
    again = next(r for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) if r.get("key") == "kit-hook-cwd")
    assert again.get("promote") and lessons.main(["undo", again["id"], str(repos[0])]) == 0
    distill.distill(repos[0], model=False)
    again = next(r for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) if r.get("key") == "kit-hook-cwd")
    assert not again.get("promote"), "an undone kit candidate is not marked again"

    found = promote.scrub(f"+ see {repos[1]}/README\n+ for acme/p1 set API_BASE_URL\n+ a generic guard step")
    assert len(found) >= 2 and not any("line 3" in f for f in found), found
    assert promote.scrub("@@ -1 +1 @@\n+ token ghp_" + "a1B2" * 9 + f"\n  context {repos[1]}") == \
        ["line 2: secret-shaped text"], "a diff's context lines are already in the kit"
    distill.judge = judge


def test_upkeep():
    import promote
    scratch = TMP / "scratch"
    scratch.mkdir()
    os.environ["KIT_TEMP_ROOTS"] = str(scratch)  # the test's repos are real; only scratch/ is a temp folder
    try:
        probe = make_repo("scratch/probe")
        assert lessons.repo(probe) is None and lessons.capture(probe, "gate", "k", "probe failed") is None, \
            "a scratchpad repo writes no lesson to a real ledger"
        noisy = {"main": str(scratch / "old"), "origin": str(scratch / "old")}
        lessons.register({"slug": "scratch-old-1", **noisy})
        lessons.file_of("scratch-old-1").write_text("{}\n")
        lessons.observe(lessons.MACHINE, "fake-gate", "gate", "the fake gate failed", "gate", extra={"from": ["scratch-old-1:L1"]})
        assert promote.specific("keep old builds") is None, "a scratchpad repo's name is not a project term"
        assert promote.specific("check pass/fail and/or CI/CD output") is None, "a slashed word is not a file path"
        for text in ("The ACME integration suites need run.sh --migrate acme",
                     "Zorbix 7 breaks ts-jest of src/generated", "ACME_DB_URL must be set"):
            assert promote.specific(text), f"a project-specific lesson stays in its repo: {text}"
        dry = lessons.prune(dry_run=True)
        assert any("would drop the ledger of scratch-old-1" in x for x in dry) and any("would retire M" in x for x in dry), dry
        assert lessons.file_of("scratch-old-1").exists(), "a dry run changes nothing"
        lessons.prune(dry_run=False)
        assert not lessons.file_of("scratch-old-1").exists() and "scratch-old-1" not in lessons.load_repos()

        a, b = (make_repo(f"g{i}", f"https://example.com/acme/g{i}.git") for i in range(2))
        for r in (a, b):
            lessons.register(lessons.repo(r))
            lessons.observe(lessons.repo(r)["slug"], "local-path", "preference", "run src/db/seed.ts first", "user", activate_at=1)
        promote.scan()
        assert not any(r.get("key") == "local-path" for r in lessons.read_rows(lessons.file_of(lessons.MACHINE))), \
            "a lesson naming a project's files stays in its repo"

        old = (datetime.date.today() - datetime.timedelta(days=lessons.IDLE_DAYS + 1)).isoformat()
        with lessons.change(lessons.repo(a)["slug"]) as state:
            for r in state["rows"]:
                r["last"] = r["created"] = old
                r["last_delivered"] = lessons.today()
        idle = lessons.idle(lessons.repo(a)["slug"])
        assert idle and all(x.startswith("would retire") for x in idle), \
            "a lesson delivered every day but not seen for IDLE_DAYS is proposed for retiring"
        with lessons.change(lessons.repo(a)["slug"], log=False) as state:
            for r in state["rows"]:
                r["kept"] = lessons.today()
        assert not lessons.idle(lessons.repo(a)["slug"]), "a lesson the user kept is not idle"
        assert lessons.rank({"id": "L1", "seen": 9, "last": old, "last_delivered": lessons.today()}) < \
            lessons.rank({"id": "L2", "seen": 1, "last": lessons.today()}), "seen lately beats only delivered"
        assert lessons.review_due(a) == "", "the first session starts the clock"
        lessons.register(lessons.repo(a), reviewed_ts=time.time() - (lessons.REVIEW_DAYS + 1) * 86400)
        assert "lesson review for this repo is due" in lessons.review_due(a)
        assert lessons.review_due(a) == "", "the due line shows once per period; a declined review snoozes"
        slug = lessons.repo(a)["slug"]
        for key, text in (("t1", "run the integration tests with a fresh database before pushing"),
                          ("t2", "run integration tests with a fresh database before you push")):
            lessons.observe(slug, key, "recipe", text, "user", activate_at=1)
        before = lessons.file_of(slug).read_bytes()
        dry = lessons.review(a, dry_run=True, model=False)
        assert any(x.startswith("would: merged") for x in dry) and "rewords skipped (--no-model)" in dry, dry
        assert lessons.file_of(slug).read_bytes() == before, "the preview runs on a copy"
        lessons.main(["review", "--no-model", str(a)])
        assert lessons.review_due(a) == "", "a review resets the clock"
    finally:
        os.environ.pop("KIT_TEMP_ROOTS", None)


def main():
    for test in (test_ledger, test_import, test_capture, test_delivery, test_fail_then_pass, test_distill,
                 test_model_pass, test_judge, test_promotion, test_upkeep):
        test()
    print("lessons: all checks passed")


if __name__ == "__main__":
    main()
