#!/usr/bin/env python3
"""The kit's own ratchet: fails when the harness grows text the model has to carry.

Every always-loaded line costs tokens in every session, and instructions the model follows can
make it worse as well as better, so the kit keeps its always-on text small and its language calm.
Checks, over every plugin in plugins/:
  - always-on budget: descriptions of model-invocable skills plus agents, per plugin;
  - each description fits the listing (<= 1024 chars) and parses as a plain YAML scalar;
  - SKILL.md files stay short (details go to files next to them, loaded on demand);
  - no shouted rules (MUST, NEVER, CRITICAL, IMPORTANT, ALWAYS) outside code blocks;
  - no request for the model's reasoning ("show your reasoning", "think out loud", "think step by
    step"): the current models decline those (reasoning_extraction) and the kit never needed them;
  - the core plugin has no hook that runs on every prompt or every tool call;
  - the lessons the SubagentStart hook hands a thread stay within SUBAGENT_LESSONS chars, and the
    ones SessionStart adds (with the kit's news lines and its coordinator line, itself within
    COORDINATOR_MAX) within SESSION_LESSONS;
  - every `kit:x`, `kit-ui:x`, `kit-llm:x` reference names a skill or agent that exists;
  - packaging: every script a hooks.json command names under ${CLAUDE_PLUGIN_ROOT} exists; no file
    under plugins/ holds a personal absolute path; no SKILL.md, agent or reference file holds
    invisible or bidirectional-control characters (see packaging() for the precise rules). These
    checks also run once on a temp copy with a planted mistake each, so a check that stops seeing
    its mistake fails too.

Run: python3 tests/test_budget.py   (exit 0 = all good; standard library only)
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"

# characters of always-on description text per plugin (about 4 characters per token)
# kit-ui 1200 -> 1300 on 2026-11-12 for kit-ui:direction: kit-ui loads only in UI projects,
# so its 276 chars cost nothing elsewhere.
# kit 2600 -> 4200 on 2026-11-13: go, learn, intake and scout load on their own now (the owner talks
# from a phone and does not type slash commands), so their descriptions are always on, about 1500 chars.
ALWAYS_ON_BUDGET = {"kit": 4200, "kit-ui": 1300, "kit-llm": 1200}
MAX_DESCRIPTION = 1024
SUBAGENT_LESSONS = 2400  # about 600 tokens, injected into every kit:implementer and kit:verifier
SESSION_LESSONS = 1600  # about 400 tokens, added to the session start text
# the coordinator line session_start.py prints in a kit project (start and compaction); its length
# comes out of SESSION_LESSONS, so this cap keeps most of that room for the lessons
COORDINATOR_MAX = 450
MAX_SKILL_LINES = 150
MAX_AGENT_LINES = 80
MAX_REFERENCE_LINES = 200
SHOUTED = re.compile(r"\b(MUST|NEVER|CRITICAL|IMPORTANT|ALWAYS)\b")
# a quoted mention ("think step by step" named as an anti-pattern) is not a request
REASONING = re.compile(r"(?<![\"'`(])\b(?:(?:show|write|share|explain|print)(?: out| me)? (?:your|its|the) "
                       r"(?:reasoning|thinking|thought process|chain of thought)|think (?:out loud|aloud|step[ -]by[ -]step))\b", re.I)
REFERENCE = re.compile(r"(?<![\w/.-])(kit(?:-ui|-llm)?):([a-z][a-z0-9-]*)")
# files that describe the past (removed pieces are named there on purpose)
HISTORY = {"CATALOG.md"}


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    fields = {}
    for line in m.group(1).splitlines():
        if re.match(r"^[A-Za-z][\w-]*:", line):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, text


HOOK_SCRIPT = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s]+)")
# a home folder with a real-looking user name: /Users/<name>/ or /home/<name>/ where <name> is a
# literal word. Placeholders pass: a name in PLACEHOLDER_USERS (the tests' /home/u/, a docstring's
# /Users/me/), or one written as <name>, $USER or ${USER} (never matched: the name may not start
# with <, $ or {).
PERSONAL_PATH = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]+)/")
PLACEHOLDER_USERS = {"u", "me", "user", "you", "name", "example"}
# zero-width space, non-joiner, joiner, word joiner, byte order mark (anywhere: a leading one also
# hides the frontmatter), the bidirectional embeddings and overrides U+202A-U+202E and the
# isolates U+2066-U+2069: they change what a reader sees without changing what the model reads
HIDDEN = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u202a-\u202e\u2066-\u2069]")


def packaging(root):
    """Packaging mistakes under root/plugins, as failure lines: a hooks.json command naming a script
    that is not there, a personal absolute path, hidden Unicode in a file the model reads."""
    problems, plugins = [], root / "plugins"
    for hooks in sorted(plugins.glob("*/hooks/hooks.json")):
        plugin = hooks.parent.parent
        try:
            entries = json.loads(hooks.read_text(encoding="utf-8")).get("hooks", {})
        except ValueError as error:
            problems.append(f"{hooks.relative_to(root)}: not valid JSON ({error})")
            continue
        for event, groups in entries.items():
            for group in groups:
                for hook in group.get("hooks", []):
                    for rel in HOOK_SCRIPT.findall(str(hook.get("command") or "")):
                        if not (plugin / rel).is_file():
                            problems.append(f"{hooks.relative_to(root)}: {event} runs ${{CLAUDE_PLUGIN_ROOT}}/{rel}, "
                                            "which does not exist")
    for path in sorted(plugins.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # an image or other binary file
        rel = path.relative_to(root)
        for m in PERSONAL_PATH.finditer(text):
            if m.group(1) not in PLACEHOLDER_USERS:
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{rel}:{line}: personal path '{m.group(0)}'; use ~ or a placeholder such as /home/u/")
    readable = sorted(plugins.glob("*/skills/*/*.md")) + sorted(plugins.glob("*/skills/*/references/*.md")) \
        + sorted(plugins.glob("*/agents/*.md"))
    for path in readable:
        text = path.read_text(encoding="utf-8")
        for m in HIDDEN.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"{path.relative_to(root)}:{line}: hidden character U+{ord(m.group(0)):04X}")
    return problems


def packaging_self_test():
    """Each packaging check, on a temp copy of plugins/ with one planted mistake, reports it."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp)
        shutil.copytree(PLUGINS, copy / "plugins", ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        hooks = copy / "plugins" / "kit" / "hooks" / "hooks.json"
        data = json.loads(hooks.read_text(encoding="utf-8"))
        data["hooks"].setdefault("Stop", []).append({"hooks": [{"type": "command",
                                                     "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/gone.py"'}]})
        hooks.write_text(json.dumps(data), encoding="utf-8")
        (copy / "plugins" / "kit" / "hooks" / "scripts" / "note.py").write_text("# see /Users/" + "jane/code/app\n")
        skill = next((copy / "plugins").glob("*/skills/*/SKILL.md"))
        skill.write_text(skill.read_text(encoding="utf-8") + "\nrun the gate\u202e first\u200b\n", encoding="utf-8")
        found = packaging(copy)
        for want in ("hooks/scripts/gone.py, which does not exist", "personal path '/Users/jane/'",
                     "hidden character U+202E", "hidden character U+200B"):
            if not any(want in line for line in found):
                problems.append(f"packaging self-test: a planted mistake went unseen ({want}); got {found}")
        personal = [line for line in found if "personal path" in line]
        if len(personal) != 1:  # only the planted one: the placeholders (/home/u/, /Users/me/) pass
            problems.append(f"packaging self-test: one personal path expected, got {personal}")
    return problems


def without_code(text):
    return re.sub(r"```.*?```", "", text, flags=re.S)


def main():
    problems = []
    names = {}  # plugin -> set of skill and agent names
    for plugin in sorted(p for p in PLUGINS.iterdir() if (p / ".claude-plugin" / "plugin.json").is_file()):
        names[plugin.name] = {p.parent.name for p in plugin.glob("skills/*/SKILL.md")}
        names[plugin.name] |= {p.stem for p in plugin.glob("agents/*.md")}
        always_on = 0
        for path in sorted(plugin.glob("skills/*/SKILL.md")) + sorted(plugin.glob("agents/*.md")):
            rel = path.relative_to(ROOT)
            fields, text = frontmatter(path)
            if fields is None or "description" not in fields or "name" not in fields:
                problems.append(f"{rel}: frontmatter needs name and description")
                continue
            desc = fields["description"]
            if len(desc) > MAX_DESCRIPTION:
                problems.append(f"{rel}: description is {len(desc)} chars (max {MAX_DESCRIPTION})")
            if desc[:1] not in "\"'" and (": " in desc or " #" in desc):
                problems.append(f"{rel}: description has ': ' or ' #', which breaks a plain YAML scalar")
            if fields.get("disable-model-invocation") != "true":
                always_on += len(desc)
            lines = text.count("\n")
            limit = MAX_AGENT_LINES if path.parent.name == "agents" else MAX_SKILL_LINES
            if lines > limit:
                problems.append(f"{rel}: {lines} lines (max {limit}); move detail to a file next to it")
        budget = ALWAYS_ON_BUDGET.get(plugin.name, 1200)
        if always_on > budget:
            problems.append(f"plugins/{plugin.name}: always-on descriptions are {always_on} chars (budget {budget})")
        print(f"{plugin.name}: always-on descriptions {always_on}/{budget} chars")
        for path in sorted(plugin.glob("skills/*/*.md")) + sorted(plugin.glob("skills/*/references/*.md")):
            if path.name != "SKILL.md" and path.read_text(encoding="utf-8").count("\n") > MAX_REFERENCE_LINES:
                problems.append(f"{path.relative_to(ROOT)}: over {MAX_REFERENCE_LINES} lines")

    for path in sorted(PLUGINS.glob("*/hooks/**/*.py")):
        if "tests" in path.parts:
            continue
        for m in REASONING.finditer(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(ROOT)}: asks for the model's reasoning ('{m.group(0)}')")
    core_hooks = json.loads((PLUGINS / "kit" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    if "UserPromptSubmit" in core_hooks:
        problems.append("plugins/kit/hooks/hooks.json: a UserPromptSubmit hook adds work and text to every prompt")
    for entry in core_hooks.get("PostToolUse", []) + core_hooks.get("PreToolUse", []):
        if not entry.get("matcher"):
            problems.append("plugins/kit/hooks/hooks.json: a tool hook without a matcher runs on every tool call")

    lessons = re.search(r"^MAX_CHARS = (\d+)", (PLUGINS / "kit" / "hooks" / "scripts" / "subagent_start.py")
                        .read_text(encoding="utf-8"), re.M)
    if not lessons or int(lessons.group(1)) > SUBAGENT_LESSONS:
        problems.append(f"plugins/kit/hooks/scripts/subagent_start.py: MAX_CHARS over {SUBAGENT_LESSONS}")
    session = re.search(r"^SESSION_LESSONS = (\d+)", (PLUGINS / "kit" / "hooks" / "scripts" / "session_start.py")
                        .read_text(encoding="utf-8"), re.M)
    if not session or int(session.group(1)) > SESSION_LESSONS:
        problems.append(f"plugins/kit/hooks/scripts/session_start.py: SESSION_LESSONS over {SESSION_LESSONS}")
    sys.path.insert(0, str(PLUGINS / "kit" / "hooks" / "scripts"))
    import session_start  # noqa: E402 (standard library only, nothing runs on import)
    if len(session_start.COORDINATOR) > COORDINATOR_MAX:
        problems.append(f"plugins/kit/hooks/scripts/session_start.py: COORDINATOR is {len(session_start.COORDINATOR)} "
                        f"chars (max {COORDINATOR_MAX})")

    docs = [p for p in PLUGINS.rglob("*.md") if "evals" not in p.parts]
    docs += [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))
    for path in docs:
        if path.name in HISTORY or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        if "skills" in path.parts or "agents" in path.parts:
            for m in SHOUTED.finditer(without_code(text)):
                problems.append(f"{rel}: shouted '{m.group(1)}'; say it calmly and give the reason")
            for m in REASONING.finditer(without_code(text)):
                problems.append(f"{rel}: asks for the model's reasoning ('{m.group(0)}'); ask for the result and its evidence")
        for m in REFERENCE.finditer(text):
            plugin, name = m.group(1), m.group(2)
            if name not in names.get(plugin, set()):
                problems.append(f"{rel}: '{plugin}:{name}' names no skill or agent")

    problems += packaging(ROOT) + packaging_self_test()

    for p in problems:
        print("FAIL " + p)
    if problems:
        return 1
    print("budget: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
