import { expect, mock, test } from 'claude-code/testing'

const MOUNT = { plugin: 'abofles-guide', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } } as const

// Starts a session whose state file (when `file` is a string) is read by the refresh; returns the paths it read.
function session($: any, on: any, file: string | null) {
  const reads: string[] = []
  mock.env(on, { ABOFLES_STATE_DIR: '/state', HOME: '/home' })
  on('session.id', () => ({ value: 'sid-guide' }))
  on('session.start', ($: any, e: any) => ({ cwd: e.cwd }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('fs.read', ($: any, e: any) => {
    reads.push(e.path)
    return file !== null && e.path === '/state/sid-guide.json' ? { value: file } : { deny: 'no such file' }
  })
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  return reads
}

// Without a state file for the session the band passes to the engine's own (here: an empty line); no Hide button.
test('draws nothing when abofles has no state for the session', async ($, on) => {
  const reads = session($, on, null)
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  expect(reads).toContain('/state/sid-guide.json') // the refresh ran and found nothing
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...MOUNT, surface })
    expect(await ui.find({ key: 'hide' })).toBeUndefined()
    await ui.unmount()
  }
})

test('the session start reads the state file of its session and draws the band from it', async ($, on) => {
  const guide = { line: '🧭 🟡 escalate', ts: 1, root: '/p', items: [{ p: '🟡', id: 'esc:a', text: 'escalate', fill: 'go', resolve: null }] }
  const reads = session($, on, JSON.stringify({ guide }))
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  expect(reads).toEqual(['/state/sid-guide.json'])
  const ui = await $.ui.mount(MOUNT)
  expect(await ui.find({ key: 'use' })).toBeDefined()
  await ui.unmount()
})

test('a state file that is not JSON, or has no guide line, draws nothing and does not throw', async ($, on) => {
  const reads = session($, on, '{ not json')
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  expect(reads.length).toBe(1)
  const ui = await $.ui.mount(MOUNT)
  expect(await ui.find({ key: 'hide' })).toBeUndefined()
  await ui.unmount()
})

test('an older state file (no items, no ctx, no task) still draws Use, Copy and Hide', async ($, on) => {
  session($, on, JSON.stringify({ guide: { line: '🧭 🟡 escalate · re-run at opus·high', ts: 1 } }))
  await $.session.start({ cwd: '/home', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(MOUNT)
  expect(await ui.find({ key: 'use' })).toBeDefined()
  expect(await ui.find({ key: 'copy' })).toBeDefined()
  expect(await ui.find({ key: 'hide' })).toBeDefined()
  expect(await ui.find({ key: 'resolve' })).toBeUndefined()
  await ui.unmount()
})

test('the classic Stop hook refreshes the band', async ($, on) => {
  const reads = session($, on, JSON.stringify({ guide: { line: '🧭 🟡 escalate', ts: 1 } }))
  on('classic.Stop', () => ({}) as never)
  const n = reads.length
  await ($ as any).classic.Stop({ hook_event_name: 'Stop', session_id: 'sid-guide', stop_hook_active: false })
  expect(reads.length).toBeGreaterThan(n)
})
