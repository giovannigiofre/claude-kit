import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

// The world beneath the kit mod: a repo at /repo, a home at /home/u, files in memory.
function world(on: On, files: Record<string, string> = {}, agents: any[] = [], exitCode = (_argv: string[]) => 0) {
  mock.store(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  const written: Record<string, string> = {}
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 200000, percent: 12 }, rateLimits: [], cost: { usd: 1.5 } } }))
  on('process.run', (_, e: any) => ({ value: { exitCode: exitCode(e.argv), stdout: '/repo\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('fs.read', (_, e: any) => {
    const text = written[e.path] ?? files[e.path]
    if (text === undefined) return { deny: `ENOENT ${e.path}` }
    return { value: text }
  })
  on('fs.write', (_, e: any) => {
    written[e.path] = e.text
    return { value: undefined }
  })
  on('fs.list', () => ({ deny: 'ENOENT' }))
  on('settings.read', () => ({ value: {} }))
  on('agent.list', () => ({ value: agents }))
  on('command.register', (_, e: any) => ({ value: { command: e.name } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  return { written, clock }
}

function promptCatcher(on: On) {
  const seen: (readonly string[] | undefined)[] = []
  on('prompt.submit', (_, e) => {
    seen.push(e.context)
    return { text: e.text, context: e.context }
  })
  return seen
}

test('light mode adds nothing; loop mode hands every prompt to the coordinator; off says stop once', async ($, on) => {
  world(on)
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })

  await $.prompt.submit({ text: 'hello' } as any)
  expect(seen.at(-1) ?? []).toEqual([])

  const turnedOn = await $.command.run({ command: 'kit-mode', args: 'loop' } as any)
  expect(JSON.stringify(turnedOn)).toContain('Loop mode on')
  await $.prompt.submit({ text: 'add a login page' } as any)
  expect((seen.at(-1) ?? []).join(' ')).toContain('coordinator')
  // the mod is the one that pings the person about the board: the coordinator is told so
  expect((seen.at(-1) ?? []).join(' ')).toContain('The kit mod notifies the user when the board gains a ready or needs-you row; do not send PushNotification for that yourself.')

  await $.command.run({ command: 'kit-mode', args: 'light' } as any)
  await $.prompt.submit({ text: 'what changed?' } as any)
  const afterOff = (seen.at(-1) ?? []).join(' ')
  expect(afterOff).toContain('switched off')
  expect(afterOff).not.toContain('Handle this message with the kit:lead')

  await $.prompt.submit({ text: 'and now?' } as any)
  expect(seen.at(-1) ?? []).toEqual([])
})

test('ask mode adds the discussion line; leaving it adds nothing; leaving loop still says stop once', async ($, on) => {
  world(on)
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const on1 = await $.command.run({ command: 'kit-mode', args: 'ask' } as any)
  expect(JSON.stringify(on1)).toContain('Ask mode on')
  await $.prompt.submit({ text: 'how does auth work here?' } as any)
  expect((seen.at(-1) ?? []).join(' ')).toContain('discussion about the repository')
  expect((seen.at(-1) ?? []).join(' ')).not.toContain('coordinator (kit:lead)')
  await $.command.run({ command: 'kit-mode', args: 'light' } as any)
  await $.prompt.submit({ text: 'thanks' } as any)
  expect(seen.at(-1) ?? []).toEqual([])
  await $.command.run({ command: 'kit-mode', args: 'loop' } as any)
  await $.command.run({ command: 'kit-mode', args: 'ask' } as any)
  await $.prompt.submit({ text: 'why is this slow?' } as any)
  const text = (seen.at(-1) ?? []).join(' ')
  expect(text).toContain('switched off')
  expect(text).toContain('discussion about the repository')
})

test('loop mode never reaches headless or scheduled prompts', async ($, on) => {
  world(on, { '/home/u/.claude/kit.json': JSON.stringify({ mode: 'loop' }) })
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  for (const kind of ['sdk', 'scheduled-trigger', 'task-notification', 'peer']) {
    await $.prompt.submit({ text: 'tick', origin: { kind } } as any)
    expect(seen.at(-1) ?? []).toEqual([])
  }
  await $.prompt.submit({ text: 'from my phone', origin: { kind: 'bridge' } } as any)
  expect((seen.at(-1) ?? []).join(' ')).toContain('coordinator')
})

test('a settings file that does not parse is never rewritten', async ($, on) => {
  const { written } = world(on, { '/repo/.claude/settings.local.json': '{ "permissions": { "allow": [ ' })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const answer = await $.command.run({ command: 'kit-safety', args: 'sandbox' } as any)
  expect(JSON.stringify(answer)).toContain('not valid JSON')
  expect(written['/repo/.claude/settings.local.json']).toBeUndefined()
})

test('a personal default of loop applies until the project chooses', async ($, on) => {
  world(on, { '/home/u/.claude/kit.json': JSON.stringify({ mode: 'loop' }) })
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.prompt.submit({ text: 'go' } as any)
  expect((seen.at(-1) ?? []).join(' ')).toContain('coordinator')
})

test('a project with kit.json starts in loop mode unless the person chose light', async ($, on) => {
  world(on, { '/repo/.claude/kit.json': JSON.stringify({ check: 'make lint' }) })
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.prompt.submit({ text: 'add a login page' } as any)
  expect((seen.at(-1) ?? []).join(' ')).toContain('coordinator')
  await $.command.run({ command: 'kit-mode', args: 'light' } as any)
  await $.prompt.submit({ text: 'what changed?' } as any)
  await $.prompt.submit({ text: 'and now?' } as any)
  expect(seen.at(-1) ?? []).toEqual([])
})

test('a personal default of light beats the kit.json default', async ($, on) => {
  world(on, {
    '/repo/.claude/kit.json': JSON.stringify({ check: 'make lint' }),
    '/home/u/.claude/kit.json': JSON.stringify({ mode: 'light' }),
  })
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.prompt.submit({ text: 'hello' } as any)
  expect(seen.at(-1) ?? []).toEqual([])
})

test('sandbox writes the kit block to settings.local.json and host removes only that', async ($, on) => {
  const { written } = world(on, { '/repo/.claude/settings.local.json': JSON.stringify({ permissions: { allow: ['Bash(npm test)'] } }) })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })

  const on1 = await $.command.run({ command: 'kit-safety', args: 'sandbox' } as any)
  expect(JSON.stringify(on1)).toContain('Sandbox on')
  const local = JSON.parse(written['/repo/.claude/settings.local.json'] ?? '{}')
  expect(local.sandbox.enabled).toBe(true)
  expect(local.sandbox.allowUnsandboxedCommands).toBe(false)
  expect(local.permissions.allow).toEqual(['Bash(npm test)'])

  await $.command.run({ command: 'kit-safety', args: 'host' } as any)
  const after = JSON.parse(written['/repo/.claude/settings.local.json'] ?? '{}')
  expect(after.sandbox).toBeUndefined()
  expect(after.permissions.allow).toEqual(['Bash(npm test)'])
})

test('the kit does not overwrite a sandbox the person configured', async ($, on) => {
  const own = { sandbox: { enabled: true, network: { allowedDomains: ['example.com'] } } }
  const { written } = world(on, { '/repo/.claude/settings.local.json': JSON.stringify(own) })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const answer = await $.command.run({ command: 'kit-safety', args: 'sandbox' } as any)
  expect(JSON.stringify(answer)).toContain('left them as they are')
  expect(written['/repo/.claude/settings.local.json']).toBeUndefined()
  await $.command.run({ command: 'kit-safety', args: 'host' } as any)
  expect(written['/repo/.claude/settings.local.json']).toBeUndefined()
})

test('the status line follows the board on every tick', async ($, on) => {
  const files: Record<string, string> = {
    '/repo/.claude/lead/board.md': [
      'NEEDS YOU: A1: which region?',
      'A1 | ship | login | DONE WHEN e2e passes | review | agent A1 | PR #3 | CI green',
    ].join('\n'),
  }
  const { clock } = world(on, files)
  const lines: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(lines.at(-1)).toBe('light · host · $1.50 · 1 ready · 1 need you')

  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: none',
    'A1 | ship | login | DONE WHEN e2e passes | done | agent A1 | PR #3 | merged',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).not.toContain('ready')
  expect(lines.at(-1)).not.toContain('need you')
})

test('a thread waiting for an answer counts on the line; a board that gains work for the person keeps the line right', async ($, on) => {
  const files: Record<string, string> = {
    '/repo/.claude/lead/board.md': 'NEEDS YOU: none\nA1 | ship | login | DONE WHEN e2e | working | agent A1 | - | started',
  }
  const { clock } = world(on, files, [{ id: 'A1', status: 'waiting' }, { id: 'A2', status: 'running' }])
  const lines: (string | undefined)[] = []
  const notices: any[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  on('ui.notify', (_, e: any) => {
    notices.push(e)
    return { value: { isSent: true, channel: 'terminal' } }
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(lines.at(-1)).toBe('light · host · $1.50 · 1 running · 1 waiting')
  expect(notices).toEqual([])

  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: A1: which region?',
    'A1 | ship | login | DONE WHEN e2e | review | agent A1 | PR #3 | CI green',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).toContain('1 ready · 1 need you')
  // one native notification for the gain, with both counts
  expect(notices.length).toBe(1)
  expect(notices[0].text).toBe('kit: 1 ready for review, 1 needs you. See the board (.claude/lead/board.md) or ask the coordinator.')

  await clock.advance(15000)
  expect(lines.at(-1)).toContain('1 ready · 1 need you')
  expect(notices.length).toBe(1) // the same board again: nothing new to say
})

test('the board may be a Markdown table, capitalise a status or drop a cell; needs-you and queued rows count', async ($, on) => {
  const files: Record<string, string> = {
    '/repo/.claude/lead/board.md': [
      'SHIP: pr | PARALLEL: 3 | BUDGET: none',
      '| id | kind | goal | done when | status | agent | branch/PR | last event |',
      '|---|---|---|---|---|---|---|---|',
      '| A1 | ship | login | DONE WHEN e2e passes | Review | agent A1 | PR #3 | CI green |',
      '| A2 | ship | grid | DONE WHEN snapshot | needs-you | agent A2 | - | which region? |',
      '| A3 | scout | search | DONE WHEN cards | queued | - | - | handed off |',
      '| A4 | ship | export | DONE WHEN csv | queued | - | - | - |',
    ].join('\n'),
  }
  const { clock } = world(on, files)
  const lines: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  // no NEEDS YOU line: the needs-you row still counts
  expect(lines.at(-1)).toBe('light · host · $1.50 · 2 queued · 1 ready · 1 need you')

  // plain rows: one without its DONE WHEN cell and a bold status, one whose question is both a
  // NEEDS YOU entry and a needs-you row (counted once)
  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: A2: which region?',
    'A1 | ship | login | **review** | agent A1 | PR #3 | CI green',
    'A2 | ship | grid | DONE WHEN snapshot | NEEDS-YOU | agent A2 | - | which region?',
    'A3 | scout | search | DONE WHEN cards | working | agent A3 | - | started',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).toBe('light · host · $1.50 · 1 ready · 1 need you')
})

test('no notification for a board change while the person is typing here; one once they have been quiet a minute', async ($, on) => {
  const files: Record<string, string> = {
    '/repo/.claude/lead/board.md': 'NEEDS YOU: none\nA1 | ship | login | DONE WHEN e2e | working | agent A1 | - | started',
  }
  const { clock } = world(on, files)
  const notices: string[] = []
  on('ui.notify', (_, e: any) => {
    notices.push(e.text)
    return { value: { isSent: true, channel: 'terminal' } }
  })
  on('ui.status', () => ({ value: undefined }))
  on('prompt.submit', (_, e) => ({ text: e.text }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.prompt.submit({ text: 'how is A1 going?' } as any)

  files['/repo/.claude/lead/board.md'] = 'NEEDS YOU: none\nA1 | ship | login | DONE WHEN e2e | review | agent A1 | PR #3 | CI green'
  await clock.advance(15000)
  expect(notices).toEqual([]) // they typed 15 s ago: the status line is in front of them

  await clock.advance(60_000)
  files['/repo/.claude/lead/board.md'] = 'NEEDS YOU: A1: which region?\nA1 | ship | login | DONE WHEN e2e | review | agent A1 | PR #3 | CI green'
  await clock.advance(15000)
  expect(notices).toEqual(['kit: 1 needs you. See the board (.claude/lead/board.md) or ask the coordinator.'])
})

test('a pane an older kit left open is closed on session start', async ($, on) => {
  world(on)
  const open = ['kit']
  on('ui.panes', () => ({ value: open.map(id => ({ id, title: id, isShown: true, isFocused: false, isPlaced: true })) }))
  on('ui.close', (_, e: any) => {
    open.splice(open.indexOf(e.id), 1)
    return { value: undefined }
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(open).toEqual([])
})

// The watchdog's wakes are prompts of the kit's own; the test catches them beneath the plugin.
function wakes(on: On) {
  const texts: string[] = []
  on('prompt.submit', (_, e) => {
    texts.push(e.text)
    return { text: e.text }
  })
  return texts
}

test('a background thread that goes silent wakes the coordinator once per stall', async ($, on) => {
  const agents = [{ id: 'a1', description: 'B2 grid', type: 'kit:implementer', status: 'running' }]
  const { clock } = world(on, {}, agents)
  const texts = wakes(on)
  on('tool.call', { tool: 'Agent' }, () => ({ result: { status: 'async_launched', agentId: 'a1', outputFile: '/tmp/a1.output' } }))
  on('fs.stat', () => ({ value: { kind: 'file', size: 1, mtimeMs: 1_000_000, isLink: false } }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'Agent', prompt: 'ITEM: B2', description: 'B2 grid', run_in_background: true } as any)
  await clock.advance(19 * 60_000)
  expect(texts).toEqual([])
  await clock.advance(2 * 60_000)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('thread B2 grid (a1) has written nothing for 20 min')
  await clock.advance(10 * 60_000)
  expect(texts.length).toBe(1)
})

test('a thread waiting on a Monitor is not silent until the Monitor\'s own timeout ends', async ($, on) => {
  const agents = [{ id: 'a1', description: 'B2 grid', type: 'kit:implementer', status: 'running' }]
  const { clock } = world(on, {}, agents)
  const texts = wakes(on)
  on('tool.call', { tool: 'Agent' }, () => ({ result: { status: 'async_launched', agentId: 'a1', outputFile: '/tmp/a1.output' } }))
  on('tool.call', { tool: 'Monitor' }, () => ({ result: { taskId: 'm1', timeoutMs: 40 * 60_000 } }))
  on('fs.stat', () => ({ value: { kind: 'file', size: 1, mtimeMs: 1_000_000, isLink: false } }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'Agent', prompt: 'ITEM: B2', description: 'B2 grid', run_in_background: true } as any)
  await $.tool.call({ tool: 'Monitor', command: 'until x; do sleep 30; done', description: 'CI', timeout_ms: 3_600_000, agentId: 'a1' } as any)
  await clock.advance(39 * 60_000)
  expect(texts).toEqual([])
  await clock.advance(2 * 60_000)
  expect(texts.join('\n')).toContain('thread B2 grid (a1) has written nothing')
})

test('a thread nudged for its report that stops again without one wakes the coordinator', async ($, on) => {
  let missing = 1
  const { clock } = world(on, {}, [], argv => (argv.includes('--missing') ? missing : 0))
  const texts = wakes(on)
  let block: string | undefined = 'kit: no report reached your caller from this run.'
  on('classic.SubagentStop', () => (block ? { block } : {}))
  const stop = (active: boolean) => ($ as any).classic.SubagentStop({ agent_id: 'a1', agent_type: 'kit:implementer', stop_hook_active: active, agent_transcript_path: '/t/a1.jsonl' })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await stop(false)
  block = undefined
  await stop(true)
  await clock.advance(1)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('a1) ended without a report')

  block = 'kit: no report reached your caller from this run.'
  await stop(false)
  block = undefined
  missing = 0
  await stop(true)
  await clock.advance(1)
  expect(texts.length).toBe(1) // it handed back after the nudge: nothing to say
})

test('a transient API failure gets a continue nudge after 15 s; a login failure notifies the person instead', async ($, on) => {
  const { clock } = world(on)
  const texts = wakes(on)
  const notices: string[] = []
  on('ui.notify', (_, e: any) => {
    notices.push(e.text)
    return { value: { isSent: true, channel: 'terminal' } }
  })
  on('classic.StopFailure', () => ({}))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await ($ as any).classic.StopFailure({ error: 'overloaded' })
  await clock.advance(14_000)
  expect(texts).toEqual([])
  await clock.advance(1_000)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('Do not repeat an external operation that already completed')
  await ($ as any).classic.StopFailure({ error: 'authentication_failed' })
  await clock.advance(120_000)
  expect(texts.length).toBe(1)
  expect(notices.join(' ')).toContain('needs you (authentication_failed)')
})

test('the watchdog\'s own wake turn is not activity: a forgotten background command wakes three times, then notifies once', async ($, on) => {
  // thresholds in minutes (kit.json `watchdog`), so the strikes at 1x, 2x and 4x the deadline
  // land at 2, 4 and 8 min: a dozen simulated minutes and some 50 ticks, not 8 hours and 1,920
  const { clock } = world(on, { '/repo/.claude/kit.json': JSON.stringify({ watchdog: { bashDeadlineMin: 2, silentMin: 1 } }) })
  const texts = wakes(on)
  const notices: string[] = []
  on('ui.notify', (_, e: any) => {
    notices.push(e.text)
    return { value: { isSent: true, channel: 'terminal' } }
  })
  on('tool.call', { tool: 'Bash' }, () => ({ result: { backgroundTaskId: 'b1' } }))
  on('turn.complete', (_, e: any) => ({ text: e.answer }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'Bash', command: 'npm run dev', description: 'Start the dev server', run_in_background: true } as any)
  for (let i = 0; i < 12; i++) {
    const before = texts.length
    await clock.advance(60_000)
    // each wake is a turn of the main session: it reads the output and answers
    if (texts.length > before) await ($ as any).turn.complete({ answer: 'still running', durationMs: 1, isAborted: false, reason: 'answer' })
  }
  expect(texts.length).toBe(3)
  expect(notices.length).toBe(1)
})

test('a resumed thread is the same thread: its start and its brief\'s EXPECT are not counted again', async ($, on) => {
  const agents = [{ id: 'a1', description: 'B2 grid', type: 'kit:implementer', status: 'running' }]
  const { clock } = world(on, { '/repo/.claude/kit.json': JSON.stringify({ watchdog: { silentMin: 0 } }) }, agents)
  const texts = wakes(on)
  on('agent.spawn', () => ({ model: 'sonnet', agentId: 'a1' }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const spawn = (extra: any) => ($ as any).agent.spawn({
    tool_use_id: 't1', prompt: 'ITEM: B2\nEXPECT: 30m', description: 'B2 grid', subagentType: 'kit:implementer',
    background: true, fork: false, parentModel: 'sonnet', provider: { plugin: 'engine', tier: 'core' }, ...extra,
  })
  await spawn({})
  await clock.advance(20 * 60_000)
  expect(texts).toEqual([])
  // SendMessage to it: agent.spawn fires again with e.resume; the clock of its EXPECT does not restart
  await spawn({ prompt: 'how far are you?', resume: { agentId: 'a1' } })
  await clock.advance(9 * 60_000)
  expect(texts).toEqual([])
  await clock.advance(60_000)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('thread B2 grid (a1) has run 30 min, past the 30 min its brief expected')
})

test('/kit-safety unattended writes permissions.denyInsteadOfPrompting beside other keys, off removes only that, and the status says so', async ($, on) => {
  const { written } = world(on, { '/repo/.claude/settings.local.json': JSON.stringify({ permissions: { allow: ['Bash(npm test)'] }, model: 'opus' }) })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const before = await $.command.run({ command: 'kit-safety', args: '' } as any)
  expect(JSON.stringify(before)).toContain('Kit safety for this project: host · unattended: off')

  const on1 = await $.command.run({ command: 'kit-safety', args: 'unattended on' } as any)
  expect(JSON.stringify(on1)).toContain('Unattended on for this project')
  expect(JSON.stringify(on1)).toContain('a tool call that would wait on a permission prompt is denied instead and the turn continues')
  const local = JSON.parse(written['/repo/.claude/settings.local.json'] ?? '{}')
  expect(local.permissions.denyInsteadOfPrompting).toBe(true)
  expect(local.permissions.allow).toEqual(['Bash(npm test)'])
  expect(local.model).toBe('opus')
  const status = await $.command.run({ command: 'kit-safety', args: '' } as any)
  expect(JSON.stringify(status)).toContain('host · unattended: on')

  const off = await $.command.run({ command: 'kit-safety', args: 'unattended off' } as any)
  expect(JSON.stringify(off)).toContain('Unattended off')
  const after = JSON.parse(written['/repo/.claude/settings.local.json'] ?? '{}')
  expect(after.permissions.denyInsteadOfPrompting).toBeUndefined()
  expect(after.permissions.allow).toEqual(['Bash(npm test)'])
  expect(after.model).toBe('opus')
  expect(JSON.stringify(await $.command.run({ command: 'kit-safety', args: '' } as any))).toContain('unattended: off')
})

test('the status line says unattended while the project\'s settings.local.json has the flag on', async ($, on) => {
  world(on, { '/repo/.claude/settings.local.json': JSON.stringify({ permissions: { denyInsteadOfPrompting: true } }) })
  const lines: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(lines.at(-1)).toBe('light · host · unattended · $1.50')
  await $.command.run({ command: 'kit-safety', args: 'unattended off' } as any)
  expect(lines.at(-1)).toBe('light · host · $1.50')
  await $.command.run({ command: 'kit-safety', args: 'unattended on' } as any)
  expect(lines.at(-1)).toBe('light · host · unattended · $1.50')
})

test('/kit-safety unattended on creates settings.local.json when there is none, and off leaves it empty', async ($, on) => {
  const { written } = world(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'kit-safety', args: 'unattended on' } as any)
  expect(JSON.parse(written['/repo/.claude/settings.local.json'] ?? 'null')).toEqual({ permissions: { denyInsteadOfPrompting: true } })
  await $.command.run({ command: 'kit-safety', args: 'unattended off' } as any)
  expect(JSON.parse(written['/repo/.claude/settings.local.json'] ?? 'null')).toEqual({})
})

test('a permission request a hook beneath answered is no prompt: no "waited for your permission" push', async ($, on) => {
  const agents = [{ id: 'a1', description: 'K10', type: 'kit:implementer', status: 'running' }]
  const { clock } = world(on, {}, agents)
  const notices: string[] = []
  on('ui.notify', (_, e: any) => {
    notices.push(e.text)
    return { value: { isSent: true, channel: 'terminal' } }
  })
  let decision: any = { behavior: 'allow' }
  on('classic.PermissionRequest', () => (decision ? { decision } : {}))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ask = () => ($ as any).classic.PermissionRequest({ agent_id: 'a1', tool_name: 'Bash', tool_input: { command: 'python3 gate.py verify' } })
  await ask()
  await clock.advance(3 * 60_000)
  expect(notices).toEqual([])
  decision = undefined
  await ask()
  await clock.advance(3 * 60_000)
  expect(notices.length).toBe(1)
})
