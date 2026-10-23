export const meta = {
  name: 'review',
  description: 'Review the current branch across several lenses, adversarially verify each finding, check that every changed file was covered, and rate the risk',
  whenToUse: 'Before merging a branch or after a large change. args: {base?: "main", lenses?: [..], focus?: "extra instructions", intent?: "what the change is for"}',
  phases: [
    { title: 'Scope', detail: 'changed files, intent, findings the user already declined' },
    { title: 'Find', detail: 'one reviewer per lens, each lists the files it read' },
    { title: 'Verify', detail: 'two skeptics per finding try to refute it' },
    { title: 'Assess', detail: 'coverage gaps and a risk rating' },
  ],
}

// Method adapted from kunchenguid/no-mistakes (MIT): findings carry an action, reviewers must
// state what they covered, declined findings are not raised again, a risk rating ends the
// review. Nothing copied.

const input = args || {}
const BASE = input.base || 'the default branch (origin/HEAD, else main or master)'
const FOCUS = input.focus ? `\nExtra focus: ${input.focus}` : ''
const LENSES = input.lenses || [
  'correctness: logic errors, edge cases, wrong assumptions, broken error handling',
  'project rules: violations of CLAUDE.md / AGENTS.md / decision logs / skills in this repo',
  'tests and verification: changed behaviour without a test, tests that cannot fail, tests that mock the very path they claim to check, unverified claims',
  'security and data: secrets, injection, unsafe input handling, personal data, destructive operations',
  'simplicity: duplication of existing helpers, dead code, needless abstraction, code the intent does not need',
  'llm: only if the diff touches LLM code (SDK or provider-endpoint calls, prompts, tool schemas, model config; else return an empty list): read skills/llm-build/checklist.md of the kit plugin (or the kit:llm-build skill) and report missing hard-check evals or eval result for a prompt/tool/model change, numbers the model computes instead of code, unvalidated structured output, loops without caps, prompt-injection paths (private data + untrusted content + a way out), rendered model-written links, content in logs, retries on non-retryable errors',
]

const SCOPE = {
  type: 'object',
  required: ['changed', 'intent', 'declined'],
  properties: {
    changed: { type: 'array', items: { type: 'string' }, description: 'every changed file path, relative to the repo root' },
    intent: { type: 'string', description: 'what the change is for, 2-4 lines' },
    declined: { type: 'array', items: { type: 'string' }, description: 'findings already declined, one line each' },
  },
}

const FINDINGS = {
  type: 'object',
  required: ['findings', 'reviewed_paths'],
  properties: {
    reviewed_paths: { type: 'array', items: { type: 'string' }, description: 'changed files you actually read for this lens' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['file', 'line', 'title', 'why', 'severity', 'action'],
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          title: { type: 'string' },
          why: { type: 'string', description: 'concrete failure scenario' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          action: {
            type: 'string',
            enum: ['auto-fix', 'ask-user', 'no-op'],
            description: 'auto-fix: mechanical, does not change what was asked for; ask-user: touches the intent or a product decision; no-op: real but not worth acting on',
          },
          fix: { type: 'string', description: 'the fix in one line; prefer deleting code the intent does not need over adding code' },
          siblings: { type: 'array', items: { type: 'string' }, description: 'other file:line sites where the same rule must hold' },
        },
      },
    },
  },
}

const VOTE = {
  type: 'object',
  required: ['refuted', 'reason'],
  properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } },
}

const RISK = {
  type: 'object',
  required: ['level', 'rationale'],
  properties: {
    level: { type: 'string', enum: ['low', 'medium', 'high'] },
    rationale: { type: 'string', description: '1-2 lines: blast radius, evidence coverage, rollback' },
  },
}

const scope = await agent(`List the changes on the current branch versus ${BASE}, committed and uncommitted
(git diff --name-only against the merge base, plus git status). Return every changed file.
Intent: ${input.intent || 'infer it in 2-4 lines from the branch commits, the PR description if one exists (gh pr view), and any linked issue'}.
Declined: if .claude/review-decisions.md exists, return each finding listed there, one line each; else an empty list.`,
  { label: 'scope', phase: 'Scope', schema: SCOPE })

const CHANGED = scope ? scope.changed : []
const CONTEXT = scope
  ? `\nIntent of the change: ${scope.intent}\nChanged files: ${CHANGED.join(', ')}${scope.declined.length ? `\nThe user already declined these findings; do not report them again:\n- ${scope.declined.join('\n- ')}` : ''}`
  : ''

const results = await pipeline(
  LENSES,
  lens => agent(`Review the changes on the current branch versus ${BASE} (committed and uncommitted) through this lens only:
${lens}${FOCUS}${CONTEXT}
Judge the change against its intent, not against the commit messages: what the author says the code does is a claim to check.
Read every changed file that matters for this lens and list them in reviewed_paths.
Report only real problems with a concrete failure scenario. An empty list is a fine answer.`,
    { label: `find:${lens.split(':')[0]}`, phase: 'Find', schema: FINDINGS }),
  (found, lens) => parallel((found ? found.findings : []).map(f => () =>
    parallel([0, 1].map(k => () => agent(`Try to refute this review finding. Read the code at ${f.file}:${f.line} and its callers.
Finding (${lens.split(':')[0]}): ${f.title}
Claimed failure: ${f.why}
Set refuted=true if the scenario cannot happen, is already handled, or is not a real problem. If unsure, refuted=true. (skeptic ${k + 1})`,
      { label: `verify:${f.file}:${f.line}#${k + 1}`, phase: 'Verify', schema: VOTE })))
      .then(votes => ({ ...f, lens: lens.split(':')[0], upheld: votes.filter(Boolean).filter(v => !v.refuted).length }))
  )).then(checked => ({ lens: lens.split(':')[0], reviewed: found ? found.reviewed_paths : [], findings: checked })),
)

const lensResults = results.filter(Boolean)
const all = lensResults.flatMap(r => r.findings).filter(Boolean)
const confirmed = all.filter(f => f.upheld === 2)
const disputed = all.filter(f => f.upheld === 1)
const rank = { high: 0, medium: 1, low: 2 }
confirmed.sort((a, b) => rank[a.severity] - rank[b.severity])

// A changed file no lens read is not certified by a clean review.
const reviewed = new Set(lensResults.flatMap(r => r.reviewed || []))
const notCovered = CHANGED.filter(p => !reviewed.has(p))

const risk = await agent(`Rate the risk of merging the changes on the current branch versus ${BASE}.${CONTEXT}
Confirmed findings still open: ${confirmed.length ? confirmed.map(f => `${f.severity} ${f.file}:${f.line} ${f.title}`).join('; ') : 'none'}.
Files no reviewer read: ${notCovered.length ? notCovered.join(', ') : 'none'}.
Consider blast radius (shared modules, auth, money, migrations, data deletion, public API), how much the tests and any evidence under .claude/evidence/ actually exercise, and how hard a rollback is.
Low means a reader can trust the summary; high means someone must read the diff.`,
  { label: 'risk', phase: 'Assess', schema: RISK })

log(`${all.length} findings, ${confirmed.length} confirmed by both skeptics, ${disputed.length} disputed, ${notCovered.length} changed files not reviewed, risk ${risk ? risk.level : 'unknown'}`)
return {
  intent: scope ? scope.intent : null,
  risk,
  confirmed,
  disputed,
  notCovered,
  byAction: {
    'auto-fix': confirmed.filter(f => f.action === 'auto-fix'),
    'ask-user': confirmed.filter(f => f.action === 'ask-user'),
    'no-op': confirmed.filter(f => f.action === 'no-op'),
  },
}
