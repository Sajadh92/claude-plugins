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
  line = '🧭 ✅ nothing open — next from the memo: wait' // the ladder changed: back
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answered' } as never)
  expect(await ui.find({ key: 'hide' })).toBeDefined()
  await ui.unmount()
})
