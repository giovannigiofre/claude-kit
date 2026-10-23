# Prompt optimization: eval-driven prompt iteration

Target: the prompt or role named in the request.

This is the text analogue of training: the eval suite is the loss, failure traces are the
gradient, the prompt is the weights. Same discipline: a held-out set, logged runs, early
stopping. (Method: the flow-ai `optimize-prompt` loop and Karpathy's autoresearch pattern;
GEPA for the automated variant. Sources at the end.)

## 0. Preconditions (stop if missing)

- A suite that measures the target and that the user trusts. If there is none, or its judges
  are uncalibrated, build it first with steps 0-5 of [SKILL.md](SKILL.md) and say why.
- A budget: number of eval runs or USD. Default: 6 runs, and ask before spending more than
  ~USD 10 on paid models.
- The component to change is one file or one prompt constant. Everything else is frozen:
  model ids, temperature, tools, data, judge. Changing two things at once makes the result
  unreadable.

## 1. Split and baseline

- Split the cases: **train** (you read their failures), **val** (scored only, never read
  case-by-case), and keep a few **controls** that pass today. Without a split the loop overfits
  the cases it reads.
- Run the baseline on train+val with k trials where the output is non-deterministic. Record
  per-mode pass rates, cost, latency, and the prompt hash in a run log (append-only file, e.g.
  `evals/ITERATIONS.md` or the project's existing log).

## 2. The loop (one change per iteration)

1. **Diagnose:** group the train failures by failure mode; pick the largest mode. Read 3-5 of
   its traces in full and write the cause in one sentence.
2. **Edit minimally:** the smallest change that addresses that cause - a clarified rule, an
   example, a reordered section, a better tool description. Prefer deleting or sharpening over
   adding; note the prompt length.
3. **Targeted run:** the failing cases of that mode + controls. Not fixed → revert, try the
   next hypothesis (max 2 per mode, then move on).
4. **Confirm:** full train+val run. **Keep** only if val improves (beyond the noise you saw
   between trials of the baseline) and no hard check regresses; otherwise revert.
5. Log: iteration, hypothesis, diff summary, scores, cost, kept/reverted.

Stop when the budget is spent, the target score is reached, or two iterations in a row bring
no val gain.

## 3. Guard rails

- Never edit the eval cases, expected facts or judge to make a score go up. If a case looks
  wrong, flag it to the user and leave it.
- Watch for prompt bloat: if length grows >30 % for <2 points, try a consolidation pass.
- A change that helps one model tier may hurt another; re-run each tier the prompt serves.
- Commit each kept iteration separately so any step can be reverted.

## 4. Automated variant (optional)

When the component is a self-contained LLM call with a scalar or textual metric, an optimizer
can run the loop: DSPy `GEPA` (reflective evolution on full traces, pass textual feedback, not
just a score; trainset for reflection, valset for selection; strong reflection model) or
`MIPROv2` for few-shot selection. Use it only if the project already uses or accepts DSPy;
otherwise run the manual loop above, which works on any stack.

## 5. Report

```
TARGET: <component>  BUDGET: <used>/<given>
BASELINE → FINAL (val): <metric per mode>   train: <...>   pass^k: <...>
KEPT: <iteration - change - gain>
REVERTED: <count, main hypotheses that failed>
COST: <USD>  PROMPT LENGTH: <before → after>
NEXT: <largest remaining failure mode, or "run model-select.md">
```

## Sources

- flow-ai, closing the loop with evals and Claude Code: https://flow-ai.com/blog/automated-prompt-engineering-cc
- GEPA paper (arXiv 2507.19457) and `dspy.GEPA`: https://dspy.ai/api/optimizers/GEPA
- Langfuse, prompt improvement with Claude skills: https://langfuse.com/blog/2026-02-16-prompt-improvement-claude-skills
