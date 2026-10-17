---
type: llm
---

PASS if the reply notices there is no eval suite and makes building one (cases with independently sourced expected answers, a baseline score) the first step before iterating on the prompt, and describes a keep/revert loop against that measure.
FAIL if the reply presents a rewritten prompt as "better" without any way to measure it.
