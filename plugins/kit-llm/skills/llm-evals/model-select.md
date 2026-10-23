# Model selection: pick models with evidence

Target: the prompt or role named in the request.

Benchmarks and vendor claims don't predict how a model does on *this* task. The project's own
eval suite does. (Anthropic: teams with evals adopt a new model in days instead of weeks.)

## 0. Preconditions

- A trusted eval suite per role (steps 0-5 of [SKILL.md](SKILL.md) if missing). Hard checks matter most here:
  grounding, format, language, forbidden content.
- The current assignment of models to roles, read from config, with current cost per case.
- A budget. Default: ask before spending more than ~USD 10.

## 1. Candidates

- Current prices, context limits and availability change monthly: look them up (provider
  pages, OpenRouter model list); never quote them from memory.
- 3-5 candidates per role: the incumbent, one cheaper, one stronger, one from another provider.
- Note per candidate: structured-output/tool-calling support, data-retention terms if the
  project has rules on them, and the languages it must handle.

## 2. Run

- Same cases, same prompt, same tools, same judge for every candidate. Pin model ids.
- k trials per case (k ≥ 3 for user-facing roles); record pass@1, pass^k, hard-check
  failures, cost per case, p50/p95 latency, failure/timeout rate.
- Judge with a model that is not a candidate, or rotate and disclose it: a judge favours its
  own family.
- If the prompt was tuned for the incumbent, say so: a fair comparison may need one short
  pass of [prompt-optimize.md](prompt-optimize.md) per finalist.

## 3. Decide

- Drop any candidate that fails a hard check the incumbent passes.
- Plot or tabulate quality vs cost per case; keep the Pareto frontier.
- Pick per role, not globally: cheap fast models for routing/classification, strong models
  for long reasoning or user-visible writing, a stable pinned model for judges.
- Add a fallback per role (another provider) and check it passes the hard checks.

## 4. Report

```
ROLE        INCUMBENT → PICK      quality (pass^k)   USD/case   p95 s   why
router      ...
writer      ...
FALLBACKS: <role → model>
MONTHLY COST at <N> conversations: <before → after>
NOT TESTED / RISKS: <...>
```

Change the configuration only after the user approves the table; then run the full suite
once more on the new assignment as the regression check.
