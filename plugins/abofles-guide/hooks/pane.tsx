import type { EngineInterface } from 'claude-code'

import type { Guide, GuideItem, Pane, PaneLive, PaneRow, PaneSpawns } from '../types'
import { overridesCard, overridesPage } from './editor'
import {
  bar,
  card,
  copyPrompt,
  fillPrompt,
  getDismissedTs,
  getFolds,
  getGuide,
  getHiddenKey,
  getPane,
  getPaneView,
  getRunning,
  heading,
  hideGuide,
  hideKeyOf,
  lookOf,
  isOpen,
  kv,
  moreButton,
  plain,
  rule,
  setFold,
  showGuide,
  undoRow,
  viewOf,
} from './shared'
import type { Folds, GuideView, Look, RenderEvent, Ui } from './shared'

// The "Abo Fles" pane, drawn like the desktop app's own side panels (Context, Changes): one card per thing the abofles hooks
// placed there (`pane.places`) — Guide, Resume, Spawns — and always Overrides, whose Edit button turns the pane into the
// overrides editor (editor.tsx). Each card folds from its header; labels sit left and values dim at the right; colour is a
// dot or a word (PASS, FAIL), never an emoji; every text wraps; long lists show their first rows and "Show all".

export const fmtTokens = (n: number): string => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}K` : String(n))
export const fmtUsd = (x: number): string => (x > 0 && x < 0.005 ? '<$0.01' : `$${x.toFixed(2)}`)

const pad2 = (n: number): string => String(n).padStart(2, '0')

// `14:05`: when a live spawn started (its `ts`, epoch seconds, in local time), or `running` when the hook gave no start.
export function fmtStart(ts: number | null): string {
  if (ts === null) return 'running'
  const d = new Date(ts > 1e11 ? ts : ts * 1000)
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// `10-22 07:19` or `2026-10-24 10:32` -> `Oct 22 07:19` / `Oct 24, 10:32`; anything else as it is.
export function fmtWhen(text: string, comma = false): string {
  const m = /^(?:\d{4}-)?(\d\d)-(\d\d) (\d\d:\d\d)$/.exec(text.trim())
  if (!m) return text
  const month = MONTHS[Number(m[1]) - 1]
  return month ? `${month} ${Number(m[2])}${comma ? ',' : ''} ${m[3]}` : text
}

const modelOf = (model: string, effort: string): string => (effort ? `${model || '?'}·${effort}` : model || '?')

// The colours the app's own meters use; theme keys for meaning (error, warning, success).
const BLUE = '#4a8cf0'
const MODEL_COLOR: Record<string, string> = { haiku: BLUE, sonnet: '#e0763a', opus: '#4fae8e', fable: '#a78bfa' }

// The tone of a priority emoji: red for 🔴, amber for 🟠🟡💰, green for ✅; none (dim) for the rest.
const toneOf = (p: string | undefined): string | undefined => (p === '🔴' ? 'error' : p === '🟠' || p === '🟡' || p === '💰' ? 'warning' : p === '✅' ? 'success' : undefined)

// A row led by a dot: the dot in the item's tone (dim without one), the text wrapping beside it.
function dotRow(ui: Ui, tone: string | undefined, text: string, dim = false) {
  const { Box, Text } = ui
  return (
    <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
      {tone ? <Text color={tone}>●</Text> : <Text dimColor>●</Text>}
      <Box flexShrink={1}>{dim ? <Text dimColor>{text}</Text> : <Text>{text}</Text>}</Box>
    </Box>
  )
}

// A list row: the mark (`•`, `3`) in a column of its own, so a right-to-left item wraps and aligns by itself.
function marked(ui: Ui, mark: string, text: string, tone?: string) {
  const { Box, Text } = ui
  return (
    <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
      <Box width={2} justifyContent={mark === '•' ? 'flex-start' : 'flex-end'} flexShrink={0}>
        {tone ? <Text color={tone}>{mark}</Text> : <Text dimColor>{mark}</Text>}
      </Box>
      <Box flexShrink={1}>
        <Text>{plain(text)}</Text>
      </Box>
    </Box>
  )
}

// A row with text that wraps on the left and a short aside (a time, a cost) held at the right.
function split(ui: Ui, left: JSX.Element, right: JSX.Element | null) {
  const { Box } = ui
  return (
    <Box flexDirection="row" justifyContent="space-between" columnGap={1}>
      <Box flexShrink={1}>{left}</Box>
      {right}
    </Box>
  )
}

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

// ---- Guide

// The guide's numbers: Context with its meter (amber once the memo is due), this task's spawns and cost, the budget, the suggestion.
function guideNumbers(ui: Ui, g: Guide, v: GuideView, look: Look): JSX.Element[] {
  const { Text } = ui
  const rows: JSX.Element[] = []
  if (g.ctx) {
    const k = Math.round(g.ctx.tokens / 1000)
    rows.push(kv(ui, 'Context', g.ctx.mark == null ? `${k}K` : `${k}K / ${g.ctx.mark}K`))
    if (g.ctx.mark) rows.push(bar(ui, look, [{ pct: (100 * k) / g.ctx.mark, color: v.memo ? 'warning' : BLUE }], `Context ${Math.round((100 * k) / g.ctx.mark)}% of the next mark`))
    if (v.memo && v.done) rows.push(<Text size="caption" dimColor>Near the next mark: save the memo, then /compact.</Text>)
  }
  if (g.task) {
    rows.push(kv(ui, 'This task', `${plural(g.task.spawns, 'spawn')} · $${g.task.usd.toFixed(2)}`))
    if (g.task.left != null) rows.push(kv(ui, 'Agent budget', g.task.budget != null ? `${g.task.left} of ${g.task.budget} left` : `${g.task.left} left`))
  }
  const main = g.main?.replace(/^\s*main:\s*/i, '').replace(/^suggest\s+/i, '').trim()
  if (main) rows.push(kv(ui, 'Suggest', main))
  return rows
}

// The guide's buttons in the pane: Use (primary), Re-check, Copy — or Save memo alone when nothing is open — and Hide as a link at the right.
function guideActions($: EngineInterface, ui: Ui, g: Guide, v: GuideView) {
  const { Box, Button } = ui
  return (
    <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1}>
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        {v.done ? null : <Button key="use" label="Use" variant="primary" onPress={() => fillPrompt($, g, v.prompt)} />}
        {v.recheck ? <Button key="recheck" label="Re-check" variant="secondary" onPress={() => fillPrompt($, g, v.recheck as string)} /> : null}
        {v.done ? null : <Button key="copy" label="Copy" variant="secondary" onPress={press => copyPrompt($, v.prompt, press.surface)} />}
        {v.memo ? <Button key="memo" label="Save memo" variant={v.done ? 'primary' : 'secondary'} onPress={() => fillPrompt($, g, '/abofles:memo')} /> : null}
      </Box>
      <Button key="hide" label="Hide" plain dimColor onPress={() => hideGuide($, g)} />
    </Box>
  )
}

// Nothing open: the ✅ item says what is left in the memo — "Next from the memo" and that text.
function clearRows(ui: Ui, g: Guide, top: GuideItem | undefined): JSX.Element {
  const { Box, Text } = ui
  const text = plain(top?.text ?? g.line.replace(/^\s*🧭\s*/, ''))
  const m = /memo:\s*(.+)$/i.exec(text)
  return (
    <Box flexDirection="column">
      <Text>{m ? 'Next from the memo' : 'All clear'}</Text>
      <Text dimColor>{m ? m[1] : text}</Text>
    </Box>
  )
}

function guideCard($: EngineInterface, ui: Ui, g: Guide, hidden: boolean, last: Guide['last_resolved'], busy: boolean, folds: Folds, look: Look) {
  const { Box, Button, Text } = ui
  const v = viewOf(g)
  const open = v.items.filter(i => i.p !== '✅')
  const rows: (JSX.Element | null)[] = []
  if (last) rows.push(undoRow($, ui, g, last, busy, true))
  if (hidden) {
    rows.push(
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1}>
        <Text dimColor>Hidden until the list changes.</Text>
        <Button key="show" label="Show" variant="secondary" onPress={() => showGuide($)} />
      </Box>,
    )
  } else {
    if (v.done || v.items.length === 0) rows.push(clearRows(ui, g, v.top))
    else {
      const [top, ...rest] = v.items
      const all = isOpen(folds, 'more:guide', false)
      rows.push(
        <Box flexDirection="column" rowGap={1}>
          {dotRow(ui, toneOf(top.p), plain(top.text))}
          {rest.length > 0 ? (
            <Box flexDirection="column" paddingLeft={2}>
              {(all ? rest : rest.slice(0, 2)).map(it => dotRow(ui, toneOf(it.p), plain(it.text), true))}
              {moreButton($, ui, folds, 'guide', v.items.length, rest.length > 2 ? 3 : v.items.length)}
            </Box>
          ) : null}
        </Box>,
      )
    }
    const numbers = guideNumbers(ui, g, v, look)
    if (numbers.length > 0) rows.push(<Box flexDirection="column">{numbers}</Box>)
    if (!v.done || v.memo) rows.push(guideActions($, ui, g, v))
  }
  const summary = hidden ? 'hidden' : v.done ? 'Nothing open' : open.length > 0 ? `${open.length} open` : null
  const tone = hidden ? undefined : v.done ? 'success' : toneOf(v.top?.p)
  return card($, ui, { id: 'guide', title: 'Guide', summary, tone, folds }, <Box flexDirection="column" rowGap={1}>{rows}</Box>)
}

// ---- Resume

// The head line's parts the card shows as rows: `📍 Resume · memo 2026-10-21 17:40 · away 2 days · session 3f7416dd · now written …`.
export function headParts(head: string): { memo: string | null; away: string | null; session: string | null } {
  const parts = plain(head).split(' · ')
  const find = (word: string) => parts.find(x => x.startsWith(`${word} `))?.slice(word.length + 1).trim() ?? null
  return { memo: find('memo'), away: find('away'), session: find('session') }
}

// A receipt line of the journal as a table row: `10-22 07:19 · 1 Spawn · 319K Tokens · $0.28 · Saved 46% ($0.24) vs Opus 5.5 · done: …`
// gives the time, `1 spawn`, `$0.28`, `46%`; `done`, `check` and `open` are its details. A line without the numbers keeps its text.
export function receiptOf(line: string): { time: string | null; spawns: string | null; usd: string | null; saved: string | null; text: string; details: string[] } {
  const parts = plain(line).split(' · ')
  const time = /^\d\d-\d\d \d\d:\d\d$/.test(parts[0] ?? '') ? (parts.shift() as string) : null
  const at = parts.findIndex(x => /^[a-z]+:\s/i.test(x))
  const stats = at < 0 ? parts : parts.slice(0, at)
  const details = at < 0 ? [] : parts.slice(at)
  const n = stats.map(x => /^(\d+) Spawns?$/i.exec(x)).find(Boolean)
  const usd = stats.map(x => /^(\$[\d.,]+)$/.exec(x)).find(Boolean)
  const saved = stats.map(x => /^Saved (\d+%)/i.exec(x)).find(Boolean)
  if (!n) return { time, spawns: null, usd: null, saved: null, text: stats.join(' · ') || details.shift() || '', details }
  return { time, spawns: plural(Number(n[1]), 'spawn'), usd: usd ? usd[1] : null, saved: saved ? saved[1] : null, text: '', details }
}

// Last receipts as the app's tables: time | spawns | $ | saved %, and a caret that opens the row's details.
function receiptRows($: EngineInterface, ui: Ui, lines: string[], folds: Folds): JSX.Element[] {
  const { Box, Button, Text } = ui
  return lines.map((line, i) => {
    const r = receiptOf(line)
    const id = `rcpt:${r.time ?? i}`
    const open = isOpen(folds, id, false)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={1}>
          <Box width={13} flexShrink={0}>
            <Text dimColor tabular>{r.time ? fmtWhen(r.time) : ''}</Text>
          </Box>
          {r.spawns ? (
            <Box flexDirection="row" flexGrow={1} columnGap={1}>
              <Box flexGrow={1}>
                <Text>{r.spawns}</Text>
              </Box>
              <Box width={7} justifyContent="flex-end">
                <Text dimColor tabular>{r.usd ?? '-'}</Text>
              </Box>
              <Box width={4} justifyContent="flex-end">
                <Text tabular>{r.saved ?? '-'}</Text>
              </Box>
            </Box>
          ) : (
            <Box flexGrow={1} flexShrink={1}>
              <Text>{r.text}</Text>
            </Box>
          )}
          {r.details.length > 0 ? (
            <Button key={id} plain dimColor onPress={() => setFold($, id, !open)}>
              {open ? '▾' : '›'}
            </Button>
          ) : (
            <Text> </Text>
          )}
        </Box>
        {open ? (
          <Box flexDirection="column" paddingLeft={14}>
            {r.details.map(d => <Text size="caption" dimColor>{d}</Text>)}
          </Box>
        ) : null}
      </Box>
    )
  })
}

// A sub-list with its own caret, as the app's "› MCP tools": a plain button over its rows.
function subList($: EngineInterface, ui: Ui, folds: Folds, id: string, title: string, rows: JSX.Element[]) {
  const { Box, Button, Text } = ui
  const open = isOpen(folds, id, true)
  return (
    <Box flexDirection="column" rowGap={open ? 1 : 0}>
      <Button key={`fold:${id}`} plain onPress={() => setFold($, id, !open)}>
        <Text>{title}</Text>
        <Text dimColor>{open ? ' ▾' : ' ›'}</Text>
      </Button>
      {open ? <Box flexDirection="column">{rows}</Box> : null}
    </Box>
  )
}

function resumeCard($: EngineInterface, ui: Ui, r: Pane['resume'], folds: Folds, look: Look) {
  const { Box, Text } = ui
  if (r === null) return card($, ui, { id: 'resume', title: 'Resume', folds }, <Text dimColor>No memo yet — run /abofles:memo</Text>)
  const head = headParts(r.head) // not `h`: that name is the JSX factory
  const parts: JSX.Element[] = []
  const text = (t: string) => <Text>{plain(t)}</Text>
  if (r.now.length > 0) parts.push(<Box flexDirection="column">{[heading(ui, 'Now'), ...r.now.map(text)]}</Box>)
  if (r.next.length > 0) parts.push(<Box flexDirection="column">{[heading(ui, 'Next'), ...r.next.map(text)]}</Box>)
  if (r.needs.length > 0) {
    const all = isOpen(folds, 'more:needs', false)
    const rows = r.needs.map((n, i) => marked(ui, String(n.n ?? i + 1), n.text, 'warning'))
    parts.push(
      <Box flexDirection="column">
        {heading(ui, 'Needs you', String(r.needs_open), 'warning')}
        {all ? rows : rows.slice(0, 3)}
        {moreButton($, ui, folds, 'needs', rows.length, 3)}
      </Box>,
    )
  }
  if (r.left.length > 0) {
    const all = isOpen(folds, 'more:left', false)
    const rows = r.left.map(t => marked(ui, '•', t))
    parts.push(
      <Box flexDirection="column">
        {heading(ui, 'Left')}
        {all ? rows : rows.slice(0, 3)}
        {moreButton($, ui, folds, 'left', rows.length, 3)}
      </Box>,
    )
  }
  if (r.last.length > 0) parts.push(rule(ui, look), subList($, ui, folds, 'receipts', 'Last receipts', receiptRows($, ui, r.last, folds)))
  const facts = [head.session ? kv(ui, 'Session', head.session) : null, head.memo ? kv(ui, 'Memo saved', fmtWhen(head.memo, true)) : null, head.away ? kv(ui, 'Away', head.away) : null].filter(
    (x): x is JSX.Element => x !== null,
  )
  if (facts.length > 0) parts.push(rule(ui, look), <Box flexDirection="column">{facts}</Box>)
  const summary = r.needs_open > 0 ? `${r.needs_open} need you` : head.memo ? `memo ${fmtWhen(head.memo)}` : null
  return card($, ui, { id: 'resume', title: 'Resume', summary, tone: r.needs_open > 0 ? 'warning' : undefined, folds }, <Box flexDirection="column" rowGap={1}>{parts}</Box>)
}

// ---- Spawns

// The verdict column of a history row: PASS, FAIL, or the status (DONE, PARTIAL, …) dim.
function chip(ui: Ui, r: PaneRow) {
  const { Text } = ui
  const v = (r.verdict ?? '').toUpperCase()
  if (/FAIL/.test(v)) return <Text size="caption" weight="semibold" color="error">FAIL</Text>
  if (/PASS/.test(v)) return <Text size="caption" weight="semibold" color="success">PASS</Text>
  return <Text size="caption" weight="semibold" dimColor>{(r.status ?? 'done').toUpperCase().slice(0, 7)}</Text>
}

// The dim line under a history row: `sonnet·high · 1.9M`, then `resolved` for a FAIL closed by hand, or a status that is not done.
export function historyDetail(r: PaneRow): string {
  const tail = r.resolved && /FAIL/i.test(r.verdict ?? '') ? 'resolved' : r.status && r.status !== 'done' && (r.verdict || r.status !== 'pending') ? r.status : ''
  return [modelOf(r.model, r.effort), r.tokens ? fmtTokens(r.tokens) : '', tail].filter(Boolean).join(' · ')
}

// The card's summary: `43 spawns`.
export function spawnsSummary(s: PaneSpawns): string {
  return plural(s.totals.spawns, 'spawn')
}

// The newest history rows the card shows before its "Show all".
const HISTORY_ROWS = 5

// A row of the history or the live list: the chip column, then the ask with its aside at the right, and the dim line under it.
function spawnRow(ui: Ui, lead: JSX.Element, text: string, aside: string, detail: string) {
  const { Box, Text } = ui
  return (
    <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
      <Box width={6} flexShrink={0}>
        {lead}
      </Box>
      <Box flexDirection="column" flexGrow={1} flexShrink={1}>
        {split(ui, <Text>{text}</Text>, aside ? <Text dimColor tabular>{aside}</Text> : null)}
        {detail ? <Text size="caption" dimColor>{detail}</Text> : null}
      </Box>
    </Box>
  )
}

const askOf = (side: string, description: string): string => [side || '?', plain(description)].filter(Boolean).join(' · ')

function spawnsCard($: EngineInterface, ui: Ui, s: PaneSpawns, folds: Folds, look: Look, ts: number) {
  const { Box, Text } = ui
  if (s.live.length === 0 && s.rows.length === 0) return card($, ui, { id: 'spawns', title: 'Spawns', folds }, <Text dimColor>No spawns yet</Text>)
  const t = s.totals
  const parts: JSX.Element[] = []
  // the saving first, as the app's "15% used": the % left, the spend against the baseline at the right, then the split by model
  const versus = t.base_usd > 0 ? `${fmtUsd(t.usd)} of ${fmtUsd(t.base_usd)}${t.base_label ? ` on ${t.base_label}` : ''}` : fmtUsd(t.usd)
  const models = t.by_model.filter(m => m.spawns > 0)
  parts.push(
    <Box flexDirection="column">
      {split(ui, <Text weight="semibold">{`${t.saved_pct}% saved`}</Text>, <Text dimColor tabular>{versus}</Text>)}
      {models.length > 0 ? bar(ui, look, models.map(m => ({ pct: m.pct, color: MODEL_COLOR[m.model] ?? '#8f8f8f' })), `Spend by model: ${models.map(m => `${m.label} ${m.pct}%`).join(', ')}`) : null}
      {models.map(m => (
        <Box flexDirection="row" columnGap={1}>
          <Text color={MODEL_COLOR[m.model] ?? '#8f8f8f'}>■</Text>
          <Box flexGrow={1} flexShrink={1}>
            <Text>{m.label}</Text>
          </Box>
          <Box width={4} justifyContent="flex-end">
            <Text dimColor tabular>{String(m.spawns)}</Text>
          </Box>
          <Box width={8} justifyContent="flex-end">
            <Text dimColor tabular>{fmtUsd(m.usd)}</Text>
          </Box>
          <Box width={5} justifyContent="flex-end">
            <Text tabular>{`${m.pct}%`}</Text>
          </Box>
        </Box>
      ))}
      {t.tokens > 0 ? kv(ui, 'Tokens', fmtTokens(t.tokens)) : null}
      {t.open_fail > 0 ? kv(ui, 'Open FAIL', String(t.open_fail), 'error') : null}
    </Box>,
  )
  if (s.live.length > 0 || s.rows.length > 0) parts.push(rule(ui, look))
  if (s.live.length > 0) {
    parts.push(
      <Box flexDirection="column" rowGap={1}>
        {heading(ui, 'Running', String(s.live.length))}
        {s.live.map((l: PaneLive) => spawnRow(ui, <Text size="caption" weight="semibold" color={BLUE}>● LIVE</Text>, askOf(l.side, l.description), fmtStart(l.ts), modelOf(l.model, l.effort)))}
      </Box>,
    )
  }
  if (s.rows.length > 0) {
    const newest = [...s.rows].reverse()
    const shown = isOpen(folds, 'more:history', false) ? newest : newest.slice(0, HISTORY_ROWS)
    parts.push(
      <Box flexDirection="column" rowGap={1}>
        {heading(ui, 'History', 'newest first')}
        {shown.map(r => spawnRow(ui, chip(ui, r), askOf(r.side, r.description), r.usd !== null ? fmtUsd(r.usd) : '', historyDetail(r)))}
        {moreButton($, ui, folds, 'history', Math.max(t.spawns, s.rows.length), HISTORY_ROWS)}
      </Box>,
    )
  }
  if (ts > 0) parts.push(<Text size="caption" dimColor>{`Updated ${fmtStart(ts)} · refreshes when a turn ends`}</Text>)
  return card($, ui, { id: 'spawns', title: 'Spawns', summary: spawnsSummary(s), folds }, <Box flexDirection="column" rowGap={1}>{parts}</Box>)
}

// ---- the pane

export async function renderPane($: EngineInterface, e: RenderEvent) {
  const ui = $.ui.resolve(e)
  const { Box } = ui
  const p = await getPane($)
  const folds = await getFolds($)
  if ((await getPaneView($)) === 'overrides') return overridesPage($, ui, p, folds)
  const look = lookOf(e)
  const g = await getGuide($)
  const cards: JSX.Element[] = []
  if (p?.places.guide === 'pane' && g !== null) {
    const hidden = hideKeyOf(g) === (await getHiddenKey($))
    const last = g.last_resolved ?? null
    const shownLast = last !== null && last.ts !== (await getDismissedTs($)) ? last : null
    cards.push(guideCard($, ui, g, hidden, shownLast, (await getRunning($)) === true, folds, look))
  }
  if (p?.places.resume === 'pane') cards.push(resumeCard($, ui, p.resume, folds, look))
  if (p?.places.spawns === 'pane') cards.push(spawnsCard($, ui, p.spawns, folds, look, p.ts))
  cards.push(await overridesCard($, ui, p, folds))
  return (
    <Box flexDirection="column" gap={1}>
      {cards}
    </Box>
  )
}
