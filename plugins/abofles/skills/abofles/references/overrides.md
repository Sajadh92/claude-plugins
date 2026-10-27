# Project override block and its forms

Read when a project `CLAUDE.md` has a `## abofles overrides` block, or the user asks to change a cell, cap, tier or setting.

The matrix is the same for every project. A project changes cells in its own `CLAUDE.md` (or project memory):

```
## abofles overrides
- Unit Test / Work = haiku·medium
- Financial & Amount Calculations / Verify = opus·xhigh
- Topic: Notifications & Messaging = T3
- Codebase Exploration & Onboarding / Read cap = 200
- Main session = sonnet·medium
- Session cap = 600
- Context marks = 500, 600, 700, 750, 800, 850, 900
- Receipt = savings 30
- Break = 10
- Agents = auto
- Parallel = 3
- Agent budgets = 2, 3, 7, 12
- Questions = judge
- Pace = normal
- Language = Arabic
- Guide = on
- Resume = project
- Review gate = auto
- Reviewers: FIN = finance, security, tester
- Workflow: Code Health = Read, Work, Verify
- Review: Security / T4 = opus·xhigh
- Guide place = pane
- Resume place = pane
- Spawns place = pane
- Receipt place = pane
```

Twenty-four forms: `Topic / Side = model·effort` (one cell), `Topic: Name = T#` (move a topic to another tier), `Topic / Side cap = N` (reply cap), `Main session = model·effort` (read by you for Step 0, not enforced by the hook), `Session cap = N` (units per session before the hook tells you to stop and ask), `Context marks = N, N, …` (thousands of tokens at which the context watch warns — the line shown is the default; a 200K-window model wants `100, 150, 180`), `Receipt = full | short | savings N | off` (receipt form, see Step 6), `Break = N | off` (minutes away before the resume block is shown again; default 10), `Agents = ask | auto | N | off` (the agent gate: ask once per session — default —, size every task by tier, a fixed budget per task, or no budget), `Parallel = M` (background agents running at once, default 3), `Agent budgets = a, b, c, d` (agents per tier T1..T4 under `auto`), `Questions = judge | off` (the question gate), `Language = Arabic` (the language owner questions are written in), `Guide = on | off` (the 🧭 next line), `Review gate = auto | on | warn | off` (the review gate at the receipt: auto = 🔴 refused once, 🟠 warned in the guide; on = 🟠 refused too; warn = never refused; off = silent), `Reviewers: <Domain code | Domain name | Topic> = security, tester | none` (replaces that domain's or topic's reviewers at T3 and T4; names as in workflow.md, lower case: security, finance, compliance, tester, qa, uiux, cleancoder, dba, ops, perf, data), `Workflow: <Domain | Topic> = Read, Work, Verify` (the steps of a `change` there — advice to the skill, not enforced), `Review: <Tag> / T<tier> = model·effort` (one reviewer's cell at one tier), `Resume = session | project | all | off` (what the resume block and the guide show: this session only, every session of this project — the default —, or other projects too; `off` (also `none`, `0`) = no automatic resume block at session start, after a compact or after a break — `/abofles:resume` still works and the guide is unaffected; override-only, not a `--default` value; a project `Resume = off` only stops the automatic block in the chat (start, compact, break); the pane's Resume card still shows. It also hides a user-level `Resume = <scope>` (first file wins), and the scope then falls back to the saved `--default` or project; `/abofles:resume --scope` wins for one call, `/abofles:resume --default` sets the user-wide default this line overrides), `Pace = normal | fast` (`fast` when the user says the plugin slows them: the direct-read guard speaks at 8/16/32/64 reads instead of 4/8/16/32, questions go to the user without a Judge only when the open task's tier (the highest of its spawns and the task tier on the `main:` line) is 🟢/🟡 — 🟠/🔴 or an unknown tier are still judged —, and the receipt is the one-line form unless `Receipt` is set; the hooks themselves cost ~20–30 ms per tool call in either pace — the time goes to spawns, so under `fast` also prefer the 1–3-call exception of rule 7 and background spawns). `Guide place = pane | band`, `Resume place = pane | output` and `Spawns place = pane | output` (where each thing shows; all three default to `pane`, the Abo Fles pane of the `abofles-guide` mod: the guide there instead of in the band above the prompt box, the resume block and the spawn history there instead of printed in the chat — `output` / `band` keep today's view; a value that is none of the two is `pane`; without the mod there is no pane, so the guide stays in the band and the resume block and spawn history are printed whatever the line says; `/abofles:resume` and `/abofles:spawns` print their text on demand either way, `/abofles:pane` opens or closes the pane). `Receipt place = pane | output` (default `pane` with the mod, `output` without it): with `pane` the Stop hook asks for the same receipt recorded by one command — `memo.py receipt` with the receipt lines on stdin — instead of printed; end the turn with one short sentence. The hook reads the recorded receipt as if it were printed (it closes the task, the review gate applies, the memo Journal and the pane's Resume › Last receipts get it), and the chat keeps one collapsed command row. The pane's overrides editor (the Overrides card's `Edit overrides`) edits the simple keys (`Key = value`) in the project's or the user's file; the forms with a name in them (cells, caps, tiers, `Reviewers`, `Workflow`, `Review`) are listed there as lines. The hooks read the project's `CLAUDE.md` first, then the user's `~/.claude/CLAUDE.md` — a line there applies to every project (`- Receipt = off` turns receipts off everywhere). Overrides are read **only** from the `## abofles overrides` block; a `- Key = value` line elsewhere in `CLAUDE.md` is prose and is ignored. Check for this block before routing. Mark its use in the route line: ` · Project Override` (the topic lookup `scripts/topic.py` applies the cell, cap and tier forms itself and marks them).
