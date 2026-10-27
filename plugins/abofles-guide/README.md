# abofles-guide

A band above the prompt box with the Abo Fles **🧭 next** line: what to do now, by priority, computed by the
`abofles` plugin's hooks after every spawn, receipt and prompt (open FAIL / ATTENTION · judged question unasked ·
owner decisions open · partial/low reply not escalated · background agents running · context or memo hygiene ·
agent budget nearly out · the memo's Next). The same line is in every receipt (`- \`next\` → 🧭 …`) and resume block.

It draws a band with buttons and the pane below. It never spawns or blocks, and it never settles an item on your word: it
runs no settle command. It runs two commands, both published by the abofles hooks: `Undo` (Claude's own last resolve)
and the overrides editor's `Save` (`scripts/overrides.py`, which edits the `## abofles overrides` block).

- `Use` puts the top item's fill text in the prompt box as the next prompt (appended after a draft you already typed)
  and takes the band down. If the prompt box is not open it says so and keeps the band: use `Copy`.
- `Re-check` (a 🔴 / 🟠 / 🟡 top item that carries a re-check prompt) puts a verify-then-resolve prompt in the prompt
  box the same way: Claude checks the item, and resolves it only with evidence.
- After Claude resolves an item the band shrinks to `✓ resolved: …` with `Undo` and `Hide`. `Undo` reopens Claude's
  last resolve (it runs the argv from `guide.last_resolved` in the project root and toasts the first line of its
  output) and stays offered until the next turn ends; the row does not depend on anything but that field. While it
  runs (up to 30 s) `Undo` is gone, so a second press cannot start a second run. `Hide` takes that row down (keyed by
  its timestamp; a newer resolve draws again).
- Reopen by hand: `/abofles:resume --reopen <n>` (an owner decision), `/abofles:status --unresolve <id>` (a FAIL or an
  escalation). Exit code 3 from `Undo` toasts `already open`; any other failure toasts `undo failed` with the first
  line of the error and keeps the row, so `Undo` can be pressed again. Exit 0 and exit 3 clear the row.
- `Memo` (when the context is within 50K of its next mark, or past the last one) puts `/abofles:memo` in the prompt box.
- `Copy` puts the Use text on the clipboard.
- `Hide` takes the band down. It is keyed on the ids of the items shown (plus the context mark when the memo is due),
  not on the emojis in the line: the band stays down while the same items are shown, even if their wording changes,
  and comes back when an item appears or goes, or when a newly crossed context mark makes the memo due again.

When nothing is open (every item ✅) the band is hidden, except when the memo is due: then it shows just the meter and
`Memo`. A dim second line, the meter, shows
`ctx 412K / 500K · task 3 spawns · $0.41 · budget 2 left · suggest Opus 5.5 · Medium` (parts without data omitted).
A toast fires once for each 🔴 item that was not toasted before (by item id), not on every refresh while the top stays
red. Fields of the state file with the wrong type are ignored (a bad item is dropped, a bad `task` or `ctx` left out)
rather than taking the band away. The ✅ suggestion in the band follows the memo's Now, which the abofles hook
rewrites after every receipt. It needs `abofles` installed; without it the band stays empty.

## The Abo Fles pane

A pane beside the transcript (the app docks it on the right) with one card per thing Abo Fles keeps for the session. The
hooks write its data into the session's state file (`pane`) and this mod only draws it, in the look of the app's own side
panels (Context, Changes, Environment): each card's header is its title with a caret (`▾` open, `›` folded; a click folds
it, and the folds are remembered across sessions) and a short summary at the right, with a coloured dot when it needs you.
Numbers are label/value rows with the values dim at the right; colour is a dot, a meter or a word (`PASS`, `FAIL`), never an
emoji. Every text wraps (nothing is cut, markdown marks are dropped); a long list shows its first rows and `Show all N`.

- **Guide**: the top item after a dot in its colour (red, amber, green), up to two more under it, then `Show all`; Context
  with a meter (amber once the memo is due), This task and Agent budget as rows; `Use` (primary), `Re-check`, `Copy`, and
  `Hide` as a link at the right; `Undo` after Claude's resolve. Nothing open: "Next from the memo" and what the memo
  left, with `Save memo` near the next context mark. A hidden card shows `Show`. With `Guide place = pane` (the default)
  the band above the prompt box is empty while the pane is up.
- **Resume**: Now, Next, Needs you (numbered in amber, the first three, then `Show all`), Left; Last receipts as a table
  under its own caret (time · spawns · $ · saved %; a row's caret opens its done / check / open); then Session, Memo saved
  and Away. What `/abofles:resume` prints (`Resume place = pane`, the default).
- **Spawns**: the saving first (`32% saved`, `$14.36 of $21.26 on Opus 5.5`), a meter split by model and a table (■ Haiku
  · Sonnet · Opus: spawns, $, share of the spend), Tokens, and Open FAIL in red when a FAIL is still open (one resolved by
  hand with evidence is not); Running (`● LIVE`, the ask, its start time, the model); History newest first, five rows then
  `Show all`: the verdict (`PASS` / `FAIL`, or the status) in a column of its own, the ask with its cost at the right, and a
  dim line (`sonnet·high · 1.9M`, `resolved` for a FAIL closed by hand). What `/abofles:spawns` prints
  (`Spawns place = pane`, the default).
- **Overrides**: a table of the values a file sets (key, value, `this project` / `all projects`), a link to the other
  lines, and `Edit`, which turns the pane into the editor page below. Always drawn.

`Guide place`, `Resume place` and `Spawns place` (`pane` | `band` / `output`) put each card in the pane or keep today's
view; the cards that are not placed in the pane are not drawn.

Opening: the pane opens by itself once per session when the state has something placed in it, unless you closed it by
hand (that is remembered across sessions, as is being open). Unasked, the app places it from 144 terminal columns, and
from 110 once you have opened it yourself; on a narrower window it waits, and the band shows one row, `Abo Fles · <top
item>`, with a `Pane` button that opens it at any width. `/abofles-pane` (the command this mod registers) opens the pane, or closes
it when it is up. `/abofles:pane` is the abofles plugin's entry that points to it (the mod answers it too when the app routes it here);
without this mod it prints the resume block and the spawn history as text.

How the abofles hook knows this mod is on (it then places the cards in the pane, else in the band/chat): the first `abofles-guide@…` key of
`~/.claude/settings.json` `enabledPlugins` decides (`false` = off); with no such key, a `abofles-guide` folder in
`~/.claude/plugins/cache/*/` or in a folder of `CLAUDE_CODE_PLUGIN_DIRS` (env) turns it on.

### The overrides editor

`Edit` turns the pane into a page of its own, laid out as the app's settings (`‹ Overrides` returns to the cards; the
draft is kept). It edits the simple keys of the `## abofles overrides` block (the table is in the abofles README):

- **Save to**: two buttons, `This project` (the project's `CLAUDE.md`, or `.claude/CLAUDE.md` when that is the file holding
  the block) and `All projects` (`~/.claude/CLAUDE.md`); the file is named under them. The project file wins over the user
  file when both set a key.
- The keys in folding groups: **Session** (Main session, Session cap, Context marks, Break, Pace), **Agents** (Agents,
  Parallel, Agent budgets, Review gate, Questions), **Output** (Receipt, Guide, Resume, Language), **Where it shows**
  (Guide place, Resume place, Spawns place, Receipt place); a key the table adds later goes to **More**. Each group's summary says
  `default`, how many keys a file sets, or how many are edited.
- Each key is a settings row: its name (`· edited` beside it while unsaved) and a one-line help (plus the file that sets
  it) on the left, the control on the right — a list for the keys with a fixed set of values (its first entry,
  `default (<value>)`, removes the line), an input for numbers, texts and lists (the default as its placeholder). The name
  is drawn beside the control, so the control carries no label of its own. `Agents` and `Receipt` also offer
  `custom value`, which opens an input for `N` agents or `savings N`.
- **Other overrides** (folded while the chosen file has none): a multi-line input for the other forms (cell, cap, tier,
  `Reviewers`, `Workflow`, `Review` lines) of the chosen file, one per line; lines of the other file are listed under it
  and edited there. Changing `Save to` drops the typed lines (they belong to one file).
- Edits are kept as a draft; the page header and the main page's card say `N unsaved`.
- `Save N changes` runs the abofles plugin's `scripts/overrides.py` (the argv the hook publishes as `pane.cmd.overrides`)
  with the changes on stdin: it edits the block in place, adds new keys, removes the ones set to the default, and keeps
  everything else in the file as it was. It toasts `Saved to <file>`, the fields show the new values and the draft is
  cleared. A refused value (exit 2) toasts the first line of the error and keeps the draft.
- `Ask Claude` puts `Apply in <file> \`## abofles overrides\`: - Key = value …` (only the changed keys) in the prompt box
  instead, so Claude makes the edit. `Discard` (a link, shown while there are edits) clears the draft.
- If the file changed while you were editing (exit 3), Save toasts `CLAUDE.md changed while saving — reload the pane and
  save again` and keeps the draft.

Commands the pane runs (Undo, Save) come from the state file and run only in the shape the abofles hook writes them:
`bash`, the abofles plugin's `scripts/py` launcher, then `memo.py`, `status.py` or `overrides.py` from that same folder;
anything else is dropped. They need `bash` on PATH (Git Bash on Windows), as the abofles hooks do.

Install: `/plugin install abofles-guide@sajadh92` (after `/plugin marketplace add <this repo>`), or
`claude --plugin-dir plugins/abofles-guide`. Validate: `claude plugin validate plugins/abofles-guide`.
Turn the line off everywhere with `- Guide = off` in the project's `## abofles overrides`.
