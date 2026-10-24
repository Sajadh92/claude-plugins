import type { EngineInterface } from 'claude-code'

import type { Guide, Pane, PaneLive, PaneRow, PaneSpawns } from '../types'
import { overridesCard, overridesPage } from './editor'
import { card, getDismissedTs, getFolds, getGuide, getHiddenKey, getPane, getPaneView, getRunning, guideButtons, hideKeyOf, isOpen, kv, limited, moreButton, plain, setFold, showGuide, undoRow, viewOf } from './shared'
import type { Folds, RenderEvent, Ui } from './shared'

// The "Abo Fles" pane: one card per thing the abofles hooks placed there (`pane.places`): Guide, Resume, Spawns, and always a
// short Overrides card whose Edit button turns the pane into the overrides editor (editor.tsx). Native elements only; every text
// wraps (nothing is cut), long lists show their first rows and a "Show all", and every card folds. The buttons are the band's.

export const fmtTokens = (n: number): string => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}K` : String(n))
export const fmtUsd = (x: number): string => (x > 0 && x < 0.005 ? '<$0.01' : `$${x.toFixed(2)}`)

// `14:05`: when a live spawn started (its `ts`, epoch seconds, in local time), or `running` when the hook gave no start. A start time does not go stale between redraws.
export function fmtStart(ts: number | null): string {
  if (ts === null) return 'running'
  const d = new Date(ts > 1e11 ? ts : ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const modelOf = (model: string, effort: string): string => (effort ? `${model || '?'}·${effort}` : model || '?')

// The theme color of a priority emoji: red for 🔴, amber for 🟠🟡, green for ✅; none for the rest.
const toneOf = (p: string | undefined): string | undefined => (p === '🔴' ? 'error' : p === '🟠' || p === '🟡' ? 'warning' : p === '✅' ? 'success' : undefined)

// A small dim heading inside a card ("Needs you").
function heading(ui: Ui, text: string) {
  const { Text } = ui
  return (
    <Text size="caption" dimColor>
      {text}
    </Text>
  )
}

// One section of a card: its heading, then its rows.
function section(ui: Ui, title: string, rows: (JSX.Element | null)[]) {
  const { Box } = ui
  return (
    <Box flexDirection="column">
      {heading(ui, title)}
      {rows}
    </Box>
  )
}

// A row with text that wraps on the left and a short aside (a time, a verdict) held at the right.
function split(ui: Ui, left: JSX.Element, right: JSX.Element | null) {
  const { Box } = ui
  return (
    <Box flexDirection="row" justifyContent="space-between" columnGap={1}>
      <Box flexShrink={1}>{left}</Box>
      {right}
    </Box>
  )
}

// ---- Guide

// The guide's numbers as rows: context, the task's spawns and cost, its budget, the main-session suggestion.
function meterRows(ui: Ui, g: Guide): JSX.Element[] {
  const rows: JSX.Element[] = []
  if (g.ctx) rows.push(kv(ui, 'Context', g.ctx.mark == null ? `${Math.round(g.ctx.tokens / 1000)}K` : `${Math.round(g.ctx.tokens / 1000)}K / ${g.ctx.mark}K`))
  if (g.task) {
    rows.push(kv(ui, 'Task', `${g.task.spawns} spawn${g.task.spawns === 1 ? '' : 's'} · $${g.task.usd.toFixed(2)}`))
    if (g.task.left != null) rows.push(kv(ui, 'Budget', `${g.task.left} left`))
  }
  const main = g.main?.replace(/^\s*main:\s*/i, '').replace(/^suggest\s+/i, '').trim()
  if (main) rows.push(kv(ui, 'Suggest', main))
  return rows
}

function guideCard($: EngineInterface, ui: Ui, g: Guide, hidden: boolean, last: Guide['last_resolved'], busy: boolean, folds: Folds) {
  const { Box, Button, Text } = ui
  const v = viewOf(g)
  const open = v.items.filter(i => i.p !== '✅').length
  const summary = v.done ? 'nothing open' : v.items.length > 0 ? `${open} open` : null
  const rows: (JSX.Element | null)[] = []
  if (last) rows.push(undoRow($, ui, g, last, busy, true))
  if (hidden) {
    rows.push(
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        <Text dimColor>Hidden until the list changes.</Text>
        <Button key="show" label="Show" variant="secondary" onPress={() => showGuide($)} />
      </Box>,
    )
  } else {
    if (v.items.length > 0) {
      // the top item in full, the others dim under it; each wraps
      const [top, ...rest] = v.items
      rows.push(
        <Box flexDirection="column">
          <Text>{`${top.p} ${plain(top.text)}`}</Text>
          {limited($, ui, folds, 'guide', rest.map(it => <Text dimColor>{`${it.p} ${plain(it.text)}`}</Text>), 2)}
        </Box>,
      )
    } else {
      rows.push(<Text>{plain(g.line)}</Text>)
    }
    const meter = meterRows(ui, g)
    if (meter.length > 0) rows.push(<Box flexDirection="column">{meter}</Box>)
    if (!v.done || v.memo) rows.push(guideButtons($, ui, g, v, true))
  }
  return card($, ui, { id: 'guide', title: 'Guide', summary: hidden ? 'hidden' : summary, tone: hidden ? undefined : toneOf(v.top?.p), folds }, <Box flexDirection="column" rowGap={1}>{rows}</Box>)
}

// ---- Resume

// The head line's parts the card shows as rows: `📍 Resume · memo 2026-10-21 17:40 · away 2 days · session 3f7416dd · now written …`.
export function headParts(head: string): { memo: string | null; away: string | null; session: string | null } {
  const parts = plain(head).split(' · ')
  const find = (word: string) => parts.find(x => x.startsWith(`${word} `))?.slice(word.length + 1).trim() ?? null
  return { memo: find('memo'), away: find('away'), session: find('session') }
}

// A receipt line of the journal as one short row: `10-22 07:19 · 1 Spawn · 319K Tokens · $0.28 · Saved 46% ($0.24) vs Opus 5.5 · done: …`
// gives the time and `1 Spawn · $0.28 · Saved 46%`; `done`, `check` and `open` are its details. A line of another shape is kept whole.
export function receiptOf(line: string): { time: string | null; head: string; details: string[] } {
  const parts = plain(line).split(' · ')
  const time = /^\d\d-\d\d \d\d:\d\d$/.test(parts[0] ?? '') ? (parts.shift() as string) : null
  const at = parts.findIndex(x => /^[a-z]+:\s/i.test(x))
  const stats = (at < 0 ? parts : parts.slice(0, at)).filter(x => !/Tokens$/.test(x)).map(x => x.replace(/\s*\(\$[\d.]+\)\s*vs\s+.*$/, '').replace(/\s+vs\s+.*$/, ''))
  const details = at < 0 ? [] : parts.slice(at)
  return stats.length > 0 ? { time, head: stats.join(' · '), details } : { time, head: details.shift() ?? '', details }
}

// A list row: the mark (`•`, `3.`) in a Text of its own beside the item, so a right-to-left item wraps and aligns by itself.
function marked(ui: Ui, mark: string, text: string) {
  const { Box, Text } = ui
  return (
    <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
      <Text dimColor>{mark}</Text>
      <Box flexShrink={1}>
        <Text>{plain(text)}</Text>
      </Box>
    </Box>
  )
}

// The rows of a list: the item alone, or with a bullet when there are several.
function listRows(ui: Ui, texts: string[]): JSX.Element[] {
  const { Text } = ui
  return texts.map(t => (texts.length > 1 ? marked(ui, '•', t) : <Text>{plain(t)}</Text>))
}

function receiptRows($: EngineInterface, ui: Ui, lines: string[], folds: Folds): (JSX.Element | null)[] {
  const { Box, Button, Text } = ui
  const shown = isOpen(folds, 'more:receipts', false)
  const rs = lines.map(receiptOf)
  const rows: (JSX.Element | null)[] = rs.map(r => (
    <Box flexDirection="column">
      {split(ui, <Text>{r.head}</Text>, r.time ? <Text size="caption" tabular dimColor>{r.time}</Text> : null)}
      {shown ? r.details.map(d => <Text size="caption" dimColor>{d}</Text>) : null}
    </Box>
  ))
  if (rs.some(r => r.details.length > 0)) rows.push(<Button key="more:receipts" label={shown ? 'Hide details' : 'Show details'} plain dimColor onPress={() => setFold($, 'more:receipts', !shown)} />)
  return rows
}

function resumeCard($: EngineInterface, ui: Ui, r: Pane['resume'], folds: Folds) {
  const { Box, Text } = ui
  if (r === null) return card($, ui, { id: 'resume', title: 'Resume', folds }, <Text dimColor>No memo yet — run /abofles:memo</Text>)
  const head = headParts(r.head) // not `h`: that name is the JSX factory
  const parts: JSX.Element[] = []
  const facts = [head.session ? kv(ui, 'Session', head.session) : null, head.memo ? kv(ui, 'Memo', head.memo) : null, head.away ? kv(ui, 'Away', head.away) : null].filter((x): x is JSX.Element => x !== null)
  if (facts.length > 0) parts.push(<Box flexDirection="column">{facts}</Box>)
  if (r.now.length > 0) parts.push(section(ui, 'Now', listRows(ui, r.now)))
  if (r.next.length > 0) parts.push(section(ui, 'Next', listRows(ui, r.next)))
  if (r.needs.length > 0) parts.push(section(ui, 'Needs you', limited($, ui, folds, 'needs', r.needs.map((n, i) => marked(ui, `${n.n ?? i + 1}.`, n.text)))))
  if (r.left.length > 0) parts.push(section(ui, 'Left', limited($, ui, folds, 'left', listRows(ui, r.left))))
  if (r.last.length > 0) parts.push(section(ui, 'Last receipts', receiptRows($, ui, r.last, folds)))
  const summary = r.needs_open > 0 ? `${r.needs_open} need you` : head.memo ? `memo ${head.memo.replace(/^\d{4}-/, '')}` : null
  return card($, ui, { id: 'resume', title: 'Resume', summary, tone: r.needs_open > 0 ? 'warning' : undefined, folds }, <Box flexDirection="column" rowGap={1}>{parts}</Box>)
}

// ---- Spawns

// The second line of a history row: `done · medium · sonnet·medium · 80K · $0.40 · saved 50%`.
export function historyDetail(r: PaneRow): string {
  const saved = r.tokens && r.base_usd ? `saved ${Math.round(100 * (1 - (r.usd ?? 0) / r.base_usd))}%` : 'saved -'
  return [r.status ?? '?', r.confidence ?? '?', modelOf(r.model, r.effort), r.tokens ? fmtTokens(r.tokens) : '-', r.usd !== null ? fmtUsd(r.usd) : '-', saved].join(' · ')
}

// The card's summary: `2 live · 3 spawns · $0.41`.
export function spawnsSummary(s: PaneSpawns): string {
  const t = s.totals
  return [s.live.length > 0 ? `${s.live.length} live` : '', `${t.spawns} spawn${t.spawns === 1 ? '' : 's'}`, fmtUsd(t.usd)].filter(Boolean).join(' · ')
}

// The newest history rows the card shows before its "Show all".
const HISTORY_ROWS = 5

function liveRow(ui: Ui, l: PaneLive) {
  const { Box, Text } = ui
  return (
    <Box flexDirection="column">
      {split(ui, <Text>{`● ${[l.side || '?', plain(l.description)].filter(Boolean).join(' · ')}`}</Text>, <Text size="caption" tabular dimColor>{fmtStart(l.ts)}</Text>)}
      <Text size="caption" dimColor>{modelOf(l.model, l.effort)}</Text>
    </Box>
  )
}

function historyRow(ui: Ui, r: PaneRow) {
  const { Box, Text } = ui
  const verdict = r.verdict ? <Text weight="semibold" color={/FAIL/i.test(r.verdict) ? 'error' : 'success'}>{r.verdict}</Text> : null
  return (
    <Box flexDirection="column">
      {split(ui, <Text>{[r.side || '?', plain(r.description)].filter(Boolean).join(' · ')}</Text>, verdict)}
      <Text size="caption" dimColor>{historyDetail(r)}</Text>
    </Box>
  )
}

function spawnsCard($: EngineInterface, ui: Ui, s: PaneSpawns, folds: Folds) {
  const { Box, Text } = ui
  if (s.live.length === 0 && s.rows.length === 0) return card($, ui, { id: 'spawns', title: 'Spawns', folds }, <Text dimColor>No spawns yet</Text>)
  const t = s.totals
  const parts: JSX.Element[] = [
    <Box flexDirection="column">
      {kv(ui, 'Saved', `${t.saved_pct}%`, t.saved_pct > 0 ? 'success' : undefined)}
      {t.tokens > 0 ? kv(ui, 'Tokens', fmtTokens(t.tokens)) : null}
      {t.open_fail > 0 ? kv(ui, 'Open FAIL', String(t.open_fail), 'error') : null}
    </Box>,
  ]
  if (s.live.length > 0) parts.push(section(ui, 'Live', [<Box flexDirection="column" rowGap={1}>{s.live.map(l => liveRow(ui, l))}</Box>]))
  if (s.rows.length > 0) {
    // newest first; the rest behind Show all
    const newest = [...s.rows].reverse()
    const shown = isOpen(folds, 'more:history', false) ? newest : newest.slice(0, HISTORY_ROWS)
    parts.push(section(ui, 'History', [<Box flexDirection="column" rowGap={1}>{shown.map(r => historyRow(ui, r))}</Box>, moreButton($, ui, folds, 'history', s.rows.length, HISTORY_ROWS)]))
  }
  return card($, ui, { id: 'spawns', title: 'Spawns', summary: spawnsSummary(s), folds }, <Box flexDirection="column" rowGap={1}>{parts}</Box>)
}

// ---- the pane

export async function renderPane($: EngineInterface, e: RenderEvent) {
  const ui = $.ui.resolve(e)
  const { Box } = ui
  const p = await getPane($)
  const folds = await getFolds($)
  if ((await getPaneView($)) === 'overrides') return overridesPage($, ui, p, folds)
  const g = await getGuide($)
  const cards: JSX.Element[] = []
  if (p?.places.guide === 'pane' && g !== null) {
    const hidden = hideKeyOf(g) === (await getHiddenKey($))
    const last = g.last_resolved ?? null
    const shownLast = last !== null && last.ts !== (await getDismissedTs($)) ? last : null
    cards.push(guideCard($, ui, g, hidden, shownLast, (await getRunning($)) === true, folds))
  }
  if (p?.places.resume === 'pane') cards.push(resumeCard($, ui, p.resume, folds))
  if (p?.places.spawns === 'pane') cards.push(spawnsCard($, ui, p.spawns, folds))
  cards.push(await overridesCard($, ui, p, folds))
  return (
    <Box flexDirection="column" gap={1}>
      {cards}
    </Box>
  )
}
