import type { EngineInterface, Register } from 'claude-code'

import type { Guide } from '../types'
import { renderPane } from './pane'
import {
  anyPane,
  autoOpen,
  closePane,
  getDismissedTs,
  getGuide,
  getHiddenKey,
  getPane,
  getPaneOpen,
  getRunning,
  guideButtons,
  hideKeyOf,
  loadFolds,
  openPane,
  paneIsPlaced,
  plain,
  refresh,
  setPaneOpen,
  undoRow,
  viewOf,
} from './shared'

// The abofles hooks (Python) compute the guide line after every spawn, receipt and prompt and keep it in the
// session's state file as `guide.line`, next to `pane`, the data of the Abo Fles pane. This mod only draws them: the
// band above the prompt, the pane (pane.tsx), and a toast when a new red item appears. It never spawns, blocks or
// writes, and it never settles an item itself: Claude resolves, after a Re-check. The one command it runs is Undo,
// the argv the hook publishes as `guide.last_resolved`. The state, its cleaning and the guide's buttons: shared.tsx.

// /abofles:pane (the abofles plugin's own command file is the fallback when this mod is off) and its alias /abofles-pane:
// open the pane, or close it when it is up. The reply is one short line.
async function togglePane($: EngineInterface) {
  if (await paneIsPlaced($)) {
    await closePane($)
    return { text: 'Abo Fles pane closed.' }
  }
  const r = await openPane($)
  return { text: r.isPlaced ? 'Abo Fles pane opened.' : `Abo Fles pane is open but waits for room (${r.reason ?? 'no surface'}).` }
}

// `text` cut at a word end to at most `n` characters (code points), with … when cut: the opener row stays one line.
function words(text: string, n: number): string {
  const cs = Array.from(plain(text))
  if (cs.length <= n) return cs.join('')
  const cut = cs.slice(0, n - 1).join('')
  const at = cut.lastIndexOf(' ')
  return `${at > n / 2 ? cut.slice(0, at) : cut}…`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    $.ui.status(undefined) // an entry an earlier build of this mod pinned: the band is enough
    try {
      await $.command.register({ name: 'abofles-pane', description: 'Open or close the Abo Fles pane (guide, resume, spawns, overrides)' })
    } catch {
      // the command file of the abofles plugin still answers /abofles:pane
    }
    await loadFolds($)
    await refresh($)
    await autoOpen($)
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
  }).catch(($, e, next) => next(e)) // a failed refresh must not change the Stop result

  // The pane's live spawns: a subagent ended, or a tool (the Agent tool's spawn among them) ran.
  on('classic.SubagentStop', async ($, e, next) => {
    const result = await next(e)
    await refresh($)
    await autoOpen($)
    return result
  }).catch(($, e, next) => next(e))

  on('classic.PostToolUse', async ($, e, next) => {
    const result = await next(e)
    await refresh($)
    await autoOpen($)
    return result
  }).catch(($, e, next) => next(e))

  // The person's command, by the name the engine gives a plugin's command file (`<plugin>:<name>`) and by the alias this mod registers.
  on('command.run', { command: 'abofles:pane' }, $ => togglePane($)).catch(($, e, next) => next(e)) // a failure leaves the command file to answer
  on('command.run', { command: 'abofles-pane' }, $ => togglePane($))

  // The pane's id is 'abofles' (PANE_ID in shared.tsx), spelled out in the matchers so the scan reads them.
  // Closed by the person (the mark or the key): it stays closed in the next session too.
  on('ui.close', { id: 'abofles' }, async ($, e, next) => {
    const result = await next(e)
    if (e.origin.kind === 'person') await setPaneOpen($, false)
    return result
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: 'abofles' }, ($, e) => renderPane($, e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const g = await getGuide($)
    const p = await getPane($)
    const open = await getPaneOpen($) // a change redraws the band: the Pane button and the opener follow the pane
    // Where the pane has something to show but is not drawn (a narrow terminal, or closed): the band is its opener.
    const wants = anyPane(p)
    const placed = wants ? await paneIsPlaced($) : false
    const ui = $.ui.resolve(e)
    const { Box, Button, Text } = ui
    const openerRow = (g: Guide | null) => {
      const top = g?.items?.[0]
      const what = top ? `${top.p} ${words(top.text, 70)}` : g ? words(g.line.replace(/^\s*🧭\s*/, ''), 70) : ''
      return (
        <Box flexDirection="row" flexWrap="wrap" gap={1}>
          <Text>{what ? `Abo Fles · ${what}` : 'Abo Fles'}</Text>
          <Button key="pane" label="Pane" variant="secondary" onPress={() => openPane($)} />
        </Box>
      )
    }
    // The guide lives in the pane: the band stays empty while the pane is up, else one row that opens it.
    if (p !== null && p.places.guide === 'pane') return placed ? next(e) : openerRow(g)
    // Claude's last resolve (published by the hook until the Stop of the turn after it), unless the person hid that row.
    const busy = (await getRunning($)) === true
    const last = g?.last_resolved ?? null
    if (g !== null && last !== null && last.ts !== (await getDismissedTs($))) {
      return undoRow($, ui, g, last, busy)
    }
    // Hidden, or nothing open: the band is quiet, save for the opener of a pane that is not drawn (and was not closed by hand).
    const quiet = () => (wants && !placed && open !== false ? openerRow(g) : next(e))
    if (g === null || hideKeyOf(g) === (await getHiddenKey($))) return quiet()
    const v = viewOf(g)
    if (v.done && !v.memo) return quiet()
    const paneButton = p !== null ? <Button key="pane" label="Pane" variant="secondary" onPress={() => openPane($)} /> : null
    return (
      <Box flexDirection="column">
        {v.done ? null : <Text>{g.line.replace(/`/g, '')}</Text>}
        {v.meter ? <Text dimColor>{v.meter}</Text> : null}
        {guideButtons($, ui, g, v, false, paneButton)}
      </Box>
    )
  })
}
