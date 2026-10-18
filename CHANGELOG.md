# Changelog

All notable changes to the plugins in this marketplace.

## abofles 1.5.2 — 2026-10-19

- Docs: the READMEs now say how to turn on auto-update for the `sajadh92` marketplace (off by default for third-party marketplaces) and how to update by hand.

## abofles 1.5.1 — 2026-10-19

- abofles: `memo.py now` (what `/abofles:memo` runs) prints the session file it wrote, `.claude/abofles-memo.d/<session>.md`, not the main memo path — as the command's reply line says.

## abofles 1.5.0 — 2026-10-19

- abofles: the memo is split — the main `.claude/abofles-memo.md` keeps only what must not be missed (Needs you, notes, a Sessions index with one link line per session: last update, task, next, receipts), and each session writes its own `.claude/abofles-memo.d/<session>.md` (Now, Journal, its questions and answers). A receipt rewrites one small file plus one index line instead of the whole memo; the resume block and the guide read this session's file plus the main memo; `show --all` prints the main memo and this session's file only (`--main`: the main memo). A pre-1.5 one-file memo is split on its first read; the git exclude already covers the folder.

## abofles 1.4.0 — 2026-10-19

- abofles: harness notes (`[harness: …]` blocks) are no longer graded as part of an agent's reply, so they no longer trigger length or format warnings.
- abofles: when the hand-back of a background agent is a stub ("Understood."), the reply is read from the agent's own transcript and graded from there.
- abofles: the question gate unlocks only on a real `VERDICT:` (judge) or `QUESTION:` (explainer; `EXPLAIN` optional) line; a stub reply leaves it locked and says so.
- abofles: only `abofles-judge` and `abofles-explainer` (or a spawn whose header side is Judge/Explain) are gate agents; a project agent named like one no longer unlocks questions. A `SendMessage` unlocks only for the ids or names of gate agents spawned this session.
- abofles: an unlock made before the open task began, or older than the gate wait with no gate agent running, is dropped instead of demanding a question nobody asked.
- abofles: a pending background row with no agent id or transcript for 30 minutes closes as lost; a pending row from an earlier task is no longer shown as running.
- abofles: `run_in_background: true` is treated as async even when the tool result looks complete.
- abofles: a task closes only on a printed receipt. A spent nudge keeps the task open (count, budget and gate answer stay; the next Stop asks again); with receipts off, the task closes at the next real user prompt, not on a task-notification turn.
- abofles: a turn whose last line ends with `?` gets no receipt nudge — the task waits on the user.
- abofles: a compact or a resume keeps the open task; only a new session or `/clear` resets it.
- abofles: a receipt counts only as the computed header line (`🧾 **N Spawns …`); a quoted 🧾 or the words `── receipt` no longer close the task.
- abofles: `/abofles:agents`, `guide`, `memo`, `bill` and `status` act on the session you type in — `ABOFLES_SESSION`, else the command's own `--session ${CLAUDE_SESSION_ID}`, else the newest prompt among this folder's sessions — never a session of another project (`status.py` and `bill.py` no longer fall back to the newest ledger of any project: with none for this session they say so and show no spend); `--resolve` acts on the same ledger the display shows; an empty `--session ""` from a command is ignored.
- abofles: the first two fetch-by-key connector reads of a task (`getJiraIssue`, `getConfluence*`, `get*Page`) do not count toward the direct-read warning; searches and lists still count.
- abofles: Judge and Verifier are told that ticket and page text comes in the prompt (they cannot reach Jira); a missing one is reported as `ticket text not given`, and the skill tells the main session to paste the key fields into their prompt.
- abofles: a receipt still owed when a turn ends is carried to the next turn's Stop.
- abofles: the free connector reads (first two fetch-by-key per task) reset at the first real user prompt with no open task.
- abofles: ledger rows record `how` (where the graded text came from: hint, transcript, stub, no_reply, lost) and `gate` (judge / explain) for the scripts.
- abofles: a row closed as lost is graded again when the background reply arrives late.
- abofles: a session that runs an old plugin cache copy while a newer one is installed gets one warning line, once per session, to restart Claude Code.

## abofles 1.3.0 · abofles-guide 0.3.0 — 2026-10-15

- abofles: after an agent-budget deny, one `AskUserQuestion` (raise the budget?) within 10 min goes to the user with no Judge — the budget question no longer needs a gate spawn; the deny text says so.
- abofles: after every receipt the hook rewrites this session's memo Now block (Task `none — between tasks`, Done/Left/Next/Verify from the receipt, Decisions kept, Tree from git status; `· from receipt`); `/abofles:memo` still writes a richer one.
- abofles: guide items carry a stable `id` (`fail:<agent>`, `dec:<n>`, `ctx:<mark>` …), the key for the band's hide and arm state; `next_setting` caps: Work/Verify stop at `opus·xhigh` except T4 (`opus·max`), and the 🟡 item says stop and report when no step is left.
- abofles: explanation-gate fixes — `SendMessage` re-ask unlock, background judge, multi-`VERDICT` capture, fenced `EXPLAIN`, stale `explain_prev`, `EXPLAIN` cut at a blank line.
- abofles: ledger rewrite locked and atomic; old lock files pruned; `prompt_dirs` paths with spaces; `/abofles:resume` `last` skips trace lines.
- abofles: `status.py` / `memo.py` validate arguments (exit 2) and exit 3 when the item is already resolved / not resolved (no trace written); `memo.py resolve|reopen --session <sid>`.
- abofles: `Pace = fast` judges by the open task's tier (spawns and `main:` line): skipped only for T1–T2, T3–T4 or unknown still judged; overrides are read only from the `## abofles overrides` block.
- abofles-guide: running guard, arm expiry, one toast per new red item, safer state reads, more tests.
- docs: broken `topics.md` link, root README lists abofles-guide, Receipt style `next` bullet, question-gate box vs. markdown `EXPLAIN`, command flags and exit codes, route `main:` form, worker `LEFT` rule.
- abofles-guide: a 🔴 open FAIL or ATTENTION gets **Re-check** instead of Resolve — it fills a prompt to run only the failed criterion and resolve the row only if it passes; nothing is closed on trust. **Resolve** (🟡 escalate, 🟠 owner decision) asks twice: the first press arms it as `Confirm resolve` for 5 s. After a resolve the band shows `✓ resolved: …` with **Undo** until the turn ends.
- abofles: a question whose explanation needs markdown can no longer reach the user without it. The hook hands the model the Explainer's own block to print verbatim, then checks the transcript when the question is asked and refuses it once if no explanation was printed — on the first ask and on a re-ask. Seen twice in DCMP on 2026-10-14: the model announced the table in its thinking only.
- abofles: each guide item carries `recheck` and `unresolve`; `status.py --unresolve <id>`, `memo.py reopen <n>`; `--trace` on resolve and reopen writes one `resolved by hand` / `reopened by hand` line in the memo Journal, shown in the resume block (not counted as a receipt). The guide is recomputed on every prompt and right after a receipt adds owner decisions, so the band never lags a turn.

## abofles 1.2.0 · abofles-guide 0.2.0 — 2026-10-14

- abofles: `SKILL.md` cut from 43 KB to 12 KB (about 8K fewer tokens per load); topic index, overrides, question gate, memo/guide, spawn details and the worked example moved to `references/*.md`, read on demand. `gen_matrix.py` writes the index to `references/topics.md`; `--check` added.
- abofles: injected hook texts about 30% shorter (receipt, guard, context watch, question and agent gates, resume preamble); a background launch no longer repeats the receipt instruction (the Stop hook asks for it when the chain ends).
- abofles: the stored guide carries an action per item (`fill` for the band's Use button, `resolve` argv), the context size against the next mark, the open task's spawns/cost/budget and the `main:` suggestion. `status.py --resolve <id> --session <sid>`.
- abofles: `status.py --resolve` and `memo.py resolve` exit 1 when nothing was resolved; the band's Resolve runs them with the hook's own Python; the question-gate text no longer claims a transcript check that does not exist; skill and `/abofles:route` quote the hook's current effort and `main:` lines.
- abofles: a reader's cited paths also resolve from absolute folders the spawn prompt names (a worktree outside the session's project root was falsely downgraded to `low` in the live test); the 🟡 escalate prompt names the agent; resolving an already-resolved row says so.
- abofles-guide: band hidden when nothing is open; Use fills the exact action for the top item; Resolve button settles a stale FAIL or a decided owner item in one click; Memo button near a context mark; the 🔴 toast fires again (its check cut the emoji in half); dim meter line (`ctx 412K / 500K · task 3 spawns · $0.41 · budget 2 left · suggest …`).

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
