#!/usr/bin/env python3
"""SessionStart: tell Claude which kit gates this project has, make the user the git author when
kit.json names them, offer the kit's machine settings once (not in a cloud container, whose
~/.claude is ephemeral: CLAUDE_CODE_REMOTE=true), re-apply the user's approved per-repo auto
mode lines to user settings, import new memories into the kit's lesson ledger and hand the main
session its lessons, the news of what the kit changed in them and, every lessons.REVIEW_DAYS, a
line that the lesson review is due (lessons.py), move an older project's kit state out of
.claude/ into .kit/ when nothing is at work (migrate_state.py: one line when it moves, one with
the reason when it waits), and after a compaction put the coordinator's board back into context
(stdout is added to context).

In a kit project every interactive start, and every compaction, also prints COORDINATOR: this
session is the project's coordinator (kit:lead), routed by this hook rather than by the kit mod,
which a cloud session or Remote Control may not load. `"mode": "light"` in the personal kit.json
(~/.claude/kit.json) is the one off switch; a headless run (KIT_HEADLESS) and a subagent get none.

A kit.json that exists is the opt-in, even `{}`: the "kit harness active" line is always printed
then, with one line per key the kit does not know (and the closest known key), one per key of
the wrong type, and one when items on disk are still `queued`."""

import difflib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import machine_setup  # noqa: E402

SESSION_LESSONS = 1600  # about 400 tokens of the ledger's lessons for the main session
MAX_BOARD_CHARS = 8000  # the contract's size: a board within it comes back whole
BOARD_LINES, BOARD_BYTES = 60, 8000  # the board's contract (kit:lead)
# every key a kit script, the mod or a skill reads, per section (docs/reference.md)
KNOWN_KEYS = {
    "": ("check", "verify", "checkTimeout", "verifyTimeout", "maxStopRetries", "onEdit", "protect", "guard",
         "watchdog", "llm", "learn", "author", "lead"),
    "lead": ("board", "notes", "read", "backlog", "ship", "merge", "parallel", "budget", "loops"),
    "guard": ("protectedBranches", "agentsAsk", "agentsDeny", "allowCommands", "denyCommands", "askCommands",
              "attribution", "waits", "sleepMaxSec", "retries"),
    "watchdog": ("silentMin", "bashDeadlineMin", "permissionMin"),
    "learn": ("model",),
}
TYPED_KEYS = {"check": (str, "a string (the shell command)"), "verify": (str, "a string (the shell command)"),
              "protect": (list, "a list of rules"), "onEdit": (list, "a list of rules")}
MAX_NOTES = 8
# The one routing line. Until 2026-11 the kit mod added it to every prompt in "loop mode"; a cloud
# session without the mod then had no coordinator, no threads and no push. Printed at start and
# after a compaction (when the skill's rules may be gone), within the session-start budget: the
# lessons get what it leaves of SESSION_LESSONS.
COORDINATOR = (
    "kit: this session coordinates this project. Handle each message with the kit:lead skill (load it "
    "before your first answer, and again after a compaction): answer a question in place, make a change "
    "of a handful of tool calls yourself, start background threads for the rest. Send one "
    "PushNotification when an item becomes ready for review or needs the user, and when an unattended "
    "run ends; none for progress.")


def config_notes(config):
    """One line per kit.json key the kit does not read (a typo stays silent otherwise) with the
    closest known key, and one per key whose value has the wrong type."""
    notes = []
    for section, known in KNOWN_KEYS.items():
        value = config if section == "" else config.get(section)
        if not isinstance(value, dict):
            continue
        prefix = section + "." if section else ""
        for key in value:
            if key in known:
                continue
            close = difflib.get_close_matches(str(key), known, n=1, cutoff=0.6)
            hint = f" (did you mean `{prefix}{close[0]}`?)" if close else ""
            notes.append(f"- unknown key `{prefix}{key}` in .claude/kit.json{hint}: the kit ignores it")
    for key, (kind, want) in TYPED_KEYS.items():
        if key in config and not isinstance(config[key], kind):
            notes.append(f"- `{key}` in .claude/kit.json should be {want}; it is ignored")
    if len(notes) > MAX_NOTES:
        notes = notes[:MAX_NOTES] + [f"- ... and {len(notes) - MAX_NOTES} more key(s) to check in .claude/kit.json"]
    return notes


def asking_line(root):
    """One line when a permission rule asks before the git steps a kit project runs all day. In
    Ciaoguest (2026-11-13) a committed `Bash(git push*)`, `Bash(git rebase *)` and `Bash(gh pr
    merge*)` made 50 prompts in a day on the owner's phone, four of them left unanswered for 20
    minutes each at night, and nothing told the owner the rules were the cause."""
    try:
        asking = kitlib.asking_rules(root)
    except Exception:
        return []
    if not asking:
        return []
    main = kitlib.main_checkout(root) or root
    seen = {}
    for found in asking.values():
        for rule, where in found:
            try:
                where = Path(where).relative_to(main)
            except (TypeError, ValueError):
                pass
            seen.setdefault(str(where), [])
            if rule not in seen[str(where)]:
                seen[str(where)].append(rule)
    which = "; ".join(", ".join(f"`{r}`" for r in rules[:4]) + f" in {where}" for where, rules in seen.items())
    return [f"- permission rules ask before every {', '.join(asking)} here ({which}): each one stops on a prompt "
            "for the owner, in auto mode and from a thread too, and an allow rule cannot override it. So run each "
            "such step once, in one command with its clean-up; never repeat one that is waiting on a prompt or was "
            "not answered (hand it back as `needs push`). The first time one of these prompts comes up in this "
            "session, tell the owner in one line that these rules are why, and ask once whether to change them "
            "(lead/unattended.md step 3: `items.py unattended --proposal` prints the diff)."]


def queued_line(root):
    """Items on disk nothing shows yet (a hand-off, a taken proposal) until the lead takes them."""
    try:
        import items
        queued = items.list_items(root, "queued")
    except Exception:
        return ""
    if not queued:
        return ""
    script = Path(__file__).resolve().parent / "items.py"
    return f"- {len(queued)} queued item(s) on disk: python3 \"{script}\" list --status queued"


def coordinator_line(data):
    """COORDINATOR, or "" in a headless run, a subagent, or with the personal `"mode": "light"`."""
    if os.environ.get("KIT_HEADLESS") or data.get("agent_id") or kitlib.personal_mode() == "light":
        return ""
    return COORDINATOR


def as_list(config, key):
    return config.get(key) if isinstance(config.get(key), list) else []


def read_board(root, config):
    """(the board's path as configured, its text) or (rel, "") when there is none."""
    path = kitlib.board_file(root, config)  # .kit/lead/board.md, .claude/lead/ before the move
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = str(path)
    try:
        return rel, path.read_text(encoding="utf-8").strip()
    except Exception:
        return rel, ""


def board_warning(text):
    """A line when the board is past its contract, else ""."""
    lines, size = text.splitlines(), len(text.encode("utf-8"))
    if len(lines) <= BOARD_LINES and size <= BOARD_BYTES:
        return ""
    return (f"kit: the board is {len(lines)} lines, {size // 1000} KB, over its {BOARD_LINES}-line, "
            f"{BOARD_BYTES // 1000} KB contract: archive done rows (items.py done <id>), keep RULES to "
            "standing rules and move dated decisions to DECISIONS.md beside the board.")


def print_board(root, config):
    """After a compaction, the board is the coordinator's memory of every thread it started.
    NEEDS YOU and the rows come first, RULES last and cut first."""
    rel, text = read_board(root, config)
    if not text:
        return
    lines = text.splitlines()
    rules = [ln for ln in lines if ln.startswith("RULES:")]
    first = [ln for ln in lines if ln.startswith(("SHIP:", "NEEDS YOU:"))]
    rest = [ln for ln in lines if ln not in rules and ln not in first]
    body = "\n".join(first + rest)
    if len(body) > MAX_BOARD_CHARS:
        body = body[:MAX_BOARD_CHARS - 40] + " ... (cut: rows over the board budget)"
    room = MAX_BOARD_CHARS - len(body) - 1
    for ln in rules:
        if room > 40:
            cut = ln if len(ln) <= room else ln[:room - 40] + " ... (cut: RULES over the board budget)"
            body += "\n" + cut
            room -= len(cut) + 1
    print(f"kit: the conversation was just compacted. The coordinator's board ({rel}):\n{body}\n")
    if board_warning(text):
        print(board_warning(text))


def ensure_author(root, config):
    """kit.json `author` ("Name <email>") is who commits in this project. When git's identity in
    the checkout is missing or an AI's (a cloud container's default), set the repo's own config to
    it, so every commit, the threads' included (worktrees share it), carries the user's name."""
    author = config.get("author") if isinstance(config, dict) else None
    m = re.match(r"^\s*(.+?)\s*<([^<>@\s]+@[^<>\s]+)>\s*$", author or "")
    if not m:
        return None
    name, email = m.group(1), m.group(2)
    _, current_name = kitlib.run_shell("git config user.name", root, timeout=10)
    _, current_email = kitlib.run_shell("git config user.email", root, timeout=10)
    current_name, current_email = current_name.strip(), current_email.strip()
    is_ai = current_name.lower() in ("claude", "claude code", "claude[bot]") or \
        current_email.lower().endswith("anthropic.com")
    if (current_name and current_email and not is_ai) or (current_name, current_email) == (name, email):
        return None
    code_n, _ = kitlib.run_shell(f"git config user.name {quote(name)}", root, timeout=10)
    code_e, _ = kitlib.run_shell(f"git config user.email {quote(email)}", root, timeout=10)
    if code_n or code_e:
        return None
    was = f"{current_name} <{current_email}>" if current_name or current_email else "unset"
    return f"- git author for this repo set to {name} <{email}> (kit.json author; was {was})"


def quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def offer_machine_setup():
    """Until the user says yes or no on this machine, ask Claude to offer the kit's user settings."""
    todo = machine_setup.pending()
    if not todo:
        return
    script = Path(__file__).resolve().parent / "machine_setup.py"
    print("kit: this machine's ~/.claude/settings.json is missing the kit's settings:\n"
          + "\n".join(f"  - {line}" for line in todo) + "\n"
          "Before the user's first request, explain this in two or three plain lines (what changes, "
          "why: they are the only author of commits and PRs; agents may rewrite only the branches "
          "they created) and ask once with AskUserQuestion, header \"Kit setup\": apply them "
          f"(Recommended) or not. Yes: run `python3 \"{script}\" --apply`. No: run "
          f"`python3 \"{script}\" --decline`. Then carry on with the request. Without "
          "AskUserQuestion (a headless run), ignore this.")


def away_back(data):
    """The owner is back: an interactive start (not headless, not a subagent, not a compaction) takes
    away the denyInsteadOfPrompting the kit set when he left (kitlib.away_on)."""
    if os.environ.get("KIT_HEADLESS") or data.get("agent_id") or data.get("source") not in ("startup", "resume"):
        return None
    try:
        if kitlib.away_state()[0] != "kit":
            return None
        kitlib.away_off()
    except Exception as exc:
        return f"kit: away could not be turned off ({exc}); run `items.py away off`."
    return "kit: away is off again (it was on while the user was away): permission prompts ask again."


def old_unattended(root):
    """The mod's `/kit-safety unattended on` (until 2026-11) left denyInsteadOfPrompting in the
    project's settings.local.json, where it outlived the evening it was for. Remove it, once."""
    path = Path(root) / ".claude" / "settings.local.json"
    settings, ok = kitlib.read_json(path)
    perms = (settings or {}).get("permissions") if ok else None
    if not isinstance(perms, dict) or kitlib.AWAY_KEY not in perms:
        return None
    perms.pop(kitlib.AWAY_KEY)
    if not perms:
        settings.pop("permissions")
    kitlib.write_json_atomic(path, settings)
    return (f"kit: removed permissions.{kitlib.AWAY_KEY} from {path}, left there by the old "
            "/kit-safety unattended. Away is now `items.py away on`, which the next session start undoes. "
            "Tell the user this once.")


def version_key(version):
    """'1.10.0' sorts after '1.9.2'; anything unparsable sorts first."""
    try:
        return tuple(int(part) for part in str(version).split("."))
    except ValueError:
        return ()


def update_notice(session_id):
    """When a newer kit is installed than the one this session runs (an update while Claude Code
    was open keeps the old hooks and skills loaded), say so once per session and version."""
    plugin = Path(__file__).resolve().parents[2]
    try:
        loaded = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        registry = json.loads((kitlib.config_dir() / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        installed = [entry.get("version") for entries in registry.get("plugins", {}).values()
                     for entry in entries if isinstance(entry, dict) and entry.get("installPath")
                     and Path(entry["installPath"]).resolve().parent == plugin.parent]
    except Exception:
        return None  # a dev checkout (--plugin-dir) or an unknown registry format: nothing to say
    newer = max((v for v in installed if version_key(v) > version_key(loaded)), key=version_key, default=None)
    if not newer or kitlib.load_state(session_id, "kit-version").get("announced") == newer:
        return None
    kitlib.save_state(session_id, "kit-version", {"announced": newer})
    line = f"kit updated to {newer}: when you're at the Mac, /reload-plugins (or a restart) loads it; this session runs {loaded} until then."
    if os.environ.get("CLAUDE_CODE_BRIDGE_SESSION_ID"):  # Remote Control: the user is on the phone
        return line + " Tell the user this line once, at the end of a reply, and carry on: nothing waits on it."
    return line + " Tell the user this line once; nothing waits on it."


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, err = kitlib.load_config(root)
    if data.get("source") == "compact":
        print_board(root, config)
    elif not os.environ.get("KIT_HEADLESS") and os.environ.get("CLAUDE_CODE_REMOTE", "").lower() not in ("1", "true"):
        offer_machine_setup()  # a cloud container's ~/.claude does not outlive the session: nothing to set up
    back = away_back(data)
    if back:
        print(back)
    if err:
        print(err)
        return 0
    if config is None:
        return 0  # project has not opted in: stay silent
    coordinator = coordinator_line(data)
    if coordinator:
        print(coordinator)
    if data.get("source") != "compact":  # not mid-session: the coordinator may be using the board
        try:  # an older project's state leaves .claude/, where every write by a thread asked the owner
            import migrate_state
            for line in migrate_state.auto(root):
                print(line)
        except Exception as exc:
            print(f"kit: moving the kit's state to .kit/ skipped: {exc}")
        try:
            migrated = old_unattended(root)
        except Exception as exc:
            migrated = f"kit: could not tidy settings.local.json: {exc}"
        if migrated:
            print(migrated)
    if data.get("source") != "compact":  # after a compaction print_board says it
        warning = board_warning(read_board(root, config)[1])
        if warning:
            print(warning)
    notice = update_notice(data.get("session_id"))
    if notice:
        print(notice)
    try:  # silent unless something changed or is wrong; never breaks session start
        import auto_mode_sync
        for line in auto_mode_sync.sync():
            print(line)
    except Exception as exc:
        print(f"kit: auto mode sync skipped: {exc}")
    lines = ["kit harness active for this project (.claude/kit.json):"]
    author_line = ensure_author(root, config)
    if author_line:
        lines.append(author_line)
    if isinstance(config.get("check"), str) and config["check"]:
        lines.append(f"- fast check (runs automatically before you stop): {config['check']}")
    if isinstance(config.get("verify"), str) and config["verify"]:
        lines.append(f"- full verify (the gate for finished work): {config['verify']}")
    for rule in as_list(config, "protect"):
        if isinstance(rule, dict):
            lines.append(f"- protected: {rule.get('glob')} ({rule.get('mode', 'read-only')}) {rule.get('reason', '')}")
    if as_list(config, "onEdit"):
        lines.append("- onEdit commands run after each edit of: "
                     + ", ".join(r.get("glob", "?") if isinstance(r, dict) else "?" for r in config["onEdit"]))
    lead = config.get("lead") or {}
    if isinstance(lead, dict) and lead.get("notes"):
        lines.append(f"- lead notes: {lead['notes']}")
    lines.extend(config_notes(config))
    lines.extend(asking_line(root))
    queued = queued_line(root)
    if queued:
        lines.append(queued)
    print("\n".join(lines))  # the header always: a kit.json of only unknown keys must not look like silence
    sys.stdout.flush()  # the gate lines stand even if the lessons run out of time
    for line in learned(root, len(coordinator)):
        print(line)
    return 0


def learned(root, reserved=0):
    """Import new memories into the ledger; then what the kit changed and this repo's lessons for
    the main session, together with the `reserved` chars of the coordinator line within
    SESSION_LESSONS."""
    try:
        import lessons
        lessons.LOCK_WAIT = 1.0  # within the hook's timeout, with the gate lines already printed
        lessons.harvest(root)
        news = lessons.take_news(root)
        block = "\n".join(t for t in (news_block(news), lessons.review_due(root)) if t)
        text = lessons.deliver(root, "lead", SESSION_LESSONS - reserved - len(block))
    except Exception:
        return []  # lessons are a help, never a reason for a session not to start
    return [t for t in (text, block) if t]


def news_block(news):
    """What the kit changed, within half the session budget (the rest: /kit:learn news)."""
    if not news:
        return ""
    lines = ["kit changed its lessons for this repo (tell the user these lines once, briefly):"]
    for i, line in enumerate(news):
        more = f"- ... and {len(news) - i} more: /kit:learn news"
        if len("\n".join(lines + [f"- {line}", more])) > SESSION_LESSONS // 2:
            lines.append(more)
            break
        lines.append(f"- {line}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
