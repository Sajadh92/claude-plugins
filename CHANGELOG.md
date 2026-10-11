# Changelog

All notable changes to the plugins in this marketplace.

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
