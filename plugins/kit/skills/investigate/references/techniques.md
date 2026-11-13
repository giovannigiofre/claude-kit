# Localization techniques

Pick the cheapest technique that halves the search space.

## Trace the bad value back to its origin
The line that crashes is rarely the line that is wrong. From the failure, ask where the bad value
came from: the caller, its caller, the data or config that fed it. Follow it upstream until you
reach the first place it was produced or accepted wrongly; fix it there, not where it surfaced.
When the chain is hard to read, log the value (and a stack trace) at each hop once.

## Waiting on a condition, not on time
A test that sleeps a fixed time and then checks is flaky by construction. Wait for the condition
itself (poll the state, await the event, retry the assertion with a deadline) and fail with a
message that says what never happened.

## Which test leaves state behind
When a test passes alone and fails in the suite, or a stray file appears, run the tests one at a
time in a fresh state and check for the artifact after each (the first one that leaves it is the
polluter); for order-dependent failures, bisect the list of tests that run before the failing
one.

## Defense in depth, after the fix
Once the root cause is fixed, consider one validation where the bad value entered the system (a
parse, a schema check, a guard at the API boundary) so the same class of input fails early and
loudly next time. Only at that boundary, not at every layer.

## Good vs bad diff
Put a working instance next to a broken one: run, commit, input, environment, user, browser.
List **every** difference (versions, env vars, config, data shape, timing), however small, then
eliminate them one at a time. With log exports, `compact_logs.py bad.json --diff good.json`
lists the signatures that appear only in the failing run, and the steps of the working run that
never happened in the failing one.

## Reading a result
A tool or API result answers three questions, in this order: did the transport succeed (HTTP
status, exit code, no timeout); did the operation itself succeed (its own status or error field,
which can say "failed" inside a 200); does the payload have the shape the caller expects (fields,
types, counts). A payload being present is not success: an error object, an empty list or a
partial page all arrive as a body. Check all three before trusting a value from it.

## Boundary instrumentation (multi-component systems)
For each boundary (UI → API → service → DB, job step → external API, CI step → script):
- log what enters (IDs, sizes, types; never raw secrets or PII)
- log what exits
- log which config is visible at that layer (`VAR=SET/UNSET`, never secret values)

Run once. The first boundary where the input is right and the output is wrong holds the fault.
Remove the logs afterwards, or turn them into structured logging on purpose.

## Bisection
- Regression with a known good commit: `git bisect start BAD GOOD`, then
  `git bisect run <command that exits non-zero on the bug>`. On a shallow clone, fetch enough
  history first (`git fetch --depth=500 origin <branch>`).
- Config or dependency regression: bisect the lockfile or config changes the same way.
- A large failing input: halve it until the smallest input that still fails (delta debugging).
  A minimal repro often names the cause by itself.

## Competing hypotheses (analysis of competing hypotheses)
When two or more causes are plausible, or you are stuck:
1. List hypotheses across categories: code logic, data/schema, config/env, dependency/version,
   concurrency/timing, infrastructure/permissions, external service.
2. One Explore agent per hypothesis, launched in the same message. Brief: the symptom, the
   evidence files, "find evidence that confirms AND evidence that refutes; cite file:line or
   log lines; state a confidence". The agents only read and run read-only checks.
3. Matrix: hypothesis × evidence item, marked consistent / inconsistent / neutral. The winner
   has the **fewest inconsistencies**, not the most support (that guards against confirmation
   bias).
4. None survives: form new hypotheses from what was learned, or ask the user for the missing
   evidence.

## A debugger instead of prints
If a debugger MCP server (DAP based: debugpy, codelldb, Delve, netcoredbg) or browser DevTools
tools are connected, set a breakpoint at the divergence point, inspect real values and evaluate
expressions. It is faster and more truthful than reading code.
