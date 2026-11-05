import { expect, mock, test } from 'claude-code/testing'

import { fmtWhen, headParts, receiptOf } from './pane'
import { COLOR_PAIRS, shortHash } from './shared'

const SURFACES = ['terminal', 'desktop'] as const
const NOW = 1_700_000_000 // epoch seconds the mocked clock stands at
const hhmm = (ts: number): string => `${String(new Date(ts * 1000).getHours()).padStart(2, '0')}:${String(new Date(ts * 1000).getMinutes()).padStart(2, '0')}` // local time, as the card draws a live start

const PANE_PROPS = { title: 'Abo Fles', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} } as const
const BAND_PROPS = { hasSurvey: false, isWorking: false, maxRows: 4 } as const
const RUN = { args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } } as const

type It = { p: string; text: string; fill: string; recheck?: string | null; id?: string }
const item = (over: Partial<It> = {}): It => ({ p: '🟡', id: 'esc:a', text: 'escalate it', fill: 'do it', recheck: null, ...over })
const guideOf = (items: It[], more: object = {}) => ({ line: `🧭 ${items.map(i => `${i.p} ${i.text}`).join(' · ')}`, ts: 1, root: '/proj', items, ctx: null, task: null, main: null, ...more })

const PLACES = { guide: 'pane', resume: 'pane', spawns: 'pane' }
const ROWS = [
  { ts: NOW - 900, side: 'Read', model: 'haiku', effort: 'low', topic: 'T1', tier: 'T1', status: 'done', confidence: 'high', tokens: 12000, usd: 0.01, base_usd: 0.1, description: 'read the docs', verdict: null, task: 'Fix login' },
  { ts: NOW - 600, side: 'Work', model: 'sonnet', effort: 'medium', topic: 'T2', tier: 'T2', status: 'done', confidence: 'medium', tokens: 80000, usd: 0.4, base_usd: 0.8, description: 'patch it', verdict: 'PASS', task: 'Fix login' },
  { ts: NOW - 300, side: 'Verify', model: 'opus', effort: 'high', topic: 'T3', tier: 'T3', status: 'done', confidence: 'low', tokens: null, usd: null, base_usd: null, description: 'check it', verdict: null, task: null },
]
const panePayload = (over: object = {}) => ({
  v: 1,
  ts: 1,
  root: '/proj',
  sid: 'sid-pane',
  places: PLACES,
  resume: { head: '📍 Resume · memo 2026-10-20 09:00 · session sid-pane · now written 2026-10-20 09:00 from receipt', now: ['wiring the pane'], left: ['tests'], next: ['ship it'], needs: [{ n: 1, text: 'pick the cap' }, { n: 3, text: 'name the key' }], needs_open: 2, last: ['wrote cards'] },
  spawns: {
    live: [{ side: 'Work', model: 'sonnet', effort: 'high', description: 'build the card', ts: NOW - 125 }],
    rows: ROWS,
    totals: { spawns: 3, tokens: 92000, usd: 0.41, base_usd: 0.9, saved_pct: 54, open_fail: 1, base_label: 'Opus 5.5', by_model: [{ model: 'haiku', label: 'Haiku 5.5', spawns: 1, usd: 0.01, pct: 2 }, { model: 'sonnet', label: 'Sonnet 5.5', spawns: 1, usd: 0.4, pct: 98 }, { model: 'opus', label: 'Opus 5.5', spawns: 1, usd: 0, pct: 0 }] },
  },
  overrides: {
    files: { project: '/proj/CLAUDE.md', user: '/home/.claude/CLAUDE.md' },
    keys: [
      { key: 'Receipt', kind: 'select', options: ['full', 'short'], value: 'short', source: 'project', default: 'full' },
      { key: 'Parallel', kind: 'number', options: [], value: '3', source: 'default', default: '3' },
    ],
    raw: [{ line: 'Topic: Billing = T3', source: 'user' }],
  },
  cmd: { overrides: ['bash', '/x/plugins/abofles/scripts/py', '/x/plugins/abofles/scripts/overrides.py', '--session', 'sid-pane'] },
  ...over,
})

// One place that answers the state file, the pane calls, the process, the prompt box and the clipboard.
// `w.state` is the whole state file (null: none); `w.canPlace` whether an unasked open is drawn (a narrow terminal: not).
async function harness($: any, on: any, state: object | null, options: { canPlace?: boolean; store?: Record<string, unknown>; start?: boolean } = {}) {
  mock.clock(on, { now: NOW * 1000 })
  mock.store(on, options.store ?? {})
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  const w = {
    state: state as object | null,
    canPlace: options.canPlace ?? true,
    open: [] as { id: string; isPlaced: boolean }[],
    opens: [] as { title?: string }[],
    closes: [] as string[],
    registered: [] as string[],
    toasts: [] as string[],
    fills: [] as { text: string; mode: string }[],
    copies: [] as string[],
    runs: [] as { argv: unknown; cwd?: string }[],
    stdins: [] as (string | undefined)[], // what each run was given on stdin
    exits: [] as number[],
    stdouts: [] as string[], // the next runs' stdout (default: one line)
    stderrs: [] as string[],
    afterRuns: [] as (() => void)[], // run after the next process runs, in order: the script has rewritten the state file
    duringRun: null as (() => Promise<void>) | null, // runs while a process is "running"
  }
  on('session.id', () => ({ value: 'sid-pane' }))
  on('session.start', ($: any, e: any) => ({ cwd: e.cwd }))
  on('turn.complete', ($: any, e: any) => ({ text: e.answer }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.toast', ($: any, e: any) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('command.register', ($: any, e: any) => {
    w.registered.push(e.name)
    return { value: { command: e.name } }
  })
  on('fs.read', () => (w.state === null ? { deny: 'no such file' } : { value: JSON.stringify(w.state) }))
  on('ui.open', ($: any, e: any) => {
    w.opens.push({ title: e.title })
    const isPlaced = w.canPlace
    w.open = [...w.open.filter(p => p.id !== e.id), { id: e.id, isPlaced }]
    return { value: isPlaced ? { isPlaced: true } : { isPlaced: false, reason: 'narrow' } } as never
  })
  on('ui.panes', () => ({ value: w.open.map(p => ({ id: p.id, title: 'Abo Fles', isShown: p.isPlaced, isFocused: false, isPlaced: p.isPlaced })) }))
  on('ui.close', ($: any, e: any) => {
    w.closes.push(`${e.id}:${e.origin.kind}`)
    w.open = w.open.filter(p => p.id !== e.id)
    return { value: undefined }
  })
  on('process.run', async ($: any, e: any) => {
    w.runs.push({ argv: e.argv, cwd: e.init?.cwd })
    w.stdins.push(e.init?.stdin)
    await w.duringRun?.()
    w.afterRuns.shift()?.()
    return { value: { exitCode: w.exits.shift() ?? 0, stdout: w.stdouts.shift() ?? 'undone line\n', stderr: w.stderrs.shift() ?? '' } } as never
  })
  on('prompt.read', () => ({ value: { text: '', cursor: 0 } }))
  on('prompt.fill', ($: any, e: any) => {
    w.fills.push({ text: e.text, mode: e.mode })
    return { isFilled: true }
  })
  on('ui.copy', ($: any, e: any) => {
    w.copies.push(e.text)
    return { value: { isCopied: true } }
  })
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  if (options.start !== false) await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  return w
}

// The desktop shows one page at a time under its nav bar (Home, Guide, Resume, Decisions, Spawns, Overrides). So the tests read the
// pane as a person who knows where things are: a lookup tries the page shown, then each page of the nav bar, and stays on the page
// that has it (a press that follows lands there); found nowhere, it goes back to the page it started on. findAll gathers every page.
const mountRaw = async ($: any, surface: string, props: object = {}) => {
  const ui = await $.ui.mount({ plugin: 'abofles-guide', surface, component: 'Pane', requestId: 'abofles', props: { ...PANE_PROPS, ...props } })
  const find = ui.find.bind(ui)
  const findAll = ui.findAll.bind(ui)
  const press = ui.press.bind(ui)
  const navs = async (): Promise<{ key: string; on: boolean }[]> =>
    (await findAll({ type: 'Button' })).filter((b: any) => /^nav:/.test(String(b.props.key ?? ''))).map((b: any) => ({ key: String(b.props.key), on: !b.props.dimColor }))
  const visit = async <T,>(each: () => Promise<T | undefined>, all: boolean): Promise<T[]> => {
    const first = await each()
    if (first !== undefined && !all) return [first]
    const out: T[] = first === undefined ? [] : [first]
    const tabs = await navs()
    const start = tabs.find(t => t.on)?.key
    for (const t of tabs) {
      if (t.key === start) continue
      await press({ key: t.key })
      const r = await each()
      if (r !== undefined) {
        out.push(r)
        if (!all) return out
      }
    }
    if (start && tabs.length) await press({ key: start })
    return out
  }
  const over: Record<string, unknown> = {}
  over.find = async (q: any) => (await visit(() => find(q), false))[0]
  over.findAll = async (q: any) => (await visit(async () => { const r = await findAll(q); return r.length ? r : undefined }, true)).flat()
  for (const verb of ['press', 'input', 'select'] as const) {
    const orig = ui[verb].bind(ui)
    over[verb] = async (a: any) => {
      if (a?.key && (await find({ key: a.key })) === undefined) await (over.find as (q: object) => Promise<unknown>)({ key: a.key })
      return orig(a)
    }
  }
  // the mounted handle is frozen: a stand-in answers with the seeking verbs and passes the rest through
  return new Proxy({}, { get: (_t, k: string) => (k in over ? over[k] : typeof ui[k] === 'function' ? ui[k].bind(ui) : ui[k]) }) as any
}
// The sections start folded (Guide open). Most tests look inside them, so this opens each folded section the way a person does: a press on its header.
const SECTIONS = ['guide', 'resume', 'spawns', 'decisions', 'overrides']
const mountPane = async ($: any, surface: string, props: object = {}) => {
  const ui = await mountRaw($, surface, props)
  for (const id of SECTIONS) if ((await labelOf(ui, `fold-caret:${id}`)) === '▸') await ui.press({ key: `fold:${id}` })
  return ui
}
const mountBand = ($: any, surface: string) => $.ui.mount({ plugin: 'abofles-guide', surface, component: 'AbovePrompt', props: BAND_PROPS })
// a Text, or a Button's label (a desktop draws a Button as its label: the section titles, the carets, the links)
// (or a line of an HTML card's alt: the card draws inside an Svg, its alt carries every text, one per line)
// a desktop button's label leads with its glyph (shared.tsx GLYPH): the tests read the words after it
const bare = (label: unknown): string => String(label ?? '').replace(/^[✓↵↻⧉⤓↓↑↶✎↺⋯≡] /, '')
const said = async (ui: any, re: RegExp) =>
  (await ui.find({ type: 'Text', text: re })) !== undefined ||
  (await ui.findAll({ type: 'Button' })).some((b: any) => re.test(bare(b.props.label))) ||
  (await ui.findAll({ type: 'Svg' })).some((x: any) => String(x.props.alt ?? '').split('\n').some(l => re.test(l)))
const has = async (ui: any, key: string) => (await ui.find({ key })) !== undefined
const valueOf = async (ui: any, key: string) => (await ui.find({ key }))?.props.value
const propOf = async (ui: any, key: string, prop: string) => (await ui.find({ key }))?.props[prop]
const labelOf = async (ui: any, key: string) => { const l = await propOf(ui, key, 'label'); return l === undefined ? undefined : bare(l) }
// every line of every HTML card's alt, in order
const altLines = async (ui: any): Promise<string[]> => (await ui.findAll({ type: 'Svg' })).flatMap((x: any) => String(x.props.alt ?? '').split('\n'))
// the Read more / Show less link run inside a cut paragraph's Button (it has no label: a desktop would draw the label alone)
const moreOf = async (ui: any, key: string) => { const t = JSON.stringify((await ui.find({ key }))?.props ?? {}); return t.includes('Show less') ? 'Show less' : t.includes('Read more') ? 'Read more' : undefined }

test('every card draws from the state file, on every surface', async ($, on) => {
  await harness($, on, { guide: guideOf([item({ p: '🔴', text: 'open FAIL', id: 'fail:a' }), item({ text: 'then escalate' })], { ctx: { tokens: 412000, mark: 500 }, task: { spawns: 3, usd: 0.41, budget: 5, left: 2 } }), pane: panePayload() })
  for (const surface of SURFACES) {
    const ui = await mountPane($, surface)
    // Guide: the top item after a dot in its tone (no emoji), the rest dim, the numbers as label/value rows, the buttons
    expect([String(/^open FAIL$/), await said(ui, /^open FAIL$/)]).toEqual([String(/^open FAIL$/), true])
    expect([String(/^then escalate$/), await said(ui, /^then escalate$/)]).toEqual([String(/^then escalate$/), true])
    expect([String(/🔴|🟡/), await said(ui, /🔴|🟡/)]).toEqual([String(/🔴|🟡/), false])
    for (const re of [/^Context$/, /^412K \/ 500K$/, /^This task$/, /^3 spawns · \$0\.41$/, /^Agent budget$/, /^2 of 5 left$/]) expect([String(re), await said(ui, re)]).toEqual([String(re), true])
    // the meters and rules: SVG on the desktop (exact width, never wrapping), a row of ━ / ─ in the terminal (exact cells)
    if (surface === 'desktop') {
      const svgs = await ui.findAll({ type: 'Svg' })
      // the Guide is one HTML card: as wide as the slot (4096 capped), its height fixed, its alt every text
      const guide = svgs.find((x: any) => /^Next up, urgent priority\n/.test(x.props.alt) && /Context 82% of the next mark/.test(x.props.alt)) // the Guide page's card (Home has its own, shorter)
      expect(guide?.props.width).toBe(4096)
      expect(guide?.props.source).toContain('<foreignObject')
      expect(String(guide?.props.alt).split('\n')).toContain('Context 82% of the next mark')
      expect(await altLines(ui)).toContain('Spend by model: Haiku 5.5 2%, Sonnet 5.5 98%, Opus 5.5 0%')
      for (const t of ['Guide', 'Resume', 'Spawns', 'Overrides']) expect([t, svgs.some((x: any) => String(x.props.alt).split('\n')[0] === t)]).toEqual([t, true]) // each section's header strip
      expect(svgs.filter((x: any) => !(x.props.height === undefined && /viewBox="0 0 \d+ \d+"/.test(x.props.source))).map((x: any) => x.props.alt)).toEqual([]) // laid out at the pane's width, scaled keeping the ratio
      expect([String(/^[━─]+$/), await said(ui, /^[━─]+$/)]).toEqual([String(/^[━─]+$/), false])
    } else {
      expect([String(/^━+$/), await said(ui, /^━+$/)]).toEqual([String(/^━+$/), true])
      expect([String(/^─+$/), await said(ui, /^─+$/)]).toEqual([String(/^─+$/), true])
    }
    for (const key of ['use', 'copy']) expect(await has(ui, key)).toBe(true)
    expect(await has(ui, 'hide')).toBe(false) // no Hide: every action is a button
    expect(await propOf(ui, 'copy', 'variant')).toBe('secondary')
    // Resume: Now, Next, Needs you (numbers in their own column), Left, Last receipts, then the facts of the head
    expect([String(/wiring the pane/), await said(ui, /wiring the pane/)]).toEqual([String(/wiring the pane/), true])
    expect([String(/^pick the cap$/), await said(ui, /^pick the cap$/)]).toEqual([String(/^pick the cap$/), true])
    expect([String(/^1$/), await said(ui, /^1$/)]).toEqual([String(/^1$/), true])
    expect([String(/^name the key$/), await said(ui, /^name the key$/)]).toEqual([String(/^name the key$/), true])
    expect([String(/^3$/), await said(ui, /^3$/)]).toEqual([String(/^3$/), true])
    expect([String(/wrote cards/), await said(ui, /wrote cards/)]).toEqual([String(/wrote cards/), true])
    for (const re of [/^Session$/, /^sid-pane$/, /^Memo saved$/, /^Oct 20, 09:00$/]) expect([String(re), await said(ui, re)]).toEqual([String(re), true])
    expect([String(/now written/), await said(ui, /now written/)]).toEqual([String(/now written/), false]) // the noisy part of the head is left out
    // Spawns: the saving first, the split by model, then Running and History (chip, ask, cost, dim detail), newest first
    for (const re of [/^54% saved$/, /^\$0\.41 of \$0\.90 on Opus 5\.5$/, /^Haiku 5\.5(: .*)?$/, /^Sonnet 5\.5(: .*)?$/, /(^|, )98%( of spend)?$/, /^Tokens$/, /^92K$/, /^Open FAIL$/]) expect([String(re), await said(ui, re)]).toEqual([String(re), true])
    if (surface === 'terminal') expect([String(/^■$/), await said(ui, /^■$/)]).toEqual([String(/^■$/), true]) // the model swatches (the desktop draws them in its card)
    expect([String(/^3 spawns · \$0\.41$/), await said(ui, /^3 spawns · \$0\.41$/)]).toEqual([String(/^3 spawns · \$0\.41$/), true]) // the card's summary
    expect([String(/^build the card$/), await said(ui, /^build the card$/)]).toEqual([String(/^build the card$/), true])
    expect([String(new RegExp(`^${hhmm(NOW - 125)} · Sonnet 5\\.5 · High · running$`)), await said(ui, new RegExp(`^${hhmm(NOW - 125)} · Sonnet 5\\.5 · High · running$`))]).toEqual([String(new RegExp(`^${hhmm(NOW - 125)} · Sonnet 5\\.5 · High · running$`)), true]) // the start time, not an age that goes stale
    expect([String(/Fix login/), await said(ui, /Fix login/)]).toEqual([String(/Fix login/), false]) // a spawn's prompt line is no heading
    expect([String(/^read the docs$/), await said(ui, /^read the docs$/)]).toEqual([String(/^read the docs$/), true])
    expect([String(new RegExp(`^${hhmm(NOW - 900)} · Haiku 5\\.5 · Low · 12K tokens$`)), await said(ui, new RegExp(`^${hhmm(NOW - 900)} · Haiku 5\\.5 · Low · 12K tokens$`))]).toEqual([String(new RegExp(`^${hhmm(NOW - 900)} · Haiku 5\\.5 · Low · 12K tokens$`)), true])
    expect([String(/^\$0\.01$/), await said(ui, /^\$0\.01$/)]).toEqual([String(/^\$0\.01$/), true])
    expect([String(/^patch it$/), await said(ui, /^patch it$/)]).toEqual([String(/^patch it$/), true])
    expect([String(/Sonnet 5\.5 · Medium · 80K tokens · PASS$/), await said(ui, /Sonnet 5\.5 · Medium · 80K tokens · PASS$/)]).toEqual([String(/Sonnet 5\.5 · Medium · 80K tokens · PASS$/), true])
    expect([String(/^check it$/), await said(ui, /^check it$/)]).toEqual([String(/^check it$/), true])
    expect([String(/Opus 5\.5 · High$/), await said(ui, /Opus 5\.5 · High$/)]).toEqual([String(/Opus 5\.5 · High$/), true]) // no tokens, plain done: no status word
    expect([String(/^DONE$/), await said(ui, /^DONE$/)]).toEqual([String(/^DONE$/), false])
    expect([String(/^Updated \d\d:\d\d · refreshes when a turn ends$/), await said(ui, /^Updated \d\d:\d\d · refreshes when a turn ends$/)]).toEqual([String(/^Updated \d\d:\d\d · refreshes when a turn ends$/), true])
    const asks = /^(read the docs|patch it|check it)$/
    const rows = surface === 'terminal' ? (await ui.findAll({ type: 'Text', text: asks })).map((r: any) => r.text) : (await altLines(ui)).filter(l => asks.test(l))
    expect(rows[0]).toBe('check it') // newest first
    expect(rows[rows.length - 1]).toBe('read the docs')
    expect([String(/^Work$/), await said(ui, /^Work$/)]).toEqual([String(/^Work$/), true]) // the side, semibold, before its ask
    // Overrides: a short card on the main page (a table of what a file sets, the other lines), the editor one press away
    expect([String(/^Overrides$/), await said(ui, /^Overrides$/)]).toEqual([String(/^Overrides$/), true])
    for (const re of [/^Receipt$/, /^short$/, /^this project$/, /^1 set$/]) expect([String(re), await said(ui, re)]).toEqual([String(re), true])
    expect([String(/^Parallel$/), await said(ui, /^Parallel$/)]).toEqual([String(/^Parallel$/), false]) // a default is not listed
    expect(await labelOf(ui, 'edit-other')).toMatch(/^1 other line · tiers, reviewers/)
    expect(await labelOf(ui, 'edit-overrides')).toBe('Edit')
    expect(await has(ui, 'sel:Receipt')).toBe(false)
    for (const key of surface === 'terminal' ? ['fold:guide', 'fold:resume', 'fold:spawns', 'fold:overrides', 'edit-overrides'] : ['edit-overrides']) expect(await has(ui, key)).toBe(true)
    // the editor page: ‹ Overrides, the scope buttons, settings rows (name and help on the left, the control on the right), the buttons
    await ui.press({ key: 'edit-overrides' })
    expect(await has(ui, 'use')).toBe(false) // the cards make room for the page
    expect(await labelOf(ui, 'back')).toBe('‹ Overrides')
    expect(await propOf(ui, 'scope:project', 'label')).toBe('✓ This project')
    expect(await propOf(ui, 'scope:user', 'label')).toBe('All projects')
    expect([String(/^CLAUDE\.md · the project file wins over yours$/), await said(ui, /^CLAUDE\.md · the project file wins over yours$/)]).toEqual([String(/^CLAUDE\.md · the project file wins over yours$/), true])
    expect([String(/^Receipt$/), await said(ui, /^Receipt$/)]).toEqual([String(/^Receipt$/), true]) // the name beside the control
    expect(await labelOf(ui, 'sel:Receipt')).toBeUndefined()
    expect(await valueOf(ui, 'sel:Receipt')).toBe('short')
    expect(await valueOf(ui, 'in:Parallel')).toBe('3')
    expect([String(/^Receipt form; savings N = only past N% · this project$/), await said(ui, /^Receipt form; savings N = only past N% · this project$/)]).toEqual([String(/^Receipt form; savings N = only past N% · this project$/), true]) // the help, and the file that sets it
    expect([String(/^Background agents at once$/), await said(ui, /^Background agents at once$/)]).toEqual([String(/^Background agents at once$/), true]) // a default: the help alone
    expect(await has(ui, 'raw')).toBe(false) // Other overrides: folded while this file has none of its lines
    expect([String(/^1 in all projects$/), await said(ui, /^1 in all projects$/)]).toEqual([String(/^1 in all projects$/), true]) // its summary
    await ui.press({ key: 'fold:g:Other' })
    expect([String(/^Topic: Billing = T3 — in all projects; switch Save to, to edit it$/), await said(ui, /^Topic: Billing = T3 — in all projects; switch Save to, to edit it$/)]).toEqual([String(/^Topic: Billing = T3 — in all projects; switch Save to, to edit it$/), true])
    for (const key of ['back', 'save', 'ask', 'raw', 'fold:g:Agents', 'fold:g:Output', 'fold:g:Other']) expect(await has(ui, key)).toBe(true)
    expect(await labelOf(ui, 'ask')).toBe('Ask Claude')
    expect(await has(ui, 'reset')).toBe(false) // nothing to discard
    await ui.press({ key: 'fold:g:Other' }) // as it was, for the next surface
    await ui.press({ key: 'back' })
    expect(await has(ui, 'use')).toBe(true) // the cards are back
    await ui.unmount()
  }
})

test('empty cards say so: no memo yet, no spawns yet', async ($, on) => {
  await harness($, on, { guide: guideOf([item()]), pane: panePayload({ resume: null, spawns: { live: [], rows: [], totals: { spawns: 0, tokens: 0, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) })
  for (const surface of SURFACES) {
    const ui = await mountPane($, surface)
    expect(await said(ui, /^No memo yet — run \/abofles:memo$/)).toBe(true)
    expect(await said(ui, /No spawns yet/)).toBe(true)
    await ui.unmount()
  }
})

test('a place other than the pane hides its card; Overrides always draws', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ places: { guide: 'band', resume: 'output', spawns: 'output' } }) })
  for (const surface of SURFACES) {
    const ui = await mountPane($, surface)
    expect(await said(ui, /Guide|Resume|Spawns/)).toBe(false)
    expect(await has(ui, 'use')).toBe(false)
    expect(await said(ui, /^Overrides$/)).toBe(true)
    await ui.unmount()
  }
  w.state = { guide: guideOf([item()]), pane: panePayload({ places: { guide: 'pane', resume: 'output', spawns: 'pane' } }) }
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answered' } as never)
  const ui = await mountPane($, 'desktop')
  expect(await said(ui, /^Guide$/)).toBe(true)
  expect(await said(ui, /^Resume$/)).toBe(false)
  expect(await said(ui, /^Spawns$/)).toBe(true)
  await ui.unmount()
})

test('a state file from older hooks (no pane): the pane has the Overrides card only and the band is today\'s', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item()]) })
  const band = await mountBand($, 'desktop')
  for (const key of ['use', 'copy', 'hide']) expect(await has(band, key)).toBe(true)
  expect(await has(band, 'pane')).toBe(false)
  await band.unmount()
  const ui = await mountPane($, 'desktop')
  expect(await said(ui, /^Guide$|^Resume$|^Spawns$/)).toBe(false)
  expect(await said(ui, /^Pane data unreadable — update both abofles and abofles-guide$/)).toBe(true)
  await ui.unmount()
  expect(w.opens).toEqual([]) // nothing opened unasked
})

test('malformed parts of the pane payload are dropped, the rest is drawn', async ($, on) => {
  const pane = panePayload({
    resume: { head: 5, now: 'x', left: [1, 'ok'], next: null, needs: [{ n: 'a', text: 7 }, { n: 2, text: 'fine' }], last: [] },
    spawns: { live: [3, { side: 'Work' }], rows: ['x', { status: 'done', tokens: 'many' }, null], totals: 'no' },
    overrides: { keys: [{ key: 9 }, { key: 'Receipt', value: 'short' }], raw: 'no' },
    cmd: 'no',
  })
  await harness($, on, { guide: guideOf([item()]), pane })
  const ui = await mountPane($, 'desktop')
  expect(await said(ui, /^ok$/)).toBe(true)
  expect(await said(ui, /^fine$/)).toBe(true)
  expect(await said(ui, /^2$/)).toBe(true)
  expect(await said(ui, /^\?$/)).toBe(true) // no model, no tokens, no start: the meta line is a bare ?
  await ui.press({ key: 'edit-overrides' })
  expect(await has(ui, 'in:Receipt')).toBe(true) // no kind: a text Input
  await ui.unmount()
})

test('a pane payload of another version is not used: nothing opens, the band is today\'s', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ v: 2 }) })
  expect(w.opens).toEqual([])
  const band = await mountBand($, 'desktop')
  expect(await has(band, 'use')).toBe(true)
  expect(await has(band, 'pane')).toBe(false)
  await band.unmount()
})

test('Use, Copy, Re-check, Show and Undo work inside the pane (no Hide)', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item({ recheck: 'run it again' })]), pane: panePayload() })
  for (const surface of SURFACES) {
    w.fills.length = 0
    w.copies.length = 0
    w.state = { guide: guideOf([item({ id: `first:${surface}`, recheck: 'run it again' })]), pane: panePayload() } // a guide not hidden before
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `t0-${surface}`, reason: 'answered' } as never)
    const ui = await mountPane($, surface)
    await ui.press({ key: 'copy' })
    expect(w.copies).toEqual(['do it'])
    await ui.press({ key: 'recheck' })
    expect(w.fills).toEqual([{ text: 'run it again', mode: 'replace' }])
    expect(await has(ui, 'use')).toBe(false) // a fill hides the guide, as the band does
    expect(await said(ui, /Hidden until the list changes/)).toBe(true)
    await ui.unmount()
    w.state = { guide: guideOf([item({ id: `esc:${surface}` })]), pane: panePayload() } // another item: the guide is back
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `t-${surface}`, reason: 'answered' } as never)
    const again = await mountPane($, surface)
    await again.press({ key: 'use' })
    expect(w.fills[w.fills.length - 1]).toEqual({ text: 'do it', mode: 'replace' })
    await again.unmount()
  }
  // no Hide button: a fill hides the card (as the band does), and Show brings it back
  w.state = { guide: guideOf([item({ id: 'esc:hide', recheck: 'again' })]), pane: panePayload() }
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't-hide', reason: 'answered' } as never)
  const ui = await mountPane($, 'desktop')
  expect(await has(ui, 'hide')).toBe(false)
  await ui.press({ key: 'recheck' })
  expect(await has(ui, 'use')).toBe(false)
  expect(await propOf(ui, 'show', 'variant')).toBe('secondary') // the hidden card offers its way back, as a button
  await ui.press({ key: 'show' })
  expect(await has(ui, 'use')).toBe(true)
  expect(await has(ui, 'show')).toBe(false)
  expect(await said(ui, /Hidden until the list changes/)).toBe(false)
  await ui.unmount()
  // Undo: the row of Claude's last resolve, with the hook's argv
  w.state = { guide: guideOf([item({ id: 'esc:undo' })], { last_resolved: { text: 'FAIL cleared', unresolve: ['bash', '/x/plugins/abofles/scripts/py', '/x/plugins/abofles/scripts/status.py', '--unresolve', 'a1'], ts: 7 } }), pane: panePayload() }
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't-undo', reason: 'answered' } as never)
  const un = await mountPane($, 'desktop')
  expect(await said(un, /✓ resolved: FAIL cleared/)).toBe(true)
  await un.press({ key: 'undo' })
  expect(w.runs).toEqual([{ argv: ['bash', '/x/plugins/abofles/scripts/py', '/x/plugins/abofles/scripts/status.py', '--unresolve', 'a1'], cwd: '/proj' }])
  expect(await said(un, /✓ resolved/)).toBe(false)
  await un.unmount()
})

test('/abofles:pane and /abofles-pane open the pane, then close it', async ($, on) => {
  // the guide is in the band here, so the session start opens nothing on its own
  const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ places: { guide: 'band', resume: 'output', spawns: 'output' } }) })
  expect(w.registered).toEqual(['abofles-pane'])
  expect(w.opens).toEqual([])
  const first = await $.command.run({ command: 'abofles:pane', ...RUN } as never)
  expect(first.text).toBe('Abo Fles pane opened.')
  expect(w.opens).toEqual([{ title: 'Abo Fles' }])
  const second = await $.command.run({ command: 'abofles:pane', ...RUN } as never)
  expect(second.text).toBe('Abo Fles pane closed.')
  expect(w.closes).toEqual(['abofles:plugin'])
  const third = await $.command.run({ command: 'abofles-pane', ...RUN } as never)
  expect(third.text).toBe('Abo Fles pane opened.')
  expect(w.opens.length).toBe(2)
})

test('the session start opens the pane unasked, unless an earlier session left it closed', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload() }, { store: {} })
  expect(w.opens).toEqual([{ title: 'Abo Fles' }])
})

test('closed by the person in an earlier session (the store says false): the session start leaves it closed', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload() }, { store: { paneOpen: false } })
  expect(w.opens).toEqual([])
  // not drawn, so the guide's opener is in the band
  const band = await mountBand($, 'desktop')
  expect(await has(band, 'pane')).toBe(true)
  await band.press({ key: 'pane' })
  expect(w.opens).toEqual([{ title: 'Abo Fles' }])
  await band.unmount()
})

test('a pane that is not placed: the band shows the opener, and its button opens the pane', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item({ p: '🔴', text: 'open FAIL', id: 'fail:a' })]), pane: panePayload({ places: { guide: 'band', resume: 'pane', spawns: 'output' } }) }, { canPlace: false })
  expect(w.opens.length).toBe(1) // the unasked open, not drawn
  const band = await mountBand($, 'desktop')
  // the guide stays in the band, with the Pane button beside its own
  for (const key of ['use', 'copy', 'hide', 'pane']) expect(await has(band, key)).toBe(true)
  w.canPlace = true
  await band.press({ key: 'pane' })
  expect(w.opens.length).toBe(2)
  expect(w.open).toEqual([{ id: 'abofles', isPlaced: true }])
  await band.unmount()
})

test('Guide place pane: the band is one opener row while the pane is not up, and empty while it is', async ($, on) => {
  const w = await harness($, on, { guide: guideOf([item({ p: '🔴', text: 'open FAIL', id: 'fail:a' }), item()]), pane: panePayload() }, { canPlace: false })
  for (const surface of SURFACES) {
    const band = await mountBand($, surface)
    expect(await said(band, /^Abo Fles · 🔴 open FAIL$/)).toBe(true)
    expect(await has(band, 'pane')).toBe(true)
    for (const key of ['use', 'copy', 'hide', 'recheck']) expect(await has(band, key)).toBe(false) // the guide lives in the pane
    await band.unmount()
  }
  // the Pane button opens it as asked; the band then goes empty
  w.canPlace = true
  const band = await mountBand($, 'desktop')
  await band.press({ key: 'pane' })
  expect(w.open).toEqual([{ id: 'abofles', isPlaced: true }])
  expect(await has(band, 'pane')).toBe(false)
  expect(await said(band, /Abo Fles/)).toBe(false)
  await band.unmount()
})

test('Guide place pane with the pane closed by the command: the opener row comes back', async ($, on) => {
  await harness($, on, { guide: guideOf([item()]), pane: panePayload() })
  const band = await mountBand($, 'desktop')
  expect(await has(band, 'pane')).toBe(false) // up
  await $.command.run({ command: 'abofles:pane', ...RUN } as never) // closes
  expect(await has(band, 'pane')).toBe(true)
  await band.unmount()
})

test('the classic PostToolUse and SubagentStop refresh the pane, so live spawns update', async ($, on) => {
  on('classic.PostToolUse', () => ({}))
  on('classic.SubagentStop', () => ({}))
  const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ spawns: { live: [], rows: [], totals: { spawns: 0, tokens: 0, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) })
  const ui = await mountPane($, 'desktop')
  expect(await said(ui, /build the card/)).toBe(false)
  w.state = { guide: guideOf([item()]), pane: panePayload() }
  await $.classic.PostToolUse({ tool_name: 'Agent', tool_input: {}, tool_response: {}, tool_use_id: 'u1' } as never)
  expect(await said(ui, /^build the card$/)).toBe(true)
  expect(await said(ui, new RegExp(`^${hhmm(NOW - 125)} · Sonnet 5\\.5 · High · running$`))).toBe(true)
  w.state = { guide: guideOf([item()]), pane: panePayload({ spawns: { live: [], rows: ROWS, totals: { spawns: 3, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) }
  await $.classic.SubagentStop({ stop_hook_active: false, agent_id: 'a1', agent_type: 'general', agent_transcript_path: '', last_assistant_message: '' } as never)
  expect(await said(ui, /build the card/)).toBe(false)
  expect(await said(ui, /^read the docs$/)).toBe(true)
  expect(await said(ui, /^Read$/)).toBe(true)
  await ui.unmount()
})

// ---- the overrides editor

const ovKeys = (more: object[] = []) => [
  { key: 'Receipt', kind: 'select', options: ['full', 'short'], value: 'short', source: 'project', default: 'full' },
  { key: 'Parallel', kind: 'number', options: [], value: '3', source: 'default', default: '3' },
  ...more,
]
const AGENTS = { key: 'Agents', kind: 'select', options: ['ask', 'auto', 'off'], value: 'ask', source: 'default', default: 'ask' }
const ovState = (keys: object[] = ovKeys(), raw: object[] = [{ line: 'Topic: Billing = T3', source: 'user' }]) => ({
  guide: guideOf([item()]),
  pane: panePayload({ overrides: { files: { project: '/proj/CLAUDE.md', user: '/home/.claude/CLAUDE.md' }, keys, raw } }),
})
const FILES = { project: '/proj/CLAUDE.md', user: '/home/.claude/CLAUDE.md' }
const saved = (keys: object[], raw: object[] = []) => JSON.stringify({ files: FILES, keys, raw })
// The next Save: the script prints the table and has rewritten the state file (`places` too), which the mod reads again.
const willSave = (w: any, keys: object[], raw: object[] = [], places: object = PLACES) => {
  w.stdouts.push(saved(keys, raw))
  w.afterRuns.push(() => {
    w.state = { guide: guideOf([item()]), pane: panePayload({ places, overrides: { files: FILES, keys, raw } }) }
  })
}
// The pane on its editor page (the main page's Edit button).
const mountEditor = async ($: any, surface: string, props: object = {}) => {
  const ui = await mountPane($, surface, props)
  if (await has(ui, 'edit-overrides')) await ui.press({ key: 'edit-overrides' })
  return ui
}

for (const surface of SURFACES) {
  test(`${surface}: the Overrides card draws a row per key and Select/Input edits go into the draft, with the count in the title`, async ($, on) => {
    await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.press({ key: 'fold:g:Other' }) // folded while the project file has none of its lines
    expect(await propOf(ui, 'scope:project', 'label')).toBe('✓ This project')
    expect(await labelOf(ui, 'scope:project')).toBe('This project')
    expect(await labelOf(ui, 'scope:user')).toBe('All projects')
    // settings rows: the name is a Text beside the control, the control carries no label of its own
    expect(await said(ui, /^Save to$/)).toBe(true)
    for (const re of [/^Parallel$/, /^Receipt$/]) expect(await said(ui, re)).toBe(true)
    expect(await labelOf(ui, 'sel:Receipt')).toBeUndefined()
    expect(await labelOf(ui, 'in:Parallel')).toBeUndefined()
    expect(await propOf(ui, 'raw', 'placeholder')).toBe('Topic: Billing = T3')
    expect(await said(ui, /unsaved/)).toBe(false)
    expect(await propOf(ui, 'save', 'variant')).toBe('secondary') // nothing to save
    expect(await has(ui, 'reset')).toBe(false) // nothing to discard
    const opts = (await ui.find({ key: 'sel:Receipt' }))?.props.options as { value: string; label?: string }[]
    expect(opts.map(o => o.label ?? o.value)).toEqual(['default (full)', 'full', 'short', 'custom value']) // the default named; Receipt also takes `savings N`
    expect(await has(ui, 'sel:Parallel')).toBe(false) // a number is an Input
    expect(await propOf(ui, 'in:Parallel', 'placeholder')).toBe('default 3')
    expect(await said(ui, /^Overrides$/)).toBe(true)
    await ui.select({ key: 'sel:Receipt', value: 'full' })
    expect(await valueOf(ui, 'sel:Receipt')).toBe('full')
    expect(await said(ui, /^1 unsaved$/)).toBe(true)
    expect(await said(ui, /^1 edited$/)).toBe(true) // the group's summary
    expect(await propOf(ui, 'save', 'variant')).toBe('primary') // something to save
    expect(await labelOf(ui, 'reset')).toBe('Discard')
    expect(await labelOf(ui, 'save')).toBe('Save 1 change')
    expect(await said(ui, /^ · edited$/)).toBe(true) // beside Receipt's name
    await ui.input({ key: 'in:Parallel', text: '5', kind: 'change' })
    expect(await valueOf(ui, 'in:Parallel')).toBe('5')
    expect(await said(ui, /^2 unsaved$/)).toBe(true)
    await ui.select({ key: 'sel:Receipt', value: '@default' }) // "default (full)" removes the line: a change from `short`
    expect(await said(ui, /^2 unsaved$/)).toBe(true)
    await ui.select({ key: 'sel:Receipt', value: 'short' }) // back to what the file has: no change
    await ui.input({ key: 'in:Parallel', text: '3' })
    expect(await said(ui, /unsaved/)).toBe(false)
    expect(await propOf(ui, 'save', 'variant')).toBe('secondary')
    await ui.press({ key: 'back' }) // the main page's card follows the draft
    await ui.press({ key: 'edit-overrides' })
    await ui.unmount()
  })

  test(`${surface}: Save runs the script with the scope and the changes on stdin, toasts, applies the printed table and clears the draft`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.select({ key: 'sel:Receipt', value: 'full' })
    await ui.input({ key: 'in:Parallel', text: ' 5 ', kind: 'change' })
    willSave(w, [{ key: 'Receipt', kind: 'select', options: ['full', 'short'], value: 'full', source: 'project', default: 'full' }, { key: 'Parallel', kind: 'number', options: [], value: '5', source: 'project', default: '3' }])
    await ui.press({ key: 'save' })
    expect(w.runs).toEqual([{ argv: ['bash', '/x/plugins/abofles/scripts/py', '/x/plugins/abofles/scripts/overrides.py', '--session', 'sid-pane', 'set', '--scope', 'project'], cwd: '/proj' }])
    expect(JSON.parse(w.stdins[0] ?? '')).toEqual({ set: { Receipt: 'full', Parallel: '5' } })
    expect(w.toasts).toContain('Saved to CLAUDE.md')
    expect(await said(ui, /unsaved/)).toBe(false) // the draft is clear
    expect(await valueOf(ui, 'in:Parallel')).toBe('5') // the table is the one the script printed
    expect(await said(ui, /^Receipt form; savings N = only past N% · this project$/)).toBe(true) // both keys now set in the project file
    expect(await said(ui, /^Background agents at once · this project$/)).toBe(true)
    expect(await said(ui, /Topic: Billing/)).toBe(false) // the printed table had no raw lines
    await ui.unmount()
  })

  test(`${surface}: a failed Save toasts the first line of stderr and keeps the draft`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.input({ key: 'in:Parallel', text: 'many', kind: 'change' })
    w.exits.push(2)
    w.stderrs.push('abofles overrides: Parallel: \'many\' is not a whole number\nsecond line')
    await ui.press({ key: 'save' })
    expect(w.toasts).toContain("abofles overrides: Parallel: 'many' is not a whole number")
    expect(w.toasts.some(t => t.startsWith('Saved'))).toBe(false)
    expect(await said(ui, /^1 unsaved$/)).toBe(true)
    expect(await valueOf(ui, 'in:Parallel')).toBe('many')
    willSave(w, ovKeys())
    await ui.input({ key: 'in:Parallel', text: '4', kind: 'change' })
    await ui.press({ key: 'save' }) // pressed again: the claim was released
    expect(w.runs.length).toBe(2)
    await ui.unmount()
  })

  test(`${surface}: a Save that finds the file changed meanwhile (exit 3) toasts it and keeps the draft`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.input({ key: 'in:Parallel', text: '5', kind: 'change' })
    w.exits.push(3)
    w.stderrs.push('abofles: CLAUDE.md changed while saving — reload the pane and save again')
    await ui.press({ key: 'save' })
    expect(w.toasts).toContain('abofles: CLAUDE.md changed while saving — reload the pane and save again')
    expect(await said(ui, /^1 unsaved$/)).toBe(true)
    expect(await labelOf(ui, 'save')).toBe('Save 1 change') // free to press again
    await ui.unmount()
  })

  test(`${surface}: Save with nothing changed runs nothing`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.press({ key: 'save' })
    expect(w.runs).toEqual([])
    expect(w.toasts.some(t => t === 'Nothing to save')).toBe(true)
    await ui.unmount()
  })

  test(`${surface}: Ask Claude to apply fills the prompt box with the changed keys only, and writes nothing`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.press({ key: 'ask' })
    expect(w.fills).toEqual([]) // nothing changed: nothing to ask
    await ui.select({ key: 'sel:Receipt', value: '@default' })
    await ui.input({ key: 'in:Parallel', text: '5', kind: 'change' })
    await ui.press({ key: 'ask' })
    expect(w.fills).toEqual([{ text: 'Apply in CLAUDE.md `## abofles overrides`: - Receipt removed (back to the default) - Parallel = 5', mode: 'replace' }])
    expect(w.runs).toEqual([])
    expect(await said(ui, /^2 unsaved$/)).toBe(true) // the draft stays for Save
    await ui.press({ key: 'reset' })
    await ui.unmount()
  })

  test(`${surface}: the scope Select picks the target file, and the lines of the forms follow it`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.press({ key: 'fold:g:Other' }) // folded while the project file has none of its lines
    expect(await valueOf(ui, 'raw')).toBe('')
    expect(await said(ui, /^Topic: Billing = T3 — in all projects; switch Save to, to edit it$/)).toBe(true)
    await ui.press({ key: 'scope:user' })
    expect(await propOf(ui, 'scope:user', 'label')).toBe('✓ All projects')
    expect(await valueOf(ui, 'raw')).toBe('Topic: Billing = T3')
    expect(await said(ui, /switch Save to/)).toBe(false)
    expect(await said(ui, /^~\/\.claude\/CLAUDE\.md · the project file wins over yours$/)).toBe(true)
    await ui.input({ key: 'raw', text: 'Topic: Billing = T3\n- Reviewers: FIN = tester\n', kind: 'change' })
    expect(await said(ui, /^1 unsaved$/)).toBe(true)
    expect(await said(ui, /^edited$/)).toBe(true) // the Other overrides group's summary
    await ui.select({ key: 'sel:Receipt', value: 'full' })
    await ui.press({ key: 'ask' })
    expect(w.fills[0]?.text).toBe('Apply in ~/.claude/CLAUDE.md `## abofles overrides`: - Receipt = full - Reviewers: FIN = tester')
    willSave(w, ovKeys(), [{ line: 'Topic: Billing = T3', source: 'user' }, { line: 'Reviewers: FIN = tester', source: 'user' }])
    await ui.press({ key: 'save' })
    expect(w.runs[0]?.argv).toEqual(['bash', '/x/plugins/abofles/scripts/py', '/x/plugins/abofles/scripts/overrides.py', '--session', 'sid-pane', 'set', '--scope', 'user'])
    expect(JSON.parse(w.stdins[0] ?? '')).toEqual({ set: { Receipt: 'full' }, raw: ['Topic: Billing = T3', 'Reviewers: FIN = tester'] })
    expect(w.toasts).toContain('Saved to ~/.claude/CLAUDE.md')
    expect(await propOf(ui, 'scope:user', 'label')).toBe('✓ All projects') // the target stays
    expect(await valueOf(ui, 'raw')).toBe('Topic: Billing = T3\nReviewers: FIN = tester')
    await ui.press({ key: 'scope:project' })
    await ui.unmount()
  })

  test(`${surface}: Discard edits clears the draft`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.press({ key: 'fold:g:Other' }) // folded while the project file has none of its lines
    await ui.select({ key: 'sel:Receipt', value: 'full' })
    await ui.input({ key: 'in:Parallel', text: '9', kind: 'change' })
    await ui.press({ key: 'scope:user' })
    await ui.input({ key: 'raw', text: 'Topic: X = T1', kind: 'change' })
    expect(await said(ui, /^3 unsaved$/)).toBe(true)
    await ui.press({ key: 'reset' })
    expect(await said(ui, /unsaved/)).toBe(false)
    expect(await has(ui, 'reset')).toBe(false)
    expect(await valueOf(ui, 'sel:Receipt')).toBe('short')
    expect(await valueOf(ui, 'in:Parallel')).toBe('3')
    expect(await valueOf(ui, 'raw')).toBe('Topic: Billing = T3')
    expect(w.runs).toEqual([])
    await ui.press({ key: 'scope:project' })
    await ui.unmount()
  })

  test(`${surface}: Agents and Receipt offer custom value, which opens an Input for N / savings N`, async ($, on) => {
    const w = await harness($, on, ovState(ovKeys([AGENTS])))
    const ui = await mountEditor($, surface)
    const opts = (await ui.find({ key: 'sel:Agents' }))?.props.options as { value: string; label?: string }[]
    expect(opts.map(o => o.label ?? o.value)).toEqual(['default (ask)', 'ask', 'auto', 'off', 'custom value'])
    expect((await ui.find({ key: 'sel:Receipt' }))?.props.options).toHaveLength(4)
    expect(await valueOf(ui, 'sel:Agents')).toBe('@default')
    expect(await has(ui, 'custom:Agents')).toBe(false)
    await ui.select({ key: 'sel:Agents', value: '@custom' })
    expect(await valueOf(ui, 'sel:Agents')).toBe('@custom')
    expect(await has(ui, 'custom:Agents')).toBe(true)
    expect(await valueOf(ui, 'custom:Agents')).toBe('3') // starts with a sensible N
    expect(await propOf(ui, 'custom:Agents', 'placeholder')).toBe('N agents per task') // its hint
    expect(await said(ui, /^N agents per task$/)).toBe(true) // and the same hint beside it
    await ui.input({ key: 'custom:Agents', text: '7', kind: 'change' })
    expect(await said(ui, /^1 unsaved$/)).toBe(true)
    await ui.select({ key: 'sel:Receipt', value: '@custom' })
    expect(await valueOf(ui, 'custom:Receipt')).toBe('savings 30')
    await ui.input({ key: 'custom:Receipt', text: 'savings 40', kind: 'change' })
    willSave(w, [{ key: 'Agents', kind: 'select', options: ['ask', 'auto', 'off'], value: '7', source: 'project', default: 'ask' }, { key: 'Receipt', kind: 'select', options: ['full', 'short'], value: 'savings 40', source: 'project', default: 'full' }])
    await ui.press({ key: 'save' })
    expect(JSON.parse(w.stdins[0] ?? '')).toEqual({ set: { Agents: '7', Receipt: 'savings 40' } })
    // a value from the file that is not an option shows as custom, its Input open with the value
    expect(await valueOf(ui, 'sel:Agents')).toBe('@custom')
    expect(await valueOf(ui, 'custom:Agents')).toBe('7')
    expect(await valueOf(ui, 'custom:Receipt')).toBe('savings 40')
    await ui.select({ key: 'sel:Agents', value: 'auto' }) // a plain option closes the Input
    expect(await has(ui, 'custom:Agents')).toBe(false)
    expect(await valueOf(ui, 'sel:Agents')).toBe('auto')
    await ui.unmount()
  })
}

const GUIDE_PLACE = { key: 'Guide place', kind: 'select', options: ['pane', 'band'], value: 'pane', source: 'default', default: 'pane' }

for (const surface of SURFACES) {
  test(`${surface}: switching scope drops the lines typed for the other file, so they are never written to it`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.press({ key: 'fold:g:Other' }) // folded while the project file has none of its lines
    await ui.input({ key: 'raw', text: 'Reviewers: FIN = tester', kind: 'change' }) // typed for the project file
    expect(await said(ui, /^1 unsaved$/)).toBe(true)
    await ui.press({ key: 'scope:user' })
    expect(await valueOf(ui, 'raw')).toBe('Topic: Billing = T3') // the user file's own lines, not the typed ones
    expect(await said(ui, /unsaved/)).toBe(false)
    await ui.select({ key: 'sel:Receipt', value: 'full' })
    willSave(w, ovKeys())
    await ui.press({ key: 'save' })
    expect(w.runs[0]?.argv).toEqual(['bash', '/x/plugins/abofles/scripts/py', '/x/plugins/abofles/scripts/overrides.py', '--session', 'sid-pane', 'set', '--scope', 'user'])
    expect(JSON.parse(w.stdins[0] ?? '')).toEqual({ set: { Receipt: 'full' } }) // no raw lines
    await ui.press({ key: 'scope:project' })
    await ui.unmount()
  })

  test(`${surface}: while Save runs it reads "Saving…" and cannot be pressed again; after it, "Save"`, async ($, on) => {
    const w = await harness($, on, ovState())
    const ui = await mountEditor($, surface)
    await ui.input({ key: 'in:Parallel', text: '5', kind: 'change' })
    let during: unknown = null
    w.duringRun = async () => {
      during = await labelOf(ui, 'save')
      await ui.press({ key: 'save' }) // a second press does nothing
    }
    willSave(w, ovKeys())
    await ui.press({ key: 'save' })
    expect(during).toBe('Saving…')
    expect(w.runs.length).toBe(1)
    expect(await labelOf(ui, 'save')).toBe('Save')
    await ui.unmount()
  })

  test(`${surface}: a Save that changes Guide place to band removes the Guide card at once`, async ($, on) => {
    const w = await harness($, on, ovState(ovKeys([GUIDE_PLACE])))
    const ui = await mountPane($, surface)
    expect(await said(ui, /^Guide$/)).toBe(true)
    expect(await has(ui, 'use')).toBe(true)
    await ui.press({ key: 'edit-overrides' })
    expect(await said(ui, /^Where it shows$/)).toBe(true) // the place keys' group
    await ui.select({ key: 'sel:Guide place', value: 'band' })
    willSave(w, ovKeys([{ ...GUIDE_PLACE, value: 'band', source: 'project' }]), [], { ...PLACES, guide: 'band' })
    await ui.press({ key: 'save' })
    await ui.press({ key: 'back' })
    expect(await said(ui, /^Guide$/)).toBe(false)
    expect(await has(ui, 'use')).toBe(false)
    expect(await said(ui, /^Resume$/)).toBe(true) // the other places stay
    await ui.unmount()
  })

  test(`${surface}: every card folds to its header and stays folded; the choice is kept in the store`, async ($, on) => {
    if (surface !== 'terminal') return // the desktop's HTML sections do not fold: every section is in view (tested below)
    const w = await harness($, on, ovState())
    const ui = await mountPane($, surface) // every section opened, as a person does
    expect(await labelOf(ui, 'fold-caret:resume')).toBe('▾') // the open caret beside the title, a grey button of its own
    await ui.press({ key: 'fold:resume' })
    expect(await labelOf(ui, 'fold-caret:resume')).toBe('▸') // the folded triangle
    expect(await said(ui, /^Resume$/)).toBe(true) // the header stays
    expect(await said(ui, /^2 need you$/)).toBe(true) // with its summary
    expect(await said(ui, /wiring the pane/)).toBe(false) // the body is gone
    expect(await said(ui, /^patch it$/)).toBe(true) // the other cards are untouched
    await ui.unmount()
    const again = await mountRaw($, surface)
    expect(await said(again, /wiring the pane/)).toBe(false)
    await again.press({ key: 'fold:resume' })
    expect(await said(again, /wiring the pane/)).toBe(true)
    await again.unmount()
    expect(w.runs).toEqual([])
  })

  test(`${surface}: a fresh pane shows Guide open and Resume, Spawns, Decisions, Overrides folded; a press on a header opens it`, async ($, on) => {
    if (surface !== 'terminal') return // the desktop's HTML sections do not fold: every section is in view (tested below)
    await harness($, on, ovState())
    const ui = await mountRaw($, surface)
    expect(await labelOf(ui, 'fold:guide')).toBe('Guide')
    expect(await labelOf(ui, 'fold-caret:guide')).toBe('▾')
    for (const [id, title] of [['resume', 'Resume'], ['spawns', 'Spawns'], ['overrides', 'Overrides']]) {
      expect(await labelOf(ui, `fold:${id}`)).toBe(title)
      expect(await labelOf(ui, `fold-caret:${id}`)).toBe('▸')
    }
    expect(await said(ui, /^2 need you$/)).toBe(true) // a folded section keeps its summary
    expect(await said(ui, /^3 spawns · \$0\.41$/)).toBe(true)
    expect(await said(ui, /wiring the pane/)).toBe(false) // and shows no body
    expect(await said(ui, /^patch it$/)).toBe(false)
    expect(await has(ui, 'edit-overrides')).toBe(false)
    await ui.press({ key: 'fold:resume' })
    expect(await labelOf(ui, 'fold-caret:resume')).toBe('▾')
    expect(await said(ui, /wiring the pane/)).toBe(true)
    expect(await labelOf(ui, 'fold-caret:spawns')).toBe('▸') // the others stay folded
    await ui.unmount()
  })

  test(`${surface}: the sections are flat, with one rule between each pair and a triangle that toggles (title or caret)`, async ($, on) => {
    if (surface !== 'terminal') return // the desktop's HTML sections do not fold: every section is in view (tested below)
    await harness($, on, ovState())
    const ui = await mountPane($, surface)
    expect(await labelOf(ui, 'fold-caret:resume')).toBe('▾')
    expect(await propOf(ui, 'fold-caret:resume', 'dimColor')).toBe(true) // grey, as the native caret
    if (surface === 'desktop') {
      const rules = (await ui.findAll({ type: 'Svg' })).filter((x: any) => x.props.alt === 'section divider')
      const heads = (await ui.findAll({ type: 'Button' })).filter((x: any) => /^fold:(guide|resume|decisions|spawns|overrides)$/.test(String(x.props.key ?? '')))
      expect(rules.length).toBe(heads.length - 1) // none above the first, none below the last
    }
    await ui.press({ key: 'fold-caret:resume' }) // the caret folds it like the title
    expect(await labelOf(ui, 'fold-caret:resume')).toBe('▸')
    expect(await said(ui, /wiring the pane/)).toBe(false)
    expect(await said(ui, /^2 need you$/)).toBe(true) // the summary is a Text: coloured where it means something
    await ui.press({ key: 'fold:resume' })
    expect(await labelOf(ui, 'fold-caret:resume')).toBe('▾')
    await ui.unmount()
  })

  test(`${surface}: a fold an earlier session kept in the store is honoured at the start`, async ($, on) => {
    if (surface !== 'terminal') return // the desktop's HTML sections do not fold: every section is in view (tested below)
    await harness($, on, ovState(), { store: { paneFolds: { resume: true, spawns: false, 'more:needs': true, junk: 'x' } } })
    const ui = await mountRaw($, surface)
    expect(await said(ui, /^patch it$/)).toBe(false)
    expect(await labelOf(ui, 'fold-caret:spawns')).toBe('▸')
    expect(await said(ui, /^pick the cap$/)).toBe(true)
    await ui.unmount()
  })

  test(`${surface}: long lists show their first rows and a Show all; nothing is cut or keeps markdown marks`, async ($, on) => {
    const long = 'Confirm the Kurdish app name "مرۆڤ" with the store team before the build goes out to review, and keep the old name in the release notes'
    const needs = Array.from({ length: 11 }, (_, i) => ({ n: i + 3, text: i === 0 ? `**Your decision**, \`next build\` ${long}` : `decision ${i + 3}` }))
    const rows = Array.from({ length: 8 }, (_, i) => ({ ...ROWS[1], ts: NOW - 1000 + i, description: `step ${i}`, task: 'Ship it' }))
    await harness($, on, { guide: guideOf([item({ p: '🟠', text: long, id: 'dec:1' }), item({ id: 'a' }), item({ id: 'b' }), item({ id: 'c' })]), pane: panePayload({ resume: { ...panePayload().resume, needs, needs_open: 11 }, spawns: { live: [], rows, totals: { spawns: 8, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) })
    const ui = await mountPane($, surface, { bodyColumns: 160 }) // wide: both long lines fit two lines, shown whole
    expect(await said(ui, new RegExp(`^${long}$`))).toBe(true) // the top guide item in full, after its dot
    expect(await said(ui, new RegExp(`^Your decision, next build ${long}$`))).toBe(true) // whole, ** and \` dropped
    expect(await said(ui, /^Needs you$/)).toBe(true)
    expect(await said(ui, /^11 need you$/)).toBe(true)
    expect(await said(ui, /^decision 5$/)).toBe(true)
    expect(await said(ui, /^decision 6$/)).toBe(false) // past the first three
    expect(await labelOf(ui, 'more:needs')).toBe('Show all 11')
    await ui.press({ key: 'more:needs' })
    expect(await said(ui, /^decision 13$/)).toBe(true)
    expect(await labelOf(ui, 'more:needs')).toBe('Show fewer') // a list's toggle, never read as a text's Show less
    // the guide's other items: two, then Show all
    expect(await labelOf(ui, 'more:guide')).toBe('Show all 4')
    expect(await said(ui, /^4 open$/)).toBe(true)
    // the history: the newest five rows, then Show all
    expect(await said(ui, /^step 7$/)).toBe(true)
    expect(await said(ui, /^step 3$/)).toBe(true)
    expect(await said(ui, /^step 2$/)).toBe(false)
    expect(await labelOf(ui, 'more:history')).toBe('Show all 8')
    await ui.press({ key: 'more:history' })
    expect(await said(ui, /^step 0$/)).toBe(true)
    await ui.unmount()
  })

  test(`${surface}: the editor page groups the keys, folds a group, and Back keeps the draft`, async ($, on) => {
    await harness($, on, ovState(ovKeys([AGENTS, GUIDE_PLACE, { key: 'Newer key', kind: 'text', options: [], value: '', source: 'default', default: '' }])))
    const ui = await mountEditor($, surface)
    for (const g of ['Agents', 'Output', 'Where it shows', 'More', 'Other overrides']) expect(await said(ui, new RegExp(`^${g}$`))).toBe(true)
    expect(await said(ui, /^Session$/)).toBe(false) // no key of it in this table
    expect(await said(ui, /^1 set$/)).toBe(true) // Output: Receipt is set in the project file
    await ui.press({ key: 'fold:g:Agents' })
    expect(await has(ui, 'sel:Agents')).toBe(false)
    expect(await has(ui, 'in:Parallel')).toBe(false)
    expect(await has(ui, 'sel:Receipt')).toBe(true)
    await ui.press({ key: 'fold:g:Agents' })
    await ui.input({ key: 'in:Parallel', text: '6', kind: 'change' })
    await ui.press({ key: 'back' })
    expect(await said(ui, /^1 unsaved$/)).toBe(true) // the main page's card says so
    await ui.press({ key: 'edit-overrides' })
    expect(await valueOf(ui, 'in:Parallel')).toBe('6')
    expect(await propOf(ui, 'in:Newer key', 'placeholder')).toBe('none') // a key without a default
    await ui.unmount()
  })

  test(`${surface}: a live spawn without a start says running; the Memo button is primary when nothing else is open`, async ($, on) => {
    const live = { live: [{ side: 'Work', model: 'sonnet', effort: 'high', description: 'build the card', ts: null }], rows: [], totals: { spawns: 0, tokens: 0, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } }
    const w = await harness($, on, { guide: guideOf([item({ p: '✅', text: 'all clear', id: 'ok:a' })], { ctx: { tokens: 480000, mark: 500 } }), pane: panePayload({ spawns: live }) })
    const ui = await mountPane($, surface)
    expect(await said(ui, /^build the card$/)).toBe(true)
    expect(await said(ui, /^Sonnet 5\.5 · High · running$/)).toBe(true) // no start: the meta line says running
    expect(await labelOf(ui, 'memo')).toBe('Save memo')
    expect(await said(ui, /^Near the next mark: save the memo, then \/compact\.$/)).toBe(true)
    expect(await propOf(ui, 'memo', 'variant')).toBe('primary')
    await ui.unmount()
    w.state = { guide: guideOf([item({ id: 'esc:open' })], { ctx: { tokens: 480000, mark: 500 } }), pane: panePayload() }
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `t-memo-${surface}`, reason: 'answered' } as never)
    const open = await mountPane($, surface)
    expect(await propOf(open, 'memo', 'variant')).toBe('secondary') // an open item comes first
    expect(await propOf(open, 'use', 'variant')).toBe('primary')
    await open.unmount()
  })
}

test('a journal receipt line reads as a table row (time, spawns, $, saved), its done / check / open as details', () => {
  const line = '10-22 07:19 · 1 Spawn · 319K Tokens · $0.28 · Saved 46% ($0.24) vs Opus 5.5 · done: the pane · check: `79 pass` · open: none'
  expect(receiptOf(line)).toEqual({ time: '10-22 07:19', spawns: '1 spawn', usd: '$0.28', saved: '46%', text: '', details: ['done: the pane', 'check: 79 pass', 'open: none'] })
  expect(receiptOf('10-22 08:00 · 11 Spawns · $7.96 · Saved 27% ($2.93) vs Opus 5.5').spawns).toBe('11 spawns')
  expect(receiptOf('10-22 08:00 · done: only a note')).toEqual({ time: '10-22 08:00', spawns: null, usd: null, saved: null, text: 'done: only a note', details: [] })
  expect(receiptOf('wrote cards')).toEqual({ time: null, spawns: null, usd: null, saved: null, text: 'wrote cards', details: [] })
  expect(headParts('📍 **Resume** · memo 2026-10-22 07:19 · away 2 days · session 8e23c250 · now written 2026-10-22 07:19 from receipt')).toEqual({ memo: '2026-10-22 07:19', away: '2 days', session: '8e23c250' })
  expect(fmtWhen('10-22 07:19')).toBe('Oct 22 07:19')
  expect(fmtWhen('2026-10-24 10:32', true)).toBe('Oct 24, 10:32')
  expect(fmtWhen('soon')).toBe('soon')
})

for (const surface of SURFACES) {
  test(`${surface}: Last receipts are one row each (caret, time, spawns, $, saved); a row's caret opens its details`, async ($, on) => {
    const last = ['10-22 07:19 · 1 Spawn · 319K Tokens · $0.28 · Saved 46% ($0.24) vs Opus 5.5 · done: the pane · check: 79 pass']
    const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ resume: { ...panePayload().resume, last } }) })
    const ui = await mountPane($, surface)
    for (const re of [/^Last receipts$/, /^Oct 22 07:19$/, /^1 spawn$/, /^\$0\.28$/, /^46%( saved)?$/]) expect(await said(ui, re)).toBe(true)
    if (surface !== 'terminal') {
      // the desktop: a card per receipt, what was done as its headline and the rest as labelled rows, no caret to press
      expect(await said(ui, /^done: the pane$/)).toBe(true)
      expect(await has(ui, 'rcpt:10-22 07:19:0')).toBe(false)
      const src = String((await ui.findAll({ type: 'Svg' })).find((x: any) => /^Oct 22 07:19\n/.test(String(x.props.alt)))?.props.source)
      expect(src).toContain('<span class="lbl t-blue">check</span>')
      expect(src).not.toContain('>done</span>') // done is the headline, not a label
      expect(await labelOf(ui, 'detail:receipt:0')).toBe('Full details') // every receipt opens on a page of its own
      await ui.unmount()
      // a long detail: Full details, right under that card, opens the whole receipt as a page; Back returns
      const long = Array.from({ length: 30 }, (_, i) => `step${i}`).join(' ')
      w.state = { guide: guideOf([item()]), pane: panePayload({ resume: { ...panePayload().resume, last: [`10-22 07:19 · 1 Spawn · $0.28 · done: the pane · open: ${long}`] } }) }
      await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 'rcpt-long', reason: 'answered' } as never)
      const lg = await mountPane($, surface)
      await lg.press({ key: 'detail:receipt:0' })
      const text = String((await lg.find({ type: 'Markdown' }))?.props.text)
      expect(text).toContain(long) // the whole text, nothing clamped
      expect(text).toContain('**Open**')
      expect(text).toContain('**Oct 22, 07:19** · **$0.28** · 1 spawn')
      expect(await labelOf(lg, 'detail-back')).toBe('‹ Resume') // back to the cards, named by the page it returns to
      expect(await has(lg, 'use')).toBe(false) // a page of its own
      await lg.press({ key: 'detail-back' })
      expect(await has(lg, 'use')).toBe(true)
      expect(await lg.find({ type: 'Markdown' })).toBeUndefined()
      return lg.unmount()
    }
    expect(await said(ui, /^done: the pane$/)).toBe(false)
    await ui.press({ key: 'rcpt:10-22 07:19:0' })
    expect(await said(ui, /^done: the pane$/)).toBe(true)
    expect(await said(ui, /^check: 79 pass$/)).toBe(true)
    expect(await labelOf(ui, 'rcpt:10-22 07:19:0')).toBe('▾') // the row's caret, open
    expect(await propOf(ui, 'rcpt:10-22 07:19:0', 'dimColor')).toBe(true)
    await ui.press({ key: 'rcpt:10-22 07:19:0' })
    expect(await said(ui, /^done: the pane$/)).toBe(false)
    expect(await said(ui, /^1 spawn$/)).toBe(true) // the row stays
    await ui.unmount()
  })
}

for (const surface of SURFACES) {
  test(`${surface}: two receipts in the same minute get distinct keys and open on their own`, async ($, on) => {
    if (surface !== 'terminal') return // the desktop shows both rows' details at once: no keys to tell apart
    const last = ['10-22 07:19 · 1 Spawn · $0.28 · done: first one', '10-22 07:19 · 2 Spawns · $0.50 · done: second one']
    await harness($, on, { guide: guideOf([item()]), pane: panePayload({ resume: { ...panePayload().resume, last } }) })
    const ui = await mountPane($, surface)
    expect(await has(ui, 'rcpt:10-22 07:19:0')).toBe(true)
    expect(await has(ui, 'rcpt:10-22 07:19:1')).toBe(true)
    await ui.press({ key: 'rcpt:10-22 07:19:1' })
    expect(await said(ui, /^done: second one$/)).toBe(true)
    expect(await said(ui, /^done: first one$/)).toBe(false)
    await ui.unmount()
  })
}

test('history groups rows by day: one muted header per day, the rows under it show only the time', async ($, on) => {
  const day = 86400
  const rows = [
    { ...ROWS[0], ts: NOW - 3 * day, description: 'old one' },
    { ...ROWS[1], ts: NOW - day, description: 'mid one' },
    { ...ROWS[2], ts: NOW - day + 60, description: 'mid two' },
    { ...ROWS[2], ts: NOW, description: 'new one' },
  ]
  await harness($, on, { guide: guideOf([item()]), pane: panePayload({ spawns: { live: [], rows, totals: { spawns: 4, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0, by_model: [] } } }) })
  const desk = await mountPane($, 'desktop') // the desktop's card: the same day captions and order in its alt
  const dl = (await altLines(desk)).filter(l => /^(Today|Yesterday|old one|mid one|mid two|new one|[A-Z][a-z]{2} \d{1,2})$/.test(l))
  expect(dl[0]).toBe('Today')
  expect(dl[1]).toBe('new one')
  expect(dl[2]).toBe('Yesterday')
  await desk.unmount()
  const ui = await mountPane($, 'terminal')
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const d = new Date((NOW - 3 * day) * 1000)
  const labels = (await ui.findAll({ type: 'Text', text: /^(Today|Yesterday|[A-Z][a-z]{2} \d{1,2})$/ })).map((x: any) => x.text)
  expect(labels).toEqual(['Today', 'Yesterday', `${MON[d.getMonth()]} ${d.getDate()}`]) // three days, three headers (two rows share one)
  const order = (await ui.findAll({ type: 'Text', text: /^(Today|Yesterday|old one|mid one|mid two|new one|[A-Z][a-z]{2} \d{1,2})$/ })).map((x: any) => x.text)
  expect(order.slice(0, 2)).toEqual(['Today', 'new one'])
  expect(order[2]).toBe('Yesterday')
  expect(order.slice(3, 5).sort()).toEqual(['mid one', 'mid two'])
  expect(order[5]).toMatch(/^[A-Z][a-z]{2} \d{1,2}$/)
  expect(order[6]).toBe('old one')
  expect(await said(ui, /^[A-Z][a-z]{2} \d{1,2} \d\d:\d\d$/)).toBe(false) // no date on a row, only the time
  await ui.unmount()
})

test('a history row meta line: time, the model as the app names it, tokens, the status word only when it means something', async ($, on) => {
  const base = { ...ROWS[0], side: 'Work', model: 'opus', effort: 'xhigh', tokens: 810000, usd: 0.1 }
  const rows = [
    { ...base, ts: NOW - 40, description: 'plain', status: 'done', verdict: null },
    { ...base, ts: NOW - 30, description: 'passed', status: 'done', verdict: 'PASS' },
    { ...base, ts: NOW - 20, description: 'failed', status: 'done', verdict: 'FAIL' },
    { ...base, ts: NOW - 10, description: 'part', status: 'partial', verdict: null },
  ]
  await harness($, on, { guide: guideOf([item()]), pane: panePayload({ spawns: { live: [], rows, totals: { spawns: 4, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0, by_model: [] } } }) })
  const ui = await mountPane($, 'desktop')
  const lines = (await altLines(ui)).filter(l => /^\d\d:\d\d · Opus 5\.5 · Extra · 810K tokens/.test(l)).map(l => l.replace(/^\d\d:\d\d/, 'T'))
  expect(lines).toEqual(['T · Opus 5.5 · Extra · 810K tokens · PARTIAL', 'T · Opus 5.5 · Extra · 810K tokens · FAIL', 'T · Opus 5.5 · Extra · 810K tokens · PASS', 'T · Opus 5.5 · Extra · 810K tokens']) // newest first; DONE has no word
  const src = String((await ui.findAll({ type: 'Svg' })).find((x: any) => /^History\n/.test(String(x.props.alt)))?.props.source)
  for (const [word, tone] of [['PASS', 'green'], ['FAIL', 'red'], ['PARTIAL', 'amber']]) expect(src).toContain(`<span class="word ink t-${tone}">${word}</span>`) // the word in its tone
  await ui.unmount()
  const term = await mountPane($, 'terminal')
  expect(await said(term, /^\d\d:\d\d · Opus 5\.5 · Extra · 810K tokens · PASS$/)).toBe(true) // the terminal: the same line, no Svg
  expect(await term.find({ type: 'Svg' })).toBeUndefined()
  await term.unmount()
})

test('a history row keeps its Read more state when a newer row is prepended (keyed by ts + text, not position)', async ($, on) => {
  const desc = 'rebuild the whole spawn pipeline so that every long running agent reports back through the shared ledger before the next turn starts'
  const old = { ...ROWS[0], description: desc }
  const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ spawns: { live: [], rows: [old], totals: { spawns: 1, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) })
  const key = `more:spawn:${old.ts}:${shortHash(`${old.side} · ${desc}`)}`
  const ui = await mountPane($, 'terminal') // the native rows' own Read more (the desktop's card has one per section)
  expect(await moreOf(ui, key)).toBe('Read more')
  await ui.press({ key })
  expect(await moreOf(ui, key)).toBe('Show less')
  await ui.unmount()
  w.state = { guide: guideOf([item()]), pane: panePayload({ spawns: { live: [], rows: [old, { ...ROWS[1], ts: NOW - 10 }], totals: { spawns: 2, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) }
  const again = await mountPane($, 'terminal')
  expect(await moreOf(again, key)).toBe('Show less') // still open: a new top row moved nothing
  await again.unmount()
})

test('Read more: text at most ~20% over the limit is shown whole; a two-row text is cut at a word, never between a letter and its mark', async ($, on) => {
  const limit = 60 - 4 - 3 // a guide item under the top one: one row of the card, less the dot column
  const near = 'a'.repeat(Math.floor(limit * 1.1))
  const arabic = 'x' + 'بَ'.repeat(90) // one base then base+mark pairs
  await harness($, on, { guide: guideOf([item({ id: 'top', text: 'the top item' }), item({ p: '🟠', id: 'near', text: near })]), pane: panePayload({ resume: { ...panePayload().resume, needs: [{ n: 1, text: arabic }] } }) })
  const ui = await mountPane($, 'terminal') // the native rows' cut (the desktop's card clamps with CSS)
  expect(await said(ui, new RegExp(`^${near}$`))).toBe(true)
  expect(await has(ui, 'more:guide:near')).toBe(false)
  const cut = (await ui.findAll({ type: 'Text', text: /^x.*…$/ }))[0]?.text as string // Needs you shows two rows: cut by code
  expect(cut).toBeDefined()
  expect(/\p{M}…$/u.test(cut)).toBe(true) // ends on a whole letter + mark, not a bare letter
  expect(arabic.startsWith(cut.slice(0, -1))).toBe(true)
  expect(await moreOf(ui, 'more:resume:needs:1')).toBe('Read more')
  await ui.unmount()
})

const ROGUE = [['sh', '-c', 'touch /tmp/x'], ['bash', '/x/plugins/abofles/scripts/py', '/tmp/evil.py'], ['bash', '/tmp/scripts/py', '/tmp/scripts/memo.py'], ['bash', '/x/plugins/abofles/scripts/py', '/y/plugins/abofles/scripts/memo.py']]
for (const argv of ROGUE) {
  test(`an argv in the state file runs only in script_cmd's shape: ${argv.join(' ')} is dropped, so a press never runs it`, async ($, on) => {
    const w = await harness($, on, { guide: guideOf([item({ id: `r:${argv[2]}` })], { last_resolved: { text: 'looks resolved', unresolve: argv, ts: 9 } }), pane: panePayload({ cmd: { overrides: argv } }) })
    const ui = await mountPane($, 'desktop')
    expect(await said(ui, /✓ resolved/)).toBe(false) // no Undo row to press
    await ui.press({ key: 'edit-overrides' })
    await ui.select({ key: 'sel:Receipt', value: 'full' })
    await ui.press({ key: 'save' })
    expect(w.runs).toEqual([])
    expect(w.toasts).toContain('Update the abofles plugin to save here')
    await ui.press({ key: 'reset' })
    await ui.press({ key: 'back' })
    await ui.unmount()
  })
}

// ---- Check all and Decisions

const FILL_ALL = 'abofles guide — check all: one, two'
const dec = (i: number, over: object = {}) => ({ ts: `10-${String(10 + (i % 18)).padStart(2, '0')} 09:${String(i % 60).padStart(2, '0')}`, q: `question ${i}`, a: `answer ${i}`, sid: 'sid-pane', ...over })
const decisions = (you: object[], judge: object[], more: object = {}) => ({ you, judge, n_you: you.length, n_judge: judge.length, ...more })

for (const surface of SURFACES) {
  test(`${surface}: Check all is hidden with one item, shown with two, fills the prompt box and does not submit`, async ($, on) => {
    const w = await harness($, on, { guide: guideOf([item()], { all: { n: 1, fill: FILL_ALL } }), pane: panePayload() })
    const one = await mountPane($, surface)
    expect(await has(one, 'check-all')).toBe(false)
    expect(await has(one, 'use')).toBe(true)
    await one.unmount()
    w.state = { guide: guideOf([item({ id: 'a' }), item({ id: 'b', text: 'second' })], { all: { n: 2, fill: FILL_ALL } }), pane: panePayload() }
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `ca-${surface}`, reason: 'answered' } as never)
    const ui = await mountPane($, surface)
    expect(await labelOf(ui, 'check-all')).toBe('Check all (2)')
    expect(await propOf(ui, 'check-all', 'variant')).toBe('primary')
    for (const key of ['use', 'copy']) expect(await has(ui, key)).toBe(true) // the other buttons stay
    expect(await propOf(ui, 'use', 'variant')).toBe('secondary') // one primary in the row
    await ui.press({ key: 'check-all' })
    expect(w.fills).toEqual([{ text: FILL_ALL, mode: 'replace' }]) // filled, never sent
    expect(w.runs).toEqual([])
    expect(w.toasts).toEqual([])
    expect(await has(ui, 'check-all')).toBe(false) // a landed fill hides the guide, as Use does
    expect(await said(ui, /Hidden until the list changes/)).toBe(true)
    await ui.unmount()
  })

  test(`${surface}: a guide without "all" (older hooks) or with a malformed one draws no Check all`, async ($, on) => {
    const w = await harness($, on, { guide: guideOf([item({ id: 'a' }), item({ id: 'b' })]), pane: panePayload() })
    const ui = await mountPane($, surface)
    expect(await has(ui, 'check-all')).toBe(false)
    expect(await has(ui, 'use')).toBe(true)
    await ui.unmount()
    for (const [n, all] of [['bad1', { n: 'two', fill: FILL_ALL }], ['bad2', { n: 3 }], ['bad3', { n: 3, fill: '  ' }], ['bad4', 'x']] as const) {
      w.state = { guide: guideOf([item({ id: `${n}a` }), item({ id: `${n}b` })], { all }), pane: panePayload() }
      await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `${n}-${surface}`, reason: 'answered' } as never)
      const bad = await mountPane($, surface)
      expect(await has(bad, 'check-all')).toBe(false)
      expect(await has(bad, 'use')).toBe(true)
      await bad.unmount()
    }
  })

  test(`${surface}: the Resume card's Needs you list has a Check all when the hook gave the combined text`, async ($, on) => {
    const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload() })
    const none = await mountPane($, surface)
    expect(await has(none, 'check-needs')).toBe(false) // no needs_fill: no button
    await none.unmount()
    w.state = { guide: guideOf([item()]), pane: panePayload({ resume: { ...panePayload().resume, needs_fill: 'abofles — decide: pick the cap; name the key' } }) }
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `rn-${surface}`, reason: 'answered' } as never)
    const ui = await mountPane($, surface)
    expect(await labelOf(ui, 'check-needs')).toBe('Check all (2)')
    await ui.press({ key: 'check-needs' })
    expect(w.fills).toEqual([{ text: 'abofles — decide: pick the cap; name the key', mode: 'replace' }])
    expect(w.runs).toEqual([])
    expect(await said(ui, /Hidden until the list changes/)).toBe(true) // the same hide-on-land as Use
    await ui.unmount()
  })

  test(`${surface}: Decisions draws By you and By Judge, five rows each, then Show all`, async ($, on) => {
    const you = Array.from({ length: 7 }, (_, i) => dec(i))
    const judge = [dec(0, { q: 'judge: which cap?', a: 'five', ts: '10-11 08:00' }), ...Array.from({ length: 2 }, (_, i) => dec(i + 100))]
    await harness($, on, { guide: guideOf([item()]), pane: panePayload({ decisions: decisions(you, judge) }) })
    const ui = await mountPane($, surface)
    expect(await said(ui, /^Decisions$/)).toBe(true)
    expect(await said(ui, /^10 · 3 by Judge$/)).toBe(true)
    expect(await said(ui, /^By you$/)).toBe(true)
    expect(await said(ui, /^By Judge$/)).toBe(true)
    expect(await said(ui, /^7$/)).toBe(true) // the group counts
    expect(await said(ui, /^question 0$/)).toBe(true) // the question, then the answer after an arrow
    expect(await said(ui, /^answer 0$/)).toBe(true)
    if (surface === 'terminal') expect(await said(ui, /^→$/)).toBe(true) // the desktop's card draws its arrow
    expect(await said(ui, /^Oct 10 09:00$/)).toBe(true)
    expect(await said(ui, /^question 4$/)).toBe(true)
    expect(await said(ui, /^question 5$/)).toBe(false) // past the fifth
    expect(await labelOf(ui, 'more:dec-you')).toBe('Show all 7')
    expect(await said(ui, /^which cap\?$/)).toBe(true) // the "judge: " lead is dropped
    expect(await said(ui, /^five$/)).toBe(true)
    expect(await said(ui, /judge:/)).toBe(false)
    expect(await has(ui, 'more:dec-judge')).toBe(false) // three rows: no fold
    await ui.press({ key: 'more:dec-you' })
    expect(await said(ui, /^question 6$/)).toBe(true)
    expect(await labelOf(ui, 'more:dec-you')).toBe('Show fewer')
    await ui.press({ key: 'more:dec-you' })
    expect(await said(ui, /^question 6$/)).toBe(false)
    await ui.unmount()
  })

  test(`${surface}: a Decisions group with no rows says so; no decisions in the state means no card`, async ($, on) => {
    const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ decisions: decisions([dec(1)], []) }) })
    const ui = await mountPane($, surface)
    expect(await said(ui, /^question 1$/)).toBe(true)
    expect(await said(ui, /^No decisions yet$/)).toBe(true) // By Judge is empty
    await ui.unmount()
    w.state = { guide: guideOf([item()]), pane: panePayload() } // older hooks: no decisions at all
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `nd-${surface}`, reason: 'answered' } as never)
    const none = await mountPane($, surface)
    expect(await said(none, /^Decisions$/)).toBe(false)
    expect(await has(none, 'fold:decisions')).toBe(false)
    expect(await said(none, /^By you$/)).toBe(false)
    await none.unmount()
  })

  test(`${surface}: malformed decisions are dropped, the valid ones kept, each group held to 50`, async ($, on) => {
    const many = Array.from({ length: 60 }, (_, i) => dec(i))
    const w = await harness($, on, { guide: guideOf([item()]), pane: panePayload({ decisions: { you: [7, null, { ts: '10-10 09:00', q: 'no answer' }, { ts: 5, q: 'x', a: 'y' }, dec(1)], judge: 'no', n_you: 'many', n_judge: 4 } }) })
    const ui = await mountPane($, surface)
    expect(await said(ui, /^question 1$/)).toBe(true)
    expect(await said(ui, /^no answer$|^y$/)).toBe(false)
    expect(await said(ui, /^No decisions yet$/)).toBe(true) // the judge group was no list
    expect(await said(ui, /^1$/)).toBe(true) // n_you fell back to the rows kept
    expect(await said(ui, /^4$/)).toBe(true) // n_judge kept
    await ui.unmount()
    w.state = { guide: guideOf([item()]), pane: panePayload({ decisions: 'garbage' }) }
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `md-${surface}`, reason: 'answered' } as never)
    const bad = await mountPane($, surface)
    expect(await said(bad, /^Decisions$/)).toBe(false)
    await bad.unmount()
    w.state = { guide: guideOf([item()]), pane: panePayload({ decisions: { you: many, judge: [], n_you: 60, n_judge: 0 } }) }
    await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: `mx-${surface}`, reason: 'answered' } as never)
    const cap = await mountPane($, surface)
    expect(await labelOf(cap, 'more:dec-you')).toBe('Show all 50')
    await cap.unmount()
  })
}

test('the editor explains the Budget raise and Git guard keys in the Agents group', async ($, on) => {
  const raise = { key: 'Budget raise', kind: 'select', options: ['auto', 'ask'], value: 'auto', source: 'default', default: 'auto' }
  const git = { key: 'Git guard', kind: 'select', options: ['warn', 'deny', 'off'], value: 'warn', source: 'default', default: 'warn' }
  await harness($, on, ovState(ovKeys([raise, git])))
  const ui = await mountEditor($, 'desktop')
  expect(await said(ui, /^Budget raise$/)).toBe(true)
  expect(await said(ui, /^auto: \+half the start budget, twice at most, then asks; ask: always asks$/)).toBe(true)
  expect(await said(ui, /^Git guard$/)).toBe(true)
  expect(await said(ui, /^warn or deny git writes outside the git agent; off$/)).toBe(true)
  expect(await has(ui, 'sel:Budget raise')).toBe(true)
  expect(await has(ui, 'sel:Git guard')).toBe(true)
  await ui.unmount()
})

// ---- Read more, header icons, dots

// The desktop draws the Guide as one HTML card (an Svg): its rows cut at the real width by CSS, so these two hold for the terminal's
// native rows; the card's own Read more is tested below.
test('desktop: the Guide is one HTML card; a long top item is clamped, Full details opens every item whole on a page; text is escaped', async ($, on) => {
  const LONG = 'Confirm the Kurdish app name with the store team before the build goes out to review, and keep the old name in the release notes so nobody is surprised'
  await harness($, on, { guide: guideOf([item({ id: 'top', text: `${LONG} ${LONG}` }), item({ p: '🟠', text: 'ship <b>R&D</b> notes', id: 'dec:1' })]), pane: panePayload() })
  const ui = await mountPane($, 'desktop', { bodyColumns: 40 })
  const card = async (u: any) => (await u.findAll({ type: 'Svg' })).find((x: any) => /^Next up, /.test(String(x.props.alt)) && /\nAlso open\n/.test(String(x.props.alt))) // the Guide page's card
  const before = await card(ui)
  expect(String(before.props.alt).split('\n')).toContain(`${LONG} ${LONG}`) // the alt carries the whole text
  expect(String(before.props.source)).toContain('-webkit-line-clamp:4')
  expect(String(before.props.source)).toContain('ship &lt;b&gt;R&amp;D&lt;/b&gt; notes') // escaped, never markup
  expect(String(before.props.source)).not.toMatch(/<script|<b>/)
  expect(await propOf(ui, 'detail:guide', 'label')).toBe('≡ Full details') // a button, its glyph first
  expect(await propOf(ui, 'detail:guide', 'variant')).toBe('secondary')
  await ui.press({ key: 'detail:guide' })
  const text = String((await ui.find({ type: 'Markdown' }))?.props.text)
  expect(text).toContain(`${LONG} ${LONG}`) // the whole top item
  expect(text).toContain('ship \\<b\\>R&D\\</b\\> notes') // markdown marks escaped: read as written
  await ui.press({ key: 'detail-back' })
  expect(await card(ui)).toBeDefined()
  expect(await has(ui, 'more:guide:dec:1')).toBe(false) // the other items are one line each, cut by CSS: no link
  await ui.unmount()
})

for (const surface of ['terminal'] as const) {
  const LONG = 'Confirm the Kurdish app name with the store team before the build goes out to review, and keep the old name in the release notes so nobody is surprised'
  test(`${surface}: a short description is shown whole; a long one is clipped to its row with Read more, opens to the full text and Show less, and is remembered`, async ($, on) => {
    await harness($, on, { guide: guideOf([item({ id: 'top', text: LONG }), item({ p: '🟠', text: LONG, id: 'dec:1' }), item({ id: 'b', text: 'short rest' })]), pane: panePayload() })
    const ui = await mountPane($, surface)
    expect(await said(ui, /^short rest$/)).toBe(true) // fits: whole, no link
    expect(await has(ui, 'more:guide:b')).toBe(false)
    const longs = async (u: any) => (await u.findAll({ type: 'Text', text: new RegExp(`^${LONG}$`) })).map((x: any) => x.props.wrap ?? 'wrap')
    expect(await longs(ui)).toEqual(['wrap', 'truncate-end']) // the top item whole (Use hands it over); the other the whole text, clipped by the surface at its row's real width
    expect(await moreOf(ui, 'more:guide:dec:1')).toBe('Read more')
    await ui.press({ key: 'more:guide:dec:1' })
    expect(await longs(ui)).toEqual(['wrap', 'wrap'])
    expect(await moreOf(ui, 'more:guide:dec:1')).toBe('Show less')
    await ui.unmount()
    const again = await mountPane($, surface) // remembered in the folds
    expect(await longs(again)).toEqual(['wrap', 'wrap'])
    await again.press({ key: 'more:guide:dec:1' })
    expect(await moreOf(again, 'more:guide:dec:1')).toBe('Read more')
    await again.unmount()
  })
}

for (const surface of ['terminal'] as const) {
  test(`${surface}: Read more is a small grey link of its own after the cut text, on its row; the text stays a Text; open, the full text and Show less`, async ($, on) => {
    const LONG = 'Confirm the Kurdish app name with the store team before the build goes out to review, and keep the old name in the release notes so nobody is surprised'
    await harness($, on, { guide: guideOf([item({ id: 'top', text: 'the top item' }), item({ p: '🟠', text: LONG, id: 'dec:1' })]), pane: panePayload() })
    const ui = await mountPane($, surface)
    const link = await ui.find({ key: 'more:guide:dec:1' })
    expect(link?.type).toBe('Button')
    expect(link?.props.label).toBe('Read more') // the link alone: the description is never inside a Button
    expect(link?.props.plain).toBe(true)
    expect(link?.props.dimColor).toBe(true)
    const cut = (await ui.findAll({ type: 'Text', text: new RegExp(`^${LONG}$`) }))[0]
    expect(cut).toBeDefined() // a Text of its own, the whole text
    expect(cut.props.wrap).toBe('truncate-end') // one row: the surface cuts it at the row's real width, so it uses all the room
    const order = (await ui.findAll({})).map((x: any) => (x.props?.key === 'more:guide:dec:1' ? 'link' : x.type === 'Text' && /^Confirm the Kurdish/.test(x.text ?? '') ? 'text' : null)).filter(Boolean)
    expect(order).toEqual(['text', 'link']) // the text, then its link at the row's end
    const boxes = (await ui.findAll({ type: 'Box' })).filter((b: any) => b.props.flexGrow === 1 && b.props.minWidth === 0)
    expect(boxes.length).toBeGreaterThan(0) // the text's box grows to fill the row: the link sits at the right edge
    await ui.press({ key: 'more:guide:dec:1' })
    expect(await said(ui, new RegExp(`^${LONG}$`))).toBe(true)
    expect(await labelOf(ui, 'more:guide:dec:1')).toBe('Show less')
    expect(await said(ui, /^Read more$/)).toBe(false)
    await ui.unmount()
  })
}

for (const surface of SURFACES) {
  test(`${surface}: a Decisions row has its time as a headline above the text, and a light divider between rows`, async ($, on) => {
    await harness($, on, { guide: guideOf([item()]), pane: panePayload({ decisions: decisions([dec(0), dec(1), dec(2)], []) }) })
    const ui = await mountPane($, surface)
    if (surface !== 'terminal') {
      // the desktop's card: time, question, answer per row (its alt in that order), a hairline between rows
      const lines = await altLines(ui)
      const at = (t: string) => lines.indexOf(t)
      expect(at('Oct 10 09:00')).toBeGreaterThan(-1)
      expect(at('question 0')).toBe(at('Oct 10 09:00') + 1)
      expect(at('answer 0')).toBe(at('question 0') + 1)
      const src = String((await ui.findAll({ type: 'Svg' })).find((x: any) => /^By you\n/.test(String(x.props.alt)))?.props.source)
      expect(src.split('class="hair"').length - 1).toBe(2) // three decisions: two hairlines
      return ui.unmount()
    }
    const texts = (await ui.findAll({ type: 'Text' })).map((x: any) => x.text)
    const at = (re: RegExp) => texts.findIndex(t => re.test(t))
    expect(at(/^Oct 10 09:00$/)).toBeGreaterThan(-1)
    expect(at(/^question 0$/)).toBe(at(/^Oct 10 09:00$/) + 1) // the headline, then the question
    expect(at(/^answer 0$/)).toBe(at(/^question 0$/) + 2) // then the arrow and the answer
    expect(at(/^Oct 11 09:01$/)).toBe(at(/^answer 0$/) + 2) // the divider sits between the rows
    await ui.unmount()
  })
}

test('desktop: each section is a header strip (icon tile, title, summary) over its cards, all open, no caret; the terminal draws none', async ($, on) => {
  await harness($, on, ovState())
  const desktop = await mountRaw($, 'desktop') // fresh: nothing pressed
  const heads = (await desktop.findAll({ type: 'Svg' })).filter((x: any) => /class="head"/.test(String(x.props.source)))
  expect(heads.map((x: any) => String(x.props.alt).split('\n')[0])).toEqual(['Home', 'Guide', 'Resume', 'Spawns', 'Overrides']) // one page each, in the nav bar's order
  expect(heads.every((x: any) => /class="htile t-\w+"/.test(x.props.source) && /stroke-linecap="round"/.test(x.props.source))).toBe(true)
  expect(await said(desktop, /wiring the pane/)).toBe(true) // every section in view at once
  expect(await said(desktop, /^patch it$/)).toBe(true)
  expect(await has(desktop, 'fold-caret:resume')).toBe(false) // no dropdown triangle
  expect(await has(desktop, 'fold:resume')).toBe(false)
  await desktop.unmount()
  const term = await mountPane($, 'terminal')
  expect((await term.findAll({ type: 'Svg' })).length).toBe(0)
  expect(await said(term, /^Guide$/)).toBe(true)
  expect(await said(term, /^Abo Fles · ابو فليس$/)).toBe(true) // the brand line as dim text, no picture
  await term.unmount()
})

test('every SVG colour has a light twin and a dark value, each >= 4.5:1 on white / #1a1a1a', () => {
  const lum = (hex: string): number => {
    const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
  }
  const ratio = (a: string, b: string): number => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05)
  for (const [name, { light, dark }] of Object.entries(COLOR_PAIRS)) {
    expect([name, ratio(light, '#ffffff') >= 4.5]).toEqual([name, true])
    expect([name, ratio(dark, '#1a1a1a') >= 4.5]).toEqual([name, true])
  }
})

test('desktop: a nav bar of icons shows one page at a time: each page its header icon, the one shown filled, a blank press area over each; Home sums up every section', async ($, on) => {
  await harness($, on, { guide: guideOf([item({ p: '🔴', text: 'open FAIL', id: 'fail:a' }), item({ text: 'then escalate' })], { all: { n: 2, fill: 'all' }, ctx: { tokens: 412000, mark: 500 }, task: { spawns: 3, usd: 0.41, budget: 5, left: 2 } }), pane: panePayload({ decisions: decisions([dec(0)], []) }) })
  const ui = await $.ui.mount({ plugin: 'abofles-guide', surface: 'desktop', component: 'Pane', requestId: 'abofles', props: PANE_PROPS }) // no tab seeking: the page as drawn
  const navs = (await ui.findAll({ type: 'Button' })).filter((b: any) => /^nav:/.test(String(b.props.key)))
  expect(navs.map((b: any) => b.props.key)).toEqual(['nav:home', 'nav:guide', 'nav:resume', 'nav:decisions', 'nav:spawns', 'nav:overrides'])
  expect(navs.every((b: any) => b.props.plain === true && /^\u2007+$/.test(b.props.label))).toBe(true) // a blank press area, no name
  expect(navs.map((b: any) => b.props.dimColor)).toEqual([false, true, true, true, true, true]) // the page shown is the one not dimmed
  const icons = (await ui.findAll({ type: 'Svg' })).filter((x: any) => x.props.width === 36)
  expect(icons.map((x: any) => x.props.alt)).toEqual(['Home, shown', 'Guide', 'Resume', 'Decisions', 'Spawns', 'Overrides'])
  expect(icons.every((x: any) => /class="htile t-\w+"/.test(x.props.source))).toBe(true) // the header strips' own tiles
  expect(icons[0].props.source).toContain('background:color-mix(in srgb,var(--c) 80%,#000);color:#fff') // filled: the page shown
  // Home: the next step with its buttons, the numbers at a glance, where the work stands, the latest decision and receipt
  const alts = (await ui.findAll({ type: 'Svg' })).map((x: any) => String(x.props.alt))
  expect(alts.some(a => /^Next up, urgent priority\nopen FAIL$/.test(a))).toBe(true)
  expect(alts.some(a => a.startsWith('At a glance') && a.includes('Needs you\n2') && a.includes('Running\n1 agent') && a.includes('Open FAIL\n1') && a.includes('Saved\n54% · $0.41 spent'))).toBe(true)
  expect(alts.some(a => a.startsWith('Now\nwiring the pane'))).toBe(true)
  expect(alts.some(a => a.startsWith('Last decision') && a.includes('answer 0'))).toBe(true)
  expect((await ui.find({ key: 'check-all' }))?.props.variant).toBe('primary')
  expect(await ui.find({ key: 'fold:guide' })).toBeUndefined()
  // a press on a glyph moves to that page; its cards slide in for a moment
  await ui.press({ key: 'nav:spawns' })
  expect((await ui.find({ key: 'nav:spawns' }))?.props.dimColor).toBe(false)
  expect((await ui.find({ key: 'nav:home' }))?.props.dimColor).toBe(true)
  const page = (await ui.findAll({ type: 'Svg' })).map((x: any) => String(x.props.alt))
  expect(page.some(a => a.startsWith('History'))).toBe(true)
  expect(page.some(a => a.startsWith('At a glance'))).toBe(false) // one page at a time
  const moved = (await ui.findAll({ type: 'Svg' })).filter((x: any) => x.props.width !== 36 && !String(x.props.alt).startsWith('Abo Fles'))
  expect(moved.every((x: any) => /class="root enter"/.test(x.props.source))).toBe(true) // the page's cards slide in; the nav bar and the brand footer stay still
  // the brand footer closes every page: the mascot inlined, the English and Arabic name, no card around it, drawn still
  const foot = (await ui.findAll({ type: 'Svg' })).filter((x: any) => String(x.props.alt) === 'Abo Fles · ابو فليس')
  expect(foot.length).toBe(1)
  expect(foot[0].props.source).toContain('class="foot"')
  expect(foot[0].props.source).toContain('src="data:image/png;base64,')
  expect(foot[0].props.source).toContain('ابو فليس')
  expect(foot[0].props.source).not.toContain('class="card"')
  expect(foot[0].props.source).not.toContain('root enter')
  await ui.unmount()
})
