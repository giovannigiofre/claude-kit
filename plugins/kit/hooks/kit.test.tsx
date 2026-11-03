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
  expect(notices.length).toBeLessThanOrEqual(1)
  if (notices.length) expect(notices[0].text).toContain('kit: 1 ready for review, 1 needs you')

  await clock.advance(15000)
  expect(lines.at(-1)).toContain('1 ready · 1 need you')
  expect(notices.length).toBeLessThanOrEqual(1)
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
