# Evals for the Omnigent bundle

Outcome evals for the specialists `lead` dispatches. They start with `engineer` and `reviewer`,
the two roles that touch code. Each case is a real task from the owner's projects. A run gives
the specialist the brief `lead` would have written, lets it work in a throwaway clone, and grades
what it left behind. The path it took is not graded. Every case runs 3 times; the score is pass@1
and pass^3 (the case passed all three times), as the research report recommends (§2.3, §2.6 point 6).

```
omnigent/evals/
  run.py      runner and graders (stdlib Python, no install)
  README.md   this file: case format, how to run, the A/B protocol
```

## Where the cases are

The cases live **outside this repo**, in `~/Documents/omnigent-research/evals/` (override with
`OMNIGENT_EVALS_HOME`). claude-kit is public. The cases come from two private repos
(`giovannigiofre/fiscometro`, `casa-studio/ciaoguest`) and carry their briefs, SHAs, seeded
patches and transcripts, so they must not be committed here. The runner and the format are
generic. To use the runner with another project, add it to `REPOS` in `run.py` and write cases
for it.

```
$OMNIGENT_EVALS_HOME/
  cases/engineer/<id>/   case.json, brief.md, rubric.md
  cases/reviewer/<id>/   case.json, brief.md, rubric.md, seed.patch (seeded cases)
  gen/                   the generator the cases are built from (engineer_cases.py, reviewer_cases.py, build.py)
  results/<stamp>-<variant>/  summary.md, summary.json, prompt-<role>.md, runs/<case>/<n>/...
```

Current set: 21 engineer cases (7 fiscometro, 14 ciaoguest) and 20 reviewer cases (8 clean, 8 seeded,
4 real defects). They come from merged PRs that fixed something the owner, a verifier, a security
review or production found: a verifier's questions, review leftovers, live defects, an outage.

## Case format

`case.json`, shared fields: `role`, `repo` (a key of `REPOS`), `pr`, `title`, `source`, `base` (the
commit the run starts from) and `timeout_min`. `brief.md` is the brief in the bundle's format: GOAL /
SCOPE / DONE WHEN / WORKTREE / SHIP / OUTPUT. `{WORKTREE}` and `{BRANCH}` are filled in per run.

**Engineer.** `ref` is the merged PR, one correct solution. `hidden_tests` are that PR's test files
and `hidden_support` their helpers. Grading has two steps, and both must pass:

1. **Hidden tests.** The reference PR's tests are copied over the agent's tree and run with vitest
   in their package. The engineer never sees them. DONE WHEN names the interface they import, so
   they test the behaviour, not whether the engineer guessed the names.
2. **Rubric.** A model judge (`claude -p --model sonnet`, no tools) reads the brief, `rubric.md`,
   the agent's diff and report, the hidden-test result and the reference diff. It answers PASS only
   if every DONE WHEN point holds, the change stays in SCOPE, and the report claims no check it did
   not run. The reference is one correct answer, not the only one.

`run.py validate` checks every engineer case: its hidden tests must fail on `base` and pass on `ref`.
A case that fails this check is broken, not hard.

**Reviewer.** `head` is the merged PR. The branch under review is `base` plus the PR's diff, plus
`seed.patch` when there is one, as a single commit. `expect` is `PASS` or `FAIL`.

- `clean`: the PR as merged, and no later PR fixed a defect in it. It must get PASS.
- `seeded`: the PR plus one injected defect. Some of these the PR's own tests catch; others they do
  not (for example, an index added to an already-shipped migration).
- `real`: the PR as merged, carrying the defect a later PR fixed (`rubric.md` names the defect and
  the fixing PR).

A FAIL case passes only if the verdict is FAIL **and** a model judge confirms that PROBLEMS names
`rubric.md`'s defect. A vague concern, a different problem, or the defect listed only under QUESTIONS
does not count. CANNOT_VERIFY fails both kinds of case. A reviewer that commits to the branch it
reviews fails the run.

**Any other role** (a specialist being onboarded, see `new-agent`) is graded by the same model
judge against `rubric.md`: what a good outcome must contain or do, and what makes it FAIL. The judge
reads the report, and the diff when the agent changed files. `repo_path` in `case.json` points at a
repo that is not in `REPOS`, and `--prompt <role>=<file>` overrides any role's prompt for an A/B arm.

## How a run works, and why `claude -p`

Each run does this:

1. Clone the project with `git clone --shared` into a temp directory (never the main checkout).
2. Point `origin` at a dead URL, so nothing can be pushed or fetched.
3. Set `refs/remotes/origin/main` to the case's base, check out the case's branch and run `pnpm install --offline`.
4. Run the specialist, then grade it.
5. Delete the clone (`--keep` keeps it).

The specialist runs as

```
claude -p <brief> --append-system-prompt <prompt from omnigent/agents/<role>/config.yaml> \
  --permission-mode auto --output-format stream-json --verbose
```

with `OMNIGENT_RUNNER_ID=eval`, so the kit leaves coordinating to lead as it does under Omnigent.
`GH_CONFIG_DIR` points at an empty folder, so a run cannot open a PR or post a comment.

Why not `POST /v1/sessions` on the local server:

- **Only `lead` is a server-side agent.** The specialists exist only as `lead`'s sub-agents
  (`omnigent agent list` shows `lead` alone). A run through the API therefore scores lead and the
  specialist together. A lead decision, such as rewriting the brief or making its own worktree,
  would blur the score of the role under test.
- **It is the same CLI.** In Omnigent 0.23, `claude-native` launches Claude Code with
  `--append-system-prompt <prompt>` and `--permission-mode auto`
  (`omnigent/runner/native/orchestration.py`). `claude -p` with those two flags runs the same
  binary, plugins, CLAUDE.md and kit hooks. What is missing: Omnigent's own tool surface (`sys_*`,
  which the specialists do not use) and its terminal bridge.
- **A/B needs a prompt per arm.** `--engineer-prompt` and `--reviewer-prompt` take a variant
  `config.yaml` or `.md` without touching the installed bundle the owner is using.

An eval of `lead` itself (does it write a good brief, dispatch the right specialist, refuse to
parallelise sequential work) has to go through the API. That is the next step, not part of this set.

## Running it

```sh
cd omnigent/evals
./run.py list                                 # the cases
./run.py validate engineer                    # hidden tests red on base, green on ref (no model calls)
./run.py run fm23-bustapaga-variants -k 1     # one case, one run
./run.py run engineer reviewer -k 3 -j 3      # the full suite (the owner's call: hours, real money)
./run.py report <results dir>
```

Case selectors are ids, id prefixes, or a role. `--model` sets the specialist's model (Claude Code's
default otherwise), and `OMNIGENT_EVALS_JUDGE` sets the judge model (default `sonnet`).

Every run writes its folder under `runs/<case>/<n>/`:

- `brief.md`, `transcript.jsonl` (read these when a case fails), `report.md`
- `agent.diff` and `hidden-tests.json` (engineer), `tree-after.txt` (reviewer)
- `grade.json`, with the cost and time

`summary.md` has pass@1, pass^k, cost and agent minutes per role and per case.

## Baseline

First run, 22 Nov 2026: Claude Code 2.1.330 with its default model, the bundle prompts as merged in
kit 2.0.2, k=3, 3 runs in parallel per role, the two roles side by side. Only a subset ran; the full
suite is the owner's call.

| role | cases | pass@1 | pass^3 | cost | agent time | wall |
|---|---|---|---|---|---|---|
| engineer | 5 | 1.00 | 1.00 | $17.64 | 93 min | 36 min |
| reviewer | 5 | 0.67 | 0.60 | $11.52 | 72 min | 27 min |

Costs are Claude Code's `total_cost_usd`, judge calls included (about $0.02 each), roughly $1 per
engineer run and $0.75 per reviewer run. On a subscription they are API-equivalent estimates, not a
bill. By that estimate the full suite (41 cases × 3) costs about $110 and takes about 2.5 hours of
wall time at `-j 3`.

What the subset shows:

- **Engineer:** 15/15. All five subset cases are small fixes with a precise DONE WHEN; the harder
  cases (the zip archive, the Assistente outage, Rome days) did not run. The subset proves the runner
  works; it does not measure the engineer's ceiling.
- **Reviewer, seeded:** 6/6. It caught the index folded into the already-shipped migration 22, a
  defect the tests do not catch, and the production fallback.
- **Reviewer, clean #50 (1/3):** it FAILed a one-line a11y fix the owner merged in 2 of 3 runs. The
  reason given: "a fix needs a test that fails on the base". A threshold question for the prompt.
- **Reviewer, real #325 (0/3):** it PASSed the Chart change all three times. It never noticed that
  the screen-reader table reads 30 rows of «0,00 €», the defect #327 later fixed. The owner's review
  missed it at the time too.

The first attempt at this run was thrown away: the clone still carried the project's later `main`,
and a reviewer found its PR already merged there. Clones are now sealed: only the case branch and
`origin/main` = base are left. What a run could still reach: the real checkout under
`~/Documents/repositories/` and GitHub through the git credential helper. No run in the kept
results did.

## Changing a prompt: the A/B loop

This is a measured propose → A/B → keep loop, after Harness² (arXiv 2610.14224). The difference is
that the owner approves every change that is kept.

1. **Propose.** Start from failures, not ideas. Read the transcripts of the failing runs of the last
   suite and name the cause in one line, for example "reviewer passed a migration edit because it
   never asks whether existing data gets the change". Write one change against that cause, as a copy
   of the role's `config.yaml` (or a skill) under `$OMNIGENT_EVALS_HOME/variants/<name>/`. One change
   per variant, so a result can be traced to its cause.
2. **A/B.** Run both arms on the same cases with the same k and model:
   `./run.py run reviewer -k 3 --variant base` and
   `./run.py run reviewer -k 3 --variant <name> --reviewer-prompt variants/<name>/config.yaml`.
   Use the whole role suite, not only the cases the change targets. A fix that breaks the clean
   cases (for example, a reviewer that now FAILs everything) has to show up.
3. **Keep the winner.** The variant wins only if:
   - pass^3 goes up, or stays level while pass@1 goes up;
   - no case that passed 3/3 on base drops below 2/3;
   - cost per case rises no more than 25 %.

   Otherwise base stays. With 20 cases and k=3, a gain of one case is noise: run it again before
   believing it.
4. **The owner approves.** The variant's diff and the two `summary.md` files go into a PR on this
   repo that edits `omnigent/agents/<role>/config.yaml`. The owner merges, then runs
   `omnigent agent add` again. A change to tools, permissions or guardrails always needs the owner,
   whatever the score.
5. **Keep the suite honest.** Each owner "no" on a real PR (a review he overrules, a fix he sends
   back) becomes a new case. A case every arm has passed 3/3 for three rounds moves to a regression
   list that runs on model changes only. Run the whole suite again whenever the model or Claude Code
   changes, and ask what the prompt can now drop.
