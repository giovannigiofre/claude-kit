// The kit's one hooks module: light/loop mode, host/sandbox safety and a status line entry.
//
// - Mode, per project: `light` (a normal session; the lead only when asked), `loop` (every
//   prompt goes to the coordinator, kit:lead) or `ask` (a discussion about the repository: read
//   and reason, change no code; documentation may be edited; /kit:handoff sends the outcome where
//   the work gets done). Stored in $.store. Without a choice: the personal default in
//   ~/.claude/kit.json ({"mode": "light"} or "loop"), else loop in a project that has
//   .claude/kit.json and light elsewhere.
// - Safety, per project: `host` (no OS sandbox; the kit's guard hook still blocks the
//   irreversible actions) or `sandbox` (Claude Code's Bash sandbox, written by the kit into
//   .claude/settings.local.json, which the overnight runner passes to its iterations too), and
//   `unattended on|off` for an evening nobody is watching: permissions.denyInsteadOfPrompting in
//   the same file (a permission prompt becomes a denial and the turn goes on). Off unless asked.
// - The status line: mode, safety, session cost, threads running and waiting for an answer, live
//   overnight runs, board items queued, ready for review and questions for the person, and
//   `unattended` while that flag is on for the project, re-read
//   every 15 seconds; one native notification when the board gains a ready item or a question,
//   skipped while the person is typing at this terminal (a prompt of theirs in the last minute).
// - The stall watchdog, on the same tick (watchdog.ts decides, this module gathers and acts): a
//   thread silent too long or past its brief's EXPECT, a background command past its deadline, a
//   thread that ended without a report, a thread waiting on a permission prompt, and a turn that
//   failed on the API. It wakes the coordinator (a prompt of its own) or notifies the person;
//   it never approves, stops or retries anything itself, and on any error it stays quiet.
import type { EngineInterface, Register, Timer } from 'claude-code'
import { CONTINUE_NOTE, RETRY_DELAYS_MS, bound, expectedMs, failureKind, permissionWaits, stalls, watchConfig } from './watchdog'
import type { Job, PermissionWait, Strike, Thread } from './watchdog'

type KitMode = 'light' | 'loop' | 'ask'
const MODES: KitMode[] = ['light', 'loop', 'ask']
type KitSafety = 'host' | 'sandbox'

const SANDBOX = {
  enabled: true,
  // where the sandbox cannot start, commands run unsandboxed (with a warning) rather than all
  // failing; /sandbox shows whether it is really on
  failIfUnavailable: false,
  allowUnsandboxedCommands: false,
  network: {
    allowedDomains: [
      'github.com', '*.github.com', '*.githubusercontent.com',
      'registry.npmjs.org', '*.npmjs.org', 'registry.yarnpkg.com',
      'pypi.org', 'files.pythonhosted.org',
      'crates.io', 'index.crates.io', 'static.crates.io',
      'proxy.golang.org', 'sum.golang.org', 'rubygems.org',
      'api.anthropic.com',
    ],
  },
  filesystem: {
    denyRead: ['~/.ssh', '~/.aws', '~/.config/gh', '~/.netrc', '~/.docker', '~/.kube', '~/.gnupg'],
  },
}

const LOOP_CONTEXT =
  'Kit loop mode: you are this project\'s coordinator. Handle this message with the kit:lead ' +
  'skill (load it first if this conversation has not, or if its rules are gone after a compaction). ' +
  'The kit mod notifies the user when the board gains a ready or needs-you row; do not send ' +
  'PushNotification for that yourself.'

const ASK_CONTEXT =
  'Kit ask mode: this session is a discussion about the repository. Explore, explain, reason and ' +
  'propose; change no code. Documentation files (Markdown, docs/) may be edited when the user asks. ' +
  'When something worth doing emerges, offer /kit:handoff: it turns the conclusion into a brief ' +
  'and hands it to the coordinator, another session or a new background session.'

const OFF_CONTEXT =
  'Kit loop mode was just switched off. Stop coordinating: delete the cron jobs you created for ' +
  'it (CronList, CronDelete), let working threads finish, rewrite the board once, and answer as ' +
  'a normal session from now on. Say so in one line.'

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

async function userKit($: $): Promise<any> {
  const home = await $.env.get('HOME')
  if (!home) return undefined
  return readJson($, `${home}/.claude/kit.json`)
}

async function getMode($: $, root: string): Promise<KitMode> {
  const stored = await $.store.get(`mode:${root}`)
  if (MODES.includes(stored as KitMode)) return stored as KitMode
  const user = await userKit($)
  if (user && (user.mode === 'loop' || user.mode === 'light')) return user.mode
  // a project that opted into the kit talks to the coordinator unless someone chose otherwise
  return (await readJson($, `${root}/.claude/kit.json`)) !== undefined ? 'loop' : 'light'
}

async function setMode($: $, root: string, mode: KitMode): Promise<string> {
  const before = await getMode($, root)
  await $.store.set(`mode:${root}`, mode)
  if (before === 'loop' && mode !== 'loop') await $.store.set(`loopOff:${root}`, true)
  if (mode === 'loop') await $.store.delete(`loopOff:${root}`)
  await refreshStatus($)
  if (mode === 'loop') return 'Loop mode on: from your next message you talk to the coordinator (kit:lead); it starts a thread for each piece of work.'
  if (mode === 'ask') return 'Ask mode on: a discussion about this repository. Claude reads and reasons, changes no code (documentation may be edited when you ask); /kit:handoff turns a conclusion into a brief for the coordinator, another session or a new background session.'
  return 'Light mode on: a normal session. The coordinator stops its loops at your next message; /kit:lead still works when you ask.'
}

async function getSafety($: $, root: string): Promise<{ safety: KitSafety; from: 'kit' | 'settings' | 'none' }> {
  const local = await readJson($, `${root}/.claude/settings.local.json`)
  const ours = (await $.store.get(`sandbox:${root}`)) === true
  if (local && local.sandbox && local.sandbox.enabled === true && ours) return { safety: 'sandbox', from: 'kit' }
  let merged: any
  try {
    merged = await $.settings.read({ key: 'sandbox' })
  } catch {
    merged = undefined
  }
  if (merged && merged.enabled === true) return { safety: 'sandbox', from: 'settings' }
  return { safety: 'host', from: 'none' }
}

async function setSafety($: $, root: string, safety: KitSafety): Promise<string> {
  const path = `${root}/.claude/settings.local.json`
  const file = await readJsonForWrite($, path)
  if (file.isBroken) {
    return '.claude/settings.local.json is not valid JSON; the kit did not touch it. Fix the file, then try again.'
  }
  const local = file.value
  const ours = (await $.store.get(`sandbox:${root}`)) === true
  if (safety === 'sandbox') {
    if (local.sandbox && !ours) {
      await refreshStatus($)
      return 'This project already has its own sandbox settings in .claude/settings.local.json; the kit left them as they are.'
    }
    local.sandbox = SANDBOX
    await $.fs.write(path, JSON.stringify(local, null, 2) + '\n')
    await $.store.set(`sandbox:${root}`, true)
    await refreshStatus($)
    return 'Sandbox on for this project (.claude/settings.local.json): Bash runs inside the OS sandbox, writes only in the project and temp, network limited to GitHub and the main package registries plus the Anthropic API, credential folders unreadable. New hosts are asked for (or reviewed in auto mode); add your own under sandbox.network.allowedDomains in that file. Check with /sandbox; if it does not show it yet, start a new session.'
  }
  if (ours && local.sandbox) {
    delete local.sandbox
    await $.fs.write(path, JSON.stringify(local, null, 2) + '\n')
  }
  await $.store.delete(`sandbox:${root}`)
  const now = await getSafety($, root)
  await refreshStatus($)
  return now.safety === 'sandbox'
    ? 'Kit sandbox removed, but your own settings still turn the sandbox on (see /sandbox).'
    : 'Host mode: no OS sandbox. The kit guard still blocks irreversible actions (deletes outside the repo, pushes to main, reading credentials).'
}

// Unattended, for an evening nobody is watching: permissions.denyInsteadOfPrompting (Claude Code
// 2.1.319) in .claude/settings.local.json makes a tool call that would wait on a permission
// prompt a denial instead, and the turn goes on, in this session and its threads. Only this
// command sets it; a denied action lowers what a thread gets done, so it is off unless asked.
const UNATTENDED_KEY = 'denyInsteadOfPrompting'

async function getUnattended($: $, root: string): Promise<{ on: boolean; from: 'kit' | 'settings' | 'none' }> {
  const local = await readJson($, `${root}/.claude/settings.local.json`)
  if (local && local.permissions && local.permissions[UNATTENDED_KEY] === true) return { on: true, from: 'kit' }
  let merged: any
  try {
    merged = await $.settings.read({ key: 'permissions' })
  } catch {
    merged = undefined
  }
  if (merged && merged[UNATTENDED_KEY] === true) return { on: true, from: 'settings' }
  return { on: false, from: 'none' }
}

async function setUnattended($: $, root: string, on: boolean): Promise<string> {
  const path = `${root}/.claude/settings.local.json`
  const file = await readJsonForWrite($, path)
  if (file.isBroken) {
    return '.claude/settings.local.json is not valid JSON; the kit did not touch it. Fix the file, then try again.'
  }
  const local = file.value
  const perms = local.permissions && typeof local.permissions === 'object' && !Array.isArray(local.permissions) ? local.permissions : {}
  if (on) {
    local.permissions = { ...perms, [UNATTENDED_KEY]: true }
    await $.fs.write(path, JSON.stringify(local, null, 2) + '\n')
    await refreshStatus($)
    return 'Unattended on for this project (.claude/settings.local.json, permissions.denyInsteadOfPrompting): a tool call that would wait on a permission prompt is denied instead and the turn continues, in this session and its threads. For an evening nobody is watching; /kit-safety unattended off when you are back, since a denied action lowers what a thread gets done.'
  }
  if (UNATTENDED_KEY in perms) {
    delete perms[UNATTENDED_KEY]
    if (Object.keys(perms).length === 0) delete local.permissions
    else local.permissions = perms
    await $.fs.write(path, JSON.stringify(local, null, 2) + '\n')
  }
  await refreshStatus($)
  return 'Unattended off: a tool call that needs permission asks you again (permissions.denyInsteadOfPrompting removed from .claude/settings.local.json).'
}

// What the coordinator's board says is queued, ready for review and what needs the person.
type BoardCounts = { ready: number; needs: number; queued: number }

const BOARD_STATUS = /^(queued|working|review|needs-you|landing|done|parked)\b/

// The status of one board row. The reference puts it in the fifth cell, but a model renders the
// board readily as a Markdown table (outer pipes, a header and a separator row), capitalises a
// word or drops a cell, so: outer pipes stripped, emphasis stripped, any case, the fifth cell
// first and else the only cell that is a status word.
function rowStatus(line: string): string | undefined {
  const cells = line.replace(/^\|/, '').replace(/\|$/, '').split('|')
    .map(c => c.trim().replace(/[*_`]/g, '').toLowerCase())
  if (cells.length < 2) return undefined
  if (cells.every(c => c === '' || /^:?-+:?$/.test(c))) return undefined // a table's separator row
  if (cells.includes('status') || cells[0] === 'id') return undefined // its header row
  const status = (c: string | undefined) => (c && BOARD_STATUS.exec(c)?.[1]) || undefined
  const found = cells.map(status).filter(Boolean) as string[]
  return status(cells[4]) ?? (found.length === 1 ? found[0] : undefined)
}

function countBoard(text: string): BoardCounts {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean).filter(l => !l.startsWith('```'))
  const needsLine = lines.find(l => /^NEEDS YOU:/i.test(l))
  let needs = 0
  if (needsLine) {
    const rest = needsLine.slice('NEEDS YOU:'.length).trim()
    if (rest && !/^(empty|none|-)$/i.test(rest)) needs = rest.split(/;\s*/).filter(Boolean).length
  }
  const statuses = lines
    .filter(l => l.includes('|') && !/^(SHIP|RULES|NEEDS YOU):/i.test(l) && !l.startsWith('<'))
    .map(rowStatus)
  const count = (s: string) => statuses.filter(x => x === s).length
  // a needs-you row with no NEEDS YOU line still needs the person; with both, the larger count
  return { ready: count('review'), needs: Math.max(needs, count('needs-you')), queued: count('queued') }
}

// The board from kit.json `lead.board` or the default path: null when there is no board,
// undefined when it (or kit.json) exists but could not be read this time.
async function readBoard($: $, root: string): Promise<BoardCounts | null | undefined> {
  const kitJson = await readJsonForWrite($, `${root}/.claude/kit.json`)
  if (kitJson.isBroken) return undefined
  const lead = kitJson.value.lead
  const boardPath = (lead && lead.board) || '.claude/lead/board.md'
  const path = boardPath.startsWith('/') ? boardPath : `${root}/${boardPath}`
  try {
    return countBoard(await $.fs.read(path))
  } catch {
    try {
      return (await $.fs.exists(path)) ? undefined : null
    } catch {
      return undefined
    }
  }
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
    let entries: { name: string; kind: string }[] = []
    try {
      entries = (await $.fs.list(`${r}/.claude/overnight`)) as any
    } catch {
      continue
    }
    for (const entry of entries) {
      if (entry.kind !== 'dir') continue
      const state = await readJson($, `${r}/.claude/overnight/${entry.name}/state.json`)
      if (state && !state.stop_reason) live++
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

// One native notification when the board gains something for the person (a thread finished and
// its PR is ready, or a question appeared) while they may be away. The loop-mode context tells
// the coordinator to leave this to the mod, so the person gets one ping, not two. Not while the
// person is typing here: a prompt of theirs in the last minute means they see the status line.
// (The main session's own activity is no such sign: the coordinator's tool calls after a thread's
// report are exactly what puts the ready row on the board while the person is away.)
const PERSON_HERE_MS = 60_000
let personAt = 0 // when the person last typed a prompt here (terminal or Remote Control)

async function notifyBoardChange($: $, before: BoardCounts | null, after: BoardCounts): Promise<void> {
  if (!before) return
  const ready = after.ready - before.ready
  const needs = after.needs - before.needs
  if (ready <= 0 && needs <= 0) return
  if (personAt && (await $.clock.now()) - personAt < PERSON_HERE_MS) return
  const parts: string[] = []
  if (ready > 0) parts.push(`${ready} ready for review`)
  if (needs > 0) parts.push(`${needs} need${needs === 1 ? 's' : ''} you`)
  await notify($, `kit: ${parts.join(', ')}. See the board (.claude/lead/board.md) or ask the coordinator.`)
}

async function notify($: $, text: string): Promise<void> {
  try {
    // an engine without $.ui.notify, or without a channel, throws here: the line still shows it
    await $.ui.notify(text, { title: 'kit' })
  } catch {
    // nothing to do
  }
}

let lastBoard: BoardCounts | null = null

// Everything on the line is read again on each call: the board is one small file, a board that
// could not be read keeps the last counts, a board that is gone clears them.
async function refreshStatus($: $): Promise<void> {
  const root = await projectRoot($)
  const mode = await getMode($, root)
  const { safety } = await getSafety($, root)
  let costUsd: number | null = null
  try {
    const usage = await $.session.usage()
    costUsd = usage.cost ? usage.cost.usd : null
  } catch {
    // spend unavailable: draw without it
  }
  const board = await readBoard($, root)
  if (board !== undefined) {
    await notifyBoardChange($, lastBoard, board)
    lastBoard = board
  }
  const { running, waiting } = await agentCounts($)
  const live = await liveOvernightRuns($, root)
  const parts: string[] = [mode, safety]
  // a forgotten `unattended on` shows here the next morning (project file, else merged settings)
  if ((await getUnattended($, root)).on) parts.push('unattended')
  if (costUsd !== null) parts.push(`$${costUsd.toFixed(2)}`)
  if (running) parts.push(`${running} running`)
  if (waiting) parts.push(`${waiting} waiting`)
  if (live) parts.push(`${live} overnight`)
  if (lastBoard && lastBoard.queued) parts.push(`${lastBoard.queued} queued`)
  if (lastBoard && lastBoard.ready) parts.push(`${lastBoard.ready} ready`)
  if (lastBoard && lastBoard.needs) parts.push(`${lastBoard.needs} need you`)
  const status = parts.join(' · ')
  if (status === lastStatus) return
  lastStatus = status
  $.ui.status(status)
}

// --- The stall watchdog's facts, in memory for this session (a reload starts them over, which
// only makes the watchdog quieter). Every map is pruned to the work in flight and bounded.
const threadsSeen = new Map<string, { outputFile?: string; startedAt: number; expectMs?: number }>()
const activity = new Map<string, number>() // 'main' or a thread's id -> its last action
const jobs = new Map<string, { id: string; owner?: string; label: string; startedAt: number; timeoutMs?: number; endsAt?: number }>()
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
  const w = watchConfig(await readJson($, `${await projectRoot($)}/.claude/kit.json`))
  const agents = await $.agent.list()
  const threads: Thread[] = []
  for (const a of agents as any[]) {
    const seen = threadsSeen.get(a.id)
    let activeAt = activity.get(a.id)
    if (seen && seen.outputFile) {
      try {
        const mtime = (await $.fs.stat(seen.outputFile)).mtimeMs
        activeAt = Math.max(activeAt ?? 0, mtime)
      } catch {
        // no transcript yet: its tool calls are the heartbeat
      }
    }
    threads.push({ id: a.id, name: a.name || a.description || a.id, status: a.status, parentId: a.parentId,
      activeAt, startedAt: seen?.startedAt, expectMs: seen?.expectMs })
  }
  const live = new Set(threads.filter(t => ['running', 'pending', 'waiting'].includes(t.status)).map(t => t.id))
  for (const id of [...threadsSeen.keys()]) if (!live.has(id)) threadsSeen.delete(id)
  for (const id of [...activity.keys()]) if (id !== 'main' && !live.has(id)) activity.delete(id)
  for (const [id, j] of [...jobs]) {
    if ((j.owner && !live.has(j.owner)) || now - j.startedAt > JOB_MAX_AGE_MS || (j.endsAt && now > j.endsAt)) jobs.delete(id)
  }
  const list: Job[] = [...jobs.values()].map(j => ({ id: j.id, owner: j.owner, label: j.label, startedAt: j.startedAt,
    // "(server)" in a command's description: meant to keep running, so it has no deadline
    deadlineMs: /\(server\)/i.test(j.label) ? 0 : j.timeoutMs ?? w.bashDeadlineMin * 60_000 }))
  const wakes = stalls(now, threads, list, activity, strikes, w)
  if (wakes.length) await wake($, wakes.map(x => x.text).join('\n\n'))
  for (const x of wakes) if (x.notify) await notify($, x.text.replace(/^kit watchdog: /, '').split('. ')[0] + '.')
  for (const p of permissionWaits(now, permissions, threads, w)) await notify($, p.text)
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
    threadsSeen.set(res.agentId, { outputFile: res.outputFile ?? seen?.outputFile, startedAt: seen?.startedAt ?? now,
      expectMs: seen?.expectMs ?? expectedMs(String(e.prompt ?? '')) })
    bound(threadsSeen)
  } else if (e.tool === 'Bash' && res && res.backgroundTaskId) {
    const label = String(e.description || e.command || '').slice(0, 80)
    // Bash's own `timeout` (ms) is the command's declared deadline; Claude Code applies it to a
    // background command only in an unattended session, so in the terminal this is the check
    jobs.set(res.backgroundTaskId, { id: res.backgroundTaskId, owner: e.agentId, label, startedAt: now,
      timeoutMs: typeof e.timeout === 'number' && e.timeout > 0 ? e.timeout : undefined })
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
    await $.command.register({ name: 'kit-mode', description: 'Kit mode for this project: light, loop or ask', argumentHint: '[light|loop|ask]' })
    await $.command.register({ name: 'kit-safety', description: 'Kit safety for this project: host or sandbox; unattended on|off for an evening', argumentHint: '[host|sandbox|unattended on|off]' })
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
  // it is the same thread, so it is neither recorded nor timed again.
  on('agent.spawn', async ($, e: any, next) => {
    const r: any = await next(e)
    try {
      if (!e.resume && r && !r.deny && r.agentId && !threadsSeen.has(r.agentId)) {
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

  on('command.run', { command: 'kit-mode' }, async ($, e) => {
    const root = await projectRoot($)
    const arg = e.args.trim().toLowerCase()
    if (MODES.includes(arg as KitMode)) return { text: await setMode($, root, arg as KitMode) }
    return { text: `Kit mode for this project: ${await getMode($, root)}. Use /kit-mode light, loop or ask.` }
  })

  on('command.run', { command: 'kit-safety' }, async ($, e) => {
    const root = await projectRoot($)
    const arg = e.args.trim().toLowerCase()
    if (arg === 'host' || arg === 'sandbox') return { text: await setSafety($, root, arg) }
    const [verb, value] = arg.split(/\s+/)
    if (verb === 'unattended') {
      if (value === 'on' || value === 'off') return { text: await setUnattended($, root, value === 'on') }
      const u = await getUnattended($, root)
      return { text: `Unattended is ${u.on ? 'on' : 'off'} for this project${u.from === 'settings' ? ' (from your settings)' : ''}. Use /kit-safety unattended on or off.` }
    }
    const now = await getSafety($, root)
    const u = await getUnattended($, root)
    return { text: `Kit safety for this project: ${now.safety}${now.from === 'settings' ? ' (from your settings)' : ''} · unattended: ${u.on ? 'on' : 'off'}${u.from === 'settings' ? ' (from your settings)' : ''}. Use /kit-safety host or /kit-safety sandbox; /kit-safety unattended on|off for an evening nobody is watching.` }
  })

  // Loop mode: every prompt the person types reaches the coordinator.
  on('prompt.submit', async ($, e, next) => {
    const kind = e.origin ? e.origin.kind : 'composer'
    if (e.command || e.isMeta || (kind !== 'composer' && kind !== 'bridge')) return next(e)
    try {
      personAt = await $.clock.now() // the person is here: the board's changes need no notification
      const root = await projectRoot($)
      const extra: string[] = []
      if (await $.store.get(`loopOff:${root}`)) {
        extra.push(OFF_CONTEXT)
        await $.store.delete(`loopOff:${root}`)
      }
      const mode = await getMode($, root)
      if (mode === 'loop') extra.push(LOOP_CONTEXT)
      if (mode === 'ask') extra.push(ASK_CONTEXT)
      if (extra.length) return next({ ...e, context: [...(e.context ?? []), ...extra] })
    } catch {
      // never block a prompt over the kit
    }
    return next(e)
  }).catch(($, e, next) => next(e))
}
