# LLM build checklist

Used by `kit-llm:llm-build` step 4 and by `kit:verifier` when a diff touches LLM code.
Tick each item that applies, or write `n/a: <reason>`. Each item is meant to be checkable in
the diff, a test or an eval result. Source keys are listed at the end.

## A. Architecture

- [ ] The parts that follow from rules, lookups or arithmetic are plain code, not model output [BEA, 12F]
- [ ] Workflow (fixed code path) unless the steps really depend on what the model finds; the reason is in the design note [BEA]
- [ ] Multi-agent only for broad, parallel work with little shared state, and the extra token cost is estimated [MAR]
- [ ] Control flow and state live in code the team owns; any framework's outgoing requests can be inspected [BEA, 12F]
- [ ] Each loop has a turn cap, a tool-call cap and a stop condition, enforced in code and tested [BEA]
- [ ] Each agent has one focused job; a growing one is split [12F]

## B. Tools

- [ ] Few tools, each matching a user task rather than an API endpoint; no two tools that a human could confuse [TOOLS]
- [ ] Each description says when to use it, when not, units and an example; names are unambiguous (`user_id`, not `id`) [TOOLS]
- [ ] Input schemas are strict (types, enums, required fields), and inputs are validated in code before running [TOOLS, SO]
- [ ] Errors come back as short, actionable messages the model can act on [TOOLS, 12F]
- [ ] Results are compact, with stable ids for citation; long results are paginated or truncated with a note [TOOLS]
- [ ] Agent ergonomics of each tool's output: a few fields per item by default with a flag or argument for the full record; truncated text says how much was cut; counts and statuses are precomputed so the agent does not page to count; an empty result says "0 results" instead of returning nothing; the output names the useful next call [AXI]
- [ ] Tools never prompt interactively, repeating a call is safe (idempotent writes), and unknown arguments fail loudly with a structured error and exit code [AXI, 12F]
- [ ] Where a CLI and an MCP server both reach the same system (GitHub, a browser), the choice is measured on success rate, tokens and turns for the real tasks, not assumed [AXI, EVALS]
- [ ] Irreversible or costly actions (send, pay, delete, write) are gated: confirmation, allowlist or a human [OAI, TOOLS]
- [ ] Tool selection is covered by eval cases (right tool, sensible arguments) [TOOLS, EVALS]

## C. Context

- [ ] System prompt order: role and audience; what the product is and is not; rules, each with its reason; tool use and citing; output format and length; 2-3 short example turns including a refusal or "I don't know" [CTX]
- [ ] Rules are added for observed failures, not a wall of capitalised MUSTs [CTX]
- [ ] Retrieval is just in time through tools rather than everything up front [CTX]
- [ ] Long histories are compacted (stale tool results dropped first, then summaries or structured state) [CTX]
- [ ] The prompt and the context format are visible in the repo, not hidden inside a framework [12F]
- [ ] Errors are fed back compactly with a retry cap, so the model can correct itself without looping [12F]

## D. Structured output and grounding

- [ ] Output that code reads is schema-constrained where the provider supports it, and always validated locally (Pydantic, Zod or equivalent) [SO]
- [ ] Refusal, truncation (max tokens) and other stop reasons are handled explicitly [SO]
- [ ] Every number or claim shown to the user traces to a tool result or source id; a code post-check (grounding guard) enforces it with a safe fallback [BEA, CTX]
- [ ] Where exact source quotes matter, provider citations or quote-and-verify in code are used; provider limits are checked (some citation features can't be combined with structured output) [CIT]
- [ ] RAG: retrieval is scored separately from generation [EVALS, RAGAS]

## E. Guardrails and security

- [ ] Trifecta statement written: does the feature combine private data, untrusted content (web pages, documents, user uploads, email) and a way to send data out (links, images, HTTP tools, email)? Which leg is removed? [LT]
- [ ] Prompt instructions are not counted as a defence; the boundary is in code [LT, PI]
- [ ] After reading untrusted content, the model cannot trigger consequential actions (plan first then execute, a quarantined model for untrusted text, an action allowlist, minimal context) [PI]
- [ ] Model output is treated as untrusted: no model-written URLs or images rendered without an allowlist; HTML/markdown escaped; never executed or used as SQL/shell [OWASP]
- [ ] Scope and safety checks: off-topic and jailbreak handling, output length limits, no system-prompt leakage [OWASP, OAI]
- [ ] Personal data: minimised in prompts, never in logs (see H), provider data-retention settings chosen [OWASP]
- [ ] Optional: a local red-team run (e.g. promptfoo's injection presets) before launch [PF]

## F. Evals-first loop

- [ ] Hard checks for known failure modes exist before merge: grounding, forbidden content, format and language, right tool [EVALS]
- [ ] Expected values come from a source independent of the model [HAMEL]
- [ ] Should-do and should-not-do cases are balanced; outcomes are graded, not exact paths [EVALS]
- [ ] Judge-based evals only after error analysis on traces, each judge binary and calibrated on human labels (`kit-llm:llm-evals`) [HAMEL, VV]
- [ ] Each eval result file records the prompt hash, model ids, data date, per-case outcome, cost and latency [kit-llm:llm-evals]
- [ ] No hard-check regression versus the last stored result [EVALS]

## G. Models, caching, cost and latency

- [ ] One model per role (router, main loop, writer, judge), chosen on the project's own suite; provisional choices are marked (`kit-llm:llm-evals`, model choice) [OAI]
- [ ] Cost is estimated per completed task or conversation, not per token [CAPI]
- [ ] Cheap wins first: a stable prompt prefix that can be cached (nothing volatile before the cache point), lean inputs, output limits, batch for offline jobs; model change last [CAPI]
- [ ] Budgets in code: max tokens per call, max calls per conversation, timeout, a hard stop before a call that would exceed the budget [BEA]
- [ ] Latency target per turn is stated and measured in the eval run [EVALS]
- [ ] Provider privacy settings match the project's data rules (e.g. OpenRouter data-collection deny / zero-retention routing) [OR]

## H. Operations

- [ ] Logs carry metadata, not content: purpose, model, tokens, cost, latency, error code. Content only with consent or a documented decision; content tracing only self-hosted [MAR]
- [ ] The prompt lives in a file or constant; its hash and the model ids go into every call log and eval result [12F, kit-llm:llm-evals]
- [ ] Retries with backoff and jitter on 429, 5xx and timeouts only, with a cap; 4xx errors are not retried [MAR]
- [ ] Tool side effects are idempotent or protected against double execution on retry [MAR]
- [ ] A fallback provider or model per role is configured and passes the hard checks, or its absence is a stated decision [kit-llm:llm-evals, model choice]
- [ ] Unit tests use a fake or replayed LLM; CI makes no network calls; live evals are a separate, budgeted command [kit-llm:llm-evals]

## Source keys

- BEA: https://www.anthropic.com/engineering/building-effective-agents
- CTX: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- TOOLS: https://www.anthropic.com/engineering/writing-tools-for-agents
- MAR: https://www.anthropic.com/engineering/multi-agent-research-system
- EVALS: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- SO: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- CIT: https://platform.claude.com/docs/en/build-with-claude/citations
- CAPI: anthropics/skills `claude-api` (Apache-2.0), cost and eval docs: https://github.com/anthropics/skills/tree/main/skills/claude-api
- OAI: OpenAI, A practical guide to building agents: https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- 12F: humanlayer/12-factor-agents (CC BY-SA 4.0; cited, not copied): https://github.com/humanlayer/12-factor-agents
- HAMEL: https://hamel.dev/blog/posts/evals-faq/
- VV: Shankar et al., Who Validates the Validators?: https://arxiv.org/abs/2404.12272
- RAGAS: https://docs.ragas.io/
- LT: Simon Willison, The lethal trifecta: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- AXI: Kun Chen, AXI (agent experience interface) design principles, MIT: https://axi.md, https://github.com/kunchenguid/axi (its benchmarks are the author's own: treat them as a hypothesis to test)
- PI: Beurer-Kellner et al., Design Patterns for Securing LLM Agents against Prompt Injections: https://arxiv.org/abs/2506.08837
- OWASP: OWASP Top 10 for LLM Applications 2025: https://genai.owasp.org/llm-top-10/
- PF: promptfoo (MIT): https://github.com/promptfoo/promptfoo
- OR: OpenRouter provider routing: https://openrouter.ai/docs/features/provider-routing
