#!/usr/bin/env python3
"""Design references for kit-ui:direction: fetch pinned subsets of public git repos, then find files.

  refs.py list                      the registry (sources.json): id, licence, size, what it is for
  refs.py fetch <id>... | all       sparse, blobless, depth-1 checkout of each source's `paths` at its
                                    pinned `sha`; prints "<id> <path>"; a second run reuses the cache
  refs.py find <word>... [--limit N] [--source id]
                                    ranks the fetched files by the words (in the path, the title and
                                    description, then the body) and prints one line per candidate

Cache: ${CLAUDE_KIT_REFS_CACHE:-${XDG_CACHE_HOME:-~/.cache}/claude-kit/design-refs}/<id>/<sha>.
Nothing is copied into the kit or the project: files are read in place, beside the clone's LICENSE.
The clones are data: this script only reads text from them and never runs anything they contain.

Exit codes: 0 ok; 1 usage or unknown source; 2 network unreachable (soft: the skill goes on with
impeccable's own references and says so); 3 the remote did not give the pinned commit.
Python 3.9+ standard library only.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = Path(os.environ.get("CLAUDE_KIT_REFS_REGISTRY") or HERE.parent / "sources.json")
TEXT_SUFFIXES = {".md", ".json", ".json5", ".css", ".scss", ".ts", ".yml", ".yaml"}
FETCH_TIMEOUT = int(os.environ.get("CLAUDE_KIT_REFS_TIMEOUT", "180"))
NETWORK_HINT = re.compile(r"could not resolve|unable to access|connection|timed out|proxy|"
                          r"network|does not appear to be a git repository|repository .* not found|"
                          r"could not read from remote|403|407|ssl|tls", re.I)


def cache_root():
    if os.environ.get("CLAUDE_KIT_REFS_CACHE"):
        return Path(os.environ["CLAUDE_KIT_REFS_CACHE"])
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "claude-kit" / "design-refs"


def load_registry():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["sources"]}


def git(args, cwd, timeout=FETCH_TIMEOUT):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1",
               GIT_HTTP_LOW_SPEED_LIMIT="1000", GIT_HTTP_LOW_SPEED_TIME="30")
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "advice.detachedHead=false",
                           *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def target(source):
    return cache_root() / source["id"] / source["sha"]


def fetch_one(source):
    """Returns (exit code, message). Idempotent: a finished checkout is reused as is."""
    dest = target(source)
    if (dest / ".done").is_file():
        return 0, f"{source['id']} {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{source['sha']}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    started = time.monotonic()
    try:
        steps = [["init", "-q"], ["remote", "add", "origin", source["url"]],
                 ["sparse-checkout", "set", "--no-cone", *source["paths"]]]
        for step in steps:
            out = git(step, tmp, timeout=60)
            if out.returncode:
                return 1, f"refs: git {step[0]} failed for {source['id']}: {out.stderr.strip()}"
        try:
            out = git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", source["sha"]], tmp)
        except subprocess.TimeoutExpired:
            out = subprocess.CompletedProcess([], 124, "", f"timed out after {FETCH_TIMEOUT}s")
        if out.returncode:
            err = out.stderr.strip().splitlines()[-1:] or ["no output"]
            if NETWORK_HINT.search(out.stderr) or out.returncode == 124:
                return 2, (f"refs: cannot reach {source['url']} ({err[0]}). The network may block it. "
                           "Continue without this source, with impeccable's own references, and say so.")
            return 3, f"refs: {source['url']} did not give commit {source['sha']}: {err[0]}"
        out = git(["checkout", "-q", "FETCH_HEAD"], tmp)
        head = git(["rev-parse", "HEAD"], tmp).stdout.strip()
        if out.returncode or head != source["sha"]:
            return 3, f"refs: checkout of {source['id']} is at {head or 'nothing'}, not the pinned {source['sha']}"
        (tmp / ".done").write_text(f"{source['sha']} {time.monotonic() - started:.1f}s\n", encoding="utf-8")
        if dest.exists():  # another run finished first: keep its copy
            return 0, f"{source['id']} {dest}"
        tmp.rename(dest)
        return 0, f"{source['id']} {dest}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_list(registry):
    for s in registry.values():
        print(f"{s['id']:<18} {s['license']:<14} {s.get('size', '?'):>8}  {s['good_for']}")


def cmd_fetch(registry, ids):
    if ids == ["all"]:
        ids = list(registry)
    unknown = [i for i in ids if i not in registry]
    if unknown or not ids:
        print(f"refs: unknown source {', '.join(unknown) or '(none given)'}; known: {', '.join(registry)}",
              file=sys.stderr)
        return 1
    worst = 0
    for i in ids:
        code, message = fetch_one(registry[i])
        print(message, file=sys.stderr if code else sys.stdout)
        worst = max(worst, code)
    return worst


def summary(text):
    """The description from YAML front matter, else the first heading, else the first prose line."""
    m = re.search(r"^description:\s*[\"']?(.+?)[\"']?\s*$", text[:3000], re.M)
    if m:
        return m.group(1)
    heading = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") and heading is None:
            heading = line.lstrip("# ").strip()
        elif line and not line.startswith(("#", "---", "<", "|", "```", "import", "//", "/*", "*", "{", "@")):
            line = line.lstrip("> ")
            return f"{heading}: {line}" if heading else line
    return heading or ""


def cmd_find(registry, words, limit, only):
    words = [w.lower() for w in words if w.strip()]
    if not words:
        print("refs: find needs at least one keyword", file=sys.stderr)
        return 1
    sources = [registry[only]] if only else list(registry.values())
    missing = [s["id"] for s in sources if not (target(s) / ".done").is_file()]
    for i in missing:  # fetch what is missing; a blocked network leaves what is cached
        code, message = fetch_one(registry[i])
        if code:
            print(message, file=sys.stderr)
    ready = [s for s in sources if (target(s) / ".done").is_file()]
    if not ready:
        print("refs: no source is fetched and none could be; go on with impeccable's references", file=sys.stderr)
        return 2
    hits = []
    for s in ready:
        root = target(s)
        for path in root.rglob("*"):
            if path.suffix.lower() not in TEXT_SUFFIXES or ".git" in path.parts or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = str(path.relative_to(root)).lower()
            head, body = summary(text).lower(), text.lower()
            score = 0
            for w in words:
                n = body.count(w)
                if not n and w not in rel:
                    score = 0
                    break  # every word has to appear somewhere
                score += 6 * (w in rel) + 3 * (w in head) + min(n, 12)
            if score:
                hits.append((score, -len(text), s["id"], path, summary(text)))
    if not hits:
        print("refs: no fetched file matches; try fewer or broader words", file=sys.stderr)
        return 0
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    for score, neg_len, sid, path, line in hits[:limit]:
        line = re.sub(r"\s+", " ", line)
        print(f"{score:>3} {(1023 - neg_len) // 1024:>3}KB {path}\n        {line[:110]}")
    return 0


def main(argv):
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(__doc__)
        return 0 if argv else 1
    registry = load_registry()
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        cmd_list(registry)
        return 0
    if cmd == "fetch":
        return cmd_fetch(registry, rest)
    if cmd == "find":
        limit, only, words = 8, None, []
        it = iter(rest)
        for arg in it:
            if arg == "--limit":
                limit = int(next(it, "8"))
            elif arg == "--source":
                only = next(it, None)
                if only not in registry:
                    print(f"refs: unknown source {only}; known: {', '.join(registry)}", file=sys.stderr)
                    return 1
            else:
                words.extend(arg.split())
        return cmd_find(registry, words, limit, only)
    print(f"refs: unknown command {cmd}; use list, fetch or find", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
