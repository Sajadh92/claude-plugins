---
description: "Add an Abo Fles override block to this project's CLAUDE.md, with tier suggestions based on what the code does"
argument-hint: "[--dry-run]"
allowed-tools: Read, Glob, Grep, Edit, Write
---

Set up Abo Fles for this project. Arguments: $ARGUMENTS

1. If `CLAUDE.md` in the project root already has a `## abofles overrides` block, show it and stop — say the user can edit it by hand. The hooks read overrides only from that block; a `- Key = value` line elsewhere in the file is ignored.

2. Scan the project quickly (Glob/Grep, or read-only shell search such as `grep`, `find`, `ls` when those tools are not exposed; no subagents, no file writes). Project memory (auto-memory notes, `CLAUDE.md` history) may support a suggestion but never replace the scan: the topic must show up in the code, and a line that leans on memory says so — `(scan + project memory: ES silent-failure history)`. Look for money, payment, wallet, balance, invoice, commission, tax, auth, token, password, tenant, PII, migration. Also note the stack (languages, frameworks, test runner) from the manifest files you find.

3. Build an override block. Rules:
   - Start from an empty block; the matrix is the default and most projects need no overrides. Suggest at most 5 lines.
   - Suggest a tier shift only when the project makes a topic more costly than the matrix assumes (for example `Topic: Notifications & Messaging = T3` when notifications carry payment confirmations).
   - Suggest a cap raise only for a topic the project will hit often with large output (for example a monorepo: `Codebase Exploration & Onboarding / Read cap = 200`).
   - Never lower a T4 topic.
   - Add `Main session = ...` only if the project is clearly small and low-risk (then `sonnet·medium`).

4. Show the proposed block and one line per entry explaining why. If `--dry-run` was passed, stop here.

5. Otherwise append the block to the project's `CLAUDE.md` (create the file if missing) in this exact form:

```
## abofles overrides
- <Topic> / <Side> = <model>·<effort>   (Side = Read | Analyse | Plan | Work | Verify)
- Topic: <Name> = T<#>
- <Topic> / <Side> cap = <N>
- Main session = <model>·<effort>
- Session cap = <N>
- Context marks = <N>, <N>, …
- Receipt = full | short | savings <N> | off
- Break = <minutes> | off
- Agents = ask | auto | <N> | off
- Parallel = <M>
- Agent budgets = <T1>, <T2>, <T3>, <T4>
- Questions = judge | off
- Pace = normal | fast
- Language = <language of owner questions>
- Guide = on | off
```

Suggest only the lines the scan justifies; the lines from `Receipt` on are listed so the user knows they exist.

Suggest `Context marks` only when the user said the project runs on a model with a small window (then `100, 150, 180`); never suggest `Session cap` unasked. Keep only the lines you suggested; an empty block with just the heading is valid and means "matrix as is". Tell the user the file path and that abofles reads this block before every route.
