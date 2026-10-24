import type { EngineInterface } from 'claude-code'

import type { Pane, PaneOverrideKey, PaneOverrides } from '../types'
import { applyOverrides, card, claimSave, getPaneDraft, getPaneSaving, kv, plain, refresh, releaseSave, setPaneView, updatePaneDraft } from './shared'
import type { Folds, Ui } from './shared'

// The overrides of the Abo Fles pane, in two places. On the pane's main page, a short card: what is set (key = value, and in which
// file) and an "Edit overrides" button. That button turns the pane into the editor page: the target file (scope), the simple keys in
// groups (a Select for the keys with a fixed set of values, an Input for numbers, texts and lists; each with a one-line help and a badge
// when a file sets it), the other forms as lines of one multi-line Input, and the buttons. Edits live in the paneDraft atom ('' = back
// to the default) until Save runs the abofles plugin's overrides.py, which edits the `## abofles overrides` block of the chosen file and
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
  'Main session': { group: 'Session', help: 'The model·effort you run on, e.g. opus·high' },
  'Session cap': { group: 'Session', help: 'Units per session before it stops to ask' },
  'Context marks': { group: 'Session', help: 'Context sizes (K tokens) that ask for a memo, then /compact' },
  Break: { group: 'Session', help: 'Minutes away before the resume shows again; off = never' },
  Pace: { group: 'Session', help: 'fast: fewer stops, no Judge on small questions, short receipts' },
  Agents: { group: 'Agents', help: 'ask once, size by tier (auto), N per task, or off' },
  Parallel: { group: 'Agents', help: 'Background agents running at once' },
  'Agent budgets': { group: 'Agents', help: 'Agents per tier T1, T2, T3, T4 under Agents = auto' },
  'Review gate': { group: 'Agents', help: 'Holds the receipt while a required reviewer has not run' },
  Questions: { group: 'Agents', help: 'judge: a Judge agent tries to answer before you are asked' },
  Receipt: { group: 'Output', help: 'The receipt form; savings N prints it only when N% was saved' },
  Guide: { group: 'Output', help: 'The 🧭 next-step line' },
  Resume: { group: 'Output', help: 'What the resume covers; off keeps it out of the chat' },
  Language: { group: 'Output', help: 'The language owner questions are written in' },
  'Guide place': { group: 'Where it shows', help: 'This pane, or the band above the prompt' },
  'Resume place': { group: 'Where it shows', help: 'This pane, or printed in the chat' },
  'Spawns place': { group: 'Where it shows', help: 'This pane, or printed in the chat' },
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

// One key: its control (named by its label), the custom value Input when open, then a dim help line and the badge.
function field($: EngineInterface, ui: Ui, k: PaneOverrideKey, d: Draft) {
  const { Box, Input, Select, Text } = ui
  const help = KEY_INFO[k.key]?.help
  const badge = isChanged(k, d) ? (
    <Text size="caption" color="warning">
      edited
    </Text>
  ) : WHERE[k.source] ? (
    <Text size="caption" color="suggestion">
      {WHERE[k.source]}
    </Text>
  ) : null
  const meta =
    help || badge ? (
      <Box flexDirection="row" flexWrap="wrap" columnGap={1}>
        {help ? (
          <Text size="caption" dimColor>
            {help}
          </Text>
        ) : null}
        {badge}
      </Box>
    ) : null
  const fallback = k.default ? `default ${k.default}` : 'none'
  if (k.kind !== 'select') {
    return (
      <Box flexDirection="column">
        <Input key={`in:${k.key}`} label={k.key} value={d[k.key] ?? k.value} placeholder={fallback} onInput={v => setDraft($, k.key, v)} onSubmit={v => setDraft($, k.key, v)} />
        {meta}
      </Box>
    )
  }
  const custom = CUSTOM_KEYS[k.key]
  const cur = written(k, d[k.key] ?? k.value)
  const known = k.options.find(o => o.toLowerCase() === cur.toLowerCase())
  const open = custom !== undefined && (d[`${CUSTOM}${k.key}`] !== undefined || (cur !== '' && known === undefined))
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
  return (
    <Box flexDirection="column">
      <Select key={`sel:${k.key}`} label={k.key} options={options} value={pick} onSelect={onSelect} />
      {open ? <Input key={`custom:${k.key}`} label={`${k.key} value`} value={d[k.key] ?? k.value} placeholder={custom?.hint} onInput={v => setDraft($, k.key, v, true)} onSubmit={v => setDraft($, k.key, v, true)} /> : null}
      {meta}
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

// The page the pane turns into: Back, the target file, the groups of keys, the other forms, and Save / Ask Claude / Discard.
export async function overridesPage($: EngineInterface, ui: Ui, p: Pane | null, folds: Folds) {
  const { Box, Button, Input, Select, Text } = ui
  const ov: PaneOverrides | null = p?.overrides ?? null
  const back = (
    <Button key="back" plain dimColor onPress={() => setPaneView($, 'main')}>
      ‹ Back
    </Button>
  )
  if (p === null || ov === null) {
    return (
      <Box flexDirection="column" gap={1}>
        {back}
        <Text dimColor>{unreadable}</Text>
      </Box>
    )
  }
  const { d, scope, files, file, dirty } = await editorState($, p, ov)
  const saving = (await getPaneSaving($)) === true
  const raw = rawLines(ov, d, scope)
  const others = ov.raw.filter(r => r.source !== scope)
  const groups = GROUPS.map(name => ({ name, keys: ov.keys.filter(k => (KEY_INFO[k.key]?.group ?? 'More') === name) })).filter(g => g.keys.length > 0)
  const setIn = (keys: PaneOverrideKey[]): string | null => {
    const edited = keys.filter(k => isChanged(k, d)).length
    const set = keys.filter(k => WHERE[k.source]).length
    return edited > 0 ? `${edited} edited` : set > 0 ? `${set} set` : null
  }
  const rawEdited = rawChanged(ov, d, scope)
  return (
    <Box flexDirection="column" gap={1}>
      <Box flexDirection="row" justifyContent="space-between" alignItems="center" columnGap={1}>
        {back}
        <Box flexDirection="row" flexWrap="wrap" columnGap={1} flexShrink={1}>
          <Text weight="semibold">Overrides</Text>
          {dirty > 0 ? <Text color="warning">{`${dirty} unsaved`}</Text> : null}
        </Box>
      </Box>
      <Box flexDirection="column">
        <Select
          key="scope"
          label="Save to"
          options={[
            { value: 'project', label: 'This project' },
            { value: 'user', label: 'All projects' },
          ]}
          value={scope}
          onSelect={v => setScope($, v === 'user' ? 'user' : 'project')}
        />
        <Text size="caption" dimColor>{file}</Text>
      </Box>
      {groups.map(g => {
        const summary = setIn(g.keys)
        return card(
          $,
          ui,
          { id: `g:${g.name}`, title: g.name, summary, tone: summary?.endsWith('edited') ? 'warning' : undefined, folds },
          <Box flexDirection="column" rowGap={1}>{g.keys.map(k => field($, ui, k, d))}</Box>,
        )
      })}
      {card(
        $,
        ui,
        // folded while this file has none of these lines: they are the rare, free-form overrides
        { id: 'g:Other', title: 'Other overrides', summary: rawEdited ? 'edited' : raw.length > 0 ? `${raw.length} line${raw.length === 1 ? '' : 's'}` : others.length > 0 ? `${others.length} in ${WHERE[others[0].source] ?? others[0].source}` : null, tone: rawEdited ? 'warning' : undefined, folds, def: raw.length > 0 || rawEdited },
        <Box flexDirection="column">
          <Text size="caption" dimColor>One per line: topic tiers, cells, reviewers, workflows — e.g. Reviewers: Money = finance, tester</Text>
          <Input key="raw" label="Lines" rows={Math.min(8, Math.max(2, raw.length + 1))} value={d[RAW] ?? rawBase(ov, scope).join('\n')} onInput={v => setDraft($, RAW, v)} onSubmit={v => setDraft($, RAW, v)} />
          {others.map(r => (
            <Text size="caption" dimColor>{`${r.line} — in ${WHERE[r.source] ?? r.source}; switch Save to, to edit it`}</Text>
          ))}
        </Box>,
      )}
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        {saving ? (
          <Button key="save" label="Saving…" variant="secondary" onPress={() => undefined} />
        ) : (
          <Button key="save" label="Save" variant={dirty > 0 ? 'primary' : 'secondary'} onPress={() => save($, p, ov, d, file)} />
        )}
        <Button key="ask" label="Ask Claude to apply" variant="secondary" onPress={() => askClaude($, ov, d, file)} />
        {dirty > 0 ? <Button key="reset" label="Discard edits" variant="secondary" onPress={() => updatePaneDraft($, cur => (cur[SCOPE] ? { [SCOPE]: cur[SCOPE] } : {}))} /> : null}
      </Box>
    </Box>
  )
}

// The short card on the pane's main page: each value a file sets, the other lines' count, and "Edit overrides".
export async function overridesCard($: EngineInterface, ui: Ui, p: Pane | null, folds: Folds) {
  const { Box, Button, Text } = ui
  const ov: PaneOverrides | null = p?.overrides ?? null
  if (p === null || ov === null) return card($, ui, { id: 'overrides', title: 'Overrides', folds }, <Text dimColor>{unreadable}</Text>)
  const { dirty } = await editorState($, p, ov)
  const set = ov.keys.filter(k => WHERE[k.source])
  // one row per value a file sets, as the app's panels read: the key, then the value and the file at the right
  const rows: JSX.Element[] = set.map(k => kv(ui, k.key, `${plain(k.value)} · ${WHERE[k.source]}`))
  if (ov.raw.length > 0) rows.push(kv(ui, 'Other lines', String(ov.raw.length)))
  if (rows.length === 0) rows.push(<Text dimColor>All defaults</Text>)
  const summary = dirty > 0 ? `${dirty} unsaved` : set.length > 0 ? `${set.length} set` : null
  return card(
    $,
    ui,
    { id: 'overrides', title: 'Overrides', summary, tone: dirty > 0 ? 'warning' : undefined, folds },
    <Box flexDirection="column" rowGap={1}>
      <Box flexDirection="column">{rows}</Box>
      <Box flexDirection="row">
        <Button key="edit-overrides" label="Edit overrides" variant="secondary" onPress={() => setPaneView($, 'overrides')} />
      </Box>
    </Box>,
  )
}
