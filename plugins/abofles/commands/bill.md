---
description: "Show what this session's subagents cost — the unit index per model and side, and the real tokens and dollars — and what Abo Fles saved versus running them all on one model"
argument-hint: "[--all]"
allowed-tools: Bash(python3 *)
---

Run the bill script and show its output to the user unchanged, inside a code block:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bill.py" $ARGUMENTS --baseline <your current main-session model> --session "${CLAUDE_SESSION_ID}"
```

Replace `<your current main-session model>` with the alias of the model you are running on (`haiku`, `sonnet`, `opus` or `fable`). The script reads the session's effort from the state the hooks keep; add `·<effort>` only when the user stated a different one in this conversation. If the script cannot find the effort it uses `high` and says it is assumed.

After the output, add at most two lines: the one route change that would save the most next time (for example, a Read agent that ran on opus), or "routing looks right" if nothing stands out. Say nothing else.
