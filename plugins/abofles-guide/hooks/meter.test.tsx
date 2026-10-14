import { expect, mock, test } from 'claude-code/testing'

type Item = { p: string; text: string; fill: string; resolve: string[] | null }
const FAIL: Item = { p: '🔴', text: 'open FAIL', fill: 'fix the FAIL now', resolve: null }
const OK: Item = { p: '✅', text: 'nothing open', fill: '', resolve: null }
const TASK = { spawns: 3, usd: 0.41, budget: 5, left: 2 }

// Mounts the band over a state file holding `guide`; returns the mounted drawing.
async function mount($: any, on: any, guide: object) {
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  on('session.id', () => ({ value: 'sid-meter' }))
  on('session.start', ($: any, e: any) => ({ cwd: e.cwd }))
  on('turn.complete', ($: any, e: any) => ({ text: e.answer }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('fs.read', ($: any, e: any) => (e.path === '/state/sid-meter.json' ? { value: JSON.stringify({ guide }) } : { deny: 'no such file' }))
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  return $.ui.mount({ plugin: 'abofles-guide', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } })
}

test('band is hidden when every item is done and there is no context meter', async ($, on) => {
  const ui = await mount($, on, { line: '🧭 ✅ nothing open', ts: 1, root: '/p', items: [OK], ctx: null, task: null, main: null })
  expect(await ui.find({ key: 'hide' })).toBeUndefined()
  expect(await ui.find({ key: 'use' })).toBeUndefined()
  await ui.unmount()
})

test('Use and Resolve are drawn when the top item has a command', async ($, on) => {
  const item = { ...FAIL, resolve: ['python3', 'fix.py'] }
  const ui = await mount($, on, { line: '🧭 🔴 open FAIL', ts: 1, root: '/p', items: [item], ctx: null, task: null, main: null })
  expect(await ui.find({ key: 'use' })).toBeDefined()
  expect(await ui.find({ key: 'resolve' })).toBeDefined()
  expect(await ui.find({ key: 'memo' })).toBeUndefined()
  await ui.unmount()
})

test('Resolve is absent when the top item has no command', async ($, on) => {
  const ui = await mount($, on, { line: '🧭 🔴 open FAIL', ts: 1, root: '/p', items: [FAIL], ctx: null, task: null, main: null })
  expect(await ui.find({ key: 'use' })).toBeDefined()
  expect(await ui.find({ key: 'resolve' })).toBeUndefined()
  await ui.unmount()
})

test('the meter shows context, task cost and the main suggestion', async ($, on) => {
  const guide = {
    line: '🧭 🔴 open FAIL', ts: 1, root: '/p', items: [FAIL], ctx: { tokens: 412000, mark: 500 }, task: TASK,
    main: 'main: suggest Opus 5.5 · Medium',
  }
  const ui = await mount($, on, guide)
  expect(await ui.find({ type: 'Text', text: 'ctx 412K / 500K' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '$0.41' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'budget 2 left · suggest Opus 5.5 · Medium' })).toBeDefined()
  await ui.unmount()
})

test('Memo is drawn within 50K of the mark, even with nothing open', async ($, on) => {
  const ui = await mount($, on, { line: '🧭 ✅ nothing open', ts: 1, root: '/p', items: [OK], ctx: { tokens: 460000, mark: 500 }, task: null, main: null })
  expect(await ui.find({ key: 'memo' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'ctx 460K / 500K' })).toBeDefined()
  expect(await ui.find({ key: 'use' })).toBeUndefined()
  await ui.unmount()
})

test('Memo is drawn past the last mark and absent far from it', async ($, on) => {
  const past = await mount($, on, { line: '🧭 🔴 open FAIL', ts: 1, root: '/p', items: [FAIL], ctx: { tokens: 900000, mark: null }, task: null, main: null })
  expect(await past.find({ key: 'memo' })).toBeDefined()
  await past.unmount()
})

test('Memo is absent when the context is far from the mark', async ($, on) => {
  const ui = await mount($, on, { line: '🧭 🔴 open FAIL', ts: 1, root: '/p', items: [FAIL], ctx: { tokens: 100000, mark: 500 }, task: null, main: null })
  expect(await ui.find({ key: 'memo' })).toBeUndefined()
  await ui.unmount()
})
