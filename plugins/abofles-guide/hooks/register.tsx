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
    const st = JSON.parse(text) as { guide?: Partial<Guide> | null }
    const raw = st.guide
    const line = raw?.line
    if (!raw || !line) {
      await update($, guide, () => null)
      return
    }
    // Older state files lack the newer fields: each is optional.
    const next: Guide = {
      line,
      ts: raw.ts ?? 0,
      root: raw.root ?? '',
      items: Array.isArray(raw.items) ? raw.items : [],
      ctx: raw.ctx ?? null,
      task: raw.task ?? null,
      main: raw.main ?? null,
    }
    await update($, guide, () => next)
    // Toast once when the top priority turns red (code points, not UTF-16 units: an emoji is two units).
    const key = keyOf(line)
    if (Array.from(key)[0] === '🔴' && lastTop !== key) {
      $.ui.toast(Array.from(line).slice(0, 160).join(''))
    }
    lastTop = key
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
    // A value an earlier build kept in $.state survives a reload: every newer field is optional here too.
    const items = Array.isArray(g.items) ? g.items : []
    const top = items[0]
    // Nothing open: every item is ✅ (an old state file without items: the line's only priority is ✅).
    const done = items.length > 0 ? items.every(i => i.p === '✅') : keyOf(g.line) === '✅'
    const memo = needsMemo(g.ctx ?? null)
    if (done && !memo) {
      return next(e)
    }
    const { Box, Button, Text } = $.ui.resolve(e)
    const prompt = top?.fill || promptFor(g.line)
    const resolve = !done && Array.isArray(top?.resolve) && top.resolve.length > 0 ? top.resolve : null
    const meter = meterOf(g)
    const hide = () => update($, hiddenKey, () => keyOf(g.line)) // down until the ladder's priorities change
    // Put text into the prompt box; keep a draft the person already typed.
    const fill = async (text: string) => {
      const draft = (await $.prompt.read()).text.trim()
      const r = await $.prompt.fill({ text: draft ? `\n${text}` : text, mode: draft ? 'append' : 'replace' })
      if (r.isFilled) await hide()
      else $.ui.toast('abofles-guide: the prompt box is not open — use Copy')
    }
    return (
      <Box flexDirection="column">
        {done ? null : <Text>{g.line.replace(/`/g, '')}</Text>}
        {meter ? <Text dimColor>{meter}</Text> : null}
        <Box flexDirection="row" flexWrap="wrap" gap={1} marginTop={1}>
          {done ? null : (
            <Button key="use" label="Use" onPress={() => fill(prompt)} />
          )}
          {resolve ? (
            <Button
              key="resolve"
              label="Resolve"
              onPress={async () => {
                try {
                  const r = await $.process.run(resolve, g.root ? { cwd: g.root } : undefined)
                  const first = (r.exitCode === 0 ? r.stdout : r.stderr || r.stdout).split('\n').find(l => l.trim()) ?? ''
                  if (r.exitCode === 0) await hide() // settled: down until the hooks recompute the ladder without it
                  $.ui.toast(r.exitCode === 0 ? first || 'abofles-guide: resolved' : `abofles-guide: resolve failed — ${first || `exit ${r.exitCode}`}`)
                } catch (err) {
                  $.ui.toast(`abofles-guide: resolve failed — ${err instanceof Error ? err.message : String(err)}`)
                }
                await refresh($)
              }}
            />
          ) : null}
          {memo ? <Button key="memo" label="Memo" onPress={() => fill('/abofles:memo')} /> : null}
          {done ? null : (
            <Button
              key="copy"
              label="Copy"
              onPress={async press => {
                const r = await $.ui.copy({ text: prompt, surface: press.surface })
                $.ui.toast(r.isCopied ? 'Guide copied — paste it in the prompt box' : `abofles-guide: copy failed (${r.reason})`)
              }}
            />
          )}
          <Button key="hide" label="Hide" onPress={hide} />
        </Box>
      </Box>
    )
  })
}

// The memo is due when the context is within 50K tokens of its next mark, or past the last mark (mark null).
function needsMemo(ctx: Guide['ctx']): boolean {
  if (!ctx) return false
  return ctx.mark == null || ctx.mark * 1000 - ctx.tokens <= 50000
}

// The dim second line: `ctx 412K / 500K · task 3 spawns · $0.41 · budget 2 left · suggest Opus 5.5 · Medium`.
function meterOf(g: Guide): string {
  const parts: string[] = []
  if (g.ctx) parts.push(g.ctx.mark == null ? `ctx ${Math.round(g.ctx.tokens / 1000)}K` : `ctx ${Math.round(g.ctx.tokens / 1000)}K / ${g.ctx.mark}K`)
  if (g.task) {
    parts.push(`task ${g.task.spawns} spawns`, `$${g.task.usd.toFixed(2)}`)
    if (g.task.left != null) parts.push(`budget ${g.task.left} left`)
  }
  const main = g.main?.replace(/^\s*main:\s*/i, '').trim()
  if (main) parts.push(main)
  return parts.join(' · ')
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
