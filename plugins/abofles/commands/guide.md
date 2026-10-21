---
description: "What to do next — one prioritised line from the ledger, the memo and the context size (open FAIL, unasked question, owner decisions, escalation, background agents, memo/compact, budget)"
argument-hint: "[--all] [--scope session|project|all]"
allowed-tools: Bash(bash *)
---

Arguments: $ARGUMENTS

Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py" "${CLAUDE_PLUGIN_ROOT}/scripts/guide.py" $ARGUMENTS --session "${CLAUDE_SESSION_ID}"` and print its output verbatim (one line, or one item per line with `--all` or `--scope`). `--scope session` counts only this session's owner decisions, `project` (default) every session of this project, `all` adds one item for the owner decisions open in other projects; without `--scope` the guide follows the resume scope (`- Resume = …` in the override block, else the saved default of `/abofles:resume --default`, else `project`). Nothing else: the guide advises, you and the user decide. The same line is handed to you by the hooks at every receipt (`- `next` → 🧭 …`) and in every resume block (`- `guide` → 🧭 …`).
