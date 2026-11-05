import type { EngineInterface } from 'claude-code'

import type { Guide, GuideItem, Pane, PaneDecision, PaneLive, PaneRow, PaneSpawns } from '../types'
import { overridesCard, overridesPage } from './editor'
import { BRAND_AR, BRAND_EN, brandFooter, decisionCards, guideBlock, homeBlocks, receiptCard, resumeBlocks, spawnsBlocks, subhead, toneOf } from './html'
import type { Block, CardItem, DecisionRow, Fact, Receipt, SpawnRow, Tone } from './html'
import {
  ACCENT,
  GREY,
  bar,
  caretOf,
  card,
  copyPrompt,
  dotIcon,
  emptyLine,
  fillPrompt,
  getDismissedTs,
  getFolds,
  getGuide,
  getHiddenKey,
  getPane,
  getPaneDetail,
  getPaneNavTs,
  getPaneTab,
  navBar,
  NAV,
  getPaneView,
  openDetail,
  setPaneView,
  getRunning,
  heading,
  GLYPH,
  buttonRow,
  glyph,
  hasSvg,
  htmlSection,
  emptyPic,
  paneW,
  pic,
  hideKeyOf,
  idOf,
  isOpen,
  kv,
  longText,
  lookOf,
  moreButton,
  plain,
  rule,
  ruled,
  sections,
  setFold,
  shortHash,
  showGuide,
  themeOf,
  undoRow,
  uniqueIds,
  viewOf,
} from './shared'
import type { Folds, GuideView, IconName, Look, RenderEvent, Ui } from './shared'

// The "Abo Fles" pane. On the desktop: a nav bar of icon tiles and one page at a time — Home (the one thing to do next and each
// section's most important line), then Guide, Resume, Decisions, Spawns as the abofles hooks placed them (`pane.places`), and
// always Overrides, whose Edit turns the pane into the overrides editor (editor.tsx). Each page is HTML cards (html.ts) with
// native buttons under them; a long text is clamped in its card and whole on the section's Full details page (detailOf).
// On the terminal: flat sections with a rule between them, each folding from its header; rows with a lead (a status dot, a
// number, a bullet, a caret), the text, and a value held at the right; long text cut at a word with a grey "Read more" link.

export const fmtTokens = (n: number): string => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}K` : String(n))
export const fmtUsd = (x: number): string => (x > 0 && x < 0.005 ? '<$0.01' : `$${x.toFixed(2)}`)

const pad2 = (n: number): string => String(n).padStart(2, '0')

// `14:05`: a spawn's start (`ts`, epoch seconds, local time), or `running` when the hook gave no start.
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

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

// The colours the app's own meters use; theme keys for meaning (error, warning, success).
const BLUE = '#4a8cf0'
const ORANGE = '#e0763a'
const MODEL_COLOR: Record<string, string> = { haiku: BLUE, sonnet: ORANGE, opus: '#4fae8e', fable: '#a78bfa' }

// ---- the rows

// A list row: the lead (a dot, a number, a bullet) in a column of its own, the body beside it, wrapping by itself (a right-to-left
// line too), and an optional value held at the right.
function row(ui: Ui, lead: JSX.Element | null, body: JSX.Element | (JSX.Element | null)[], value?: JSX.Element | null) {
  const { Box } = ui
  return (
    <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
      {lead ? <Box flexShrink={0}>{lead}</Box> : null}
      <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
        {body}
      </Box>
      {value ? <Box flexShrink={0}>{value}</Box> : null}
    </Box>
  )
}

// A status dot: the desktop draws it (its word as the alt), the terminal a ● in the nearest theme colour.
function dot(ui: Ui, look: Look, tone: string, word: string) {
  const { Text } = ui
  const theme = themeOf(tone)
  return dotIcon(ui, look, tone, word) ?? (theme ? <Text color={theme}>●</Text> : <Text dimColor>●</Text>)
}

// The dot of a guide priority and its word: red 🔴 urgent, orange 🟠 high, amber 🟡 medium / 💰 budget, green 🟢 / ✅ ok; grey for
// the rest. The colour never carries the meaning alone: the desktop's dot has the word as its alt, the terminal a muted word line.
function priority(p: string | undefined): { word: string; tone: string } {
  if (p === '🔴') return { word: 'urgent', tone: 'error' }
  if (p === '🟠') return { word: 'high', tone: ORANGE }
  if (p === '🟡') return { word: 'medium', tone: 'warning' }
  if (p === '💰') return { word: 'budget', tone: 'warning' }
  if (p === '🟢' || p === '✅') return { word: 'ok', tone: 'success' }
  return { word: 'note', tone: GREY }
}

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

// The guide's actions, right under the items they act on, all buttons in one wrapping row: one primary (Check all when 2+ items
// are open, else Use; Save memo when nothing else is open), the rest secondary, then `extra` (the card's Full details, Show all).
// On the desktop each label leads with its glyph (GLYPH).
function guideActions($: EngineInterface, ui: Ui, g: Guide, v: GuideView, look: Look, extra: (JSX.Element | null)[] = []) {
  const { Button } = ui
  const all = g.all && g.all.n >= 2 ? g.all : null
  return buttonRow(ui, [
    all ? <Button key="check-all" label={glyph(look, GLYPH.all, `Check all (${all.n})`)} variant="primary" onPress={() => fillPrompt($, g, all.fill)} /> : null,
    v.done ? null : <Button key="use" label={glyph(look, GLYPH.use, 'Use')} variant={all ? 'secondary' : 'primary'} onPress={() => fillPrompt($, g, v.prompt)} />,
    v.recheck ? <Button key="recheck" label={glyph(look, GLYPH.recheck, 'Re-check')} variant="secondary" onPress={() => fillPrompt($, g, v.recheck as string)} /> : null,
    v.done ? null : <Button key="copy" label={glyph(look, GLYPH.copy, 'Copy')} variant="secondary" onPress={press => copyPrompt($, v.prompt, press.surface)} />,
    v.memo ? <Button key="memo" label={glyph(look, GLYPH.memo, 'Save memo')} variant={v.done ? 'primary' : 'secondary'} onPress={() => fillPrompt($, g, '/abofles:memo')} /> : null,
    ...extra,
  ])
}

// A guide item: its priority dot and its text. The top item — the one Use hands over — is shown whole; the others are dim, one row.
function guideItem($: EngineInterface, ui: Ui, look: Look, folds: Folds, it: GuideItem, top: boolean) {
  const { Text } = ui
  const { word, tone } = priority(it.p)
  const text = plain(it.text)
  return row(ui, dot(ui, look, tone, `${word} priority`), [
    top ? <Text>{text}</Text> : longText($, ui, look, folds, `guide:${idOf(it)}`, text, { dim: true, indent: 3 }),
    look.svg ? null : <Text size="caption" dimColor>{word}</Text>,
  ])
}

// Nothing open: "All clear", or "Next from the memo" and that text.
function clearRows($: EngineInterface, ui: Ui, g: Guide, top: GuideItem | undefined, folds: Folds, look: Look): JSX.Element {
  const { Box } = ui
  const text = plain(top?.text ?? g.line.replace(/^\s*🧭\s*/, ''))
  const m = /memo:\s*(.+)$/i.exec(text)
  return (
    <Box flexDirection="column">
      {emptyLine(ui, look, m ? 'Next from the memo' : 'All clear', 'check', 'success')}
      {longText($, ui, look, folds, `guide:clear:${top ? idOf(top) : 'line'}`, m ? m[1] : text, { dim: !m, lines: 2 })}
    </Box>
  )
}

// The guide's numbers for the HTML card, as two-edge facts, and the same facts as label/value lines for its alt text.
// The main-session line as a two-row fact: the model to use as the value, what it is now (and where to switch) under it.
// "main: suggest Opus 5.5 · High for this 🔴 Critical task (now Opus 5.5 · Extra). Switch …" → Main model · Opus 5.5 · High,
// "now Opus 5.5 · Extra · switch in the model picker"; "main: Opus 5.5 · Medium fits this 🟠 Sensitive task" → … · "fits this Sensitive task".
function mainFact(line: string | null | undefined): Fact | null {
  const raw = (line ?? '').replace(/^\s*main:\s*/i, '').replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]\uFE0F?\s*/gu, '').trim()
  if (!raw) return null
  const fits = /^(.+?)\s+fits this (.+?) task/i.exec(raw)
  if (fits) return { label: 'Main model', value: fits[1], tone: 'green', sub: `fits this ${fits[2]} task` }
  const sug = /^suggest\s+(.+?)(?:\s+for this (.+?) task)?\s*\(now ([^)]+)\)/i.exec(raw)
  if (sug) return { label: 'Main model', value: sug[1], tone: 'amber', sub: `now ${sug[3]} · switch in the model picker` }
  return { label: 'Main model', value: raw.replace(/^suggest\s+/i, '').split(/\s+for this |\s*\(/)[0] }
}

function guideFacts(g: Guide, v: GuideView): { facts: Fact[]; alt: string[] } {
  const facts: Fact[] = []
  const alt: string[] = []
  const due = v.memo && v.done ? 'Near the next mark: save the memo, then /compact.' : undefined
  if (g.ctx) {
    const k = Math.round(g.ctx.tokens / 1000)
    const value = g.ctx.mark == null ? `${k}K` : `${k}K / ${g.ctx.mark}K`
    const meter = g.ctx.mark ? { pct: (100 * k) / g.ctx.mark, tone: (v.memo ? 'amber' : 'blue') as Tone } : undefined
    facts.push({ label: 'Context', value, tone: v.memo ? 'amber' : undefined, meter, sub: due ? 'Save the memo, then /compact.' : undefined })
    alt.push('Context', value, ...(meter ? [`Context ${Math.round(meter.pct)}% of the next mark`] : []), ...(due ? [due] : []))
  }
  if (g.task) {
    const value = `${plural(g.task.spawns, 'spawn')} · $${g.task.usd.toFixed(2)}`
    facts.push({ label: 'This task', value })
    alt.push('This task', value)
    if (g.task.left != null) {
      const left = g.task.budget != null ? `${g.task.left} of ${g.task.budget} left` : `${g.task.left} left`
      facts.push({ label: 'Agent budget', value: left, tone: g.task.left === 0 ? 'red' : undefined })
      alt.push('Agent budget', left)
    }
  }
  const mm = mainFact(g.main)
  if (mm) {
    facts.push(mm)
    alt.push(mm.label, mm.value, mm.sub ?? '')
  }
  return { facts, alt }
}

// The Guide where the surface draws SVG: one HTML card (html.ts) — "Next up" with the top item's priority pill and its text, the
// other open items one line each, the numbers as two-edge facts — and the buttons under it, the card's Full details and Show all
// last. The card's alt carries every text, one per line.
function guideHtml($: EngineInterface, ui: Ui, g: Guide, v: GuideView, folds: Folds, look: Look): (JSX.Element | null)[] {
  const { Button } = ui
  const cardItem = (it: GuideItem): CardItem => {
    const { word, tone } = priority(it.p)
    return { text: plain(it.text), word, tone: toneOf(tone) }
  }
  const clear = v.done || v.items.length === 0
  const [top, ...rest] = clear ? [] : v.items
  const shown = isOpen(folds, 'more:guide', false) ? rest : rest.slice(0, 2)
  let note: { title: string; text: string } | null = null
  if (clear) {
    const text = plain(v.top?.text ?? g.line.replace(/^\s*🧭\s*/, ''))
    const m = /memo:\s*(.+)$/i.exec(text)
    note = { title: m ? 'Next from the memo' : 'All clear', text: m ? m[1] : text }
  }
  const t = guideFacts(g, v)
  const { block, more } = guideBlock({ paneW: paneW(look), top: top ? cardItem(top) : null, rest: shown.map(cardItem), clear: note, facts: t.facts })
  const alt = [
    ...(top ? [`Next up, ${cardItem(top).word} priority`, cardItem(top).text] : []),
    ...(note ? [note.title, note.text] : []),
    ...(shown.length > 0 ? ['Also open', ...shown.flatMap(it => [`${cardItem(it).word} priority`, cardItem(it).text])] : []),
    ...t.alt,
  ]
  const extra = [
    more || rest.length > shown.length ? <Button key="detail:guide" label={glyph(look, GLYPH.detail, 'Full details')} variant="secondary" onPress={() => openDetail($, 'guide')} /> : null,
    moreButton($, ui, folds, 'guide', v.items.length, rest.length > 2 ? 3 : v.items.length, look),
  ]
  return [pic(ui, look, block, alt), !v.done || v.memo || extra.some(Boolean) ? guideActions($, ui, g, v, look, extra) : null]
}

function guideCard($: EngineInterface, ui: Ui, g: Guide, hidden: boolean, last: Guide['last_resolved'], busy: boolean, folds: Folds, look: Look) {
  const { Box, Button, Text } = ui
  const v = viewOf(g)
  const open = v.items.filter(i => i.p !== '✅')
  const parts: (JSX.Element | null)[] = []
  const summary = hidden ? 'hidden' : v.done ? 'all clear' : open.length > 0 ? `${open.length} open` : null
  const tone = hidden ? undefined : v.done ? 'success' : open.length > 0 ? 'warning' : undefined
  if (last) parts.push(undoRow($, ui, g, last, busy, true))
  if (hidden) {
    parts.push(
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1}>
        <Text dimColor>Hidden until the list changes.</Text>
        <Button key="show" label={glyph(look, GLYPH.show, 'Show')} variant={look.svg ? 'secondary' : undefined} plain={look.svg ? undefined : true} dimColor={look.svg ? undefined : true} onPress={() => showGuide($)} />
      </Box>,
    )
  }
  if (hasSvg(ui, look)) {
    if (!hidden) parts.push(...guideHtml($, ui, g, v, folds, look))
    return htmlSection(ui, look, { icon: 'compass', tone: 'coral', title: 'Guide', summary, summaryTone: tone ? toneOf(tone) : null }, parts)
  }
  if (!hidden) {
    if (v.done || v.items.length === 0) parts.push(clearRows($, ui, g, v.top, folds, look))
    else {
      const [top, ...rest] = v.items
      const shown = isOpen(folds, 'more:guide', false) ? rest : rest.slice(0, 2)
      parts.push(
        <Box flexDirection="column" rowGap={1}>
          {guideItem($, ui, look, folds, top, true)}
          {shown.map(it => guideItem($, ui, look, folds, it, false))}
          {moreButton($, ui, folds, 'guide', v.items.length, rest.length > 2 ? 3 : v.items.length)}
        </Box>,
      )
    }
    if (!v.done || v.memo) parts.push(guideActions($, ui, g, v, look))
    const numbers = guideNumbers(ui, g, v, look)
    if (numbers.length > 0) parts.push(rule(ui, look, 'row divider', true), <Box flexDirection="column">{numbers}</Box>)
  }
  return card($, ui, { id: 'guide', title: 'Guide', summary, tone, folds, icon: 'compass', look }, <Box flexDirection="column" rowGap={1}>{parts}</Box>)
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

// A receipt as one row, as the app lists its own: the grey caret that opens the details, the time, the spawns, and at the right
// the cost and the saving in columns of their own; open, its done / check / open lines under it.
function receiptRow($: EngineInterface, ui: Ui, look: Look, folds: Folds, line: string, i: number): JSX.Element {
  const { Box, Button, Text } = ui
  const r = receiptOf(line)
  const id = `rcpt:${r.time ?? 'x'}:${i}`
  const open = isOpen(folds, id, false)
  const when = r.time ? fmtWhen(r.time) : ''
  return (
    <Box flexDirection="column" rowGap={0}>
      <Box flexDirection="row" alignItems="center" columnGap={1}>
        {r.details.length > 0 ? <Button key={id} label={caretOf(open)} plain dimColor onPress={() => setFold($, id, !open)} /> : null}
        <Box flexDirection="row" flexGrow={1} flexShrink={1} minWidth={0} columnGap={2}>
          {when ? <Text dimColor tabular>{when}</Text> : null}
          {r.spawns ? <Text>{r.spawns}</Text> : longText($, ui, look, folds, `${id}:text`, r.text, { indent: when ? 14 : 0 })}
        </Box>
        {r.spawns ? (
          <Box width={7} justifyContent="flex-end" flexShrink={0}>
            <Text dimColor tabular>{r.usd ?? '-'}</Text>
          </Box>
        ) : null}
        {r.spawns ? (
          <Box width={4} justifyContent="flex-end" flexShrink={0}>
            <Text dimColor tabular>{r.saved ?? '-'}</Text>
          </Box>
        ) : null}
      </Box>
      {open ? (
        <Box flexDirection="column" paddingLeft={3}>
          {r.details.map((d, j) => longText($, ui, look, folds, `${id}:d${j}`, d, { caption: true, dim: true, indent: 3, lines: 2 }))}
        </Box>
      ) : null}
    </Box>
  )
}

// A group of a card: its captioned heading (with an icon and a count or note at the right) and its rows.
function group(ui: Ui, head: JSX.Element, rows: (JSX.Element | null)[]) {
  const { Box } = ui
  return (
    <Box flexDirection="column" rowGap={1}>
      {head}
      {rows}
    </Box>
  )
}

// Resume on the desktop: where the work stands (Now, Next), what needs the owner with its Check all and Show all right under it,
// what is left (Full details joins the last card's row), and the last receipts, each with its own Full details, with the memo's facts.
function resumeHtml($: EngineInterface, ui: Ui, r: Pane['resume'], folds: Folds, look: Look, g: Guide | null) {
  const { Button } = ui
  const head = { icon: 'bookmark' as const, tone: 'blue' as const, title: 'Resume' }
  if (r === null) return htmlSection(ui, look, head, [emptyPic(ui, look, 'No memo yet — run /abofles:memo')])
  const hp = headParts(r.head)
  const needs = isOpen(folds, 'more:needs', false) ? r.needs : r.needs.slice(0, 3)
  const left = isOpen(folds, 'more:left', false) ? r.left : r.left.slice(0, 3)
  const receipts: Receipt[] = r.last.map(l => {
    const x = receiptOf(l)
    return { ...x, time: x.time ? fmtWhen(x.time) : '' }
  })
  const facts: Fact[] = [hp.session ? { label: 'Session', value: hp.session } : null, hp.memo ? { label: 'Memo saved', value: fmtWhen(hp.memo, true) } : null, hp.away ? { label: 'Away', value: hp.away } : null].filter(
    (x): x is Fact => x !== null,
  )
  const nums = needs.map((n, i) => String(n.n ?? i + 1))
  const w = paneW(look)
  const b = resumeBlocks({ paneW: w, now: r.now.map(plain), next: r.next.map(plain), needs: needs.map((n, i) => ({ n: nums[i], text: plain(n.text) })), needsOpen: r.needs_open, left: left.map(plain), facts })
  const body: (JSX.Element | null)[] = []
  if (b.status) body.push(pic(ui, look, b.status, [...(r.now.length ? ['Now', ...r.now.map(plain)] : []), ...(r.next.length ? ['Next', ...r.next.map(plain)] : [])]))
  const needsRow = [
    // secondary: the Guide's action is the pane's one primary (its first item is usually this same ask)
    r.needs_fill ? <Button key="check-needs" label={glyph(look, GLYPH.all, `Check all (${r.needs_open})`)} variant="secondary" onPress={() => fillPrompt($, g, r.needs_fill as string)} /> : null,
    moreButton($, ui, folds, 'needs', r.needs.length, 3, look),
  ]
  const leftRow = [moreButton($, ui, folds, 'left', r.left.length, 3, look)]
  // Full details joins the last card's row, so the block ends in one line of buttons
  const detail = b.status || b.needs || b.left ? <Button key="detail:resume" label={glyph(look, GLYPH.detail, 'Full details')} variant="secondary" onPress={() => openDetail($, 'resume')} /> : null
  if (b.needs) body.push(pic(ui, look, b.needs, ['Needs you', `${r.needs_open} open`, ...needs.flatMap((n, i) => [nums[i], plain(n.text)])]), buttonRow(ui, b.left ? needsRow : [...needsRow, detail]))
  if (b.left) body.push(pic(ui, look, b.left, ['Left', ...left.map(plain)]), buttonRow(ui, [...leftRow, detail]))
  if (detail && !b.needs && !b.left) body.push(buttonRow(ui, [detail]))
  // the last receipts: a card each, with its Full details right under it (every line of the receipt on a page of its own)
  if (receipts.length > 0) {
    body.push(pic(ui, look, subhead('Last receipts'), ['Last receipts']))
    receipts.forEach((x, i) => {
      body.push(pic(ui, look, receiptCard(x, w), [x.time, x.spawns ?? x.text, x.usd, x.saved ? `${x.saved} saved` : null, ...x.details]))
      body.push(buttonRow(ui, [<Button key={`detail:receipt:${i}`} label={glyph(look, GLYPH.detail, 'Full details')} variant="secondary" onPress={() => openDetail($, `receipt:${i}`)} />]))
    })
  }
  if (b.facts) body.push(pic(ui, look, b.facts, facts.flatMap(f => [f.label, f.value])))
  const summary = r.needs_open > 0 ? `${r.needs_open} need you` : hp.memo ? `memo ${fmtWhen(hp.memo)}` : null
  return htmlSection(ui, look, { ...head, summary, summaryTone: r.needs_open > 0 ? 'amber' : null }, body)
}

function resumeCard($: EngineInterface, ui: Ui, r: Pane['resume'], folds: Folds, look: Look, g: Guide | null) {
  const { Box, Button, Text } = ui
  if (hasSvg(ui, look)) return resumeHtml($, ui, r, folds, look, g)
  if (r === null) return card($, ui, { id: 'resume', title: 'Resume', def: false, folds, icon: 'bookmark', look }, emptyLine(ui, look, 'No memo yet — run /abofles:memo', 'bookmark'))
  const head = headParts(r.head) // not `h`: that name is the JSX factory
  const ic = (name: IconName, color?: string) => ({ look, name, color })
  const lines = (key: string, list: string[], n: number) => list.map((t, i) => longText($, ui, look, folds, `resume:${key}:${i}`, plain(t), { lines: n }))
  const parts: (JSX.Element | null)[] = []
  if (r.now.length > 0) parts.push(group(ui, heading(ui, 'Now', undefined, undefined, ic('clock')), lines('now', r.now, 2)))
  if (r.next.length > 0) parts.push(group(ui, heading(ui, 'Next', undefined, undefined, ic('arrow')), lines('next', r.next, 2)))
  if (r.needs.length > 0) {
    const shown = isOpen(folds, 'more:needs', false) ? r.needs : r.needs.slice(0, 3)
    const rows = shown.map((n, i) => {
      const num = String(n.n ?? i + 1)
      return row(
        ui,
        <Box width={2} justifyContent="flex-end">
          <Text color="warning" tabular>{num}</Text>
        </Box>,
        longText($, ui, look, folds, `resume:needs:${num}`, plain(n.text), { indent: 3, lines: 2 }),
      )
    })
    parts.push(
      group(ui, heading(ui, 'Needs you', String(r.needs_open), 'warning', ic('alert', '#e3a33b')), [
        ...rows,
        moreButton($, ui, folds, 'needs', r.needs.length, 3),
        r.needs_fill ? (
          <Box flexDirection="row">
            <Button key="check-needs" label={`Check all (${r.needs_open})`} variant="primary" onPress={() => fillPrompt($, g, r.needs_fill as string)} />
          </Box>
        ) : null,
      ]),
    )
  }
  if (r.left.length > 0) {
    const shown = isOpen(folds, 'more:left', false) ? r.left : r.left.slice(0, 3)
    const rows = shown.map((t, i) => row(ui, <Text dimColor>•</Text>, longText($, ui, look, folds, `resume:left:${i}`, plain(t), { indent: 2 })))
    parts.push(group(ui, heading(ui, 'Left', undefined, undefined, ic('list')), [...rows, moreButton($, ui, folds, 'left', r.left.length, 3)]))
  }
  if (r.last.length > 0) parts.push(group(ui, heading(ui, 'Last receipts', undefined, undefined, ic('receipt')), ruled(ui, look, r.last.map((l, i) => receiptRow($, ui, look, folds, l, i)))))
  const facts = [head.session ? kv(ui, 'Session', head.session) : null, head.memo ? kv(ui, 'Memo saved', fmtWhen(head.memo, true)) : null, head.away ? kv(ui, 'Away', head.away) : null].filter(
    (x): x is JSX.Element => x !== null,
  )
  if (facts.length > 0) parts.push(rule(ui, look, 'row divider', true), <Box flexDirection="column">{facts}</Box>)
  const summary = r.needs_open > 0 ? `${r.needs_open} need you` : head.memo ? `memo ${fmtWhen(head.memo)}` : null
  return card($, ui, { id: 'resume', title: 'Resume', def: false, summary, tone: r.needs_open > 0 ? 'warning' : undefined, folds, icon: 'bookmark', look }, <Box flexDirection="column" rowGap={1}>{parts}</Box>)
}

// ---- Spawns

// What a history row says of its outcome: the dot's tone and the status word, which only a status with meaning carries
// (PASS, FAIL, PARTIAL, BLOCKED, PENDING, `FAIL · resolved`); a plain DONE has a green dot and no word.
export function rowStatus(r: PaneRow): { tone: string; alt: string; word: string } {
  const v = (r.verdict ?? '').toUpperCase()
  const st = (r.status ?? 'done').toLowerCase()
  if (/FAIL/.test(v) || /fail/.test(st)) return { tone: 'error', alt: 'fail', word: r.resolved ? 'FAIL · resolved' : 'FAIL' }
  if (/PASS/.test(v)) return { tone: 'success', alt: 'pass', word: 'PASS' }
  if (st === 'pending') return { tone: ORANGE, alt: 'pending', word: 'PENDING' }
  if (st === 'partial' || st === 'blocked' || st === 'low') return { tone: 'warning', alt: st, word: st.toUpperCase() }
  return { tone: 'success', alt: st, word: '' }
}

// `Sonnet 5.5 · Medium`, as the app names its models: the label the totals give, else the app's name for the id (else the id
// capitalised), and `Extra` for xhigh.
const EFFORT: Record<string, string> = { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra', max: 'Max' }
const MODEL_NAME: Record<string, string> = { haiku: 'Haiku 5.5', sonnet: 'Sonnet 5.5', opus: 'Opus 5.5', fable: 'Fable 5.1' }
const cap = (t: string): string => (t ? t[0].toUpperCase() + t.slice(1) : t)
export function modelName(model: string, effort: string, labels: Record<string, string> = {}): string {
  const m = model ? labels[model] ?? MODEL_NAME[model] ?? cap(model) : '?'
  return effort ? `${m} · ${EFFORT[effort] ?? cap(effort)}` : m
}

// `Today`, `Yesterday`, else `Nov 3`: the caption over a day's rows (local time); '' for a row without a start.
export function dayLabel(ts: number | null, now: number = Date.now()): string {
  if (ts === null) return ''
  const d = new Date(ts > 1e11 ? ts : ts * 1000)
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((day(new Date(now)) - day(d)) / 86400000)
  return diff === 0 ? 'Today' : diff === 1 ? 'Yesterday' : `${MONTHS[d.getMonth()]} ${d.getDate()}`
}

// The muted line under a spawn: `14:24 · Sonnet 5.5 · Medium · 810K tokens · PASS`.
export function rowMeta(parts: { time: string; model: string; tokens: number | null; word: string }): string {
  return [parts.time, parts.model, parts.tokens ? `${fmtTokens(parts.tokens)} tokens` : '', parts.word].filter(Boolean).join(' · ')
}

// The card's summary: `43 spawns · $4.10`.
export function spawnsSummary(s: PaneSpawns): string {
  return s.totals.usd > 0 ? `${plural(s.totals.spawns, 'spawn')} · ${fmtUsd(s.totals.usd)}` : plural(s.totals.spawns, 'spawn')
}

// The newest history rows the card shows before its "Show all".
const HISTORY_ROWS = 5

// A spawn as an activity row: the status dot; the side in semibold and the ask (two rows, then Read more); the cost at the right;
// under them the muted meta line (time, model, tokens, the status word).
function spawnRow($: EngineInterface, ui: Ui, look: Look, folds: Folds, id: string, st: { tone: string; alt: string }, side: string, desc: string, cost: string, meta: string) {
  const { Box, Text } = ui
  const lead = side || '?'
  return row(
    ui,
    dot(ui, look, st.tone, st.alt),
    [
      <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
        <Box flexShrink={0}>
          <Text weight="semibold">{lead}</Text>
        </Box>
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          {desc ? longText($, ui, look, folds, id, desc, { indent: 3 + Array.from(lead).length + 1 + (cost ? 7 : 0), lines: 2 }) : null}
        </Box>
      </Box>,
      meta ? <Text size="caption" dimColor>{meta}</Text> : null,
    ],
    cost ? <Text dimColor tabular>{cost}</Text> : null,
  )
}

const askOf = (side: string, description: string): string => [side || '?', plain(description)].filter(Boolean).join(' · ')

// The saving first, as the app's "15% used": the % saved, the spend against the baseline at the right, the split by model.
function spendBlock(ui: Ui, s: PaneSpawns, look: Look) {
  const { Box, Text } = ui
  const t = s.totals
  const versus = t.base_usd > 0 ? `${fmtUsd(t.usd)} of ${fmtUsd(t.base_usd)}${t.base_label ? ` on ${t.base_label}` : ''}` : fmtUsd(t.usd)
  const models = t.by_model.filter(m => m.spawns > 0)
  return (
    <Box flexDirection="column" rowGap={0}>
      <Box flexDirection="row" justifyContent="space-between" columnGap={1}>
        <Text weight="semibold">{`${t.saved_pct}% saved`}</Text>
        <Text dimColor tabular>{versus}</Text>
      </Box>
      {models.length > 0 ? bar(ui, look, models.map(m => ({ pct: m.pct, color: MODEL_COLOR[m.model] ?? GREY })), `Spend by model: ${models.map(m => `${m.label} ${m.pct}%`).join(', ')}`) : null}
      {models.map(m => (
        <Box flexDirection="row" columnGap={1}>
          <Text color={themeOf(MODEL_COLOR[m.model] ?? GREY)}>■</Text>
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
    </Box>
  )
}

// Spawns on the desktop: the saving and the spend split by model, the running agents, the history by day (newest first) with its
// Show all and the section's Full details under it.
function spawnsHtml($: EngineInterface, ui: Ui, s: PaneSpawns, folds: Folds, look: Look, ts: number, now: number) {
  const { Button } = ui
  const t = s.totals
  const head = { icon: 'fork' as const, tone: 'violet' as const, title: 'Spawns' }
  if (s.live.length === 0 && s.rows.length === 0) return htmlSection(ui, look, head, [emptyPic(ui, look, 'No spawns yet')])
  const labels = Object.fromEntries(t.by_model.map(m => [m.model, m.label]))
  const models = t.by_model.filter(m => m.spawns > 0)
  const versus = t.base_usd > 0 ? `${fmtUsd(t.usd)} of ${fmtUsd(t.base_usd)}${t.base_label ? ` on ${t.base_label}` : ''}` : fmtUsd(t.usd)
  const facts: Fact[] = [t.tokens > 0 ? { label: 'Tokens', value: fmtTokens(t.tokens) } : null, t.open_fail > 0 ? { label: 'Open FAIL', value: String(t.open_fail), tone: 'red' as Tone } : null].filter((x): x is Fact => x !== null)
  const wordTone = (tone: string): Tone | null => (tone === 'success' ? 'green' : tone === 'error' ? 'red' : tone === 'warning' ? 'amber' : tone === ORANGE ? 'orange' : null)
  const live: SpawnRow[] = s.live.map(l => ({ tone: 'blue', side: l.side, desc: plain(l.description), cost: '', meta: rowMeta({ time: l.ts === null ? '' : fmtStart(l.ts), model: modelName(l.model, l.effort, labels), tokens: null, word: '' }), word: 'running', wordTone: 'blue' }))
  const newest = [...s.rows].reverse()
  const shown = isOpen(folds, 'more:history', false) ? newest : newest.slice(0, HISTORY_ROWS)
  const days: { label: string; rows: SpawnRow[] }[] = []
  const alt: string[] = []
  for (const r of shown) {
    const st = rowStatus(r)
    const row: SpawnRow = { tone: toneOf(st.tone), side: r.side, desc: plain(r.description), cost: r.usd !== null ? fmtUsd(r.usd) : '', meta: rowMeta({ time: r.ts === null ? '' : fmtStart(r.ts), model: modelName(r.model, r.effort, labels), tokens: r.tokens, word: '' }), word: st.word, wordTone: wordTone(st.tone) }
    const label = dayLabel(r.ts, now)
    const last = days[days.length - 1]
    if (last && last.label === label) last.rows.push(row)
    else {
      days.push({ label, rows: [row] })
      if (label) alt.push(label)
    }
    alt.push(row.side, row.desc, row.cost, rowMeta({ time: r.ts === null ? '' : fmtStart(r.ts), model: modelName(r.model, r.effort, labels), tokens: r.tokens, word: st.word }))
  }
  const updated = ts > 0 ? `Updated ${fmtStart(ts)} · refreshes when a turn ends` : null
  const b = spawnsBlocks({ paneW: paneW(look), saved: `${t.saved_pct}% saved`, versus, models: models.map(m => ({ label: m.label, tone: toneOf(MODEL_COLOR[m.model] ?? GREY), spawns: m.spawns, usd: fmtUsd(m.usd), pct: m.pct })), facts, live, days, updated })
  const body: (JSX.Element | null)[] = [
    pic(ui, look, b.spend, [
      `${t.saved_pct}% saved`,
      versus,
      models.length ? `Spend by model: ${models.map(m => `${m.label} ${m.pct}%`).join(', ')}` : null,
      ...models.map(m => `${m.label}: ${m.spawns} spawn${m.spawns === 1 ? '' : 's'}, ${fmtUsd(m.usd)}, ${m.pct}% of spend`),
      ...facts.flatMap(f => [f.label, f.value]),
    ]),
  ]
  if (b.running) body.push(pic(ui, look, b.running, ['Running', String(s.live.length), ...live.flatMap(l => [l.side, l.desc, `${l.meta} · running`.replace(/^ · /, '')])]))
  // a long history is split into cards: the first carries the whole list's alt, so it is read once
  b.history.forEach((c, i) => body.push(pic(ui, look, c, i === 0 ? ['History', 'newest first', ...alt, updated] : [])))
  body.push(
    buttonRow(ui, [
      moreButton($, ui, folds, 'history', Math.max(t.spawns, s.rows.length), HISTORY_ROWS, look),
      <Button key="detail:spawns" label={glyph(look, GLYPH.detail, 'Full details')} variant="secondary" onPress={() => openDetail($, 'spawns')} />,
    ]),
  )
  return htmlSection(ui, look, { ...head, summary: spawnsSummary(s), summaryTone: t.open_fail > 0 ? 'red' : null }, body)
}

function spawnsCard($: EngineInterface, ui: Ui, s: PaneSpawns, folds: Folds, look: Look, ts: number, now: number) {
  const { Box, Text } = ui
  if (hasSvg(ui, look)) return spawnsHtml($, ui, s, folds, look, ts, now)
  if (s.live.length === 0 && s.rows.length === 0) return card($, ui, { id: 'spawns', title: 'Spawns', def: false, folds, icon: 'fork', look }, emptyLine(ui, look, 'No spawns yet', 'fork'))
  const t = s.totals
  const labels = Object.fromEntries(t.by_model.map(m => [m.model, m.label]))
  const parts: (JSX.Element | null)[] = [spendBlock(ui, s, look)]
  if (s.live.length > 0) {
    const ids = uniqueIds(s.live.map(l => `spawn:live:${l.ts ?? 'x'}:${shortHash(askOf(l.side, l.description))}`))
    const rows = s.live.map((l: PaneLive, i: number) =>
      spawnRow($, ui, look, folds, ids[i], { tone: BLUE, alt: 'running' }, l.side, plain(l.description), '', rowMeta({ time: l.ts === null ? '' : fmtStart(l.ts), model: modelName(l.model, l.effort, labels), tokens: null, word: 'running' })),
    )
    parts.push(rule(ui, look, 'row divider', true), group(ui, heading(ui, 'Running', String(s.live.length), undefined, { look, name: 'activity', color: BLUE }), ruled(ui, look, rows)))
  }
  if (s.rows.length > 0) {
    const newest = [...s.rows].reverse()
    const ids = uniqueIds(newest.map(r => `spawn:${r.ts ?? 'x'}:${shortHash(askOf(r.side, r.description))}`))
    const shown = (isOpen(folds, 'more:history', false) ? newest : newest.slice(0, HISTORY_ROWS)).map((r, i) => ({ r, id: ids[i] }))
    // one muted caption per day; the rows under it show only the time
    const days: { label: string; rows: { r: PaneRow; id: string }[] }[] = []
    for (const x of shown) {
      const label = dayLabel(x.r.ts, now)
      const last = days[days.length - 1]
      if (last && last.label === label) last.rows.push(x)
      else days.push({ label, rows: [x] })
    }
    const daysOut = days.map(d => (
      <Box flexDirection="column" rowGap={1}>
        {d.label ? <Text size="caption" weight="medium" dimColor>{d.label}</Text> : null}
        {ruled(
          ui,
          look,
          d.rows.map(({ r, id }) => {
            const st = rowStatus(r)
            return spawnRow($, ui, look, folds, id, st, r.side, plain(r.description), r.usd !== null ? fmtUsd(r.usd) : '', rowMeta({ time: r.ts === null ? '' : fmtStart(r.ts), model: modelName(r.model, r.effort, labels), tokens: r.tokens, word: st.word }))
          }),
        )}
      </Box>
    ))
    parts.push(rule(ui, look, 'row divider', true), group(ui, heading(ui, 'History', 'newest first', undefined, { look, name: 'clock' }), [...daysOut, moreButton($, ui, folds, 'history', Math.max(t.spawns, s.rows.length), HISTORY_ROWS)]))
  }
  if (ts > 0) parts.push(<Text size="caption" dimColor>{`Updated ${fmtStart(ts)} · refreshes when a turn ends`}</Text>)
  return card($, ui, { id: 'spawns', title: 'Spawns', def: false, summary: spawnsSummary(s), tone: t.open_fail > 0 ? 'error' : undefined, folds, icon: 'fork', look }, <Box flexDirection="column" rowGap={1}>{parts}</Box>)
}

// ---- Decisions

// The newest decisions each group shows before its "Show all".
const DECISION_ROWS = 5

// A decision as every view reads it: the Judge's question loses its "judge: " lead; a note (`memo.py note`) has no question.
function decisionOf(d: PaneDecision, judge: boolean): DecisionRow {
  const q = plain(judge ? d.q.replace(/^\s*judge:\s*/i, '') : d.q)
  return { when: fmtWhen(d.ts), q, a: plain(d.a), note: q.toLowerCase() === 'note' || q === '' }
}

// A decision: its time as a small muted headline, the question, and the answer under it after an arrow, in semibold — what was
// decided reads at a glance. A note is its text alone.
function decisionRow($: EngineInterface, ui: Ui, look: Look, folds: Folds, id: string, d: PaneDecision, judge: boolean) {
  const { Box, Text } = ui
  const { q, a, note } = decisionOf(d, judge)
  return (
    <Box flexDirection="column" rowGap={0}>
      <Text size="caption" dimColor tabular>{fmtWhen(d.ts)}</Text>
      {note ? null : longText($, ui, look, folds, `${id}:q`, q, { lines: 2 })}
      {note
        ? longText($, ui, look, folds, `${id}:a`, a, { lines: 2 })
        : row(ui, <Text dimColor>→</Text>, longText($, ui, look, folds, `${id}:a`, a, { weight: 'semibold', indent: 2, lines: 2 }))}
    </Box>
  )
}

function decisionGroup($: EngineInterface, ui: Ui, look: Look, folds: Folds, id: string, title: string, rows: PaneDecision[], n: number, judge: boolean) {
  const shown = isOpen(folds, `more:${id}`, false) ? rows : rows.slice(0, DECISION_ROWS)
  const ids = uniqueIds(rows.map(d => `dec:${id}:${d.ts}:${shortHash(`${d.q}\n${d.a}`)}`))
  return group(ui, heading(ui, title, String(n), undefined, { look, name: judge ? 'scale' : 'user', color: judge ? ACCENT.scale : GREY }), [
    ...(rows.length === 0 ? [emptyLine(ui, look, 'No decisions yet', judge ? 'scale' : 'user')] : ruled(ui, look, shown.map((d, i) => decisionRow($, ui, look, folds, ids[i], d, judge)))),
    moreButton($, ui, folds, id, rows.length, DECISION_ROWS),
  ])
}

// Decisions on the desktop: By you and By Judge, each a card (or more, for a long list) with its Show all right under it; the
// section's Full details at the end.
function decisionsHtml($: EngineInterface, ui: Ui, d: NonNullable<Pane['decisions']>, folds: Folds, look: Look) {
  const { Button } = ui
  const total = d.n_you + d.n_judge
  const body: (JSX.Element | null)[] = []
  const group = (id: string, title: string, rows: PaneDecision[], n: number, judge: boolean) => {
    const shown = isOpen(folds, `more:${id}`, false) ? rows : rows.slice(0, DECISION_ROWS)
    const list = shown.map(x => decisionOf(x, judge))
    const cards = decisionCards(title, n, list, paneW(look))
    const alt = [title, String(n), ...(list.length === 0 ? ['No decisions yet'] : list.flatMap(x => [x.when, x.note ? null : x.q, x.a]))]
    cards.forEach((card, i) => body.push(pic(ui, look, card, i === 0 ? alt : [])))
    body.push(buttonRow(ui, [moreButton($, ui, folds, id, rows.length, DECISION_ROWS, look)]))
  }
  group('dec-you', 'By you', d.you, d.n_you, false)
  group('dec-judge', 'By Judge', d.judge, d.n_judge, true)
  if (total > 0) body.push(buttonRow(ui, [<Button key="detail:decisions" label={glyph(look, GLYPH.detail, 'Full details')} variant="secondary" onPress={() => openDetail($, 'decisions')} />]))
  return htmlSection(ui, look, { icon: 'scale', tone: 'teal', title: 'Decisions', summary: total > 0 ? `${total} · ${d.n_judge} by Judge` : null }, body)
}

function decisionsCard($: EngineInterface, ui: Ui, d: NonNullable<Pane['decisions']>, folds: Folds, look: Look) {
  const { Box } = ui
  if (hasSvg(ui, look)) return decisionsHtml($, ui, d, folds, look)
  const total = d.n_you + d.n_judge
  return card(
    $,
    ui,
    { id: 'decisions', title: 'Decisions', def: false, summary: total > 0 ? `${total} · ${d.n_judge} by Judge` : null, folds, icon: 'scale', look },
    <Box flexDirection="column" rowGap={1}>
      {decisionGroup($, ui, look, folds, 'dec-you', 'By you', d.you, d.n_you, false)}
      {rule(ui, look, 'row divider', true)}
      {decisionGroup($, ui, look, folds, 'dec-judge', 'By Judge', d.judge, d.n_judge, true)}
    </Box>,
  )
}

// ---- the detail page

// Text for markdown: the marks that would style or link it escaped, so a memo line reads as written.
// Text for the detail page's Markdown: every mark escaped, a leading list or rule mark too, and links, www. names and emails broken
// with a zero-width space, so a memo line (which a prompt could have written) never turns into a link or a list.
const md = (t: string): string =>
  plain(t)
    .replace(/([\\`*_[\]<>#|~])/g, '\\$1')
    .replace(/^(\s*)([-+=])/, '$1\\$2')
    .replace(/^(\s*\d+)([.)])/, '$1\\$2')
    .replace(/\b(https?|ftp)(?=:\/\/)/gi, '$1\u200b')
    .replace(/\bwww\./gi, 'www\u200b.')
    .replace(/@/g, '@\u200b')
const cap1 = (t: string): string => (t ? t[0].toUpperCase() + t.slice(1) : t)

// One receipt in full: the time, the cost, the spawns and the saving, then every detail under its kind.
function receiptMd(line: string): string {
  const x = receiptOf(line)
  const head = [x.time ? `**${md(fmtWhen(x.time, true))}**` : null, x.usd ? `**${md(x.usd)}**` : null, x.spawns, x.saved ? `${x.saved} saved` : null].filter(Boolean).join(' · ')
  const parts = x.details.map(d => {
    const m = /^([a-z][a-z ]{1,14}):\s*(.*)$/i.exec(d)
    return m ? `**${cap1(m[1].toLowerCase())}**\n\n${md(m[2])}` : md(d)
  })
  return [head, x.text ? md(x.text) : null, ...parts].filter(Boolean).join('\n\n')
}

// A card's whole text as markdown, for the detail page: the receipt, or every item of the Guide, Resume, Spawns, Decisions.
function detailOf(id: string, p: Pane | null, g: Guide | null, now: number): { icon: IconName; tone: Tone; title: string; sub: string | null; text: string } | null {
  if (id.startsWith('receipt:')) {
    const line = p?.resume?.last[Number(id.slice(8))]
    if (!line) return null
    const x = receiptOf(line)
    return { icon: 'receipt', tone: 'blue', title: 'Receipt', sub: x.time ? fmtWhen(x.time, true) : null, text: receiptMd(line) }
  }
  if (id === 'guide' && g) {
    const v = viewOf(g)
    // nothing open: the card's note (what the memo says next), whole
    const items = v.items.length ? v.items.map(it => `**${cap1(priority(it.p).word)}** · ${md(it.text)}`) : [md(v.top?.text ?? g.line.replace(/^\s*🧭\s*/, ''))]
    const t = guideFacts(g, v).facts.map(f => `- ${md(f.label)}: **${md(f.value)}**`)
    return { icon: 'compass', tone: 'coral', title: 'Guide', sub: `${v.items.length} item${v.items.length === 1 ? '' : 's'}`, text: [...items, ...(t.length ? ['', ...t] : [])].join('\n\n') }
  }
  if (id === 'resume' && p?.resume) {
    const r = p.resume
    const sec = (title: string, lines: string[]) => (lines.length ? `#### ${title}\n\n${lines.join('\n\n')}` : null)
    return {
      icon: 'bookmark',
      tone: 'blue',
      title: 'Resume',
      sub: r.needs_open > 0 ? `${r.needs_open} need you` : null,
      text: [
        sec('Now', r.now.map(md)),
        sec('Next', r.next.map(md)),
        sec('Needs you', r.needs.map((n, i) => `**${n.n ?? i + 1}** · ${md(n.text)}`)),
        sec('Left', r.left.map(t => `- ${md(t)}`)),
      ]
        .filter(Boolean)
        .join('\n\n'),
    }
  }
  if (id === 'spawns' && p?.spawns) {
    const s = p.spawns
    const labels = Object.fromEntries(s.totals.by_model.map(m => [m.model, m.label]))
    const live = s.live.map(l => `**${md(l.side || '?')}** · running\n\n${md(l.description)}\n\n*${md(rowMeta({ time: l.ts === null ? '' : fmtStart(l.ts), model: modelName(l.model, l.effort, labels), tokens: null, word: '' }))}*`)
    const rows: string[] = []
    let day = ''
    for (const r of [...s.rows].reverse()) {
      const label = dayLabel(r.ts, now)
      if (label && label !== day) rows.push(`#### ${label}`)
      day = label
      const st = rowStatus(r)
      const head = [`**${md(r.side || '?')}**`, r.usd !== null ? fmtUsd(r.usd) : null, st.word || null].filter(Boolean).join(' · ')
      rows.push(`${head}\n\n${md(r.description)}\n\n*${md(rowMeta({ time: r.ts === null ? '' : fmtStart(r.ts), model: modelName(r.model, r.effort, labels), tokens: r.tokens, word: '' }))}*`)
    }
    return { icon: 'fork', tone: 'violet', title: 'Spawns', sub: spawnsSummary(s), text: [live.length ? `#### Running\n\n${live.join('\n\n---\n\n')}` : null, ...rows].filter(Boolean).join('\n\n') }
  }
  if (id === 'decisions' && p?.decisions) {
    const d = p.decisions
    const row = (x: PaneDecision, judge: boolean) => {
      const { when, q, a, note } = decisionOf(x, judge)
      return `*${md(when)}*\n\n${note ? md(a) : `${md(q)}\n\n→ **${md(a)}**`}`
    }
    const grp = (title: string, list: PaneDecision[], judge: boolean) => `#### ${title}\n\n${list.length ? list.map(x => row(x, judge)).join('\n\n---\n\n') : '*No decisions yet*'}`
    return { icon: 'scale', tone: 'teal', title: 'Decisions', sub: `${d.n_you + d.n_judge} · ${d.n_judge} by Judge`, text: [grp('By you', d.you, false), grp('By Judge', d.judge, true)].join('\n\n') }
  }
  return null
}

// The detail page: ‹ <the page it returns to> (Home when opened from Home), the section's header strip, and the card's whole text as markdown — drawn by the app as it
// draws a reply, so it wraps at the real width and nothing is cut.
async function detailPage($: EngineInterface, ui: Ui, p: Pane | null, g: Guide | null, look: Look, now: number) {
  const { Box, Button, Text } = ui
  const id = await getPaneDetail($)
  const d = id ? detailOf(id, p, g, now) : null
  const tab = await getPaneTab($)
  const back = (
    <Box flexDirection="row" alignItems="center">
      <Button key="detail-back" label={glyph(look, '‹', NAV.find(n => n.id === tab)?.label ?? 'Back')} variant="secondary" onPress={() => setPaneView($, 'main')} />
    </Box>
  )
  if (d === null) return <Box flexDirection="column" rowGap="sm">{back}<Text dimColor>Nothing to show here any more.</Text></Box>
  const { Markdown } = ui as Ui & { Markdown: NonNullable<Ui['Markdown']> }
  return (
    <Box flexDirection="column" rowGap="md">
      {back}
      {htmlSection(ui, look, { icon: d.icon, tone: d.tone, title: d.title, summary: d.sub }, [<Markdown key="detail-text" text={d.text} />])}
    </Box>
  )
}

// ---- Home

// The Home page of the desktop: the one thing to do next with its buttons, the numbers that matter from every section at a glance,
// where the work stands, and the latest decision and receipt. The nav bar's other pages hold the detail.
// Only the sections the pane holds feed it: one placed in the band or the chat is not summed up here (`p` and `g` come filtered).
function homeHtml($: EngineInterface, ui: Ui, p: { resume: Pane['resume']; spawns: PaneSpawns | null; decisions: Pane['decisions'] | null }, g: Guide | null, look: Look, hidden: boolean) {
  const { Button } = ui
  const v = g ? viewOf(g) : null
  const open = v ? v.items.filter(i => i.p !== '✅').length : 0
  const clear = !v || v.done || v.items.length === 0
  const top = !clear && v ? v.items[0] : undefined
  const topItem: CardItem | null = top ? { text: plain(top.text), word: priority(top.p).word, tone: toneOf(priority(top.p).tone) } : null
  let note: { title: string; text: string } | null = null
  if (clear) {
    const text = g ? plain(v?.top?.text ?? g.line.replace(/^\s*🧭\s*/, '')) : 'Nothing from the guide yet'
    const m = /memo:\s*(.+)$/i.exec(text)
    note = { title: m ? 'Next from the memo' : 'All clear', text: m ? m[1] : text }
  }
  // the numbers that matter now, one from each section where it says something
  const glance: Fact[] = []
  const gf = g && v ? guideFacts(g, v).facts : []
  const ctx = gf.find(f => f.label === 'Context')
  if (ctx) glance.push({ ...ctx, sub: undefined })
  const r = p?.resume ?? null
  if (r && r.needs_open > 0) glance.push({ label: 'Needs you', value: String(r.needs_open), tone: 'amber' })
  const s = p?.spawns ?? null
  if (s && s.live.length > 0) glance.push({ label: 'Running', value: plural(s.live.length, 'agent'), tone: 'blue' })
  if (s && s.totals.open_fail > 0) glance.push({ label: 'Open FAIL', value: String(s.totals.open_fail), tone: 'red' })
  const task = gf.find(f => f.label === 'This task')
  if (task) glance.push(task)
  if (s && s.totals.spawns > 0) glance.push({ label: 'Saved', value: `${s.totals.saved_pct}% · ${fmtUsd(s.totals.usd)} spent`, tone: 'green' })
  // the newest decision of either group (the times sort as written)
  const d = p?.decisions ?? null
  const newest = d ? [d.you[0], d.judge[0]].filter((x): x is PaneDecision => !!x).sort((a, b) => (a.ts < b.ts ? 1 : -1))[0] : undefined
  const decision = newest ? decisionOf(newest, d?.judge[0] === newest) : null
  const last = r?.last[0]
  const rc = last ? receiptOf(last) : null
  const done = rc ? rc.details.map(x => /^done:\s*(.*)$/i.exec(x)?.[1]).find(Boolean) ?? rc.text : null
  const b = homeBlocks({
    paneW: paneW(look),
    top: topItem,
    clear: note,
    glance,
    now: r?.now[0] ? plain(r.now[0]) : null,
    next: r?.next[0] ? plain(r.next[0]) : null,
    decision,
    receipt: rc && done ? { time: rc.time ? fmtWhen(rc.time) : '', text: plain(done) } : null,
  })
  const all = g?.all && g.all.n >= 2 ? g.all : null
  const body: (JSX.Element | null)[] = !g ? [] : [
    hidden
      ? emptyPic(ui, look, 'Guide hidden until the list changes')
      : pic(ui, look, b.next, [...(topItem ? [`Next up, ${topItem.word} priority`, topItem.text] : []), ...(note ? [note.title, note.text] : [])]),
    hidden
      ? buttonRow(ui, [<Button key="show" label={glyph(look, GLYPH.show, 'Show')} variant="secondary" onPress={() => showGuide($)} />])
      : buttonRow(ui, [
          g && v && !v.done && all ? <Button key="check-all" label={glyph(look, GLYPH.all, `Check all (${all.n})`)} variant="primary" onPress={() => fillPrompt($, g, all.fill)} /> : null,
          g && v && !v.done ? <Button key="use" label={glyph(look, GLYPH.use, 'Use')} variant={all ? 'secondary' : 'primary'} onPress={() => fillPrompt($, g, v.prompt)} /> : null,
          // the card cuts a long text at four lines: its whole text is on the Guide's detail page
          b.more ? <Button key="detail:next" label={glyph(look, GLYPH.detail, 'Full details')} variant="secondary" onPress={() => openDetail($, 'guide')} /> : null,
        ]),
  ]
  if (b.glance) body.push(pic(ui, look, b.glance, ['At a glance', ...glance.flatMap(f => [f.label, f.value])]))
  if (b.where) body.push(pic(ui, look, b.where, [r?.now[0] ? 'Now' : null, r?.now[0] ? plain(r.now[0]) : null, r?.next[0] ? 'Next' : null, r?.next[0] ? plain(r.next[0]) : null]))
  if (b.latest) body.push(pic(ui, look, b.latest, [decision ? 'Last decision' : null, decision?.when, decision && !decision.note ? decision.q : null, decision?.a, done ? 'Last receipt' : null, done ? plain(done) : null]))
  if (body.length === 0) body.push(emptyPic(ui, look, 'Nothing to sum up yet'))
  return htmlSection(ui, look, { icon: 'house', tone: 'mint', title: 'Home', summary: g ? (open > 0 ? `${open} open` : 'all clear') : null, summaryTone: g ? (open > 0 ? 'amber' : 'green') : null }, body)
}

// ---- the pane

// The brand line under the last section: on the desktop a muted picture row (the mascot, the English and Arabic name); in the
// terminal the name alone, dim and centred.
function brandFoot(ui: Ui, look: Look) {
  if (hasSvg(ui, look)) return pic(ui, look, brandFooter(), [`${BRAND_EN} · ${BRAND_AR}`])
  const { Box, Text } = ui
  return (
    <Box flexDirection="row" justifyContent="center">
      <Text dimColor>{`${BRAND_EN} · ${BRAND_AR}`}</Text>
    </Box>
  )
}

export async function renderPane($: EngineInterface, e: RenderEvent) {
  const ui = $.ui.resolve(e)
  const p = await getPane($)
  const folds = await getFolds($)
  const look = lookOf(e)
  const view = await getPaneView($)
  if (view === 'overrides') return overridesPage($, ui, p, folds, look)
  if (view === 'detail' && hasSvg(ui, look)) return detailPage($, ui, p, await getGuide($), look, await $.clock.now())
  const g = await getGuide($)
  const guideHere = async (lk: Look) => {
    if (!(p?.places.guide === 'pane' && g !== null)) return null
    const hidden = hideKeyOf(g) === (await getHiddenKey($))
    const last = g.last_resolved ?? null
    const shownLast = last !== null && last.ts !== (await getDismissedTs($)) ? last : null
    return guideCard($, ui, g, hidden, shownLast, (await getRunning($)) === true, folds, lk)
  }
  if (hasSvg(ui, look)) {
    // the desktop: a nav bar and one page at a time (Home, then each section), so nothing needs a long scroll
    const now = await $.clock.now()
    const tabs = [
      'home',
      ...(p?.places.guide === 'pane' && g !== null ? ['guide'] : []),
      ...(p?.places.resume === 'pane' ? ['resume'] : []),
      ...(p?.decisions ? ['decisions'] : []),
      ...(p?.places.spawns === 'pane' ? ['spawns'] : []),
      'overrides',
    ]
    const want = await getPaneTab($)
    const tab = tabs.includes(want) ? want : 'home'
    const lk: Look = now - (await getPaneNavTs($)) < 1500 ? { ...look, enter: { n: 0 } } : look // just moved here: the cards slide in
    const page =
      tab === 'guide'
        ? await guideHere(lk)
        : tab === 'resume' && p
          ? resumeCard($, ui, p.resume, folds, lk, g)
          : tab === 'decisions' && p?.decisions
            ? decisionsCard($, ui, p.decisions, folds, lk)
            : tab === 'spawns' && p
              ? spawnsCard($, ui, p.spawns, folds, lk, p.ts, now)
              : tab === 'overrides'
                ? await overridesCard($, ui, p, folds, lk)
                : homeHtml(
                    $,
                    ui,
                    { resume: p?.places.resume === 'pane' ? p.resume : null, spawns: p?.places.spawns === 'pane' ? p.spawns : null, decisions: p?.decisions ?? null },
                    p?.places.guide === 'pane' ? g : null,
                    lk,
                    g !== null && hideKeyOf(g) === (await getHiddenKey($)),
                  )
    const { Box } = ui
    return (
      <Box flexDirection="column" rowGap="lg">
        {navBar($, ui, look, tab, tabs)}
        {page}
        {brandFoot(ui, look)}
      </Box>
    )
  }
  const cards: JSX.Element[] = []
  const gc = await guideHere(look)
  if (gc) cards.push(gc)
  if (p?.places.resume === 'pane') cards.push(resumeCard($, ui, p.resume, folds, look, g))
  if (p?.decisions) cards.push(decisionsCard($, ui, p.decisions, folds, look))
  if (p?.places.spawns === 'pane') cards.push(spawnsCard($, ui, p.spawns, folds, look, p.ts, await $.clock.now())) // the engine's clock: Today / Yesterday
  cards.push(await overridesCard($, ui, p, folds, look))
  cards.push(brandFoot(ui, look))
  return sections(ui, look, cards)
}
