---
description: "Where was I? Print the resume block from the work memo (now · next · needs you · last receipts) without re-reading anything; --resolve <n> [note] ticks an item, --note <text> records something settled in chat"
argument-hint: "[--all] [--resolve <n> [note]] [--reopen <n>] [--note <text>]"
allowed-tools: Bash(python3 *)
---

Arguments: $ARGUMENTS

- No arguments: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/memo.py" show` and print its output **verbatim** as the whole reply. Do not re-read the transcript, the ledger or any file to "improve" it — the point of the memo is that this costs nothing.
- `--all`: run `… memo.py show --all` and print the file verbatim.
- `--resolve <n> [note]`: run `… memo.py resolve <n> "<note>"`, then print the one-line result.
- `--reopen <n>`: run `… memo.py reopen <n>`, then print the one-line result. Add `--trace` to `--resolve` or `--reopen` to write a "resolved/reopened by hand" line into the memo Journal (shown under `last`).
- `--resolve` and `--reopen` also take `--session <sid>` (two sessions in one root). Exit codes: 0 changed · 1 no such item · 2 usage · 3 already resolved / already open (no trace line is written).
- `--note <text>`: run `… memo.py note "<text>"`, then print `noted`.

If the script says there is no memo yet, say so in one line and suggest `/abofles:memo`.
