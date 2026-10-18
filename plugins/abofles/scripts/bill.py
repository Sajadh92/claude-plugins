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
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
try:
    from abofles_hook import label, newest_state, newest_session_id, usd, fmt_tokens, fmt_usd, PRICE_USD, session_arg
except Exception:  # pragma: no cover
    newest_state = lambda *a, **k: {}
    newest_session_id = lambda *a, **k: ""
    session_arg = lambda argv, keep=False: None
    label = lambda m, e=None: f"{m} · {e}" if e else m
    usd = lambda m, u: 0.0
    fmt_tokens = str
    fmt_usd = lambda x: f"${x:.2f}"
    PRICE_USD = {}

LEDGER_DIR = Path(os.environ.get("ABOFLES_LEDGER_DIR", Path.home() / ".abofles" / "ledgers"))
PRICE = {"haiku": 1, "sonnet": 20, "opus": 40, "fable": 100}
EFFORT = {"low": 0.5, "medium": 1, "high": 1.5, "xhigh": 2.5, "max": 4}
SIDE_FULL = {"R": "Read", "A": "Analyse", "P": "Plan", "W": "Work", "V": "Verify"}
SIDE_ORDER = ["Read", "Analyse", "Plan", "Work", "Verify"]


def cost(model, effort):
    return PRICE.get(model, 40) * EFFORT.get(effort, 1.5)


def load(all_sessions, sess=None):
    if all_sessions:
        files = sorted(LEDGER_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    else:  # this project's session only (state root == cwd), never the newest ledger of another project
        files = []
        for c in (os.environ.get("ABOFLES_SESSION"), sess, newest_session_id(os.getcwd(), sess)):
            c = "" if "${" in (c or "") else re.sub(r"[^A-Za-z0-9_-]", "", c or "")
            if c and (LEDGER_DIR / f"{c}.jsonl").exists():
                files = [LEDGER_DIR / f"{c}.jsonl"]
                break
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
    if args[-2:] == ["--session", ""]:  # a command whose ${CLAUDE_SESSION_ID} expanded to nothing
        del args[-2:]
    sess = session_arg(args)
    all_sessions = "--all" in args
    baseline = "opus·high"
    if "--baseline" in args:
        baseline = args[args.index("--baseline") + 1]
    assumed = "--assumed-effort" in args
    bm, _, be = baseline.replace("-", "·").partition("·")
    from_session = False
    if not be or assumed:
        se = newest_state(os.getcwd(), sess).get("effort")
        if se:
            be, assumed, from_session = se, False, True
    baseline = label(bm, be or "high")
    rows = load(all_sessions, sess)
    if not rows:
        print("abofles: no spawns logged yet." if all_sessions else "abofles: no ledger for this session yet")
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
        key = label(r.get("model") or "?", r.get("effort") or "?")
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
        print(f"  {k:<20} {n:>3}  {'█' * max(1, round(20 * n / mx))}")
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
    print_real_spend(rows, bm)


def print_real_spend(rows, base_model):
    """Real tokens and dollars from the rows that carry them (subagent transcripts), priced at list prices."""
    real = [r for r in rows if r.get("tokens")]
    if not real:
        return
    tokens = sum(r["tokens"] for r in real)
    cost = sum(r.get("usd") or 0 for r in real)
    base = sum(r.get("base_usd") or 0 for r in real)
    saved = base - cost
    print()
    print(f"Real spend ({len(real)} of {len(rows)} spawns had a transcript): {fmt_tokens(tokens)} tokens · {fmt_usd(cost)}")
    print(f"Same tokens on {label(base_model)}: {fmt_usd(base)} · saved {fmt_usd(saved)} ({100 * saved / base:.0f}%)" if base else "")


if __name__ == "__main__":
    main()
