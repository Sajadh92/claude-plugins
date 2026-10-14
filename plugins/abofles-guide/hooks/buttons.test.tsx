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
const YELLOW = { p: '🟡', text: 'escalate it', fill: 'do it', resolve: ['echo', 'ok'], recheck: null, unresolve: ['echo', 'undone'] }

test('Re-check shows for a red item with a recheck prompt and no Resolve', async ($, on) => {
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  mock.clock(on)
  on('session.id', () => ({ value: 'sid-test' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('ui.toast', () => ({ value: undefined }))
  const red = { p: '🔴', text: 'FAIL', fill: 'fix', resolve: null, recheck: 'run it again', unresolve: null }
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

for (const exitCode of [0, 1]) {
  test(`Resolve asks twice, then ${exitCode === 0 ? 'offers Undo' : 'keeps the band without Undo'}`, async ($, on) => {
    mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
    mock.clock(on)
    on('session.id', () => ({ value: 'sid-test' }))
    on('session.start', ($, e) => ({ cwd: e.cwd }))
    on('ui.toast', () => ({ value: undefined }))
    on('fs.read', () => ({ value: STATE([YELLOW]) }))
    const calls: { argv: unknown; cwd?: string }[] = []
    on('process.run', ($, e) => {
      const ev = e as never as { argv: unknown; init?: { cwd?: string } }
      calls.push({ argv: ev.argv, cwd: ev.init?.cwd })
      return { value: { exitCode: calls.length === 1 ? exitCode : 0, stdout: 'out\n', stderr: 'bad\n' } } as never
    })
    on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
      const { Text } = $.ui.resolve(e)
      return <Text key="engine-own"> </Text>
    })
    await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
    const ui = await $.ui.mount({ plugin: 'abofles-guide', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } })
    await ui.press({ key: 'resolve' })
    expect(calls.length).toBe(0)
    expect((await ui.find({ key: 'resolve' }))?.text).toContain('Confirm resolve')
    await ui.press({ key: 'resolve' })
    expect(calls.length).toBe(1)
    expect(JSON.stringify(calls[0])).toContain('echo')
    expect(JSON.stringify(calls[0])).toContain('/proj')
    if (exitCode === 0) {
      expect(await ui.find({ key: 'undo' })).toBeDefined()
      await ui.press({ key: 'undo' })
      expect(calls.length).toBe(2)
      expect(JSON.stringify(calls[1])).toContain('undone')
    } else {
      expect(await ui.find({ key: 'undo' })).toBeUndefined()
      expect(await ui.find({ key: 'resolve' })).toBeDefined()
    }
    await ui.unmount()
  })
}

// An armed Resolve disarms itself after 5 s (label back to Resolve), and a press then only re-arms.
// Hide on the "resolved" row keeps the band down: the hooks have not recomputed the ladder yet.
test('Confirm resolve expires after 5 s; Hide after a resolve keeps the band down', async ($, on) => {
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  const clock = mock.clock(on)
  on('session.id', () => ({ value: 'sid-test' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('ui.toast', () => ({ value: undefined }))
  on('fs.read', () => ({ value: STATE([YELLOW]) }))
  const calls: unknown[] = []
  on('process.run', ($, e) => {
    calls.push(e)
    return { value: { exitCode: 0, stdout: 'out\n', stderr: '' } } as never
  })
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'abofles-guide', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } })
  await ui.press({ key: 'resolve' })
  expect((await ui.find({ key: 'resolve' }))?.text).toContain('Confirm resolve')
  await clock.advance(5001)
  expect((await ui.find({ key: 'resolve' }))?.text).not.toContain('Confirm')
  await ui.press({ key: 'resolve' })
  expect(calls.length).toBe(0)
  await ui.press({ key: 'resolve' })
  expect(calls.length).toBe(1)
  expect(await ui.find({ key: 'undo' })).toBeDefined()
  await ui.press({ key: 'hide' })
  expect(await ui.find({ key: 'undo' })).toBeUndefined()
  expect(await ui.find({ key: 'resolve' })).toBeUndefined()
  await ui.unmount()
})

// ---- press tests over a harness: one place that answers the state file, the process, the prompt box and the clipboard

type It = { p: string; text: string; fill: string; resolve: string[] | null; recheck?: string | null; unresolve?: string[] | null; id?: string }
const item = (over: Partial<It> = {}): It => ({ p: '🟡', id: 'esc:a', text: 'escalate it', fill: 'do it', resolve: ['echo', 'ok'], recheck: null, unresolve: ['echo', 'undone'], ...over })
const guideOf = (items: It[], more: object = {}) => ({ line: `🧭 ${items.map(i => `${i.p} ${i.text}`).join(' · ')}`, ts: 1, root: '/proj', items, ctx: null, task: null, main: null, ...more })

// `w.state` is the guide the state file holds (null: no file); `w.exits` the exit codes the next process runs return;
// `w.gate`, when set, holds every process run until it resolves.
async function harness($: any, on: any, first: object | null, opts: { noTimers?: boolean } = {}) {
  // noTimers: a clock whose timers never fire, as after a reload when the arm's timer is gone
  let t = 1000
  const clock = opts.noTimers
    ? { advance: async (ms: number) => void (t += ms), settle: async () => {} }
    : mock.clock(on)
  if (opts.noTimers) {
    on('clock.now', () => ({ value: t }))
    on('clock.after', () => ({ deny: 'timer lost' })) // the callback never runs
  }
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
// Two presses on Resolve: arm, then confirm.
async function resolveTwice(w: any) {
  await w.ui.press({ key: 'resolve' })
  await w.ui.press({ key: 'resolve' })
}

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
  expect(w.toasts.some(t => t.includes('prompt box is not open'))).toBe(true)
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
  const w = await harness($, on, guideOf([item({ p: '🔴', id: 'fail:x', text: 'FAIL x', resolve: null, recheck: 'run it again' })]))
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

test('Undo runs the undo argv in the project root and clears the row', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await resolveTwice(w)
  expect(await has(w, 'undo')).toBe(true)
  await w.ui.press({ key: 'undo' })
  expect(w.runs).toEqual([{ argv: ['echo', 'ok'], cwd: '/proj' }, { argv: ['echo', 'undone'], cwd: '/proj' }])
  expect(await has(w, 'undo')).toBe(false)
  expect(w.toasts.at(-1)).toBe('out line')
  await w.ui.unmount()
})

test('Undo that fails (exit 1) toasts the failure and clears the row', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await resolveTwice(w)
  w.exits.push(1)
  await w.ui.press({ key: 'undo' })
  expect(w.toasts.at(-1)).toBe('abofles-guide: undo failed — err line')
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('Undo that finds the item already open (exit 3) toasts that and clears the row', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await resolveTwice(w)
  w.exits.push(3)
  await w.ui.press({ key: 'undo' })
  expect(w.toasts.at(-1)).toBe('abofles-guide: already open')
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('Resolve that fails (exit 1) toasts "resolve failed" and offers no Undo', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  w.exits.push(1)
  await resolveTwice(w)
  expect(w.toasts.at(-1)).toBe('abofles-guide: resolve failed — err line')
  expect(await has(w, 'undo')).toBe(false)
  expect(await has(w, 'resolve')).toBe(true)
  await w.ui.unmount()
})

test('Resolve on an item already resolved (exit 3) toasts that and offers no Undo', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  w.exits.push(3)
  await resolveTwice(w)
  expect(w.toasts.at(-1)).toBe('abofles-guide: already resolved')
  expect(await has(w, 'undo')).toBe(false)
  expect(w.runs.length).toBe(1)
  await w.ui.unmount()
})

test('Resolve and Undo are gone while a command runs, so a second press runs nothing', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  let release!: () => void
  w.gate = new Promise<void>(r => {
    release = r
  })
  await w.ui.press({ key: 'resolve' }) // arm
  const confirm = w.ui.press({ key: 'resolve' }) // runs, held by the gate
  await w.clock.settle()
  expect(w.runs.length).toBe(1)
  expect(await has(w, 'resolve')).toBe(false)
  release()
  await confirm
  w.gate = null
  expect(w.runs.length).toBe(1)
  expect(await has(w, 'undo')).toBe(true)
  await w.ui.unmount()
})

test('two Confirm presses at once start one run', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  let release!: () => void
  w.gate = new Promise<void>(r => {
    release = r
  })
  await w.ui.press({ key: 'resolve' }) // arm
  const a = w.ui.press({ key: 'resolve' })
  const b = w.ui.press({ key: 'resolve' }).catch(() => undefined)
  await w.clock.settle()
  release()
  await Promise.all([a, b])
  expect(w.runs.length).toBe(1)
  await w.ui.unmount()
})

test('a Confirm stays good until 5 s are up, then a press only re-arms', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await w.ui.press({ key: 'resolve' })
  await w.clock.advance(4999)
  expect((await w.ui.find({ key: 'resolve' }))?.text).toContain('Confirm resolve')
  await w.clock.advance(2)
  expect((await w.ui.find({ key: 'resolve' }))?.text).not.toContain('Confirm')
  await w.ui.press({ key: 'resolve' })
  expect(w.runs.length).toBe(0)
  await w.ui.unmount()
})

test('an arm on one item does not confirm another item with the same text', async ($, on) => {
  const w = await harness($, on, guideOf([item({ id: 'esc:a', resolve: ['echo', 'A'] })]))
  await w.ui.press({ key: 'resolve' })
  w.state = guideOf([item({ id: 'esc:b', resolve: ['echo', 'B'] })]) // same text, another agent
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  expect((await w.ui.find({ key: 'resolve' }))?.text).not.toContain('Confirm')
  await w.ui.press({ key: 'resolve' })
  expect(w.runs.length).toBe(0)
  await w.ui.press({ key: 'resolve' })
  expect(w.runs).toEqual([{ argv: ['echo', 'B'], cwd: '/proj' }])
  await w.ui.unmount()
})

test('turn.complete clears the resolved row and an armed Resolve', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await w.ui.press({ key: 'resolve' })
  expect((await w.ui.find({ key: 'resolve' }))?.text).toContain('Confirm resolve')
  await $.turn.complete(turn('t1'))
  expect((await w.ui.find({ key: 'resolve' }))?.text).not.toContain('Confirm')
  await resolveTwice(w)
  expect(await has(w, 'undo')).toBe(true)
  await $.turn.complete(turn('t2'))
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('the resolved row is drawn even when the refresh after it found no guide', async ($, on) => {
  const w = await harness($, on, guideOf([item()]))
  await w.ui.press({ key: 'resolve' })
  w.state = null
  await w.ui.press({ key: 'resolve' })
  expect(await has(w, 'undo')).toBe(true)
  expect(await w.ui.find({ type: 'Text', text: '✓ resolved: escalate it' })).toBeDefined()
  await w.ui.press({ key: 'hide' })
  expect(await has(w, 'undo')).toBe(false)
  await w.ui.unmount()
})

test('a red toast fires once per new red item id, not on every refresh', async ($, on) => {
  const red = (id: string, text = 'FAIL') => item({ p: '🔴', id, text, resolve: null, recheck: 'again' })
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
  const done = item({ p: '✅', id: 'next', text: 'nothing open', resolve: null })
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

// After a reload the timer that clears the arm is gone; the timestamp alone must keep a stale arm from confirming.
test('an arm older than 5 s does not confirm even when its timer never fired', async ($, on) => {
  const w = await harness($, on, guideOf([item()]), { noTimers: true })
  await w.ui.press({ key: 'resolve' })
  expect((await w.ui.find({ key: 'resolve' }))?.text).toContain('Confirm resolve')
  await w.clock.advance(6000)
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true }) // a refresh redraws the band
  expect((await w.ui.find({ key: 'resolve' }))?.text).not.toContain('Confirm')
  await w.ui.press({ key: 'resolve' }) // only re-arms
  expect(w.runs.length).toBe(0)
  expect((await w.ui.find({ key: 'resolve' }))?.text).toContain('Confirm resolve')
  await w.ui.unmount()
})
