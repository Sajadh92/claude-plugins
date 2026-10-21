# abofles — ابو فليس

In Iraqi slang, Abo Fles is the stingy guy who counts every fils. This plugin counts every token.

A Claude Code plugin that picks the right model and effort for every subagent, so multi-agent sessions stop running cheap jobs on expensive settings.

- 100 coding topics in 13 groups (security, money, business logic, testing, debugging, code health, architecture, data, integrations, DevOps, frontend, docs, product), each with a risk tier (T1–T4).
- 5 sides per topic: Read & Collect, Analyse & Find Gaps, Plan & Design, Act & Work, Verify & Review.
- Each topic/side cell maps to a model (`haiku`, `sonnet`, `opus`, `fable` — always the latest version) and an effort (`low` … `max`).
- Reply cap per tier and side, so a Read agent on a T1 topic returns 20 lines and an Analyse agent on a T4 topic returns 50 — never cutting a finding to fit.
- 7 side agents (`abofles-reader`, `-analyst`, `-planner`, `-worker`, `-verifier`, `-judge`, `-explainer`) with a fixed reply format: `STATUS`, `CONFIDENCE`, then the side's content. Low confidence feeds escalation.
- Two modes by main model: **orchestrator** (opus/fable — the main session only routes and decides; the direct-read guard warns in any mode when it greps instead of spawning a reader) and **worker** (haiku/sonnet — the agent gate offers `Switch main to Opus 5.5 and orchestrate` on the first spawn, while the context is still cheap to rebuild).
- Progress line during a chain and a 5-line **receipt** at the end of every task that spawned agents: a header the hook computes from the subagents' transcripts (spawns · real tokens · real $ · $ and % saved vs the main session's model at list prices) then done · why · check · open. `Receipt = full | short | savings N | off` sets the form per project or for every project (in `~/.claude/CLAUDE.md`). Ships an optional **Receipt** output style (fixed line shapes, numbers first, nothing twice) — pick `abofles:Receipt` in the output-style picker.
- `/abofles:status`: spawns per model as bars, confidence, and the open follow-ups from the ledger; `--resolve <id>` closes one.
- Optional `Session cap = N` units in the project override block; the hook says stop-and-ask when passed.
- Knows the session's **effort** (Claude Code passes it to hooks): the skill's `main:` line, `/abofles:bill` and `/abofles:status` use the real level, not an assumed `high`.
- **Context watch**: at 500K, 600K, 700K, 750K, 800K, 850K and 900K tokens of context the Stop hook makes the session print, at the end of the turn, a big, bold "run `/abofles:memo`, then `/compact`" block once per mark — with the opposite advice ("finish the step and the receipt first, do not compact mid-task") while a chain is running. Marks are per project (`Context marks = 100, 150, 180` for a 200K window). `/abofles:memo` writes the hand-off memo (Task, Done, Left, Decisions, Next, Verify, Tree) to `.claude/abofles-memo.md`.
- A `PreToolUse` hook blocks any subagent spawn that has no `model` or `effort`, or puts Fable on a Read/Work/Verify agent. A `PostToolUse` hook logs every spawn and flags replies that skip the format, pass the cap, or report low confidence; a `SubagentStop` hook completes the ledger for background spawns.
- **Work memo**: the hooks keep a small main memo `.claude/abofles-memo.md` (Needs you, notes, a Sessions index with one link per session) and one file per session `.claude/abofles-memo.d/<session>.md` (Now, Journal, that session's decisions) in the project root (the directory the session started in — a `cd` into a nested repo never moves it, but the session's edits do: once three or more land in another repository and more than in the launch folder, the session's memo moves there with its Needs-you items and index line, so a session opened in the wrong folder still files under the project it works on; `/abofles:resume --move <folder>` does it by hand; both memo headers carry `Project: <path>`; both files are added to `.git/info/exclude`; a receipt rewrites one small file plus an index line, and no session ever prints another's journal) — after every receipt the hook rewrites this session's Now from it (Task `none — between tasks`, Done, Left/Next from `open`, Decisions kept, Verify from `check`, Tree from git status; stamped `Written … · from receipt`) — `/abofles:memo` still writes a richer one before a `/compact` — one journal line per receipt, a numbered **Needs you** list (ATTENTION, FAIL, owner decisions — stays until resolved), every `AskUserQuestion` with its answer. After a `/compact`, at session start, or on the first prompt after `Break` minutes away (default 10, `Break = N | off`), the session prints a short **resume block** (now · next · needs you · last receipts) instead of re-reading anything. `/abofles:resume` prints it on demand. Its **scope** is `project` by default (every session of this project; a session with nothing of its own yet sees the others as one hint line); `--scope session` shows this session's file and its own Needs-you items only, `--scope all` adds one `elsewhere` line per other project that has a memo; `--default <scope>` saves a user-wide default (`~/.abofles/config.json`), `- Resume = …` in the override block sets it per project. The guide's owner-decision item follows the same scope.
- **Agent gate**: before the first spawn of a session the plugin asks once — *Auto* (every task sized by topic, side and tier: Minor 2 · Normal 3 · Sensitive 7 · Critical 12 agents in Orchestrator mode, 1 · 2 · 5 · 8 in Worker mode), *This task: N agents* (with the units and $ estimate), *Main session only*, or a number / `off` typed in Other. The hook then denies any spawn over the budget and caps background agents at `Parallel` (default 3), so a session never runs 10+ agents without the user knowing. `Agents = ask | auto | N | off`, `Parallel = M`, `Agent budgets = a, b, c, d` in the override block; `/abofles:agents` mid-session.
- **Guide**: after every receipt and in every resume block the hooks add one `🧭 next →` line — what to do now, by priority (open FAIL/ATTENTION, judged question unasked, owner decisions, unescalated partial/low with the Step 4 setting, background agents, context/memo hygiene, budget, the memo's Next). Advice only; `/abofles:guide`; `Guide = off`. The companion mod `abofles-guide` draws the same line in a band above the prompt box; its buttons are in [plugins/abofles-guide/README.md](../abofles-guide/README.md).
- **Pace**: `Pace = fast` in the override block when speed matters more than control — the direct-read guard waits until 8 reads, questions skip the Judge only while the open task's tier (highest of its spawns and the `main:` line) is Minor/Normal (Sensitive/Critical or unknown tier are still judged), receipts are one line. The hooks cost ~20–30 ms per tool call either way; the time a session spends is in the spawns, so `fast` is about fewer of them.
- **Workflow + specialist reviewers**: the ask's intent (`question` · `review` · `design` · `change`) and the topic's tier pick the steps — a 🟢 fix is Work → Verify, a 🔴 change is Read → Analyse → Plan → Work → Verify → Review. `Review` = the topic group's specialists after Verify passes, in parallel, at the Verify cell: 🛡️ Security, 💰 Finance, 📜 Compliance, 🧪 Tester (the only one that edits — test files), 🎯 QA, 🎨 UIUX (uses the Better Design and UX Pilot connectors when they are connected), 🧹 Clean — Money → Finance (+ Security, Tester at 🔴), Security → Security (+ Tester), Frontend → UIUX (+ QA), Business → QA, Quality/Debugging → Tester, Code Health → Clean, PII/audit topics always add Compliance ([skills/abofles/references/workflow.md](skills/abofles/references/workflow.md)). The **review gate** refuses the receipt of a 🔴 change once when a required reviewer did not run (🟠: a 🟠 guide item); `<Tag> skipped: <reason>` in the receipt's `workflow` line passes it. Agent budgets under `auto` are 2 · 3 · 7 · 12 per tier (orchestrator) to hold them. Overrides: `Reviewers: <Group|Topic> = …`, `Workflow: …`, `Review: <Tag> / T<tier> = cell`, `Review gate = auto | on | warn | off`.
- **Connectors**: the plugin's `.mcp.json` adds four MCP servers — the official Atlassian MCP (`https://mcp.atlassian.com/v2/mcp` — the same Rovo server as the claude.ai connector: Jira, Confluence, Loom, Bitbucket; OAuth on first use), Context7 (`https://mcp.context7.com/mcp` — current library docs), Better Design (`https://better-design.com/api/mcp` — review rules, comprehension and spacing checks, design systems; OAuth) and UX Pilot (`https://mcp-server-485825078314.us-central1.run.app/mcp/ui` — UX review, attention heatmap, persona audit on a design; OAuth). The UI/UX reviewer uses the last two when connected. Remove or rename them in your own settings if you already connect the same servers elsewhere (a second copy only wastes tool slots). The first two fetch-by-key Jira/Confluence reads of a task are free of the direct-read guard. Claude in Chrome is not an MCP server a plugin can bundle: enable it in the Claude app (`/chrome`) and the UI/UX and QA reviewers use its tools when they are present.
- **Question gate**: no `AskUserQuestion` reaches the user before a **Judge** agent has tried to answer it from the code, tests, docs, Jira and the memo (with evidence — the session then states the answer and goes on, logged in the memo), or rewritten it in plain words with each option's consequence, a recommendation and a table/example/diagram when needed. T1–T2: one Sonnet agent judges and explains; T3: Sonnet judges and hands off to an Opus explainer; T4: Opus judges, Opus · High explains. Both write in the user's language, with code names turned into words; a plain explanation goes inside the question text; a table or diagram is printed in the same message right above the question box, where the app shows it; the Stop hook refuses to end a turn while a judged question is unasked; a question asked twice without its table printed above goes through with the explanation put inside the box and the `📖 … printed above` line removed. Re-asking the same round reworded or translated needs no second judge; `Language = Arabic` fixes the question language for a project; gate spawns never count against the agent budget. `Questions = off` disables it.
- Commands: `/abofles:route <task>` (dry run with a cost estimate, no spawns), `/abofles:bill` (units plus the real tokens, $ and savings of this session's subagents), `/abofles:status` (session summary + follow-ups), `/abofles:init` (project override block), `/abofles:memo` (Now section of this session's memo file before a compact), `/abofles:resume` (where was I), `/abofles:agents` (agent gate), `/abofles:guide` (what to do next).
- Escalates only on failure. Never uses ultracode without your approval.

Full matrix: [skills/abofles/references/matrix.md](skills/abofles/references/matrix.md).

Requires `python3` on PATH for the hooks and the bill. Without it the hooks exit silently and the skill still routes — nothing is enforced or logged.

## Layout

```
.claude-plugin/plugin.json   manifest
skills/abofles/              SKILL.md (short routing rules) + references/*.md (loaded on demand)
agents/                      14 agents with fixed reply formats: 7 sides (Read, Analyse, Plan, Work, Verify, Judge, Explain) + 7 specialist reviewers (Security, Finance, Compliance, Tester, QA, UIUX, Clean)
.mcp.json                    bundled connectors: Atlassian (Jira/Confluence), Context7, Better Design, UX Pilot
hooks/                       hooks.json + abofles_hook.py (pre = enforce model/effort + agent budget, post = log + check, stop = background fill-in, guard = direct-read streak, start = session marker + resume block, prompt = effort note + break resume, receipt = receipt enforcement + memo journal + context watch at turn end, decision = question log + gate answer, qgate = question gate, sendmsg = re-ask unlock, edit = where edits land → the memo follows the session's repository)
output-styles/               receipt.md — Receipt style, optional
commands/                    bill.md, route.md, init.md, status.md, memo.md, resume.md, agents.md, guide.md
scripts/                     gen_matrix.py (single source of truth: topics, tiers, workflows, reviewers → topics.md, matrix.md, workflow.md, hooks/workflow.json), bill.py, status.py, memo.py, agents.py, guide.py, test_hooks.py
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
- Use the abofles skill once per session, before the first coding task or subagent (never re-invoke it per task: it stays in context), and tier every task with it.
```

### Updates

Auto-update is off by default for third-party marketplaces. Turn it on once: run `/plugin`, open **Marketplaces**, pick `sajadh92`, choose **Enable auto-update**. Claude Code then installs each new version at startup.

To update by hand instead:

```
/plugin marketplace update sajadh92
```

Then restart Claude Code.

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
- Agent budgets = 2, 3, 7, 12
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

It rewrites the topic index in `skills/abofles/references/topics.md` and regenerates `skills/abofles/references/matrix.md`. Bump `version` in `.claude-plugin/plugin.json` and in the root `.claude-plugin/marketplace.json`.
