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
  prompt?: { tool: string; detail: string; since: number } // a permission prompt it waits on
}

export type Job = {
  id: string
  owner?: string // the thread that started it; absent for the main session
  label: string
  startedAt: number
  deadlineMs: number // 0: a server or watcher meant to keep running, never checked
  declared?: boolean // the deadline is the command's own timeout, not the bashDeadlineMin default
  holder?: boolean // it waits on its owner's own later action (isHolder): it never ends by itself
  endedAt?: number // its output file ends with Claude Code's exit line, written then
  ending?: string // that line, after the last result lines above it (outputEnd)
}

// Claude Code ends a finished background command's output file with "[exited with code N]" (or
// "[killed]"): that line, after the two result lines above it, or undefined while it runs.
export function outputEnd(text: string): string | undefined {
  const m = /\[(exited with code -?\d+|killed)\]\s*$/.exec(text || '')
  if (!m) return undefined
  const above = text.slice(0, m.index).split('\n').map(l => l.trim()).filter(Boolean).slice(-2)
  return [...above.map(l => l.slice(0, 100)), `[${m[1]}]`].join(' / ')
}

// A hold loop: a command that only ends when its owner acts again (removes a file, kills it), so
// an owner that waits on it waits on itself. Its description or its command says so.
export function isHolder(text: string): boolean {
  return /\bhold(s|ing|er)?\b|\bwhile\s+\[\s+-[efs]\s|\buntil\s+\[\s+!\s+-[efs]\s|\bsleep\s+infinity\b|\btail\s+-f\s+\/dev\/null\b/i.test(text || '')
}

// Claude Code's interim task notice: a thread stopped with background work of its own still
// running, and has not reported. It changes nothing for the coordinator (the same task id notifies
// again with the report, and the `stuck` check below catches work that ended without waking it),
// yet each one is a turn. True only when every `<task-notification>` in the text is such a notice
// and nothing else is there but Claude Code's own preamble, so a real hand-back, a command's
// notice or anything typed beside them is never held.
const NOTICE = /<task-notification>([\s\S]*?)<\/task-notification>/g
const PREAMBLE = /^(\[SYSTEM NOTIFICATION\b|This is an automated background-task event|Do NOT interpret this|No human input has been received)/
export function isInterimNotice(text: string): boolean {
  const blocks = [...String(text || '').matchAll(NOTICE)].map(m => m[1])
  if (blocks.length === 0) return false
  const interim = (b: string) => {
    const summary = /<summary>([\s\S]*?)<\/summary>/.exec(b)?.[1] ?? ''
    const result = /<result>([\s\S]*?)<\/result>/.exec(b)?.[1]
    return /is waiting on its own background work/i.test(summary) && (result === undefined || /has not reported yet/i.test(result))
  }
  if (!blocks.every(interim)) return false
  const rest = String(text).replace(NOTICE, '').split('\n').map(l => l.trim()).filter(l => l && !PREAMBLE.test(l))
  return rest.length === 0
}

export type Strike = { count: number; since: number }
export type Wake = { subject: string; text: string; notify: boolean }

const LIVE = new Set(['running', 'pending'])
// A thread parked on its own background work, all of which has ended or never will: the notice
// that would wake it is due within seconds, so a few minutes without it is a stall.
export const STUCK_MIN = 5
const mins = (ms: number) => Math.round(ms / MIN)
// what a thread can wait on: a command that is running, has a deadline and ends by itself
const pending = (j: Job) => j.deadlineMs > 0 && !j.holder && j.endedAt === undefined

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

  // parked on its own background work (Claude Code's `waiting`), none of which will wake it
  for (const t of live) {
    if (t.status !== 'waiting' || live.some(c => c.parentId === t.id)) continue
    const own = jobs.filter(j => j.owner === t.id)
    if (own.length === 0 || own.some(pending)) continue
    const k = strikes.get(`stuck:${t.id}`)?.count ?? 0
    const since = Math.max(t.activeAt ?? 0, ...own.map(j => j.endedAt ?? j.startedAt))
    strike(`stuck:${t.id}`, now - since >= STUCK_MIN * MIN * 2 ** k, since, count =>
      `kit watchdog: thread ${t.name} (${t.id}) has waited ${mins(now - since)} min on its own background work, ` +
      `but nothing it waits on will wake it.` + notes(now, t, jobs) + last(count, STUCK_MIN * 2 ** count))
  }

  for (const t of threads) {
    if (!LIVE.has(t.status)) continue
    // a thread waiting on its own subagent or background command is the child's to watch; a
    // server it left running (deadline 0), a holder or a command that ended is not something
    // it waits on
    if (live.some(c => c.parentId === t.id) || jobs.some(j => j.owner === t.id && pending(j))) continue
    const k = strikes.get(`silent:${t.id}`)?.count ?? 0
    if (w.silentMin > 0 && t.activeAt !== undefined) {
      const quiet = now - t.activeAt
      strike(`silent:${t.id}`, quiet >= w.silentMin * MIN * 2 ** k, t.activeAt, count =>
        `kit watchdog: thread ${t.name} (${t.id}) has written nothing for ${mins(quiet)} min.` +
        (notes(now, t, jobs) || ` Check it (read the end of its transcript); nudge it with SendMessage if it is stuck, or stop it with TaskStop.`) +
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
  // its owner sits waiting on it, quiet for silentMin. A thread still within its brief's EXPECT
  // is waiting on its own work as planned: only a command past the timeout it declared counts
  // (the default deadline is a guess, and the overdue check speaks once EXPECT has passed).
  const withinExpect = (owner: string) => {
    const t = live.find(x => x.id === owner)
    return !!t && !!t.expectMs && t.startedAt !== undefined && now < t.startedAt + t.expectMs
  }
  const owners = new Map<string, Job[]>()
  for (const j of jobs) {
    if (!pending(j) || (j.owner && !liveIds.has(j.owner))) continue // a gone owner: kit.tsx drops it
    owners.set(j.owner ?? 'main', [...(owners.get(j.owner ?? 'main') ?? []), j])
  }
  for (const [owner, own] of owners) {
    const k = strikes.get(`job:${owner}`)?.count ?? 0
    const ownerAt = Math.max(activity.get(owner) ?? 0, live.find(t => t.id === owner)?.activeAt ?? 0,
      ...own.map(j => j.startedAt))
    const planned = withinExpect(owner)
    const late = now - ownerAt >= w.silentMin * MIN * 2 ** k
      ? own.filter(j => now >= j.startedAt + j.deadlineMs * 2 ** k && (j.declared || !planned)) : []
    strike(`job:${owner}`, late.length > 0, ownerAt, count =>
      `kit watchdog: ${owner === 'main' ? 'this session' : `thread ${live.find(t => t.id === owner)?.name} (${owner})`} has waited ${mins(now - ownerAt)} min on ` +
      late.map(j => `background command ${j.id} "${j.label}" (${mins(now - j.startedAt)} min, deadline ${mins(j.deadlineMs)})`).join(', ') +
      `. Read its output file; stop it with TaskStop if it hangs, or leave it if it is still making progress.` +
      (owner === 'main' ? '' : notes(now, live.find(t => t.id === owner), jobs)) +
      last(count, w.silentMin * 2 ** count))
  }

  for (const key of [...strikes.keys()]) if (!seen.has(key)) strikes.delete(key)
  return wakes
}

// What else holds a quiet thread, each with what the coordinator can do about it without reading
// the transcript: a permission prompt, a command that ended unnoticed, a holder.
function notes(now: number, t: Thread | undefined, jobs: Job[]): string {
  if (!t) return ''
  const out: string[] = []
  if (t.prompt) {
    out.push(` It has waited ${mins(now - t.prompt.since)} min on a permission prompt (${`${t.prompt.tool} ${t.prompt.detail}`.trim()}): ` +
      `only the person can answer it, so put it under NEEDS YOU; a message to the thread only queues behind it.`)
  }
  const own = jobs.filter(j => j.owner === t.id)
  for (const j of own.filter(j => j.endedAt !== undefined)) {
    out.push(` Its background command ${j.id} "${j.label}" ended ${mins(now - j.endedAt!)} min ago and it has not acted ` +
      `since (its output ends: ${j.ending ?? 'an exit line'}): the notice was lost or the thread is blocked.`)
  }
  for (const j of own.filter(j => j.holder && j.endedAt === undefined)) {
    out.push(` Its background command ${j.id} "${j.label}" is a holder: it ends only when the thread acts again, so the ` +
      `thread must not wait on it; remove what it waits for, or stop it with TaskStop ${j.id}.`)
  }
  if (out.length === 0) return ''
  return out.join('') + ` To resume it: TaskStop ${t.id}, then SendMessage ${t.id} with what it missed (the result lines, ` +
    `the answer); a stopped thread resumes from its transcript. Tell it to run the rest in the foreground.`
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
