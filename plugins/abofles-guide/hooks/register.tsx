import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Guide, GuideItem } from '../types'

// The abofles hooks (Python) compute the guide line after every spawn, receipt and prompt and keep it in the
// session's state file as `guide.line`. This mod only draws it: a band above the prompt and a toast when a new
// red item appears. It never spawns, blocks or writes.
const guide = atom({ plugin: 'abofles-guide', key: 'guide' } as const, null)
// What Hide compares: the ids of the shown items (+ the memo mark when the memo is due), see hideKeyOf.
const hiddenKey = atom({ plugin: 'abofles-guide', key: 'hiddenKey' } as const, null)

// Resolve asks twice: the first press arms the item (keyed by its id) for 5 s; the second runs the command.
const armed = atom({ plugin: 'abofles-guide', key: 'armed' } as const, null)
// The last hand-resolve, kept for Undo until the next turn completes.
const lastResolved = atom({ plugin: 'abofles-guide', key: 'lastResolved' } as const, null)
// Set while Resolve or Undo runs its command (up to 30 s): both buttons are gone, a second press is ignored.
const running = atom({ plugin: 'abofles-guide', key: 'running' } as const, false)
// The ids of the red items already toasted: a toast fires only for a red id not in it (kept across reloads).
const toasted = atom({ plugin: 'abofles-guide', key: 'toasted' } as const, [] as string[])
const ARM_MS = 5000

const isStr = (v: unknown): v is string => typeof v === 'string'
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const argvOf = (v: unknown): string[] | null => (Array.isArray(v) && v.length > 0 && v.every(isStr) ? v : null)

// The id of an item: stable per underlying thing; a state file from before ids has none, so its text stands in.
const idOf = (it: GuideItem): string => it.id || it.text

// One item from the state file, or null when it lacks a priority or text. Wrong-typed optional fields fall back.
function cleanItem(v: unknown): GuideItem | null {
  if (!isObj(v) || !isStr(v.p) || !isStr(v.text)) return null
  const item: GuideItem = {
    p: v.p,
    text: v.text,
    fill: isStr(v.fill) ? v.fill : '',
    resolve: argvOf(v.resolve),
    recheck: isStr(v.recheck) && v.recheck.trim() ? v.recheck : null,
    unresolve: argvOf(v.unresolve),
  }
  if (isStr(v.id) && v.id) item.id = v.id
  return item
}

// The guide from the state file with every field type-checked (older files lack the newer fields), or null.
function cleanGuide(raw: unknown): Guide | null {
  if (!isObj(raw) || !isStr(raw.line) || !raw.line) return null
  let ctx: Guide['ctx'] = null
  if (isObj(raw.ctx) && isNum(raw.ctx.tokens) && (raw.ctx.mark == null || isNum(raw.ctx.mark))) {
    ctx = { tokens: raw.ctx.tokens, mark: raw.ctx.mark ?? null }
  }
  let task: Guide['task'] = null
  if (isObj(raw.task) && isNum(raw.task.spawns) && isNum(raw.task.usd)) {
    task = {
      spawns: raw.task.spawns,
      usd: raw.task.usd,
      budget: isNum(raw.task.budget) ? raw.task.budget : null,
      left: isNum(raw.task.left) ? raw.task.left : null,
    }
  }
  const items = Array.isArray(raw.items) ? raw.items.map(cleanItem).filter((i): i is GuideItem => i !== null) : []
  return { line: raw.line, ts: isNum(raw.ts) ? raw.ts : 0, root: isStr(raw.root) ? raw.root : '', items, ctx, task, main: isStr(raw.main) ? raw.main : null }
}

// Takes the "running" flag; false when a Resolve or Undo already holds it (a second press does nothing).
async function claim($: EngineInterface): Promise<boolean> {
  let wasRunning = false
  await update($, running, cur => {
    wasRunning = cur === true
    return true
  })
  return !wasRunning
}

async function refresh($: EngineInterface) {
  try {
    const home = (await $.env.get('HOME')) ?? ''
    const dir = (await $.env.get('ABOFLES_STATE_DIR')) ?? `${home}/.abofles/state`
    const id = await $.session.id()
    const text = await $.fs.read(`${dir}/${id}.json`)
    const st = JSON.parse(text) as { guide?: unknown }
    const next = cleanGuide(isObj(st) ? st.guide : null)
    if (!next) {
      await update($, guide, () => null)
      return
    }
    await update($, guide, () => next)
    // Toast when a red item appears that was not toasted before (an old state file without items: the line itself).
    const red = next.items.filter(i => i.p === '🔴').map(idOf)
    if (red.length === 0 && Array.from(keyOf(next.line))[0] === '🔴') red.push(`line:${next.line}`)
    const seen = await read($, toasted)
    if (red.some(r => !seen.includes(r))) {
      // code points, not UTF-16 units: an emoji is two units
      $.ui.toast(Array.from(next.line).slice(0, 160).join(''))
    }
    if (red.length !== seen.length || red.some((r, n) => r !== seen[n])) await update($, toasted, () => red)
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
    await update($, lastResolved, () => null)
    await update($, armed, () => null)
    await refresh($)
    return result
  })

  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    await refresh($)
    return result
  }).catch(($, e, next) => next(e)) // a failed refresh must not change the Stop result

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const g = await read($, guide)
    const last = await read($, lastResolved)
    const busy = (await read($, running)) === true
    // The "resolved" row needs only lastResolved: the guide may be gone by now (a refresh found no state).
    if (!e.props.hasSurvey && last !== null) {
      const { Box, Button, Text } = $.ui.resolve(e)
      const unresolve = argvOf(last.unresolve)
      const root = last.root || g?.root || ''
      return (
        <Box flexDirection="row" flexWrap="wrap" gap={1}>
          <Text>{`✓ resolved: ${Array.from(last.text).slice(0, 90).join('')}`}</Text>
          {unresolve && !busy ? (
            <Button
              key="undo"
              label="Undo"
              onPress={async () => {
                if (!(await claim($))) return
                try {
                  await update($, lastResolved, () => null)
                  const r = await $.process.run(unresolve, root ? { cwd: root } : undefined)
                  const first = (r.exitCode === 0 ? r.stdout : r.stderr || r.stdout).split('\n').find(l => l.trim()) ?? ''
                  if (r.exitCode === 0) $.ui.toast(first || 'abofles-guide: undone')
                  else if (r.exitCode === 3) $.ui.toast('abofles-guide: already open') // nothing changed
                  else $.ui.toast(`abofles-guide: undo failed — ${first || `exit ${r.exitCode}`}`)
                  await refresh($)
                } catch (err) {
                  $.ui.toast(`abofles-guide: undo failed — ${err instanceof Error ? err.message : String(err)}`)
                } finally {
                  await update($, running, () => false)
                }
              }}
            />
          ) : null}
          <Button
            key="hide"
            label="Hide"
            onPress={async () => {
              // the hooks have not recomputed the ladder yet: keep the band down until its items change,
              // so the item just resolved does not come back with its Resolve button
              await update($, lastResolved, () => null)
              if (g !== null) await update($, hiddenKey, () => hideKeyOf(g))
            }}
          />
        </Box>
      )
    }
    if (e.props.hasSurvey || g === null || hideKeyOf(g) === (await read($, hiddenKey))) {
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
    const recheck = !done && typeof top?.recheck === 'string' && top.recheck.trim() ? top.recheck : null
    const resolve = !done && !recheck && Array.isArray(top?.resolve) && top.resolve.length > 0 ? top.resolve : null
    const meter = meterOf(g)
    const disarm = () => update($, armed, () => null)
    const hide = async () => {
      await disarm()
      await update($, hiddenKey, () => hideKeyOf(g)) // down until the shown items (or the memo mark) change
    }
    const topId = top ? idOf(top) : ''
    // Armed for this very item and not older than ARM_MS (the timer is gone after a reload, the timestamp is not).
    const was = resolve ? await read($, armed) : null
    const isArmed = was !== null && was.id === topId && (await $.clock.now()) - was.ts <= ARM_MS
    // Put text into the prompt box; keep a draft the person already typed.
    const fill = async (text: string) => {
      await disarm()
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
          {recheck ? <Button key="recheck" label="Re-check" onPress={() => fill(recheck)} /> : null}
          {resolve && !busy ? (
            <Button
              key="resolve"
              label={isArmed ? 'Confirm resolve' : 'Resolve'}
              onPress={async () => {
                const now = await $.clock.now()
                const armedNow = await read($, armed)
                if (!armedNow || armedNow.id !== topId || now - armedNow.ts > ARM_MS) {
                  await update($, armed, () => ({ id: topId, ts: now }))
                  // the label goes back to Resolve when the 5 s pass, so it never reads "Confirm" for a press that only re-arms
                  $.clock.after(ARM_MS, () => {
                    void update($, armed, cur => (cur && cur.ts === now ? null : cur))
                  })
                  return
                }
                await disarm()
                if (!(await claim($))) return
                try {
                  const r = await $.process.run(resolve, g.root ? { cwd: g.root } : undefined)
                  const first = (r.exitCode === 0 ? r.stdout : r.stderr || r.stdout).split('\n').find(l => l.trim()) ?? ''
                  if (r.exitCode === 0) {
                    await update($, lastResolved, () => ({ text: top.text, unresolve: top.unresolve ?? null, root: g.root, ts: now }))
                    $.ui.toast(first || 'abofles-guide: resolved')
                  } else if (r.exitCode === 3) {
                    // nothing changed: it was resolved already, so there is nothing to undo
                    $.ui.toast('abofles-guide: already resolved')
                  } else {
                    $.ui.toast(`abofles-guide: resolve failed — ${first || `exit ${r.exitCode}`}`)
                  }
                  await refresh($)
                } catch (err) {
                  $.ui.toast(`abofles-guide: resolve failed — ${err instanceof Error ? err.message : String(err)}`)
                } finally {
                  await update($, running, () => false)
                }
              }}
            />
          ) : null}
          {memo ? <Button key="memo" label="Memo" onPress={() => fill('/abofles:memo')} /> : null}
          {done ? null : (
            <Button
              key="copy"
              label="Copy"
              onPress={async press => {
                await disarm()
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

// The ladder's priorities in order (🔴🟡, ✅, …): the fallback identity of a state file from before item ids.
function keyOf(line: string): string {
  return (line.match(/[🔴🟠🟡⏳🧠💰✅]/gu) ?? []).join('') || line
}

// What Hide compares: the ids of the shown items, plus the memo mark when the memo is due. A hidden band comes back
// when an item appears or goes, or when a newly crossed mark makes the memo due again; not when only wording changes.
function hideKeyOf(g: Guide): string {
  const items = Array.isArray(g.items) ? g.items : []
  const ids = items.length > 0 ? items.map(idOf).join('|') : keyOf(g.line)
  return needsMemo(g.ctx ?? null) ? `${ids}|memo:${g.ctx?.mark ?? 'past'}` : ids
}

// The prompt the Use and Copy buttons hand over: the guide line as an instruction the assistant acts on.
function promptFor(line: string): string {
  const body = line.replace(/^\s*🧭\s*/, '').trim()
  return `abofles guide — do this now, in order: ${body}`
}
