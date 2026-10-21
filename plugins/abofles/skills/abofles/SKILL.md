---
name: abofles
description: "Abo Fles (ابو فليس) — picks the model (haiku / sonnet / opus / fable) and effort (low..max) for every subagent in coding work from a topic × side matrix, and suggests the main-session model. TRIGGER once per session, before the first coding task or Agent tool call (it stays in context after that — never re-invoke it per task), before planning a multi-agent fan-out, and when the user asks which model or effort to use. Never spawn a subagent in coding work without routing here first. SKIP for non-coding tasks."
---

# Abo Fles (ابو فليس) — Agent Router

Goal: correct work, fast, fewest tokens. The usual waste is a subagent inheriting the main session's model and effort.

- Models (latest): `haiku` = Haiku 5.5 · `sonnet` = Sonnet 5.5 · `opus` = Opus 5.5 · `fable` = Fable 5.1. Effort: `low < medium < high < xhigh < max`.
- **To the user, write names as the Claude app does** (`Haiku 5.5 · Low`, `Opus 5.5 · Extra` = xhigh); Agent params and matrix cells stay lowercase.
- Cost units (`u`) = price × effort factor; table in [references/receipt-and-example.md](references/receipt-and-example.md).

## Hard rules

1. Every Agent call passes **both** `model` and `effort`. Never inherit. This skill is the explicit instruction that permits setting `effort`.
2. Print one route line before each spawn, plain markdown: <Side emoji> `<Side>` → **<Topic>** · <Model> · <Effort> · Cap <N> · <Tier>[ · <Modifier>]. Emoji: 🔍 Read · 🧠 Analyse · 📐 Plan · 🛠️ Work · ✅ Verify · ⚖️ Judge · 💬 Explain; reviewers (Verify cell): 🛡️ Security · 💰 Finance · 📜 Compliance · 🧪 Tester · 🎯 QA · 🎨 UIUX · 🧹 Clean · 🗄️ DBA · ⚙️ Ops · ⚡ Perf · 📊 Data. Tier = the word with its dot, never the code: 🟢 Minor (T1) · 🟡 Normal (T2) · 🟠 Sensitive (T3) · 🔴 Critical (T4); `T#` stays in prompt headers. Side = full word; topic = matrix name exactly, Title Case. Modifiers, each after its own ` · `: `Scope −1`, `User: <what>`, `User Cap`, `Project Override`, `Merged: N Questions`, `Parallel`, `Fallback: <Model> Unavailable`. Several route lines: bullets.
3. One subagent = one side (Read → Analyse → Plan → Work → Verify, separate small agents; Judge and Explain are the question gate's). Results flow forward as short summaries.
4. `fable` only on Analyse and Plan. Never for Read, Work or Verify.
5. `max` effort only through escalation, never as a start value.
6. **Ultracode / Workflow tool: never without a clear yes from the user.** For huge jobs (30+ files) suggest it in one line with an agent count; wait.
7. No subagent when the main session can finish in 1–3 tool calls, unless the user asks for one or says "use abofles".
8. **Merge parallel reads**: same topic and tier → one Read agent with a numbered question list; split only for unrelated folders or a combined cap over 150 lines.
9. **Model not available** (access/permission error): re-spawn one step down, effort up — `fable` → `opus·xhigh`, `opus` → `sonnet·xhigh`, `sonnet` → `haiku·high`; modifier `Fallback: Fable 5.1 Unavailable`. Never retry the same model.
10. **Background spawns:** `run_in_background: false` unless in a parallel group (independent agents go in one message); for a background spawn **you** check `STATUS`/`CONFIDENCE` on arrival and apply Step 4. Details and fallback agents: [references/spawn-details.md](references/spawn-details.md).

A hook blocks breaches of rules 1 and 4; `abofles:skip` as the prompt's first word bypasses it once (non-coding spawns only).

## Step 0 — Main session check (once per session, then once per task)

You know your model. Your effort comes from the hook line `abofles: session effort is <level>`; else the user's statement or a `Main session = …` override; the desktop `get_session` tool is the last resort ([references/agent-gate.md](references/agent-gate.md)). Else unknown: never infer it.

| Main model | Mode | What it means |
|---|---|---|
| opus, fable | **Orchestrator** | Routes, spawns, reads replies, decides. Does **not** read code, grep, write code or run tests itself — every side goes through the matrix. A `Stop` hook refuses to end a turn that spawned agents without the receipt. A guard warns on direct-read streaks in any mode. |
| haiku, sonnet | **Worker** | Fine for T1–T2 or pure coordination. For T3+ the gate offers `Switch main to Opus 5.5 and orchestrate`. |

**Agent gate — once per session, before the first spawn.** The hook denies the first Agent call until you ask (unless `Agents = auto | N | off`). Size the task, then ask **one** `AskUserQuestion` whose text contains `Abo Fles agent gate`, options in this order, labels starting exactly:
1. `Auto (recommended)` 2. `This task: N agents` 3. `Main session only` 4. Orchestrator, Large task only: `Max: N agents · M parallel`; Worker mode (any tier): `Switch main to Opus 5.5 and orchestrate` — if chosen, reply with one line, `Pick Opus 5.5 in the model picker (bottom right), then send "go".`, and **end the turn** (the plugin cannot switch the model).
The hook records the answer (`agents: …`) — continue, never re-ask; over budget it denies the spawn: finish in the main session or ask to raise it. Descriptions, sizing, budgets: [references/agent-gate.md](references/agent-gate.md).

**Per task**, tier the task and compare with the table. The hook hands you a line at the first work spawn (`abofles: new task — print this line now … \`main: …\``): print it **as given, as the next line of your reply** (right after the first route line), every task — `main: <Model> · <Effort> fits this <Tier> task` when both match, else `main: suggest <Model> · <Effort> for this <Tier> task (now <current Model> · <Effort or 'effort unknown'>). Switch in the model picker, or say "keep".` Continue on the current setting; a resume block printed first never replaces it.

| Task shape | Suggested main session |
|---|---|
| Quick question, rename, tiny edit | haiku·low |
| T1–T2 task, or main session only coordinates | sonnet·medium |
| T3 task, or main session writes code itself | opus·medium |
| T4 task, or design across many modules | opus·high |
| Hard T4 architecture, security, or incident work, unclear cause | fable·medium |

## Step 1 — Find the side

| Side | The subagent... | `subagent_type` |
|---|---|---|
| **Read** | finds files, maps code, collects facts; no opinions | `abofles:abofles-reader` |
| **Analyse** | finds bugs/gaps/risks, compares options | `abofles:abofles-analyst` |
| **Plan** | plans or designs before code changes | `abofles:abofles-planner` |
| **Work** | writes or edits code, tests, docs, configs | `abofles:abofles-worker` |
| **Verify** | runs tests, reviews the diff, checks docs vs code | `abofles:abofles-verifier` |
| **Review** (Verify cell) | one specialist per concern, after Verify passes, in parallel: `Security` · `Finance` · `Compliance` · `Tester` (the only one that edits — test files) · `QA` · `UIUX` (uses the Better Design and UX Pilot connectors when connected) · `Clean` · `DBA` · `Ops` · `Perf` · `Data` | `abofles:abofles-security` · `-finance` · `-compliance` · `-tester` · `-qa` · `-uiux` · `-cleancoder` · `-dba` · `-ops` · `-perf` · `-data` |

Every abofles agent opens with `STATUS: done|partial|blocked` and `CONFIDENCE: high|medium|low` (feeds Step 4); its file holds the reply format. **The cell picks the model, not the agent type**: a read `abofles-reader` cannot do (Jira connector, project agent) still takes the Read cell — `general-purpose` at `haiku·low`.

## Step 1½ — Find the workflow

Two inputs: the topic's **tier** (Step 2) and the ask's **intent**. Print one workflow line before the first route line: `🧭 Workflow · <intent> · <Tier> → <steps>`.

| Intent | The ask looks like | Steps |
|---|---|---|
| `question` | where is X, what calls Y, how does Z work | Read |
| `review` | review X, find risks, audit, compare | Read → Analyse → Review |
| `design` | plan how, design, migration strategy | Read → Analyse → Plan |
| `change` 🟢 / 🟡 | add, fix, implement, refactor | Work → Verify / Read → Work → Verify |
| `change` 🟠 / 🔴 | same | Read → Analyse → Plan → Work → Verify → Review |

`Review` = the topic domain's specialist reviewers at that tier — the lookup prints them per topic (`reviewers T3 … · T4 …`; table in [references/workflow.md](references/workflow.md): Money → Finance; Security → Security; Databases → DBA; Cache/Search/Messaging and Performance → Perf; DevOps, Cloud, Edge, Servers, Observability → Ops; Data & Analytics → Data; Frontend/UX/Mobile → UIUX; Business, APIs, Integrations, AI → QA; Testing/Debugging → Tester; Code Health → Clean; PII and audit topics add Compliance), spawned **in parallel after Verify passes**, each at the tier's Verify cell with the header `abofles: <Topic> / <Tag> · T<tier>`. A reviewer FAIL → Work fixes → re-run that reviewer only. A step you drop (rule 7, or the ask makes it pointless) is fine — say so in the receipt's `workflow` line. On a 🔴 change the Plan's open decisions go through the Judge before Work starts. **Review gate** (hook): a 🔴 change closed without a required reviewer is refused once, naming them; 🟠 gets a 🟠 guide item; `Security skipped: <reason>` in the `workflow` line passes it. Overrides: `Workflow: <Domain|Topic> = …`, `Reviewers: <Domain|Topic> = …`, `Review: <Tag> / T<tier> = cell`, `Review gate = auto | on | warn | off` ([references/overrides.md](references/overrides.md)).

## Step 2 — Find the topic and its tier

**Look it up, never read a list.** 1,100+ topics in 27 domains live in an index; one Bash call returns the top 3 with tier, cells, reviewers, workflow and suggestions (≤ 7 lines):

```
python3 "<plugin>/scripts/topic.py" find "<the ask, 3–8 content words>"
```

The exact path is in the SessionStart note `abofles: topic lookup = …` (else `<this skill's base dir>/../../scripts/topic.py`). Run it once per task before the workflow line; the call is free of the direct-read guard. Pick the match that names the *work*, not the code it touches; several unrelated topics → the highest tier, or one agent per independent topic. `topic.py show <#|name>` prints one topic's header template; `domains` the domain table ([references/topics.md](references/topics.md)); `list <CODE>` a domain. Project overrides are already applied in the output (`· Project Override`). No match → fast tier test below + the closest domain; name the nearest topic in the route line and tell the user the topic is new. A `💡 suggest` line names a package or tool fit for the topic and the project's stack (e.g. DynamicWhere.ex on .NET dynamic filtering): put it in the Plan/Work prompt and tell the user in one line; never install it unasked.

Tier = how much a mistake costs. Cell = `model·effort / reply cap` (max content lines, status header excluded).

| Tier | A mistake means... | Read | Analyse | Plan | Work | Verify |
|---|---|---|---|---|---|---|
| 🟢 T1 Minor | cosmetic, local, instantly reversible | haiku·low / 20 | sonnet·low / 10 | sonnet·low / 25 | haiku·medium / 10 | haiku·low / 10 |
| 🟡 T2 Normal | a test catches it; dev-only; a redeploy reverts it | haiku·low / 40 | sonnet·medium / 20 | sonnet·medium / 50 | sonnet·medium / 20 | sonnet·low / 20 |
| 🟠 T3 Sensitive | wrong prod behaviour, business rule, shared infra, SLO | haiku·medium / 60 | opus·medium / 35 | opus·medium / 90 | sonnet·high / 30 | sonnet·high / 35 |
| 🔴 T4 Critical | money, auth, secrets, PII, data loss, prod infra, irreversible | sonnet·low / 100 | opus·high / 50 | opus·xhigh / 150 | opus·high / 40 | opus·high / 60 |

**Tier bumps** (after the lookup, say so in the route line as ` · Prod +1` / ` · Sandbox −1`): the ask names production, live customers, real money or real personal data → +1 (max T4); the ask is read-only, a dry run, localhost-only or a sandbox → −1 (floor T1; Money, Security and Privacy topics never below T3). **Fast tier test** (no match): money, auth, secrets, personal data, data loss, concurrency → T4; production behaviour or business rule → T3; ordinary code or tests → T2; text, formatting, exploration → T1.

Never cut a finding to fit — rank, keep the top ones in full, end with `+N more: <one line each>`. One fact per line (`path:line — issue — fix`), ≤ 200 chars, no prose, code dumps or code fence.

**Reading is not the task.** A caller list, usage map, "where is X", "what calls Y" is **Codebase Exploration & Onboarding (T1, haiku·low)** whatever code it touches, even money or auth. The T4 Read cell (`sonnet·low`) is for reads whose misreading breaks the plan (exact rounding rules, token lifetime, state transitions before changing them).

## Step 3 — Apply modifiers (in precedence order)

1. **User in chat.** A named model, effort or cap wins; modifier `User: Sonnet 5.5 · High`, or `User Cap` for a cap alone.
2. **Project override block** (`## abofles overrides` in `CLAUDE.md`; check before routing; `Project Override`): [references/overrides.md](references/overrides.md).
3. **Scope.** Work/Verify where the exact edit is known (rename, one-line fix, config value, typo): −1 effort (floor `low`; T4 never below base); new code or tests is never "known". 20+ files, T1/T2: split by folder, don't raise effort.
4. **Matrix** cell.

## Step 4 — Escalation (only on failure)

Escalate on `STATUS: partial|blocked`, `CONFIDENCE: low`, or verifier `VERDICT: FAIL` (fix with a Work agent, re-verify). Not escalation: a `partial` whose OPEN/LEFT is an owner decision (put it under `open`, ask the user); verifier `NOTE: ATTENTION:` (show it). One step at a time, re-running the same subtask:

1. +1 effort on the same model (up to `xhigh`).
2. Next model at `medium`: haiku → sonnet → opus → fable (fable only Analyse/Plan; Work/Verify/Read stop at `opus·xhigh`).
3. `max` only for T4 after `opus·xhigh` (or `fable·xhigh` on Analyse/Plan) failed — opus·max for T4 Work/Verify. No step left: stop and report (the 🟡 guide item says so).

Stop after 2 escalations per subtask; report what failed. Never re-run at the same setting.

After a verifier FAIL, re-verify only the failed criterion: [references/spawn-details.md](references/spawn-details.md).

## Step 5 — Write the subagent prompt for low token use

- Self-contained (goal, exact files, constraints, "done"): the subagent has none of your context.
- First line: `abofles: <Topic> / <Side> · T<tier>` (side as a full word: `Read`, `Analyse`, `Plan`, `Work`, `Verify`, `Judge`, `Explain`). Last line: `Line cap: N`.
- Read: a precise question; working tree only, never `.worktrees/`, `.claude/worktrees/`, `node_modules/`, `bin/`, `obj/`, `vendor/` unless named. Plan: files in scope, not to touch, out of scope. Work: plan or findings as a short list. Verify: criteria and the command.
- Judge/Verifier needing a ticket (no Jira access): fetch it yourself (first two fetch-by-key reads per task are free) or via the Read agent, then paste summary, acceptance criteria and status.

## Step 6 — Progress line, receipt, gates, memo

Between spawns print only the route line and, for 2+ spawns, a progress line when it changes: `abofles [■■■□□] 3/5 · Plan ✓ · Work ✓ · Work ▶ · Verify · 142 u`

After every task that spawned agents print the receipt as **plain markdown, never in a code block**: the 🧾 header, then bullets `done`, `why`, `check`, `workflow` (🟠/🔴 changes: each step and reviewer with ✓, or `<Tag> skipped: <reason>`), `open`, `next` (2+ items → indented sub-bullets). **The hook computes the header** — copy the newest `abofles: Receipt at task end … 🧾 **…**` exactly; `next` is the 🧭 line it hands you. The form (`full | short | savings N | off`) follows its note. `open` lists every `partial`, `blocked`, `low`, `NOTE: ATTENTION` or unresolved FAIL reply, plus anything the user must decide; never close with an ATTENTION unmentioned. Shape and example: [references/receipt-and-example.md](references/receipt-and-example.md).

- **Question gate**: a hook denies every `AskUserQuestion` bar the agent gate until a Judge has seen it; route by the decision's tier, follow the VERDICT (`ANSWERED` → don't ask; `ASK` → ask; `HANDOFF` → Explainer first). Read [references/question-gate.md](references/question-gate.md) first.
- **Resume block** (`📍 **Resume**`) handed by a hook: print verbatim first, then the prompt; never rebuild it. **Context watch** block from the `Stop` hook: print verbatim as the turn's last output plus one line for the branch that applies (no task open / task open — see memo-resume.md). Memo, Needs-you, guide: [references/memo-resume.md](references/memo-resume.md).
- **Session cap** warning: stop spawning, ask.

Commands and editing this skill: [references/maintenance.md](references/maintenance.md).

