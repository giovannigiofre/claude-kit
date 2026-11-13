import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

// The world beneath the kit mod: a repo at /repo, a home at /home/u, files in memory.
function world(on: On, files: Record<string, string> = {}, agents: any[] = [], exitCode = (_argv: string[]) => 0,
               stdout = (_argv: string[]) => '/repo\n') {
  mock.store(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  const written: Record<string, string> = {}
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 200000, percent: 12 }, rateLimits: [], cost: { usd: 1.5 } } }))
  on('process.run', (_, e: any) => ({ value: { exitCode: exitCode(e.argv), stdout: stdout(e.argv), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('fs.read', (_, e: any) => {
    const text = written[e.path] ?? files[e.path]
    if (text === undefined) return { deny: `ENOENT ${e.path}` }
    return { value: text }
  })
  on('fs.write', (_, e: any) => {
    written[e.path] = e.text
    return { value: undefined }
  })
  on('fs.list', (_, e: any) => { // the folders under a path, from the files in memory
    const dir = `${e.path}/`
    const names = [...new Set(Object.keys(files).filter(f => f.startsWith(dir)).map(f => f.slice(dir.length).split('/')[0]))]
    return names.length ? { value: names.map(name => ({ name, kind: 'dir' })) } : { deny: 'ENOENT' }
  })
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
  expect((seen.at(-1) ?? []).join(' ')).not.toContain('Remote Control')
  // over Remote Control the person is on a phone, where neither the line nor that ping shows:
  // there the coordinator pushes itself
  await $.prompt.submit({ text: 'and a logout', origin: { kind: 'bridge' } } as any)
  expect((seen.at(-1) ?? []).join(' ')).toContain('this message came over Remote Control')
  expect((seen.at(-1) ?? []).join(' ')).toContain('send one PushNotification yourself when an item becomes ready or needs them')

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

test('an interim task notice is dropped before it becomes a turn; a report, a mix or the same text typed passes', async ($, on) => {
  world(on)
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const block = (summary: string, result: string) => `<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n` +
    `<summary>${summary}</summary>\n<result>${result}</result>\n</task-notification>`
  const interim = block('Agent "B2 login page" is waiting on its own background work',
    'This agent has not reported yet: it is waiting on its own background work and will deliver its report through SubagentHandback when that finishes.')
  const report = block('Agent "B2 login page" completed', 'STATUS: done')
  const held = await $.prompt.submit({ text: interim, origin: { kind: 'task-notification' } } as any)
  expect(JSON.stringify(held)).toContain('held an interim notice')
  expect(seen.length).toBe(0)
  await $.prompt.submit({ text: report, origin: { kind: 'task-notification' } } as any)
  await $.prompt.submit({ text: `${interim}\n${report}`, origin: { kind: 'task-notification' } } as any)
  await $.prompt.submit({ text: interim } as any) // the person pasted it: theirs to send
  expect(seen.length).toBe(3)
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

test('a worktree without kit.json of its own uses the main checkout\'s', async ($, on) => {
  // /repo is a linked worktree of /main: kit.json is personal (kept out of git), so only /main has it
  const commonDir = (argv: string[]) => (argv.includes('--git-common-dir') ? '/main/.git\n' : '/repo\n')
  world(on, { '/main/.claude/kit.json': JSON.stringify({ check: 'make lint' }) }, [], () => 0, commonDir)
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.prompt.submit({ text: 'add a login page' } as any)
  expect((seen.at(-1) ?? []).join(' ')).toContain('coordinator')
})

test('a worktree whose main checkout has no kit.json stays light', async ($, on) => {
  const commonDir = (argv: string[]) => (argv.includes('--git-common-dir') ? '/main/.git\n' : '/repo\n')
  world(on, {}, [], () => 0, commonDir)
  const seen = promptCatcher(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.prompt.submit({ text: 'add a login page' } as any)
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
  expect(lines.at(-1)).toBe('light · host · $1.50 · needs you 1: A1 · ready 1: A1')

  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: none',
    'A1 | ship | login | DONE WHEN e2e passes | done | agent A1 | PR #3 | merged',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).toBe('light · host · $1.50')
})

test('the board and overnight runs are read from .kit first, then .claude', async ($, on) => {
  const files: Record<string, string> = {
    '/repo/.claude/kit.json': JSON.stringify({ lead: { board: '.claude/lead/board.md' } }),
    '/repo/.kit/lead/board.md': 'NEEDS YOU: none\nB1 | ship | moved | DONE WHEN e2e | review | agent B1 | PR #4 | CI green',
    '/repo/.claude/lead/board.md': 'NEEDS YOU: none\nA1 | ship | old | DONE WHEN e2e | review | agent A1 | PR #3 | CI green',
    '/repo/.kit/overnight/r1/state.json': JSON.stringify({ stop_reason: null }),
    '/repo/.claude/overnight/r0/state.json': JSON.stringify({ stop_reason: null }),
  }
  world(on, files)
  const lines: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  // the old default board path in kit.json follows the move; a run in either layout is live
  expect(lines.at(-1)).toBe('loop · host · $1.50 · ready 1: B1 · 2 overnight')
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
  // the board's own row, by name, not the engine's count of every subagent
  expect(lines.at(-1)).toBe('light · host · $1.50 · working 1: A1 · 1 waiting on a prompt')
  expect(notices).toEqual([])

  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: A1: which region?',
    'A1 | ship | login | DONE WHEN e2e | review | agent A1 | PR #3 | CI green',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).toContain('needs you 1: A1 · ready 1: A1')
  // one native notification for the gain, naming the item and its question
  expect(notices.length).toBe(1)
  expect(notices[0].text).toBe('kit: needs you: A1 (which region?) · ready for review: A1')

  await clock.advance(15000)
  expect(lines.at(-1)).toContain('needs you 1: A1 · ready 1: A1')
  expect(notices.length).toBe(1) // the same board again: nothing new to say

  // one item leaves review as another enters: the counts are the same, the news is not
  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: A1: which region?',
    'A1 | ship | login | DONE WHEN e2e | done | agent A1 | PR #3 | merged',
    'A2 | ship | export | DONE WHEN csv | review | agent A2 | PR #4 | CI green',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).toContain('needs you 1: A1 · ready 1: A2')
  expect(notices.length).toBe(2)
  expect(notices[1].text).toBe('kit: ready for review: A2')
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
  expect(lines.at(-1)).toBe('light · host · $1.50 · needs you 1: A2 · ready 1: A1 · queued 2')

  // plain rows: one without its DONE WHEN cell and a bold status, one whose question is both a
  // NEEDS YOU entry and a needs-you row (counted once)
  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: A2: which region?',
    'A1 | ship | login | **review** | agent A1 | PR #3 | CI green',
    'A2 | ship | grid | DONE WHEN snapshot | NEEDS-YOU | agent A2 | - | which region?',
    'A3 | scout | search | DONE WHEN cards | working | agent A3 | - | started',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).toBe('light · host · $1.50 · needs you 1: A2 · ready 1: A1 · working 1: A3')

  // a row that dropped its agent cell keeps its status ("DONE WHEN ..." is not `done`); a `;` inside a
  // question starts no second question; more than two ids are cut to a count; a long id is shortened
  files['/repo/.claude/lead/board.md'] = [
    'NEEDS YOU: A2: eu-west; or us-east?; pr-328: merge now?; a-very-long-item-identifier-here: ok?',
    'A1 | ship | login | DONE WHEN e2e passes | review | PR #3 | CI green',
    'A5 | ship | chart | DONE WHEN snapshot | landing | agent A5 | PR #9 | merging',
  ].join('\n')
  await clock.advance(15000)
  expect(lines.at(-1)).toBe('light · host · $1.50 · needs you 3: A2, pr-328 +1 · ready 1: A1 · working 1: A5')
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
  expect(notices).toEqual(['kit: needs you: A1 (which region?)'])
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

// Files with an mtime each, for fs.stat: a thread's transcript and its commands' output files.
function stats(on: On, files: Record<string, string>, mtimes: Record<string, number>) {
  on('fs.stat', (_, e: any) => (mtimes[e.path] === undefined ? { deny: `ENOENT ${e.path}` }
    : { value: { kind: 'file', size: (files[e.path] ?? '').length, mtimeMs: mtimes[e.path], isLink: false } }))
  on('ui.notify', () => ({ value: { isSent: true, channel: 'terminal' } }))
}

// 2026-11-09: the coordinator stopped a thread and resumed it with SendMessage; 15 s later the
// watchdog said it "has written nothing for 57 min", counting from its last tool call before.
test('a resumed thread\'s silence counts from the resume, not from its last tool call before the stop', async ($, on) => {
  const agents = [{ id: 'a1', description: 'PRIV-12', type: 'kit:implementer', status: 'running' }]
  const { clock } = world(on, {}, agents)
  const texts = wakes(on)
  stats(on, {}, { '/tasks/a1.output': 1_000_000 })
  on('tool.call', { tool: 'Agent' }, () => ({ result: { status: 'async_launched', agentId: 'a1', outputFile: '/tasks/a1.output' } }))
  on('tool.call', { tool: 'Bash' }, () => ({ result: { backgroundTaskId: 'b1' } }))
  on('tool.call', { tool: 'TaskStop' }, () => ({ result: {} }))
  on('agent.spawn', () => ({ model: 'opus', agentId: 'a1' }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'Agent', prompt: 'ITEM: P12', description: 'PRIV-12', run_in_background: true } as any)
  await $.tool.call({ tool: 'Bash', command: 'pnpm test:api', description: 'API suite', timeout: 7_200_000, run_in_background: true, agentId: 'a1' } as any)
  await clock.advance(57 * 60_000)
  expect(texts).toEqual([]) // it waits on its own command, within its deadline
  await $.tool.call({ tool: 'TaskStop', task_id: 'b1' } as any)
  await ($ as any).agent.spawn({ tool_use_id: 't2', prompt: 'Resume: your suite passed', description: 'PRIV-12',
    subagentType: 'kit:implementer', background: true, fork: false, parentModel: 'opus', provider: { plugin: 'engine', tier: 'core' },
    resume: { agentId: 'a1' } })
  await clock.advance(15_000)
  expect(texts).toEqual([])
  await clock.advance(20 * 60_000)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('has written nothing for 20 min')
})

test('a thread the mod lost its record of (it finished, then was resumed) is still timed by its transcript', async ($, on) => {
  const agents = [{ id: 'a1', description: 'PRIV-12', type: 'kit:implementer', status: 'running' }]
  const { clock } = world(on, {}, agents)
  const texts = wakes(on)
  const mtimes: Record<string, number> = { '/tasks/a1.output': 1_000_000 }
  stats(on, {}, mtimes)
  on('tool.call', { tool: 'Agent' }, () => ({ result: { status: 'async_launched', agentId: 'a1', outputFile: '/tasks/a1.output' } }))
  on('tool.call', { tool: 'Bash' }, () => ({ result: {} }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'Agent', prompt: 'ITEM: P12', description: 'PRIV-12', run_in_background: true } as any)
  agents[0].status = 'completed' // it reported: the tick forgets it
  await clock.advance(15_000)
  agents[0].status = 'running' // a SendMessage resumed it
  await $.tool.call({ tool: 'Bash', command: 'pnpm check', agentId: 'a1' } as any)
  for (let m = 1; m <= 25; m++) {
    if (m <= 10) mtimes['/tasks/a1.output'] = clock.now() // it writes for 10 min, no tool call finishes
    await clock.advance(60_000)
  }
  expect(texts).toEqual([])
  await clock.advance(6 * 60_000)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('has written nothing for 20 min')
})

test('a command whose output file ends with the exit line no longer hides a quiet thread: the wake names it, the holder and the prompt', async ($, on) => {
  const agents = [{ id: 'a1', description: 'PRIV-12', type: 'kit:implementer', status: 'running' }]
  const files: Record<string, string> = { '/tasks/b1.output': 'Tests  298 passed (298)\n' }
  const { clock } = world(on, files, agents)
  const texts = wakes(on)
  const mtimes: Record<string, number> = { '/tasks/a1.output': 1_000_000, '/tasks/b1.output': 1_000_000, '/tasks/b2.output': 1_000_000 }
  stats(on, files, mtimes)
  let task = 'b2'
  on('tool.call', { tool: 'Agent' }, () => ({ result: { status: 'async_launched', agentId: 'a1', outputFile: '/tasks/a1.output' } }))
  on('tool.call', { tool: 'Bash' }, () => ({ result: { backgroundTaskId: task } }))
  on('classic.PermissionRequest', () => ({}))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'Agent', prompt: 'ITEM: P12', description: 'PRIV-12', run_in_background: true } as any)
  await $.tool.call({ tool: 'Bash', command: 'sh hold.sh', description: 'Hold the stack lock for the push (server)', run_in_background: true, agentId: 'a1' } as any)
  task = 'b1'
  await $.tool.call({ tool: 'Bash', command: 'lockf x pnpm test:api', description: 'API suite under the lock', timeout: 3_600_000, run_in_background: true, agentId: 'a1' } as any)
  await ($ as any).classic.PermissionRequest({ agent_id: 'a1', tool_name: 'Bash', tool_input: { command: 'git push origin fix/x' } })
  await clock.advance(3 * 60_000)
  files['/tasks/b1.output'] += '\n[exited with code 0]\n'
  mtimes['/tasks/b1.output'] = clock.now()
  await clock.advance(16 * 60_000)
  expect(texts).toEqual([])
  await clock.advance(2 * 60_000)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('thread PRIV-12 (a1) has written nothing for 20 min')
  expect(texts[0]).toContain('on a permission prompt (Bash git push origin fix/x): only the person can answer it')
  expect(texts[0]).toContain('b1 "API suite under the lock" ended 17 min ago and it has not acted since (its output ends: Tests  298 passed (298) / [exited with code 0])')
  expect(texts[0]).toContain('b2 "Hold the stack lock for the push (server)" is a holder')
})

test('a thread parked on a command that ended is woken for within minutes, and dropped once its notice lands', async ($, on) => {
  const agents = [{ id: 'a1', description: 'PRIV-12', type: 'kit:implementer', status: 'waiting' }]
  const files: Record<string, string> = { '/tasks/b1.output': '' }
  const { clock } = world(on, files, agents)
  const texts = wakes(on)
  const mtimes: Record<string, number> = { '/tasks/a1.output': 1_000_000, '/tasks/b1.output': 1_000_000 }
  stats(on, files, mtimes)
  on('tool.call', { tool: 'Agent' }, () => ({ result: { status: 'async_launched', agentId: 'a1', outputFile: '/tasks/a1.output' } }))
  on('tool.call', { tool: 'Bash' }, () => ({ result: { backgroundTaskId: 'b1' } }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'Agent', prompt: 'ITEM: P12', description: 'PRIV-12', run_in_background: true } as any)
  await $.tool.call({ tool: 'Bash', command: 'pnpm test:e2e', description: 'e2e', timeout: 3_600_000, run_in_background: true, agentId: 'a1' } as any)
  await clock.advance(2 * 60_000)
  files['/tasks/b1.output'] = '  18 passed (8.4m)\n\n[exited with code 0]\n'
  mtimes['/tasks/b1.output'] = clock.now()
  await clock.advance(4 * 60_000)
  expect(texts).toEqual([])
  await clock.advance(60_000)
  expect(texts.length).toBe(1)
  expect(texts[0]).toContain('has waited 5 min on its own background work, but nothing it waits on will wake it')
  expect(texts[0]).toContain('the notice was lost or the thread is blocked')
  expect(texts[0]).toContain('To resume it: TaskStop a1, then SendMessage a1')
  // the notice lands (its transcript moves): the command is no longer on record
  mtimes['/tasks/a1.output'] = clock.now()
  await clock.advance(60 * 60_000)
  expect(texts.length).toBe(1)
})
