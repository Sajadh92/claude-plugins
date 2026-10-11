#!/usr/bin/env python3
"""Abo Fles bill: what the subagents of a session cost, in relative units.

    bill.py                 newest session ledger
    bill.py --all           every ledger
    bill.py --baseline opus·high   compare against this model·effort (default opus·high)
    bill.py --assumed-effort       mark the baseline effort as assumed (session effort unknown)

Cost index = output-price ratio x effort factor. haiku 1, sonnet 20, opus 40,
fable 100 (list price per output token, Haiku = 1). Effort: low 0.5, medium 1,
high 1.5, xhigh 2.5, max 4. Reply length is not known, so one spawn = one unit
of work. These are relative numbers for comparing routes, not dollars.
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
try:
    from abofles_hook import newest_state
except Exception:  # pragma: no cover
    newest_state = lambda: {}

LEDGER_DIR = Path(os.environ.get("ABOFLES_LEDGER_DIR", Path.home() / ".abofles" / "ledgers"))
PRICE = {"haiku": 1, "sonnet": 20, "opus": 40, "fable": 100}
EFFORT = {"low": 0.5, "medium": 1, "high": 1.5, "xhigh": 2.5, "max": 4}
SIDE_FULL = {"R": "Read", "A": "Analyse", "P": "Plan", "W": "Work", "V": "Verify"}
SIDE_ORDER = ["Read", "Analyse", "Plan", "Work", "Verify"]


def cost(model, effort):
    return PRICE.get(model, 40) * EFFORT.get(effort, 1.5)


def load(all_sessions):
    files = sorted(LEDGER_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        return []
    if not all_sessions:
        files = files[-1:]
    rows = []
    for f in files:
        for line in f.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def main():
    args = sys.argv[1:]
    all_sessions = "--all" in args
    baseline = "opus·high"
    if "--baseline" in args:
        baseline = args[args.index("--baseline") + 1]
    assumed = "--assumed-effort" in args
    bm, _, be = baseline.replace("-", "·").partition("·")
    from_session = False
    if not be or assumed:
        se = newest_state().get("effort")
        if se:
            be, assumed, from_session = se, False, True
    baseline = f"{bm}·{be or 'high'}"
    rows = load(all_sessions)
    if not rows:
        print("abofles: no spawns logged yet.")
        return

    by_model = Counter()
    by_side = Counter()
    by_topic = Counter()
    conf = Counter()
    status = Counter()
    verdict = Counter()
    open_fail = {}
    total = 0.0
    for r in rows:
        key = f"{r.get('model') or '?'}·{r.get('effort') or '?'}"
        by_model[key] += 1
        by_side[SIDE_FULL.get(r.get("side") or "?", r.get("side") or "?")] += 1
        by_topic[r.get("topic") or "(no header)"] += 1
        conf[r.get("confidence") or "?"] += 1
        status[r.get("status") or "?"] += 1
        if r.get("verdict"):
            key = r["verdict"] + (" +attention" if r.get("attention") else "")
            if r["verdict"] == "PASS" and open_fail.get(r.get("topic")):
                key = f"PASS (after {open_fail.pop(r.get('topic'))} fix)"
            elif r["verdict"] == "FAIL":
                open_fail[r.get("topic")] = open_fail.get(r.get("topic"), 0) + 1
                continue
            verdict[key] += 1
        total += cost(r.get("model"), r.get("effort"))
    base_total = len(rows) * cost(bm, be or "high")
    saved = 100 * (1 - total / base_total) if base_total else 0

    scope = "all sessions" if all_sessions else "this session"
    print(f"Abo Fles (ابو فليس) — bill for {scope}: {len(rows)} spawn{'' if len(rows) == 1 else 's'}")
    print()
    print("By model·effort:")
    mx = max(by_model.values()) if by_model else 1
    for k, n in by_model.most_common():
        print(f"  {k:<16} {n:>3}  {'█' * max(1, round(20 * n / mx))}")
    print()
    print("By side: " + "  ".join(f"{s} {by_side[s]}" for s in SIDE_ORDER + sorted(k for k in by_side if k not in SIDE_ORDER) if s in by_side))
    print("Status: " + "  ".join(f"{c} {n}" for c, n in status.most_common()))
    print("Confidence: " + "  ".join(f"{c} {n}" for c, n in conf.most_common()))
    for t, n in open_fail.items():
        verdict[f"FAIL (open, {t or 'no topic'})"] += n
    if verdict:
        print("Verdicts: " + "  ".join(f"{c} {n}" for c, n in verdict.most_common()))
    bg = [(r.get("topic") or "?", r.get("side") or "?", w) for r in rows if r.get("completed_ts") and r.get("warnings") for w in r["warnings"]]
    if bg:
        print()
        print("Background spawn warnings (not shown live — the hook stays silent on SubagentStop):")
        for t, sd, w in bg[:10]:
            print(f"  {t} / {sd}: {w}")
    print()
    print("Top topics:")
    for t, n in by_topic.most_common(8):
        print(f"  {n:>3}  {t}")
    print()
    print(f"Cost index: {total:.1f} units" if total < 10 else f"Cost index: {total:,.0f} units")
    print(f"Same spawns all at {baseline}{' (baseline effort assumed — the session effort is not visible)' if assumed else ''}{' (effort read from the session)' if from_session else ''}: {base_total:,.0f} units")
    low_tier = any((r.get("model") in ("haiku", "sonnet")) for r in rows)
    if saved < 0:
        note = f" (T4 spawns ran above the session effort `{be or 'high'}` on purpose — abofles raises effort where money or security is at stake; the saving is in the cheap reads and tests around them)"
    elif saved > 0 or low_tier:
        note = ""
    else:
        note = " (every spawn ran on opus — the saving of abofles is in tier routing; no Read/T1–T2 spawn in this session)"
    print(f"Saved: {saved:.0f}%{note}")


if __name__ == "__main__":
    main()
