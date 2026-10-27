import { expect, mock, test } from 'claude-code/testing'

import { fmtWhen, headParts, receiptOf } from './pane'

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

const mountPane = ($: any, surface: string, props: object = {}) => $.ui.mount({ plugin: 'abofles-guide', surface, component: 'Pane', requestId: 'abofles', props: { ...PANE_PROPS, ...props } })
const mountBand = ($: any, surface: string) => $.ui.mount({ plugin: 'abofles-guide', surface, component: 'AbovePrompt', props: BAND_PROPS })
const said = async (ui: any, re: RegExp) => (await ui.find({ type: 'Text', text: re })) !== undefined
const has = async (ui: any, key: string) => (await ui.find({ key })) !== undefined
const valueOf = async (ui: any, key: string) => (await ui.find({ key }))?.props.value
const propOf = async (ui: any, key: string, prop: string) => (await ui.find({ key }))?.props[prop]

test('every card draws from the state file, on every surface', async ($, on) => {
  await harness($, on, { guide: guideOf([item({ p: '🔴', text: 'open FAIL', id: 'fail:a' }), item({ text: 'then escalate' })], { ctx: { tokens: 412000, mark: 500 }, task: { spawns: 3, usd: 0.41, budget: 5, left: 2 } }), pane: panePayload() })
  for (const surface of SURFACES) {
    const ui = await mountPane($, surface)
    // Guide: the top item after a dot in its tone (no emoji), the rest dim, the numbers as label/value rows, the buttons
    expect(await said(ui, /^open FAIL$/)).toBe(true)
    expect(await said(ui, /^then escalate$/)).toBe(true)
    expect(await said(ui, /🔴|🟡/)).toBe(false)
    for (const re of [/^Context$/, /^412K \/ 500K$/, /^This task$/, /^3 spawns · \$0\.41$/, /^Agent budget$/, /^2 of 5 left$/]) expect(await said(ui, re)).toBe(true)
    // the meters and rules: SVG on the desktop (exact width, never wrapping), a row of ━ / ─ in the terminal (exact cells)
    if (surface === 'desktop') {
      const svgs = await ui.findAll({ type: 'Svg' })
      expect(svgs.some((x: any) => x.props.alt === 'Context 82% of the next mark' && x.props.height === 4)).toBe(true)
      expect(svgs.some((x: any) => /^Spend by model: Haiku 5\.5 2%, Sonnet 5\.5 98%, Opus 5\.5 0%$/.test(x.props.alt))).toBe(true)
      expect(svgs.some((x: any) => x.props.alt === 'divider' && x.props.height === 1)).toBe(true)
      expect(await said(ui, /^[━─]+$/)).toBe(false)
    } else {
      expect(await said(ui, /^━+$/)).toBe(true)
      expect(await said(ui, /^─+$/)).toBe(true)
    }
    for (const key of ['use', 'copy', 'hide']) expect(await has(ui, key)).toBe(true)
    expect(await propOf(ui, 'hide', 'plain')).toBe(true) // Hide is a link at the right, not a button among the actions
    // Resume: Now, Next, Needs you (numbers in their own column), Left, Last receipts, then the facts of the head
    expect(await said(ui, /wiring the pane/)).toBe(true)
    expect(await said(ui, /^pick the cap$/)).toBe(true)
    expect(await said(ui, /^1$/)).toBe(true)
    expect(await said(ui, /^name the key$/)).toBe(true)
    expect(await said(ui, /^3$/)).toBe(true)
    expect(await said(ui, /wrote cards/)).toBe(true)
    for (const re of [/^Session$/, /^sid-pane$/, /^Memo saved$/, /^Oct 20, 09:00$/]) expect(await said(ui, re)).toBe(true)
    expect(await said(ui, /now written/)).toBe(false) // the noisy part of the head is left out
    // Spawns: the saving first, the split by model, then Running and History (chip, ask, cost, dim detail), newest first
    for (const re of [/^54% saved$/, /^\$0\.41 of \$0\.90 on Opus 5\.5$/, /^Haiku 5\.5$/, /^Sonnet 5\.5$/, /^98%$/, /^Tokens$/, /^92K$/, /^Open FAIL$/]) expect(await said(ui, re)).toBe(true)
    expect(await said(ui, /^■$/)).toBe(true) // the model swatches
    expect(await said(ui, /^3 spawns$/)).toBe(true) // the card's summary
    expect(await said(ui, /^● LIVE$/)).toBe(true)
    expect(await said(ui, /^Work · build the card$/)).toBe(true)
    expect(await said(ui, new RegExp(`^${hhmm(NOW - 125)}$`))).toBe(true) // the start time, not an age that goes stale
    expect(await said(ui, /^sonnet·high$/)).toBe(true)
    expect(await said(ui, /Fix login/)).toBe(false) // a spawn's prompt line is no heading
    expect(await said(ui, /^Read · read the docs$/)).toBe(true)
    expect(await said(ui, /^haiku·low · 12K$/)).toBe(true)
    expect(await said(ui, /^\$0\.01$/)).toBe(true)
    expect(await said(ui, /^Work · patch it$/)).toBe(true)
    expect(await said(ui, /^PASS$/)).toBe(true)
    expect(await said(ui, /^sonnet·medium · 80K$/)).toBe(true)
    expect(await said(ui, /^Verify · check it$/)).toBe(true)
    expect(await said(ui, /^DONE$/)).toBe(true) // no verdict: the status, dim
    expect(await said(ui, /^opus·high$/)).toBe(true)
    expect(await said(ui, /^Updated \d\d:\d\d · refreshes when a turn ends$/)).toBe(true)
    const rows = (await ui.findAll({ type: 'Text', text: /^(Read|Work|Verify) · (read|patch|check)/ })).map((r: any) => r.text)
    expect(rows[0]).toBe('Verify · check it') // newest first
    expect(rows[rows.length - 1]).toBe('Read · read the docs')
    // Overrides: a short card on the main page (a table of what a file sets, the other lines), the editor one press away
    expect(await said(ui, /^Overrides$/)).toBe(true)
    for (const re of [/^Receipt$/, /^short$/, /^this project$/, /^1 set$/]) expect(await said(ui, re)).toBe(true)
    expect(await said(ui, /^Parallel$/)).toBe(false) // a default is not listed
    expect(await propOf(ui, 'edit-other', 'label')).toBe('1 other line · tiers, reviewers ›')
    expect(await propOf(ui, 'edit-overrides', 'label')).toBe('Edit')
    expect(await has(ui, 'sel:Receipt')).toBe(false)
    for (const key of ['fold:guide', 'fold:resume', 'fold:spawns', 'fold:overrides', 'edit-overrides']) expect(await has(ui, key)).toBe(true)
    // the editor page: ‹ Overrides, the scope buttons, settings rows (name and help on the left, the control on the right), the buttons
    await ui.press({ key: 'edit-overrides' })
    expect(await has(ui, 'fold:guide')).toBe(false) // the cards make room for the page
    expect(await propOf(ui, 'back', 'label')).toBe('‹ Overrides')
    expect(await propOf(ui, 'scope:project', 'variant')).toBe('primary')
    expect(await propOf(ui, 'scope:user', 'variant')).toBe('secondary')
    expect(await said(ui, /^CLAUDE\.md · the project file wins over yours$/)).toBe(true)
    expect(await said(ui, /^Receipt$/)).toBe(true) // the name beside the control
    expect(await propOf(ui, 'sel:Receipt', 'label')).toBeUndefined()
    expect(await valueOf(ui, 'sel:Receipt')).toBe('short')
    expect(await valueOf(ui, 'in:Parallel')).toBe('3')
    expect(await said(ui, /^Receipt form; savings N = only past N% · this project$/)).toBe(true) // the help, and the file that sets it
    expect(await said(ui, /^Background agents at once$/)).toBe(true) // a default: the help alone
    expect(await has(ui, 'raw')).toBe(false) // Other overrides: folded while this file has none of its lines
    expect(await said(ui, /^1 in all projects$/)).toBe(true) // its summary
    await ui.press({ key: 'fold:g:Other' })
    expect(await said(ui, /^Topic: Billing = T3 — in all projects; switch Save to, to edit it$/)).toBe(true)
    for (const key of ['back', 'save', 'ask', 'raw', 'fold:g:Agents', 'fold:g:Output', 'fold:g:Other']) expect(await has(ui, key)).toBe(true)
    expect(await propOf(ui, 'ask', 'label')).toBe('Ask Claude')
    expect(await has(ui, 'reset')).toBe(false) // nothing to discard
    await ui.press({ key: 'fold:g:Other' }) // as it was, for the next surface
    await ui.press({ key: 'back' })
    expect(await has(ui, 'fold:guide')).toBe(true)
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
  expect(await said(ui, /^DONE$/)).toBe(true) // a row with nothing but a status
  expect(await said(ui, /^\?$/)).toBe(true) // no model, no tokens: the detail line is a bare ?
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

test('Use, Copy, Hide and Undo work inside the pane', async ($, on) => {
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
  // Hide
  w.state = { guide: guideOf([item({ id: 'esc:hide' })]), pane: panePayload() }
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't-hide', reason: 'answered' } as never)
  const ui = await mountPane($, 'desktop')
  await ui.press({ key: 'hide' })
  expect(await has(ui, 'use')).toBe(false)
  expect(await propOf(ui, 'show', 'variant')).toBe('secondary') // the hidden card offers its way back
  await ui.press({ key: 'show' })
  expect(await has(ui, 'use')).toBe(true)
  expect(await has(ui, 'show')).toBe(false)
  expect(await said(ui, /Hidden until the list changes/)).toBe(false)
  await ui.press({ key: 'hide' })
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
  expect(await said(ui, /^Work · build the card$/)).toBe(true)
  expect(await said(ui, new RegExp(`^${hhmm(NOW - 125)}$`))).toBe(true)
  w.state = { guide: guideOf([item()]), pane: panePayload({ spawns: { live: [], rows: ROWS, totals: { spawns: 3, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) }
  await $.classic.SubagentStop({ stop_hook_active: false, agent_id: 'a1', agent_type: 'general', agent_transcript_path: '', last_assistant_message: '' } as never)
  expect(await said(ui, /build the card/)).toBe(false)
  expect(await said(ui, /^Read · read the docs$/)).toBe(true)
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
    expect(await propOf(ui, 'scope:project', 'variant')).toBe('primary')
    expect(await propOf(ui, 'scope:project', 'label')).toBe('This project')
    expect(await propOf(ui, 'scope:user', 'label')).toBe('All projects')
    // settings rows: the name is a Text beside the control, the control carries no label of its own
    expect(await said(ui, /^Save to$/)).toBe(true)
    for (const re of [/^Parallel$/, /^Receipt$/]) expect(await said(ui, re)).toBe(true)
    expect(await propOf(ui, 'sel:Receipt', 'label')).toBeUndefined()
    expect(await propOf(ui, 'in:Parallel', 'label')).toBeUndefined()
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
    expect(await propOf(ui, 'reset', 'label')).toBe('Discard')
    expect(await propOf(ui, 'save', 'label')).toBe('Save 1 change')
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
    expect(await propOf(ui, 'save', 'label')).toBe('Save 1 change') // free to press again
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
    expect(await propOf(ui, 'scope:user', 'variant')).toBe('primary')
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
    expect(await propOf(ui, 'scope:user', 'variant')).toBe('primary') // the target stays
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
      during = await propOf(ui, 'save', 'label')
      await ui.press({ key: 'save' }) // a second press does nothing
    }
    willSave(w, ovKeys())
    await ui.press({ key: 'save' })
    expect(during).toBe('Saving…')
    expect(w.runs.length).toBe(1)
    expect(await propOf(ui, 'save', 'label')).toBe('Save')
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
    const w = await harness($, on, ovState())
    const ui = await mountPane($, surface)
    expect(await said(ui, /^ ▾$/)).toBe(true) // the open caret beside the title
    await ui.press({ key: 'fold:resume' })
    expect(await said(ui, /^ ›$/)).toBe(true) // the folded chevron
    expect(await said(ui, /^Resume$/)).toBe(true) // the header stays
    expect(await said(ui, /^2 need you$/)).toBe(true) // with its summary
    expect(await said(ui, /wiring the pane/)).toBe(false) // the body is gone
    expect(await said(ui, /^Work · patch it$/)).toBe(true) // the other cards are untouched
    await ui.unmount()
    const again = await mountPane($, surface)
    expect(await said(again, /wiring the pane/)).toBe(false)
    await again.press({ key: 'fold:resume' })
    expect(await said(again, /wiring the pane/)).toBe(true)
    await again.unmount()
    expect(w.runs).toEqual([])
  })

  test(`${surface}: a fold an earlier session kept in the store is honoured at the start`, async ($, on) => {
    await harness($, on, ovState(), { store: { paneFolds: { spawns: false, 'more:needs': true, junk: 'x' } } })
    const ui = await mountPane($, surface)
    expect(await said(ui, /^Work · patch it$/)).toBe(false)
    expect(await said(ui, /^ ›$/)).toBe(true)
    expect(await said(ui, /^pick the cap$/)).toBe(true)
    await ui.unmount()
  })

  test(`${surface}: long lists show their first rows and a Show all; nothing is cut or keeps markdown marks`, async ($, on) => {
    const long = 'Confirm the Kurdish app name "مرۆڤ" with the store team before the build goes out to review, and keep the old name in the release notes'
    const needs = Array.from({ length: 11 }, (_, i) => ({ n: i + 3, text: i === 0 ? `**Your decision**, \`next build\` ${long}` : `decision ${i + 3}` }))
    const rows = Array.from({ length: 8 }, (_, i) => ({ ...ROWS[1], ts: NOW - 1000 + i, description: `step ${i}`, task: 'Ship it' }))
    await harness($, on, { guide: guideOf([item({ p: '🟠', text: long, id: 'dec:1' }), item({ id: 'a' }), item({ id: 'b' }), item({ id: 'c' })]), pane: panePayload({ resume: { ...panePayload().resume, needs, needs_open: 11 }, spawns: { live: [], rows, totals: { spawns: 8, tokens: 1, usd: 0, base_usd: 0, saved_pct: 0, open_fail: 0 } } }) })
    const ui = await mountPane($, surface)
    expect(await said(ui, new RegExp(`^${long}$`))).toBe(true) // the top guide item in full, after its dot
    expect(await said(ui, new RegExp(`^Your decision, next build ${long}$`))).toBe(true) // whole, ** and \` dropped
    expect(await said(ui, /^Needs you$/)).toBe(true)
    expect(await said(ui, /^11 need you$/)).toBe(true)
    expect(await said(ui, /^decision 5$/)).toBe(true)
    expect(await said(ui, /^decision 6$/)).toBe(false) // past the first three
    expect(await propOf(ui, 'more:needs', 'label')).toBe('Show all 11')
    await ui.press({ key: 'more:needs' })
    expect(await said(ui, /^decision 13$/)).toBe(true)
    expect(await propOf(ui, 'more:needs', 'label')).toBe('Show less')
    // the guide's other items: two, then Show all
    expect(await propOf(ui, 'more:guide', 'label')).toBe('Show all 4')
    expect(await said(ui, /^4 open$/)).toBe(true)
    // the history: the newest five rows, then Show all
    expect(await said(ui, /^Work · step 7$/)).toBe(true)
    expect(await said(ui, /^Work · step 3$/)).toBe(true)
    expect(await said(ui, /^Work · step 2$/)).toBe(false)
    expect(await propOf(ui, 'more:history', 'label')).toBe('Show all 8')
    await ui.press({ key: 'more:history' })
    expect(await said(ui, /^Work · step 0$/)).toBe(true)
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
    expect(await said(ui, /^Work · build the card$/)).toBe(true)
    expect(await said(ui, /^running$/)).toBe(true)
    expect(await propOf(ui, 'memo', 'label')).toBe('Save memo')
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
  test(`${surface}: Last receipts are table rows under their own caret; a row's caret opens its details; the card header reads as its title`, async ($, on) => {
    const last = ['10-22 07:19 · 1 Spawn · 319K Tokens · $0.28 · Saved 46% ($0.24) vs Opus 5.5 · done: the pane · check: 79 pass']
    await harness($, on, { guide: guideOf([item()]), pane: panePayload({ resume: { ...panePayload().resume, last } }) })
    const ui = await mountPane($, surface)
    for (const re of [/^Last receipts$/, /^Oct 22 07:19$/, /^1 spawn$/, /^\$0\.28$/, /^46%$/]) expect(await said(ui, re)).toBe(true)
    expect(await said(ui, /^done: the pane$/)).toBe(false)
    await ui.press({ key: 'rcpt:10-22 07:19' })
    expect(await said(ui, /^done: the pane$/)).toBe(true)
    expect(await said(ui, /^check: 79 pass$/)).toBe(true)
    await ui.press({ key: 'fold:receipts' }) // the sub-list folds as a whole
    expect(await said(ui, /^1 spawn$/)).toBe(false)
    expect(await said(ui, /^Last receipts$/)).toBe(true)
    await ui.press({ key: 'fold:receipts' })
    expect(await propOf(ui, 'fold:resume', 'label')).toBe('Resume ▾') // the header button reads as the title and its caret
    await ui.unmount()
  })
}

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
