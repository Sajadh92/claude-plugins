# abofles — ابو فليس

In Iraqi slang, Abo Fles is the stingy guy who counts every fils. This plugin counts every token.

A Claude Code plugin that picks the right model and effort for every subagent, so multi-agent sessions stop running cheap jobs on expensive settings.

- 100 coding topics in 13 groups (security, money, business logic, testing, debugging, code health, architecture, data, integrations, DevOps, frontend, docs, product), each with a risk tier (T1–T4).
- 5 sides per topic: Read & Collect, Analyse & Find Gaps, Plan & Design, Act & Work, Verify & Review.
- Each topic/side cell maps to a model (`haiku`, `sonnet`, `opus`, `fable` — always the latest version) and an effort (`low` … `max`).
- Reply cap per tier and side, so a Read agent on a T1 topic returns 20 lines and an Analyse agent on a T4 topic returns 50 — never cutting a finding to fit.
- 7 side agents (`abofles-reader`, `-analyst`, `-planner`, `-worker`, `-verifier`, `-judge`, `-explainer`) with a fixed reply format: `STATUS`, `CONFIDENCE`, then the side's content. Low confidence feeds escalation.
- Two modes by main model: **orchestrator** (opus/fable — the main session only routes and decides; a guard warns when it greps instead of spawning a reader) and **worker** (haiku/sonnet — the agent gate offers `Switch main to Opus 5.5 and orchestrate` on the first spawn, while the context is still cheap to rebuild).
- Progress line during a chain and a 5-line **receipt** at the end of every task that spawned agents: a header the hook computes from the subagents' transcripts (spawns · real tokens · real $ · $ and % saved vs the main session's model at list prices) then done · why · check · open. `Receipt = full | short | savings N | off` sets the form per project or for every project (in `~/.claude/CLAUDE.md`). Ships an optional **Receipt** output style (fixed line shapes, numbers first, nothing twice) — pick `abofles:Receipt` in the output-style picker.
- `/abofles:status`: spawns per model as bars, confidence, and the open follow-ups from the ledger; `--resolve <id>` closes one.
- Optional `Session cap = N` units in the project override block; the hook says stop-and-ask when passed.
- Knows the session's **effort** (Claude Code passes it to hooks): the skill's `main:` line, `/abofles:bill` and `/abofles:status` use the real level, not an assumed `high`.
- **Context watch**: at 500K, 600K, 700K, 750K, 800K, 850K and 900K tokens of context the Stop hook makes the session print, at the end of the turn, a big, bold "run `/abofles:memo`, then `/compact`" block once per mark — with the opposite advice ("finish the step and the receipt first, do not compact mid-task") while a chain is running. Marks are per project (`Context marks = 100, 150, 180` for a 200K window). `/abofles:memo` writes the hand-off memo (task, done, left, decisions, open, next, verify) to `.claude/abofles-memo.md`.
- A `PreToolUse` hook blocks any subagent spawn that has no `model` or `effort`, or puts Fable on a Read/Work/Verify agent. A `PostToolUse` hook logs every spawn and flags replies that skip the format, pass the cap, or report low confidence; a `SubagentStop` hook completes the ledger for background spawns.
- **Work memo**: the hooks keep `.claude/abofles-memo.md` in the project root (the directory the session started in — a `cd` into a nested repo never moves it; it is added to `.git/info/exclude`; several sessions in one root each keep their own Now block and see their own receipts) — one journal line per receipt, a numbered **Needs you** list (ATTENTION, FAIL, owner decisions — stays until resolved), every `AskUserQuestion` with its answer. After a `/compact`, at session start, or on the first prompt after `Break` minutes away (default 10, `Break = N | off`), the session prints a short **resume block** (now · next · needs you · last receipts) instead of re-reading anything. `/abofles:resume` prints it on demand.
- **Agent gate**: before the first spawn of a session the plugin asks once — *Auto* (every task sized by topic, side and tier: Minor 2 · Normal 3 · Sensitive 5 · Critical 8 agents in Orchestrator mode, 1 · 2 · 4 · 6 in Worker mode), *This task: N agents* (with the units and $ estimate), *Main session only*, or a number / `off` typed in Other. The hook then denies any spawn over the budget and caps background agents at `Parallel` (default 3), so a session never runs 10+ agents without the user knowing. `Agents = ask | auto | N | off`, `Parallel = M`, `Agent budgets = a, b, c, d` in the override block; `/abofles:agents` mid-session.
- **Guide**: after every receipt and in every resume block the hooks add one `🧭 next →` line — what to do now, by priority (open FAIL/ATTENTION, judged question unasked, owner decisions, unescalated partial/low with the Step 4 setting, background agents, context/memo hygiene, budget, the memo's Next). Advice only; `/abofles:guide`; `Guide = off`. The companion mod `abofles-guide` draws the same line in a band above the prompt box with a Hide button.
- **Pace**: `Pace = fast` in the override block when speed matters more than control — the direct-read guard waits until 8 reads, Minor/Normal questions skip the Judge (Sensitive/Critical are still judged), receipts are one line. The hooks cost ~20–30 ms per tool call either way; the time a session spends is in the spawns, so `fast` is about fewer of them.
- **Question gate**: no `AskUserQuestion` reaches the user before a **Judge** agent has tried to answer it from the code, tests, docs, Jira and the memo (with evidence — the session then states the answer and goes on, logged in the memo), or rewritten it in plain words with each option's consequence, a recommendation and a table/example/diagram when needed. T1–T2: one Sonnet agent judges and explains; T3: Sonnet judges and hands off to an Opus explainer; T4: Opus judges, Opus · High explains. Both write in the user's language, with code names turned into words; a plain explanation goes inside the question text; a table or diagram is printed in the same message right above the question box, where the app shows it; the Stop hook refuses to end a turn while a judged question is unasked. Re-asking the same round reworded or translated needs no second judge; `Language = Arabic` fixes the question language for a project; gate spawns never count against the agent budget. `Questions = off` disables it.
- Commands: `/abofles:route <task>` (dry run with a cost estimate, no spawns), `/abofles:bill` (what this session's subagents cost in relative units, and what was saved), `/abofles:status` (session summary + follow-ups), `/abofles:init` (project override block), `/abofles:memo` (Now section of the memo before a compact), `/abofles:resume` (where was I), `/abofles:agents` (agent gate), `/abofles:guide` (what to do next).
- Escalates only on failure. Never uses ultracode without your approval.

Full matrix: [skills/abofles/references/matrix.md](skills/abofles/references/matrix.md).

Requires `python3` on PATH for the hooks and the bill. Without it the hooks exit silently and the skill still routes — nothing is enforced or logged.

## Layout

```
.claude-plugin/plugin.json   manifest
skills/abofles/              the routing skill + references/matrix.md
agents/                      7 side agents with fixed reply formats (Read, Analyse, Plan, Work, Verify, Judge, Explain)
hooks/                       hooks.json + abofles_hook.py (pre = enforce model/effort + agent budget, post = log + check, stop = background fill-in, guard = direct-read streak, start = session marker + resume block, prompt = effort note + break resume, receipt = receipt enforcement + memo journal + context watch at turn end, decision = question log + gate answer, qgate = question gate, sendmsg = re-ask unlock)
output-styles/               receipt.md — Receipt style, optional
commands/                    bill.md, route.md, init.md, status.md, memo.md, resume.md, agents.md, guide.md
scripts/                     gen_matrix.py (single source of truth), bill.py, status.py, memo.py, agents.py, guide.py, test_hooks.py
```

The ledger is written to `~/.abofles/ledgers/<session>.jsonl` (`ABOFLES_LEDGER_DIR` to move it); the guard's counter to `~/.abofles/state/` (`ABOFLES_STATE_DIR`).

## Install

In Claude Code:

```
/plugin marketplace add Sajadh92/claude-plugins
/plugin install abofles@sajadh92
```

Or from a local clone:

```
claude plugin marketplace add /path/to/claude-plugins
claude plugin install abofles@sajadh92
```

Then add one line to `~/.claude/CLAUDE.md` so every session routes before it spawns:

```
- Always use the abofles skill before spawning subagents, and at the start of each coding task to check the main session model.
```

Optional: pick `abofles:Receipt` in the output-style picker (session `⋯` menu → Output style) for the compact progress line + receipt format.

## Quick start — what a task looks like

```
> Cap the Aqsati store surcharge at 5,000 IQD per unit in AqsatiRules.Surcharge, and cover it in TestLab/AqsatiRulesTester.cs

```

- 📐 `Plan` → **Pricing, Fees, Commission & Tax** · Opus 5.5 · Extra · Cap 150 · 🔴 Critical
- 🛠️ `Work` → **Pricing, Fees, Commission & Tax** · Opus 5.5 · High · Cap 40 · 🔴 Critical
- 🛠️ `Work` → **Unit Test** · Sonnet 5.5 · Medium · Cap 20 · 🟡 Normal
- ✅ `Verify` → **Financial & Amount Calculations** · Opus 5.5 · High · Cap 60 · 🔴 Critical

```
abofles [■■■■] 4/4 · Plan ✓ · Work ✓ · Work ✓ · Verify ✓ · 240 u
```

🧾 **4 Spawns + 1 gate · 2.6M Tokens · $2.40 · Saved 0% ($0.00)** vs Opus 5.5
- `done` →
  - AqsatiRules.cs: SurchargeCapIqd = 5,000, Surcharge() clamps
  - AqsatiRulesTester.cs: 3 cap tests
- `why` → money topic → T4 plan/work/verify, tests are T2 → sonnet
- `check` → `dotnet test TestLab/TestLab.csproj` → total 13, failed 0
- `open` → ATTENTION: cap applies in order currency — USD orders uncapped (OrderPricingRules.cs:77)

A read-only question on the same project routes to `haiku·low`: the same 1M-token read costs $0.28 on Haiku 5.5 and $0.90 on Opus 5.5 — that is where the saving comes from. `Tokens` counts every billed token of the subagents, cache reads of each call's context included (that is what the dollars are priced from), so it is much larger than the harness's per-agent `totalTokens`. `/abofles:bill` adds the real tokens and dollars of the session. `/abofles:route <task>` shows the plan and the estimate without spawning anything; `/abofles:bill` shows what the session cost afterwards.

## Change cells for one project

Add this block to the project's `CLAUDE.md`. It wins over the matrix for that project only.

```
## abofles overrides
- Unit Test / Work = haiku·medium
- Financial & Amount Calculations / Verify = opus·xhigh
- Topic: Notifications & Messaging = T3
- Codebase Exploration & Onboarding / Read cap = 200
- Main session = sonnet·medium
- Session cap = 600
- Receipt = savings 30
- Break = 10
- Agents = auto
- Parallel = 3
- Agent budgets = 2, 3, 5, 8
- Questions = judge
- Pace = normal
- Language = Arabic
- Guide = on
- Context marks = 500, 600, 700, 750, 800, 850, 900
```

Sides are always written in full: Read, Analyse, Plan, Work, Verify.

## Add or change a topic

Everything lives in `scripts/gen_matrix.py`: topics, tiers, cell overrides, reply caps and keyword signals. Reply formats live in `agents/*.md`, one file per side. Edit it, then run:

```
python3 scripts/gen_matrix.py
```

It rewrites the topic index in `skills/abofles/SKILL.md` and regenerates `skills/abofles/references/matrix.md`. Bump `version` in `.claude-plugin/plugin.json` and in the root `.claude-plugin/marketplace.json`.
