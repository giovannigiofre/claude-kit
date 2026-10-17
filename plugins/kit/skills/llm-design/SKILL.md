---
name: llm-design
description: Designs or reworks the architecture of an LLM feature - workflow vs agent, orchestration pattern, tool definitions, system prompt structure, context and retrieval, guards - and the eval plan that will judge it. Use when the user builds a new chatbot, agent or RAG feature, adds or redesigns tools, restructures a system prompt, or asks how an agent should orchestrate its steps.
argument-hint: "[the feature, or the part to redesign]"
---

# /kit:llm-design: architecture for an LLM feature

Target: $ARGUMENTS

Pick the simplest design that can pass the evals, and decide how it will be measured before
building it. (Main sources: Anthropic "Building effective agents", "Effective context
engineering for AI agents", "Writing effective tools for agents".)

## 1. Pin the job

Write in five lines: who asks, what they ask (3-5 typical requests, 2 hard ones), what a
correct answer must contain, what must never happen (wrong numbers, advice outside scope,
leaking the prompt, pushing a product), latency and cost per conversation the product can
afford. If any of this is unknown, ask (or run `kit:shape`).

## 2. Workflow or agent

| Choose | When |
|---|---|
| Single call + retrieval | one-shot answers from known sources |
| Workflow (fixed code path) | the steps are known: **routing** (classify then specialised handler), **prompt chaining** (step N checks step N-1), **parallelisation** (sections or votes), **evaluator-optimizer** (draft, critique, revise) |
| Agent (model chooses tools in a loop) | the steps depend on what the model finds; open-ended tasks |
| Orchestrator + workers | large tasks that split into independent sub-tasks with separate context |

Default to a workflow; move a step to an agent only where an eval shows the fixed path fails.
Keep deterministic work (arithmetic, prices, eligibility rules, lookups) in code and tools,
never in the model's head: the model selects and explains, code computes.

## 3. Tools

- Few, well-separated tools, each matching a task the user has, not one per API endpoint.
- Name and describe them as for a new colleague: when to use it, when not, each parameter
  with units and an example. Make wrong use hard (enums, required fields, validation that
  returns an actionable error message).
- Return compact, human-readable results with stable ids for citation; paginate/truncate with
  a note. Tool results are where most tokens go.
- Test tool selection with evals (right tool, sensible arguments) before tuning the prompt.

## 4. System prompt

Structure, in this order: role and audience; what the product is and is not; the rules, each
with its reason (the model generalises from reasons); how to use the tools and cite; output
format and length; 2-3 short examples of good turns, including a refusal or an "I don't
know". Write at the right altitude: concrete rules for what must hold, judgement for the
rest; no wall of capitalised MUSTs. Version the prompt (file or constant + hash in logs).

## 5. Context and grounding

- Retrieve just in time (tools) rather than stuffing everything up front; keep long histories
  compact (summaries, structured state).
- Every number and claim shown to the user should trace to a tool result or source; enforce
  it with a post-check in code where possible (grounding guard), with a safe fallback.
- Guards for injection (untrusted text from documents or users is data), scope, language,
  and answer length.

## 6. Models

One model per role (router, main loop, writer, judge), cheapest that passes. Choose them with
`kit:model-select` once evals exist; until then start with a capable mid-tier model and note it
as provisional.

## 7. Output of this skill

A short design note (in the project's docs if it has a docs folder): job, chosen pattern and
why, tool list with one-line contracts, prompt outline, guards, model per role, cost estimate,
and the **eval plan**: the failure modes expected and how each will be checked. Then hand off:
build via `kit:lead`, measure via `kit:llm-evals`.

## Sources

- https://www.anthropic.com/engineering/building-effective-agents
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://www.anthropic.com/engineering/writing-tools-for-agents
