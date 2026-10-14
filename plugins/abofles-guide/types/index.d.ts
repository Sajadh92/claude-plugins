export type GuideItem = {
  id?: string // stable per underlying thing (fail:<agent>, dec:<n>, ctx:<mark>, …); absent in older state files: text stands in
  p: string // the priority emoji (🔴🟠🟡⏳🧠💰✅)
  text: string
  fill: string // what Use puts in the prompt box and Copy copies
  resolve: string[] | null // argv Resolve runs (cwd = Guide.root), or null
  recheck?: string | null // 🔴 items: the prompt Re-check puts in the prompt box (no Resolve then)
  unresolve?: string[] | null // argv Undo runs (cwd = Guide.root) after a successful Resolve, or null
}

export type Guide = {
  line: string
  ts: number
  root: string
  items: GuideItem[]
  ctx: { tokens: number; mark: number | null } | null // mark in K tokens; null: past the last mark
  task: { spawns: number; usd: number; budget: number | null; left: number | null } | null
  main: string | null // "suggest Opus 5.5 · Medium (now Fable 5.1 · Medium)"; null when the main session fits
}

declare module 'claude-code' {
  interface PluginState {
    // `hiddenKey`: the ids of the items shown when the person hid the band (Hide or Use), plus the memo mark when the
    // memo was due; the band stays down while those are the same, and comes back when an item appears or goes.
    // `armed`: the item (by id) whose Resolve was pressed once, with the clock time; the second press within 5 s runs it.
    // `lastResolved`: the last successful Resolve, kept for Undo until the next turn completes.
    // `running`: true while a Resolve or Undo command runs; both buttons are gone meanwhile.
    // `toasted`: the ids of the red items already toasted; a toast fires only for a red id not in it.
    'abofles-guide': {
      guide: Guide | null
      hiddenKey: string | null
      armed: { id: string; ts: number } | null
      lastResolved: { text: string; unresolve: string[] | null; root?: string; ts: number } | null
      running: boolean
      toasted: string[]
    }
  }
}
