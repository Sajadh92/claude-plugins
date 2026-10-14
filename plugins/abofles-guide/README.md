# abofles-guide

A band above the prompt box with the Abo Fles **🧭 next** line: what to do now, by priority, computed by the
`abofles` plugin's hooks after every spawn, receipt and prompt (open FAIL / ATTENTION · judged question unasked ·
owner decisions open · partial/low reply not escalated · background agents running · context or memo hygiene ·
agent budget nearly out · the memo's Next). The same line is in every receipt (`- \`next\` → 🧭 …`) and resume block.

It only draws: a band with buttons — `Use` puts the top item's fill text in the prompt box as the next prompt (appended
after a draft you already typed) and takes the band down, `Resolve` (only when the top item carries a command) runs
that command in the project root and toasts the first line of its output, `Memo` (when the context is within 50K of
its next mark, or past the last one) puts `/abofles:memo` in the prompt box, `Copy` puts the Use text on the clipboard,
`Hide` takes the band down; a hidden band comes back only when the ladder's priorities change (a 🔴 appears, the 🟡 is
gone), not when the wording changes. When nothing is open (every item ✅) the band is hidden, except when the memo is
due: then it shows just the meter and `Memo`. A dim second line, the meter, shows
`ctx 412K / 500K · task 3 spawns · $0.41 · budget 2 left · suggest Opus 5.5 · Medium` (parts without data omitted).
A toast fires when the top priority turns 🔴. It needs `abofles` installed; without it the band stays empty.

Install: `/plugin install abofles-guide@sajadh92` (after `/plugin marketplace add <this repo>`), or
`claude --plugin-dir plugins/abofles-guide`. Validate: `claude plugin validate plugins/abofles-guide`.
Turn the line off everywhere with `- Guide = off` in the project's `## abofles overrides`.
