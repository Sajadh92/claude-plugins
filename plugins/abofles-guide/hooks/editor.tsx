import type { EngineInterface } from 'claude-code'

import type { Pane, PaneOverrideKey, PaneOverrides } from '../types'
import { applyOverrides, card, claimSave, getPaneDraft, getPaneSaving, plain, refresh, releaseSave, setFold, setPaneView, updatePaneDraft } from './shared'
import type { Folds, Ui } from './shared'

// The overrides of the Abo Fles pane, in two places. On the pane's main page, a short card: a table of the values a file sets
// (key, value, which file), the other lines, and Edit. Edit turns the pane into the editor page, laid out as the app's settings:
// the target file (two buttons), then the keys in folding groups, one settings row each — the name and a one-line help on the left,
// the control (a Select for the keys with a fixed set of values, an Input for numbers, texts and lists) on the right — the other
// forms as lines of one multi-line Input, and Save / Ask Claude / Discard. Edits live in the paneDraft atom ('' = back to the
// default) until Save runs the abofles plugin's overrides.py, which edits the `## abofles overrides` block of the chosen file and
// prints the new table. Nothing is written by this mod itself.

type Draft = Record<string, string>
type Scope = 'project' | 'user'

const SCOPE = '@scope'
const RAW = '@raw'
const CUSTOM = '@custom:'
const DEFAULT_PICK = '@default' // the Select entries that are not a value of the key
const CUSTOM_PICK = '@custom'

// The keys that also take a value of their own: the Input a "custom value" pick opens, what it starts with and what it asks for.
const CUSTOM_KEYS: Record<string, { start: string; hint: string }> = {
  Agents: { start: '3', hint: 'N agents per task' },
  Receipt: { start: 'savings 30', hint: 'savings N (percent)' },
}

// The editor's groups, in order, and each key's group and help line. A key the table adds later lands in "More", without help.
const GROUPS = ['Session', 'Agents', 'Output', 'Where it shows', 'More'] as const
const KEY_INFO: Record<string, { group: (typeof GROUPS)[number]; help: string }> = {
  'Main session': { group: 'Session', help: 'Model you run on, e.g. opus·high' },
  'Session cap': { group: 'Session', help: 'Units before it stops to ask' },
  'Context marks': { group: 'Session', help: 'K tokens that ask for a memo' },
  Break: { group: 'Session', help: 'Minutes away before the resume' },
  Pace: { group: 'Session', help: 'fast: fewer stops, short receipts' },
  Agents: { group: 'Agents', help: 'Agents per task: ask, auto, N, off' },
  Parallel: { group: 'Agents', help: 'Background agents at once' },
  'Agent budgets': { group: 'Agents', help: 'Per tier T1 to T4, under auto' },
  'Review gate': { group: 'Agents', help: 'Holds the receipt for reviewers' },
  Questions: { group: 'Agents', help: 'A Judge answers first' },
  Receipt: { group: 'Output', help: 'Receipt form; savings N = only past N%' },
  Guide: { group: 'Output', help: 'The next-step line' },
  Resume: { group: 'Output', help: 'What it covers; off = not in chat' },
  Language: { group: 'Output', help: 'Language of owner questions' },
  'Guide place': { group: 'Where it shows', help: 'Pane, or the band over the prompt' },
  'Resume place': { group: 'Where it shows', help: 'Pane, or printed in the chat' },
  'Spawns place': { group: 'Where it shows', help: 'Pane, or printed in the chat' },
  'Receipt place': { group: 'Where it shows', help: 'Recorded to the pane, or printed' },
}

// Which file a value comes from, as the badge says it.
const WHERE: Record<string, string> = { project: 'this project', user: 'all projects' }

export const scopeOf = (d: Draft): Scope => (d[SCOPE] === 'user' ? 'user' : 'project')

// The value as it would stand in the file: '' = no line (the default). A default value typed over a default is no line either.
export const written = (k: PaneOverrideKey, v: string): string => {
  const t = v.trim()
  return t === '' || (k.source === 'default' && t === k.value) ? '' : t
}

const baseline = (k: PaneOverrideKey): string => written(k, k.value)

const isChanged = (k: PaneOverrideKey, d: Draft): boolean => d[k.key] !== undefined && written(k, d[k.key]) !== baseline(k)

export const changedKeys = (ov: PaneOverrides, d: Draft): PaneOverrideKey[] => ov.keys.filter(k => isChanged(k, d))

const linesOf = (text: string): string[] => text.split('\n').map(l => l.replace(/^\s*-\s*/, '').trim()).filter(Boolean)
const rawBase = (ov: PaneOverrides, scope: Scope): string[] => ov.raw.filter(r => r.source === scope).map(r => r.line)
const rawLines = (ov: PaneOverrides, d: Draft, scope: Scope): string[] => (d[RAW] === undefined ? rawBase(ov, scope) : linesOf(d[RAW]))
const rawChanged = (ov: PaneOverrides, d: Draft, scope: Scope): boolean => d[RAW] !== undefined && rawLines(ov, d, scope).join('\n') !== rawBase(ov, scope).join('\n')

export const dirtyCount = (ov: PaneOverrides, d: Draft): number => changedKeys(ov, d).length + (rawChanged(ov, d, scopeOf(d)) ? 1 : 0)

// The prompt "Ask Claude to apply" fills: only what changed, in the block's own `- Key = value` shape.
export function askText(file: string, ov: PaneOverrides, d: Draft): string {
  const parts = changedKeys(ov, d).map(k => {
    const v = written(k, d[k.key])
    return v === '' ? `- ${k.key} removed (back to the default)` : `- ${k.key} = ${v}`
  })
  const scope = scopeOf(d)
  if (rawChanged(ov, d, scope)) {
    const base = rawBase(ov, scope)
    const now = rawLines(ov, d, scope)
    parts.push(...now.filter(l => !base.includes(l)).map(l => `- ${l}`), ...base.filter(l => !now.includes(l)).map(l => `- remove: ${l}`))
  }
  return `Apply in ${file} \`## abofles overrides\`: ${parts.join(' ')}`
}

// A path as the card shows it: relative to the project, or with ~ for the home folder.
function shortPath(path: string, root: string, home: string): string {
  if (root && path.startsWith(`${root}/`)) return path.slice(root.length + 1)
  if (home && path.startsWith(`${home}/`)) return `~${path.slice(home.length)}`
  return path
}

const firstLine = (text: string): string => text.split('\n').find(l => l.trim()) ?? ''

function setDraft($: EngineInterface, key: string, value: string, custom: boolean | null = null) {
  return updatePaneDraft($, cur => {
    const next: Draft = { ...cur, [key]: value }
    if (custom === true) next[`${CUSTOM}${key}`] = '1'
    if (custom === false) delete next[`${CUSTOM}${key}`]
    return next
  })
}

// Another scope is another file: the lines typed for the old one are dropped, so they are never written to the new one.
function setScope($: EngineInterface, scope: Scope) {
  return updatePaneDraft($, cur => {
    if (scopeOf(cur) === scope) return cur
    const next: Draft = { ...cur, [SCOPE]: scope }
    delete next[RAW]
    return next
  })
}

// ---- the buttons

async function save($: EngineInterface, p: Pane, ov: PaneOverrides, d: Draft, file: string) {
  const argv = p.cmd.overrides
  if (!argv) {
    $.ui.toast('Update the abofles plugin to save here')
    return
  }
  const scope = scopeOf(d)
  const set: Record<string, string> = {}
  for (const k of changedKeys(ov, d)) set[k.key] = written(k, d[k.key])
  const body: { set: Record<string, string>; raw?: string[] } = { set }
  if (rawChanged(ov, d, scope)) body.raw = rawLines(ov, d, scope)
  if (Object.keys(set).length === 0 && body.raw === undefined) {
    $.ui.toast('Nothing to save')
    return
  }
  if (!(await claimSave($))) return
  try {
    const r = await $.process.run([...argv, 'set', '--scope', scope], { ...(p.root ? { cwd: p.root } : {}), stdin: JSON.stringify(body) })
    if (r.exitCode !== 0) {
      $.ui.toast(firstLine(r.stderr) || firstLine(r.stdout) || `Save failed (exit ${r.exitCode})`) // the draft stays
      return
    }
    let again: unknown = null
    try {
      again = JSON.parse(r.stdout)
    } catch {
      // the file is written; the state file has the table
    }
    if (again !== null) await applyOverrides($, again)
    else await refresh($)
    await updatePaneDraft($, cur => (cur[SCOPE] ? { [SCOPE]: cur[SCOPE] } : {}))
    $.ui.toast(`Saved to ${file}`)
  } catch (err) {
    $.ui.toast(`Save failed — ${err instanceof Error ? err.message : String(err)}`)
  } finally {
    await releaseSave($)
  }
}

async function askClaude($: EngineInterface, ov: PaneOverrides, d: Draft, file: string) {
  if (dirtyCount(ov, d) === 0) {
    $.ui.toast('Nothing changed to ask for')
    return
  }
  const text = askText(file, ov, d)
  const have = (await $.prompt.read()).text.trim()
  const r = await $.prompt.fill({ text: have ? `\n${text}` : text, mode: have ? 'append' : 'replace' })
  if (!r.isFilled) $.ui.toast('Prompt box is not open')
}

// ---- the editor page

// The control column of a settings row, in cells (about the app's 128 px).
const CONTROL = 16

// One key as a settings row: the name (with "· edited" while unsaved) and its help on the left, the control on the right; the
// custom value Input under it when open. The name is drawn beside the control, so the control itself carries no label.
function field($: EngineInterface, ui: Ui, k: PaneOverrideKey, d: Draft) {
  const { Box, Input, Select, Text } = ui
  const help = [KEY_INFO[k.key]?.help, WHERE[k.source]].filter(Boolean).join(' · ')
  const edited = isChanged(k, d)
  const fallback = k.default ? `default ${k.default}` : 'none'
  const custom = CUSTOM_KEYS[k.key]
  const cur = written(k, d[k.key] ?? k.value)
  const known = k.options.find(o => o.toLowerCase() === cur.toLowerCase())
  const open = k.kind === 'select' && custom !== undefined && (d[`${CUSTOM}${k.key}`] !== undefined || (cur !== '' && known === undefined))
  let control: JSX.Element
  if (k.kind !== 'select') {
    control = <Input key={`in:${k.key}`} value={d[k.key] ?? k.value} placeholder={fallback} onInput={v => setDraft($, k.key, v)} onSubmit={v => setDraft($, k.key, v)} />
  } else {
    const pick = open ? CUSTOM_PICK : cur === '' ? DEFAULT_PICK : (known ?? cur)
    const options = [
      { value: DEFAULT_PICK, label: k.default ? `default (${k.default})` : 'default' },
      ...k.options.map(o => ({ value: o })),
      ...(custom ? [{ value: CUSTOM_PICK, label: 'custom value' }] : known === undefined && cur !== '' ? [{ value: cur }] : []),
    ]
    const onSelect = (v: string) => {
      if (v === CUSTOM_PICK) return setDraft($, k.key, cur !== '' && known === undefined ? cur : custom?.start ?? '', true)
      return setDraft($, k.key, v === DEFAULT_PICK ? '' : v, false)
    }
    control = <Select key={`sel:${k.key}`} options={options} value={pick} onSelect={onSelect} />
  }
  return (
    <Box flexDirection="column" rowGap={open ? 1 : 0}>
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={2}>
        <Box flexDirection="column" flexShrink={1}>
          <Box flexDirection="row" flexWrap="wrap">
            <Text>{k.key}</Text>
            {edited ? <Text color="warning">{' · edited'}</Text> : null}
          </Box>
          {help ? <Text size="caption" dimColor>{help}</Text> : null}
        </Box>
        <Box width={CONTROL} flexShrink={0} justifyContent="flex-end">
          {control}
        </Box>
      </Box>
      {open ? (
        <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={2}>
          <Text size="caption" dimColor>{custom?.hint ?? ''}</Text>
          <Box width={CONTROL} flexShrink={0}>
            <Input key={`custom:${k.key}`} value={d[k.key] ?? k.value} placeholder={custom?.hint} onInput={v => setDraft($, k.key, v, true)} onSubmit={v => setDraft($, k.key, v, true)} />
          </Box>
        </Box>
      ) : null}
    </Box>
  )
}

// What the page and the short card both need: the draft, the file names, the counts.
async function editorState($: EngineInterface, p: Pane, ov: PaneOverrides) {
  const d = (await getPaneDraft($)) ?? {}
  const home = (await $.env.get('HOME')) ?? ''
  const scope = scopeOf(d)
  const files = { project: shortPath(ov.files.project, p.root, home) || 'CLAUDE.md', user: shortPath(ov.files.user, p.root, home) || '~/.claude/CLAUDE.md' }
  return { d, scope, files, file: files[scope], dirty: dirtyCount(ov, d) }
}

const unreadable = 'Pane data unreadable — update both abofles and abofles-guide'

// The page's top row: ‹ Overrides (back to the cards) and the unsaved count.
function pageTop($: EngineInterface, ui: Ui, dirty: number) {
  const { Box, Button, Text } = ui
  return (
    <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1} paddingX={1}>
      <Button key="back" plain onPress={() => setPaneView($, 'main')}>
        <Text dimColor>{'‹ '}</Text>
        <Text weight="medium">Overrides</Text>
      </Button>
      {dirty > 0 ? <Text color="warning">{`${dirty} unsaved`}</Text> : null}
    </Box>
  )
}

// The page the pane turns into: the target file, the groups of keys, the other forms, and Save / Ask Claude / Discard.
export async function overridesPage($: EngineInterface, ui: Ui, p: Pane | null, folds: Folds) {
  const { Box, Button, Input, Text } = ui
  const ov: PaneOverrides | null = p?.overrides ?? null
  if (p === null || ov === null) {
    return (
      <Box flexDirection="column" gap={1}>
        {pageTop($, ui, 0)}
        <Text dimColor>{unreadable}</Text>
      </Box>
    )
  }
  const { d, scope, file, dirty } = await editorState($, p, ov)
  const saving = (await getPaneSaving($)) === true
  const raw = rawLines(ov, d, scope)
  const others = ov.raw.filter(r => r.source !== scope)
  const groups = GROUPS.map(name => ({ name, keys: ov.keys.filter(k => (KEY_INFO[k.key]?.group ?? 'More') === name) })).filter(g => g.keys.length > 0)
  const rawEdited = rawChanged(ov, d, scope)
  const scopeButton = (value: Scope, label: string) => <Button key={`scope:${value}`} label={label} variant={scope === value ? 'primary' : 'secondary'} onPress={() => setScope($, value)} />
  return (
    <Box flexDirection="column" gap={1}>
      {pageTop($, ui, dirty)}
      <Box flexDirection="column" borderStyle="round" borderDimColor paddingX={2} paddingY={1} rowGap={1}>
        <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1} flexWrap="wrap">
          <Text>Save to</Text>
          <Box flexDirection="row" gap={1}>
            {scopeButton('project', 'This project')}
            {scopeButton('user', 'All projects')}
          </Box>
        </Box>
        <Text size="caption" dimColor>{`${file} · the project file wins over yours`}</Text>
      </Box>
      {groups.map(g => {
        const edited = g.keys.filter(k => isChanged(k, d)).length
        const set = g.keys.filter(k => WHERE[k.source]).length
        return card(
          $,
          ui,
          { id: `g:${g.name}`, title: g.name, summary: edited > 0 ? `${edited} edited` : set > 0 ? `${set} set` : 'default', tone: edited > 0 ? 'warning' : undefined, folds },
          <Box flexDirection="column" rowGap={1}>{g.keys.map(k => field($, ui, k, d))}</Box>,
        )
      })}
      {card(
        $,
        ui,
        // folded while this file has none of these lines: they are the rare, free-form overrides
        { id: 'g:Other', title: 'Other overrides', summary: rawEdited ? 'edited' : raw.length > 0 ? `${raw.length} line${raw.length === 1 ? '' : 's'}` : others.length > 0 ? `${others.length} in ${WHERE[others[0].source] ?? others[0].source}` : null, tone: rawEdited ? 'warning' : undefined, folds, def: raw.length > 0 || rawEdited },
        <Box flexDirection="column" rowGap={1}>
          <Text size="caption" dimColor>One per line: topic tiers, cells, reviewers, workflows — e.g. Reviewers: Money = finance, tester</Text>
          <Input key="raw" rows={Math.min(8, Math.max(2, raw.length + 1))} placeholder="Topic: Billing = T3" value={d[RAW] ?? rawBase(ov, scope).join('\n')} onInput={v => setDraft($, RAW, v)} onSubmit={v => setDraft($, RAW, v)} />
          {others.map(r => (
            <Text size="caption" dimColor>{`${r.line} — in ${WHERE[r.source] ?? r.source}; switch Save to, to edit it`}</Text>
          ))}
        </Box>,
      )}
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1} paddingX={1}>
        <Box flexDirection="row" flexWrap="wrap" gap={1}>
          {saving ? (
            <Button key="save" label="Saving…" variant="secondary" onPress={() => undefined} />
          ) : (
            <Button key="save" label={dirty > 0 ? `Save ${dirty} change${dirty === 1 ? '' : 's'}` : 'Save'} variant={dirty > 0 ? 'primary' : 'secondary'} onPress={() => save($, p, ov, d, file)} />
          )}
          <Button key="ask" label="Ask Claude" variant="secondary" onPress={() => askClaude($, ov, d, file)} />
        </Box>
        {dirty > 0 ? <Button key="reset" label="Discard" plain dimColor onPress={() => updatePaneDraft($, cur => (cur[SCOPE] ? { [SCOPE]: cur[SCOPE] } : {}))} /> : null}
      </Box>
    </Box>
  )
}

// Opens the editor page; `group` (an editor group's fold id) is opened with it.
async function openEditor($: EngineInterface, group?: string) {
  if (group) await setFold($, group, true)
  await setPaneView($, 'overrides')
}

// The short card on the pane's main page: a table of the values a file sets, the other lines, and Edit.
export async function overridesCard($: EngineInterface, ui: Ui, p: Pane | null, folds: Folds) {
  const { Box, Button, Text } = ui
  const ov: PaneOverrides | null = p?.overrides ?? null
  if (p === null || ov === null) return card($, ui, { id: 'overrides', title: 'Overrides', folds }, <Text dimColor>{unreadable}</Text>)
  const { dirty } = await editorState($, p, ov)
  const set = ov.keys.filter(k => WHERE[k.source])
  const rows: JSX.Element[] = set.map(k => (
    <Box flexDirection="row" columnGap={1}>
      <Box flexGrow={1} flexShrink={1}>
        <Text dimColor>{k.key}</Text>
      </Box>
      <Text>{plain(k.value)}</Text>
      <Box width={13} justifyContent="flex-end" flexShrink={0}>
        <Text size="caption" dimColor>{WHERE[k.source]}</Text>
      </Box>
    </Box>
  ))
  const summary = dirty > 0 ? `${dirty} unsaved` : set.length > 0 ? `${set.length} set` : 'defaults'
  return card(
    $,
    ui,
    { id: 'overrides', title: 'Overrides', summary, tone: dirty > 0 ? 'warning' : undefined, folds },
    <Box flexDirection="column" rowGap={1}>
      {rows.length > 0 ? <Box flexDirection="column">{rows}</Box> : null}
      {ov.raw.length > 0 ? (
        <Button key="edit-other" plain dimColor onPress={() => openEditor($, 'g:Other')}>
          {`${ov.raw.length} other line${ov.raw.length === 1 ? '' : 's'} · tiers, reviewers ›`}
        </Button>
      ) : null}
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1}>
        <Text size="caption" dimColor>{set.length > 0 ? 'Everything else uses the defaults.' : 'Everything uses the defaults.'}</Text>
        <Button key="edit-overrides" label="Edit" variant="secondary" onPress={() => openEditor($)} />
      </Box>
    </Box>,
  )
}
