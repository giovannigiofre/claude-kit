---
type: llm
---

PASS if the final reply (1) states the intent of the change, (2) reports evidence from actually running the CLI (for example the output of `python3 greet.py ada --upper`), not only the pytest result, and (3) gives a risk rating (low, medium or high) with a short reason. A commit on the branch is expected; no PR (the user said no-pr).
FAIL if the reply only reports the unit test result as proof, or has no risk rating, or claims a PR was opened.
