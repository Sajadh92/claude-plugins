---
description: "One line per spawn of this session — time, side, status, confidence, model·effort, tokens, $ and saved — plus the totals line (the pane's Spawns card as text)"
argument-hint: "[--all]"
allowed-tools: Bash(bash *)
---

Run the bill script in history mode and show its output to the user unchanged, inside a code block:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/py" "${CLAUDE_PLUGIN_ROOT}/scripts/bill.py" --history $ARGUMENTS --baseline <your current main-session model> --session "${CLAUDE_SESSION_ID}"
```

Replace `<your current main-session model>` with the alias of the model you are running on (`haiku`, `sonnet`, `opus` or `fable`). `/abofles:bill` is the summary of the same ledger (per model, per side, verdicts, the unit cost index); this command is the row list. Say nothing else.
