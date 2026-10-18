---
description: "Session summary from the ledger: spawns per model as bars, confidence, and the open follow-ups (partial, blocked, low, ATTENTION, FAIL); --resolve <id> closes one"
argument-hint: "[--all] [--resolve <agent id>] [--unresolve <agent id>] [--session <sid>] [--trace <text>]"
allowed-tools: Bash(python3 *)
---

Run the status script and show its output to the user unchanged, inside a code block:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" $ARGUMENTS --baseline <your current main-session model> --session "${CLAUDE_SESSION_ID}"
```

Use the alias of the model you are running on (`haiku`, `sonnet`, `opus`, `fable`). The script reads the session's effort from the state the hooks keep; add `·<effort>` only when the user stated a different one.

After the output: if there are open follow-ups, add one line per follow-up saying what you will do about it (handle it now, ask the user, or why it can stay open). When you have handled one, run `/abofles:status --resolve <id> --trace "re-checked: <evidence>"` so it leaves the list (the memo Journal keeps a "resolved by hand" line); `--unresolve <id>` reopens one. If there are none, add nothing.

Exit codes: 0 changed · 1 no match or no ledger · 2 usage (missing or empty value) · 3 already resolved / not resolved (no trace line is written). `--session <sid>` picks a session other than this one (an empty trailing `--session ""` is ignored); the display and `--resolve` use the same ledger, only this project's; `--trace [text]` works with `--resolve` and `--unresolve`.
