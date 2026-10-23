// The kit's one hooks module: compaction at the end of a turn, and the kit panel
// (light/loop mode, host/sandbox safety, a live view of agents, captain board,
// overnight runs and loops, and a status line entry).
import type { Register } from 'claude-code'

import { compactAfterTurn } from './compact.ts'
import { recordUsage, register as registerPanel } from './panel.tsx'

export const register: Register = (on, options) => {
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await recordUsage($, e)
    await compactAfterTurn($, e)
    return result
  })
  registerPanel(on, options)
}
