---
name: llm-build
description: Designs, builds, changes or reviews code that calls an LLM - an SDK (anthropic, openai, google-genai, litellm, langchain...) or a raw HTTP call to a provider (/v1/messages, /chat/completions, OpenRouter) - or a prompt, tool schema or model config, so it ships grounded, injection-aware, measured and within budget. Use for any chatbot, agent, RAG, extraction, LLM judge or tool-calling work, even a small change such as a retry, a new tool or one prompt line.
argument-hint: "[the feature or change]"
---

# llm-build: design, build and review an LLM feature

Target: $ARGUMENTS (if empty, the LLM code this conversation is touching).

An LLM feature fails in ways ordinary tests do not catch: plausible wrong numbers, a tool the
model misuses, a web page that steers the agent, a bill that grows per turn. This skill keeps
the design simple, makes each of those failure modes an explicit decision, and ends with
evidence (hard-check evals), not with "the prompt reads better". Sources at the end.

## 1. Scope the change

Say which one it is, in one line:

- **New feature**: do steps 2-6 in full.
- **New component** (a tool, a step, a judge, a provider): steps 3-6 for that component.
- **Change to existing code** (prompt line, retry, model id, tool field): first read the
  feature's design note, eval suite and last eval result; then step 4 for the touched items
  and step 5.

The project's CLAUDE.md / AGENTS.md win over this skill (data rules, logging policy, owner
decisions).

## 2. Pin the job

Five lines: who asks; what they ask (3-5 typical requests, 2 hard ones); what a correct answer
must contain; what must never happen (wrong numbers, out-of-scope advice, prompt leakage,
pushing a product, sending data out); the latency and cost per conversation the product can
afford. Anything unknown: ask, or run `kit:shape`.

## 3. Architecture

Start with the simplest design that can pass the evals; add a step only when an eval shows
the simpler one fails.

| Choose | When |
|---|---|
| Plain code, no model | the answer follows from rules, lookups or arithmetic |
| One call + retrieval | one-shot answers from known sources |
| Workflow (fixed code path) | the steps are known: routing, chaining with checks between steps, parallel sections or votes, draft-critique-revise |
| Agent (model picks tools in a loop) | the steps depend on what the model finds |
| Orchestrator + workers | broad work that splits into independent parts with little shared state; costs several times the tokens of one agent |

- Code owns control flow, state, arithmetic, prices, eligibility and lookups. The model
  selects, phrases and explains; it never computes a number the user relies on.
- Every loop has a turn cap, a tool-call cap, a token/cost cap and a stop condition, enforced
  in code. Errors per step compound over a long loop: keep loops short.
- Use a framework only if you can see exactly what it sends; a raw API call is often a few
  lines.

## 4. Build checklist

Copy the sections of [checklist.md](checklist.md) that apply into the task list and tick each
item, or write `n/a: <reason>`. Sections:

- **A** architecture: code first, workflow vs agent, caps.
- **B** tools: few, task-shaped, strict schemas, actionable errors, risky actions gated.
- **C** context: system prompt structure, just-in-time retrieval, compaction, errors fed back.
- **D** structured output and grounding: schema + local validation, stop reasons, grounding
  guard, citations; RAG scored per layer and per slice, with an answer for missing context.
- **E** guardrails and security: lethal trifecta, prompt injection, output rendering, scope,
  PII; a no-side-effect test per consequential tool, a sentinel secret, path containment.
- **F** evals-first loop: hard checks now, judges after error analysis (`kit-llm:llm-evals`).
- **G** models, caching measured by the provider's counters, cost and latency budgets
  (`kit-llm:llm-evals`, model choice); queue and worker designs against
  [cost-burn.md](cost-burn.md).
- **H** operations: logging without content, prompt hash, retries on 429/5xx, fallback
  provider, fake-LLM tests.

For a small change, only the touched sections apply, but E (security) and F (evals) are always
read: a one-line prompt or tool change can open an injection path or regress a hard check.

## 5. Hard-check evals before merge

For every new or changed behaviour, add at least one code-checked eval case in the project's
existing harness (never a parallel one):

- grounding: each number shown traces to a tool result or source id;
- forbidden content: no out-of-scope advice, no leaked prompt, no model-written links;
- format and language: the schema validates, the reply is in the user's language;
- tools: the right tool with sensible arguments (grade the outcome, not the exact path).

Expected values come from a source independent of the model (database, document, hand
calculation). Judge-based evals come after error analysis on real or synthetic traces: hand
that to `kit-llm:llm-evals`. Every eval result records the prompt hash and the model ids.

Live-model runs cost money: state the estimate and get the user's OK above a few dollars
unless a budget was given. CI runs the deterministic part only.

## 6. Provider facts

Never write API shapes, parameter names, prices or model ids from memory. If the code uses the
Anthropic SDK, the built-in `claude-api` skill is the reference (its `build-eval`,
`cost-optimize` and `prompt-audit` workflows fit steps 4-5). For any other provider, or a raw
HTTP call, read the provider's current docs and cite the page in the design note.

## 7. Done when

Each one needs evidence (the reviewer checks them before a PR):

- [ ] every applicable checklist item is ticked, or marked `n/a` with a reason;
- [ ] unit tests pass with a fake or replayed LLM (no network in CI);
- [ ] hard-check evals for the new behaviour are added and pass, and the result file names
      the prompt hash and the model ids;
- [ ] no hard-check regression on the existing suite;
- [ ] cost and latency per conversation are estimated, and the budgets are enforced in code;
- [ ] trifecta statement: which leg (private data, untrusted content, a way out) is absent,
      or why the risk is accepted (an owner decision, written down);
- [ ] the design note is updated: job, pattern and why, tools with one-line contracts, guards,
      model per role, budgets, eval plan.

## 8. Hand-off

- Measure an existing feature, add judges, improve a prompt against the suite or choose a model
  per role: `kit-llm:llm-evals` (prompt optimization and model choice are its second and third
  parts).

## Sources

Method summarised in the kit's own words; nothing is copied.

- Anthropic, Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, Writing effective tools for agents: https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic, How we built our multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Demystifying evals for AI agents: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- humanlayer/12-factor-agents (cited, CC BY-SA, not copied): https://github.com/humanlayer/12-factor-agents
- Simon Willison, The lethal trifecta: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- More per item in [checklist.md](checklist.md).
