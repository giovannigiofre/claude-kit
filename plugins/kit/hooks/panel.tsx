// The kit panel: one place to switch how the session works and to see what runs.
//
// - Mode, per project: `light` (a normal session; the lead only when asked) or `loop` (every
//   prompt goes to the coordinator, kit:lead). Stored in $.store. Without a choice: the personal
//   default in ~/.claude/kit.json ({"mode": "light"} or "loop"), else loop in a project that has
//   .claude/kit.json and light elsewhere.
// - Safety, per project: `host` (no OS sandbox; the kit's guard hook still blocks the
//   irreversible actions) or `sandbox` (Claude Code's Bash sandbox, written by the kit into
//   .claude/settings.local.json, which the overnight runner passes to its iterations too).
// - A live view: session cost and context, rate limits, every agent with its tokens, the
//   coordinator's board (NEEDS YOU first, then ready for review, then working), overnight runs,
//   scheduled loops. Also a status line.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, TurnCompleteInput } from 'claude-code'

import type { KitAgentRow, KitMode, KitOvernightRun, KitSafety, KitSnapshot } from '../types'

const PANE = 'kit'
const snapshot = atom({ plugin: 'kit', key: 'snapshot' } as const, null, { shape: 'snapshot-1' })
const agents = atom({ plugin: 'kit', key: 'agents' } as const, [], { shape: 'agents-1' })

export const SANDBOX = {
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
let crons: { schedule: string; prompt: string }[] = []

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
  await refresh($)
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
      await refresh($)
      return 'This project already has its own sandbox settings in .claude/settings.local.json; the kit left them as they are.'
    }
    local.sandbox = SANDBOX
    await $.fs.write(path, JSON.stringify(local, null, 2) + '\n')
    await $.store.set(`sandbox:${root}`, true)
    await refresh($)
    return 'Sandbox on for this project (.claude/settings.local.json): Bash runs inside the OS sandbox, writes only in the project and temp, network limited to GitHub and the main package registries plus the Anthropic API, credential folders unreadable. New hosts are asked for (or reviewed in auto mode); add your own under sandbox.network.allowedDomains in that file. Check with /sandbox; if it does not show it yet, start a new session.'
  }
  if (ours && local.sandbox) {
    delete local.sandbox
    await $.fs.write(path, JSON.stringify(local, null, 2) + '\n')
  }
  await $.store.delete(`sandbox:${root}`)
  const now = await getSafety($, root)
  await refresh($)
  return now.safety === 'sandbox'
    ? 'Kit sandbox removed, but your own settings still turn the sandbox on (see /sandbox).'
    : 'Host mode: no OS sandbox. The kit guard still blocks irreversible actions (deletes outside the repo, pushes to main, reading credentials).'
}

// what the person should look at first: questions, then work ready for review, then the rest
const STATUS_ORDER = ['needs-you', 'review', 'working', 'landing', 'queued', 'done', 'parked']

function statusRank(status: string): number {
  const i = STATUS_ORDER.indexOf(status)
  return i === -1 ? STATUS_ORDER.length : i
}

function parseBoard(text: string): KitSnapshot['board'] {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean).filter(l => !l.startsWith('```'))
  const header = lines.find(l => l.startsWith('SHIP:')) ?? ''
  const needsLine = lines.find(l => l.startsWith('NEEDS YOU:'))
  const needsYou: string[] = []
  if (needsLine) {
    const rest = needsLine.slice('NEEDS YOU:'.length).trim()
    if (rest && !/^(empty|none|-)$/i.test(rest)) needsYou.push(...rest.split(/;\s*/).filter(Boolean))
  }
  const items = lines
    .filter(l => l.includes('|') && !/^(SHIP|RULES|NEEDS YOU):/.test(l) && !l.startsWith('<'))
    .map(l => l.split('|').map(c => c.trim()))
    .filter(c => c.length >= 5)
    .map(c => ({ id: c[0] ?? '', kind: c[1] ?? '', goal: c[2] ?? '', status: c[4] ?? '' }))
    .sort((a, b) => statusRank(a.status) - statusRank(b.status))
  return { header, needsYou, items }
}

async function overnightRuns($: $, root: string): Promise<KitOvernightRun[]> {
  const roots = new Set<string>([root])
  try {
    const out = await $.process.run(['git', '-C', root, 'worktree', 'list', '--porcelain'])
    for (const line of out.stdout.split('\n')) if (line.startsWith('worktree ')) roots.add(line.slice(9).trim())
  } catch {
    // no git: only the project folder
  }
  const runs: KitOvernightRun[] = []
  for (const r of roots) {
    let entries: { name: string; kind: string; mtimeMs: number }[] = []
    try {
      entries = (await $.fs.list(`${r}/.claude/overnight`)) as any
    } catch {
      continue
    }
    for (const entry of entries) {
      if (entry.kind !== 'dir') continue
      const state = await readJson($, `${r}/.claude/overnight/${entry.name}/state.json`)
      if (!state) continue
      runs.push({
        runId: entry.name,
        branch: String(state.branch ?? ''),
        iteration: Number(state.iteration ?? 0),
        costUsd: Number(state.cost ?? 0),
        tokens: Number(state.tokens ?? 0),
        commits: Array.isArray(state.commits) ? state.commits.length : 0,
        stopReason: state.stop_reason ?? null,
        updatedAt: entry.mtimeMs,
      })
    }
  }
  return runs.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 6)
}

// what was last written, so an unchanged snapshot or line is not sent again
let lastKey = ''
let lastStatus: string | undefined

async function paneOpen($: $): Promise<boolean> {
  try {
    return (await $.ui.panes()).some(p => p.id === PANE)
  } catch {
    return false
  }
}

// The coordinator's board, from kit.json `lead.board` or the default path: null when there is
// none, undefined when it exists but could not be read this time.
async function readBoard($: $, root: string): Promise<KitSnapshot['board'] | undefined> {
  const kitJson = await readJson($, `${root}/.claude/kit.json`)
  const boardPath = (kitJson && kitJson.lead && kitJson.lead.board) || '.claude/lead/board.md'
  const path = boardPath.startsWith('/') ? boardPath : `${root}/${boardPath}`
  try {
    return parseBoard(await $.fs.read(path))
  } catch {
    try {
      return (await $.fs.exists(path)) ? undefined : null
    } catch {
      return undefined
    }
  }
}

// Agent statuses from the engine: a thread that finished must stop counting as running.
async function refreshAgents($: $): Promise<void> {
  try {
    const live = await $.agent.list()
    await update($, agents, rows =>
      rows.map(row => {
        const info = live.find(a => a.id === row.id)
        return info ? { ...row, status: info.status } : row
      }),
    )
  } catch {
    // agent list unavailable
  }
}

export async function refresh($: $, full = true): Promise<void> {
  const root = await projectRoot($)
  const mode = await getMode($, root)
  const { safety, from } = await getSafety($, root)
  let costUsd: number | null = null
  let contextPercent: number | null = null
  let limits: { kind: string; percentUsed: number }[] = []
  try {
    const usage = await $.session.usage()
    costUsd = usage.cost ? usage.cost.usd : null
    contextPercent = usage.context.percent ?? null
    limits = usage.rateLimits.map(l => ({ kind: l.kind, percentUsed: l.percentUsed }))
  } catch {
    // figures unavailable: draw without them
  }
  // the board and agent statuses feed the status line, so every tick reads them; a board that
  // could not be read keeps the last one, a board that is gone clears it
  const previous = await read($, snapshot)
  const fresh = await readBoard($, root)
  const board = fresh === undefined ? (previous ? previous.board : null) : fresh
  await refreshAgents($)
  if (!full && previous) {
    // the cheap tick: overnight runs (git worktree list plus a state file each) only while the
    // pane is drawn, so the line's "N overnight" can lag until then
    const cheap: KitSnapshot = { ...previous, mode, safety, sandboxFrom: from, costUsd, contextPercent, limits, board }
    await writeSnapshot($, cheap)
    return
  }
  const overnight = await overnightRuns($, root)
  const snap: KitSnapshot = {
    root, mode, safety, sandboxFrom: from, costUsd, contextPercent, limits, board, overnight, crons,
    updatedAt: await $.clock.now(),
  }
  await writeSnapshot($, snap)
}

async function writeSnapshot($: $, snap: KitSnapshot): Promise<void> {
  const { updatedAt, ...content } = snap
  const key = JSON.stringify(content)
  if (key !== lastKey) {
    lastKey = key
    await update($, snapshot, () => snap)
  }
  const { mode, safety, costUsd, overnight, board } = snap
  const rows = await read($, agents)
  const running = rows.filter(r => r.status === 'running' || r.status === 'pending').length
  const needs = board ? board.needsYou.length : 0
  const ready = board ? board.items.filter(i => i.status === 'review').length : 0
  const live = overnight.filter(r => !r.stopReason).length
  const parts = [`kit ${mode}`, safety]
  if (costUsd !== null) parts.push(`$${costUsd.toFixed(2)}`)
  if (running) parts.push(`${running} running`)
  if (live) parts.push(`${live} overnight`)
  if (ready) parts.push(`${ready} ready`)
  if (needs) parts.push(`${needs} need you`)
  const status = parts.join(' · ')
  // agent rows are not in the snapshot, so the line is compared on its own
  if (status === lastStatus) return
  lastStatus = status
  $.ui.status(status)
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

function cut(text: string, width: number): string {
  return text.length > width ? text.slice(0, Math.max(1, width - 1)) + '…' : text
}

// Tokens per agent, main loop included; called from kit.tsx's one turn.complete hook.
export async function recordUsage($: $, e: TurnCompleteInput): Promise<void> {
  try {
    const u = e.usage
    if (!u) return
    const tokens = u.input_tokens + u.output_tokens + (u.cache_creation_input_tokens ?? 0)
    const id = e.agentId ?? 'main'
    let label = 'main session'
    let status = 'idle'
    if (e.agentId) {
      const info = (await $.agent.list()).find(a => a.id === e.agentId)
      label = info ? `${info.name ?? info.type}: ${info.description}` : e.agentId
      status = info ? info.status : 'completed'
    }
    const now = await $.clock.now()
    await update($, agents, rows => {
      const found = rows.find(r => r.id === id)
      const row: KitAgentRow = found
        ? { ...found, tokens: found.tokens + tokens, turns: found.turns + 1, lastAt: now, status }
        : { id, label, status, tokens, turns: 1, lastAt: now }
      return [row, ...rows.filter(r => r.id !== id)].slice(0, 40)
    })
  } catch {
    // usage is a nicety
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'kit-panel', description: 'Open the kit panel: mode, safety, board, agents, loops, spend' })
    await $.command.register({ name: 'kit-mode', description: 'Kit mode for this project: light or loop', argumentHint: '[light|loop]' })
    await $.command.register({ name: 'kit-safety', description: 'Kit safety for this project: host or sandbox', argumentHint: '[host|sandbox]' })
    const result = await next(e)
    try {
      // nothing to draw in a headless run (claude -p, an overnight iteration): no timer there
      if ((await $.session.surfaces()).length === 0) return result
      lastKey = ''
      lastStatus = undefined
      await refresh($)
    } catch {
      return result // the panel never blocks a session's start
    }
    $.clock.every(15000, () => {
      void paneOpen($)
        .then(open => refresh($, open))
        .catch(() => undefined)
    })
    return result
  })

  on('command.run', { command: 'kit-panel' }, async $ => {
    await refresh($)
    const opened = await $.ui.open({ id: PANE, title: 'Kit' })
    return { text: opened.isPlaced ? 'Kit panel opened.' : 'This surface cannot show a panel; the status line shows the summary.' }
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
      // never block a prompt over the panel
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // Scheduled loops: the Stop hook input lists the session's cron jobs.
  on('classic.Stop', ($, e, next) => {
    const list = (e as any).session_crons
    if (Array.isArray(list)) crons = list.map((c: any) => ({ schedule: String(c.schedule), prompt: String(c.prompt) }))
    return next(e)
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const snap = await read($, snapshot)
    const rows = await read($, agents)
    const width = Math.max(30, (e.props as any).bodyColumns ?? 60)
    if (!snap) return <Text dimColor>Loading the kit panel…</Text>
    const root = snap.root
    const needs = snap.board ? snap.board.needsYou : []
    return (
      <Box flexDirection="column">
        <Box>
          <Text bold>Mode </Text>
          <Button key="mode-light" label="Light" variant={snap.mode === 'light' ? 'primary' : 'secondary'}
            onPress={() => setMode($, root, 'light').then(t => $.ui.toast(t))} />
          <Button key="mode-loop" label="Loop" variant={snap.mode === 'loop' ? 'primary' : 'secondary'}
            onPress={() => setMode($, root, 'loop').then(t => $.ui.toast(t))} />
        </Box>
        <Box>
          <Text bold>Safety </Text>
          <Button key="safety-host" label="Host" variant={snap.safety === 'host' ? 'primary' : 'secondary'}
            onPress={() => setSafety($, root, 'host').then(t => $.ui.toast(t))} />
          <Button key="safety-sandbox" label="Sandbox" variant={snap.safety === 'sandbox' ? 'primary' : 'secondary'}
            onPress={() => setSafety($, root, 'sandbox').then(t => $.ui.toast(t))} />
          {snap.sandboxFrom === 'settings' && <Text dimColor> (from your settings)</Text>}
        </Box>
        <Text dimColor>
          {cut(
            [
              snap.costUsd !== null ? `session $${snap.costUsd.toFixed(2)}` : null,
              snap.contextPercent !== null ? `context ${Math.round(snap.contextPercent)}%` : null,
              ...snap.limits.map(l => `${l.kind} ${Math.round(l.percentUsed)}%`),
            ].filter(Boolean).join(' · ') || 'no usage figures yet',
            width,
          )}
        </Text>
        {needs.length > 0 && <Text bold>NEEDS YOU</Text>}
        {needs.map((n, i) => (
          <Text key={`needs-${i}`}>{cut(`• ${n}`, width)}</Text>
        ))}
        <Text bold>Agents</Text>
        {rows.length === 0 && <Text dimColor>none yet</Text>}
        {rows.slice(0, 8).map(r => (
          <Text key={`agent-${r.id}`} dimColor={r.status !== 'running' && r.status !== 'pending'}>
            {cut(`${r.status.padEnd(9)} ${fmtTokens(r.tokens).padStart(5)}  ${r.label}`, width)}
          </Text>
        ))}
        {snap.board && snap.board.items.length > 0 && <Text bold>Board</Text>}
        {snap.board && snap.board.header && <Text dimColor>{cut(snap.board.header, width)}</Text>}
        {snap.board &&
          snap.board.items.slice(0, 10).map(item => (
            <Text key={`item-${item.id}`} dimColor={item.status === 'done' || item.status === 'parked'}>
              {cut(`${item.id} ${(item.status === 'review' ? 'ready' : item.status).padEnd(10)} ${item.goal}`, width)}
            </Text>
          ))}
        {snap.overnight.length > 0 && <Text bold>Overnight</Text>}
        {snap.overnight.map(run => (
          <Text key={`run-${run.runId}`} dimColor={run.stopReason !== null}>
            {cut(
              `${run.stopReason ? 'stopped' : 'running'} #${run.iteration} ${run.commits} commits $${run.costUsd.toFixed(2)} ${fmtTokens(run.tokens)} ${run.branch}${run.stopReason ? ` (${run.stopReason})` : ''}`,
              width,
            )}
          </Text>
        ))}
        {snap.crons.length > 0 && <Text bold>Loops</Text>}
        {snap.crons.map((c, i) => (
          <Text key={`cron-${i}`} dimColor>
            {cut(`${c.schedule}  ${c.prompt}`, width)}
          </Text>
        ))}
      </Box>
    )
  })
}
