---
description: "Session summary from the ledger: spawns per model as bars, confidence, and the open follow-ups (partial, blocked, low, ATTENTION, FAIL); --resolve <id> closes one"
argument-hint: "[--all] [--resolve <agent id>]"
allowed-tools: Bash(python3 *)
---

Run the status script and show its output to the user unchanged, inside a code block:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" $ARGUMENTS --baseline <your current main-session model>
```

Use the alias of the model you are running on (`haiku`, `sonnet`, `opus`, `fable`). The script reads the session's effort from the state the hooks keep; add `·<effort>` only when the user stated a different one.

After the output: if there are open follow-ups, add one line per follow-up saying what you will do about it (handle it now, ask the user, or why it can stay open). When you have handled one, run `/abofles:status --resolve <id>` so it leaves the list. If there are none, add nothing.
