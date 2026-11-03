import { expect, test } from 'claude-code/testing'
import { WATCH_DEFAULTS, failureKind, permissionWaits, stalls, watchConfig } from './watchdog'
import type { Strike } from './watchdog'

const MIN = 60_000
const T0 = 1_000_000_000

test('a silent thread wakes the coordinator at 20, 40 and 80 min, the third time notifying; activity resets it', async () => {
  const strikes = new Map<string, Strike>()
  const thread = { id: 'a1', name: 'B2', status: 'running', activeAt: T0 }
  const at = (m: number, t = thread) => stalls(T0 + m * MIN, [t], [], new Map(), strikes, WATCH_DEFAULTS)
  expect(at(19)).toEqual([])
  expect(at(20).map(x => x.notify)).toEqual([false])
  expect(at(30)).toEqual([]) // one wake per stall
  expect(at(40).map(x => x.notify)).toEqual([false])
  expect(at(80).map(x => x.notify)).toEqual([true])
  expect(at(500)).toEqual([]) // three strikes, then quiet
  const moved = { ...thread, activeAt: T0 + 600 * MIN }
  expect(at(610, moved)).toEqual([])
  expect(at(620, moved).length).toBe(1)
})

test('no wake for a finished thread, one with a live child, or one waiting on its own command', async () => {
  const quiet = { name: 'x', activeAt: T0 }
  const threads = [
    { ...quiet, id: 'done', status: 'completed' },
    { ...quiet, id: 'parent', status: 'running' },
    { ...quiet, id: 'child', status: 'waiting', parentId: 'parent' },
    { ...quiet, id: 'owner', status: 'running' },
  ]
  const jobs = [{ id: 'b1', owner: 'owner', label: 'npm test', startedAt: T0 + 50 * MIN, deadlineMs: 120 * MIN }]
  expect(stalls(T0 + 60 * MIN, threads, jobs, new Map(), new Map(), WATCH_DEFAULTS)).toEqual([])
})

test('a background command past its deadline wakes its owner once, unless the owner is still acting; a server never', async () => {
  const strikes = new Map<string, Strike>()
  const jobs = [
    { id: 'b1', label: 'gh pr checks --watch', startedAt: T0, deadlineMs: 30 * MIN },
    { id: 'b2', label: 'next dev (server)', startedAt: T0, deadlineMs: 0 },
    { id: 'b3', label: 'paid run', startedAt: T0, deadlineMs: 30 * MIN },
  ]
  const activity = new Map([['main', T0 + 10 * MIN]])
  const wakes = stalls(T0 + 31 * MIN, [], jobs.slice(0, 2), activity, strikes, WATCH_DEFAULTS)
  expect(wakes.map(x => x.subject)).toEqual(['job:main'])
  expect(wakes[0].text).toContain('b1 "gh pr checks --watch"')
  expect(stalls(T0 + 32 * MIN, [], jobs.slice(0, 2), activity, strikes, WATCH_DEFAULTS)).toEqual([])
  expect(stalls(T0 + 31 * MIN, [], [jobs[2]], new Map([['main', T0 + 30.5 * MIN]]), new Map(), WATCH_DEFAULTS)).toEqual([])
  stalls(T0 + 33 * MIN, [], [], activity, strikes, WATCH_DEFAULTS)
  expect(strikes.size).toBe(0) // a command that ended leaves nothing behind
})

test('a thread past its brief\'s EXPECT is flagged even while it is busy', async () => {
  const t = { id: 'a1', name: 'K10', status: 'running', activeAt: T0 + 59 * MIN, startedAt: T0, expectMs: 45 * MIN }
  const wakes = stalls(T0 + 60 * MIN, [t], [], new Map(), new Map(), WATCH_DEFAULTS)
  expect(wakes.map(x => x.subject)).toEqual(['overdue:a1'])
})

test('a permission prompt left 2 min notifies once; one the thread moved past is dropped', async () => {
  const waits = new Map([['a1', { tool: 'Bash', detail: 'git push', since: T0 }], ['a2', { tool: 'Edit', detail: 'x', since: T0 }]])
  const threads = [{ id: 'a1', name: 'B2', status: 'running', activeAt: T0 }, { id: 'a2', name: 'C3', status: 'running', activeAt: T0 + MIN }]
  expect(permissionWaits(T0 + 1.5 * MIN, waits, threads, WATCH_DEFAULTS)).toEqual([])
  expect(waits.has('a2')).toBe(false)
  expect(permissionWaits(T0 + 2 * MIN, waits, threads, WATCH_DEFAULTS).map(x => x.text)).toEqual(['Thread B2 has waited 2 min for your permission: Bash git push'])
  expect(permissionWaits(T0 + 5 * MIN, waits, threads, WATCH_DEFAULTS)).toEqual([])
})

test('API failures: overload retries, a login or a usage limit needs the person; kit.json overrides thresholds', async () => {
  expect(failureKind('overloaded')).toBe('retry')
  expect(failureKind('authentication_failed')).toBe('person')
  expect(failureKind('rate_limit', "You've hit your weekly limit · resets 4pm (Europe/Zurich)")).toBe('person')
  expect(failureKind('rate_limit', 'Request rate limited')).toBe('retry')
  expect(watchConfig({ watchdog: { silentMin: 45, bashDeadlineMin: 'x', permissionMin: 0 } })).toEqual({ silentMin: 45, bashDeadlineMin: 30, permissionMin: 0 })
})
