---
description: "Dry run — print the Abo Fles route lines (model, effort, reply cap) for a task without spawning anything"
argument-hint: "<task description>"
---

Load the abofles skill if it is not already loaded. Then route this task, following the skill exactly, but **do not spawn any agent and do not change any file**:

$ARGUMENTS

Print only:

1. The `main:` line (Step 0): `main: <model>·<effort> fits` when your model **and** effort both match the suggestion (effort unknown → the model alone decides and the line reads `main: <model> fits (suggested effort <effort>, yours unknown)`), else `main: suggest <model>·<effort> for this task (now <your model>·<your effort or 'effort unknown'>)`. The session's effort is the one the abofles hook told you (`abofles: this session runs at effort …`, sent at the first hook of the session); else what the user told you; else write `effort unknown`.
2. One `route:` line per subagent you would spawn, in execution order, in the skill's format: `route: <Topic> / <Side> → <model>·<effort> · cap <N> (T<tier>[, modifier])` with the side as a full word (Read, Analyse, Plan, Work, Verify). Mark parallel groups with `(parallel)`.
3. One line: the total number of spawns, how many run on each model, and the estimated cost: `Σ <n> spawns · ~<units> u` where a spawn's units = model price × effort factor (haiku 1, sonnet 20, opus 40, fable 100 × low 0.5, medium 1, high 1.5, xhigh 2.5, max 4). Add `· vs ~<units> u all-<your model>·<your effort, or high when unknown>` for the same spawns at your own model.

If the task is too small for subagents (1–3 tool calls), print `route: none — main session handles it` and say why in one line. If a project override block changed a cell, mark it `(project override)`. No other text.
