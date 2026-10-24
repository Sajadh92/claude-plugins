---
description: "Where was I? Print the resume block from the work memo (now · next · needs you · last receipts) without re-reading anything; --resolve <n> <note> ticks an item (the note is required: the evidence), --note <text> records something settled in chat"
argument-hint: "[--scope session|project|all] [--default <scope>] [--move <folder>] [--all | --main] [--resolve <n> <note>] [--reopen <n>] [--note <text>]"
allowed-tools: Bash(bash *)
---

Arguments: $ARGUMENTS

Append `--session "${CLAUDE_SESSION_ID}"` to every `memo.py` call below (it picks this session's state when several are open; a `--session` the user typed comes first and wins; the script ignores a trailing `--session ""`).

- No arguments: run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py" "${CLAUDE_PLUGIN_ROOT}/scripts/memo.py" show --session "${CLAUDE_SESSION_ID}"` and print its output **verbatim** as the whole reply. Do not re-read the transcript, the ledger or any file to "improve" it — the point of the memo is that this costs nothing.
- `--scope session|project|all`: run `… memo.py show --scope <value> --session "${CLAUDE_SESSION_ID}"` and print it verbatim. `session` = this session's file and its own Needs-you items only; `project` (the default) = every session of this project; `all` = this project, then one `elsewhere` line per other project that has a memo. A session with nothing of its own yet sees the other sessions as one hint line by default; `--scope project` shows them in full.
- `--default <scope>`: run `… memo.py scope <value>` and print its one line — the value becomes the user default for every project (`~/.abofles/config.json`); a project overrides it with `- Resume = session | project | all | off` in its `## abofles overrides` block (`off` (also `none`, `0`) = no automatic resume block at session start, after /compact or after a break; `/abofles:resume` still works and the guide is unaffected; it is an override value only, not a `--default` value), and `--scope` wins over both for one call. `--default` alone (no value): run `… memo.py scope` and print which scope is in force and where it comes from.
- `--move <folder>`: run `… memo.py move "<folder>" --session "${CLAUDE_SESSION_ID}"` and print its one line — moves this session's memo (its file, its Needs-you items, its index line) to that project and makes it the session's project, for a session that was started in the wrong folder (the hooks do this by themselves once most of the session's edits land in another repository).
- `--all`: run `… memo.py show --all --session "${CLAUDE_SESSION_ID}"` and print its output verbatim (the main memo, then this session's file). `--main`: `… show --main …` prints the main memo only (Needs you, Decisions, the Sessions index with a link per session file).
- `--resolve <n> <note>`: run `… memo.py resolve <n> "<note>"`, then print the one-line result. The note is required (what you re-checked, or what the user answered: `"re-checked: <evidence>"` / `"user answered: <answer>"`); without it the script refuses with exit 2 and resolves nothing.
- `--reopen <n>`: run `… memo.py reopen <n>`, then print the one-line result. Add `--trace` to `--resolve` or `--reopen` to write a "resolved/reopened by hand" line into the memo Journal (shown under `last`).
- `--resolve` and `--reopen` also take `--session <sid>` (two sessions in one root). Exit codes: 0 changed · 1 no such item · 2 usage or `--resolve` without a note · 3 already resolved / already open (no trace line is written).
- `--note <text>`: run `… memo.py note "<text>"`, then print `noted`.

If the script says there is no memo yet, say so in one line and suggest `/abofles:memo`. The memo lives in the project this session's edits land in: the folder the session started in, until most edits go to another repository — the hooks move the session's memo there (its file, its Needs-you items, its index line) and say so in the Journal.
