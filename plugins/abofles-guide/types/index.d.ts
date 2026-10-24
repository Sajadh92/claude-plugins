export type GuideItem = {
  id?: string // stable per underlying thing (fail:<agent>, dec:<n>, ctx:<mark>, …); absent in older state files: text stands in
  p: string // the priority emoji (🔴🟠🟡⏳🧠💰✅)
  text: string
  fill: string // what Use puts in the prompt box and Copy copies
  recheck?: string | null // 🔴🟠🟡 items: the prompt Re-check puts in the prompt box (Claude verifies, then resolves)
  // The hook still writes `resolve: null` and `unresolve: null` on every item; the band never reads them.
}

export type Guide = {
  line: string
  ts: number
  root: string
  items: GuideItem[]
  ctx: { tokens: number; mark: number | null } | null // mark in K tokens; null: past the last mark
  task: { spawns: number; usd: number; budget: number | null; left: number | null } | null
  main: string | null // "suggest Opus 5.5 · Medium (now Fable 5.1 · Medium)"; null when the main session fits
  // Claude's last resolve, kept by the hook until the Stop of the turn after it; null when nothing. Undo runs `unresolve` (cwd = root).
  last_resolved: { text: string; unresolve: string[]; ts: number } | null
}

// ---- the Abo Fles pane: `pane` in the session's state file, written by the abofles hooks (v 1). Every part is optional to the mod:
// cleanPane() drops what is malformed and keeps the rest; a state file from older hooks has no `pane` at all.

export type PanePlaces = {
  guide: 'pane' | 'band' // where the guide shows; old hooks: the band
  resume: 'pane' | 'output' // where /abofles:resume shows; old hooks: the output
  spawns: 'pane' | 'output' // where /abofles:bill shows; old hooks: the output
}

export type PaneResume = {
  head: string
  now: string[]
  left: string[]
  next: string[]
  needs: { n: number | null; text: string }[] // the open decisions, numbered as the memo numbers them
  needs_open: number
  last: string[]
}

export type PaneLive = { side: string; model: string; effort: string; description: string; ts: number | null } // ts: epoch seconds

export type PaneRow = {
  ts: number | null
  side: string
  model: string
  effort: string
  topic: string
  tier: string | null
  status: string | null
  confidence: string | null
  tokens: number | null
  usd: number | null
  base_usd: number | null
  description: string
  verdict: string | null
  task: string | null // the task the spawn belongs to; rows are grouped by it
}

export type PaneTotals = { spawns: number; tokens: number; usd: number; base_usd: number; saved_pct: number; open_fail: number }

export type PaneSpawns = { live: PaneLive[]; rows: PaneRow[]; totals: PaneTotals } // rows: the last 30, oldest first

export type PaneOverrideKey = { key: string; kind: string; options: string[]; value: string; source: string; default: string }

export type PaneOverrides = {
  files: { project: string; user: string }
  keys: PaneOverrideKey[]
  raw: { line: string; source: string }[] // override lines the table cannot show
}

export type Pane = {
  v: 1
  ts: number
  root: string
  sid: string
  places: PanePlaces
  resume: PaneResume | null // null: no memo yet
  spawns: PaneSpawns
  overrides: PaneOverrides | null
  cmd: { overrides: string[] | null } // argv prefix of the script the overrides editor runs
}

declare module 'claude-code' {
  interface PluginState {
    // `hiddenKey`: the ids of the items shown when the person hid the band (Hide or Use), plus the memo mark when the
    // memo was due; the band stays down while those are the same, and comes back when an item appears or goes.
    // `dismissedTs`: the `ts` of the last_resolved row the person hid; that row stays down.
    // `running`: true while an Undo command runs; its button is gone meanwhile.
    // `toasted`: the ids of the red items already toasted; a toast fires only for a red id not in it.
    // `pane`: the pane payload of the state file (null: older hooks, or none yet).
    // `paneOpen`: true after the person or a command opened the pane, false after it was closed by hand or by the
    // command, null while undecided; also kept in $.store under `paneOpen` so a new session honours it.
    // `paneAuto`: true once this session tried the unasked open (once per session).
    // `paneDraft`: unsaved values of the overrides editor, by override key (+ '@scope', '@raw', '@custom:<key>').
    // `paneSaving`: true while the editor's Save runs its command.
    // `paneView`: the page the pane shows: 'main' (the cards) or 'overrides' (the editor).
    // `paneFolds`: open (true) or folded (false) by id: a card, an editor group (`g:<name>`), a long list (`more:<id>`); also in $.store.
    'abofles-guide': {
      guide: Guide | null
      hiddenKey: string | null
      dismissedTs: number | null
      running: boolean
      toasted: string[]
      pane: Pane | null
      paneOpen: boolean | null
      paneAuto: boolean
      paneDraft: Record<string, string>
      paneSaving: boolean
      paneView: 'main' | 'overrides'
      paneFolds: Record<string, boolean>
    }
  }
}
