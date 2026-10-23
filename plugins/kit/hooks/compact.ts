// Compacts the main conversation at the end of a turn once the context is past the kit's
// `context.compactAt` and the handoff note is current. The decision is context_guard.py's
// (`--should-compact`), so the command hooks and this module share one state and one test suite.
// Command hooks cannot start a compaction; a hooks module can, between turns.
// Called from kit.tsx's one `turn.complete` hook, after the turn's result.
import type { EngineInterface, TurnCompleteInput } from 'claude-code'

export async function compactAfterTurn($: EngineInterface, e: TurnCompleteInput): Promise<void> {
  if (e.agentId !== undefined || e.isAborted) return
  try {
    const { context } = await $.session.usage()
    if (!context.tokens) return
    const input = JSON.stringify({
      session_id: await $.session.id(),
      cwd: await $.session.cwd(),
      tokens: context.tokens,
    })
    const script = `${$.plugin.root}/hooks/scripts/context_guard.py`
    const { exitCode, stdout } = await $.process.run(['python3', script, '--should-compact'], { stdin: input })
    const answer = exitCode === 0 ? JSON.parse(stdout) : {}
    if (answer.compact === true) {
      // not awaited: the engine compacts between turns, after this hook has returned
      void $.session.compact({ instructions: String(answer.instructions ?? '') }).catch(() => undefined)
    }
  } catch {
    // a failed check never breaks the turn; Claude Code's own auto-compact still applies
  }
}
