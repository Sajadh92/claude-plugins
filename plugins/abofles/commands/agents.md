---
description: "Agent gate — show or set how many agents a task may spawn: auto (sized by tier), N (this task), off, or ask again"
argument-hint: "[auto | N | off | ask]"
allowed-tools: Bash(python3 *)
---

Arguments: $ARGUMENTS

- No argument: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agents.py"` and print its three lines verbatim.
- `auto`, a number, `off` or `ask`: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agents.py" set <value>` and print the one-line result. Nothing else.

The hook enforces the budget on every Agent call: the spawn after the budget is denied until the user raises it. `auto` sizes each task from its tier (Orchestrator mode: Minor 2 · Normal 3 · Sensitive 5 · Critical 8; Worker mode: 1 · 2 · 4 · 6; `- Agent budgets = a, b, c, d` in the override block changes the table). Judge and Explainer spawns (question gate) are never counted; answering the gate again restarts the count. The gate question is asked once per session when `Agents = ask` (the default), unless the answer was per task (`This task: N` / `Main session only`) — then it is asked again at the next task; `Agents = auto | N | off` in the override block skips it.
