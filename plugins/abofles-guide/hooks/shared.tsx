import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { Guide, GuideItem, Pane, PaneLive, PaneOverrideKey, PaneOverrides, PanePlaces, PaneResume, PaneRow, PaneSpawns, PaneTotals } from '../types'

// What the band (register.tsx) and the pane (pane.tsx) share: the state atoms, the cleaning of the state file's
// `guide` and `pane`, the refresh, and the guide's actions and buttons, so both places run the same code.
const guide = atom({ plugin: 'abofles-guide', key: 'guide' } as const, null)
// What Hide compares: the ids of the shown items (+ the memo mark when the memo is due), see hideKeyOf.
const hiddenKey = atom({ plugin: 'abofles-guide', key: 'hiddenKey' } as const, null)

// The `ts` of the last_resolved row the person hid: that row stays down, a newer resolve (other ts) draws again.
const dismissedTs = atom({ plugin: 'abofles-guide', key: 'dismissedTs' } as const, null)
// Set while Undo runs its command (up to 30 s): the button is gone, a second press is ignored.
const running = atom({ plugin: 'abofles-guide', key: 'running' } as const, false)
// The ids of the red items already toasted: a toast fires only for a red id not in it (kept across reloads).
const toasted = atom({ plugin: 'abofles-guide', key: 'toasted' } as const, [] as string[])

// The pane payload of the state file (null: older hooks, or none yet), see cleanPane.
const pane = atom({ plugin: 'abofles-guide', key: 'pane' } as const, null)
// true after the person or a command opened the pane, false after it was closed; null while undecided. Also kept in $.store.
const paneOpen = atom({ plugin: 'abofles-guide', key: 'paneOpen' } as const, null)
// true once this session tried the unasked open: it is tried once.
const paneAuto = atom({ plugin: 'abofles-guide', key: 'paneAuto' } as const, false)
// The overrides editor's unsaved values by override key ('' = back to the default), plus its own entries: '@scope' (project | user),
// '@raw' (the lines of the complex forms as typed) and '@custom:<key>' (the custom value input of Agents / Receipt is open).
const paneDraft = atom({ plugin: 'abofles-guide', key: 'paneDraft' } as const, {} as Record<string, string>)
// true while the editor's Save runs its command (up to 30 s): a second press is ignored.
const paneSaving = atom({ plugin: 'abofles-guide', key: 'paneSaving' } as const, false)
// Which page the pane shows: the cards, or the overrides editor ('overrides').
const paneView = atom({ plugin: 'abofles-guide', key: 'paneView' } as const, 'main' as 'main' | 'overrides')
// Open (true) or folded (false) by id: a card ('guide'), an editor group ('g:Agents'), a long list ('more:needs'). Kept in $.store too.
const paneFolds = atom({ plugin: 'abofles-guide', key: 'paneFolds' } as const, {} as Record<string, boolean>)

// The atoms are read here alone: the state library's scan wants the reference and its read in one file.
export function getGuide($: EngineInterface) {
  return read($, guide)
}
export function getHiddenKey($: EngineInterface) {
  return read($, hiddenKey)
}
export function getDismissedTs($: EngineInterface) {
  return read($, dismissedTs)
}
export function getRunning($: EngineInterface) {
  return read($, running)
}
export function getPane($: EngineInterface) {
  return read($, pane)
}
export function getPaneOpen($: EngineInterface) {
  return read($, paneOpen)
}
// The overrides editor's unsaved values: read, and change by a function of the current ones.
export function getPaneDraft($: EngineInterface) {
  return read($, paneDraft)
}
export function updatePaneDraft($: EngineInterface, fn: (cur: Record<string, string>) => Record<string, string>) {
  return update($, paneDraft, cur => fn(cur ?? {}))
}

export function getPaneSaving($: EngineInterface) {
  return read($, paneSaving)
}

export async function getPaneView($: EngineInterface): Promise<'main' | 'overrides'> {
  return (await read($, paneView)) === 'overrides' ? 'overrides' : 'main'
}
export function setPaneView($: EngineInterface, view: 'main' | 'overrides') {
  return update($, paneView, () => view)
}

export type Folds = Record<string, boolean>

export async function getFolds($: EngineInterface): Promise<Folds> {
  return (await read($, paneFolds)) ?? {}
}

// Is the card, group or list `id` open? Absent from the map: its default.
export const isOpen = (folds: Folds, id: string, def = true): boolean => (typeof folds[id] === 'boolean' ? folds[id] : def)

// Opens or folds one id, in the atom (the pane redraws) and in $.store (the next session finds it the same).
export async function setFold($: EngineInterface, id: string, open: boolean) {
  let next: Folds = {}
  await update($, paneFolds, cur => (next = { ...(cur ?? {}), [id]: open }))
  try {
    await $.store.set('paneFolds', next)
  } catch {
    // no store: the session's atom is enough
  }
}

// What an earlier session kept (booleans by id), loaded into the atom at the session start.
export async function loadFolds($: EngineInterface) {
  let stored: unknown
  try {
    stored = await $.store.get('paneFolds')
  } catch {
    stored = undefined
  }
  const folds: Folds = {}
  if (isObj(stored)) for (const [k, v] of Object.entries(stored)) if (typeof v === 'boolean') folds[k] = v
  await update($, paneFolds, () => folds)
}

// Takes the editor's "saving" flag; false when a Save already holds it. releaseSave gives it back.
export async function claimSave($: EngineInterface): Promise<boolean> {
  let was = false
  await update($, paneSaving, cur => {
    was = cur === true
    return true
  })
  return !was
}
export function releaseSave($: EngineInterface) {
  return update($, paneSaving, () => false)
}

export const PANE_ID = 'abofles'
export const PANE_TITLE = 'Abo Fles'

export type Ui = ReturnType<EngineInterface['ui']['resolve']>
export type RenderEvent = Parameters<EngineInterface['ui']['resolve']>[0]

// A line of a memo or a ledger as the cards draw it: control bytes and markdown marks (**bold**, `code`, __x__) dropped, spaces folded.
export const plain = (text: string): string =>
  text
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g, '') // terminal control bytes a memo line could carry
    .replace(/\*\*|__|`/g, '')
    .replace(/\s+/g, ' ')
    .trim()

// A card in the look of the desktop app's own side panels (Context, Changes, Environment): a rounded dim border; a header
// row whose left part, the title and a chevron (› folded, ⌄ open), is one plain button that folds the card, and whose right
// part is a short summary (in `tone`, a theme key, or dim); the body only while the card is open. `id` names the fold (see isOpen).
export function card($: EngineInterface, ui: Ui, c: { id: string; title: string; summary?: string | null; tone?: string; folds: Folds; def?: boolean }, body: JSX.Element | (JSX.Element | null)[]) {
  const { Box, Button, Text } = ui
  const open = isOpen(c.folds, c.id, c.def ?? true)
  return (
    <Box flexDirection="column" borderStyle="round" borderDimColor paddingX={1} rowGap={1}>
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1}>
        <Button key={`fold:${c.id}`} plain onPress={() => setFold($, c.id, !open)}>
          <Text weight="semibold">{c.title}</Text>
          <Text dimColor>{open ? ' ⌄' : ' ›'}</Text>
        </Button>
        {c.summary ? (
          <Box flexShrink={1}>
            {c.tone ? <Text color={c.tone}>{c.summary}</Text> : <Text dimColor>{c.summary}</Text>}
          </Box>
        ) : null}
      </Box>
      {open ? body : null}
    </Box>
  )
}

// A row of the side panels: a label on the left and its value, dim (or in `tone`), held at the right.
export function kv(ui: Ui, label: string, value: string, tone?: string) {
  const { Box, Text } = ui
  return (
    <Box flexDirection="row" justifyContent="space-between" columnGap={1}>
      <Box flexShrink={1}>
        <Text>{label}</Text>
      </Box>
      {tone ? <Text color={tone}>{value}</Text> : <Text dimColor>{value}</Text>}
    </Box>
  )
}

// The "Show all N" / "Show less" button of a list longer than `limit` (id `more:<id>`, folded by default), or null.
export function moreButton($: EngineInterface, ui: Ui, folds: Folds, id: string, total: number, limit: number) {
  const { Button } = ui
  if (total <= limit) return null
  const all = isOpen(folds, `more:${id}`, false)
  return <Button key={`more:${id}`} label={all ? 'Show less' : `Show all ${total}`} plain dimColor onPress={() => setFold($, `more:${id}`, !all)} />
}

// A long list: its first `limit` rows, then its moreButton.
export function limited($: EngineInterface, ui: Ui, folds: Folds, id: string, rows: JSX.Element[], limit = 3): (JSX.Element | null)[] {
  if (rows.length <= limit) return rows
  return [...(isOpen(folds, `more:${id}`, false) ? rows : rows.slice(0, limit)), moreButton($, ui, folds, id, rows.length, limit)]
}

export const isStr = (v: unknown): v is string => typeof v === 'string'
export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
export const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const argvOf = (v: unknown): string[] | null => (Array.isArray(v) && v.length > 0 && v.every(isStr) ? v : null)

// An argv the hook published (Undo's `unresolve`, the editor's `cmd.overrides`) runs only in the shape script_cmd gives it: bash, the
// abofles plugin's scripts/py launcher, then one of `scripts` from that same folder (forward slashes; Windows paths too). The state file
// is the user's own, but anything that can write it must not get an arbitrary command run by a press. Any other argv is dropped.
export function scriptArgv(v: unknown, scripts: readonly string[]): string[] | null {
  const a = argvOf(v)
  if (!a || a.length < 3 || !/^(?:.*\/)?bash(?:\.exe)?$/i.test(a[0])) return null
  const m = /^(.*\/abofles(?:\/[^/]+)?\/scripts)\/py$/.exec(a[1])
  if (!m || !scripts.some(name => a[2] === `${m[1]}/${name}`)) return null
  return a
}
const strsOf = (v: unknown): string[] => (Array.isArray(v) ? v.filter(isStr) : [])
const strOr = (v: unknown, d: string): string => (isStr(v) ? v : d)
const numOrNull = (v: unknown): number | null => (isNum(v) ? v : null)
const strOrNull = (v: unknown): string | null => (isStr(v) ? v : isNum(v) ? String(v) : null)

// The id of an item: stable per underlying thing; a state file from before ids has none, so its text stands in.
export const idOf = (it: GuideItem): string => it.id || it.text

// One item from the state file, or null when it lacks a priority or text. Wrong-typed optional fields fall back.
function cleanItem(v: unknown): GuideItem | null {
  if (!isObj(v) || !isStr(v.p) || !isStr(v.text)) return null
  const item: GuideItem = {
    p: v.p,
    text: v.text,
    fill: isStr(v.fill) ? v.fill : '',
    recheck: isStr(v.recheck) && v.recheck.trim() ? v.recheck : null,
  }
  if (isStr(v.id) && v.id) item.id = v.id
  return item
}

// The guide from the state file with every field type-checked (older files lack the newer fields), or null.
export function cleanGuide(raw: unknown): Guide | null {
  if (!isObj(raw) || !isStr(raw.line) || !raw.line) return null
  let ctx: Guide['ctx'] = null
  if (isObj(raw.ctx) && isNum(raw.ctx.tokens) && (raw.ctx.mark == null || isNum(raw.ctx.mark))) {
    ctx = { tokens: raw.ctx.tokens, mark: raw.ctx.mark ?? null }
  }
  let task: Guide['task'] = null
  if (isObj(raw.task) && isNum(raw.task.spawns) && isNum(raw.task.usd)) {
    task = {
      spawns: raw.task.spawns,
      usd: raw.task.usd,
      budget: isNum(raw.task.budget) ? raw.task.budget : null,
      left: isNum(raw.task.left) ? raw.task.left : null,
    }
  }
  // Claude's last resolve, kept by the hook for Undo: needs its text, a ready argv and a timestamp.
  let lastResolved: Guide['last_resolved'] = null
  const lr = raw.last_resolved
  if (isObj(lr) && isStr(lr.text) && isNum(lr.ts)) {
    const unresolve = scriptArgv(lr.unresolve, ['memo.py', 'status.py'])
    if (unresolve) lastResolved = { text: lr.text, unresolve, ts: lr.ts }
  }
  const items = Array.isArray(raw.items) ? raw.items.map(cleanItem).filter((i): i is GuideItem => i !== null) : []
  return { line: raw.line, ts: isNum(raw.ts) ? raw.ts : 0, root: isStr(raw.root) ? raw.root : '', items, ctx, task, main: isStr(raw.main) ? raw.main : null, last_resolved: lastResolved }
}

// Where each thing shows; a missing or unknown place is today's view (guide in the band, resume and spawns in the output).
function cleanPlaces(raw: unknown): PanePlaces {
  const p = isObj(raw) ? raw : {}
  return {
    guide: p.guide === 'pane' ? 'pane' : 'band',
    resume: p.resume === 'pane' ? 'pane' : 'output',
    spawns: p.spawns === 'pane' ? 'pane' : 'output',
  }
}

function cleanResume(raw: unknown): PaneResume | null {
  if (!isObj(raw)) return null
  const needs = Array.isArray(raw.needs)
    ? raw.needs.filter(isObj).filter(n => isStr(n.text)).map(n => ({ n: numOrNull(n.n), text: n.text as string }))
    : []
  return { head: strOr(raw.head, ''), now: strsOf(raw.now), left: strsOf(raw.left), next: strsOf(raw.next), needs, needs_open: isNum(raw.needs_open) ? raw.needs_open : needs.length, last: strsOf(raw.last) }
}

function cleanLive(v: unknown): PaneLive | null {
  if (!isObj(v)) return null
  return { side: strOr(v.side, ''), model: strOr(v.model, ''), effort: strOr(v.effort, ''), description: strOr(v.description, ''), ts: numOrNull(v.ts) }
}

function cleanRow(v: unknown): PaneRow | null {
  if (!isObj(v)) return null
  return {
    ts: numOrNull(v.ts),
    side: strOr(v.side, ''),
    model: strOr(v.model, ''),
    effort: strOr(v.effort, ''),
    topic: strOr(v.topic, ''),
    tier: strOrNull(v.tier),
    status: strOrNull(v.status),
    confidence: strOrNull(v.confidence),
    tokens: numOrNull(v.tokens),
    usd: numOrNull(v.usd),
    base_usd: numOrNull(v.base_usd),
    description: strOr(v.description, ''),
    verdict: strOrNull(v.verdict),
    task: isStr(v.task) && v.task ? v.task : null,
  }
}

function cleanSpawns(raw: unknown): PaneSpawns {
  const s = isObj(raw) ? raw : {}
  const live = Array.isArray(s.live) ? s.live.map(cleanLive).filter((r): r is PaneLive => r !== null) : []
  const rows = Array.isArray(s.rows) ? s.rows.map(cleanRow).filter((r): r is PaneRow => r !== null) : []
  const t = isObj(s.totals) ? s.totals : {}
  const totals: PaneTotals = { spawns: isNum(t.spawns) ? t.spawns : rows.length, tokens: isNum(t.tokens) ? t.tokens : 0, usd: isNum(t.usd) ? t.usd : 0, base_usd: isNum(t.base_usd) ? t.base_usd : 0, saved_pct: isNum(t.saved_pct) ? t.saved_pct : 0, open_fail: isNum(t.open_fail) ? t.open_fail : 0 }
  return { live, rows, totals }
}

function cleanOverrideKey(v: unknown): PaneOverrideKey | null {
  if (!isObj(v) || !isStr(v.key) || !v.key) return null
  return { key: v.key, kind: strOr(v.kind, 'text'), options: strsOf(v.options), value: strOr(v.value, ''), source: strOr(v.source, 'default'), default: strOr(v.default, '') }
}

function cleanOverrides(raw: unknown): PaneOverrides | null {
  if (!isObj(raw)) return null
  const f = isObj(raw.files) ? raw.files : {}
  const keys = Array.isArray(raw.keys) ? raw.keys.map(cleanOverrideKey).filter((k): k is PaneOverrideKey => k !== null) : []
  const lines = Array.isArray(raw.raw) ? raw.raw.filter(isObj).filter(r => isStr(r.line)).map(r => ({ line: r.line as string, source: strOr(r.source, '') })) : []
  return { files: { project: strOr(f.project, ''), user: strOr(f.user, '') }, keys, raw: lines }
}

// The pane payload from the state file with every part type-checked, or null (no payload, or one of another version).
// A malformed part is dropped and the rest kept; it never throws.
export function cleanPane(raw: unknown): Pane | null {
  try {
    if (!isObj(raw) || raw.v !== 1) return null
    const cmd = isObj(raw.cmd) ? raw.cmd : {}
    return {
      v: 1,
      ts: isNum(raw.ts) ? raw.ts : 0,
      root: strOr(raw.root, ''),
      sid: strOr(raw.sid, ''),
      places: cleanPlaces(raw.places),
      resume: cleanResume(raw.resume),
      spawns: cleanSpawns(raw.spawns),
      overrides: cleanOverrides(raw.overrides),
      cmd: { overrides: scriptArgv(cmd.overrides, ['overrides.py']) },
    }
  } catch {
    return null
  }
}

// The overrides the editor's script printed after a save: the pane's table follows at once, then the state file is read again (the script refreshed it).
export async function applyOverrides($: EngineInterface, raw: unknown) {
  const ov = cleanOverrides(raw)
  if (ov) await update($, pane, cur => (cur ? { ...cur, overrides: ov } : cur))
  await refresh($) // the script also rewrote the state file: a changed place (Guide place = band) shows at once
}

// Does any of the three things show in the pane?
export const anyPane = (p: Pane | null): p is Pane => p !== null && (p.places.guide === 'pane' || p.places.resume === 'pane' || p.places.spawns === 'pane')

// Takes the "running" flag; false when an Undo already holds it (a second press does nothing).
async function claim($: EngineInterface): Promise<boolean> {
  let wasRunning = false
  await update($, running, cur => {
    wasRunning = cur === true
    return true
  })
  return !wasRunning
}

// Reads the session's state file: the guide and the pane. Toasts a new red item.
export async function refresh($: EngineInterface) {
  try {
    const home = (await $.env.get('HOME')) ?? ''
    const dir = (await $.env.get('ABOFLES_STATE_DIR')) ?? `${home}/.abofles/state`
    const id = await $.session.id()
    const text = await $.fs.read(`${dir}/${id}.json`)
    const st = JSON.parse(text) as { guide?: unknown; pane?: unknown }
    const nextPane = cleanPane(isObj(st) ? st.pane : null)
    await update($, pane, () => nextPane)
    const next = cleanGuide(isObj(st) ? st.guide : null)
    if (!next) {
      await update($, guide, () => null)
      return
    }
    await update($, guide, () => next)
    // Toast when a red item appears that was not toasted before (an old state file without items: the line itself).
    const red = next.items.filter(i => i.p === '🔴').map(idOf)
    if (red.length === 0 && Array.from(keyOf(next.line))[0] === '🔴') red.push(`line:${next.line}`)
    const seen = await read($, toasted)
    if (red.some(r => !seen.includes(r))) {
      // code points, not UTF-16 units: an emoji is two units
      $.ui.toast(Array.from(next.line).slice(0, 160).join(''))
    }
    if (red.length !== seen.length || red.some((r, n) => r !== seen[n])) await update($, toasted, () => red)
  } catch {
    // no state yet (abofles not installed, or no hook ran): draw nothing
    await update($, guide, () => null)
    await update($, pane, () => null)
  }
}

// ---- the pane's open state

// Keeps paneOpen in the atom (the band redraws on it) and in $.store (the next session honours it).
export async function setPaneOpen($: EngineInterface, open: boolean) {
  await update($, paneOpen, () => open)
  try {
    await $.store.set('paneOpen', open)
  } catch {
    // no store: the session's atom is enough
  }
}

// What the store kept from an earlier session (true, false, or null: never decided), loaded into the atom.
async function loadPaneOpen($: EngineInterface): Promise<boolean | null> {
  let stored: unknown
  try {
    stored = await $.store.get('paneOpen')
  } catch {
    stored = undefined
  }
  const open = typeof stored === 'boolean' ? stored : null
  await update($, paneOpen, () => open)
  return open
}

// Opens the pane as asked (a command or a press): it is placed at any width.
export async function openPane($: EngineInterface): Promise<{ isPlaced: boolean; reason?: string }> {
  let result: { isPlaced: boolean; reason?: string }
  try {
    result = await $.ui.open({ id: PANE_ID, title: PANE_TITLE })
  } catch (err) {
    result = { isPlaced: false, reason: err instanceof Error ? err.message : String(err) }
  }
  await setPaneOpen($, true)
  return result
}

// Closes the pane for good (the person's next session finds it closed too).
export async function closePane($: EngineInterface) {
  try {
    await $.ui.close({ id: PANE_ID })
  } catch {
    // already gone
  }
  await setPaneOpen($, false)
}

// Is the pane open and drawn now?
export async function paneIsPlaced($: EngineInterface): Promise<boolean> {
  try {
    return (await $.ui.panes()).some(p => p.id === PANE_ID && p.isPlaced)
  } catch {
    return false
  }
}

// The unasked open: once per session, when the state has a pane payload with a place on the pane and the person
// did not close it. Not placed (a narrow terminal): the band shows the opener.
export async function autoOpen($: EngineInterface) {
  const p = await read($, pane)
  if (!anyPane(p) || (await read($, paneAuto)) === true) return
  await update($, paneAuto, () => true)
  if ((await loadPaneOpen($)) === false) return
  try {
    await $.ui.open({ id: PANE_ID, title: PANE_TITLE })
  } catch {
    // the band's opener stays
  }
}

// ---- the guide: what both places draw and do

// The memo is due when the context is within 50K tokens of its next mark, or past the last mark (mark null).
export function needsMemo(ctx: Guide['ctx']): boolean {
  if (!ctx) return false
  return ctx.mark == null || ctx.mark * 1000 - ctx.tokens <= 50000
}

// The dim second line: `ctx 412K / 500K · task 3 spawns · $0.41 · budget 2 left · suggest Opus 5.5 · Medium`.
export function meterOf(g: Guide): string {
  const parts: string[] = []
  if (g.ctx) parts.push(g.ctx.mark == null ? `ctx ${Math.round(g.ctx.tokens / 1000)}K` : `ctx ${Math.round(g.ctx.tokens / 1000)}K / ${g.ctx.mark}K`)
  if (g.task) {
    parts.push(`task ${g.task.spawns} spawns`, `$${g.task.usd.toFixed(2)}`)
    if (g.task.left != null) parts.push(`budget ${g.task.left} left`)
  }
  const main = g.main?.replace(/^\s*main:\s*/i, '').trim()
  if (main) parts.push(main)
  return parts.join(' · ')
}

// The ladder's priorities in order (🔴🟡, ✅, …): the fallback identity of a state file from before item ids.
export function keyOf(line: string): string {
  return (line.match(/[🔴🟠🟡⏳🧠💰✅]/gu) ?? []).join('') || line
}

// What Hide compares: the ids of the shown items, plus the memo mark when the memo is due. A hidden band comes back
// when an item appears or goes, or when a newly crossed mark makes the memo due again; not when only wording changes.
export function hideKeyOf(g: Guide): string {
  const items = Array.isArray(g.items) ? g.items : []
  const ids = items.length > 0 ? items.map(idOf).join('|') : keyOf(g.line)
  return needsMemo(g.ctx ?? null) ? `${ids}|memo:${g.ctx?.mark ?? 'past'}` : ids
}

// The prompt the Use and Copy buttons hand over: the guide line as an instruction the assistant acts on.
export function promptFor(line: string): string {
  const body = line.replace(/^\s*🧭\s*/, '').trim()
  return `abofles guide — do this now, in order: ${body}`
}

// What the guide shows, worked out once: the items, the top one, whether nothing is open, and the texts the buttons hand over.
export type GuideView = { items: GuideItem[]; top: GuideItem | undefined; done: boolean; memo: boolean; prompt: string; recheck: string | null; meter: string }

export function viewOf(g: Guide): GuideView {
  // A value an earlier build kept in $.state survives a reload: every newer field is optional here too.
  const items = Array.isArray(g.items) ? g.items : []
  const top = items[0]
  // Nothing open: every item is ✅ (an old state file without items: the line's only priority is ✅).
  const done = items.length > 0 ? items.every(i => i.p === '✅') : keyOf(g.line) === '✅'
  const recheck = !done && typeof top?.recheck === 'string' && top.recheck.trim() ? top.recheck : null
  return { items, top, done, memo: needsMemo(g.ctx ?? null), prompt: top?.fill || promptFor(g.line), recheck, meter: meterOf(g) }
}

// Show: the hidden guide comes back at once (the pane's "Show" button).
export async function showGuide($: EngineInterface) {
  await update($, hiddenKey, () => null)
}

// Hide: the guide stays down until the shown items (or the memo mark) change.
export async function hideGuide($: EngineInterface, g: Guide) {
  await update($, hiddenKey, () => hideKeyOf(g))
}

// Put text into the prompt box; keep a draft the person already typed. Hides the guide once it is in.
export async function fillPrompt($: EngineInterface, g: Guide, text: string) {
  const draft = (await $.prompt.read()).text.trim()
  const r = await $.prompt.fill({ text: draft ? `\n${text}` : text, mode: draft ? 'append' : 'replace' })
  if (r.isFilled) await hideGuide($, g)
  else $.ui.toast('Prompt box is not open — use Copy')
}

export async function copyPrompt($: EngineInterface, text: string, surface: Parameters<EngineInterface['ui']['copy']>[0]['surface']) {
  const r = await $.ui.copy({ text, surface })
  $.ui.toast(r.isCopied ? 'Guide copied — paste it in the prompt box' : `Copy failed (${r.reason})`)
}

// Undo: runs the argv the hook published as last_resolved (cwd = the project root), then reads the state again.
export async function undoLast($: EngineInterface, g: Guide, last: NonNullable<Guide['last_resolved']>) {
  if (!(await claim($))) return
  try {
    const r = await $.process.run(last.unresolve, g.root ? { cwd: g.root } : undefined)
    if (r.exitCode === 0 || r.exitCode === 3) await update($, dismissedTs, () => last.ts) // a failed Undo keeps the row, so it can be retried
    const first = (r.exitCode === 0 ? r.stdout : r.stderr || r.stdout).split('\n').find(l => l.trim()) ?? ''
    if (r.exitCode === 0) $.ui.toast(first || 'Undone')
    else if (r.exitCode === 3) $.ui.toast('Already open') // nothing changed
    else $.ui.toast(`Undo failed — ${first || `exit ${r.exitCode}`}`)
    await refresh($)
  } catch (err) {
    $.ui.toast(`Undo failed — ${err instanceof Error ? err.message : String(err)}`)
  } finally {
    await update($, running, () => false)
  }
}

// The row "✓ resolved: …" with Undo (gone while an Undo runs) and Hide; the band and the pane's guide card both draw it.
export function undoRow($: EngineInterface, ui: Ui, g: Guide, last: NonNullable<Guide['last_resolved']>, busy: boolean, inPane = false) {
  const { Box, Button, Text } = ui
  const look = inPane ? ({ variant: 'secondary' } as const) : {}
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={1}>
      <Text>{`✓ resolved: ${inPane ? plain(last.text) : Array.from(last.text).slice(0, 90).join('')}`}</Text>
      {!busy ? <Button key="undo" label="Undo" {...look} onPress={() => undoLast($, g, last)} /> : null}
      <Button key="undo-hide" label="Hide" {...look} onPress={() => update($, dismissedTs, () => last.ts)} />
    </Box>
  )
}

// The guide's buttons: Use, Re-check, Memo, Copy, Hide. In the pane Use is the primary button and the rest secondary.
export function guideButtons($: EngineInterface, ui: Ui, g: Guide, v: GuideView, inPane = false, extra: unknown = null) {
  const { Box, Button } = ui
  const main = inPane ? ({ variant: 'primary' } as const) : {}
  const look = inPane ? ({ variant: 'secondary' } as const) : {}
  const memoLook = v.done && v.memo ? ({ variant: 'primary' } as const) : look // nothing else open: the memo is the next step
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={1} marginTop={inPane ? 0 : 1}>
      {v.done ? null : <Button key="use" label="Use" {...main} onPress={() => fillPrompt($, g, v.prompt)} />}
      {v.recheck ? <Button key="recheck" label="Re-check" {...look} onPress={() => fillPrompt($, g, v.recheck as string)} /> : null}
      {v.memo ? <Button key="memo" label="Memo" {...memoLook} onPress={() => fillPrompt($, g, '/abofles:memo')} /> : null}
      {v.done ? null : <Button key="copy" label="Copy" {...look} onPress={press => copyPrompt($, v.prompt, press.surface)} />}
      <Button key="hide" label="Hide" {...look} onPress={() => hideGuide($, g)} />
      {extra as never}
    </Box>
  )
}
