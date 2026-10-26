import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

// The world beneath the kit mod: a repo at /repo, a home at /home/u, files in memory.
function world(on: On, files: Record<string, string> = {}) {
  mock.store(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  const written: Record<string, string> = {}
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 200000, percent: 12 }, rateLimits: [], cost: { usd: 1.5 } } }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: '/repo\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
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
  on('agent.list', () => ({ value: [] }))
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
