# Changelog

All notable changes to the plugins in this marketplace.

## abofles 1.1.0 · abofles-guide 0.1.0 — 2026-10-14

- Receipt: header computed by the hook from each subagent's transcript — `🧾 **N Spawns · T Tokens · $C · Saved P% ($S)** vs <main Model>` — then `done / why / check / open` as inline-code tags; `Receipt = full | short | savings N | off`. Usage deduplicated by message id; `/abofles:bill` and `/abofles:status` print the real spend.
- Context watch moved to the Stop hook: the block is the last thing in the turn, never at the start of a prompt.
- Display names as in the Claude app (`Opus 5.5 · High`, `Extra` for xhigh); route lines as `<emoji> \`Side\` → **Topic** · Model · Effort · Cap N · 🟢/🟡/🟠/🔴 Tier · Modifier`.
- Work memo (`.claude/abofles-memo.md`): journal line per receipt, **Needs you** list (ATTENTION, FAIL, owner decisions), every `AskUserQuestion` with its answer; resume block after `/compact`, at session start and after `Break` minutes away (default 10); `/abofles:resume`.
- Agent gate: asked once per session (Auto / This task: N / Main session only / Max or Switch-to-Opus) or set by `Agents = ask | auto | N | off`; the hook denies spawns over the budget and caps background agents at `Parallel` (default 3); `/abofles:agents`. Replaces the Low-model stop.
- Question gate: no `AskUserQuestion` before a Judge agent (T1–T2 judges and explains; T3 Sonnet → Opus Explainer; T4 Opus → Opus · High) answered it from evidence or rewrote it with consequences; `Questions = judge | off`. Two new agents: `abofles-judge`, `abofles-explainer`.
- Reader agent gets a read-only shell (`git show`, `gh`, grep); reply-format checks only on abofles agents; receipt nudge waits for background agents.
- Overrides also read from `~/.claude/CLAUDE.md`. Hook unit tests: 200+.
- Field-test fixes (DCMP session 5aa36499): memo, lock and overrides follow the project root the session started in, never a `cd` (a stray `.claude/abofles-memo.*` in a nested team repo was one `git add -A` from a commit); the memo is added to `.git/info/exclude`, the lock lives under `~/.abofles`. Receipt closes the task even while a background agent runs; answering the gate again restarts the budget count; gate spawns shown as `+ N gate` and never counted; a prompt without the abofles header is flagged (tier unknown). Question gate: WHY/EXPLAIN go inside the question text; Judge/Explainer write in the user's language with code names glossed; a reworded re-ask or a `SendMessage` to the gate agent passes without a second judge; dismissed questions are not decisions; Decisions keep the question sentence; an answered question ticks its Needs-you item; near-duplicate items deduplicated. Haiku 5.5 priced at $1 / $1.25 / $0.10 / $5 per MTok (was a tenth of that). Resume block: every `Left` line, the Now section's age and a `since` line when receipts came after it, no mid-word cuts. Read guard: shell appends, `wc`, `tail` are not reads; connector lookups (Jira) are. `STATUS: partial` with `GAPS/LEFT: none` is treated as done; cited paths resolved from the workspace root and sibling repos; Judge/Explainer replies no longer nagged about line length or absolute paths; the spawn-count nudge fires at 20/50/100/200 only.
- Receipt and resume block: a field with 2+ items is written as indented sub-bullets (one idea per line) instead of a long `;`/`·` line; the hooks parse both shapes. Resume `away`/age shown as days, hours, min.
- Question gate: a plain EXPLAIN goes inside the question as one line per option (the AskUserQuestion box renders raw characters); a markdown EXPLAIN (table, diagram, example) is printed in the same message right above the question under `📖 Explanation for the question below`, with a plain summary and a pointer inside. The Stop hook refuses to end a turn while a judged question is unasked (not while a gate agent is still replying). A judge reply with several VERDICT blocks is read block by block (HANDOFF/ASK win over ANSWERED, every ANSWERED is logged). Re-asks within 15 minutes (translations) pass; `Language = Arabic` override.
- Guide: a hook-computed `🧭 next →` line (priority ladder: open FAIL/ATTENTION, judged question unasked, owner decisions, unescalated partial/low with the next Step 4 setting, background agents, context/memo hygiene, budget, the memo's Next) in every receipt and resume block; `/abofles:guide`, `Guide = off`. Companion mod `abofles-guide` (band above the prompt with `Use` / `Copy` / `Hide` buttons — a hidden band returns only when the ladder's priorities change — 🔴 toast) added to the marketplace. Guide FAIL/ATTENTION items are scoped to the open task (earlier tasks close with their receipt; `/abofles:status --resolve <id>` closes one by hand — its `NameError` fixed).
- Receipt header names the dominant spawn (`largest: Work Opus 5.5 · High $11.00 (69%)`) when one spawn is half the cost or more.
- Question text is QUESTION + WHY only; options live in the option cards and are never restated in the text.
- Field-test round 2 (DCMP sessions 1–5): per-session Now blocks, session-tagged journal and Needs-you lines, session-aware resume block; receipts printed mid-turn close their task at the next spawn (budget and header restart per ticket); cited paths resolved from the project root two folder levels deep, `.../x.cs` abbreviations ignored; judge/explainer replies never trigger the escalation nag; `main:` line handed at the first work spawn of every task (model read first); no resume block on task-notification turns; header shows `N running` background spawns and no saving for gate-only tasks; `Language` override; skill line limit aligned to 200 chars.
- Step 0 `main:` line computed by the hook at each task's first work spawn (fits or suggest, from the session's real model and effort) and handed to the model — it was skipped when a resume block opened the reply.
- `Pace = normal | fast` override: `fast` raises the direct-read guard marks to 8/16/32/64, lets 🟢/🟡 questions skip the Judge and defaults the receipt to `short` — for users who found the plugin slower than working without it (hook latency measured at 20–30 ms per tool call; the time is in the spawns).

## abofles 1.0.0 — 2026-10-11

First release.

- Routing matrix: 100 coding topics in 13 groups, 4 risk tiers, 5 sides (Read, Analyse, Plan, Work, Verify) → model (haiku / sonnet / opus / fable) + effort (low … max) + reply cap.
- Five side agents with fixed reply formats; a `PostToolUse` hook checks every reply (caps, long lines, absolute paths, trailing text, false `done`, bad paths) and feeds escalation.
- `PreToolUse` hook blocks any spawn without `model` and `effort`, or Fable on a Read / Work / Verify agent.
- Escalation only on failure; verifier `FAIL` → fix in the main session, re-verify the failed criterion only; `ATTENTION` notes are never closed silently.
- Session ledger (`~/.abofles/ledgers`), background spawns completed on `SubagentStop`.
- Main-session modes: orchestrator (opus / fable, direct-read guard) and worker (haiku / sonnet, one manual-switch stop on the first T3+ task).
- Session effort read from the hook input; used by the `main:` line, `/abofles:bill` and `/abofles:status`.
- Progress line and 5-line receipt (`done / why / spend / check / open`), enforced by a `Stop` hook; optional `Receipt` output style.
- Context watch: one bold block per mark (500K, 600K, 700K, 750K, 800K, 850K, 900K tokens; `Context marks` override) with both compact advices; `/abofles:memo` writes the hand-off memo.
- Commands: `/abofles:route`, `/abofles:bill`, `/abofles:status`, `/abofles:init`, `/abofles:memo`.
- Project overrides in `CLAUDE.md`: cell, tier, cap, main session, session cap, context marks.
- 84 hook unit tests (`scripts/test_hooks.py`); 17 live test runs on a .NET project, average saving ≈ 33 % vs all-opus.
