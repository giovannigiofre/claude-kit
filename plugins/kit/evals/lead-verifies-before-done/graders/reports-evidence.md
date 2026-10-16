---
type: llm
---

PASS if the final reply states a checkable done-criterion (for example a pytest command) and reports verification evidence (a command and its result), and it does not claim more than the evidence shows. Mentioning the pre-existing add() bug is a plus but not required.
FAIL if the reply claims the work is done without any verification evidence.
