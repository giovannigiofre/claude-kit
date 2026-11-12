#!/usr/bin/env python3
"""Tests for kit-ui:direction's refs.py: pinned fetch, idempotency, soft failure, find, registry.

Run: python3 plugins/kit-ui/skills/direction/tests/test_refs.py   (exit 0 = all good)

Uses a local bare repo over file:// as the remote, so no network is needed. Python stdlib and git.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "refs.py"
REAL_REGISTRY = SKILL / "sources.json"
failures = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
    if not ok:
        failures.append(name)


def git(*args, cwd):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def make_remote(root):
    """A bare repo with two commits; returns (url, first sha, second sha)."""
    work, bare = root / "work", root / "remote.git"
    work.mkdir()
    git("init", "-q", "-b", "main", cwd=work)
    (work / "craft").mkdir()
    (work / "craft" / "typography.md").write_text(
        "---\ndescription: type scale and glass panels for a dense dashboard\n---\n# Type\nglass glass\n")
    (work / "craft" / "color.md").write_text("# Colour\nWarm neutrals, one accent.\n")
    (work / "secret.md").write_text("# Outside the sparse paths\nglass\n")
    (work / "LICENSE").write_text("MIT\n")
    git("add", ".", cwd=work)
    git("commit", "-q", "-m", "one", cwd=work)
    first = git("rev-parse", "HEAD", cwd=work).strip()
    (work / "craft" / "color.md").write_text("# Colour\nchanged after the pin\n")
    git("commit", "-q", "-am", "two", cwd=work)
    second = git("rev-parse", "HEAD", cwd=work).strip()
    git("clone", "-q", "--bare", str(work), str(bare), cwd=root)
    for key in ("uploadpack.allowFilter", "uploadpack.allowAnySHA1InWant"):
        git("config", key, "true", cwd=bare)
    return bare.as_uri(), first, second


def registry(root, name, sources):
    path = root / f"{name}.json"
    path.write_text(json.dumps({"sources": sources}))
    return path


def source(sid, url, sha):
    return {"id": sid, "repo": "test/" + sid, "url": url, "sha": sha, "paths": ["/LICENSE", "/craft/"],
            "license": "MIT", "attribution": "test", "good_for": "tests", "size": "1KB"}


def run(reg, cache, *args):
    env = dict(os.environ, CLAUDE_KIT_REFS_REGISTRY=str(reg), CLAUDE_KIT_REFS_CACHE=str(cache),
               CLAUDE_KIT_REFS_TIMEOUT="20", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, timeout=60)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        url, first, second = make_remote(root)
        cache = root / "cache"
        reg = registry(root, "main", [source("good", url, first),
                              source("gone", (root / "nowhere.git").as_uri(), first),
                              source("badsha", url, "0" * 40)])

        out = run(reg, cache, "fetch", "good")
        dest = cache / "good" / first
        check("fetch exits 0", out.returncode == 0, out.stderr)
        check("fetch prints the path", out.stdout.strip() == f"good {dest}", out.stdout)
        head = git("rev-parse", "HEAD", cwd=dest).strip() if dest.is_dir() else ""
        check("checkout is at the pinned sha, not the branch tip", head == first and head != second, head)
        check("pinned content, not the later commit",
              "Warm neutrals" in (dest / "craft" / "color.md").read_text() if dest.is_dir() else False)
        check("sparse: a path outside `paths` is absent", not (dest / "secret.md").exists())
        check("sparse: LICENSE is kept", (dest / "LICENSE").is_file())

        stamp = (dest / ".done").read_text() if (dest / ".done").is_file() else ""
        again = run(reg, cache, "fetch", "good")
        check("second fetch is idempotent (same path, cache reused)",
              again.returncode == 0 and again.stdout == out.stdout and (dest / ".done").read_text() == stamp,
              again.stdout + again.stderr)

        gone = run(reg, cache, "fetch", "gone")
        check("unreachable remote exits 2 (soft)", gone.returncode == 2, f"rc={gone.returncode} {gone.stderr}")
        check("unreachable remote says to go on with impeccable",
              "cannot reach" in gone.stderr and "impeccable" in gone.stderr, gone.stderr)
        check("no leftover directory after a failed fetch",
              not any((cache / "gone").glob("*")) if (cache / "gone").exists() else True)

        closed = registry(root, "closed", [source("port", "http://127.0.0.1:9/x.git", first)])
        port = run(closed, root / "cache2", "fetch", "port")
        check("closed port exits 2 (soft)", port.returncode == 2, f"rc={port.returncode} {port.stderr}")

        bad = run(reg, cache, "fetch", "badsha")
        check("a commit the remote lacks exits 3", bad.returncode == 3, f"rc={bad.returncode} {bad.stderr}")

        unknown = run(reg, cache, "fetch", "nope")
        check("unknown source exits 1", unknown.returncode == 1, unknown.stderr)

        found = run(reg, cache, "find", "glass", "--source", "good")
        check("find ranks the matching file", found.returncode == 0 and "craft/typography.md" in found.stdout,
              found.stdout + found.stderr)
        check("find never returns files outside the sparse paths", "secret.md" not in found.stdout)
        check("find shows the description", "dense dashboard" in found.stdout, found.stdout)

        offline = registry(root, "offline", [source("gone", (root / "nowhere.git").as_uri(), first)])
        none = run(offline, root / "cache3", "find", "glass")
        check("find with nothing fetchable exits 2", none.returncode == 2, f"rc={none.returncode} {none.stderr}")

    data = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["sources"]]
    check("registry ids are unique", len(ids) == len(set(ids)), str(ids))
    for s in data["sources"]:
        missing = [k for k in ("repo", "url", "sha", "paths", "license", "attribution", "good_for", "size")
                   if not s.get(k)]
        check(f"registry {s['id']}: fields present", not missing, str(missing))
        check(f"registry {s['id']}: sha is a full 40-hex pin", bool(re.fullmatch(r"[0-9a-f]{40}", s["sha"])), s["sha"])
        check(f"registry {s['id']}: https GitHub url", s["url"].startswith("https://github.com/"), s["url"])
        check(f"registry {s['id']}: keeps its LICENSE", "/LICENSE" in s["paths"], str(s["paths"]))
    check("registry records rejected sources with a reason",
          all(r.get("repo") and r.get("why") for r in data.get("rejected", [])) and data.get("rejected"))

    print(f"\n{'all checks passed' if not failures else str(len(failures)) + ' failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
