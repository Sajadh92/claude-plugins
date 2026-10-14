---
description: "Dry run — print the Abo Fles route lines (model, effort, reply cap) for a task without spawning anything"
argument-hint: "<task description>"
---

Load the abofles skill if it is not already loaded. Then route this task, following the skill exactly, but **do not spawn any agent and do not change any file**:

$ARGUMENTS

Print only:

1. The `main:` line (Step 0): `main: <Model> · <Effort> fits` when your model **and** effort both match the suggestion (effort unknown → the model alone decides and the line reads `main: <Model> fits (suggested effort <Effort>, yours unknown)`), else `main: suggest <Model> · <Effort> for this task (now <your Model> · <your Effort or 'effort unknown'>)`. The session's effort is the one the abofles hook told you (`abofles: session effort is …`, sent at the first hook of the session); else what the user told you; else write `effort unknown`.
2. One route line per subagent you would spawn, in execution order, one bullet each, in the skill's format: `- <Side emoji> `<Side>` → **<Topic>** · <Model> · <Effort> · Cap <N> · <Tier>[ · <Modifier>]` — side tag a full word, topic in Title Case, tier as dot + word (🟢 Minor, 🟡 Normal, 🟠 Sensitive, 🔴 Critical). Mark parallel groups with ` · Parallel`.
3. One line: the total number of spawns, how many run on each model, and the estimated cost: `Σ <n> spawns · ~<units> u` where a spawn's units = model price × effort factor (haiku 1, sonnet 20, opus 40, fable 100 × low 0.5, medium 1, high 1.5, xhigh 2.5, max 4). Add `· vs ~<units> u all <your Model> · <your Effort, or High when unknown>` for the same spawns at your own model.

If the task is too small for subagents (1–3 tool calls), print `none — main session handles it` and say why in one line. If a project override block changed a cell, mark it ` · Project Override`. No other text.
