# abofles — ابو فليس

In Iraqi slang, Abo Fles is the stingy guy who counts every fils. This plugin counts every token.

A Claude Code plugin that picks the right model and effort for every subagent, so multi-agent sessions stop running cheap jobs on expensive settings.

- 100 coding topics in 13 groups (security, money, business logic, testing, debugging, code health, architecture, data, integrations, DevOps, frontend, docs, product), each with a risk tier (T1–T4).
- 5 sides per topic: Read & Collect, Analyse & Find Gaps, Plan & Design, Act & Work, Verify & Review.
- Each topic/side cell maps to a model (`haiku`, `sonnet`, `opus`, `fable` — always the latest version) and an effort (`low` … `max`).
- Reply cap per tier and side, so a Read agent on a T1 topic returns 20 lines and an Analyse agent on a T4 topic returns 50 — never cutting a finding to fit.
- 5 side agents (`abofles-reader`, `-analyst`, `-planner`, `-worker`, `-verifier`) with a fixed reply format: `STATUS`, `CONFIDENCE`, then the side's content. Low confidence feeds escalation.
- Two modes by main model: **orchestrator** (opus/fable — the main session only routes and decides; a guard warns when it greps instead of spawning a reader) and **worker** (haiku/sonnet — on the first T3+ task it stops once and offers the switch while the context is still empty).
- Progress line during a chain and a 5-line **receipt** at the end of every task (done · why · spend · check · open follow-ups). Ships an optional **Receipt** output style (fixed line shapes, numbers first, nothing twice) — pick `abofles:Receipt` in the output-style picker.
- `/abofles:status`: spawns per model as bars, confidence, and the open follow-ups from the ledger; `--resolve <id>` closes one.
- Optional `Session cap = N` units in the project override block; the hook says stop-and-ask when passed.
- Knows the session's **effort** (Claude Code passes it to hooks): the skill's `main:` line, `/abofles:bill` and `/abofles:status` use the real level, not an assumed `high`.
- **Context watch**: at 500K, 600K, 700K, 750K, 800K, 850K and 900K tokens of context the hook makes the session print a big, bold "run `/abofles:memo`, then `/compact`" block once per mark — with the opposite advice ("finish the step and the receipt first, do not compact mid-task") while a chain is running. Marks are per project (`Context marks = 100, 150, 180` for a 200K window). `/abofles:memo` writes the hand-off memo (task, done, left, decisions, open, next, verify) to `.claude/abofles-memo.md`.
- A `PreToolUse` hook blocks any subagent spawn that has no `model` or `effort`, or puts Fable on a Read/Work/Verify agent. A `PostToolUse` hook logs every spawn and flags replies that skip the format, pass the cap, or report low confidence; a `SubagentStop` hook completes the ledger for background spawns.
- Commands: `/abofles:route <task>` (dry run with a cost estimate, no spawns), `/abofles:bill` (what this session's subagents cost in relative units, and what was saved), `/abofles:status` (session summary + follow-ups), `/abofles:init` (project override block), `/abofles:memo` (hand-off memo before a compact).
- Escalates only on failure. Never uses ultracode without your approval.

Full matrix: [skills/abofles/references/matrix.md](skills/abofles/references/matrix.md).

Requires `python3` on PATH for the hooks and the bill. Without it the hooks exit silently and the skill still routes — nothing is enforced or logged.

## Layout

```
.claude-plugin/plugin.json   manifest
skills/abofles/              the routing skill + references/matrix.md
agents/                      5 side agents with fixed reply formats
hooks/                       hooks.json + abofles_hook.py (pre = enforce, post = log + check, stop = background fill-in, guard = direct-read streak + context watch, prompt = context watch, receipt = receipt enforcement)
output-styles/               receipt.md — Receipt style, optional
commands/                    bill.md, route.md, init.md, status.md, memo.md
scripts/                     gen_matrix.py (single source of truth), bill.py, status.py, test_hooks.py
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

route: Pricing, Fees, Commission & Tax / Plan → opus·xhigh · cap 150 (T4)
abofles [■□□□] 1/4 · Plan ✓ · Work ▶ · Work · Verify · 100 u
route: Pricing, Fees, Commission & Tax / Work → opus·high · cap 40 (T4)
abofles [■■□□] 2/4 · Plan ✓ · Work ✓ · Work ▶ · Verify · 160 u
route: Unit Test / Work → sonnet·medium · cap 20 (T2)
abofles [■■■□] 3/4 · Plan ✓ · Work ✓ · Work ✓ · Verify ▶ · 180 u
route: Financial & Amount Calculations / Verify → opus·high · cap 60 (T4)

── receipt ──────────────────────────
done   AqsatiRules.cs: SurchargeCapIqd = 5,000, Surcharge() clamps; AqsatiRulesTester.cs: 3 cap tests
why    money topic → T4 plan/work/verify, tests are T2 → sonnet
spend  4 spawns · 240 u · saved 0% — T4 chain, saving is in the tier routing
check  dotnet test TestLab/TestLab.csproj → total 13, failed 0
open   ATTENTION: cap applies in order currency — USD orders uncapped (OrderPricingRules.cs:77)
```

A read-only question on the same project routes to `haiku·low` (0.5 u instead of 60): that is where the saving comes from. `/abofles:route <task>` shows the plan and the estimate without spawning anything; `/abofles:bill` shows what the session cost afterwards.

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
```

Sides are always written in full: Read, Analyse, Plan, Work, Verify.

## Add or change a topic

Everything lives in `scripts/gen_matrix.py`: topics, tiers, cell overrides, reply caps and keyword signals. Reply formats live in `agents/*.md`, one file per side. Edit it, then run:

```
python3 scripts/gen_matrix.py
```

It rewrites the topic index in `skills/abofles/SKILL.md` and regenerates `skills/abofles/references/matrix.md`. Bump `version` in `.claude-plugin/plugin.json` and in the root `.claude-plugin/marketplace.json`.
