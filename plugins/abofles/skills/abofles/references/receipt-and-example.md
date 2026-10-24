# Receipt details and example

Read when printing a receipt or a progress line, estimating cost units, or to see a full routed task.

Cost units (`u`) = model price × effort factor: haiku 1 · sonnet 20 · opus 40 · fable 100, times low 0.5 · medium 1 · high 1.5 · xhigh 2.5 · max 4 (haiku·low = 0.5 u, sonnet·medium = 20 u, opus·high = 60 u, opus·xhigh = 100 u). Every step down pays.

Between spawns print nothing but the route line and, when a chain of 2+ spawns runs, one progress line reprinted only when it changes:

```
abofles [■■■□□] 3/5 · Plan ✓ · Work ✓ · Work ▶ · Verify · 142 u
```

At the end of every task that spawned agents, print the receipt as **plain markdown — never inside a code block** — five lines, this order, nothing after it except what the user asked for:

🧾 **4 Spawns + 2 gate · 2.1M Tokens · $1.12 · Saved 71% ($2.74)** vs Opus 5.5
- `done` → <what changed, one line, files named>
- `why` → <the reason or rule that drove it, one line>
- `check` → <the command that proves it → its decisive result>
- `workflow` → <🟠/🔴 changes only: `Read ✓ · Analyse ✓ · Plan ✓ · Work ✓ · Verify ✓ · Finance ✓ · Security ✓ · Tester skipped: <reason>` — every step and reviewer of the workflow line, done or skipped with its reason; the review gate reads the skipped ones>
- `open` → <follow-ups — or "none">
- `next` → 🧭 <the guide line the hook hands you — copy it as given>

**The guide line.** The hook computes `🧭 …` from the ledger, the memo, the state and the context size — a priority ladder: 🔴 open FAIL/ATTENTION · 🟠 judged question unasked, owner decisions open · 🟡 partial/low reply not escalated (with the Step 4 setting) · ⏳ background agents running · 🧠 context near a mark, memo Now stale · 💰 budget nearly out · ✅ the memo's Next. It is advice: copy it, then decide; the user sees the same line in the resume block (`guide`) and in the band above the prompt when the `abofles-guide` mod is installed. `/abofles:guide [--all]` prints it on demand; `- Guide = off` removes it. The band never resolves an item: Re-check fills a verify-then-resolve prompt (look at code, state, PRs and tests first; resolve with `--trace "re-checked: <evidence>"`), and an owner's-call item goes to AskUserQuestion with the answer as the trace; Undo reopens your last resolve until the next turn ends.

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
