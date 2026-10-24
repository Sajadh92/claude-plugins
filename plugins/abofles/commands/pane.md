---
description: "The Abo Fles pane (resume, spawns, overrides) — toggled by /abofles-pane (abofles-guide mod); without the mod, prints the resume block and the spawn history as text"
allowed-tools: Bash(bash *)
---

The Abo Fles pane is toggled by the `abofles-guide` mod's own command, `/abofles-pane`: it shows the resume block, the session's spawns and the override table on the right side of the window, and opens by itself when there is something to show. The hooks keep its data fresh.

If you got this command as text (the mod did not answer it), tell the user in one line: `Type /abofles-pane to open or close the Abo Fles pane.` Then, only when the `abofles-guide` mod is not enabled (no pane to open), also print the resume block and the spawn history as text. Run both and show each output unchanged, inside a code block:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/py" "${CLAUDE_PLUGIN_ROOT}/scripts/memo.py" show --session "${CLAUDE_SESSION_ID}"
bash "${CLAUDE_PLUGIN_ROOT}/scripts/py" "${CLAUDE_PLUGIN_ROOT}/scripts/bill.py" --history --baseline <your current main-session model> --session "${CLAUDE_SESSION_ID}"
```

Replace `<your current main-session model>` with the alias of the model you are running on (`haiku`, `sonnet`, `opus` or `fable`). Say nothing else.
