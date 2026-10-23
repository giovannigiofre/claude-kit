// The kit mod's state contract: what its pane and status line draw from.

export type KitMode = 'light' | 'loop'
export type KitSafety = 'host' | 'sandbox'

export type KitAgentRow = {
  id: string
  label: string
  status: string
  tokens: number
  turns: number
  lastAt: number
}

export type KitBoardItem = { id: string; kind: string; goal: string; status: string }

export type KitOvernightRun = {
  runId: string
  branch: string
  iteration: number
  costUsd: number
  tokens: number
  commits: number
  stopReason: string | null
  updatedAt: number
}

export type KitSnapshot = {
  root: string
  mode: KitMode
  safety: KitSafety
  sandboxFrom: 'kit' | 'settings' | 'none'
  costUsd: number | null
  contextPercent: number | null
  limits: { kind: string; percentUsed: number }[]
  board: { header: string; needsYou: string[]; items: KitBoardItem[] } | null
  overnight: KitOvernightRun[]
  crons: { schedule: string; prompt: string }[]
  updatedAt: number
}

declare module 'claude-code' {
  interface PluginState {
    kit: {
      snapshot: Shaped<KitSnapshot | null>
      agents: Shaped<KitAgentRow[]>
    }
  }
}
