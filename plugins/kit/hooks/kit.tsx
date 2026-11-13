// The kit's one hooks module: a status line entry, the stall watchdog and the interim-notice drop.
//
// The coordinator's routing is not here: session_start.py prints it in a kit project, so a cloud
// session or Remote Control without this mod still has it, and the coordinator's own
// PushNotification reaches the phone (this mod's native notification for board changes showed
// on the computer the person was away from, and is gone with the light/loop/ask modes, 2026-11).
// - The status line: `sandbox` while Claude Code's Bash sandbox is on, `away` while
//   permissions.denyInsteadOfPrompting is (items.py `away on`), session cost, threads running and
//   waiting for an answer, live overnight runs, board items queued, ready for review and questions
//   for the person, re-read every 15 seconds.
// - The stall watchdog, on the same tick (watchdog.ts decides, this module gathers and acts): a
//   thread silent too long or past its brief's EXPECT, a background command past its deadline, a
//   thread that ended without a report, a thread waiting on a permission prompt, and a turn that
//   failed on the API. It wakes the coordinator (a prompt of its own) or notifies the person;
//   it never approves, stops or retries anything itself, and on any error it stays quiet.
// - Interim notices: Claude Code's "Agent X is waiting on its own background work" task notice
//   is dropped before it becomes a turn; a real report, a command's notice or anything mixed in
//   passes unchanged.
import type { EngineInterface, Register, Timer } from 'claude-code'
import { CONTINUE_NOTE, RETRY_DELAYS_MS, bound, expectedMs, failureKind, isHolder, isInterimNotice, outputEnd, permissionWaits, stalls, watchConfig } from './watchdog'
import type { Job, PermissionWait, Strike, Thread } from './watchdog'

type $ = EngineInterface

let rootCache: string | undefined
// the status line: what was last shown, the last board that could be read, the 15 s tick
let lastStatus: string | undefined
let tick: Timer | undefined

async function projectRoot($: $): Promise<string> {
  if (rootCache) return rootCache
  const cwd = await $.session.cwd()
  try {
    const out = await $.process.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'])
    rootCache = out.exitCode === 0 && out.stdout.trim() ? out.stdout.trim() : cwd
  } catch {
    rootCache = cwd
  }
  return rootCache
}

// The project's kit.json: the checkout's own, else its main checkout's. kit.json is personal and
// kept out of git by default, so a linked worktree has none of its own.
async function kitJsonPath($: $, root: string): Promise<string> {
  const own = `${root}/.claude/kit.json`
  const readable = async (path: string) => {
    try {
      await $.fs.read(path)
      return true
    } catch {
      return false
    }
  }
  if (await readable(own)) return own
  try {
    const out = await $.process.run(['git', '-C', root, 'rev-parse', '--path-format=absolute', '--git-common-dir'])
    const common = out.exitCode === 0 ? out.stdout.trim() : ''
    const main = common.endsWith('/.git') ? `${common.slice(0, -5)}/.claude/kit.json` : ''
    if (main && main !== own && (await readable(main))) return main
  } catch {
    // no git: the checkout's own path
  }
  return own
}

async function readJson($: $, path: string): Promise<any> {
  try {
    return JSON.parse(await $.fs.read(path))
  } catch {
    return undefined
  }
}

// { exists, value } for a file the kit may rewrite: a file that exists and does not parse is
// reported as such, so the kit never replaces it.
async function readJsonForWrite($: $, path: string): Promise<{ exists: boolean; value: any; isBroken: boolean }> {
  let text: string
  try {
    text = await $.fs.read(path)
  } catch {
    return { exists: false, value: {}, isBroken: false }
  }
  try {
    const value = JSON.parse(text)
    return { exists: true, value: value && typeof value === 'object' ? value : {}, isBroken: !(value && typeof value === 'object') }
  } catch {
    return { exists: true, value: {}, isBroken: true }
  }
}

// What the merged settings say about the sandbox and the away switch, for the status line only.
async function settingFlags($: $): Promise<{ sandbox: boolean; away: boolean }> {
  const read = async (key: string) => {
    try {
      return (await $.settings.read({ key })) as any
    } catch {
      return undefined
    }
  }
  const sandbox = await read('sandbox')
  const permissions = await read('permissions')
  return { sandbox: !!(sandbox && sandbox.enabled === true), away: !!(permissions && permissions.denyInsteadOfPrompting === true) }
}

// What the coordinator's board says, by item id: what needs the person (with the question when
// the NEEDS YOU line gives one), what is ready for review, at work and queued. Ids, not counts:
// "1 ready · 2 need you" told the person nothing they could act on, and the counts did not add up
// with the engine's "running" (which also counts a verifier, an Explore agent, another plugin's).
type Board = { needs: string[]; ready: string[]; working: string[]; queued: string[]; questions: Record<string, string> }

const STATUS_WORDS = 'queued|working|review|needs-you|landing|done|parked'
const STATUS_CELL = new RegExp(`^(${STATUS_WORDS})$`)      // a cell that is a status and nothing else
const STATUS_START = new RegExp(`^(${STATUS_WORDS})\\b`)   // the status cell itself may add a note

// One board row as [id, status]. The reference puts the status in the fifth cell, but a model
// renders the board readily as a Markdown table (outer pipes, a header and a separator row),
// capitalises a word or drops a cell, so: outer pipes stripped, emphasis stripped, any case, the
// fifth cell first and else the only cell that is exactly a status word ("DONE WHEN e2e" is not
// `done`: read as one, it made a row with a dropped cell count as nothing).
function boardRow(line: string): [string, string] | undefined {
  const cells = line.replace(/^\|/, '').replace(/\|$/, '').split('|')
    .map(c => c.trim().replace(/[*_`]/g, ''))
  if (cells.length < 2) return undefined
  const lower = cells.map(c => c.toLowerCase())
  if (lower.every(c => c === '' || /^:?-+:?$/.test(c))) return undefined // a table's separator row
  if (lower.includes('status') || lower[0] === 'id') return undefined // its header row
  const fifth = lower[4] && STATUS_START.exec(lower[4])?.[1]
  const exact = lower.filter(c => STATUS_CELL.test(c))
  const status = fifth || (exact.length === 1 ? exact[0] : undefined)
  return status && cells[0] ? [cells[0], status] : undefined
}

function readBoardText(text: string): Board {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean).filter(l => !l.startsWith('```'))
  const board: Board = { needs: [], ready: [], working: [], queued: [], questions: {} }
  const add = (list: string[], id: string) => {
    if (!list.some(x => x.toLowerCase() === id.toLowerCase())) list.push(id)
  }
  const needsLine = lines.find(l => /^NEEDS YOU:/i.test(l))
  if (needsLine) {
    const rest = needsLine.slice('NEEDS YOU:'.length).trim()
    if (rest && !/^(empty|none|-)$/i.test(rest)) {
      // entries are `<id>: <question>`; a `;` inside a question starts no new entry
      const entries = rest.split(/;\s*(?=[A-Za-z0-9][\w.-]*\s*:)/).map(x => x.trim()).filter(Boolean)
      entries.forEach((entry, i) => {
        const m = /^([A-Za-z0-9][\w.-]*)\s*:\s*(.*)$/.exec(entry)
        const id = m ? m[1] : `question ${i + 1}`
        add(board.needs, id)
        board.questions[id.toLowerCase()] = (m ? m[2] : entry).replace(/;+$/, '').trim()
      })
    }
  }
  for (const line of lines) {
    if (!line.includes('|') || /^(SHIP|RULES|NEEDS YOU):/i.test(line) || line.startsWith('<')) continue
    const row = boardRow(line)
    if (!row) continue
    const [id, status] = row
    if (status === 'needs-you') add(board.needs, id) // also on the NEEDS YOU line: once
    else if (status === 'review') add(board.ready, id)
    else if (status === 'working' || status === 'landing') add(board.working, id)
    else if (status === 'queued') add(board.queued, id)
  }
  return board
}

// `needs you 2: a2-region, pr-328`: the count, then the first ids (a long id cut), then `+n`.
const SHOWN_IDS = 2
function named(label: string, ids: string[]): string {
  const cut = (id: string) => (id.length > 22 ? `${id.slice(0, 21)}…` : id)
  const more = ids.length > SHOWN_IDS ? ` +${ids.length - SHOWN_IDS}` : ''
  return `${label} ${ids.length}: ${ids.slice(0, SHOWN_IDS).map(cut).join(', ')}${more}`
}

// The kit's working state lives in `.kit/` at the repo root; a project the kit has not moved yet
// still has it in `.claude/` (Claude Code protects that folder, so threads stalled on prompts
// writing there). Both are read, `.kit` first, as kitlib.state_entry does.
const STATE_DIRS = ['.kit', '.claude']
const LEGACY_BOARD = '.claude/lead/board.md' // the default /kit:init wrote into kit.json

// The board from kit.json `lead.board` or the default path: null when there is no board,
// undefined when it (or kit.json) exists but could not be read this time.
async function readBoard($: $, root: string): Promise<Board | null | undefined> {
  const kitJson = await readJsonForWrite($, await kitJsonPath($, root))
  if (kitJson.isBroken) return undefined
  const lead = kitJson.value.lead
  const custom = typeof (lead && lead.board) === 'string' ? lead.board.trim().replace(/^\.\//, '') : ''
  const paths = custom && custom !== LEGACY_BOARD
    ? [custom.startsWith('/') ? custom : `${root}/${custom}`]
    : STATE_DIRS.map(dir => `${root}/${dir}/lead/board.md`)
  for (const path of paths) {
    try {
      return readBoardText(await $.fs.read(path))
    } catch {
      // the next place, or none
    }
  }
  for (const path of paths) {
    try {
      if (await $.fs.exists(path)) return undefined
    } catch {
      return undefined
    }
  }
  return null
}

// Overnight runs still going, in the project and each of its worktrees.
async function liveOvernightRuns($: $, root: string): Promise<number> {
  const roots = new Set<string>([root])
  try {
    const out = await $.process.run(['git', '-C', root, 'worktree', 'list', '--porcelain'])
    for (const line of out.stdout.split('\n')) if (line.startsWith('worktree ')) roots.add(line.slice(9).trim())
  } catch {
    // no git: only the project folder
  }
  let live = 0
  for (const r of roots) {
    for (const dir of STATE_DIRS) {
      let entries: { name: string; kind: string }[] = []
      try {
        entries = (await $.fs.list(`${r}/${dir}/overnight`)) as any
      } catch {
        continue
      }
      for (const entry of entries) {
        if (entry.kind !== 'dir') continue
        const state = await readJson($, `${r}/${dir}/overnight/${entry.name}/state.json`)
        if (state && !state.stop_reason) live++
      }
    }
  }
  return live
}

// Threads at work, and threads waiting for an answer (a question, a permission): the second
// kind needs the person as much as a NEEDS YOU line on the board.
async function agentCounts($: $): Promise<{ running: number; waiting: number }> {
  try {
    const agents = await $.agent.list()
    return {
      running: agents.filter(a => a.status === 'running' || a.status === 'pending').length,
      waiting: agents.filter(a => (a.status as string) === 'waiting').length,
    }
  } catch {
    return { running: 0, waiting: 0 }
  }
}

async function notify($: $, text: string): Promise<void> {
  try {
    // an engine without $.ui.notify, or without a channel, throws here: the line still shows it
    await $.ui.notify(text, { title: 'kit' })
  } catch {
    // nothing to do
  }
}

let lastBoard: Board | null = null

// Everything on the line is read again on each call: the board is one small file, a board that
// could not be read keeps the last counts, a board that is gone clears them.
async function refreshStatus($: $): Promise<void> {
  const root = await projectRoot($)
  const flags = await settingFlags($)
  let costUsd: number | null = null
  try {
    const usage = await $.session.usage()
    costUsd = usage.cost ? usage.cost.usd : null
  } catch {
    // spend unavailable: draw without it
  }
  const board = await readBoard($, root)
  if (board !== undefined) lastBoard = board
  const { running, waiting } = await agentCounts($)
  const live = await liveOvernightRuns($, root)
  const parts: string[] = []
  if (flags.sandbox) parts.push('sandbox')
  // a forgotten `away on` shows here the next morning
  if (flags.away) parts.push('away')
  if (costUsd !== null) parts.push(`$${costUsd.toFixed(2)}`)
  // what needs the person first, by name; the board's own rows for work in hand, so the numbers
  // are the ones the coordinator reports. Without a board, the engine's threads.
  const b = lastBoard
  if (b && b.needs.length) parts.push(named('needs you', b.needs))
  if (b && b.ready.length) parts.push(named('ready', b.ready))
  if (b && b.working.length) parts.push(named('working', b.working))
  else if (running) parts.push(`${running} running`)
  if (waiting) parts.push(`${waiting} waiting on a prompt`)
  if (b && b.queued.length) parts.push(`queued ${b.queued.length}`)
  if (live) parts.push(`${live} overnight`)
  const status = parts.join(' · ')
  if (status === lastStatus) return
  lastStatus = status
  $.ui.status(status)
}

// --- The stall watchdog's facts, in memory for this session (a reload starts them over, which
// only makes the watchdog quieter). Every map is pruned to the work in flight and bounded.
const threadsSeen = new Map<string, { outputFile?: string; startedAt: number; expectMs?: number }>()
const activity = new Map<string, number>() // 'main' or a thread's id -> its last action
const jobs = new Map<string, { id: string; owner?: string; label: string; startedAt: number; timeoutMs?: number; endsAt?: number
  holder?: boolean; output?: string; seenMtime?: number; readMtime?: number; endedAt?: number; ending?: string }>()
// Claude Code's task files for this session, `<dir>/<id>.output`: a thread's transcript and a
// background command's output. Learnt from the first thread the coordinator starts.
let tasksDir: string | undefined
const OUTPUT_READ_MAX = 1_000_000 // bytes: a larger output file is never read for its end
const strikes = new Map<string, Strike>()
const permissions = new Map<string, PermissionWait>()
const nudged = new Set<string>() // threads subagent_stop.py told to hand their report back
const failures = new Map<string, { attempts: number; at: number }>() // 'main' or a thread -> API failures in a row
const JOB_MAX_AGE_MS = 24 * 3600_000
const NO_REPORT_MARK = 'kit: no report reached your caller'
// Set where the tick starts: wakes are prompts, so a headless run (claude -p) gets none.
let interactive = false
// The main session's turn that a wake started: what it does is the watchdog's echo, not the
// person's or the coordinator's own activity, so it neither clears a stall nor restarts its count.
let wakeTurn = false

// A prompt of the kit's own, its own turn once the session is idle. Sent from a timer, never
// awaited inside the hook that saw the stall: a stop or a tool call must not wait on that turn.
async function wake($: $, text: string): Promise<void> {
  if (!interactive) return
  $.clock.after(0, () => {
    wakeTurn = true
    // a session that cannot take a prompt now: the next stall wakes it again
    void $.prompt.submit({ text }).catch(() => { wakeTurn = false })
  })
}

function noteActivity(who: string, at: number): void {
  if (who !== 'main' || !wakeTurn) activity.set(who, at)
}

async function nameOf($: $, id: string): Promise<string> {
  try {
    const a = (await $.agent.list()).find(x => x.id === id) as any
    if (a) return a.name || a.description || id
  } catch {
    // the id is name enough
  }
  return id
}

async function watchTick($: $): Promise<void> {
  const now = await $.clock.now()
  const w = watchConfig(await readJson($, await kitJsonPath($, await projectRoot($))))
  const agents = await $.agent.list()
  const threads: Thread[] = []
  for (const a of agents as any[]) {
    const seen = threadsSeen.get(a.id)
    let activeAt = activity.get(a.id)
    // a live thread with no record here (resumed after it finished, or started before a reload)
    // still has its transcript beside the others'
    const isLive = ['running', 'pending', 'waiting'].includes(a.status)
    const transcript = seen?.outputFile ?? (isLive && tasksDir ? `${tasksDir}/${a.id}.output` : undefined)
    if (transcript) {
      try {
        const mtime = (await $.fs.stat(transcript)).mtimeMs
        activeAt = Math.max(activeAt ?? 0, mtime)
      } catch {
        // no transcript yet: its tool calls are the heartbeat
      }
    }
    // a permission prompt it has not moved past (permissionWaits drops the others below)
    const p = permissions.get(a.id)
    const prompt = p && (activeAt ?? 0) <= p.since + 1000 ? { tool: p.tool, detail: p.detail, since: p.since } : undefined
    threads.push({ id: a.id, name: a.name || a.description || a.id, status: a.status, parentId: a.parentId,
      activeAt, startedAt: seen?.startedAt, expectMs: seen?.expectMs, prompt })
  }
  const live = new Set(threads.filter(t => ['running', 'pending', 'waiting'].includes(t.status)).map(t => t.id))
  for (const id of [...threadsSeen.keys()]) if (!live.has(id)) threadsSeen.delete(id)
  for (const id of [...activity.keys()]) if (id !== 'main' && !live.has(id)) activity.delete(id)
  for (const [id, j] of [...jobs]) {
    if ((j.owner && !live.has(j.owner)) || now - j.startedAt > JOB_MAX_AGE_MS || (j.endsAt && now > j.endsAt)) jobs.delete(id)
  }
  await noteEnds($, threads)
  const list: Job[] = [...jobs.values()].map(j => ({ id: j.id, owner: j.owner, label: j.label, startedAt: j.startedAt,
    // "(server)" in a command's description: meant to keep running, so it has no deadline
    deadlineMs: /\(server\)/i.test(j.label) ? 0 : j.timeoutMs ?? w.bashDeadlineMin * 60_000,
    declared: j.timeoutMs !== undefined, holder: j.holder, endedAt: j.endedAt, ending: j.ending }))
  const wakes = stalls(now, threads, list, activity, strikes, w)
  if (wakes.length) await wake($, wakes.map(x => x.text).join('\n\n'))
  for (const x of wakes) if (x.notify) await notify($, x.text.replace(/^kit watchdog: /, '').split('. ')[0] + '.')
  for (const p of permissionWaits(now, permissions, threads, w)) await notify($, p.text)
}

// A background command whose output file ends with Claude Code's exit line has ended, whatever its
// owner heard of it. Read once the file has stopped growing for a tick; dropped once its owner
// acted after the end (its transcript moves when the notice arrives).
async function noteEnds($: $, threads: Thread[]): Promise<void> {
  for (const [id, j] of [...jobs]) {
    if (j.endedAt !== undefined) {
      const ownerAt = j.owner ? threads.find(t => t.id === j.owner)?.activeAt : activity.get('main')
      if ((ownerAt ?? 0) > j.endedAt) jobs.delete(id)
      continue
    }
    if (!j.output) continue
    try {
      const st = await $.fs.stat(j.output)
      if (st.mtimeMs === j.seenMtime && st.mtimeMs !== j.readMtime && st.size <= OUTPUT_READ_MAX) {
        j.readMtime = st.mtimeMs
        const ending = outputEnd(String(await $.fs.read(j.output)))
        if (ending) {
          j.endedAt = st.mtimeMs
          j.ending = ending
        }
      }
      j.seenMtime = st.mtimeMs
    } catch {
      // no output file (yet, or not here): the command counts as running
    }
  }
}

// What a tool call tells the watchdog: a thread or a background command started or stopped, and
// that its caller acted.
async function noteTool($: $, e: any, r: any): Promise<void> {
  const now = await $.clock.now()
  noteActivity(e.agentId ?? 'main', now)
  const res = r && !r.deny && !r.isError ? r.result : undefined
  if ((e.tool === 'Agent' || e.tool === 'Task') && res && res.status === 'async_launched' && res.agentId) {
    // a thread already on record (agent.spawn saw it start, or this call resumed it) keeps its
    // start and its brief's EXPECT: a resume is the same thread, not a new one
    const seen = threadsSeen.get(res.agentId)
    if (typeof res.outputFile === 'string' && /[\\/]/.test(res.outputFile)) tasksDir = res.outputFile.replace(/[\\/][^\\/]*$/, '')
    threadsSeen.set(res.agentId, { outputFile: res.outputFile ?? seen?.outputFile, startedAt: seen?.startedAt ?? now,
      expectMs: seen?.expectMs ?? expectedMs(String(e.prompt ?? '')) })
    bound(threadsSeen)
  } else if (e.tool === 'Bash' && res && res.backgroundTaskId) {
    const label = String(e.description || e.command || '').slice(0, 80)
    // Bash's own `timeout` (ms) is the command's declared deadline; Claude Code applies it to a
    // background command only in an unattended session, so in the terminal this is the check
    jobs.set(res.backgroundTaskId, { id: res.backgroundTaskId, owner: e.agentId, label, startedAt: now,
      timeoutMs: typeof e.timeout === 'number' && e.timeout > 0 ? e.timeout : undefined,
      holder: isHolder(`${e.description ?? ''} ${e.command ?? ''}`),
      output: tasksDir ? `${tasksDir}/${res.backgroundTaskId}.output` : undefined })
    bound(jobs)
  } else if (e.tool === 'Monitor' && res && res.taskId) {
    // its owner waits on it and Claude Code ends it at its timeout: a job until then. The result
    // carries the real one (0: persistent); else timeout_ms as Claude Code caps it (30 min, default 5)
    const ms = typeof res.timeoutMs === 'number' && res.timeoutMs > 0 ? res.timeoutMs
      : typeof e.timeout_ms === 'number' && e.timeout_ms > 0 ? Math.min(e.timeout_ms, 1_800_000) : 300_000
    jobs.set(String(res.taskId), { id: String(res.taskId), owner: e.agentId, label: String(e.description || 'Monitor').slice(0, 80),
      startedAt: now, timeoutMs: ms, endsAt: now + ms })
    bound(jobs)
  } else if (e.tool === 'TaskStop' || e.tool === 'KillShell') {
    jobs.delete(String(e.task_id ?? e.shell_id ?? ''))
  }
}

// Background work Claude Code still lists as in flight at a stop: the stopping agent's commands
// not in it ended. Only its own are pruned, since the list may hold only that agent's tasks.
function pruneJobs(tasks: any, owner?: string): void {
  if (!Array.isArray(tasks)) return
  const running = new Set(tasks.filter(t => t && t.id).map(t => String(t.id)))
  for (const [id, j] of [...jobs]) if (j.owner === owner && !running.has(id)) jobs.delete(id)
}

// A turn that failed on the API (classic StopFailure). One that clears on its own gets a
// "continue" after 15, 30 and 60 s; one that needs the person (a login, a usage limit) notifies.
async function onFailure($: $, who: string, error: string, details: string): Promise<void> {
  const now = await $.clock.now()
  const f = failures.get(who) ?? { attempts: 0, at: now }
  failures.set(who, { attempts: f.attempts + 1, at: now })
  bound(failures)
  const name = who === 'main' ? 'this session' : `thread ${await nameOf($, who)} (${who})`
  if (failureKind(error, details) === 'person' || f.attempts >= RETRY_DELAYS_MS.length) {
    failures.delete(who)
    const why = failureKind(error, details) === 'person' ? error : `${error}, ${f.attempts + 1} times in a row`
    await notify($, `kit: ${name} stopped on an API error that needs you (${why}).`)
    if (who !== 'main') await wake($, `kit: ${name} stopped on an API error the person must clear (${why}${details ? `: ${details.slice(0, 200)}` : ''}). Put it under NEEDS YOU; do not retry it in a loop.`)
    return
  }
  $.clock.after(RETRY_DELAYS_MS[f.attempts], () => {
    void (who === 'main'
      ? wake($, `kit: the last turn failed on a transient API error (${error}). ${CONTINUE_NOTE}`)
      : wake($, `kit: ${name} stopped on a transient API error (${error}). Resume it with SendMessage: "${CONTINUE_NOTE}"`)
    ).catch(() => undefined)
  })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    // panes outlive a module reload, and the kit has none since 1.2.0: close what an older one left
    try {
      for (const pane of await $.ui.panes()) await $.ui.close({ id: pane.id })
    } catch {
      // never blocks a session's start
    }
    try {
      // nothing to draw in a headless run (claude -p, an overnight iteration): no timer there
      if ((await $.session.surfaces()).length === 0) return result
      lastStatus = undefined
      lastBoard = null
      await refreshStatus($)
    } catch {
      return result // the status line never blocks a session's start
    }
    // one tick per module, even when session.start runs again (resume, /clear). The watchdog
    // rides on it, so a headless run has none: there Claude Code's own background time limit applies
    if (tick) tick.cancel()
    interactive = true
    tick = $.clock.every(15000, () => {
      void refreshStatus($).catch(() => undefined)
      void watchTick($).catch(() => undefined)
    })
    return result
  })

  // A thread starting: its record (start, the EXPECT of its brief) begins here. A resumed run
  // (SendMessage to a thread that finished or stopped) fires this event too, with e.resume set:
  // it is the same thread, so it is neither recorded nor timed again, but it just acted: its
  // silence counts from here, not from its last tool call before the stop.
  on('agent.spawn', async ($, e: any, next) => {
    const r: any = await next(e)
    try {
      if (e.resume && r && !r.deny) {
        const id = String(e.resume.agentId ?? r.agentId ?? '')
        if (id) activity.set(id, await $.clock.now())
      } else if (r && !r.deny && r.agentId && !threadsSeen.has(r.agentId)) {
        threadsSeen.set(r.agentId, { startedAt: await $.clock.now(), expectMs: expectedMs(String(e.prompt ?? '')) })
        bound(threadsSeen)
      }
    } catch {
      // the thread starts either way
    }
    return r
  }).catch(($, e, next) => next(e))

  // The watchdog's facts. Each hook passes its event on unchanged and never fails it.
  for (const tool of ['Agent', 'Task', 'Bash', 'Monitor', 'TaskStop', 'KillShell']) {
    on('tool.call', { tool }, async ($, e: any, next) => {
      const r = await next(e)
      await noteTool($, e, r).catch(() => undefined)
      return r
    }).catch(($, e, next) => next(e))
  }

  on('classic.SubagentStop', async ($, e: any, next) => {
    const r: any = await next(e)
    try {
      const id = String(e.agent_id ?? '')
      pruneJobs(e.background_tasks, id)
      if (typeof r?.block === 'string' && r.block.includes(NO_REPORT_MARK)) {
        nudged.add(id)
        bound(nudged as any)
      } else if (e.stop_hook_active && nudged.delete(id) && e.agent_transcript_path) {
        // told once and stopping again: ask the same check whether the report went out this time
        const out = await $.process.run(['python3', `${$.plugin.root}/hooks/scripts/subagent_stop.py`, '--missing', e.agent_transcript_path])
        if (out.exitCode === 1) {
          const name = await nameOf($, id)
          await wake($, `kit: thread ${name} (${id}) ended without a report: its hand-back was refused or never made. ` +
            `SendMessage it to ask for the report (it can send it with SendMessage to "main"), or resume it if it stopped ` +
            `mid-work. Do not redo its work.`)
        }
      }
    } catch {
      // the stop goes on
    }
    return r
  })

  on('classic.Stop', async ($, e: any, next) => {
    const r = await next(e)
    try {
      pruneJobs(e.background_tasks)
    } catch {
      // the stop goes on
    }
    return r
  })

  on('classic.StopFailure', async ($, e: any, next) => {
    const r = await next(e)
    await onFailure($, e.agent_id ? String(e.agent_id) : 'main', String(e.error ?? 'unknown'),
      `${e.error_details ?? ''} ${e.last_assistant_message ?? ''}`.trim()).catch(() => undefined)
    return r
  })

  // a thread waiting on a permission prompt: noted, never answered (the prompt stays the person's)
  on('classic.PermissionRequest', async ($, e: any, next) => {
    const r: any = await next(e)
    try {
      // a hook beneath that answered it (an auto-allow) leaves no prompt for the person
      if (e.agent_id && !r?.decision) {
        const input = e.tool_input ?? {}
        const detail = String(input.command ?? input.file_path ?? input.url ?? '').slice(0, 120)
        permissions.set(String(e.agent_id), { tool: String(e.tool_name ?? ''), detail, since: await $.clock.now() })
        bound(permissions)
      }
    } catch {
      // noted or not, the request goes on
    }
    return r
  })

  on('turn.complete', async ($, e: any, next) => {
    const r = await next(e)
    try {
      const who = e.agentId ? String(e.agentId) : 'main'
      const own = who === 'main' && wakeTurn
      if (who === 'main') wakeTurn = false  // first, so a throw below cannot leave it set
      if (!own) activity.set(who, await $.clock.now())
      if (e.reason === 'answer') failures.delete(who)
    } catch {
      // nothing to note
    }
    return r
  })

  // A thread's interim notice ("waiting on its own background work") is held: it would be a turn
  // that changes nothing.
  on('prompt.submit', async ($, e, next) => {
    const kind = e.origin ? e.origin.kind : 'composer'
    if (kind === 'task-notification' && !e.command && isInterimNotice(e.text)) {
      return { drop: 'kit: held an interim notice from a thread waiting on its own background work; its report, or a stall, still reaches the coordinator' }
    }
    return next(e)
  }).catch(($, e, next) => next(e))
}
