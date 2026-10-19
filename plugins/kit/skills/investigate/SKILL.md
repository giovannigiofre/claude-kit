---
name: investigate
description: Finds and fixes the root cause of any reported failure - backend, cloud/production, frontend/browser, CI/build, data pipeline, third-party integration, performance. Use when the user reports an error, a stack trace, a failing test, a broken page, a failed job or deploy, wrong output, or says something "doesn't work" / "stopped working" and wants it fixed, including when the logs or dashboards are reachable only by the user. Runs evidence intake (asks once, with exact export steps), reproduction, falsifiable hypotheses, a regression-tested fix and independent verification.
argument-hint: "[the symptom, error or failing command]"
---

# /kit:investigate: evidence first, then the root cause, then a verified fix

Symptom: $ARGUMENTS (if empty, the failure the conversation is about).

**Iron law: no fix without a confirmed root cause, and no "fixed" without evidence from where it
failed.** The debugging discipline is `kit:systematic-debugging` (vendored from obra/superpowers):
load it and follow its four phases. This skill adds what it leaves open: getting the evidence
when only the user can reach it, reading large log exports without flooding context, the kit's
agents and gates, and closing the loop. (Method sources at the end.)

**LLM behaviour is different.** If the "bug" is answer quality of an LLM feature (wrong, worse or
inconsistent answers, a judge score dropped), use `kit:llm-evals` first: a prompt change without
a measure is the failure mode, not the fix. Use this skill for LLM code that crashes, times out
or returns malformed output.

## 0. Frame

- One line in `.debug/NOTES.md`: *expected X, got Y, when Z* (who, where, since when).
- Name the **failure surface(s)**: local/tests, backend/cloud, frontend/browser, CI/build,
  data/LLM pipeline, third-party integration, performance. For each, open its section in
  [references/evidence-by-surface.md](references/evidence-by-surface.md).
- **Users affected right now?** Propose mitigation first (rollback, revert, feature flag) and ask
  before touching production. Root cause after.
- Make sure `.debug/` is gitignored before anything lands there: exports carry PII and secrets.
  `.debug/NOTES.md` is the audit trail (hypotheses, checks, results); at phase boundaries also
  bring the kit handoff note (`.claude/handoff.md`) up to date.

## 1. Evidence

1. **Collect yourself first** what is reachable: run the failing command or test, read the whole
   stack trace, `git log -20 --oneline`, `git diff` against the last known-good, lockfile, config
   and env changes, logs or consoles through any connected CLI, MCP server or browser tool.
2. **Then ask the user once.** One batched request (AskUserQuestion for choices, a numbered
   checklist for exports), only for what you could not get. Every item comes with click-level
   steps from the surface reference: what to open, which filter or query to paste (filled in
   with the real names and times), which format, where to put the file (`.debug/` or attached
   in chat). Always include:
   - when it started, the last time it worked, what changed around then;
   - always, intermittent, or only some users, inputs, environments;
   - one identifier of a failing instance (request, trace or run ID, timestamp, URL, user);
   - **the same export for a working instance**, to compare.
   GCP with console-only access: [references/gcp-logs-manual-export.md](references/gcp-logs-manual-export.md).
3. **Never read raw exports.** Compact them:
   `python3 ${CLAUDE_SKILL_DIR}/scripts/compact_logs.py .debug/fail.json --diff .debug/ok.json`
   (JSON, NDJSON, CSV, plain text; stdlib only). Read its summary, then drill down with
   `--trace`, `--grep`, `--min-severity`, `--window`. If `${CLAUDE_SKILL_DIR}` is not
   substituted, the script is in `scripts/` next to this file.
4. Evidence the user cannot give: carry on, and write the gap in NOTES and in the final report.

## 2. Reproduce and localize

- Repro ladder, best first: an automated failing test, a one-off script, exact manual steps (you
  drive the browser if browser tools are connected), the narrowed production evidence.
- Flaky: run it at least 3 times; failing 2 of 3 means it is real. See
  `${CLAUDE_SKILL_DIR}/../systematic-debugging/condition-based-waiting.md` and, for
  tests that leave state behind, `${CLAUDE_SKILL_DIR}/../systematic-debugging/find-polluter.sh`.
- Localize with the cheapest technique that halves the search space:
  `${CLAUDE_SKILL_DIR}/../systematic-debugging/root-cause-tracing.md` (trace the bad value
  back to its origin), plus good-vs-bad diff, boundary instrumentation, `git bisect run` and
  input minimization in [references/techniques.md](references/techniques.md).
- Phase output: the component, and ideally the line, where behaviour departs from expectation.

## 3. Hypotheses

- 1-3 falsifiable hypotheses in NOTES: *"Root cause is X because evidence Y; if true, Z must
  also hold."* For each, the cheapest check that could **disprove** it. Predict, run, record.
- Stuck after step 2, or two or more plausible causes across layers: **competing hypotheses**.
  One Explore agent per hypothesis, launched in one message, each briefed with the symptom, the
  evidence files and "find confirming AND refuting evidence, cite file:line or log lines, give a
  confidence". Arbitrate on the least inconsistent evidence, not the most plausible story
  ([references/techniques.md](references/techniques.md)).
- Nothing confirmed: write "I don't understand X yet" and go back to step 1 with a sharper
  request. Never guess a fix.

## 4. Fix

1. A failing test (or script) that reproduces the bug. Run it, see it fail for the right reason.
2. One fix at the root cause: no "while I'm here" edits, no bundled refactor. Called from
   `kit:lead`, or a fix that spans several areas: brief a `kit:implementer` with the root cause,
   the regression test and the done-criterion below.
3. The test passes; the project's `check` from `.claude/kit.json` passes.
4. It did not work: revert it and go back to step 2 with what you learned. Never stack fixes.
5. **Three failed fixes: stop.** The model of the problem, or the architecture, is wrong. Show
   NOTES to the user and decide together before attempt four (same limit as `kit:lead`).
6. Optional, after the real fix: defense in depth at the boundary where the bad value entered
   (`${CLAUDE_SKILL_DIR}/../systematic-debugging/defense-in-depth.md`).

## 5. Verify and close

- **Done-criterion:** the regression test fails without the fix and passes with it, the
  project's `verify` passes, and the original signature is gone where it failed.
- Send the change to `kit:verifier` with that done-criterion and the root-cause evidence. Never
  report your own "fixed"; follow `kit:verification-before-completion`.
- Where only the user can see the failing environment (a production dashboard, their device),
  say exactly what to re-check after the deploy (the same query or steps as in step 1) and what
  "fixed" looks like (signature gone, status 200, the run succeeds). Until they confirm, report
  it as verified locally, not in production.
- Remove temporary instrumentation, or keep it on purpose as structured logging.
- Report from NOTES:

```
SYMPTOM: <one line>
ROOT CAUSE: <what, where (file:line) - the evidence that proves it>
FIX: <what changed and why it removes the cause>
REGRESSION TEST: <name - fails before, passes after>
VERIFIED: <verifier verdict + gate lines; production: confirmed by the user | pending>
NOT VERIFIED / RISK: <gaps, evidence the user could not provide>
```

- A non-obvious cause, or a correction from the user: finish with `/kit:learn`. A debugging
  rule a machine can enforce (a lint, a check) belongs in `.claude/kit.json`. Then offer
  `/kit:go`.

## Red flags: stop and go back to step 1

- "Let me just try changing X", or several changes and then a test run.
- A fix proposed before reading the path from input to failure.
- "Probably flaky", "probably the cache", with nothing checked.
- Asking the user for something you could fetch yourself, or asking in several rounds.
- Reading a raw log export instead of compacting it.
- "One more attempt" after two failed fixes.

## Sources

obra/superpowers `systematic-debugging` (vendored here: iron law, phases, boundary
instrumentation, three-fix rule); garrytan/gstack `/investigate` (the name, which avoids the
built-in `/debug`); wshobson/agents `parallel-debugging` (competing hypotheses); Anthropic,
Claude Code best practices (a failing test first, a check Claude can run); David J. Agans,
*Debugging: The 9 Indispensable Rules* (make it fail, quit thinking and look, keep an audit
trail, if you didn't fix it it ain't fixed). Details in CATALOG.md.
