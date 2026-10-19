---
type: llm
weight: 2
---

PASS if the reply identifies the root cause as the partner API's schema change to version 2 (the key is now customerId and amount is a string with a currency such as "42.50 CHF"), citing the log evidence (X-Schema-Version 2 or the first-record line, compared with the working run), AND the fix handles v2 records where records enter the system (parse() or a normalization step it calls), keeping v1 working, AND a new test with a v2 record was added and the reply shows it passing.
FAIL if the reply only catches or skips the KeyError, defaults the customer, drops records, changes only the error message, or misses the amount format; or if it claims the fix works without showing a test run.
