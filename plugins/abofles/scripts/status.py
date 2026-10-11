#!/usr/bin/env python3
"""Abo Fles session status: where the spend went, what is still open.

    status.py                       newest session ledger
    status.py --all                 every ledger
    status.py --resolve <agent_id>  mark one follow-up resolved (prefix match)
    status.py --baseline opus·high  compare against this model·effort (default opus·high)

Follow-ups = ledger lines with status partial/blocked, confidence low, an
ATTENTION note, or a FAIL verdict not followed by a PASS on the same topic —
and not yet marked resolved.
"""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
try:
    from abofles_hook import context_tokens, context_marks, newest_transcript, newest_state
except Exception:  # pragma: no cover
    context_tokens = context_marks = newest_transcript = None
    newest_state = lambda: {}

LEDGER_DIR = Path(os.environ.get("ABOFLES_LEDGER_DIR", Path.home() / ".abofles" / "ledgers"))
PRICE = {"haiku": 1, "sonnet": 20, "opus": 40, "fable": 100}
EFFORT = {"low": 0.5, "medium": 1, "high": 1.5, "xhigh": 2.5, "max": 4}
SIDE_FULL = {"R": "Read", "A": "Analyse", "P": "Plan", "W": "Work", "V": "Verify"}


def cost(model, effort):
    return PRICE.get(model, 40) * EFFORT.get(effort, 1.5)


def ledger_files(all_sessions):
    files = sorted(LEDGER_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files if all_sessions else files[-1:]


def load(files):
    out = []
    for f in files:
        rows = []
        for line in f.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        out.append((f, rows))
    return out


def follow_ups(rows):
    open_fail = {}
    items = []
    for i, r in enumerate(rows):
        if r.get("resolved"):
            continue
        why = []
        if r.get("status") in ("partial", "blocked"):
            why.append(f"status {r['status']}")
        if r.get("confidence") == "low":
            why.append("confidence low")
        if r.get("attention"):
            why.append("ATTENTION note")
        if r.get("verdict") == "FAIL":
            open_fail[r.get("topic")] = i
            why.append("VERDICT FAIL")
        if r.get("verdict") == "PASS" and r.get("topic") in open_fail:
            j = open_fail.pop(r.get("topic"))
            items = [it for it in items if it[0] != j]
        if r.get("status") == "pending":
            why.append("still pending (background reply never arrived?)")
        if why:
            items.append((i, r, why))
    return items


def bar(n, width=20, total=None):
    total = total or n or 1
    return "█" * max(1, round(width * n / total)) if n else ""


def main():
    args = sys.argv[1:]
    all_sessions = "--all" in args
    baseline = args[args.index("--baseline") + 1] if "--baseline" in args else "opus·high"
    bm, _, be = baseline.replace("-", "·").partition("·")
    if not be or "--assumed-effort" in args:
        be = newest_state().get("effort") or be
    baseline = f"{bm}·{be or 'high'}"
    files = ledger_files(all_sessions)
    if not files:
        print("abofles: no spawns logged yet.")
        return

    if "--resolve" in args:
        key = args[args.index("--resolve") + 1]
        f = files[-1]
        rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        hit = [r for r in rows if (r.get("agent_id") or "").startswith(key)]
        if not hit:
            print(f"abofles: no follow-up with agent id starting '{key}' in {f.name}")
            return
        for r in hit:
            r["resolved"] = True
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        print(f"abofles: resolved {len(hit)} entr{'y' if len(hit) == 1 else 'ies'} ({key}…)")
        return

    rows = [r for _, rs in load(files) for r in rs]
    by_model = Counter((r.get("model") or "?") for r in rows)
    by_side = Counter(SIDE_FULL.get(r.get("side") or "?", r.get("side") or "?") for r in rows)
    conf = Counter((r.get("confidence") or "?") for r in rows)
    total = sum(cost(r.get("model"), r.get("effort")) for r in rows)
    base = len(rows) * cost(bm, be or "high")
    scope = "all sessions" if all_sessions else "this session"

    units = f"{total:.1f}" if total < 10 else f"{total:,.0f}"
    print(f"Abo Fles (ابو فليس) — status, {scope}: {len(rows)} spawn{'' if len(rows) == 1 else 's'} · {units} u · saved {100 * (1 - total / base):.0f}% vs all-{baseline}")
    if context_tokens and not all_sessions:
        tp = newest_transcript()
        tk = context_tokens(str(tp)) if tp else None
        if tk is not None:
            marks = context_marks(os.getcwd())
            nxt = next((m for m in marks if tk < m * 1000), None)
            print(f"Context:    {tk // 1000}K tokens · " + (f"next compact warning at {nxt}K" if nxt else "past the last mark — run /abofles:memo, then /compact"))
    print()
    print("Spawns per model")
    mx = max(by_model.values()) if by_model else 1
    for m in ("haiku", "sonnet", "opus", "fable"):
        if by_model.get(m):
            print(f"  {m:<7}{bar(by_model[m], 24, mx)} {by_model[m]}")
    print()
    print("Sides:      " + "  ".join(f"{s} {by_side[s]}" for s in ("Read", "Analyse", "Plan", "Work", "Verify") if by_side.get(s)))
    print("Confidence: " + "  ".join(f"{c} {n}" for c, n in conf.most_common()))
    pend = sum(1 for r in rows if r.get("status") == "pending")
    if pend:
        print(f"Pending:    {pend} background spawn(s) not yet filled")
    print()
    fu = follow_ups(rows)
    if fu:
        print(f"Open follow-ups ({len(fu)}) — resolve with: /abofles:status --resolve <id>")
        for i, r, why in fu:
            aid = (r.get("agent_id") or f"row{i}")[:8]
            print(f"  ⚠ {aid}  {r.get('topic') or '?'} / {SIDE_FULL.get(r.get('side') or '?', r.get('side') or '?')} — {', '.join(why)}")
    else:
        print("Open follow-ups: none")


if __name__ == "__main__":
    main()
