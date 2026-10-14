# abofles-guide

A band above the prompt box with the Abo Fles **🧭 next** line: what to do now, by priority, computed by the
`abofles` plugin's hooks after every spawn, receipt and prompt (open FAIL / ATTENTION · judged question unasked ·
owner decisions open · partial/low reply not escalated · background agents running · context or memo hygiene ·
agent budget nearly out · the memo's Next). The same line is in every receipt (`- \`next\` → 🧭 …`) and resume block.

It only draws: a band with buttons. It never spawns, blocks or writes by itself; the only commands it runs are the
ones the item carries, when you press `Resolve` or `Undo`.

- `Use` puts the top item's fill text in the prompt box as the next prompt (appended after a draft you already typed)
  and takes the band down. If the prompt box is not open it says so and keeps the band: use `Copy`.
- `Re-check` (a 🔴 top item that carries a re-check prompt; such an item has no `Resolve`) puts that prompt in the
  prompt box the same way.
- `Resolve` (only when the top item carries a command) asks twice: the first press turns it into `Confirm resolve`
  for 5 s, the second runs the command in the project root and toasts the first line of its output. The arm belongs to
  that item (by its id): a different item with the same wording needs its own first press, and an arm older than 5 s
  (a reload, a late redraw) only re-arms. While the command runs (up to 30 s) `Resolve` and `Undo` are gone, so a
  second press cannot start a second run. After a success the band shrinks to `✓ resolved: …` with `Undo` (runs the
  item's undo command, when it has one) and `Hide`, until the next turn completes; the row does not depend on the
  guide still being on disk. Each hand-resolve is written to the memo journal.
- Exit code 3 from the command means nothing changed: `Resolve` toasts `already resolved` and offers no `Undo`;
  `Undo` toasts `already open` and clears the row. Any other failure toasts `resolve failed` / `undo failed` with the
  first line of the error; a failed `Resolve` keeps the band, a failed `Undo` clears the row.
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

Install: `/plugin install abofles-guide@sajadh92` (after `/plugin marketplace add <this repo>`), or
`claude --plugin-dir plugins/abofles-guide`. Validate: `claude plugin validate plugins/abofles-guide`.
Turn the line off everywhere with `- Guide = off` in the project's `## abofles overrides`.
