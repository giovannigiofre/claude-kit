---
name: llm-evals
description: Measures and improves an LLM feature (chatbot, agent, RAG, extraction) with evals - error analysis on traces, a failure taxonomy, code checks and calibrated binary judges, a regression gate - then optimizes a prompt or picks a model per role against that suite. Use when the user asks whether an LLM feature is good, reports wrong or worse answers, wants evals or an LLM judge, asks to optimize, tune or rewrite a prompt or agent instructions (never blind, with or without a suite), or asks which model to use.
argument-hint: "[the LLM feature, failure, prompt to optimize or role to pick a model for]"
---

# llm-evals: measure an LLM feature, then improve it against the measure

Target: $ARGUMENTS (if empty, the LLM feature the conversation is about).

Evals decide what to fix and prove a change helped. Generic metrics ("helpfulness",
"coherence") do neither. Build the suite from the failures this feature actually has.
(Method: Hamel Husain & Shreya Shankar's error analysis; Anthropic, "Demystifying evals for AI
agents"; Ragas for the RAG layer. Sources at the end.)

## 0. Inventory first

Read what exists before adding anything: eval dirs, golden files, runners, judges, scorecards,
CI jobs, iteration logs, the project's rules on data (some projects forbid sampling real user
conversations). Extend the existing harness; never build a parallel one. Report the gaps
against the checklist in step 7 in a few lines before writing code.

## 1. Traces to look at

- Real traces if the project allows them; otherwise synthetic ones.
- Synthetic inputs come from **dimensions**, not free generation: list 3-4 axes (persona,
  intent, input quality/ambiguity, language, edge condition), sample tuples, then turn each
  tuple into a natural input. Free "generate 50 questions" gives near-duplicates.
- 50-100 traces is enough to start. Store them with the exact system version (prompt hash,
  model ids, data date) so a later run is comparable.

## 2. Error analysis (the step that cannot be skipped)

1. **Open coding:** read each trace, write one sentence on the *first* thing that went wrong
   (upstream errors cause downstream ones). The domain owner should review these notes; an LLM
   may draft them, the human confirms.
2. **Axial coding:** group the notes into a failure taxonomy of 5-10 named modes with
   counts. An LLM may propose the grouping.
3. Rank modes by frequency x severity. Fix obvious bugs (a missing instruction, a broken tool)
   directly; write evals only for modes that need ongoing measurement.

Show the user the taxonomy table and ask them to confirm or rename modes before step 3.

## 3. One check per failure mode

| Failure mode is | Check |
|---|---|
| Objective (number matches the source, citation resolves, format, language, forbidden content, right tool called) | code assertion |
| Subjective (tone, completeness, honest uncertainty, follows the user's goal) | binary LLM judge, one per mode |

- **Expected facts never come from the system under test.** Read them from the database, the
  source documents, or compute them by hand/raw query. An AI-written "ideal answer" is a draft
  until a human or a deterministic source confirms it; otherwise the suite optimises toward the
  model's own bias.
- Grade the outcome, not the path: checking an exact tool sequence punishes valid alternatives.
  Give partial credit for multi-part tasks.
- RAG: score retrieval and generation separately (retrieval: hit@k / context recall on cases
  with a known source; generation: faithfulness = share of claims supported by the retrieved
  context). An end-to-end score alone can't tell which layer failed.
- Non-determinism: run k trials per case for anything user-facing and report **pass^k** (all k
  pass) next to pass@1. A consumer advisor needs consistency, not best-of-k.

## 4. Judges you can trust

- Binary PASS/FAIL with a written critique per mode, not a 1-5 average across criteria. Allow
  `UNKNOWN` when evidence is missing.
- Prompt: the mode's definition, 2-4 labelled examples (pass and fail), the trace, the
  evidence the judge may use. Structured output.
- **Calibrate:** the owner labels 50-100 traces for that mode. Split the labels
  train (few-shot examples) / dev (tune the judge prompt) / test (report once). Report TPR and
  TNR on test; a judge below ~0.85 on either is not a gate. Re-check after a judge-model change.
- Judge model: capable and different from the generator where possible; pin its id.

## 5. Gate and record

- Deterministic, cheap checks run in CI (replay/snapshot the tool results if they need a DB).
  Live-model and judge runs are a separate, budgeted command, not CI.
- Every run writes a result file with: system version (prompt hash, model ids, data date),
  per-case outcome, per-mode pass rate, cost and latency. Baselines must be reproducible from
  stored results, never from a chat transcript.
- Known failures are marked (e.g. `known_gap`/xfail) so new failures stand out as regressions.

## 6. Improve against the suite

When the suite is trusted, say in one line which of these comes next and read its file:

- **Optimize a prompt, tool descriptions or agent instructions:** [prompt-optimize.md](prompt-optimize.md).
  Asked to optimize a prompt with no trusted suite, build the suite first (steps 0-5): a prompt
  rewritten without a measure is not an improvement anyone can show.
- **Choose or switch the model for a role:** [model-select.md](model-select.md).

## 7. Checklist (report gaps against it)

- [ ] failure taxonomy from real error analysis, with counts
- [ ] expected facts from a source independent of the system under test
- [ ] code checks for every objective mode
- [ ] one binary judge per subjective mode, calibrated (TPR/TNR on a held-out label set)
- [ ] retrieval and generation scored separately (if RAG)
- [ ] pass^k on user-facing behaviour
- [ ] CI gate (deterministic) + budgeted live run
- [ ] versioned, reproducible run records

## Rules

- Respect the project's data rules: if real conversations may not be sampled, say so and use
  synthetic traces plus explicit opt-in feedback only.
- Eval runs that call paid models: state the estimated cost and get the user's OK for anything
  above a few dollars, unless a budget was already given.
- Don't stop at metrics: end with the 3 failure modes worth fixing first.

## Sources

- Hamel Husain, error analysis FAQ: https://hamel.dev/blog/posts/evals-faq/
- Shankar et al., "Who Validates the Validators?" (judge alignment): https://arxiv.org/abs/2404.12272
- Anthropic, Demystifying evals for AI agents: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Ragas metrics: https://docs.ragas.io/
