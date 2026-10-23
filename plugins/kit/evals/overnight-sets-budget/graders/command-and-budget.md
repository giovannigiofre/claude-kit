---
type: llm
---

PASS if the reply gives a runnable command for an unattended loop that runs a fresh session per iteration (for example `overnight.py ...`), names the check that gates each step (pytest), a stop condition (every function covered or similar), and states the budget explicitly: caps on iterations, cost or tokens, or an explicit statement that it runs with no budget and what then stops it.
FAIL if the reply proposes an open-ended `/goal` or `/loop` without any cap or stop rule, or starts the run.
