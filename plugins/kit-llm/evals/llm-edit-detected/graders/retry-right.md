---
type: llm
---

PASS if the new retry in llm.py backs off exponentially with a cap (and ideally jitter), retries only on rate limits (429), server errors (5xx) and timeouts or connection errors, and does not retry other 4xx errors such as 400 or 401; and a test that uses the injectable `post` (no network) checks the behaviour.
FAIL if it still retries every exception, retries 400/401, has no upper bound, or has no test.
