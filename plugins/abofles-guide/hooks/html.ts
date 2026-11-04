// Cards drawn as HTML and CSS inside an SVG picture, on the surfaces that draw `Svg` (every one but the terminal).
//
// The desktop draws a plain `Svg` (no `isInteractive`) as an <img> of the markup: no scrub on that road, so a <foreignObject>
// holding XHTML lays out with real CSS (flex, grid, ellipsis, line clamps, color-mix). It also writes the app's own `color` on the
// root <svg> when the markup names none, so the HTML inherits the theme's text colour and every grey and tint below is mixed from
// `currentColor`: one markup reads right in light and dark. The root is laid out at the pane's width as the hooks know it (its
// cells × CELL_PX) with a viewBox of that size, and the pane gives the image a 4096 px width capped at the slot and no height: the
// picture is scaled, keeping its ratio, to the slot's real width, so nothing is clipped or left blank and the text is drawn at
// about its own size. (A `width="100%"` root has no natural size: Chrome lays it out at its default 300 px and stretches that.)
// The height is fixed ahead, from the rows each block declares (`h`) and an estimate of a text's wrapped lines (estLines) at that
// same width; every text is clamped to the lines it was given, so a short estimate ends in "…", never spills.
//
// Plain data in, markup and height out, with no engine import: a card can be drawn and checked outside the engine. pane.tsx gives
// each block to an `Svg` (svgOf) and keeps the actions as native Buttons under it.

// The tones, by name: the dark-theme values. Text in a tone is mixed half and half with the theme's text colour, so it keeps >= 4.5:1
// on both themes (amber and green are the closest, 4.8:1 on white); a fill or a dot uses the tone as it is.
export const TONE = {
  red: '#e5675e',
  orange: '#e0763a',
  amber: '#e3a33b',
  green: '#63c174',
  blue: '#4a8cf0',
  violet: '#8b6cf0',
  teal: '#17a398',
  coral: '#d97757',
  mint: '#4fae8e',
  grey: '#8f8f8f',
} as const
export type Tone = keyof typeof TONE

// The theme keys and hex colours the cards are given, as tones.
const BY_COLOR: Record<string, Tone> = { error: 'red', warning: 'amber', success: 'green', suggestion: 'blue', claude: 'coral' }
export const toneOf = (color: string): Tone => BY_COLOR[color] ?? (Object.entries(TONE).find(([, hex]) => hex === color)?.[0] as Tone | undefined) ?? 'grey'

// The type scale, in px: every block's height is a sum of these, so the layout is known before the surface draws it.
export const LINE = 20 // body text: 14 px on a 20 px line, the size the pane's own text is drawn at
export const CAP = 16 // captions and labels: 11-12 px on a 16 px line
export const PAD = 12 // a section's padding, around and between its rows
export const GAP = 8 // between the rows of a list
// Every length below is on one 4 px scale (4, 8, 12, 16); inside a picture px is the unit (no reader font setting reaches it).

const FONT = '-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif'
const mix = (c: string, pct: number) => `color-mix(in srgb,${c} ${pct}%,transparent)`
const tones = Object.entries(TONE)
  .map(([n, hex]) => `.t-${n}{--c:${hex}}`)
  .join('')

// The style sheet every card shares. No `<` or `&` in it (it sits in XML).
const CSS = [
  `.root{box-sizing:border-box;width:100%;height:100%;padding:1px;font:14px/${LINE}px ${FONT};-webkit-font-smoothing:antialiased;color:inherit;overflow:hidden}`,
  // no app colour written on the root (a surface without one): the theme's text colour by the media query
  'svg:not([color]) .root{color:#1f1e1d}@media (prefers-color-scheme:dark){svg:not([color]) .root{color:#ececec}}',
  '.root *{box-sizing:border-box;margin:0;padding:0;min-width:0}',
  `.card{border:1px solid ${mix('currentColor', 14)};border-radius:10px;background:${mix('currentColor', 3)};overflow:hidden}`,
  `.sec{padding:${PAD}px}.sec+.sec{border-top:1px solid ${mix('currentColor', 10)}}`,
  `.col{display:flex;flex-direction:column;gap:${GAP}px}`,
  `.row{display:flex;align-items:center;gap:8px;height:${LINE}px}`,
  '.grow{flex:1 1 auto}.fix{flex:none}',
  '.row .grow{text-align:start}', // a line keeps the column's leading edge (dir=auto still orders an Arabic line's words)
  '.one{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
  `.clamp{display:-webkit-box;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}`,
  '.dim{opacity:.7}.faint{opacity:.62}', // 6:1 and 4.6:1 on white; more in dark
  `.cap{font-size:11px;line-height:${CAP}px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;opacity:.66;white-space:nowrap}`,
  `.small{font-size:12px;line-height:${CAP}px}`,
  '.num{font-variant-numeric:tabular-nums;white-space:nowrap}',
  '.b{font-weight:600}',
  // a tinted pill: a priority, a status, a count
  `.pill{flex:none;display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:10px;font-size:11px;font-weight:650;letter-spacing:.04em;text-transform:uppercase;background:${mix('var(--c)', 17)};color:color-mix(in srgb,var(--c) 50%,currentColor)}`,
  '.dot{flex:none;width:8px;height:8px;border-radius:50%;background:var(--c)}',
  '.ink{color:color-mix(in srgb,var(--c) 50%,currentColor)}',
  // a round badge with a glyph in it (✓, !, …)
  `.badge{flex:none;display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;font-size:12px;font-weight:700;background:${mix('var(--c)', 18)};color:color-mix(in srgb,var(--c) 50%,currentColor)}`,
  // facts held between two edges: the label at the leading edge, muted; the value at the trailing edge
  `.fact{display:flex;align-items:center;justify-content:space-between;gap:12px;height:${LINE}px}`,
  '.fact .k{flex:0 1 auto;opacity:.7}',
  '.fact .v{flex:0 1 auto;text-align:end;font-variant-numeric:tabular-nums}',
  // a row is one line at any width: its parts never wrap, the ones that may shrink end in "…"
  '.row>*,.fact>*{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row>.fix,.row>.dot,.row>.pill,.row>.nb,.row>.badge,.row>.sw{overflow:visible}',
  `.track{height:4px;border-radius:2px;background:${mix('currentColor', 12)};overflow:hidden}`,
  '.tuck{margin-top:-4px}', // a meter or a note sits 4 px under its fact, not a whole row gap
  '.fill{height:100%;border-radius:2px;background:var(--c)}',
  // a section's header strip: the icon on a tinted tile, the title, the summary at the right; its text on the card content's inset
  `.head{display:flex;align-items:center;gap:8px;height:24px;padding-inline:${PAD + 1}px}`,
  `.htile{flex:none;display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:7px;background:${mix('var(--c)', 16)};color:color-mix(in srgb,var(--c) 50%,currentColor)}`,
  '.htile svg{display:block}',
  `.head.sub{height:${CAP}px}`, // a small heading above a group of cards (subhead)
  '.title{flex:0 1 auto;font-size:15px;line-height:20px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
  // a row whose lead (a dot, a number, a bullet, an arrow) sits on the first line of a text that may wrap
  '.lead{display:flex;align-items:flex-start;gap:8px}',
  `.nb{flex:none;display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;padding:0 6px;border-radius:10px;font-size:12px;font-weight:650;font-variant-numeric:tabular-nums;background:${mix('var(--c)', 17)};color:color-mix(in srgb,var(--c) 50%,currentColor)}`,
  '.bul{flex:none;width:6px;height:6px;margin:7px 0;border-radius:50%;background:currentColor;opacity:.45}',
  '.arrow{flex:none;width:12px;opacity:.5}',
  `.hair{height:1px;background:${mix('currentColor', 9)}}`,
  '.big{font-size:16px;line-height:20px;font-weight:650;white-space:nowrap}',
  `.bar{display:flex;gap:2px;height:6px}.bar i{display:block;flex:none;height:6px;border-radius:3px;background:var(--c)}.bar .rest{flex:1 1 auto;background:${mix('currentColor', 12)}}`,
  '.sw{flex:none;width:8px;height:8px;border-radius:2px;background:var(--c)}',
  '.mt{font-size:12px;line-height:16px;height:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mt .q{opacity:.7}',
  '.word{font-weight:650;letter-spacing:.03em}',
  // a receipt detail's kind (check, open, next, flow) as a small word in its tone, in a column of its own
  '.lbl{flex:none;width:44px;font-size:10px;line-height:16px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:color-mix(in srgb,var(--c) 50%,currentColor)}',
  '.mt2{display:-webkit-box;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-size:12px;line-height:16px}.mt2 .q{opacity:.7}',
  '.pad{padding-inline-start:16px}',
  '.c1{flex:none;width:28px;text-align:end}.c2{flex:none;width:56px;text-align:end}.c3{flex:none;width:36px;text-align:end}',
  // a page's cards slide in when the person moves to it (a short ease-out, one after another); none for reduced motion
  '.enter{animation:enter .26s cubic-bezier(.2,.8,.2,1) both}@keyframes enter{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}',
  '@media (prefers-reduced-motion:reduce){.enter{animation:none}}',
  tones,
].join('')

// Text for XML: the five marks escaped; control bytes, lone surrogates and U+FFFE/FFFF dropped (any one of them breaks the picture's XML).
export const esc = (t: string): string =>
  t
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\ufffe\uffff]|[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g, '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

// A block of a card: its markup and its height in px.
export type Block = { html: string; h: number }

// The pane's width in px from its width in cells (a cell is 1ch of the pane's body font: about 9 px, read off the app), and the room a text has
// inside a card's section (borders and padding off).
export const CELL_PX = 9
export const paneWidth = (bodyColumns: number): number => Math.max(220, Math.round(bodyColumns * CELL_PX))
export const textRoom = (paneW: number, indent = 0): number => Math.max(120, paneW - 4 - 2 * PAD - indent) // the root's 1 px padding and the card's border, each side

// A character's advance in hundredths of an em in the system UI face (SF Pro Text, measured at 14 px: larger sizes switch to the
// tighter Display cut): printable ASCII by code, then the
// marks the memo and the hooks write; other scripts by range. Close enough to count lines, never to clip by.
const ASCII_EM = [
  27, 30, 47, 62, 62, 91, 70, 29, 37, 37, 46, 62, 29, 46, 29, 29, 62, 45, 59, 62, 63, 61, 63, 58, 63, 63, 29, 29, 62, 62, 62, 50, 91, 66, 65, 71, 72, 58, 56, 74,
  73, 26, 53, 65, 56, 86, 73, 76, 62, 76, 64, 63, 62, 73, 66, 96, 67, 64, 65, 37, 29, 37, 62, 54, 49, 54, 60, 55, 60, 56, 35, 60, 58, 24, 24, 53, 24, 86, 57, 58,
  60, 60, 38, 50, 35, 57, 53, 76, 51, 53, 53, 37, 25, 37, 62,
]
const MARK_EM: Record<string, number> = { '«': 65, '»': 65, '·': 29, '×': 62, '–': 57, '—': 87, '‘': 29, '’': 29, '“': 45, '”': 45, '•': 46, '…': 79, '→': 90 }
function em(ch: string): number {
  const c = ch.codePointAt(0) ?? 0
  if (c >= 32 && c < 127) return ASCII_EM[c - 32] / 100
  if (MARK_EM[ch] !== undefined) return MARK_EM[ch] / 100
  if (/[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]/.test(ch)) return 0.43 // joined letters run narrower than alone (measured 0.42)
  if (/[\u2e80-\u9fff\uac00-\ud7af\uff00-\uffef]/.test(ch)) return 1
  if (/\p{Extended_Pictographic}/u.test(ch)) return 1.25
  return 0.6
}

// How many lines `text` wraps to in `room` px at `size` px (`bold`: semibold, 4% wider): the words laid greedily on lines 1% short
// of the room, as the surface wraps them (a word that does not fit starts the next line; a word longer than a line breaks).
// Never less than 1.
export function estLines(text: string, room: number, size = 14, bold = false): number {
  const max = Math.max(40, room * 0.99)
  size = bold ? size * 1.04 : size
  const sp = em(' ') * size
  let lines = 1
  let x = 0
  // a hyphen is a break too: `purpose-bound` may end a line at `purpose-`, with no space before `bound`
  const parts = text.split(/\s+/).filter(Boolean).flatMap(word => word.split(/(?<=-)(?=.)/).map((p, i) => ({ p, glued: i > 0 })))
  for (const { p, glued } of parts) {
    let w = 0
    for (const ch of p) w += em(ch) * size
    const gap = glued ? 0 : sp
    if (x === 0) x = w
    else if (x + gap + w <= max) x += gap + w
    else {
      lines++
      x = w
    }
    while (x > max) {
      lines++
      x -= max
    }
  }
  return lines
}

// A text clamped to `lines` lines, its block exactly that tall. `cls` adds classes (dim, b, small); `dir="auto"` lets an Arabic
// line run right to left.
export function clamped(text: string, lines: number, cls = '', lineH = LINE): Block {
  const h = lines * lineH
  return { html: `<div class="clamp ${cls}" dir="auto" style="-webkit-line-clamp:${lines};height:${h}px">${esc(text)}</div>`, h }
}

// Blocks stacked in a column with `gap` px between them.
export function stack(blocks: (Block | null)[], gap = GAP): Block {
  const shown = blocks.filter((b): b is Block => b !== null)
  if (shown.length === 0) return { html: '', h: 0 }
  return {
    html: `<div class="col" style="gap:${gap}px">${shown.map(b => b.html).join('')}</div>`,
    h: shown.reduce((n, b) => n + b.h, 0) + gap * (shown.length - 1),
  }
}

// A card: its sections one under another, a hairline between each.
export function cardOf(sections: (Block | null)[]): Block {
  const shown = sections.filter((b): b is Block => b !== null && b.h > 0)
  return {
    html: `<div class="card">${shown.map(s => `<div class="sec">${s.html}</div>`).join('')}</div>`,
    h: 2 + shown.reduce((n, s) => n + s.h + 2 * PAD, 0) + (shown.length - 1),
  }
}

// A fact: a label and its value held between two edges (no divider needed), an optional meter under it (`pct` of the track, in
// `tone`) and an optional muted line under that (`sub`). `tone` colours the value where it carries meaning (a budget at 0).
// A meter or a note is tucked 4 px under its fact (`.tuck` takes 4 px back from the row gap); its `h` counts that.
export type Fact = { label: string; value: string; tone?: Tone; meter?: { pct: number; tone: Tone }; sub?: string }
export function facts(list: Fact[]): Block {
  const parts: Block[] = []
  for (const f of list) {
    parts.push({ html: `<div class="fact"><span class="k">${esc(f.label)}</span><span class="v${f.tone ? ` ink t-${f.tone}` : ''}" dir="auto">${esc(f.value)}</span></div>`, h: LINE })
    if (f.meter) parts.push({ html: `<div class="track tuck"><div class="fill t-${f.meter.tone}" style="width:${Math.max(0, Math.min(100, f.meter.pct)).toFixed(1)}%"></div></div>`, h: 4 - 4 })
    if (f.sub) parts.push({ html: `<div class="small dim one tuck" dir="auto">${esc(f.sub)}</div>`, h: CAP - 4 })
  }
  return stack(parts, GAP)
}

// The SVG document of a block laid out `w` px wide (paneWidth) and exactly the block's height (the root's 1 px padding around
// it), with a viewBox of that size so the surface scales it to the slot keeping its ratio.
// `enter` >= 0: the picture slides in after that many ms (a page just opened); below 0, it is drawn still.
export function svgOf(b: Block, w: number, enter = -1): string {
  const h = b.h + 2
  const anim = enter >= 0 ? ` enter" style="animation-delay:${Math.min(enter, 240)}ms` : ''
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
    `<style><![CDATA[${CSS}]]></style>` +
    `<foreignObject x="0" y="0" width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" class="root${anim}">${b.html}</div></foreignObject>` +
    '</svg>'
  )
}

// ---- Guide

// A guide item as the card shows it: the text, its priority word (urgent, high, medium, …) and that priority's tone.
export type CardItem = { text: string; word: string; tone: Tone }

export type GuideIn = {
  paneW: number // the pane's width in px (paneWidth)
  top: CardItem | null // the item Use hands over; null: nothing open
  rest: CardItem[] // the other open items shown (the pane cuts the list)
  clear: { title: string; text: string } | null // nothing open: "All clear" or "Next from the memo", and its text
  facts: Fact[]
}

// The most lines the top item takes; the whole text is on the detail page.
export const TOP_LINES = 4

// The Guide card: "Next up" with the top item's priority pill and its text; the other open items, one line each; the numbers as
// two-edge facts. `more` says a text was cut (the pane then offers Full details).
export function guideBlock(g: GuideIn): { block: Block; more: boolean } {
  const room = textRoom(g.paneW)
  let more = false
  const sections: (Block | null)[] = []
  if (g.top) {
    const need = estLines(g.top.text, room * 0.94) // the same 6% short room as fit(): a text that may need one more line counts as cut
    more = need > TOP_LINES
    const lines = Math.min(need, TOP_LINES)
    const head: Block = {
      html: `<div class="row"><span class="cap grow">Next up</span><span class="pill t-${g.top.tone}">${esc(g.top.word)}</span></div>`,
      h: LINE,
    }
    sections.push(stack([head, clamped(g.top.text, lines)], 8))
  } else if (g.clear) {
    const head: Block = {
      html: `<div class="row"><span class="badge t-green">✓</span><span class="b">${esc(g.clear.title)}</span></div>`,
      h: LINE,
    }
    // the text starts under the title, not under the badge (20 px badge + 8 px gap)
    const need = g.clear.text ? estLines(g.clear.text, (room - 28) * 0.94) : 0
    more = need > 3
    const text = g.clear.text ? clamped(g.clear.text, Math.min(need, 3), 'dim') : null
    sections.push(stack([head, text ? { ...text, html: `<div style="padding-inline-start:28px">${text.html}</div>` } : null], 4))
  }
  if (g.rest.length > 0) {
    const rows = g.rest.map(
      (it): Block => ({
        html: `<div class="row"><span class="dot t-${it.tone}"></span><span class="grow one dim" dir="auto">${esc(it.text)}</span><span class="small faint num fix">${esc(it.word)}</span></div>`,
        h: LINE,
      }),
    )
    sections.push(stack([{ html: '<div class="cap">Also open</div>', h: CAP }, ...rows], GAP))
  }
  if (g.facts.length > 0) sections.push(facts(g.facts))
  return { block: cardOf(sections), more }
}

// ---- the parts every card uses

// Lucide-style line icons (24 grid, round caps), drawn in `currentColor` so one asset follows its tile's tone.
export const ICONS = {
  house: '<path d="M15 21v-8a1 1 0 0 0-1-1h-2a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
  bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
  fork: '<circle cx="12" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9"/><path d="M12 12v3"/>',
  scale: '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
  sliders: '<path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  receipt: '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8M12 6v2M12 16v2"/>',
} as const
export type IconName = keyof typeof ICONS
const iconSvg = (name: IconName, size = 14, stroke = 2) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`

// The tallest card one picture holds: the surface takes a height of 4096 px at most, so a long list goes on in a second card.
const CARD_MAX = 3000 // a picture past ~1.1× its laid-out width would pass 4096 px high at 3600

// A section's header: the icon on a tile in `tone`, the title, and the summary at the right — a pill where its tone means
// something, else muted. It sits above the section's cards, its text on their content's inset.
export function headerBlock(icon: IconName, tone: Tone, title: string, summary?: string | null, summaryTone?: Tone | null): Block {
  const right = !summary ? '' : summaryTone ? `<span class="pill t-${summaryTone}">${esc(summary)}</span>` : `<span class="dim num small">${esc(summary)}</span>`
  return { html: `<div class="head"><span class="htile t-${tone}">${iconSvg(icon)}</span><span class="title grow">${esc(title)}</span>${right}</div>`, h: 24 }
}

// A section's icon tile alone, as the header strip draws it (the icon in `tone` on a tint of it), as a picture `size` px square:
// the nav bar's items. `on` (the page shown) fills the tile with the tone and draws the icon white on it — outline at rest, fill
// for the active one.
// `dy` px of room above the tile: the desktop sets a picture on its line a little high, so the nav bar drops the tile to centre
// it on the button laid over it.
export function tileSvg(icon: IconName, tone: Tone, size = 32, on = false, dy = 0): string {
  const t = size - 2
  const fill = on ? 'background:color-mix(in srgb,var(--c) 80%,#000);color:#fff;box-shadow:0 1px 3px rgba(0,0,0,.25)' : ''
  return svgOf({ html: `<div style="padding-top:${dy}px"><span class="htile t-${tone}" style="width:${t}px;height:${t}px;border-radius:10px;${fill}">${iconSvg(icon, Math.round(t * 0.56), on ? 2.25 : 2)}</span></div>`, h: t + dy }, size)
}

// A group's caption inside a card, with an optional count at the right (a pill in `tone`, else muted).
export function capRow(text: string, right?: string | null, tone?: Tone | null): Block {
  const r = !right ? '' : tone ? `<span class="nb t-${tone}">${esc(right)}</span>` : `<span class="small dim num">${esc(right)}</span>`
  return { html: `<div class="row"><span class="cap grow">${esc(text)}</span>${r}</div>`, h: LINE }
}

// Rows with a hairline between each (the line on the 4 px scale: half the gap above it, half below).
export function ruledRows(rows: Block[]): Block {
  const parts: Block[] = []
  rows.forEach((r, i) => {
    if (i > 0) parts.push({ html: '<div class="hair"></div>', h: 1 })
    parts.push(r)
  })
  return stack(parts, GAP)
}

// Cards for a list too long for one picture: the head and the rows, split where a card would pass CARD_MAX.
export function listCards(head: Block | null, rows: Block[], tail: Block | null = null): Block[] {
  const cards: Block[] = []
  let cur: Block[] = []
  let h = head ? head.h : 0
  const flush = (first: boolean) => {
    if (cur.length === 0 && !(first && head)) return
    cards.push(cardOf([stack([first ? head : null, cur.length ? ruledRows(cur) : null], GAP)]))
    cur = []
    h = 0
  }
  for (const r of rows) {
    if (h + r.h + 2 * GAP + 1 > CARD_MAX && cur.length > 0) flush(cards.length === 0)
    cur.push(r)
    h += r.h + 2 * GAP + 1
  }
  flush(cards.length === 0)
  if (tail && cards.length > 0) {
    const last = cards.pop() as Block
    cards.push({ html: last.html.replace(/<\/div>$/, `<div class="sec">${tail.html}</div></div>`), h: last.h + tail.h + 2 * PAD + 1 })
  }
  return cards
}

// A muted empty state in a card of its own, wrapped to three lines at most.
export function emptyCard(text: string, paneW: number): Block {
  return cardOf([clamped(text, Math.min(estLines(text, textRoom(paneW) * 0.94), 3), 'dim')])
}

// A text clamped to its estimated lines, at most `max` (the whole text is on the section's detail page). The estimate runs on a
// room 6% short: a text that may need one more line gets it, so a short estimate never hides a last word.
function fit(text: string, room: number, max: number, cls = ''): Block {
  return clamped(text, Math.min(estLines(text, room * 0.94, 14, /\bb\b/.test(cls)), max), cls)
}

// The same at the small size (12 px on a 16 px line, muted); SF Pro Text tracks wider at 12 px than at 14 (+5%).
function fitSmall(text: string, room: number, max: number): Block {
  return clamped(text, Math.min(estLines(text, (room * 0.94) / 1.05, 12), max), 'small dim', CAP)
}

// A row with a lead on its text's first line: a dot, a number, a bullet, an arrow.
function leadRow(lead: string, leadW: number, text: string, room: number, max: number, cls = ''): Block {
  const f = fit(text, room - leadW - GAP, max, cls)
  return { html: `<div class="lead">${lead}<div class="grow">${f.html}</div></div>`, h: f.h }
}

// ---- Resume

// A receipt's detail kinds, each a label in its own tone: how it was checked, what is open, what comes next, the steps run.
// `done` is not among them: it is the receipt's headline.
const DETAIL_TONE: Record<string, Tone> = { check: 'blue', open: 'amber', next: 'violet', workflow: 'teal', why: 'grey' }
const DETAIL_WORD: Record<string, string> = { workflow: 'flow' }
const LABEL_W = 44

const kindOf = (d: string): { kind: string; text: string } => {
  const m = /^([a-z][a-z ]{1,14}):\s*(.*)$/i.exec(d)
  return m ? { kind: m[1].toLowerCase(), text: m[2] } : { kind: '', text: d }
}

// A receipt detail: its kind as a small word in its tone, in a column of its own (no fill: nine filled labels in one list would
// all shout), the text beside it, muted, two lines at most.
function detailRow(kind: string, text: string, room: number): Block {
  const tw = kind ? LABEL_W + GAP : 0
  const f = fitSmall(text, room - tw, 2)
  const lead = kind ? `<span class="lbl t-${DETAIL_TONE[kind] ?? 'grey'}">${esc(DETAIL_WORD[kind] ?? kind)}</span>` : ''
  return { html: `<div class="lead">${lead}<div class="grow">${f.html}</div></div>`, h: f.h }
}

export type Receipt = { time: string; spawns: string | null; usd: string | null; saved: string | null; text: string; details: string[] }

// A receipt as a card of its own: the time and the cost on two edges; what was done as its headline (body text, two lines, then
// its Full details); the spawns and the saving; then, under a hairline, the other details as quiet labelled rows.
export function receiptCard(x: Receipt, paneW: number): Block {
  const room = textRoom(paneW)
  const kinds = x.details.map(kindOf)
  const done = kinds.find(k => k.kind === 'done')
  const headline = done?.text ?? (x.text || kinds[0]?.text || '')
  const rest = kinds.filter(k => k !== done && (done || x.text || k !== kinds[0]))
  const top: Block = { html: `<div class="fact"><span class="cap k">${esc(x.time)}</span><span class="v">${esc(x.usd ?? '')}</span></div>`, h: LINE }
  const stat: Block | null = x.spawns ? { html: `<div class="mt"><span class="q">${esc(x.spawns)}</span>${x.saved ? ` <span class="q">·</span> <span class="ink t-green">${esc(x.saved)} saved</span>` : ''}</div>`, h: CAP } : null
  const head = stack([top, headline ? fit(headline, room, 2) : null, stat], 4)
  const rows = rest.map(k => detailRow(k.kind, k.text, room))
  return cardOf([head, rows.length ? stack(rows, GAP) : null])
}

// A small heading above a group of cards, on their content's inset.
export function subhead(text: string): Block {
  return { html: `<div class="head sub"><span class="cap grow">${esc(text)}</span></div>`, h: CAP }
}

export type ResumeIn = {
  paneW: number
  now: string[]
  next: string[]
  needs: { n: string; text: string }[] // the ones shown
  needsOpen: number
  left: string[] // the ones shown
  facts: Fact[] // Session, Memo saved, Away
}

// The Resume cards: where the work stands (Now, Next), what needs the owner (numbered), what is left, and the memo's facts. Each
// is a card of its own so its buttons sit right under it; the receipts are cards of their own (receiptCard).
export function resumeBlocks(r: ResumeIn): { status: Block | null; needs: Block | null; left: Block | null; facts: Block | null } {
  const room = textRoom(r.paneW)
  const lines = (title: string, list: string[]) => (list.length === 0 ? null : stack([capRow(title), ...list.map(t => fit(t, room, 3))], 4))
  const now = lines('Now', r.now)
  const next = lines('Next', r.next)
  const status = now || next ? cardOf([now, next]) : null
  const needs =
    r.needs.length === 0
      ? null
      : cardOf([stack([capRow('Needs you', String(r.needsOpen), 'amber'), ruledRows(r.needs.map(n => leadRow(`<span class="nb t-amber">${esc(n.n)}</span>`, 20, n.text, room, 2)))], GAP)])
  const left = r.left.length === 0 ? null : cardOf([stack([capRow('Left'), ...r.left.map(t => leadRow('<span class="bul"></span>', 6, t, room, 2))], 4)])
  return { status, needs, left, facts: r.facts.length > 0 ? cardOf([facts(r.facts)]) : null }
}

// ---- Spawns

export type SpawnRow = { tone: Tone; side: string; desc: string; cost: string; meta: string; word: string; wordTone: Tone | null }
export type SpawnsIn = {
  paneW: number
  saved: string // "54% saved"
  versus: string // "$0.41 of $0.90 on Opus 5.5"
  models: { label: string; tone: Tone; spawns: number; usd: string; pct: number }[]
  facts: Fact[] // Tokens, Open FAIL
  live: SpawnRow[]
  days: { label: string; rows: SpawnRow[] }[] // the history rows shown, newest first, by day
  updated: string | null // "Updated 15:30 · refreshes when a turn ends"
}

// A spawn: its status dot, the side in semibold and the cost at the right; the ask under it (two lines; the whole ask is on the
// detail page); the muted meta line (time, model, tokens) with the status word in its tone.
function spawnBlock(x: SpawnRow, room: number): Block {
  const top: Block = { html: `<div class="row"><span class="dot t-${x.tone}"></span><span class="b grow one" dir="auto">${esc(x.side || '?')}</span>${x.cost ? `<span class="dim num fix">${esc(x.cost)}</span>` : ''}</div>`, h: LINE }
  const d = x.desc ? fit(x.desc, room - 16, 2) : null
  const word = x.word ? ` · <span class="word${x.wordTone ? ` ink t-${x.wordTone}` : ''}">${esc(x.word)}</span>` : ''
  // the meta line wraps to a second line rather than cutting the tokens or the status word
  const metaText = [x.meta, x.word].filter(Boolean).join(' · ')
  const n = Math.min(2, estLines(metaText, room - 16, 12))
  const meta: Block | null = metaText
    ? { html: `<div class="mt2 pad" style="-webkit-line-clamp:${n};height:${n * CAP}px"><span class="q">${esc(x.meta)}</span>${x.meta ? word : word.replace(/^ · /, '')}</div>`, h: n * CAP }
    : null
  return stack([top, d ? { ...d, html: `<div class="pad">${d.html}</div>` } : null, meta], 4)
}

export function spawnsBlocks(s: SpawnsIn): { spend: Block; running: Block | null; history: Block[] } {
  const room = textRoom(s.paneW)
  const row = (x: SpawnRow) => spawnBlock(x, room)
  // the saving as the headline, what it compares under it: the full line at any width
  const top = stack([{ html: `<div class="big">${esc(s.saved)}</div>`, h: 20 }, { html: `<div class="mt"><span class="q num">${esc(s.versus)}</span></div>`, h: CAP }], 2)
  const bar: Block | null =
    s.models.length === 0
      ? null
      : { html: `<div class="bar">${s.models.filter(m => m.pct > 0).map(m => `<i class="t-${m.tone}" style="width:calc(${Math.max(1, m.pct).toFixed(1)}% - 2px)"></i>`).join('')}<i class="rest"></i></div>`, h: 6 }
  const legend = s.models.map(
    (m): Block => ({
      html: `<div class="row"><span class="sw t-${m.tone}"></span><span class="grow one">${esc(m.label)}</span><span class="c1 dim num">${m.spawns}</span><span class="c2 dim num">${esc(m.usd)}</span><span class="c3 num">${m.pct}%</span></div>`,
      h: LINE,
    }),
  )
  const spend = cardOf([stack([top, bar, ...legend], GAP), s.facts.length > 0 ? facts(s.facts) : null])
  const running = s.live.length === 0 ? null : cardOf([stack([capRow('Running', String(s.live.length), 'blue'), ruledRows(s.live.map(row))], GAP)])
  const rows: Block[] = []
  s.days.forEach(d => {
    d.rows.forEach((x, i) => rows.push(i === 0 && d.label ? stack([{ html: `<div class="cap faint">${esc(d.label)}</div>`, h: CAP }, row(x)], GAP) : row(x)))
  })
  const un = s.updated ? Math.min(2, estLines(s.updated, room, 12)) : 0
  const foot: Block | null = s.updated ? { html: `<div class="mt2" style="-webkit-line-clamp:${un};height:${un * CAP}px"><span class="q">${esc(s.updated)}</span></div>`, h: un * CAP } : null
  const history = rows.length === 0 ? [] : listCards(capRow('History', 'newest first'), rows, foot)
  return { spend, running, history }
}

// ---- Decisions

export type DecisionRow = { when: string; q: string; a: string; note: boolean }

// A decision: its time small and muted, the question, then the answer after an arrow in semibold — what was decided reads at a
// glance. A note is its text alone.
export function decisionCards(title: string, n: number, rows: DecisionRow[], paneW: number): Block[] {
  const room = textRoom(paneW)
  const head = capRow(title, String(n))
  if (rows.length === 0) return [cardOf([stack([head, { html: '<div class="dim">No decisions yet</div>', h: LINE }], GAP)])]
  const blocks = rows.map(d =>
    stack(
      [
        { html: `<div class="mt"><span class="q num">${esc(d.when)}</span></div>`, h: CAP },
        fit(d.note ? d.a : d.q, room, 2),
        d.note ? null : leadRow('<span class="arrow">→</span>', 12, d.a, room, 2, 'b'),
      ],
      4,
    ),
  )
  return listCards(head, blocks)
}

// ---- Overrides

// The keys set in a CLAUDE.md, the value and where it is set held at the right; a muted line on the rest.
export function overridesBlock(rows: { key: string; value: string; where: string }[], note: string): Block {
  const list = rows.map(
    (k): Block => ({
      html: `<div class="fact"><span class="k one">${esc(k.key)}</span><span class="row" style="gap:8px;min-width:0"><span class="b one" dir="auto">${esc(k.value)}</span><span class="pill t-grey">${esc(k.where)}</span></span></div>`,
      h: LINE,
    }),
  )
  return cardOf([list.length > 0 ? ruledRows(list) : null, { html: `<div class="small dim">${esc(note)}</div>`, h: CAP }])
}

// ---- Home

export type HomeIn = {
  paneW: number
  top: CardItem | null // the Guide's top item
  clear: { title: string; text: string } | null // nothing open: what the memo says next
  glance: Fact[] // the numbers that matter now, from every section
  now: string | null
  next: string | null
  decision: DecisionRow | null // the newest decision
  receipt: { time: string; text: string } | null // the newest receipt: what was done
}

// The Home page: the one thing to do next (the Guide's top item), the numbers that matter at a glance, where the work stands, and
// the latest decision and receipt — each section's most important line, so the other pages are for the detail.
export function homeBlocks(h: HomeIn): { next: Block; more: boolean; glance: Block | null; where: Block | null; latest: Block | null } {
  const room = textRoom(h.paneW)
  const g = guideBlock({ paneW: h.paneW, top: h.top, rest: [], clear: h.clear, facts: [] })
  const glance = h.glance.length ? cardOf([stack([capRow('At a glance'), facts(h.glance)], GAP)]) : null
  const line = (title: string, t: string | null) => (t ? stack([capRow(title), fit(t, room, 2)], 4) : null)
  const now = line('Now', h.now)
  const next = line('Next', h.next)
  const where = now || next ? cardOf([now, next]) : null
  const dec = h.decision
    ? stack(
        [
          capRow('Last decision', h.decision.when),
          fit(h.decision.note ? h.decision.a : h.decision.q, room, 2),
          h.decision.note ? null : leadRow('<span class="arrow">→</span>', 12, h.decision.a, room, 1, 'b'),
        ],
        4,
      )
    : null
  const rcpt = h.receipt ? stack([capRow('Last receipt', h.receipt.time), fit(h.receipt.text, room, 2)], 4) : null
  const latest = dec || rcpt ? cardOf([dec, rcpt]) : null
  return { next: g.block, more: g.more, glance, where, latest }
}
