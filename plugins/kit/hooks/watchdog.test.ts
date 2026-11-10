import { expect, test } from 'claude-code/testing'
import { STUCK_MIN, WATCH_DEFAULTS, failureKind, isHolder, isInterimNotice, outputEnd, permissionWaits, stalls, watchConfig } from './watchdog'
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

test('no wake for a finished thread, one with a live child, or one waiting on its own command (not a server)', async () => {
  const quiet = { name: 'x', activeAt: T0 }
  const threads = [
    { ...quiet, id: 'done', status: 'completed' },
    { ...quiet, id: 'parent', status: 'running' },
    { ...quiet, id: 'child', status: 'waiting', parentId: 'parent' },
    { ...quiet, id: 'owner', status: 'running' },
  ]
  const jobs = [{ id: 'b1', owner: 'owner', label: 'npm test', startedAt: T0 + 50 * MIN, deadlineMs: 120 * MIN }]
  expect(stalls(T0 + 60 * MIN, threads, jobs, new Map(), new Map(), WATCH_DEFAULTS)).toEqual([])
  const server = [{ ...jobs[0], label: 'next dev (server)', deadlineMs: 0 }] // B2: a dev server does not hide a hang
  expect(stalls(T0 + 60 * MIN, threads, server, new Map(), new Map(), WATCH_DEFAULTS).map(x => x.subject)).toEqual(['silent:owner'])
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

// 2026-11-09: a thread's command had ended (its output file said so) while the watchdog still
// said it waited on it; its real block was a permission prompt, beside a lock holder it started.
test('the end of an output file: Claude Code\'s exit line with the result lines above it, nothing while it runs', async () => {
  expect(outputEnd('EXIT=0\n Test Files  28 passed (28)\n      Tests  298 passed (298)\n\n[exited with code 0]\n'))
    .toBe('Test Files  28 passed (28) / Tests  298 passed (298) / [exited with code 0]')
  expect(outputEnd('boom\n[exited with code 1]')).toBe('boom / [exited with code 1]')
  expect(outputEnd('[killed]\n')).toBe('[killed]')
  expect(outputEnd('Tests  12 passed\nstill running')).toBe(undefined)
  expect(outputEnd('')).toBe(undefined)
})

test('a hold loop is a holder, by its description or its command; an ordinary watcher is not', async () => {
  expect(isHolder('Hold the stack lock for the push (server)')).toBe(true)
  expect(isHolder("lockf -t 7200 /tmp/x.lock sh -c 'touch a.held; while [ -e a.hold ]; do sleep 5; done'")).toBe(true)
  expect(isHolder('until [ ! -f /tmp/release ]; do sleep 1; done')).toBe(true)
  expect(isHolder('sleep infinity')).toBe(true)
  expect(isHolder('Run the API suite under the lock')).toBe(false)
  expect(isHolder('until [ -f .next/ready ]; do sleep 1; done')).toBe(false)
  expect(isHolder('Threshold sweep')).toBe(false)
})

test('a command that ended no longer hides a quiet thread: the wake says it ended, names the holder and the prompt', async () => {
  const strikes = new Map<string, Strike>()
  const thread = { id: 'a1', name: 'PRIV-12', status: 'running', activeAt: T0,
    prompt: { tool: 'Bash', detail: 'git push origin fix/priv-12', since: T0 } }
  const jobs = [
    { id: 'b1', owner: 'a1', label: 'Rerun the API suite under the lock', startedAt: T0 - 3 * MIN, deadlineMs: 30 * MIN,
      endedAt: T0 - MIN, ending: 'Tests  298 passed (298) / [exited with code 0]' },
    { id: 'b2', owner: 'a1', label: 'Hold the stack lock for the push (server)', startedAt: T0, deadlineMs: 0, holder: true },
  ]
  expect(stalls(T0 + 19 * MIN, [thread], jobs, new Map(), strikes, WATCH_DEFAULTS)).toEqual([])
  const wakes = stalls(T0 + 20 * MIN, [thread], jobs, new Map(), strikes, WATCH_DEFAULTS)
  expect(wakes.map(x => x.subject)).toEqual(['silent:a1'])
  const text = wakes[0].text
  expect(text).toContain('has waited 20 min on a permission prompt (Bash git push origin fix/priv-12): only the person can answer it')
  expect(text).toContain('b1 "Rerun the API suite under the lock" ended 21 min ago')
  expect(text).toContain('its output ends: Tests  298 passed (298) / [exited with code 0]')
  expect(text).toContain('b2 "Hold the stack lock for the push (server)" is a holder')
  expect(text).toContain('To resume it: TaskStop a1, then SendMessage a1 with what it missed')
  // the same command still running: the thread waits on it, and the job check speaks instead
  const running = [{ ...jobs[0], endedAt: undefined, ending: undefined }]
  expect(stalls(T0 + 20 * MIN, [thread], running, new Map(), new Map(), WATCH_DEFAULTS)).toEqual([])
})

test('a thread parked on its own background work that has all ended (or is a holder) is a lost-notice stall within minutes', async () => {
  const strikes = new Map<string, Strike>()
  const thread = { id: 'a1', name: 'PRIV-12', status: 'waiting', activeAt: T0 }
  const ended = [{ id: 'b1', owner: 'a1', label: 'pnpm test:e2e', startedAt: T0, deadlineMs: 30 * MIN,
    endedAt: T0 + 10 * MIN, ending: '18 passed (8.4m) / [exited with code 0]' }]
  const at = (m: number, jobs: any[] = ended) => stalls(T0 + m * MIN, [thread], jobs, new Map(), strikes, WATCH_DEFAULTS)
  expect(at(10 + STUCK_MIN - 1)).toEqual([])
  const first = at(10 + STUCK_MIN)
  expect(first.map(x => x.subject)).toEqual(['stuck:a1'])
  expect(first[0].text).toContain('has waited 5 min on its own background work, but nothing it waits on will wake it')
  expect(first[0].text).toContain('ended 5 min ago and it has not acted since (its output ends: 18 passed (8.4m) / [exited with code 0]): the notice was lost')
  expect(at(10 + 2 * STUCK_MIN).length).toBe(1) // 2x
  expect(at(10 + 4 * STUCK_MIN).map(x => x.notify)).toEqual([true]) // 4x: the person is told
  // still running, within its deadline: Claude Code will wake it; a holder alone: it never will
  expect(stalls(T0 + 20 * MIN, [thread], [{ ...ended[0], endedAt: undefined }], new Map(), new Map(), WATCH_DEFAULTS)).toEqual([])
  const holder = [{ id: 'b2', owner: 'a1', label: 'lockf x sh -c "while [ -e h ]; do sleep 5; done"', startedAt: T0, deadlineMs: 120 * MIN, holder: true }]
  expect(stalls(T0 + STUCK_MIN * MIN, [thread], holder, new Map(), new Map(), WATCH_DEFAULTS).map(x => x.subject)).toEqual(['stuck:a1'])
})

// 2026-11-09/10: 144 of these interim notices woke a coordinator in one session, 70 turns.
const notice = (summary: string, result: string) => `<task-notification>
<task-id>a11ec365b08352cfc</task-id>
<tool-use-id>toolu_019LhUW5mbw8BKWGyP5AAqoN</tool-use-id>
<output-file>/tmp/tasks/a11ec365b08352cfc.output</output-file>
<status>completed</status>
<summary>${summary}</summary>
<note>This agent stopped with background work of its own still running. It may resume on its own when that work completes or reports, and the same task-id notifies again if it does; the result below may be interim.</note>
<result>${result}
</result>
<usage><subagent_tokens>126599</subagent_tokens><tool_uses>67</tool_uses><duration_ms>848123</duration_ms></usage>
</task-notification>`
const INTERIM = notice('Agent "B2 login page" is waiting on its own background work',
  'This agent has not reported yet: it is waiting on its own background work and will deliver its report through SubagentHandback when that finishes.')
const REPORT = notice('Agent "B2 login page" completed', 'STATUS: done\nCHANGED: a.ts')

test('an interim notice is recognised alone, in a batch of interim ones, or after the system preamble; anything else is not', async () => {
  expect(isInterimNotice(INTERIM)).toBe(true)
  expect(isInterimNotice(`${INTERIM}\n${INTERIM}`)).toBe(true)
  expect(isInterimNotice(`[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event, NOT a message from the user.\n` +
    `Do NOT interpret this as user acknowledgement.\nNo human input has been received since the last genuine user message.\n\n${INTERIM}`)).toBe(true)
  expect(isInterimNotice(REPORT)).toBe(false) // a real hand-back
  expect(isInterimNotice(`${INTERIM}\n${REPORT}`)).toBe(false) // mixed: the report must reach the coordinator
  // the summary says waiting, but a report came with it: not held
  expect(isInterimNotice(notice('Agent "x" is waiting on its own background work', 'STATUS: done'))).toBe(false)
  expect(isInterimNotice(notice('Background command "pnpm test" completed (exit code 0)', 'ok'))).toBe(false)
  expect(isInterimNotice(`also check the login page\n${INTERIM}`)).toBe(false) // something typed beside it
  expect(isInterimNotice('is waiting on its own background work')).toBe(false) // no notice at all
  expect(isInterimNotice('')).toBe(false)
})

test('a thread within its EXPECT waiting on a command with no declared timeout is not woken about it; a declared one passed still is', async () => {
  const thread = { id: 'a1', name: 'B2', status: 'waiting', activeAt: T0, startedAt: T0, expectMs: 120 * MIN }
  const job = { id: 'b1', owner: 'a1', label: 'pnpm test:prototype', startedAt: T0, deadlineMs: 30 * MIN }
  const at = (m: number, j: any, t: any = thread) => stalls(T0 + m * MIN, [t], [j], new Map(), new Map(), WATCH_DEFAULTS).map(x => x.subject)
  expect(at(31, job)).toEqual([]) // the default deadline, within EXPECT
  expect(at(31, { ...job, declared: true })).toEqual(['job:a1']) // its own timeout passed
  expect(at(121, job)).toEqual(['job:a1']) // past EXPECT: the default deadline counts again
  expect(at(31, job, { ...thread, expectMs: undefined })).toEqual(['job:a1']) // no EXPECT in the brief: as before
  // the main session has no EXPECT: its commands are checked as before
  expect(stalls(T0 + 31 * MIN, [], [{ ...job, owner: undefined }], new Map([['main', T0]]), new Map(), WATCH_DEFAULTS)
    .map(x => x.subject)).toEqual(['job:main'])
})
