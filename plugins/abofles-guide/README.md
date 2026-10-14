# abofles-guide

A band above the prompt box with the Abo Fles **🧭 next** line: what to do now, by priority, computed by the
`abofles` plugin's hooks after every spawn, receipt and prompt (open FAIL / ATTENTION · judged question unasked ·
owner decisions open · partial/low reply not escalated · background agents running · context or memo hygiene ·
agent budget nearly out · the memo's Next). The same line is in every receipt (`- \`next\` → 🧭 …`) and resume block.

It only draws: a band with three buttons — `Use` puts the line in the prompt box as the next prompt (appended after a
draft you already typed) and takes the band down, `Copy` puts it on the clipboard, `Hide` takes the band down; a hidden
band comes back only when the ladder's priorities change (a 🔴 appears, the 🟡 is gone), not when the wording of
the same items changes — and a toast when the top priority turns 🔴. It needs `abofles` installed; without it the band stays empty.

Install: `/plugin install abofles-guide@sajadh92` (after `/plugin marketplace add <this repo>`), or
`claude --plugin-dir plugins/abofles-guide`. Validate: `claude plugin validate plugins/abofles-guide`.
Turn the line off everywhere with `- Guide = off` in the project's `## abofles overrides`.
