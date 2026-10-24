import { expect, mock, test } from 'claude-code/testing'

const LINE = '🧭 🔴 open FAIL · Bug Fix & Debugging: fix it · 🟡 escalate · re-run at opus·high'

// With a guide line in the session's state file the band draws Use, Copy and Hide; Hide takes the band down and a
// refresh with the same priorities keeps it down; a line with other priorities brings it back.
test('draws Use, Copy and Hide buttons when the session has a guide line', async ($, on) => {
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  on('session.id', () => ({ value: 'sid-test' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('turn.complete', ($, e) => ({ text: e.answer }))
  on('ui.toast', () => ({ value: undefined }))
  let line = LINE
  on('fs.read', ($, e) => (e.path === '/state/sid-test.json' ? { value: JSON.stringify({ guide: { line, ts: 1 } }) } : { deny: 'no such file' }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'abofles-guide', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } })
  expect(await ui.find({ key: 'use' })).toBeDefined()
  expect(await ui.find({ key: 'copy' })).toBeDefined()
  expect(await ui.find({ key: 'hide' })).toBeDefined()
  await ui.press({ key: 'hide' })
  expect(await ui.find({ key: 'hide' })).toBeUndefined()
  line = LINE.replace('fix it', 'fix the null case') // same priorities, other wording
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answered' } as never)
  expect(await ui.find({ key: 'hide' })).toBeUndefined()
  line = '🧭 🟡 escalate · re-run at opus·high' // the ladder changed: back
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answered' } as never)
  expect(await ui.find({ key: 'hide' })).toBeDefined()
  await ui.unmount()
})

const STATE = (items: unknown[]) => JSON.stringify({ guide: { line: '🧭 🟡 escalate', ts: 1, root: '/proj', items } })

test('Re-check shows for a red item with a recheck prompt and no Resolve', async ($, on) => {
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  mock.clock(on)
  on('session.id', () => ({ value: 'sid-test' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('ui.toast', () => ({ value: undefined }))
  const red = { p: '🔴', text: 'FAIL', fill: 'fix', recheck: 'run it again' }
  on('fs.read', () => ({ value: STATE([red]) }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'abofles-guide', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } })
  expect(await ui.find({ key: 'recheck' })).toBeDefined()
  expect(await ui.find({ key: 'resolve' })).toBeUndefined()
  await ui.unmount()
})

// ---- press tests over a harness: one place that answers the state file, the process, the prompt box and the clipboard

type It = { p: string; text: string; fill: string; recheck?: string | null; id?: string; resolve?: string[] | null; unresolve?: string[] | null }
const item = (over: Partial<It> = {}): It => ({ p: '🟡', id: 'esc:a', text: 'escalate it', fill: 'do it', recheck: null, ...over })
const guideOf = (items: It[], more: object = {}) => ({ line: `🧭 ${items.map(i => `${i.p} ${i.text}`).join(' · ')}`, ts: 1, root: '/proj', items, ctx: null, task: null, main: null, ...more })

// `w.state` is the guide the state file holds (null: no file); `w.exits` the exit codes the next process runs return;
// `w.gate`, when set, holds every process run until it resolves.
async function harness($: any, on: any, first: object | null) {
  const clock = mock.clock(on)
  const w = {
    state: first as object | null,
    exits: [] as number[],
    gate: null as Promise<void> | null,
    draft: '',
    isFilled: true,
    toasts: [] as string[],
    runs: [] as { argv: unknown; cwd?: string }[],
    fills: [] as { text: string; mode: string }[],
    copies: [] as string[],
    clock,
    ui: undefined as any,
  }
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  on('session.id', () => ({ value: 'sid-press' }))
  on('session.start', ($: any, e: any) => ({ cwd: e.cwd }))
  on('turn.complete', ($: any, e: any) => ({ text: e.answer }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.toast', ($: any, e: any) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('fs.read', () => (w.state === null ? { deny: 'no such file' } : { value: JSON.stringify({ guide: w.state }) }))
  on('process.run', async ($: any, e: any) => {
    w.runs.push({ argv: e.argv, cwd: e.init?.cwd })
    if (w.gate) await w.gate
    return { value: { exitCode: w.exits.shift() ?? 0, stdout: 'out line\nsecond\n', stderr: 'err line\n' } } as never
  })
  on('prompt.read', () => ({ value: { text: w.draft, cursor: w.draft.length } }))
  on('prompt.fill', ($: any, e: any) => {
    w.fills.push({ text: e.text, mode: e.mode })
    return { isFilled: w.isFilled }
  })
  on('ui.copy', ($: any, e: any) => {
    w.copies.push(e.text)
    return { value: { isCopied: true } }
  })
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  w.ui = await $.ui.mount({ plugin: 'abofles-guide', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } })
  return w
}
const turn = (id: string) => ({ answer: 'x', durationMs: 1, isAborted: false, turnId: id, reason: 'answered' }) as never
const has = async (w: any, key: string) => (await w.ui.find({ key })) !== undefined

test('Use fills the prompt box and takes the band down; a draft is kept and the text appended', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await w.ui.press({ key: 'use' })
  expect(w.fills).toEqual([{ text: 'do it', mode: 'replace' }])
  expect(await has(w, 'hide')).toBe(false)
  w.draft = 'half typed'
  w.state = guideOf([item({ id: 'esc:b' })]) // another item brings the band back
  await $.turn.complete(turn('t1'))
  await w.ui.press({ key: 'use' })
  expect(w.fills[1]).toEqual({ text: '\ndo it', mode: 'append' })
  await w.ui.unmount()
})

test('Use keeps the band and toasts when the prompt box is not open', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  w.isFilled = false
  await w.ui.press({ key: 'use' })
  expect(w.toasts.some(t => t.includes('Prompt box is not open'))).toBe(true)
  expect(await has(w, 'hide')).toBe(true)
  await w.ui.unmount()
})

test('Copy puts the Use text on the clipboard and leaves the band up', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await w.ui.press({ key: 'copy' })
  expect(w.copies).toEqual(['do it'])
  expect(w.toasts.some(t => t.includes('Guide copied'))).toBe(true)
  expect(await has(w, 'hide')).toBe(true)
  await w.ui.unmount()
})

test('Re-check fills the recheck prompt (not the Use text) and takes the band down', async ($, on) => {
  const w = await harness($, on, guideOf([item({ p: '🔴', id: 'fail:x', text: 'FAIL x', recheck: 'run it again' })]))
  await w.ui.press({ key: 'recheck' })
  expect(w.fills).toEqual([{ text: 'run it again', mode: 'replace' }])
  expect(await has(w, 'hide')).toBe(false)
  await w.ui.unmount()
})

test('Memo fills /abofles:memo when the memo is due', async ($, on) => {
  const w = await harness($, on, guideOf([item()], { ctx: { tokens: 480000, mark: 500 } }))
  await w.ui.press({ key: 'memo' })
  expect(w.fills).toEqual([{ text: '/abofles:memo', mode: 'replace' }])
  await w.ui.unmount()
})


const rechecked = [
  item({ p: '🟠', id: 'dec:1', text: 'owner decision 1', recheck: 'verify decision 1' }),
  item({ p: '🟡', id: 'esc:x', text: 'escalate x', recheck: 'verify esc x' }),
]
for (const it of rechecked) {
  test(`${it.p} ${it.id} item with a recheck prompt shows Use and Re-check and no Resolve`, async ($, on) => {
    const w = await harness($, on, guideOf([it]))
    expect(await has(w, 'use')).toBe(true)
    expect(await has(w, 'recheck')).toBe(true)
    expect(await has(w, 'resolve')).toBe(false)
    await w.ui.press({ key: 'recheck' })
    expect(w.fills).toEqual([{ text: it.recheck, mode: 'replace' }])
    expect(w.runs).toEqual([])
    await w.ui.unmount()
  })
}

test('a stale item carrying a resolve argv draws no Resolve and process.run is never called', async ($, on) => {
  const stale = item({ p: '🔴', id: 'fail:x', text: 'FAIL x', recheck: 'run it again', resolve: ['echo', 'ok'], unresolve: ['echo', 'undone'] })
  const w = await harness($, on, guideOf([stale]))
  expect(await has(w, 'resolve')).toBe(false)
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.press({ key: 'use' })
  await $.turn.complete(turn('t1'))
  expect(w.runs).toEqual([])
  await w.ui.unmount()
})

// ---- Undo of Claude's last resolve: the hook publishes guide.last_resolved; the band only draws and runs its argv

const UNDO = ['bash', '/p/abofles/2.0.1/scripts/py', '/p/abofles/2.0.1/scripts/memo.py', 'reopen', '2', '--trace', '--session', 'sid-press'] // script_cmd's shape
const resolved = (ts = 50) => ({ last_resolved: { text: 'owner decision 2: ship it', unresolve: UNDO, ts } })

test('last_resolved draws the resolved row with Undo; Undo runs exactly its argv in the project root', async ($, on) => {
  const w = await harness($, on, guideOf([item()], resolved()))
  expect(await w.ui.find({ type: 'Text', text: '✓ resolved: owner decision 2: ship it' })).toBeDefined()
  expect(await has(w, 'undo')).toBe(true)
  await w.ui.press({ key: 'undo' })
  expect(w.runs).toEqual([{ argv: UNDO, cwd: '/proj' }])
  expect(w.toasts.at(-1)).toBe('out line')
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('after Undo the refreshed guide (last_resolved cleared by the hook) draws the band again', async ($, on) => {
  const w = await harness($, on, guideOf([item()], resolved()))
  w.state = guideOf([item()], { last_resolved: null }) // what the hook writes once the argv ran
  await w.ui.press({ key: 'undo' })
  expect(await has(w, 'undo')).toBe(false)
  expect(await has(w, 'use')).toBe(true)
  await w.ui.unmount()
})

test('Undo that fails (exit 1) toasts the failure and keeps the row so Undo can be retried', async ($, on) => {
  const w = await harness($, on, guideOf([item()], resolved()))
  w.exits.push(1)
  await w.ui.press({ key: 'undo' })
  expect(w.toasts.at(-1)).toBe('Undo failed — err line')
  expect(await has(w, 'undo')).toBe(true)
  await w.ui.press({ key: 'undo' }) // the retry runs the argv again and, on exit 0, clears the row
  expect(w.runs).toEqual([{ argv: UNDO, cwd: '/proj' }, { argv: UNDO, cwd: '/proj' }])
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('Undo that finds the item already open (exit 3) toasts that and clears the row', async ($, on) => {
  const w = await harness($, on, guideOf([item()], resolved()))
  w.exits.push(3)
  await w.ui.press({ key: 'undo' })
  expect(w.toasts.at(-1)).toBe('Already open')
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('Undo is gone while its command runs, and two presses at once start one run', async ($, on) => {
  const w = await harness($, on, guideOf([item()], resolved()))
  let release!: () => void
  w.gate = new Promise<void>(r => {
    release = r
  })
  const a = w.ui.press({ key: 'undo' }) // runs, held by the gate
  const b = w.ui.press({ key: 'undo' }).catch(() => undefined)
  await w.clock.settle()
  expect(w.runs.length).toBe(1)
  expect(await has(w, 'undo')).toBe(false)
  release()
  await Promise.all([a, b])
  w.gate = null
  expect(w.runs.length).toBe(1)
  await w.ui.unmount()
})

test('Hide on the resolved row removes it, keyed by its ts; a newer resolve draws again', async ($, on) => {
  const w = await harness($, on, guideOf([item()], resolved(50)))
  await w.ui.press({ key: 'undo-hide' })
  expect(await has(w, 'undo')).toBe(false)
  expect(w.runs).toEqual([])
  expect(await has(w, 'use')).toBe(true) // the band below shows
  await $.turn.complete(turn('t1')) // same last_resolved still published: stays hidden
  expect(await has(w, 'undo')).toBe(false)
  w.state = guideOf([item()], resolved(90))
  await $.turn.complete(turn('t2'))
  expect(await has(w, 'undo')).toBe(true)
  await w.ui.unmount()
})

test('with last_resolved null there is no resolved row and no Undo; a malformed one is ignored', async ($, on) => {
  const w = await harness($, on, guideOf([item()], { last_resolved: null }))
  expect(await has(w, 'undo')).toBe(false)
  expect(await has(w, 'use')).toBe(true)
  w.state = guideOf([item()], { last_resolved: { text: 'x', unresolve: [], ts: 5 } }) // no argv: nothing to draw
  await $.turn.complete(turn('t1'))
  expect(await has(w, 'undo')).toBe(false)
  w.state = guideOf([item()], resolved())
  await $.turn.complete(turn('t2'))
  expect(await has(w, 'undo')).toBe(true)
  w.state = guideOf([item()], { last_resolved: null }) // the hook dropped it
  await $.turn.complete(turn('t3'))
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('a red toast fires once per new red item id, not on every refresh', async ($, on) => {
  const red = (id: string, text = 'FAIL') => item({ p: '🔴', id, text, recheck: 'again' })
  const w = await harness($, on, guideOf([red('fail:a')]))
  expect(w.toasts.length).toBe(1)
  await $.turn.complete(turn('t1'))
  await $.turn.complete(turn('t2'))
  expect(w.toasts.length).toBe(1)
  w.state = guideOf([red('fail:a', 'FAIL, reworded'), item()]) // same red id, other wording, a new yellow
  await $.turn.complete(turn('t3'))
  expect(w.toasts.length).toBe(1)
  w.state = guideOf([red('fail:a'), red('fail:b', 'FAIL b')]) // a second red
  await $.turn.complete(turn('t4'))
  expect(w.toasts.length).toBe(2)
  await $.turn.complete(turn('t5'))
  expect(w.toasts.length).toBe(2)
  await w.ui.unmount()
})

test('a bad number in the state file does not take the band away', async ($, on) => {
  const w = await harness($, on, guideOf([item(), { p: 7, text: 'junk' } as never], { task: { spawns: 'x', usd: '0.4' }, ctx: { tokens: 'many', mark: 500 } }))
  expect(await has(w, 'use')).toBe(true)
  expect(await has(w, 'memo')).toBe(false)
  await w.ui.unmount()
})

// Hide is keyed on the shown items, not on the priority emojis anywhere in the line.
test('Hide stays down for the same items and comes back for a new item, even one with the same priority', async ($, on) => {
  const w = await harness($, on, guideOf([item({ id: 'esc:a' })]))
  await w.ui.press({ key: 'hide' })
  expect(await has(w, 'hide')).toBe(false)
  w.state = guideOf([item({ id: 'esc:a', text: 'escalate it 🔴 now' })]) // reworded, an emoji inside the text
  await $.turn.complete(turn('t1'))
  expect(await has(w, 'hide')).toBe(false)
  w.state = guideOf([item({ id: 'esc:b', text: 'escalate other' })]) // another item, same 🟡
  await $.turn.complete(turn('t2'))
  expect(await has(w, 'hide')).toBe(true)
  await w.ui.unmount()
})

test('a hidden Memo band comes back when a new mark is crossed', async ($, on) => {
  const done = item({ p: '✅', id: 'next', text: 'nothing open' })
  const w = await harness($, on, guideOf([done], { ctx: { tokens: 460000, mark: 500 } }))
  expect(await has(w, 'memo')).toBe(true)
  await w.ui.press({ key: 'hide' })
  expect(await has(w, 'memo')).toBe(false)
  w.state = guideOf([done], { ctx: { tokens: 480000, mark: 500 } }) // same mark, more tokens
  await $.turn.complete(turn('t1'))
  expect(await has(w, 'memo')).toBe(false)
  w.state = guideOf([done], { ctx: { tokens: 710000, mark: 750 } }) // the next mark is near
  await $.turn.complete(turn('t2'))
  expect(await has(w, 'memo')).toBe(true)
  await w.ui.unmount()
})

