import { expect, test } from 'claude-code/testing'

// Without a state file for the session the band passes to the engine's own (here: an empty line); no Hide button.
test('draws nothing when abofles has no state for the session', async ($, on) => {
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-own"> </Text>
  })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'abofles-guide', surface, component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 4 } })
    expect(await ui.find({ key: 'hide' })).toBeUndefined()
    await ui.unmount()
  }
})
