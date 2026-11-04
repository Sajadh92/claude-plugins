import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { Guide, GuideItem, Pane, PaneDecision, PaneDecisions, PaneLive, PaneModel, PaneOverrideKey, PaneOverrides, PanePlaces, PaneResume, PaneRow, PaneSpawns, PaneTotals } from '../types'
import { ICONS, emptyCard, headerBlock, paneWidth, svgOf, tileSvg } from './html'
import type { Block, IconName, Tone } from './html'

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
const paneView = atom({ plugin: 'abofles-guide', key: 'paneView' } as const, 'main' as 'main' | 'overrides' | 'detail')
// which card the detail page shows (see PluginState)
const paneDetail = atom({ plugin: 'abofles-guide', key: 'paneDetail' } as const, null as string | null)
// the desktop's page (the nav bar's tab), and when the person last moved (its cards slide in for a moment)
const paneTab = atom({ plugin: 'abofles-guide', key: 'paneTab' } as const, 'home')
const paneNavTs = atom({ plugin: 'abofles-guide', key: 'paneNavTs' } as const, 0)
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

export async function getPaneView($: EngineInterface): Promise<'main' | 'overrides' | 'detail'> {
  const v = await read($, paneView)
  return v === 'overrides' || v === 'detail' ? v : 'main'
}
export function setPaneView($: EngineInterface, view: 'main' | 'overrides' | 'detail') {
  return update($, paneView, () => view)
}
export async function getPaneDetail($: EngineInterface): Promise<string | null> {
  const v = await read($, paneDetail)
  return typeof v === 'string' ? v : null
}
export async function getPaneTab($: EngineInterface): Promise<string> {
  const v = await read($, paneTab)
  return typeof v === 'string' && v ? v : 'home'
}
export async function getPaneNavTs($: EngineInterface): Promise<number> {
  const v = await read($, paneNavTs)
  return typeof v === 'number' ? v : 0
}
// Moves the desktop pane to a page of its nav bar: the cards there slide in, and the page starts at its top.
export async function goTab($: EngineInterface, tab: string) {
  const at = await $.clock.now()
  await update($, paneNavTs, () => at)
  await update($, paneTab, () => tab)
  await setPaneView($, 'main')
  try {
    await $.ui.scroll({ in: PANE_ID, to: 'start' })
  } catch {
    // a surface or a test without scrolling
  }
}

// Opens the detail page of one card (`id`: 'guide', 'resume', 'spawns', 'decisions', 'receipt:<n>'); its Back returns to the cards.
export async function openDetail($: EngineInterface, id: string) {
  await update($, paneDetail, () => id)
  await setPaneView($, 'detail')
  try {
    await $.ui.scroll({ in: PANE_ID, to: 'start' }) // the button sat low in the pane: the page starts at its top
  } catch {
    // a surface or a test without scrolling: the page still opens
  }
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

// The disclosure caret, as the native panels draw it: a small solid triangle, right when folded and down when open. It is a
// Button of its own (grey, `dimColor`): a desktop draws a Button's label alone, so a caret inside the title's Button could not be grey.
export const CARET_OPEN = '▾'
export const CARET_FOLDED = '▸'
export const caretOf = (open: boolean): string => (open ? CARET_OPEN : CARET_FOLDED)

// The gap in px between an icon and the Text after it: carried by the icon's own width, so the Box needs no column gap.
// A Button after an icon needs none: the surface pads a Button by itself.
const ICON_GAP = 4

// A section in the look of the desktop app's own side panels (Context, Changes, Environment): flat, no box. The header row: a
// 16 px line icon in the section's accent (desktop only), the title, and the small grey caret (▾ open, ▸ folded) — the title and the
// caret are two plain Buttons that both fold the section (a desktop draws a Button's label alone, in one colour, so the caret is a
// Button of its own to be grey) — and at the right a short summary, a Text: grey, or in `tone` (a theme key) where it carries
// meaning. The body sits under the header only while the section is open. `id` names the fold (see isOpen). The pane draws a rule
// between sections.
export function card($: EngineInterface, ui: Ui, c: { id: string; title: string; summary?: string | null; tone?: string; folds: Folds; def?: boolean; icon?: IconName; neutral?: boolean; look?: Look }, body: JSX.Element | (JSX.Element | null)[]) {
  const { Box, Button, Text } = ui
  const open = isOpen(c.folds, c.id, c.def ?? true)
  const toggle = () => setFold($, c.id, !open)
  const mark = c.icon && c.look ? icon(ui, c.look, c.icon, c.neutral ? GREY : ACCENT[c.icon] ?? GREY, 16, `${c.title} icon`) : null
  return (
    <Box flexDirection="column">
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1} paddingY="md">
        <Box flexDirection="row" alignItems="center" columnGap={c.look?.svg === false ? 1 : 0} flexShrink={1}>
          {mark}
          <Button key={`fold:${c.id}`} label={c.title} plain onPress={toggle} />
          <Button key={`fold-caret:${c.id}`} label={caretOf(open)} plain dimColor onPress={toggle} />
        </Box>
        {c.summary ? c.tone ? <Text color={c.tone} tabular>{c.summary}</Text> : <Text dimColor tabular>{c.summary}</Text> : null}
      </Box>
      {open ? <Box flexDirection="column" rowGap={1} paddingBottom="md">{body}</Box> : null}
    </Box>
  )
}

// Sections with a thin rule between each (not above the first, not below the last), as the app's panel divides its own.
export function sections(ui: Ui, look: Look, items: (JSX.Element | null)[]) {
  const { Box } = ui
  const shown = items.filter((x): x is JSX.Element => x !== null)
  if (hasSvg(ui, look)) return <Box flexDirection="column" rowGap="xl">{shown}</Box> // the HTML sections: space between groups, no rule
  return (
    <Box flexDirection="column">
      {shown.flatMap((x, i) => (i === 0 ? [x] : [rule(ui, look, 'section divider'), x]))}
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
      {tone ? <Text color={tone}>{value}</Text> : <Text dimColor tabular>{value}</Text>}
    </Box>
  )
}

// A small heading inside a card (caption, medium, muted), with an optional small icon before it (`ic`, desktop only) and an
// optional count or note at the right (in `tone`, or dim).
export function heading(ui: Ui, text: string, right?: string, tone?: string, ic?: { look: Look; name: IconName; color?: string }) {
  const { Box, Text } = ui
  const mark = ic ? icon(ui, ic.look, ic.name, ic.color ?? GREY, 12, `${text} icon`, ICON_GAP) : null
  return (
    <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1}>
      <Box flexDirection="row" alignItems="center" columnGap={mark ? 0 : 1} flexShrink={1}>
        {mark}
        <Text size="caption" weight="medium" dimColor>
          {text}
        </Text>
      </Box>
      {right ? (
        tone ? (
          <Text size="caption" color={tone} tabular>
            {right}
          </Text>
        ) : (
          <Text size="caption" dimColor tabular>
            {right}
          </Text>
        )
      ) : null}
    </Box>
  )
}

// The inner width of a card in cells: the pane body less its padding (4). Unknown width: 40.
export const innerWidth = (cols?: number): number => Math.max(12, (typeof cols === 'number' ? cols : 46) - 4)

// The hex of a tone for SVG, which cannot name a theme key: the theme's red, amber and green as the app draws them (the dark values).
const HEX: Record<string, string> = { error: '#e5675e', warning: '#e3a33b', success: '#63c174' }
const hexOf = (color: string): string => HEX[color] ?? color

// Each colour an SVG uses, by its dark value: [class, light value]. The dark values read >= 4.5:1 on #1a1a1a, the light ones >= 4.5:1
// on #ffffff; a <style> in the SVG source gives light by default and the dark value under prefers-color-scheme: dark.
const PAL: Record<string, [string, string]> = {
  '#8f8f8f': ['grey', '#6b6b6b'],
  '#e5675e': ['red', '#c53030'],
  '#e3a33b': ['amber', '#9a6410'],
  '#63c174': ['green', '#2a8043'],
  '#d97757': ['coral', '#b5532f'],
  '#4a8cf0': ['blue', '#2f6fd0'],
  '#8b6cf0': ['violet', '#6a4bd0'],
  '#17a398': ['teal', '#0f7f76'],
  '#e0763a': ['orange', '#b5532f'],
  '#4fae8e': ['mint', '#2b7a62'],
  '#a78bfa': ['lilac', '#6d4fd0'],
}
const classOf = (hex: string, kind: 's' | 'f'): string => (PAL[hex] ? ` class="${kind}-${PAL[hex][0]}"` : '')
const svgStyle = (): string => {
  const rule = (dark: boolean) => Object.entries(PAL).map(([d, [n, l]]) => `.s-${n}{stroke:${dark ? d : l}}.f-${n}{fill:${dark ? d : l}}`).join('')
  return `<style>${rule(false)}@media (prefers-color-scheme: dark){${rule(true)}}</style>`
}
// The light/dark pairs, for the record and the tests.
export const COLOR_PAIRS: Record<string, { light: string; dark: string }> = Object.fromEntries(Object.entries(PAL).map(([d, [n, l]]) => [n, { light: l, dark: d }]))

// A text colour for a colour that may be a hex (the terminal's Text takes theme keys, not hex): the nearest theme key.
const TERM: Record<string, string> = { '#4a8cf0': 'suggestion', '#e0763a': 'claude', '#d97757': 'claude', '#4fae8e': 'success', '#63c174': 'success', '#e5675e': 'error', '#e3a33b': 'warning', '#a78bfa': 'inactive' }
export const themeOf = (color: string): string | undefined => (color.startsWith('#') ? TERM[color] : color)

// A short stable hash of a text (djb2, base 36): row ids keyed by it stay put when a row is prepended.
export function shortHash(text: string): string {
  let h = 5381
  for (const ch of text) h = ((h * 33) ^ (ch.codePointAt(0) ?? 0)) >>> 0
  return h.toString(36)
}

// Unique ids for a list: `base` per row, a repeated one gets `~2`, `~3`, ... so no two rows share a key.
export function uniqueIds(bases: string[]): string[] {
  const seen = new Map<string, number>()
  return bases.map(b => {
    const n = (seen.get(b) ?? 0) + 1
    seen.set(b, n)
    return n === 1 ? b : `${b}~${n}`
  })
}

// How wide a card's inside is in cells, and whether the surface draws SVG (every one but the terminal), from the render event.
// `enter`: on a page just opened, the next picture's slide-in delay (ms), counted up as pictures are drawn; absent, drawn still.
export type Look = { width: number; svg: boolean; enter?: { n: number } }
export const lookOf = (e: RenderEvent): Look => ({ width: innerWidth((e.props as { bodyColumns?: number }).bodyColumns), svg: e.surface !== 'terminal' })

// ---- icons: Lucide-style line icons (24 grid, 1.75 stroke, round caps), drawn as SVG where the surface can; none in the terminal.

// the icon paths live in html.ts, which the HTML cards draw them from too
export type { IconName }

// Hex colours (SVG cannot name a theme key): the dark values, each with a light twin in PAL.
export const GREY = '#8f8f8f' // the dark values; PAL gives each its light twin
export const ACCENT: Record<string, string> = { compass: '#d97757', bookmark: '#4a8cf0', fork: '#8b6cf0', scale: '#17a398', sliders: GREY }

// A line icon `size` px square in `color` (a hex), or null where the surface draws no SVG (the terminal: no icon).
// `pad` px of empty room after the drawing (the gap to the label), added to the SVG's width.
export function icon(ui: Ui, look: Look, name: IconName, color: string, size = 16, alt = `${name} icon`, pad = 0) {
  if (!look.svg || !('Svg' in ui) || !ui.Svg) return null
  const { Svg } = ui
  const hex = hexOf(color)
  const source = `<svg xmlns="http://www.w3.org/2000/svg" width="${size + pad}" height="${size}" viewBox="0 0 ${(24 * (size + pad)) / size} 24" preserveAspectRatio="xMinYMid meet" fill="none" stroke="${hex}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">${svgStyle()}<g${classOf(hex, 's')}>${ICONS[name]}</g></svg>`
  return <Svg source={source} alt={alt} width={size + pad} height={size} />
}

// A filled dot `size` px in `color`, with `alt` saying what it means (null where the surface draws no SVG). It is drawn centred in
// a box `line` px tall — a line of body text — so beside a Text it sits on the first line's middle, however the text wraps.
export function dotIcon(ui: Ui, look: Look, color: string, alt: string, size = 8, line = 20) {
  if (!look.svg || !('Svg' in ui) || !ui.Svg) return null
  const { Svg } = ui
  const hex = hexOf(color)
  const r = size / 2
  const source = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${line}" viewBox="0 0 ${size} ${line}">${svgStyle()}<circle cx="${r}" cy="${line / 2}" r="${r}"${classOf(hex, 'f')} fill="${hex}"/></svg>`
  return <Svg source={source} alt={alt} width={size} height={line} />
}

// A muted empty-state line with a small icon before it (the icon only where the surface draws SVG).
export function emptyLine(ui: Ui, look: Look, text: string, name: IconName = 'check', color: string = GREY) {
  const { Box, Text } = ui
  return (
    <Box flexDirection="row" alignItems="center" columnGap={1}>
      {icon(ui, look, name, color, 14, 'empty')}
      <Text dimColor>{text}</Text>
    </Box>
  )
}

// Where a long text is cut: about `room` code points, never between a letter and its combining mark, back to the last space when
// that is past the middle, trailing punctuation dropped, and "…" added.
function cutAt(chars: string[], room: number): string {
  let cut = Math.max(8, room)
  while (cut < chars.length && /\p{M}/u.test(chars[cut])) cut++ // never between a letter and its combining mark
  let head = chars.slice(0, cut).join('')
  const sp = head.lastIndexOf(' ')
  if (sp > head.length / 2) head = head.slice(0, sp)
  return `${head.replace(/[\s,;:.\-–—،؛]+$/, '')}…`
}

// The room the "Read more" link takes at the end of the last row, in cells.
const LINK_ROOM = 11

type TextLook = { dim?: boolean; caption?: boolean; weight?: 'regular' | 'medium' | 'semibold' | 'bold' }

// A text in one of the pane's styles (dim, caption, weight); `clip` cuts it at the edge with an ellipsis instead of wrapping.
function styled(ui: Ui, t: string, o: TextLook, clip = false) {
  const { Text } = ui
  return (
    <Text size={o.caption ? 'caption' : undefined} dimColor={o.dim ? true : undefined} weight={o.weight} wrap={clip ? 'truncate-end' : undefined}>
      {t}
    </Text>
  )
}

// A description as the app's lists show one. It fits in `lines` rows of the card (`look.width` cells less `indent`, with 20% to
// spare): shown whole, wrapping. Longer: the text fills the row and a small grey "Read more" link — a Button of its own, never the
// text — sits at the row's right end; pressed, the full text with "Show less" there. One row is cut by the surface itself at the
// row's real width (truncate-end, the whole text given), so the text uses every bit of room the pane has at any width; more rows
// cannot be clipped by a surface, so their text is cut at a word with "…" to about that many rows. The text keeps its style (dim,
// caption, weight) and stays plain text. The state is the fold `more:<id>`, kept with the other folds; `id` must be stable per text.
export function longText($: EngineInterface, ui: Ui, look: Look, folds: Folds, id: string, text: string, o: TextLook & { indent?: number; lines?: number } = {}) {
  const { Box, Button } = ui
  const chars = Array.from(text)
  const lines = Math.max(1, o.lines ?? 1)
  const avail = Math.max(16, look.width - (o.indent ?? 0))
  if (chars.length <= Math.ceil(avail * lines * 1.2)) return styled(ui, text, o) // at most ~20% over: a cut would save almost nothing
  const key = `more:${id}`
  const open = isOpen(folds, key, false)
  // cells are the surface's code-font advance; a proportional face fits about a tenth more per row
  const shown = open || lines === 1 ? text : cutAt(chars, Math.floor(avail * lines * 1.1) - LINK_ROOM)
  return (
    <Box flexDirection="row" alignItems="flex-end" columnGap={1}>
      <Box flexGrow={1} flexShrink={1} minWidth={0}>
        {styled(ui, shown, o, !open && lines === 1)}
      </Box>
      <Box flexShrink={0}>
        <Button key={key} label={open ? 'Show less' : 'Read more'} plain dimColor onPress={() => setFold($, key, !open)} />
      </Box>
    </Box>
  )
}

// A drawing as wide as the card at a fixed height in px, where the surface draws SVG: the markup is 1200 wide and stretched
// (preserveAspectRatio none), so it fills the card at any pane width without wrapping. Null in the terminal.
function strip(ui: Ui, look: Look, height: number, alt: string, body: string) {
  if (!look.svg || !('Svg' in ui) || !ui.Svg) return null
  const { Svg } = ui
  return <Svg source={`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="${height}" viewBox="0 0 1200 ${height}" preserveAspectRatio="none">${svgStyle()}${body}</svg>`} alt={alt} height={height} />
}

// A thin rule across the card: 1 px on the desktop, a row of ─ in the terminal (whose cells are exact).
// `light` (between the rows of a list) is fainter than the rule between sections.
export function rule(ui: Ui, look: Look, alt = 'divider', light = false) {
  const { Text } = ui
  return strip(ui, look, 1, alt, `<rect width="1200" height="1" fill="#808080" fill-opacity="${light ? '0.15' : '0.3'}"/>`) ?? <Text dimColor>{'─'.repeat(look.width)}</Text>
}

// The rows of a list with a light rule between each pair (not above the first, not below the last).
export function ruled(ui: Ui, look: Look, rows: JSX.Element[]): JSX.Element[] {
  return rows.flatMap((r, i) => (i === 0 ? [r] : [rule(ui, look, 'row divider', true), r]))
}

// A meter as the app draws one: coloured segments (percent of the width each) on a dim track — 4 px with 2 px gaps on the
// desktop, a row of ━ in the terminal. `alt` says what it shows.
export function bar(ui: Ui, look: Look, parts: { pct: number; color: string }[], alt: string) {
  const width = look.width
  const { Box, Text } = ui
  const clamp = (n: number) => Math.max(0, Math.min(100, n))
  let x = 0
  const rects = parts
    .filter(p => clamp(p.pct) > 0)
    .map(p => {
      const w = Math.max(4, (1200 * clamp(p.pct)) / 100 - 4)
      const r = `<rect x="${x.toFixed(1)}" width="${Math.min(w, 1200 - x).toFixed(1)}" height="4" rx="2"${classOf(hexOf(p.color), 'f')} fill="${hexOf(p.color)}"/>`
      x += w + 4
      return x <= 1204 ? r : ''
    })
    .join('')
  const svg = strip(ui, look, 4, alt, `<rect width="1200" height="4" rx="2" fill="#808080" fill-opacity="0.25"/>${rects}`)
  if (svg) return svg
  let used = 0
  const segs = parts.map(p => {
    const n = Math.max(p.pct > 0 ? 1 : 0, Math.round((width * clamp(p.pct)) / 100))
    const cells = Math.min(n, width - used)
    used += cells
    return cells > 0 ? <Text color={themeOf(p.color)}>{'━'.repeat(cells)}</Text> : null
  })
  return (
    <Box flexDirection="row">
      {segs}
      {width - used > 0 ? <Text dimColor>{'━'.repeat(width - used)}</Text> : null}
    </Box>
  )
}

// The "Show all N" / "Show fewer" button of a list longer than `limit` (id `more:<id>`, folded by default), or null.
export function moreButton($: EngineInterface, ui: Ui, folds: Folds, id: string, total: number, limit: number, look?: Look) {
  const { Button } = ui
  if (total <= limit) return null
  const all = isOpen(folds, `more:${id}`, false)
  const label = all ? 'Show fewer' : `Show all ${total}`
  if (look && hasSvg(ui, look)) return <Button key={`more:${id}`} label={glyph(look, all ? GLYPH.less : GLYPH.more, label)} variant="secondary" onPress={() => setFold($, `more:${id}`, !all)} />
  return <Button key={`more:${id}`} label={label} plain dimColor onPress={() => setFold($, `more:${id}`, !all)} />
}

// ---- the desktop's HTML sections (html.ts): a header strip, cards, and native buttons right under the card they act on

// Whether this surface draws the HTML sections: it draws SVG (every one but the terminal).
export const hasSvg = (ui: Ui, look: Look): boolean => look.svg && 'Svg' in ui && !!ui.Svg

// The glyph before a button's label, one single-tone set for the whole pane: a glyph is text, so it takes the button's own colour
// and state (primary, secondary, hover) as its label does. The terminal's buttons keep the label alone.
export const GLYPH = { all: '✓', use: '↵', recheck: '↻', copy: '⧉', memo: '⤓', more: '↓', less: '↑', edit: '✎', show: '↺', other: '⋯', detail: '≡' } as const
export const glyph = (look: Look, g: string, label: string): string => (look.svg ? `${g} ${label}` : label)

// The pane's width in px, as its cards are laid out.
export const paneW = (look: Look): number => paneWidth(look.width + 4)

// An HTML block as a picture laid out at the pane's width and scaled to the slot keeping its ratio (a 4096 px width capped at
// the slot, no height); `alt` is every text in it, one per line.
export function pic(ui: Ui, look: Look, b: Block, alt: (string | null | undefined)[]) {
  const { Svg } = ui as Ui & { Svg: NonNullable<Ui['Svg']> }
  const enter = look.enter ? look.enter.n++ * 50 : -1 // one after another, 50 ms apart
  return <Svg source={svgOf(b, paneW(look), enter)} alt={alt.filter((x): x is string => !!x).join('\n') || ' '} width={4096} />
}

// An empty or error state: a muted text in a card of its own, wrapped (never cut before its instruction).
export const emptyPic = (ui: Ui, look: Look, text: string) => pic(ui, look, emptyCard(text, paneW(look)), [text])

// The buttons of one group, in one wrapping row.
export function buttonRow(ui: Ui, buttons: (JSX.Element | null)[]) {
  const { Box } = ui
  return buttons.some(Boolean) ? <Box flexDirection="row" flexWrap="wrap" alignItems="center" gap="sm">{buttons}</Box> : null
}

// The desktop's pages, in the nav bar's order: each with the icon and tone its section's header strip draws, and its name.
export const NAV: readonly { id: string; icon: IconName; tone: Tone; label: string }[] = [
  { id: 'home', icon: 'house', tone: 'mint', label: 'Home' },
  { id: 'guide', icon: 'compass', tone: 'coral', label: 'Guide' },
  { id: 'resume', icon: 'bookmark', tone: 'blue', label: 'Resume' },
  { id: 'decisions', icon: 'scale', tone: 'teal', label: 'Decisions' },
  { id: 'spawns', icon: 'fork', tone: 'violet', label: 'Spawns' },
  { id: 'overrides', icon: 'sliders', tone: 'grey', label: 'Overrides' },
]

// The nav bar at the top of every page, one tight row in the middle: one icon per page, the tile its section's header draws, 32 px, the page shown filled
// in its tone. A Button holds text alone and a picture takes no press, so each icon has a plain Button laid over it, centred both
// ways, its label one figure space (blank, never collapsed; wider labels are cut with "…"): with the button's own padding and
// line it is about the 36 px tile, which is drawn 2 px low to sit on the button's centre — the press lands on the icon and the
// desktop's ghost fill matches the tile under the pointer. The shown page's Button is the one not dimmed.
const BLANK = '\u2007'
export function navBar($: EngineInterface, ui: Ui, look: Look, tab: string, tabs: string[]) {
  const { Box, Button, Svg } = ui as Ui & { Svg: NonNullable<Ui['Svg']> }
  return (
    <Box flexDirection="row" flexWrap="wrap" justifyContent="center" alignItems="center" gap="xs">
      {NAV.filter(n => tabs.includes(n.id)).map(n => (
        <Box key={`navitem:${n.id}`} position="relative" width={4} height={2} alignItems="center" justifyContent="center">
          <Svg source={tileSvg(n.icon, n.tone, 36, n.id === tab, 2)} alt={n.id === tab ? `${n.label}, shown` : n.label} width={36} />
          <Box position="absolute" top={0} left={0} right={0} bottom={0} alignItems="center" justifyContent="center">
            <Button key={`nav:${n.id}`} label={BLANK} plain dimColor={n.id !== tab} onPress={() => goTab($, n.id)} />
          </Box>
        </Box>
      ))}
    </Box>
  )
}

// A section on the desktop: its header strip (the icon on a tile in `tone`, the title, the summary at the right in `summaryTone`
// when it carries meaning) and its body, the cards and their buttons. Sections do not fold here: everything is in view.
export function htmlSection(ui: Ui, look: Look, head: { icon: IconName; tone: Tone; title: string; summary?: string | null; summaryTone?: Tone | null }, body: (JSX.Element | null)[]) {
  const { Box } = ui
  return (
    <Box flexDirection="column" rowGap="sm">
      {pic(ui, look, headerBlock(head.icon, head.tone, head.title, head.summary, head.summaryTone), [head.title, head.summary])}
      {body}
    </Box>
  )
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
    if (isNum(raw.task.raised)) task.raised = raw.task.raised
  }
  // Check all: a count and the text it hands over; anything else is dropped (older files have none).
  const all = isObj(raw.all) && isNum(raw.all.n) && isStr(raw.all.fill) && raw.all.fill.trim() ? { n: raw.all.n, fill: raw.all.fill } : null
  // Claude's last resolve, kept by the hook for Undo: needs its text, a ready argv and a timestamp.
  let lastResolved: Guide['last_resolved'] = null
  const lr = raw.last_resolved
  if (isObj(lr) && isStr(lr.text) && isNum(lr.ts)) {
    const unresolve = scriptArgv(lr.unresolve, ['memo.py', 'status.py'])
    if (unresolve) lastResolved = { text: lr.text, unresolve, ts: lr.ts }
  }
  const items = Array.isArray(raw.items) ? raw.items.map(cleanItem).filter((i): i is GuideItem => i !== null) : []
  return { line: raw.line, ts: isNum(raw.ts) ? raw.ts : 0, root: isStr(raw.root) ? raw.root : '', items, ctx, task, all, main: isStr(raw.main) ? raw.main : null, last_resolved: lastResolved }
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
  const needsFill = isStr(raw.needs_fill) && raw.needs_fill.trim() ? raw.needs_fill : null
  return { head: strOr(raw.head, ''), now: strsOf(raw.now), left: strsOf(raw.left), next: strsOf(raw.next), needs, needs_open: isNum(raw.needs_open) ? raw.needs_open : needs.length, needs_fill: needsFill, last: strsOf(raw.last) }
}

// One decision (the owner's or the Judge's): the time, the question and the answer are text; a malformed entry is dropped.
function cleanDecision(v: unknown): PaneDecision | null {
  if (!isObj(v) || !isStr(v.ts) || !isStr(v.q) || !isStr(v.a)) return null
  return { ts: v.ts, q: v.q, a: v.a, sid: strOr(v.sid, '') }
}

const DECISIONS_MAX = 50

// The decisions with each group type-checked and held to 50 rows; not an object: none (the card is not drawn).
function cleanDecisions(raw: unknown): PaneDecisions | null {
  if (!isObj(raw)) return null
  const group = (v: unknown): PaneDecision[] => (Array.isArray(v) ? v.map(cleanDecision).filter((d): d is PaneDecision => d !== null).slice(0, DECISIONS_MAX) : [])
  const you = group(raw.you)
  const judge = group(raw.judge)
  return { you, judge, n_you: isNum(raw.n_you) ? raw.n_you : you.length, n_judge: isNum(raw.n_judge) ? raw.n_judge : judge.length }
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
    resolved: v.resolved === true,
  }
}

function cleanModel(v: unknown): PaneModel | null {
  if (!isObj(v) || !isStr(v.model)) return null
  return { model: v.model, label: strOr(v.label, v.model), spawns: isNum(v.spawns) ? v.spawns : 0, usd: isNum(v.usd) ? v.usd : 0, pct: isNum(v.pct) ? v.pct : 0 }
}

function cleanSpawns(raw: unknown): PaneSpawns {
  const s = isObj(raw) ? raw : {}
  const live = Array.isArray(s.live) ? s.live.map(cleanLive).filter((r): r is PaneLive => r !== null) : []
  const rows = Array.isArray(s.rows) ? s.rows.map(cleanRow).filter((r): r is PaneRow => r !== null) : []
  const t = isObj(s.totals) ? s.totals : {}
  const byModel = Array.isArray(t.by_model) ? t.by_model.map(cleanModel).filter((m): m is PaneModel => m !== null) : []
  const totals: PaneTotals = { spawns: isNum(t.spawns) ? t.spawns : rows.length, tokens: isNum(t.tokens) ? t.tokens : 0, usd: isNum(t.usd) ? t.usd : 0, base_usd: isNum(t.base_usd) ? t.base_usd : 0, saved_pct: isNum(t.saved_pct) ? t.saved_pct : 0, open_fail: isNum(t.open_fail) ? t.open_fail : 0, base_label: strOr(t.base_label, ''), by_model: byModel }
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
      decisions: cleanDecisions(raw.decisions),
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
export async function fillPrompt($: EngineInterface, g: Guide | null, text: string) {
  const draft = (await $.prompt.read()).text.trim()
  const r = await $.prompt.fill({ text: draft ? `\n${text}` : text, mode: draft ? 'append' : 'replace' })
  if (r.isFilled) {
    if (g) await hideGuide($, g)
  }
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
      {/* the pane keeps the row until the guide changes: no Hide there (the band's row can be put away) */}
      {inPane ? null : <Button key="undo-hide" label="Hide" onPress={() => update($, dismissedTs, () => last.ts)} />}
    </Box>
  )
}

// The band's guide buttons: Use, Re-check, Memo, Copy, Hide (the pane's Guide has its own row, pane.tsx guideActions).
export function guideButtons($: EngineInterface, ui: Ui, g: Guide, v: GuideView, extra: unknown = null) {
  const { Box, Button } = ui
  const memoLook = v.done && v.memo ? ({ variant: 'primary' } as const) : {} // nothing else open: the memo is the next step
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={1} marginTop={1}>
      {v.done ? null : <Button key="use" label="Use" onPress={() => fillPrompt($, g, v.prompt)} />}
      {v.recheck ? <Button key="recheck" label="Re-check" onPress={() => fillPrompt($, g, v.recheck as string)} /> : null}
      {v.memo ? <Button key="memo" label="Memo" {...memoLook} onPress={() => fillPrompt($, g, '/abofles:memo')} /> : null}
      {v.done ? null : <Button key="copy" label="Copy" onPress={press => copyPrompt($, v.prompt, press.surface)} />}
      <Button key="hide" label="Hide" onPress={() => hideGuide($, g)} />
      {extra as never}
    </Box>
  )
}
