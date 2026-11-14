---
name: investigate
description: Finds and fixes the root cause of a reported failure - an error, stack trace, failing test, broken page, failed job or deploy, wrong output, something that "stopped working" - in any layer (backend, cloud, frontend, CI, data, integrations, performance), including when only the user can reach the logs. Gets the evidence, reproduces, tests hypotheses, lands a regression-tested fix.
argument-hint: "[the symptom, error or failing command]"
---

# /kit:investigate: evidence first, then the root cause, then a verified fix

Symptom: $ARGUMENTS (if empty, the failure the conversation is about).

No fix before a confirmed root cause, and no "fixed" without evidence from where it failed: a
fix for a guessed cause tends to move the bug, and a green unit test proves nothing about the
page or job the user saw. The phases below are evidence, reproduction, hypotheses, fix,
verification; this skill adds what generic debugging advice leaves open: getting evidence only
the user can reach, reading large log exports without flooding context, and closing the loop.
(Method sources at the end.)

**LLM behaviour is different.** If the "bug" is answer quality of an LLM feature (wrong, worse or
inconsistent answers, a judge score dropped), use `kit-llm:llm-evals` first (offered through `kit:extras` if this project lacks it): a prompt change without
a measure is the failure mode, not the fix. Use this skill for LLM code that crashes, times out
or returns malformed output.

## 0. Frame

- One line in `.debug/NOTES.md`: *expected X, got Y, when Z* (who, where, since when).
- Name the **failure surface(s)**: local/tests, backend/cloud, frontend/browser, CI/build,
  data/LLM pipeline (an LLM feature that got worse has its own section), third-party integration, performance. For each, open its section in
  [references/evidence-by-surface.md](references/evidence-by-surface.md).
- **Users affected right now?** Propose mitigation first (rollback, revert, feature flag) and ask
  before touching production. Root cause after.
- Make sure `.debug/` is gitignored before anything lands there: exports carry PII and secrets.
  `.debug/NOTES.md` is the audit trail (hypotheses, checks, results), and what survives a
  compaction.

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

- Reproduce it end to end first, as close as possible to how the user met it: the page in a
  browser (you drive it if browser tools are connected), the CLI command, the API call, the job
  run. Then pin it with the narrowest automated test. A unit test written from your reading of
  the code can pass while the user's failure remains.
- Repro ladder, best first: an automated failing test that goes through the same path the user
  takes, a one-off script, exact manual steps, the narrowed production evidence.
- Flaky: run it at least 3 times; failing 2 of 3 means it is real. Waiting on a condition
  instead of a time, and finding the test that leaves state behind, are in
  [references/techniques.md](references/techniques.md).
- Localize with the cheapest technique that halves the search space: tracing the bad value back
  to its origin, good-vs-bad diff, boundary instrumentation, `git bisect run`, input
  minimization ([references/techniques.md](references/techniques.md)).
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
2. One fix at the root cause: no "while I'm here" edits, no bundled refactor.
3. The test passes; the project's `check` from `.claude/kit.json` passes.
4. It did not work: revert it and go back to step 2 with what you learned. Never stack fixes.
5. **Three failed fixes: stop.** The model of the problem, or the architecture, is wrong. Show
   NOTES to the user and decide together before attempt four.
6. Optional, after the real fix: one validation at the boundary where the bad value entered
   ([references/techniques.md](references/techniques.md)).

## 5. Verify and close

- **Done-criterion:** the regression test fails without the fix and passes with it, the
  project's `verify` passes, and the original signature is gone where it failed.
- For a risky fix (shared code, data, money, auth), have `kit:verifier` review it in a fresh
  context with that done-criterion and the root-cause evidence.
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
VERIFIED: <gate lines, reviewer verdict if any; production: confirmed by the user | pending>
NOT VERIFIED / RISK: <gaps, evidence the user could not provide>
```

- A non-obvious cause, or a correction from the user: run `kit:learn` yourself, which prefers a
  check a machine runs (a lint, a test, `.claude/kit.json`) over a sentence. Then offer `/kit:go`.

## Red flags: stop and go back to step 1

- "Let me just try changing X", or several changes and then a test run.
- A fix proposed before reading the path from input to failure.
- "Probably flaky", "probably the cache", with nothing checked.
- Asking the user for something you could fetch yourself, or asking in several rounds.
- Reading a raw log export instead of compacting it.
- "One more attempt" after two failed fixes.

## Sources

obra/superpowers `systematic-debugging` (MIT; its phases, backward tracing, boundary
instrumentation and three-fix rule, summarized here in the kit's words); garrytan/gstack `/investigate` (the name, which avoids the
built-in `/debug`); wshobson/agents `parallel-debugging` (competing hypotheses); Anthropic,
Claude Code best practices (a failing test first, a check Claude can run); David J. Agans,
*Debugging: The 9 Indispensable Rules* (make it fail, quit thinking and look, keep an audit
trail, if you didn't fix it it ain't fixed). Details in CATALOG.md.
