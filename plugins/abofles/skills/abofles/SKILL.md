---
name: abofles
description: "Abo Fles (ابو فليس) — picks the model (haiku / sonnet / opus / fable) and effort (low..max) for every subagent in coding work from a topic × side matrix, and suggests the main-session model. TRIGGER at the start of each coding task, before every Agent tool call, before planning a multi-agent fan-out, and when the user asks which model or effort to use. Never spawn a subagent in coding work without routing here first. SKIP for non-coding tasks."
---

# Abo Fles (ابو فليس) — Agent Router

Goal: correct work, fast, with the fewest tokens. The usual waste is a subagent that inherits the main session's model and effort — Opus·xhigh doing a file search. This skill stops that.

- Models (always the latest version): `haiku` = Haiku 5.5 · `sonnet` = Sonnet 5.5 · `opus` = Opus 5.5 · `fable` = Fable 5.1.
- **Shown to the user, write names the way the Claude app does**: `Haiku 5.5 · Low`, `Sonnet 5.5 · Medium`, `Opus 5.5 · High`, `Opus 5.5 · Extra` (= xhigh), `Fable 5.1 · Max` — in route lines, `main:`, progress and receipt lines and in prose. The Agent call's `model` and `effort` params and the matrix cells below stay lowercase (`opus`, `xhigh`).
- Routing estimate — cost units (`u`) = model price × effort factor: haiku 1 · sonnet 20 · opus 40 · fable 100, times low 0.5 · medium 1 · high 1.5 · xhigh 2.5 · max 4. So haiku·low = 0.5 u, sonnet·medium = 20 u, opus·high = 60 u, opus·xhigh = 100 u. Every step down pays.
- Effort ladder: `low < medium < high < xhigh < max`.

## Hard rules

1. Every Agent call passes **both** `model` and `effort`. Never inherit. This skill is the explicit instruction that permits setting `effort`.
2. Print one route line before each spawn, plain markdown: <Side emoji> `<Side>` → **<Topic>** · <Model> · <Effort> · Cap <N> · <Tier>[ · <Modifier>]. The side emoji marks the side: 🔍 Read · 🧠 Analyse · 📐 Plan · 🛠️ Work · ✅ Verify · ⚖️ Judge · 💬 Explain. `<Tier>` is the tier's word, never its code: T1 = 🟢 Minor, T2 = 🟡 Normal, T3 = 🟠 Sensitive, T4 = 🔴 Critical, dot included (the `T#` code stays in prompt headers and override lines). The side tag is the full word (`Read`, `Analyse`, `Plan`, `Work`, `Verify`); the topic is the matrix name exactly, in Title Case (a topic not in the index: Title Case too). Modifiers, each after its own ` · `, in Title Case: `Scope −1`, `User: <what>`, `User Cap`, `Project Override`, `Merged: N Questions`, `Parallel`, `Fallback: <Model> Unavailable`. Several route lines in one message: one bullet each (`- <Side emoji> …`), so they never run together. Example: 🔍 `Read` → **Pricing, Fees, Commission & Tax** · Sonnet 5.5 · Low · Cap 100 · 🔴 Critical · Parallel
3. One subagent = one side. Read → Analyse → Plan → Work → Verify run as separate small agents; Judge and Explain are the two sides of the question gate. Results flow forward as short summaries, never raw output.
4. `fable` only on the Analyse and Plan sides. Never for Read, Work or Verify.
5. `max` effort only through escalation (Step 4), never as a start value.
6. **Ultracode / Workflow tool: never without a clear yes from the user.** For huge jobs (full-repo audit, 30+ files, many independent topics) suggest it in one line with a rough agent count, then wait.
7. No subagent when the main session can finish in 1–3 tool calls. A spawn has a fixed context cost. Exception: the user explicitly asks for a subagent or says "use abofles" — then spawn, routed as usual.
8. **Merge parallel reads.** Two or more Read agents on the same topic and tier become one agent with a numbered question list. One fixed cost instead of three. Split only when the folders are unrelated or the combined cap would pass 150 lines.
9. **Model not available** (the spawn fails with a model-access or permission error): re-spawn one step down at the next effort up — `fable` → `opus·xhigh`, `opus` → `sonnet·xhigh`, `sonnet` → `haiku·high`. Say so in the route line with the modifier ` · Fallback: Fable 5.1 Unavailable`. Never retry the same model.

10. **Background spawns.** Pass `run_in_background: false` on abofles spawns unless they are a parallel group. A background reply reaches the hooks only through `SubagentStop`, which fills the ledger silently (any hook output there would be fed back to the subagent and replace its reply); for a background spawn **you** check the `STATUS`/`CONFIDENCE` header when the result arrives and apply Step 4 yourself. `/abofles:bill` lists the warnings the hook recorded for background spawns.

A `PreToolUse` hook enforces rules 1 and 4: an Agent call without `model` and `effort`, or `fable` on a Read/Work/Verify agent, is blocked with the reason. `abofles:skip` as the first word of the prompt bypasses it once — use it only for non-coding spawns.

## Routing in four steps

1. **Side** — what the agent does (Step 1).
2. **Topic → tier** — find the topic in the index; the tier gives the base cell (Step 2).
3. **Modifiers** — precedence: user in chat > project override block > scope > matrix (Step 3).
4. **Spawn** — compact prompt, compact return (Step 5).

## Step 0 — Main session check (once per session, then once per task)

You know your own model (the system prompt names it). Your effort level comes from the abofles hook: at the session's first hook (SessionStart, a user prompt, a read, or an Agent call) it sends one line, `abofles: this session runs at effort <level>`, and sends it again if the level changes. Use that. If no such line has arrived yet, the user's statement in this conversation or a `Main session = …` override line counts; the desktop `mcp__ccd_session_mgmt__get_session` tool (`"self"`, loaded with ToolSearch) is the last resort. Otherwise it is unknown: never infer it from memory, past sessions or project notes.

**Two modes, decided by the main model:**

| Main model | Mode | What it means |
|---|---|---|
| opus, fable | **Orchestrator** | The main session routes, spawns, reads replies and decides. It does **not** read code, grep, write code or run tests itself — every side goes through the matrix. Only the 1–3-call exception of rule 7 stays. A `PreToolUse` guard warns after 4, 8, 16 and 32 direct reads in a row (Read/Grep/Glob, Bash `grep`/`find`/`cat`/`sed -n` — the desktop Code tab has no Grep tool — and connector lookups such as a Jira `getJiraIssue`, which are the expensive ones; a shell append or `wc` is not a read); a `Stop` hook refuses to end a turn that spawned agents without printing the receipt. |
| haiku, sonnet | **Worker** | Fine for a T1–T2 task or pure coordination. For a T3+ task the agent gate (below) offers `Switch main to Opus 5.5 and orchestrate`. |

**Agent gate — once per session, before the first spawn.** The `PreToolUse` hook denies the first Agent call of a session until you have asked it (unless the override says `Agents = auto | N | off`). Size the task first (Step 2: tier, topics, files; Small = T1–T2 one topic → 1–2 agents; Medium = T3 or two topics → 3–4; Large = T4, 3+ topics or 20+ files → 5–8 with parallel reads). Then ask **one** `AskUserQuestion` whose question text contains `Abo Fles agent gate`, options in this order, labels starting exactly like this:
1. `Auto (recommended)` — description: *abofles sizes every task by topic, side and tier (Orchestrator: Minor 2 · Normal 3 · Sensitive 5 · Critical 8 agents; Worker: 1 · 2 · 4 · 6); no more questions this session; the hook denies a spawn over the budget.*
2. `This task: N agents` — N and the plan from your route lines, with `≈ <units> u · ≈ $<est>` (estimate $ from the session's average tokens per spawn in the ledger, else 300K tokens at list price); asked again next task.
3. `Main session only` — 0 agents this task. In Orchestrator mode add *(costly: <Model> does every read itself)*.
4. Orchestrator mode, Large task only: `Max: N agents · M parallel`. Worker mode (any tier): `Switch main to Opus 5.5 and orchestrate` — if chosen, reply with one line, `Pick Opus 5.5 in the model picker (bottom right), then send "go".`, and **end the turn** (the plugin cannot switch the model).
The user may type a number or `off` in Other. The hook records the answer (budget, `auto`, or `off`) and tells you `agents: …` — continue the task; never re-ask. A per-task answer expires at the receipt and the gate asks again at the next task's first spawn; `Auto` and `off` hold for the session. `/abofles:agents <auto | N | off | ask>` changes it; when the user says "agents N" in chat, run `python3 "<plugin root>/scripts/agents.py" set N`. Over budget, the hook denies the spawn: finish in the main session or ask the user to raise it (answering the gate again — `Auto`, a number — restarts the count from that moment). Judge and Explainer spawns never count. A prompt without the `abofles: <Topic> / <Side> · T<n>` first line has no tier: the budget is sized as 🟡 Normal and the hook says so. Background spawns are capped at `Parallel` running at once (default 3).

**Per task** (after the mode is set), tier the whole task (Step 2) and compare with this table. The `PreToolUse` hook computes the line at the task's first work spawn from the session's real model and effort and hands it to you (`abofles: print this line once … \`main: …\``): print it **as given, right after the first route line**, every task — `main: <Model> · <Effort> fits this <Tier> task` when both match, else `main: suggest <Model> · <Effort> for this <Tier> task (now <current Model> · <Effort or 'effort unknown'>). Switch in the model picker, or say "keep".` Then continue on the current setting. A resume block printed first never replaces it. `/abofles:route` always prints `main: <Model> · <Effort> fits` when both match, else the suggestion line.

| Task shape | Suggested main session |
|---|---|
| Quick question, rename, or tiny edit | haiku·low |
| T1–T2 task, or the main session only coordinates subagents | sonnet·medium |
| T3 task, or the main session writes code itself | opus·medium |
| T4 task, or design across many modules | opus·high |
| Hard T4 architecture, security, or incident work with unclear cause | fable·medium |

## Step 1 — Find the side

| Side | The subagent... | `subagent_type` | Reply |
|---|---|---|---|
| **Read** (Read & Collect) | finds files, maps code, collects facts, lists usages. No opinions. | `abofles:abofles-reader` | FACTS as `path:line — fact`, GAPS |
| **Analyse** (Analyse & Find Gaps) | judges, finds bugs/gaps/risks, compares options, suggests a better approach | `abofles:abofles-analyst` | ranked FINDINGS `[severity] path:line — issue — fix`, RECOMMENDATION |
| **Plan** (Plan & Design) | writes an implementation plan, design, or migration strategy before code changes | `abofles:abofles-planner` | numbered PLAN with files, RISKS, VERIFY, OPEN |
| **Work** (Act & Work) | writes or edits code, tests, docs, configs | `abofles:abofles-worker` | CHANGED one line per file, RAN, LEFT |
| **Verify** (Verify & Review) | checks finished work: runs tests, reviews the diff, confirms docs match code | `abofles:abofles-verifier` | VERDICT PASS/FAIL, EVIDENCE per criterion, ISSUES |

Every abofles agent starts its reply with `STATUS: done|partial|blocked` and `CONFIDENCE: high|medium|low`. `partial`, `blocked`, or `low` feeds escalation (Step 4). The agent files carry the format; the spawn prompt only passes the line cap.

**The cell picks the model, not the agent type.** `abofles-reader` has read-only Bash (`git show`, `gh pr view`, grep), so most reads fit it. A read it cannot do — a connector such as Jira, a project agent — still takes the Read cell: `general-purpose` at `haiku·low`, never sonnet because the agent type changed.

If the abofles agents are not available (skill copied without the plugin), fall back to `Explore` for Read, `Plan` for Plan, `general-purpose` for Analyse/Work/Verify, and paste the reply format from `references/matrix.md` into the prompt. Always pass `model` and `effort`.

## Step 2 — Find the topic and its tier

Tier = how much a mistake costs.

| Tier | A mistake means... | Read | Analyse | Plan | Work | Verify |
|---|---|---|---|---|---|---|
| T1 Minor | cosmetic, easy to undo | haiku·low | sonnet·low | sonnet·low | haiku·medium | haiku·low |
| T2 Normal | a bug a test will catch | haiku·low | sonnet·medium | sonnet·medium | sonnet·medium | sonnet·low |
| T3 Sensitive | wrong production behavior or business rule | haiku·medium | opus·medium | opus·medium | sonnet·high | sonnet·high |
| T4 Critical | money, auth, data loss, security breach | sonnet·low | opus·high | opus·xhigh | opus·high | opus·high |

**Reply cap** — max lines of content the agent returns (status header excluded). Grows with the tier: a cut-off finding on a critical topic costs more than the lines it saves.

| Tier | Read | Analyse | Plan | Work | Verify |
|---|---|---|---|---|---|
| T1 | 20 | 10 | 25 | 10 | 10 |
| T2 | 40 | 20 | 50 | 20 | 20 |
| T3 | 60 | 35 | 90 | 30 | 35 |
| T4 | 100 | 50 | 150 | 40 | 60 |

Cap rules: never cut a finding to fit — the agent ranks, keeps the top ones in full, ends with `+N more: <one line each>`; the main session asks for the rest only when needed. The cap limits lines, not information: `path:line — issue — fix`, one fact per line, a line is at most 200 characters (the hook warns past that), no prose, no code dumps, no code fence around the reply. Work replies stay short on every tier — the code is in the files.

**Fast tier test** when the topic is unclear: touches money, auth, secrets, personal data, data loss, or concurrency → T4. Changes production behavior or a business rule → T3. Ordinary code or tests → T2. Text, formatting, or exploration only → T1.

**Reading is not the task.** A caller list, a usage map, "where is X", "what calls Y" is **Codebase Exploration & Onboarding (T1, haiku·low)** whatever code it touches, even money or auth. The T4 Read cell (`sonnet·low`) is for reads whose misreading breaks the plan: collecting the exact rounding rules, the token lifetime, the state transitions before a change to them.

**Topic index** — `N. Topic · Tier — cell overrides, cap overrides` (sides named in full: Read, Analyse, Plan, Work, Verify). Only the overrides differ from the tier base. Full table with every cell and keyword signals: [references/matrix.md](references/matrix.md).

<!-- topics:start -->
**A. Security & Trust**
- 1. Security & Risk Review · T4 — Analyse=fable·medium, cap Analyse=80
- 2. Authentication (login, sessions, tokens, MFA) · T4
- 3. Authorization, Roles & Permissions · T4
- 4. Secrets, Keys & Config Security · T4 — Work=sonnet·high
- 5. Data Privacy, PII & Compliance · T4
- 6. Input Validation & Injection · T3
- 7. Cryptography, Hashing & Signing · T4
- 8. Rate Limiting, Abuse & Fraud Prevention · T3
- 9. Audit Logging & Traceability · T3 — Work=sonnet·medium
- 10. Dependency Vulnerabilities (CVE scan) · T3 — Read=haiku·low, cap Read=60

**B. Money & Finance**
- 11. Financial & Amount Calculations · T4 — Analyse=fable·medium
- 12. Revenue Flow & Profit · T4
- 13. Payments & Gateway Integration · T4
- 14. Pricing, Fees, Commission & Tax · T4
- 15. Wallets, Balances & Ledger · T4
- 16. Refunds, Chargebacks & Reversals · T4
- 17. Reconciliation & Financial Reports · T3
- 18. Invoicing & Billing Cycles · T3
- 19. Multi-currency & Exchange Rates · T4

**C. Business Logic & Workflows**
- 20. Business Logic (domain rules) · T3
- 21. Status & Workflows (state machines) · T3 — Analyse=opus·high
- 22. Validation Rules & Constraints · T3
- 23. Notifications & Messaging · T2
- 24. Scheduling, Time Zones & Calendars · T3
- 25. Multi-tenancy & Account Isolation · T4
- 26. Reporting & Dashboards (business) · T2
- 27. Import, Export & Data Migration (business data) · T3

**D. Quality & Testing**
- 28. Quality Assurance (strategy & coverage) · T2
- 29. Unit Test · T2
- 30. Integration & API Test · T2
- 31. End to End Test · T2 — Work=sonnet·high
- 32. Test Data, Fixtures & Mocks · T1
- 33. Regression & Smoke Check · T1
- 34. Flaky Test Hunting · T2
- 35. Performance & Load Testing · T3
- 36. Contract & Snapshot Tests · T2

**E. Debugging & Incidents**
- 37. Bug Fix & Debugging · T3
- 38. Incident & Production Debug · T4 — Analyse=fable·medium, cap Analyse=80
- 39. Root Cause Analysis & Postmortem · T3 — Analyse=opus·high, cap Analyse=60
- 40. Log & Trace Investigation · T2
- 41. Memory Leaks & Resource Exhaustion · T3
- 42. Data Corruption & Recovery · T4

**F. Code Health**
- 43. Clean Code (naming, structure, readability) · T2
- 44. Refactoring (behavior-preserving) · T3
- 45. Lint, Format & Style · T1 — Work=haiku·low
- 46. Dead Code & Tech Debt · T2
- 47. Error Handling & Resilience · T3
- 48. Logging & Observability (instrumentation) · T2
- 49. Code Duplication & Reuse · T2
- 50. Type Safety & Static Analysis · T2
- 51. Code Comments & Inline Docs · T1

**G. Architecture & Design**
- 52. Architecture, Design Pattern & Stack Used · T4 — Plan=fable·medium, Work=sonnet·high, cap Plan=200
- 53. Module Boundaries & Dependency Graph · T3
- 54. API Design & Contracts · T3
- 55. Event-driven & Messaging Architecture · T3
- 56. Microservices vs Monolith Decisions · T4 — Plan=fable·medium, Work=sonnet·medium
- 57. Domain Modeling (DDD, entities, aggregates) · T3
- 58. Scalability & Capacity Planning · T3
- 59. Framework & Language Migration · T4 — Work=sonnet·high, cap Plan=200

**H. Data & Storage**
- 60. DB Schema & Migrations · T4
- 61. Query & DB Performance · T3
- 62. Data Integrity & Constraints · T4
- 63. Caching Strategy · T3
- 64. Concurrency, Locking & Race Conditions · T4
- 65. Backups, Retention & Archival · T3
- 66. Search & Indexing (full-text) · T2
- 67. File Storage & Media Handling · T2

**I. Integrations & Async**
- 68. 3rd-party Integrations & Webhooks · T3
- 69. Background Jobs & Queues · T3
- 70. Real-time (WebSockets, SSE, Push) · T3
- 71. External API Clients & SDK Usage · T2
- 72. Idempotency & Retry Logic · T4
- 73. AI / LLM Integration · T2 — Analyse=opus·medium

**J. Dependencies & DevOps**
- 74. Packages & Libs Updates · T2 — Analyse=sonnet·high
- 75. CI/CD & Build Pipelines · T2
- 76. Docker, Containers & Orchestration · T3
- 77. Infra as Code & Cloud Config · T3
- 78. Environment & Config Files · T2
- 79. Release, Versioning & Changelog · T1
- 80. Monitoring, Alerts & Health Checks · T2
- 81. Feature Flags & Rollouts · T2

**K. Frontend & UX**
- 82. UI Components & Styling · T2
- 83. UX Flows & Accessibility · T2
- 84. State Management (frontend) · T2
- 85. Forms & Client-side Validation · T2
- 86. Responsive, RTL & Theming · T2
- 87. Frontend Performance · T2
- 88. Mobile-specific (iOS, Android, cross-platform) · T2

**L. Docs & Content**
- 89. Work on Document (README, guides) · T1
- 90. Code Match Documents (docs vs code drift) · T2 — cap Analyse=40
- 91. API Docs (OpenAPI / Swagger) · T1
- 92. Legal & Marketing Content & Translation · T2 — Analyse=opus·medium
- 93. i18n & l10n (strings, locales) · T2
- 94. Codebase Exploration & Onboarding · T1 — cap Read=120
- 95. Architecture Decision Records (ADR) · T2

**M. Product & Scope**
- 96. Check MVP vs Advance · T3 — Work=sonnet·medium, Verify=sonnet·low
- 97. Feature Scoping & Requirements · T3 — Work=sonnet·medium
- 98. Analytics & Tracking Events · T2
- 99. User Feedback & Bug Triage · T1
- 100. Competitor & Feature Parity Check · T2 — Read=sonnet·low
<!-- topics:end -->

- Topic not listed: use the closest one, or the fast tier test. Tell the user the new topic so it can be added.
- Task spans several topics: use the highest tier, or better, split into one subagent per topic when the parts are independent.

## Step 3 — Apply modifiers (in precedence order)

1. **User in chat.** A model, effort or line cap the user names wins over everything. Say which cell it replaced with the modifier: `… · Cap 20 · 🟡 Normal · User: Sonnet 5.5 · High`; a cap alone prints as `… · Cap 8 · 🟢 Minor · User Cap`.
2. **Project override block.** See below. Wins over scope and matrix.
3. **Scope.** Work or Verify where the exact edit is already known — a rename, a one-line fix, a config value, a typo: −1 effort step (floor `low`; T4 never below its base). Writing new code or new tests is never "already known", however small. 20+ files on a T1/T2 topic: split into parallel agents by folder, do not raise effort.
4. **Matrix** cell.

### Project override block

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
- Agent budgets = 2, 3, 5, 8
- Questions = judge
- Pace = normal
- Language = Arabic
- Guide = on
```

Fifteen forms: `Topic / Side = model·effort` (one cell), `Topic: Name = T#` (move a topic to another tier), `Topic / Side cap = N` (reply cap), `Main session = model·effort` (read by you for Step 0, not enforced by the hook), `Session cap = N` (units per session before the hook tells you to stop and ask), `Context marks = N, N, …` (thousands of tokens at which the context watch warns — the line shown is the default; a 200K-window model wants `100, 150, 180`), `Receipt = full | short | savings N | off` (receipt form, see Step 6), `Break = N | off` (minutes away before the resume block is shown again; default 10), `Agents = ask | auto | N | off` (the agent gate: ask once per session — default —, size every task by tier, a fixed budget per task, or no budget), `Parallel = M` (background agents running at once, default 3), `Agent budgets = a, b, c, d` (agents per tier T1..T4 under `auto`), `Questions = judge | off` (the question gate), `Language = Arabic` (the language owner questions are written in), `Guide = on | off` (the 🧭 next line), `Pace = normal | fast` (`fast` when the user says the plugin slows them: the direct-read guard speaks at 8/16/32/64 reads instead of 4/8/16/32, 🟢 Minor and 🟡 Normal questions go to the user without a Judge — 🟠/🔴 are still judged —, and the receipt is the one-line form unless `Receipt` is set; the hooks themselves cost ~20–30 ms per tool call in either pace — the time goes to spawns, so under `fast` also prefer the 1–3-call exception of rule 7 and background spawns). The hooks read the project's `CLAUDE.md` first, then the user's `~/.claude/CLAUDE.md` — a line there applies to every project (`- Receipt = off` turns receipts off everywhere). Check for this block before routing. Mark its use in the route line: `(project override)`.

## Step 4 — Escalation (only on failure)

Escalate when a subagent returns `STATUS: partial|blocked` or `CONFIDENCE: low` (a Plan agent's `partial` whose OPEN holds owner questions, or a Work agent's `partial` whose LEFT is an owner decision rather than unfinished work, is not escalation — put the question under `open` in the receipt and ask the user), or the verifier returns `VERDICT: FAIL` (a criterion failed: fix with a W agent, then re-verify). A verifier `NOTE: ATTENTION:` does not escalate — it means the criteria pass but a critical issue outside them exists; show it to the user before closing. The `PostToolUse` hook flags these after every spawn, and also downgrades a reply itself when its header lies: `done` with GAPS/LEFT admitting unanswered parts becomes `partial`; a reader citing a path that does not exist becomes `low`. One step at a time, re-running the same subtask:

1. +1 effort on the same model (up to `xhigh`).
2. Next model at `medium`: haiku → sonnet → opus → fable (fable only for Analyse and Plan; Work and Verify stop at `opus·xhigh`).
3. `max` effort only for T4 topics after `opus·xhigh` (or `fable·high` on Analyse/Plan) failed.

Stop after 2 escalations per subtask. Report what failed and what was tried. Never re-run the same agent at the same setting.

**After a verifier FAIL:** if the fix is already known and takes ≤ 3 tool calls, the main session applies it (rule 7). Then re-verify **only the failed criterion**: run its command in the main session, or spawn Verify at −1 effort with that one criterion. A full re-verify at the original setting is only for a fix that touched more than the failed criterion.

## Step 5 — Write the subagent prompt for low token use

- Self-contained: goal, exact files or folders, constraints, and what "done" means. The subagent has none of your context.
- First line of every prompt: `abofles: <Topic> / <Side> · T<tier>` with the side as a full word (`Read`, `Analyse`, `Plan`, `Work`, `Verify`, `Judge`, `Explain`). The ledger hook reads it; `/abofles:bill` reports by topic from it.
- Last line of every prompt: `Line cap: N`. The agent's own file holds the reply format — do not repeat it.
- Give Read agents a precise question, not "explore the repo". Reads cover the working tree only — never `.worktrees/`, `.claude/worktrees/`, `node_modules/`, `bin/`, `obj/`, `vendor/` unless the task names them.
- Give Plan agents the same scope limits the Work agent will get: the files in scope, the files not to touch, what is out of scope. A plan that proposes six files for a two-file task is a prompt fault, not a planner fault.
- Give Work agents the plan or findings as a short list, not the transcript.
- Give Verify agents the acceptance criteria and the command to run.
- Run independent agents in parallel in one message (that is the one case for `run_in_background: true`).

## Step 6 — Show the work: progress line and receipt

Between spawns print nothing but the route line and, when a chain of 2+ spawns runs, one progress line reprinted only when it changes:

```
abofles [■■■□□] 3/5 · Plan ✓ · Work ✓ · Work ▶ · Verify · 142 u
```

At the end of every task that spawned agents, print the receipt as **plain markdown — never inside a code block** — five lines, this order, nothing after it except what the user asked for:

🧾 **4 Spawns + 2 gate · 2.1M Tokens · $1.12 · Saved 71% ($2.74)** vs Opus 5.5
- `done` → <what changed, one line, files named>
- `why` → <the reason or rule that drove it, one line>
- `check` → <the command that proves it → its decisive result>
- `open` → <follow-ups — or "none">
- `next` → 🧭 <the guide line the hook hands you — copy it as given>

**The guide line.** The hook computes `🧭 …` from the ledger, the memo, the state and the context size — a priority ladder: 🔴 open FAIL/ATTENTION · 🟠 judged question unasked, owner decisions open · 🟡 partial/low reply not escalated (with the Step 4 setting) · ⏳ background agents running · 🧠 context near a mark, memo Now stale · 💰 budget nearly out · ✅ the memo's Next. It is advice: copy it, then decide; the user sees the same line in the resume block (`guide`) and in the band above the prompt when the `abofles-guide` mod is installed. `/abofles:guide [--all]` prints it on demand; `- Guide = off` removes it.

**Readable, not dense.** A field with one item stays on its line. A field with 2+ items (several files changed, several follow-ups) puts nothing after the arrow and lists each item as an indented sub-bullet, one idea per line — a human must scan the receipt in seconds, and a long `;`-separated line cannot be scanned:

- `done` →
  - `AqsatiRules.cs`: SurchargeCapIqd = 5,000, `Surcharge()` clamps
  - `AqsatiRulesTester.cs`: 3 cap tests
- `open` →
  - ATTENTION: USD orders uncapped (`OrderPricingRules.cs:77`)
  - owner decision: cap per currency?

The hooks parse both shapes; the memo journal and Needs you take each sub-bullet as one item.

The first line is **computed by the hook** — never by you. `Spawns` counts the work agents; `+ N gate` the Judge/Explainer runs of the question gate (shown only when there were any). `Tokens` is every token the subagents were billed for — input, cache writes, **cache reads of each call's context**, output — summed over all their calls, so it is far larger than the harness's per-agent `totalTokens` (which counts a context once); the dollars are priced from exactly these tokens at list price, and the same tokens at the main session's model give the saving. When the baseline would have been cheaper the header reads `Cost +P% ($Z)`. A spawn whose transcript is missing is counted as ` · N unpriced` at the end of the line; only when no spawn has a transcript does the line fall back to the unit estimate (`… u …`). After every spawn the `PostToolUse` hook hands you the current header (`abofles: Receipt at task end … 🧾 **…**`); copy the newest one exactly. A task with no spawn gets no receipt. The project or user override `Receipt = …` decides the form, and the hook's note already tells you which one applies: `full` (default, the 5 lines), `short` (one line: header + ` · open: …`), `savings N` (full when the task saved ≥ N%, else no receipt), `off` (never). With no receipt, still name every open follow-up in prose.

`open` lists every reply that came back `partial`, `blocked`, `low`, with `NOTE: ATTENTION`, or with an unresolved `VERDICT: FAIL`, plus anything the user must decide. A task is never closed with an ATTENTION unmentioned. The `Receipt` output style (`abofles:Receipt` in the output-style picker) enforces this shape for the whole session; without it, the receipt and progress line still apply to abofles tasks.

**Session cap.** A project may set `- Session cap = N` (units) in its override block. The `PostToolUse` hook warns when the session's spawns pass it; then stop spawning and ask the user before the next spawn.

### Question gate — no question reaches the user unjudged

A `PreToolUse` hook denies every `AskUserQuestion` (except the agent gate) until a Judge has seen it. Reason: the user answers most questions with the recommended option without understanding them, and pays later in rework. Two sides, routed by the **tier of the decision** (money, auth, data = T4; a production rule = T3; the rest T1–T2):

| Tier | Judge (`abofles:abofles-judge`, header side `Judge`) | Explainer (`abofles:abofles-explainer`, side `Explain`) |
|---|---|---|
| T1 | Sonnet 5.5 · Low — judges **and** explains | — |
| T2 | Sonnet 5.5 · Medium — judges **and** explains | — |
| T3 | Sonnet 5.5 · Medium — judges, then `HANDOFF` | Opus 5.5 · Medium |
| T4 | Opus 5.5 · Medium — judges, then `HANDOFF` | Opus 5.5 · High |

Cap 40 lines each. These spawns do not count against the task's agent budget (the receipt shows them as `+ N gate`). Give the Judge everything it cannot see: the question as you would ask it, the options, what is being built, the files, what the user already decided this session, and `Language: <the language the user writes in>` — the Judge and the Explainer write every user-facing line in that language, with internal names, enum values and ticket keys turned into plain words. It also reads the memo's Decisions.

- `VERDICT: ANSWERED` — the evidence settles it. State the answer and its evidence in one line, continue, **do not ask**. The hook logs it in the memo's Decisions; on T3–T4 it also adds *judge decided (🔴 Critical): … — check* to Needs you so the user sees it in the next resume block.
- `VERDICT: ASK` (T1–T2) — `AskUserQuestion` whose **question text** is the `QUESTION`, a blank line, the `WHY` line, then the `EXPLAIN` block (table, example or diagram) — all inside the question, because the question box is what the user reads (reply text printed right before the box **is** shown above it — that is where a table goes; nothing printed is lost). The box renders **plain text** — a markdown table arrives as `| a | b |` soup, bold as `**`. Two shapes, and the hook's note after the Judge/Explainer tells you which applies:
  - **Plain EXPLAIN**: the question text is `QUESTION`, a blank line, `WHY` — and nothing else unless EXPLAIN carries a fact the options do not (a worked example with numbers, a timeline), then that as plain lines. **Never restate the options in the question text**: the option cards already show each label with its `then:` consequence as the description, and a question that lists "A does x, B does y, C does z" above the same three cards is read twice.
  - **Markdown EXPLAIN** (table, diagram, worked example): in **one assistant message**, first the text `📖 **Explanation for the question below**` with the block as real markdown, then the `AskUserQuestion` call — text and call in the same message, no other tool call between them (the desktop app folds text that is followed by further tool calls into a collapsed step, and a denied question folds it too). The question text carries QUESTION and WHY and ends with `📖 the full table/diagram is printed above this question` — no summary of the options. The `Stop` hook refuses to end the turn while a judged question is unasked. Never replace the question box with "reply A, B or C in chat".
  One option per `OPTIONS` line with the `then:` consequence as the description; the `RECOMMEND` option first with `(Recommended)`.
- `VERDICT: HANDOFF` (T3–T4) — spawn the Explainer with the Judge's `QUESTION`, `EVIDENCE` and `WHY` (never re-collect them), then ask from the Explainer's reply as above.

Re-asking the **same round** reworded or translated (the user rejected the wording, or asked for Arabic) needs no second Judge: within 15 minutes of an allowed question the hook lets the next one through, and a `SendMessage` to the Judge or Explainer that produced the round (the cheap way to reword) unlocks one `AskUserQuestion` for its reply — wait for that reply and ask from its wording, never with your own translation first. A new question later is judged again. Pass `Language: <language>` to the Judge and Explainer: the override `- Language = Arabic` fixes it for a project, else it is the language the user writes in. A dismissed question is not a decision: it is not logged, and may be asked again.

`- Questions = off` in the override block turns the gate off for a project; `- Pace = fast` keeps it for 🟠 Sensitive and 🔴 Critical questions only.

### Memo — the work journal (so the user never pays twice to re-read)

`.claude/abofles-memo.md` in the **project root — the directory the session started in** — is kept by the hooks, not by you. Several sessions may share one root: each keeps its **own Now block** (`Session <id>` inside the Now section), journal lines and Needs-you items carry the session tag `s:<id>`, and the resume block shows this session's Now and receipts only — other sessions' Now blocks appear as one labelled hint ("their work, not yours"), never as your `next`. A `cd` into a worktree or a nested repository never moves it (the hooks remember the root; a stray memo inside a team repo would be one `git add -A` from a commit). On its first write the hooks add `.claude/abofles-memo.*` to the root's `.git/info/exclude`, so it never shows in `git status`; the lock lives under `~/.abofles/state/`, never in the project.

- **Journal** — every receipt you print is parsed by the hooks (at the turn's end, or at the next spawn when you printed it mid-turn) and appended as one line (header · done · check · open). A receipt printed mid-turn also closes its task there: the budget and the header start again for the next ticket. Newest first, last 40 kept.
- **Needs you** — every `open` item that is an ATTENTION, a FAIL, an owner decision or a question becomes a numbered `[ ]` item that stays until resolved. This is the list of things the user must not miss.
- **Decisions** — every `AskUserQuestion` you ask is logged as the question sentence (not the story before it) with the answer. A logged decision is settled: never reopen it, never ask it again. A dismissed question is not logged. The Needs-you item that raised the question is ticked when it is answered.
- **Now** — the only section you write, via `/abofles:memo` (`memo.py now`): Task, Done, Left (one `Left` line per item — all of them are shown), Decisions, Next, Verify, Tree. The hook stamps it `Written <date time>`; the resume block shows that age and, when receipts came after it, a `since` line saying `now`/`next` may be stale — after a long working stretch, run `/abofles:memo` again before a break or a compact.

The **resume block** (`📍 **Resume**` · now · left · next · needs you · last 3 receipts · guide — a field with 2+ items is rendered as sub-bullets, so write one `Left` line per item in the memo) is handed to you by the hooks after a `/compact`, at session start when a memo exists, and on the first prompt after the user was away `Break` minutes (default 10). **Print it verbatim, first in your reply, then handle the prompt.** Never rebuild it by re-reading the transcript, the ledger or files — the user already paid for that output once. `/abofles:resume` prints it on demand.

When the user settles an open item in chat, run `python3 "<plugin root>/scripts/memo.py" resolve <n> "<what was decided>"` (one cheap call) so it leaves the list; when something is decided in prose without a question, `… memo.py note "<decision>"`. Put every owner decision and ATTENTION in the receipt's `open` line — that is how it reaches the list.

### Context watch — when to compact

The hooks read the session's context size from the transcript (the token count the next request will carry) and warn **once per mark** at 500K, 600K, 700K, 750K, 800K, 850K and 900K tokens (project override: `- Context marks = …`). When several marks are jumped at once, only the highest one warns. The warning arrives **once**, from the `Stop` hook at the **end of a turn** (when you finish or pause) — never at the start of a turn or between tool calls. The hook refuses that stop once and hands you the block; it is never sent again, so show it then. When it arrives:

1. Print the block it carries **verbatim as your last output of the turn** — a level-1 heading in bold, four lines — plus one line naming the branch that applies. Start no new work.
2. The block holds both advices; **you** pick the one that is true:
   - **No task open** → stop here. Run `/abofles:memo` (writes the Now section of `.claude/abofles-memo.md`: task, done, left, decisions, next, verify), then the user runs `/compact`. The resume block comes back right after the compact. Compacting between tasks is safe.
   - **Task open** (edits half applied, a chain running, a verifier not yet back) → do **not** compact now; a compact drops the chain's working state. Finish the current step, print the receipt, run `/abofles:memo`, **then** compact.
3. Compacting re-arms the marks: after `/compact` the context drops and every mark warns again when passed.

`/abofles:status` shows the current context size and the next mark; `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/abofles_hook.py" tokens` prints it alone.

The 900K mark is the last one: say so and treat it as "compact before the next task starts, whatever the state".

## Commands

- `/abofles:route <task>` — dry run: prints the `main:` line, every route line and the estimated units, spawns nothing. Use it to check a plan before paying for it.
- `/abofles:bill [--all]` — spawns per model and side, verdicts, top topics, the unit cost index, and the real spend (tokens, $, $ saved vs the main-session model). Reads the ledger the hook writes to `~/.abofles/ledgers/`.
- `/abofles:init [--dry-run]` — scans the project and adds a `## abofles overrides` block to its `CLAUDE.md`, with at most 5 suggested lines.
- `/abofles:status [--all] [--resolve <id>]` — session summary from the ledger: spawns per model as bars, confidence, open follow-ups. `--resolve <id>` closes one once handled.
- `/abofles:agents [auto | N | off | ask]` — show or set the agent gate: this task's budget, how many ran, the auto table.
- `/abofles:guide [--all]` — the 🧭 next line (what to do now, by priority), or the whole ladder.
- `/abofles:memo [path]` — writes the Now section of the work memo (`.claude/abofles-memo.md`) so the session can be compacted or paused without losing the thread. The context watch points here.
- `/abofles:resume [--all] [--resolve <n> [note]] [--note <text>]` — "where was I?": prints the resume block from the memo without re-reading anything; `--resolve` ticks a Needs-you item, `--note` records a decision made in chat.

## Example

Orchestrator mode (main = Opus 5.5 · Medium); the agent gate was answered `Auto` earlier in the session.

Task: "Add commission calculation to the wallet transfer, with tests."

main: suggest Opus 5.5 · High for this task (now Opus 5.5 · Medium). Switch in the model picker, or say "keep".

- 🔍 `Read` → **Pricing, Fees, Commission & Tax** · Sonnet 5.5 · Low · Cap 100 · 🔴 Critical
- 📐 `Plan` → **Pricing, Fees, Commission & Tax** · Opus 5.5 · Extra · Cap 150 · 🔴 Critical
- 🛠️ `Work` → **Pricing, Fees, Commission & Tax** · Opus 5.5 · High · Cap 40 · 🔴 Critical
- 🛠️ `Work` → **Unit Test** · Sonnet 5.5 · Medium · Cap 20 · 🟡 Normal
- ✅ `Verify` → **Financial & Amount Calculations** · Opus 5.5 · High · Cap 60 · 🔴 Critical

```
abofles [■■■■■] 5/5 · Read ✓ · Plan ✓ · Work ✓ · Work ✓ · Verify ✓ · 250 u
```

🧾 **5 Spawns · 3.4M Tokens · $2.95 · Saved 8% ($0.26)** vs Opus 5.5
- `done` → commission = amount × rate, capped at 5,000 IQD — AqsatiRules.cs, AqsatiRulesTester.cs
- `why` → T4 money rule: cap per unit, rounding once, tests at under/at/over
- `check` → `dotnet test …AqsatiRules` → Passed 13, Failed 0
- `open` → ATTENTION: cap compares in order currency — USD orders uncapped (OrderPricingRules.cs:77); owner decision

## Maintaining this skill

Topics, tiers, cell overrides, reply caps and signals live in one place: `scripts/gen_matrix.py` (plugin root). Edit it, run `python3 scripts/gen_matrix.py`; it rewrites the topic index above and `references/matrix.md`. Never edit the index or the matrix by hand. Reply formats live in `agents/*.md` (plugin root), one file per side. Hooks live in `hooks/abofles_hook.py` (`pre` blocks and enforces the agent budget, `post` logs and checks sync replies or writes a `pending` line for background spawns, `stop` fills that line on `SubagentStop`, `guard` warns on direct-read streaks, `start` writes the session marker and the resume block, `receipt` refuses a stop without the receipt and journals it, `prompt` notes the effort and the break, `decision` logs questions and the gate answer, `qgate` guards questions); the memo and gate CLIs in `scripts/memo.py` and `scripts/agents.py`; the status in `scripts/status.py`; the output style in `output-styles/receipt.md`; unit tests in `scripts/test_hooks.py`; the bill in `scripts/bill.py`; commands in `commands/*.md`.
