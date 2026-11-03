// The stall watchdog's decisions, kept pure (no `$`, no clock of its own) so they can be tested
// with a fake clock and a fake agent list. kit.tsx gathers the facts on its 15 s tick and acts on
// what these functions return: a wake for the coordinator, a native notification for the person.

export type Watch = {
  silentMin: number // a running thread that wrote nothing for this long is checked
  bashDeadlineMin: number // a background command with no declared timeout is checked after this
  permissionMin: number // a thread waiting this long on a permission prompt pings the person
}

export const WATCH_DEFAULTS: Watch = { silentMin: 20, bashDeadlineMin: 30, permissionMin: 2 }

// Wakes per subject: at 1x, 2x and 4x the threshold, the third one also notifying the person.
export const MAX_STRIKES = 3
// Transient API failures: a "continue" nudge after each of these waits, then the person is told.
export const RETRY_DELAYS_MS = [15_000, 30_000, 60_000]
const MIN = 60_000

// kit.json `watchdog`: each threshold overridable, a 0 turns that check off; anything that is
// not a number >= 0 keeps the default.
export function watchConfig(kit: any): Watch {
  const own = kit && typeof kit.watchdog === 'object' && kit.watchdog ? kit.watchdog : {}
  const out = { ...WATCH_DEFAULTS }
  for (const key of Object.keys(out) as (keyof Watch)[]) {
    const v = own[key]
    if (typeof v === 'number' && Number.isFinite(v) && v >= 0) out[key] = v
  }
  return out
}

// "EXPECT: 90m" (or 2h) on a line of a thread's brief: how long the coordinator expects it to run.
export function expectedMs(prompt: string): number | undefined {
  const m = /^\W*EXPECT(?:ED)?:?\s*(\d+(?:\.\d+)?)\s*(m|min|minutes?|h|hours?)\b/im.exec(prompt || '')
  if (!m) return undefined
  return Number(m[1]) * (m[2].startsWith('h') ? 60 : 1) * MIN
}

export type Thread = {
  id: string
  name: string
  status: string
  parentId?: string
  activeAt?: number // the latest of its transcript's mtime and its last tool call
  startedAt?: number
  expectMs?: number
}

export type Job = {
  id: string
  owner?: string // the thread that started it; absent for the main session
  label: string
  startedAt: number
  deadlineMs: number // 0: a server or watcher meant to keep running, never checked
}

export type Strike = { count: number; since: number }
export type Wake = { subject: string; text: string; notify: boolean }

const LIVE = new Set(['running', 'pending'])
const mins = (ms: number) => Math.round(ms / MIN)

// What has stalled since the last tick. `strikes` is updated in place and pruned to the subjects
// that still exist, so it stays as small as the work in flight. `activity` holds the last time the
// main session ("main") or a thread acted, for the owner of a background command.
export function stalls(now: number, threads: Thread[], jobs: Job[], activity: Map<string, number>,
  strikes: Map<string, Strike>, w: Watch): Wake[] {
  const wakes: Wake[] = []
  const seen = new Set<string>()
  const live = threads.filter(t => LIVE.has(t.status) || t.status === 'waiting')
  const liveIds = new Set(live.map(t => t.id))

  const strike = (subject: string, due: boolean, since: number, text: (count: number) => string) => {
    seen.add(subject)
    let s = strikes.get(subject)
    if (s && since > s.since) { // it moved again: this stall is over
      strikes.delete(subject)
      s = undefined
    }
    if (!due || (s && s.count >= MAX_STRIKES)) return
    const count = (s ? s.count : 0) + 1
    strikes.set(subject, { count, since })
    wakes.push({ subject, text: text(count), notify: count === MAX_STRIKES })
  }

  for (const t of threads) {
    if (!LIVE.has(t.status)) continue
    // a thread waiting on its own subagent or background command is the child's to watch; a
    // server it left running (deadline 0) is not something it waits on
    if (live.some(c => c.parentId === t.id) || jobs.some(j => j.owner === t.id && j.deadlineMs > 0)) continue
    const k = strikes.get(`silent:${t.id}`)?.count ?? 0
    if (w.silentMin > 0 && t.activeAt !== undefined) {
      const quiet = now - t.activeAt
      strike(`silent:${t.id}`, quiet >= w.silentMin * MIN * 2 ** k, t.activeAt, count =>
        `kit watchdog: thread ${t.name} (${t.id}) has written nothing for ${mins(quiet)} min. Check it ` +
        `(read the end of its transcript); nudge it with SendMessage if it is stuck, or stop it with TaskStop.` +
        last(count, w.silentMin * 2 ** count))
    }
    if (t.expectMs && t.startedAt !== undefined) {
      const ko = strikes.get(`overdue:${t.id}`)?.count ?? 0
      const ran = now - t.startedAt
      strike(`overdue:${t.id}`, ran >= t.expectMs * 2 ** ko, t.startedAt, count =>
        `kit watchdog: thread ${t.name} (${t.id}) has run ${mins(ran)} min, past the ${mins(t.expectMs)} min its ` +
        `brief expected. Check whether it is still making progress; ask it for a status with SendMessage if unsure.` +
        last(count, mins(t.expectMs * 2 ** count)))
    }
  }

  // background commands, one subject per owner: past its deadline a command matters only while
  // its owner sits waiting on it, quiet for silentMin
  const owners = new Map<string, Job[]>()
  for (const j of jobs) {
    if (!(j.deadlineMs > 0) || (j.owner && !liveIds.has(j.owner))) continue // a gone owner: kit.tsx drops it
    owners.set(j.owner ?? 'main', [...(owners.get(j.owner ?? 'main') ?? []), j])
  }
  for (const [owner, own] of owners) {
    const k = strikes.get(`job:${owner}`)?.count ?? 0
    const ownerAt = Math.max(activity.get(owner) ?? 0, live.find(t => t.id === owner)?.activeAt ?? 0,
      ...own.map(j => j.startedAt))
    const late = now - ownerAt >= w.silentMin * MIN * 2 ** k ? own.filter(j => now >= j.startedAt + j.deadlineMs * 2 ** k) : []
    strike(`job:${owner}`, late.length > 0, ownerAt, count =>
      `kit watchdog: ${owner === 'main' ? 'this session' : `thread ${live.find(t => t.id === owner)?.name} (${owner})`} has waited ${mins(now - ownerAt)} min on ` +
      late.map(j => `background command ${j.id} "${j.label}" (${mins(now - j.startedAt)} min, deadline ${mins(j.deadlineMs)})`).join(', ') +
      `. Read its output file; stop it with TaskStop if it hangs, or leave it if it is still making progress.` +
      last(count, w.silentMin * 2 ** count))
  }

  for (const key of [...strikes.keys()]) if (!seen.has(key)) strikes.delete(key)
  return wakes
}

function last(count: number, nextMin: number): string {
  return count >= MAX_STRIKES
    ? ' This is the last reminder for it; the person has been notified.'
    : ` The next reminder, if it stays like this, comes at ${nextMin} min.`
}

export type PermissionWait = { tool: string; detail: string; since: number; isNotified?: boolean }

// Threads that have waited `permissionMin` on a permission prompt with no activity since it was
// raised: one notification each. A wait whose thread moved on (or is gone) is dropped.
export function permissionWaits(now: number, waits: Map<string, PermissionWait>, threads: Thread[],
  w: Watch): { id: string; text: string }[] {
  const out: { id: string; text: string }[] = []
  for (const [id, p] of [...waits]) {
    const t = threads.find(x => x.id === id)
    // the transcript is written a moment after the request is raised: allow a second for that
    if (!t || (t.activeAt ?? 0) > p.since + 1000) {
      waits.delete(id)
      continue
    }
    if (p.isNotified || w.permissionMin <= 0 || now - p.since < w.permissionMin * MIN) continue
    p.isNotified = true
    out.push({ id, text: `Thread ${t.name} has waited ${mins(now - p.since)} min for your permission: ${p.tool} ${p.detail}`.trim() })
  }
  return out
}

// What a failed API turn needs: `retry` clears on its own (overloaded, a server error, a short
// rate limit); `person` does not (a login, a usage limit or quota, billing, an invalid request).
export function failureKind(error: string, details = ''): 'retry' | 'person' {
  if (/usage limit|hit your (\w+ )?limit|quota|credit|billing|\bresets?\b/i.test(details)) return 'person'
  return ['rate_limit', 'overloaded', 'server_error', 'unknown', 'max_output_tokens'].includes(error) ? 'retry' : 'person'
}

export const CONTINUE_NOTE =
  'Continue where you stopped. Do not repeat an external operation that already completed (a push, a PR, ' +
  'a comment, a paid run); check its result first.'

// Keeps a map below `max` entries by dropping the oldest inserted.
export function bound<K, V>(map: Map<K, V>, max = 200): void {
  while (map.size > max) map.delete(map.keys().next().value as K)
}
