// The kit's one hooks module: light/loop mode, host/sandbox safety and a status line entry.
//
// - Mode, per project: `light` (a normal session; the lead only when asked) or `loop` (every
//   prompt goes to the coordinator, kit:lead). Stored in $.store. Without a choice: the personal
//   default in ~/.claude/kit.json ({"mode": "light"} or "loop"), else loop in a project that has
//   .claude/kit.json and light elsewhere.
// - Safety, per project: `host` (no OS sandbox; the kit's guard hook still blocks the
//   irreversible actions) or `sandbox` (Claude Code's Bash sandbox, written by the kit into
//   .claude/settings.local.json, which the overnight runner passes to its iterations too).
// - The status line: mode, safety, session cost, threads running, live overnight runs, board
//   items ready for review and questions for the person, re-read every 15 seconds.
import type { EngineInterface, Register, Timer } from 'claude-code'

type KitMode = 'light' | 'loop'
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
  'skill (load it first if this conversation has not, or if its rules are gone after a compaction).'

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
  if (stored === 'loop' || stored === 'light') return stored
  const user = await userKit($)
  if (user && (user.mode === 'loop' || user.mode === 'light')) return user.mode
  // a project that opted into the kit talks to the coordinator unless someone chose otherwise
  return (await readJson($, `${root}/.claude/kit.json`)) !== undefined ? 'loop' : 'light'
}

async function setMode($: $, root: string, mode: KitMode): Promise<string> {
  const before = await getMode($, root)
  await $.store.set(`mode:${root}`, mode)
  if (before === 'loop' && mode === 'light') await $.store.set(`loopOff:${root}`, true)
  if (mode === 'loop') await $.store.delete(`loopOff:${root}`)
  await refreshStatus($)
  return mode === 'loop'
    ? 'Loop mode on: from your next message you talk to the coordinator (kit:lead); it starts a thread for each piece of work.'
    : 'Light mode on: a normal session. The coordinator stops its loops at your next message; /kit:lead still works when you ask.'
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

// What the coordinator's board says is ready for review and what needs the person.
type BoardCounts = { ready: number; needs: number }

function countBoard(text: string): BoardCounts {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean).filter(l => !l.startsWith('```'))
  const needsLine = lines.find(l => l.startsWith('NEEDS YOU:'))
  let needs = 0
  if (needsLine) {
    const rest = needsLine.slice('NEEDS YOU:'.length).trim()
    if (rest && !/^(empty|none|-)$/i.test(rest)) needs = rest.split(/;\s*/).filter(Boolean).length
  }
  const ready = lines
    .filter(l => l.includes('|') && !/^(SHIP|RULES|NEEDS YOU):/.test(l) && !l.startsWith('<'))
    .map(l => l.split('|').map(c => c.trim()))
    .filter(c => c.length >= 5 && c[4] === 'review').length
  return { ready, needs }
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

async function runningAgents($: $): Promise<number> {
  try {
    return (await $.agent.list()).filter(a => a.status === 'running' || a.status === 'pending').length
  } catch {
    return 0
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
  if (board !== undefined) lastBoard = board
  const running = await runningAgents($)
  const live = await liveOvernightRuns($, root)
  const parts: string[] = [mode, safety]
  if (costUsd !== null) parts.push(`$${costUsd.toFixed(2)}`)
  if (running) parts.push(`${running} running`)
  if (live) parts.push(`${live} overnight`)
  if (lastBoard && lastBoard.ready) parts.push(`${lastBoard.ready} ready`)
  if (lastBoard && lastBoard.needs) parts.push(`${lastBoard.needs} need you`)
  const status = parts.join(' · ')
  if (status === lastStatus) return
  lastStatus = status
  $.ui.status(status)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'kit-mode', description: 'Kit mode for this project: light or loop', argumentHint: '[light|loop]' })
    await $.command.register({ name: 'kit-safety', description: 'Kit safety for this project: host or sandbox', argumentHint: '[host|sandbox]' })
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
    // one tick per module, even when session.start runs again (resume, /clear)
    if (tick) tick.cancel()
    tick = $.clock.every(15000, () => {
      void refreshStatus($).catch(() => undefined)
    })
    return result
  })

  on('command.run', { command: 'kit-mode' }, async ($, e) => {
    const root = await projectRoot($)
    const arg = e.args.trim().toLowerCase()
    if (arg === 'light' || arg === 'loop') return { text: await setMode($, root, arg) }
    return { text: `Kit mode for this project: ${await getMode($, root)}. Use /kit-mode light or /kit-mode loop.` }
  })

  on('command.run', { command: 'kit-safety' }, async ($, e) => {
    const root = await projectRoot($)
    const arg = e.args.trim().toLowerCase()
    if (arg === 'host' || arg === 'sandbox') return { text: await setSafety($, root, arg) }
    const now = await getSafety($, root)
    return { text: `Kit safety for this project: ${now.safety}${now.from === 'settings' ? ' (from your settings)' : ''}. Use /kit-safety host or /kit-safety sandbox.` }
  })

  // Loop mode: every prompt the person types reaches the coordinator.
  on('prompt.submit', async ($, e, next) => {
    const kind = e.origin ? e.origin.kind : 'composer'
    if (e.command || e.isMeta || (kind !== 'composer' && kind !== 'bridge')) return next(e)
    try {
      const root = await projectRoot($)
      const extra: string[] = []
      if (await $.store.get(`loopOff:${root}`)) {
        extra.push(OFF_CONTEXT)
        await $.store.delete(`loopOff:${root}`)
      }
      if ((await getMode($, root)) === 'loop') extra.push(LOOP_CONTEXT)
      if (extra.length) return next({ ...e, context: [...(e.context ?? []), ...extra] })
    } catch {
      // never block a prompt over the kit
    }
    return next(e)
  }).catch(($, e, next) => next(e))
}
