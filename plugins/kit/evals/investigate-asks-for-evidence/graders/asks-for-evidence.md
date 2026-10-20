---
type: llm
weight: 2
---

PASS if, before presenting any code change as the fix, the reply asks the user for log evidence from the console with concrete steps: it names Logs Explorer (or Cloud Logging), gives a filter or query that targets the job (for example resource.type="cloud_run_job" and the job name nightly-ingest, or the execution), asks for a download/export as a file (JSON or CSV, not only screenshots), AND asks for the same evidence from a run that worked (the night before) to compare. Asking for the failed execution's ID or time and for recent changes is a plus.
FAIL if the reply edits code or presents a fix without having seen any log evidence, asks only vague questions ("can you share the logs?") without saying how to get them, or asks only for screenshots.
