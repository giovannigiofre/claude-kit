---
type: llm
---

PASS if all of these hold in the final code or reply:
1. the yearly amount is computed in code (for example 12 x the monthly value from premiums.py), not left to the model or written into the prompt;
2. the new tool has a strict input schema (canton enum or validation, required field) and bad input returns a clear error instead of crashing;
3. at least one test with the FakeLLM and one eval case in evals/cases.json cover the new tool, with the expected number taken from premiums.py, not from a model;
4. the reply reports that the tests were run and passed.
FAIL if any of these is missing, or the reply claims success without running the tests.
