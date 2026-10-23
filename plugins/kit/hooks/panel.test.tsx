import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

// The world beneath the kit mod: a repo at /repo, a home at /home/u, files in memory.
function world(on: On, files: Record<string, string> = {}) {
  mock.store(on)
  mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  const written: Record<string, string> = {}
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('ui.panes', () => ({ value: [] }))
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
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  return written
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
  const written = world(on, { '/repo/.claude/settings.local.json': '{ "permissions": { "allow": [ ' })
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

test('sandbox writes the kit block to settings.local.json and host removes only that', async ($, on) => {
  const written = world(on, { '/repo/.claude/settings.local.json': JSON.stringify({ permissions: { allow: ['Bash(npm test)'] } }) })
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
  const written = world(on, { '/repo/.claude/settings.local.json': JSON.stringify(own) })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const answer = await $.command.run({ command: 'kit-safety', args: 'sandbox' } as any)
  expect(JSON.stringify(answer)).toContain('left them as they are')
  expect(written['/repo/.claude/settings.local.json']).toBeUndefined()
  await $.command.run({ command: 'kit-safety', args: 'host' } as any)
  expect(written['/repo/.claude/settings.local.json']).toBeUndefined()
})

const PANE = {
  plugin: 'kit',
  component: 'Pane',
  requestId: 'kit',
  props: {
    title: 'Kit',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

test('the pane shows mode, safety, spend and what needs the person, on every surface', async ($, on) => {
  const board = [
    'SHIP: pr+fix | PARALLEL: 3 | BUDGET: none',
    'RULES: reuse the thread for follow-ups | propose before starting',
    'NEEDS YOU: A1: send emails in production or only log in dev?',
    'A2 | scout | Supabase or SQLite | DONE WHEN report written | done | agent A2 | - | report ready',
    'A3 | ship | CSV export | DONE WHEN download test passes | review | agent A3 | PR #4 | CI green',
    'A1 | ship | magic-link login | DONE WHEN e2e login passes | needs-you | agent A1 | feat/login | PR #3',
  ].join('\n')
  world(on, { '/repo/.claude/lead/board.md': board })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'kit-panel', args: '' } as any)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ key: 'mode-light' })).toBeDefined()
    expect(await ui.find({ key: 'safety-sandbox' })).toBeDefined()
    expect((await ui.find({ type: 'Text', text: /session \$1\.50/ }))?.text).toContain('context 12%')
    expect(await ui.find({ type: 'Text', text: /NEEDS YOU/ })).toBeDefined()
    expect((await ui.find({ type: 'Text', text: /send emails/ }))?.text).toContain('A1')
    expect(await ui.find({ type: 'Text', text: /magic-link login/ })).toBeDefined()
    expect((await ui.find({ type: 'Text', text: /CSV export/ }))?.text).toContain('ready')
    expect(await ui.find({ type: 'Text', text: /reuse the thread/ })).toBeUndefined()
    await ui.press({ key: 'mode-loop' })
    await ui.unmount()
  }
})
