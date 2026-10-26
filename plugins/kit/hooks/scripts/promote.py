#!/usr/bin/env python3
"""Promotion: lessons that hold in more than one repo move up a layer.

- **Machine.** The same lesson (same key, or the distiller's word match) active in 2 repo ledgers
  becomes one machine lesson (`_machine.jsonl`, ids M1, M2, ...) that every repo gets; the repo
  records turn `promoted` and point at it. Undoing the machine lesson gives them back and stops
  them from being promoted again.
- **Kit candidate.** A machine lesson seen in 3 or more repos or about the kit itself, and any
  `kit-defect` lesson, is marked a promotion candidate and announced. Nothing else happens: a
  claude-kit branch and PR are prepared only by `/kit:learn promote <id>`, run by the user in a
  session (`brief` refuses in a headless run), and the PR is never merged by Claude.
- **Version-bound.** A lesson whose fix shipped (`fixed_in`, set by `lessons.py promoted`) retires
  once its PR is merged and the installed kit is at that version (distill.retire_why).

`scrub` checks text bound for the kit (a diff) against what the ledgers know about this machine:
repo names, orgs, slugs and checkout paths, the home folder, env var names lessons mention, and
anything shaped like a secret. Standard library only.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import distill  # noqa: E402
import kitlib  # noqa: E402
import lessons  # noqa: E402

MACHINE_AT = 2
KIT_AT = 3
ABOUT_KIT = re.compile(r"\b(claude code|claude-kit|the kit|kit:\w+|/kit:\w+|worktree guard|subagents?)\b", re.I)
ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]{2,}\b")
COMMON_ENV = ("KIT_", "CLAUDE_", "GITHUB_", "NODE_", "NPM_", "PYTHON", "HOME", "PATH")
GENERIC = set("app api web src lib docs doc hooks scripts tests test main site server client core infra".split())


def repo_slugs():
    return sorted(s for s in lessons.load_repos() if s != lessons.MACHINE)


def same(a, b):
    return a.get("key") == b.get("key") or distill.alike(a, b)


# ---- repo -> machine ------------------------------------------------------------------------

def scan():
    """Promote lessons active in MACHINE_AT+ repos, then mark kit candidates. Returns news lines.
    One scan at a time on this machine; a second one returns at once."""
    try:
        with lessons.locked("_promote", wait=0):
            return scan_locked()
    except lessons.Busy:
        return []


def scan_locked():
    machine = distill.live(lessons.read_rows(lessons.file_of(lessons.MACHINE)))
    held = {m for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) for m in r.get("from") or []}
    # a repo copy a machine lesson already holds stays out: it is active again only by an undo
    pool = [(slug, r) for slug in repo_slugs() for r in lessons.read_rows(lessons.file_of(slug))
            if r.get("status") == "active" and not r.get("no_promote") and member(slug, r) not in held]
    clusters = [{"m": m, "members": []} for m in machine]
    for slug, r in pool:
        home = next((c for c in clusters if (c["m"] and same(c["m"], r))
                     or any(same(x, r) for _, x in c["members"])), None)
        if home is None:
            clusters.append({"m": None, "members": [(slug, r)]})
        else:
            home["members"].append((slug, r))
    lines = []
    for c in clusters:
        if c["m"] and c["members"]:
            lines += attach(c["m"]["id"], c["members"])
        elif not c["m"] and len({slug for slug, _ in c["members"]}) >= MACHINE_AT:
            lines += create(c["members"])
    return lines + mark_candidates()


def create(members):
    best = max((r for _, r in members), key=lessons.rank)
    with lessons.change(lessons.MACHINE) as state:
        record = {k: v for k, v in best.items() if k not in ("file", "sources", "delivered", "last_delivered",
                                                              "proposal", "promote", "fixed_in")}
        record.update({"id": lessons.next_id(state["rows"], "M"), "status": "active", "origin_src": "promoted",
                       "created": lessons.today(), "activated": lessons.today(), "from": [],
                       "seen": 0, "misses": 0, "helpful": 0, "harmful": 0, "evidence": [], "projects": []})
        add_members(record, members)
        state["rows"].append(record)
        line = (f"made {record['id']} a lesson for every repo (seen in {repos_of(record)} repos): "
                f"{lessons.brief(record['text'])} · {lessons.UNDO.format(record['id'])}")
        state["news"].append(line)
    mark_promoted(record["id"], members)
    return [line]


def attach(m_id, members):
    with lessons.change(lessons.MACHINE) as state:
        record = next(r for r in state["rows"] if r.get("id") == m_id)
        add_members(record, members)
    mark_promoted(m_id, members)
    return []


def member(slug, record):
    """How a machine lesson names a repo lesson it holds (`from`)."""
    return f"{slug}:{record['id']}"


def add_members(record, members):
    agents = set((record.get("applies") or {}).get("agents") or [])
    for slug, r in members:
        if member(slug, r) in record["from"]:
            continue
        record["from"].append(member(slug, r))
        for field in ("seen", "misses", "helpful", "harmful"):
            record[field] = int(record.get(field, 0)) + int(r.get(field, 0))
        record["evidence"] = sorted(record["evidence"] + (r.get("evidence") or []),
                                    key=lambda e: e.get("date", ""))[-lessons.MAX_EVIDENCE:]
        record["projects"] += [p for p in r.get("projects") or [] if p not in record["projects"]]
        record["last"] = max(record.get("last") or "", r.get("last") or "")
        agents |= set((r.get("applies") or {}).get("agents") or lessons.AGENTS)
    record["applies"] = {"agents": [a for a in lessons.AGENTS if a in agents]}


def mark_promoted(m_id, members):
    for slug in sorted({slug for slug, _ in members}):
        ids = {r["id"] for s, r in members if s == slug}
        with lessons.change(slug) as state:
            for r in state["rows"]:
                if r.get("id") in ids:
                    r["status"], r["promoted_to"] = "promoted", m_id


def repos_of(record):
    return len({str(f).rsplit(":", 1)[0] for f in record.get("from") or []})


def release(m_id):
    """After an undo of machine lesson m_id: repo records it no longer holds become active again,
    and are not promoted again."""
    m = next((r for r in lessons.read_rows(lessons.file_of(lessons.MACHINE)) if r.get("id") == m_id), None)
    held = set(m.get("from") or []) if m and m.get("status") == "active" else set()
    for slug in repo_slugs():
        with lessons.change(slug, log=False) as state:
            for r in state["rows"]:
                if r.get("promoted_to") == m_id and r.get("status") == "promoted" and member(slug, r) not in held:
                    r["status"], r["no_promote"] = "active", True
                    r.pop("promoted_to", None)


# ---- machine -> kit -------------------------------------------------------------------------

def why_candidate(record, machine):
    if record.get("kind") == "kit-defect":
        return "a kit defect"
    if not machine:
        return None
    n = repos_of(record)
    if n >= KIT_AT:
        return f"seen in {n} repos"
    if ABOUT_KIT.search(record.get("text", "")) or str(record.get("key", "")).startswith(("kit-", "guard-")):
        return f"about the kit, seen in {n} repos"
    return None


def mark_candidates():
    lines = []
    for slug in [lessons.MACHINE] + repo_slugs():
        machine = slug == lessons.MACHINE

        def pick(r):
            return r.get("status") == "active" and not r.get("promote") and not r.get("kept") \
                and not r.get("retire_proposed") \
                and why_candidate(r, machine)

        def act(r):
            why = why_candidate(r, machine)
            r["promote"] = {"state": "candidate", "date": lessons.today(), "why": why}
            return (f"kit candidate {r['id']} ({why}): {lessons.brief(r['text'])}. A claude-kit PR is "
                    f"prepared only if you run /kit:learn promote {r['id']} · {lessons.UNDO.format(r['id'])}")
        lines += distill.each(slug, pick, act)
    return lines


def find(lesson_id, info):
    slug = lessons.MACHINE if lesson_id.startswith("M") else info["slug"]
    return slug, next((r for r in lessons.read_rows(lessons.file_of(slug)) if r.get("id") == lesson_id), None)


def merged(url):
    """True when the PR at `url` is merged (gh, 5 s); unknown counts as not merged."""
    if not url or not shutil.which("gh"):
        return False
    try:
        out = subprocess.run(["gh", "pr", "view", url, "--json", "state", "-q", ".state"], capture_output=True,
                             text=True, timeout=5)
        return out.returncode == 0 and out.stdout.strip() == "MERGED"
    except Exception:
        return False


def kit_checkout():
    origin = lessons.kit_origin()
    for entry in lessons.load_repos().values():
        if origin and entry.get("origin") == origin and entry.get("main") and Path(entry["main"]).is_dir():
            return entry["main"]
    return None


def brief(lesson_id, info):
    """The brief for `/kit:learn promote <id>`, or (None, why not)."""
    if lessons.headless():
        return None, "promotion runs only from /kit:learn promote in an interactive session"
    slug, r = find(lesson_id, info)
    if not r or not r.get("promote"):
        return None, f"{lesson_id} is not a promotion candidate (/kit:learn promote lists them)"
    hits = scrub(r.get("text", ""))
    key = re.sub(r"[^a-z0-9-]+", "-", str(r.get("key", lesson_id)).lower()).strip("-")[:40] or lesson_id.lower()
    return "\n".join([
        f"Promote {lesson_id} to the kit ({r['promote']['why']}; kind {r.get('kind')}; seen {r.get('seen', 1)} times, "
        f"{r.get('misses', 0)} after threads were told).",
        f"Lesson: {r.get('text')}",
        "The lesson text names repo specifics; write the kit change without them." if hits else
        "The lesson text passes the scrub.",
        f"Kit checkout: {kit_checkout() or 'none registered; clone ' + (lessons.kit_origin() or 'the kit repo')}",
        f"Kit origin: {lessons.kit_origin()}; kit version installed: {lessons.kit_version()}",
        f"Branch: learn/{key}",
    ]), None


def promoted(lesson_id, version, url, info):
    """The PR is open: the lesson retires itself once the PR is merged and the installed kit reaches
    `version`."""
    slug, r = find(lesson_id, info)
    if not r:
        return False
    with lessons.change(slug) as state:
        for x in state["rows"]:
            if x.get("id") == lesson_id:
                x["promote"] = dict(x.get("promote") or {}, state="opened", pr=url, date=lessons.today())
                x["fixed_in"] = version
    return True


# ---- scrub ----------------------------------------------------------------------------------

def denylist():
    """Terms that must not reach the kit: what the ledgers know about this machine's repos."""
    kit = set((lessons.kit_origin() or "").lower().split("/"))
    names, paths = set(), {str(Path.home())}
    for slug, entry in lessons.load_repos().items():
        if slug == lessons.MACHINE or (entry.get("origin") and entry.get("origin") == lessons.kit_origin()):
            continue
        names.add(slug)
        origin = str(entry.get("origin") or "")
        if not origin.startswith("/"):  # a repo without a remote is keyed by its path, listed below
            names.update(p for p in origin.split("/")[1:] if len(p) >= 3)
        if entry.get("main"):
            paths.add(str(entry["main"]))
            names.add(Path(entry["main"]).name)
    for slug in [lessons.MACHINE] + repo_slugs():
        for r in lessons.read_rows(lessons.file_of(slug)):
            names.update(n for n in ENV_NAME.findall(r.get("text", "")) if not n.startswith(COMMON_ENV))
            if r.get("file"):
                paths.add(str(Path(r["file"]).parent))
    if len(Path.home().name) >= 3:
        names.add(Path.home().name)
    return sorted(n for n in names if n.lower() not in kit | GENERIC and len(n) >= 3), sorted(paths)


def scrub(text):
    """Problems in `text` (one per line and term), without echoing secret-shaped text. In a diff,
    only the added lines count: context lines are already in the kit."""
    names, paths = denylist()
    lines = text.splitlines()
    diff = any(line.startswith(("diff --git", "@@ ")) for line in lines)
    found = []
    for n, line in enumerate(lines, 1):
        if diff and not line.startswith(("+", "diff --git", "rename to ")):
            continue  # file names (+++, diff --git, rename) count too
        if kitlib.looks_secret(line):
            found.append(f"line {n}: secret-shaped text")
        found += [f"line {n}: a path from this machine ({p})" for p in paths if p in line]
        found += [f"line {n}: names a repo or its setup ({t})" for t in names
                  if re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])", line, re.I)]
    return found


def main(argv):
    """lessons.py promote|promoted|scrub."""
    cmd, rest = argv[0], argv[1:]
    if cmd == "scrub":
        source = rest[0] if rest else "-"
        try:
            text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"scrub: cannot read {source}: {exc.strerror}", file=sys.stderr)
            return 2
        found = scrub(text)
        print("\n".join(found) if found else "scrub: clean")
        return 1 if found else 0
    ids = [a.upper() for a in rest if re.fullmatch(r"[LMlm]\d+", a)]
    others = [a for a in rest if a.upper() not in ids]
    info = lessons.repo(others[-1] if others and Path(others[-1]).is_dir() else os.getcwd())
    if not info:
        print("kit lessons: not a git checkout the kit can key a ledger to", file=sys.stderr)
        return 1
    if cmd == "promoted":
        if len(ids) != 1 or len(others) < 2:
            print("usage: lessons.py promoted ID VERSION PR_URL [DIR]", file=sys.stderr)
            return 2
        ok = promoted(ids[0], others[0], others[1], info)
        print(f"{ids[0]} retires itself once the PR is merged and kit {others[0]} is installed" if ok else "no such lesson")
        return 0 if ok else 1
    if not ids:
        for slug in [lessons.MACHINE, info["slug"]]:
            for r in lessons.read_rows(lessons.file_of(slug)):
                if r.get("status") == "active" and (r.get("promote") or {}).get("state") == "candidate":
                    print(f"{r['id']:>5} ({r['promote']['why']})  {r.get('text', '')}")
        return 0
    text, why = brief(ids[0], info)
    print(text or why)
    return 0 if text else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
