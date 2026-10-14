import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Guide } from '../types'

// The abofles hooks (Python) compute the guide line after every spawn, receipt and prompt and keep it in the
// session's state file as `guide.line`. This mod only draws it: a band above the prompt and a toast when the top
// priority turns red. It never spawns, blocks or writes.
const guide = atom({ plugin: 'abofles-guide', key: 'guide' } as const, null)
const hiddenKey = atom({ plugin: 'abofles-guide', key: 'hiddenKey' } as const, null)

let lastTop = ''

async function refresh($: EngineInterface) {
  try {
    const home = (await $.env.get('HOME')) ?? ''
    const dir = (await $.env.get('ABOFLES_STATE_DIR')) ?? `${home}/.abofles/state`
    const id = await $.session.id()
    const text = await $.fs.read(`${dir}/${id}.json`)
    const st = JSON.parse(text) as { guide?: { line?: string; ts?: number } | null }
    const line = st.guide?.line
    if (!line) {
      await update($, guide, () => null)
      return
    }
    const next: Guide = { line, ts: st.guide?.ts ?? 0 }
    await update($, guide, () => next)
    const top = line.slice(0, 4)
    if (top.includes('🔴') && lastTop !== top) {
      $.ui.toast(line.slice(0, 160))
    }
    lastTop = top
  } catch {
    // no state yet (abofles not installed, or no hook ran): draw nothing
    await update($, guide, () => null)
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    $.ui.status(undefined) // an entry an earlier build of this mod pinned: the band is enough
    await refresh($)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await refresh($)
    return result
  })

  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    await refresh($)
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const g = await read($, guide)
    if (e.props.hasSurvey || g === null || keyOf(g.line) === (await read($, hiddenKey))) {
      return next(e)
    }
    const { Box, Button, Text } = $.ui.resolve(e)
    const prompt = promptFor(g.line)
    const hide = () => update($, hiddenKey, () => keyOf(g.line)) // down until the ladder's priorities change
    return (
      <Box>
        <Text>{g.line} </Text>
        <Button
          key="use"
          label="Use"
          onPress={async () => {
            // Put the guide into the prompt box as the next prompt; keep a draft the person already typed.
            const { text } = await $.prompt.read()
            const r = await $.prompt.fill({ text: text.trim() ? `\n${prompt}` : prompt, mode: text.trim() ? 'append' : 'replace' })
            if (r.isFilled) await hide()
            else $.ui.toast('abofles-guide: the prompt box is not open — use Copy')
          }}
        />
        <Button
          key="copy"
          label="Copy"
          onPress={async press => {
            const r = await $.ui.copy({ text: prompt, surface: press.surface })
            $.ui.toast(r.isCopied ? 'Guide copied — paste it in the prompt box' : `abofles-guide: copy failed (${r.reason})`)
          }}
        />
        <Button key="hide" label="Hide" onPress={hide} />
      </Box>
    )
  })
}

// What Hide compares: the ladder's priorities in order (🔴🟡, ✅, …). A hidden band comes back when a priority
// appears or goes, not when only the wording of the same items changes.
function keyOf(line: string): string {
  return (line.match(/[🔴🟠🟡⏳🧠💰✅]/gu) ?? []).join('') || line
}

// The prompt the Use and Copy buttons hand over: the guide line as an instruction the assistant acts on.
function promptFor(line: string): string {
  const body = line.replace(/^\s*🧭\s*/, '').trim()
  return `abofles guide — do this now, in order: ${body}`
}
