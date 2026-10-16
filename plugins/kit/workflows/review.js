export const meta = {
  name: 'review',
  description: 'Review the current branch across several lenses, then adversarially verify each finding before reporting',
  whenToUse: 'Before merging a branch or after a large change. args: {base?: "main", lenses?: [..], focus?: "extra instructions"}',
  phases: [
    { title: 'Find', detail: 'one reviewer per lens' },
    { title: 'Verify', detail: 'two skeptics per finding try to refute it' },
  ],
}

const input = args || {}
const BASE = input.base || 'the default branch (origin/HEAD, else main or master)'
const FOCUS = input.focus ? `\nExtra focus: ${input.focus}` : ''
const LENSES = input.lenses || [
  'correctness: logic errors, edge cases, wrong assumptions, broken error handling',
  'project rules: violations of CLAUDE.md / AGENTS.md / decision logs / skills in this repo',
  'tests and verification: changed behaviour without a test, tests that cannot fail, unverified claims',
  'security and data: secrets, injection, unsafe input handling, personal data, destructive operations',
  'simplicity: duplication of existing helpers, dead code, needless abstraction',
]

const FINDINGS = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['file', 'line', 'title', 'why', 'severity'],
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          title: { type: 'string' },
          why: { type: 'string', description: 'concrete failure scenario' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
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

const results = await pipeline(
  LENSES,
  lens => agent(`Review the changes on the current branch versus ${BASE} (committed and uncommitted) through this lens only:
${lens}${FOCUS}
Report only real problems with a concrete failure scenario. An empty list is a fine answer.`,
    { label: `find:${lens.split(':')[0]}`, phase: 'Find', schema: FINDINGS }),
  (found, lens) => parallel((found ? found.findings : []).map(f => () =>
    parallel([0, 1].map(k => () => agent(`Try to refute this review finding. Read the code at ${f.file}:${f.line} and its callers.
Finding (${lens.split(':')[0]}): ${f.title}
Claimed failure: ${f.why}
Set refuted=true if the scenario cannot happen, is already handled, or is not a real problem. If unsure, refuted=true. (skeptic ${k + 1})`,
      { label: `verify:${f.file}:${f.line}#${k + 1}`, phase: 'Verify', schema: VOTE })))
      .then(votes => ({ ...f, lens: lens.split(':')[0], upheld: votes.filter(Boolean).filter(v => !v.refuted).length }))
  )),
)

const all = results.filter(Boolean).flat().filter(Boolean)
const confirmed = all.filter(f => f.upheld === 2)
const disputed = all.filter(f => f.upheld === 1)
const rank = { high: 0, medium: 1, low: 2 }
confirmed.sort((a, b) => rank[a.severity] - rank[b.severity])
log(`${all.length} findings, ${confirmed.length} confirmed by both skeptics, ${disputed.length} disputed`)
return { confirmed, disputed }
