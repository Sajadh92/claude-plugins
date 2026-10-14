export type GuideItem = {
  p: string // the priority emoji (🔴🟠🟡⏳🧠💰✅)
  text: string
  fill: string // what Use puts in the prompt box and Copy copies
  resolve: string[] | null // argv Resolve runs (cwd = Guide.root), or null
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
    // `hiddenKey`: the priorities (🔴🟡…) of the line the person hid (Hide or Use); the band stays down while the
    // ladder keeps those priorities, and comes back when one appears or goes.
    'abofles-guide': { guide: Guide | null; hiddenKey: string | null }
  }
}
