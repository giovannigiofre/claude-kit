export const meta = {
  name: 'ship',
  description: 'Implement a list of tasks in parallel worktrees, verify each independently, fix and re-verify until it passes',
  whenToUse: 'Several independent tasks with checkable done-criteria. args: {tasks: [{id, goal, scope?, done}], maxRounds?: 3, isolate?: true, context?: "project rules or skill to load"}',
  phases: [
    { title: 'Implement', detail: 'one kit:implementer per task' },
    { title: 'Verify', detail: 'independent kit:verifier per task' },
    { title: 'Fix', detail: 'implementer fixes verifier problems, then re-verify' },
  ],
}

const input = args || {}
const tasks = Array.isArray(input) ? input : (input.tasks || [])
const MAX_ROUNDS = input.maxRounds || 3
const ISOLATE = input.isolate !== false
const CONTEXT = input.context ? `\nProject context: ${input.context}` : ''

if (!tasks.length) {
  log('No tasks given. Pass args: {tasks: [{id, goal, scope, done}]}')
  return { results: [] }
}

const IMPL = {
  type: 'object',
  required: ['status', 'changed', 'location', 'checks'],
  properties: {
    status: { type: 'string', enum: ['done', 'blocked', 'partial'] },
    changed: { type: 'array', items: { type: 'string' } },
    location: { type: 'string', description: 'branch name and worktree path, or "main checkout"' },
    checks: { type: 'array', items: { type: 'string' } },
    open: { type: 'array', items: { type: 'string' } },
  },
}

const VERDICT = {
  type: 'object',
  required: ['verdict', 'evidence', 'problems'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL', 'CANNOT_VERIFY'] },
    evidence: { type: 'array', items: { type: 'string' } },
    problems: { type: 'array', items: { type: 'string' } },
    notChecked: { type: 'array', items: { type: 'string' } },
  },
}

const brief = t => `Task ${t.id}: ${t.goal}
Scope: ${t.scope || 'as needed, keep it minimal'}
Done when: ${t.done}${CONTEXT}`

const results = await pipeline(
  tasks,
  t => agent(`${brief(t)}

Implement this task.${ISOLATE ? ' You are in an isolated git worktree: commit your change on its branch when checks pass.' : ''}`,
    { label: `impl:${t.id}`, phase: 'Implement', agentType: 'kit:implementer', schema: IMPL,
      ...(ISOLATE ? { isolation: 'worktree' } : {}) }),
  async (impl, t) => {
    if (!impl) return { id: t.id, verdict: 'FAIL', rounds: 0, note: 'implementer died' }
    if (impl.status === 'blocked') return { id: t.id, verdict: 'BLOCKED', rounds: 0, impl }
    let current = impl
    let v = null
    for (let round = 1; round <= MAX_ROUNDS; round++) {
      v = await agent(`${brief(t)}

The implementer reports: status=${current.status}, location=${current.location}
Changed: ${current.changed.join('; ')}
Their checks: ${current.checks.join('; ')}

Verify independently in that location. Do not trust the summary above.`,
        { label: `verify:${t.id}#${round}`, phase: 'Verify', agentType: 'kit:verifier', schema: VERDICT })
      if (!v) return { id: t.id, verdict: 'CANNOT_VERIFY', rounds: round, impl: current, note: 'verifier died' }
      if (v.verdict !== 'FAIL') return { id: t.id, verdict: v.verdict, rounds: round, impl: current, verification: v }
      if (round === MAX_ROUNDS) break
      const fixed = await agent(`${brief(t)}

Work in: ${current.location} (continue on the same branch/worktree; if it is a worktree path, cd there first).
An independent verifier rejected the change. Fix every problem, re-run the checks, commit.
Problems:
${v.problems.map((p, i) => `${i + 1}. ${p}`).join('\n')}`,
        { label: `fix:${t.id}#${round}`, phase: 'Fix', agentType: 'kit:implementer', schema: IMPL })
      if (!fixed) break
      current = fixed
    }
    return { id: t.id, verdict: 'FAIL', rounds: MAX_ROUNDS, impl: current, verification: v }
  },
)

const clean = results.map((r, i) => r || { id: tasks[i].id, verdict: 'FAIL', note: 'pipeline dropped the task' })
const passed = clean.filter(r => r.verdict === 'PASS').length
log(`${passed}/${clean.length} tasks verified PASS`)
return { results: clean }
