#!/usr/bin/env python3
"""Abo Fles hooks for the Agent tool.

    abofles_hook.py pre   -- PreToolUse:   block a spawn with no model/effort
    abofles_hook.py post  -- PostToolUse:  log the spawn; check the reply (sync) or log `pending` (async)
    abofles_hook.py stop  -- SubagentStop: fill the pending async entry from last_assistant_message (ledger only, prints nothing)
    abofles_hook.py guard   -- PreToolUse(Read|Grep|Glob): orchestrator guard — too many direct reads in a row
    abofles_hook.py start   -- SessionStart: write the session marker the guard gates on
    abofles_hook.py receipt -- Stop: refuse the stop once when the turn spawned agents and no receipt was printed
    abofles_hook.py prompt   -- UserPromptSubmit: effort note; resume block after a break (`Break = N` minutes)
    abofles_hook.py decision -- PostToolUse(AskUserQuestion): log the question + answer to the memo; parse the agent-gate answer
    abofles_hook.py qgate    -- PreToolUse(AskUserQuestion): deny a question no Judge/Explainer has seen (a re-ask of the same round passes)
    abofles_hook.py sendmsg  -- PostToolUse(SendMessage): a message to a Judge/Explainer unlocks one question
    abofles_hook.py tokens   -- CLI: print the context size of the newest session transcript (no stdin)

The context watch runs only in `receipt` (Stop): a passed mark refuses the stop once so the block is the last thing
the user sees in the turn; one send per mark, never re-sent, marks re-arm after a compact. The block carries both
advice branches; the model picks. `receipt` also journals every printed receipt into the memo, enforces the receipt,
expires a per-task agent-gate answer, and closes the task. Real tokens and dollars come from each subagent's own
transcript (`<transcript dir>/<session_id>/subagents/agent-<id>.jsonl`, usage deduplicated by message id).
Hooks fired inside a subagent (agent_id in the input, or an `agent-*`
transcript) never touch the guard streak or the context watch — their output would go to the subagent.
Debug: `touch ~/.abofles/debug` makes every hook append its input keys to `~/.abofles/debug.log`. Marks come from `- Context marks = 500, 600, ...` (thousands of
tokens) in the project's `## abofles overrides` block, else the defaults above.

Reads the hook JSON on stdin. Never raises: a broken hook must not block work.
"""
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

MODELS = {"haiku", "sonnet", "opus", "fable"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
NO_FABLE = ("abofles-reader", "abofles-worker", "abofles-verifier")
SIDE_FULL = {"R": "Read", "A": "Analyse", "P": "Plan", "W": "Work", "V": "Verify", "J": "Judge", "E": "Explain"}
LEDGER_DIR = Path(os.environ.get("ABOFLES_LEDGER_DIR", Path.home() / ".abofles" / "ledgers"))
STATE_DIR = Path(os.environ.get("ABOFLES_STATE_DIR", Path.home() / ".abofles" / "state"))
PRICE = {"haiku": 1, "sonnet": 20, "opus": 40, "fable": 100}
EFFORT = {"low": 0.5, "medium": 1, "high": 1.5, "xhigh": 2.5, "max": 4}


# How the Claude app names them — use in every line shown to the user. Agent call params stay lowercase.
MODEL_LABEL = {"haiku": "Haiku 5.5", "sonnet": "Sonnet 5.5", "opus": "Opus 5.5", "fable": "Fable 5.1"}
EFFORT_LABEL = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra", "max": "Max"}


def label(model, effort=None):
    """`opus`, `xhigh` -> `Opus 5.5 · Extra`; unknown names are capitalised as they are."""
    m = MODEL_LABEL.get((model or "").lower(), (model or "?").capitalize())
    return f"{m} · {EFFORT_LABEL.get((effort or '').lower(), effort.capitalize())}" if effort else m


# List price per million tokens (Claude API, 2026-10): input, cache write (1.25x input), cache read, output.
PRICE_USD = {"haiku": (1.0, 1.25, 0.10, 5.0), "sonnet": (2.0, 2.5, 0.20, 10.0), "opus": (4.0, 5.0, 0.20, 20.0), "fable": (10.0, 12.5, 0.25, 50.0)}
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


EXPLAIN_MARK = "📖"  # heads a markdown explanation printed above a question
TIER_NAME = {1: "🟢 Minor", 2: "🟡 Normal", 3: "🟠 Sensitive", 4: "🔴 Critical"}


def tier_name(t):
    return TIER_NAME.get(t or 2, f"T{t}")


def alias_of(model_id):
    """`claude-opus-5-5` -> `opus`; an alias passes through; unknown -> None."""
    m = (model_id or "").lower()
    return next((a for a in PRICE_USD if a in m), None)


def usd(model, usage):
    """Dollar cost of a usage dict at `model`'s list prices (0 when the model is unknown)."""
    pr = PRICE_USD.get(alias_of(model) or "")
    if not pr or not usage:
        return 0.0
    return sum(usage.get(k, 0) * pr[i] for i, k in enumerate(USAGE_KEYS)) / 1_000_000


def transcript_usage(path):
    """Sum the usage of every assistant message in a (sub)agent transcript. None when the file is missing/empty."""
    tot = dict.fromkeys(USAGE_KEYS, 0)
    calls, model = 0, None
    seen = set()  # one API message is written as several lines (thinking, text, tool_use) that repeat its usage
    try:
        with open(path, "rb") as f:
            for raw in f:
                if b'"usage"' not in raw:
                    continue
                try:
                    r = json.loads(raw)
                except Exception:
                    continue
                if r.get("type") != "assistant":
                    continue
                u = (r.get("message") or {}).get("usage") or {}
                if not u:
                    continue
                mid = (r.get("message") or {}).get("id")
                if mid is not None:
                    if mid in seen:
                        continue
                    seen.add(mid)
                calls += 1
                model = (r.get("message") or {}).get("model") or model
                for k in USAGE_KEYS:
                    tot[k] += int(u.get(k) or 0)
    except Exception:
        return None
    if not calls:
        return None
    tot["total"] = sum(tot[k] for k in USAGE_KEYS)
    tot["calls"] = calls
    tot["model"] = model
    return tot


def agent_transcript(st, session_id, agent_id):
    """`<transcript dir>/<session_id>/subagents/agent-<id>.jsonl` — where Claude Code keeps a subagent's transcript."""
    known = (st.get("agent_transcripts") or {}).get(agent_id)
    if known:
        return Path(known)
    main = st.get("transcript_path") or ""
    if not main or not agent_id:
        return None
    return Path(main).parent / session_id / "subagents" / f"agent-{agent_id}.jsonl"


def main_model(transcript_path):
    """Alias of the model of the newest main-thread assistant message, or None."""
    for line in reversed(transcript_tail(transcript_path)):
        if '"model"' not in line or '"assistant"' not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") == "assistant" and not r.get("isSidechain"):
            a = alias_of((r.get("message") or {}).get("model"))
            if a:
                return a
    return None


def add_spend(st, session_id, agent_id, model, what=""):
    """Read the subagent's transcript and add its real tokens and cost to the task. Returns the usage fields for the ledger."""
    path = agent_transcript(st, session_id, agent_id)
    u = transcript_usage(path) if path else None
    if not u:
        st["task_unpriced"] = st.get("task_unpriced", 0) + 1  # no transcript: this spawn is missing from the $ figures
        return {}
    base_model = st.get("main_model") or "opus"
    cost, base = usd(u.get("model") or model, u), usd(base_model, u)
    st["task_tokens"] = st.get("task_tokens", 0) + u["total"]
    st["task_usd"] = st.get("task_usd", 0.0) + cost
    st["task_base_usd"] = st.get("task_base_usd", 0.0) + base
    if cost > (st.get("task_top") or {}).get("usd", 0.0):
        st["task_top"] = {"usd": cost, "what": what or label(u.get("model") or model)}  # the costliest spawn of the task, named in the header when it dominates
    return {"tokens": u["total"], "calls": u["calls"], "usd": round(cost, 4), "base_usd": round(base, 4), "resolved_model": u.get("model")}


def fmt_tokens(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}K" if n >= 1000 else str(n)


def fmt_usd(x):
    return "<$0.01" if 0 < x < 0.005 else f"${x:,.2f}"


def units(model, effort):
    return PRICE.get(model or "", 40) * EFFORT.get(effort or "", 1.5)


USER_CLAUDE_MD = Path(os.environ.get("ABOFLES_USER_CLAUDE_MD", Path.home() / ".claude" / "CLAUDE.md"))


def override_value(cwd, key):
    """`- <key> = <value>` in the project's CLAUDE.md, else in the user's ~/.claude/CLAUDE.md, or None."""
    for path in (Path(cwd) / "CLAUDE.md", Path(cwd) / ".claude" / "CLAUDE.md", USER_CLAUDE_MD):
        try:
            txt = path.read_text()
        except Exception:
            continue
        m = re.search(r"^\s*-\s*" + re.escape(key) + r"\s*=\s*(.+?)\s*$", txt, re.M | re.I)
        if m:
            return m.group(1)
    return None


def session_cap(cwd):
    """`- Session cap = N`, or None."""
    v = override_value(cwd, "Session cap")
    m = re.match(r"(\d+)", v or "")
    return int(m.group(1)) if m else None


def pace(cwd):
    """`- Pace = fast | normal` (default normal). Fast trades some control for speed: the direct-read guard speaks at
    8/16/32/64 instead of 4/8/16/32, 🟢 Minor and 🟡 Normal questions skip the Judge, and the receipt is the one-line form
    unless `Receipt` says otherwise. Hooks themselves cost ~20–30 ms per tool call in either pace."""
    v = (override_value(cwd, "Pace") or os.environ.get("ABOFLES_PACE") or "normal").strip().lower()
    return "fast" if v.startswith("fast") else "normal"


GUARD_MARKS = {"normal": (4, 8, 16, 32), "fast": (8, 16, 32, 64)}


def receipt_mode(cwd):
    """`- Receipt = full | short | savings <N> | off` (project, then user CLAUDE.md, then $ABOFLES_RECEIPT; `Pace = fast`
    makes `short` the default). Returns (mode, threshold%). Unknown values fall back to full."""
    v = (override_value(cwd, "Receipt") or os.environ.get("ABOFLES_RECEIPT") or ("short" if pace(cwd) == "fast" else "full")).strip().lower()
    m = re.match(r"(full|short|savings|off)\b\s*(\d+)?", v)
    if not m:
        return "full", 0
    return m.group(1), (int(m.group(2) or 30) if m.group(1) == "savings" else 0)


def fmt_units(u):
    return f"{u:.1f}".rstrip("0").rstrip(".") if u < 10 else f"{u:,.0f}"


def task_saving(st):
    """Saving % of this task: real dollars when the transcripts gave usage, else the unit estimate."""
    if st.get("task_tokens"):
        u, b = st.get("task_usd", 0.0), st.get("task_base_usd", 0.0)
    else:
        u, b = st.get("task_units", 0.0), st.get("task_base", 0.0)
    return round(100 * (1 - u / b)) if b else 0


def receipt_header(st):
    """The receipt's first line, computed from this task's spawns — the model copies it, never computes it.
    Real tokens and dollars from the subagent transcripts; the unit estimate only when no transcript was found."""
    pct = task_saving(st)
    base_model = st.get("main_model") or "opus"
    if st.get("task_tokens"):
        cost, base = st.get("task_usd", 0.0), st.get("task_base_usd", 0.0)
        diff = base - cost
        s = f"Saved {pct}% ({fmt_usd(diff)})" if diff >= 0 else f"Cost +{-pct}% ({fmt_usd(-diff)})"
        k = st.get("task_unpriced", 0)
        tail = f" · {k} unpriced" if k else ""
        r = st.get("running_bg", 0)
        tail += f" · {r} running" if r else ""
        top = st.get("task_top") or {}
        if cost and top.get("usd", 0) / cost >= 0.5 and st.get("spawns_since_receipt", 0) >= 2:
            tail += f" · largest: {top['what']} {fmt_usd(top['usd'])} ({round(100 * top['usd'] / cost)}%)"
        if not work_spawns(st):
            return f"🧾 **{spawn_word(st)} · {fmt_tokens(st['task_tokens'])} Tokens · {fmt_usd(cost)}** (gate runs only, no routing saving to show){tail}"
        return f"🧾 **{spawn_word(st)} · {fmt_tokens(st['task_tokens'])} Tokens · {fmt_usd(cost)} · {s}** vs {label(base_model)}{tail}"
    s = f"Saved {pct}%" if pct >= 0 else f"Cost +{-pct}%"
    return f"🧾 **{spawn_word(st)} · {fmt_units(st.get('task_units', 0.0))} u · {s}** vs {label(base_model, st.get('effort') or 'high')}"


def spawn_word(st):
    """`4 Spawns` — work agents only; the question-gate's Judge/Explainer runs are named apart: `4 Spawns + 2 gate`."""
    n, g = work_spawns(st), st.get("task_judges", 0)
    return f"{n} Spawn{'' if n == 1 else 's'}" + (f" + {g} gate" if g else "")


def work_spawns(st):
    return max(0, st.get("spawns_since_receipt", 0) - st.get("task_judges", 0))


def budget_used(st):
    """Spawns that count against the task budget: work spawns since the user's last gate answer (a new answer restarts the count)."""
    return max(0, work_spawns(st) - st.get("budget_base", 0))


RECEIPT_FULL = ("Receipt at task end — plain markdown, never in a code block (the labels are inline-code tags), these 5 lines:\n"
                "{header}\n- `done` → <what changed, files named>\n- `why` → <the reason or rule>\n"
                "- `check` → <command → decisive result>\n- `open` → <follow-ups: partial, low, ATTENTION, open FAIL, owner decisions — or none>{guide}\n"
                "A field with 2+ items (several files, several follow-ups) puts nothing after the arrow and lists each item as an indented sub-bullet `  - <item>` on its own line, one idea per sub-bullet — never a long `;`-separated line.")
RECEIPT_SHORT = "Receipt at task end — one line, plain markdown, no code block: {header} · open: <follow-ups or none>{guide_short}"


def receipt_decision(cwd, st):
    """(kind, instruction) for this task: kind is full, short or skip."""
    mode, thr = receipt_mode(cwd)
    header = receipt_header(st)
    if mode == "off" or (mode == "savings" and task_saving(st) < thr):
        why = "receipts are off" if mode == "off" else f"saving {task_saving(st)}% is under the {thr}% bar"
        return "skip", f"abofles: no receipt for this task ({why}). Still name any open follow-up (partial, low, ATTENTION, open FAIL) in prose."
    g = (st.get("guide") or {}).get("line") if guide_on(cwd) else ""
    if mode == "short":
        return "short", "abofles: " + RECEIPT_SHORT.format(header=header, guide_short=f" · {g}" if g else "")
    return "full", "abofles: " + RECEIPT_FULL.format(header=header, guide=f"\n- `next` → {g} (copy this line as given)" if g else "")


def reset_task(st):
    st["task_started"] = int(time.time())
    st["spawns_since_receipt"] = 0
    st["task_units"] = 0.0
    st["task_base"] = 0.0
    st["task_tokens"] = 0
    st["task_usd"] = 0.0
    st["task_base_usd"] = 0.0
    st["task_unpriced"] = 0
    st["task_top"] = None
    st["task_tier_max"] = 0
    st["task_judges"] = 0
    st["budget_base"] = 0
    st["asked"] = []  # questions this task asked (a reworded re-ask needs no second judge)
    st["inflight"] = 0
    st["inflight_bg"] = 0
    st["judge_ok"] = 0  # an unlock not used by a question does not carry into the next task
    if st.get("gate") == "task":  # a per-task answer expires with the task; auto/off stay for the session
        st["gate"], st["task_budget"], st["task_parallel"] = None, None, None


CONTEXT_MARKS = (500, 600, 700, 750, 800, 850, 900)  # thousands of tokens


def context_marks(cwd):
    """`- Context marks = 100, 150, 180` (thousands of tokens) in the override block, else the defaults."""
    v = override_value(cwd, "Context marks")
    marks = sorted({int(x) for x in re.findall(r"\d+", v or "")}) if v else []
    return tuple(marks) or CONTEXT_MARKS


# ── Guide: what to do next, computed from the ledger, the memo, the state and the context size ───────────────
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")
MODEL_ORDER = ("haiku", "sonnet", "opus", "fable")


def guide_on(cwd):
    return (override_value(cwd, "Guide") or "on").strip().lower() not in ("off", "0", "none")


def next_setting(model, effort, side):
    """Step 4, one step: +1 effort on the same model up to xhigh, then the next model at medium (fable only for Analyse/Plan)."""
    m, e = (model or "opus"), (effort or "medium")
    if e in EFFORT_ORDER[:3]:
        return m, EFFORT_ORDER[EFFORT_ORDER.index(e) + 1]
    i = MODEL_ORDER.index(m) if m in MODEL_ORDER else 2
    if i < 3 and not (i == 2 and side not in ("Analyse", "Plan")):
        return MODEL_ORDER[i + 1], "medium"
    return m, "xhigh" if e != "xhigh" else "max"


def guide_items(root, st, sid):
    """The ladder, first match highest: open FAIL/ATTENTION → unasked judged question → owner decisions → unescalated
    partial/low → background running → context/memo hygiene → budget → the memo's Next. Returns [(emoji, text)]."""
    items = []
    try:
        rows = [json.loads(l) for l in ledger_path(sid).read_text().splitlines() if l.strip()]
    except Exception:
        rows = []
    started = st.get("task_started", 0) or int(time.time()) - GUIDE_WINDOW  # no task start known: the last few hours
    # 1. a verifier FAIL or ATTENTION of this task not closed by a later PASS on the same topic (earlier tasks closed
    #    with their receipt; /abofles:status --resolve <id> closes one by hand)
    for i, r in enumerate(rows):
        if r.get("resolved") or r.get("ts", 0) < started:
            continue
        later_pass = any(x.get("verdict") == "PASS" and x.get("topic") == r.get("topic") for x in rows[i + 1:])
        if r.get("verdict") == "FAIL" and not later_pass:
            items.append(("🔴", f"open FAIL · {r.get('topic') or r.get('side')}: fix it (main session when ≤ 3 calls), re-verify only the failed criterion"))
        elif r.get("attention") and not later_pass:
            items.append(("🔴", f"ATTENTION · {r.get('topic') or r.get('side')}: show it to the user before closing the task"))
    # 2. a judged question nobody asked
    if st.get("judge_ok", 0) > 0 and (time.time() - st.get("gate_wait_ts", 0)) > GATE_WAIT:
        items.append(("🟠", "a judged question is unasked — AskUserQuestion now (QUESTION + WHY in the box, options as cards)"))
    # 3. owner decisions open in the memo
    try:
        need = [l for l in memo_read(root)["Needs you"].splitlines() if "[ ]" in l]
    except Exception:
        need = []
    if need:
        first = re.sub(r"^(\d+)\. \[ \] \S+ \S+ · ", r"\1) ", need[0])
        items.append(("🟠", f"{len(need)} owner decision{'s' if len(need) > 1 else ''} open — ask (judge first): {clip(first, 90)}"))
    # 4. a reply of this task that needs Step 4 and got nothing
    for r in rows:
        if r.get("ts", 0) <= started or r.get("resolved") or side_of(r.get("agent") or "")[0] in ("judge", "explainer"):
            continue
        if r.get("owner_input") or r.get("status") == "pending":
            continue
        if r.get("status") in ("partial", "blocked") or r.get("confidence") == "low":
            nm, ne = next_setting(r.get("model"), r.get("effort"), r.get("side"))
            items.append(("🟡", f"escalate · {r.get('side')} {label(r.get('model'), r.get('effort'))} came back {r.get('status')}/{r.get('confidence')} — re-run that subtask at {label(nm, ne)} (Step 4), or say why not"))
            break
    # 5. background agents still running
    running = sum(1 for r in rows if r.get("status") == "pending")
    if running:
        items.append(("⏳", f"{running} background agent{'s' if running > 1 else ''} running — collect them (and their receipt) before the next ticket"))
    # 6. context and memo hygiene
    tp = st.get("transcript_path") or ""
    tk = context_tokens(tp) if tp else None
    if tk is not None:
        marks = context_marks(root)
        nxt = next((m for m in marks if m * 1000 > tk), None)
        if nxt is None:
            items.append(("🧠", f"context {tk // 1000}K is past the last mark — /abofles:memo, then /compact at the next task boundary"))
        elif nxt * 1000 - tk <= 50_000:
            items.append(("🧠", f"context {tk // 1000}K, mark {nxt}K is {(nxt * 1000 - tk) // 1000}K away — plan /abofles:memo + /compact at the next task boundary"))
    try:
        mine = next((b for k, b in now_blocks(memo_read(root)["Now"]) if k == sid8(sid)), None)
        wm = re.search(r"^Written\s+(\S+ \S+)", mine or "", re.M)
        if wm:
            age_min = int((time.time() - time.mktime(time.strptime(wm.group(1), "%Y-%m-%d %H:%M"))) // 60)
            since = sum(1 for l in memo_read(root)["Journal"].splitlines() if f"s:{sid8(sid)}" in l and re.match(r"- (\d\d-\d\d \d\d:\d\d)", l) and re.match(r"- (\d\d-\d\d \d\d:\d\d)", l).group(1) > wm.group(1)[5:])
            if age_min >= 120 and since:
                items.append(("🧠", f"memo Now is {span(age_min)} old with {since} receipt{'s' if since > 1 else ''} since — run /abofles:memo before the next break"))
    except Exception:
        pass
    # 7. budget nearly out on an open chain
    budget, src = task_budget(root, st, st.get("task_tier_max") or None)
    if budget is not None and work_spawns(st) and budget - budget_used(st) <= 1:
        left = max(0, budget - budget_used(st))
        items.append(("💰", f"agent budget: {left} of {budget} left ({src}) — finish in the main session, or `/abofles:agents N`"))
    # 8. nothing open: the memo's Next
    if not items:
        nxt_line = ""
        try:
            mine = next((b for k, b in now_blocks(memo_read(root)["Now"]) if k == sid8(sid)), None) or ""
            nm = re.search(r"^Next\s+(.+)$", mine, re.M)
            nxt_line = nm.group(1).strip() if nm else ""
        except Exception:
            pass
        items.append(("✅", f"nothing open — next from the memo: {clip(nxt_line, 110)}" if nxt_line else "nothing open — pick the next ticket and route it with abofles first"))
    return items


def refresh_guide(root, st, sid):
    """Compute the guide, keep it in the state (the band mod reads it there), return its one-line form."""
    if not guide_on(root):
        st["guide"] = None
        return None
    items = guide_items(root, st, sid)
    line = "🧭 " + " · ".join(f"{e} {t}" for e, t in items[:3]) + (f" · +{len(items) - 3} more" if len(items) > 3 else "")
    st["guide"] = {"line": line, "items": [{"p": e, "text": t} for e, t in items], "ts": int(time.time())}
    return line


# ── Memo: the work journal the hooks keep for the user ───────────────────────────────────────────────
MEMO_SECTIONS = ("Now", "Needs you", "Decisions", "Journal")
JOURNAL_KEEP = 40
NEEDS_RE = re.compile(r"ATTENTION|VERDICT:? ?FAIL|\bFAIL\b|owner|decide|decision|confirm|approve|choose|pick|\?", re.I)


def project_root(data=None, st=None):
    """The directory the session started in — the one memo, overrides and resume use. A `cd` into a worktree or a
    nested repo must not move the memo (it would land as an untracked file in a team repository)."""
    root = (st or {}).get("root")
    if root:
        return root
    return (data or {}).get("cwd") or os.getcwd()


def memo_path(cwd):
    return Path(cwd or os.getcwd()) / ".claude" / "abofles-memo.md"


def git_exclude_memo(cwd):
    """Keep the memo out of `git status` without touching the project's .gitignore: `.git/info/exclude` is local."""
    try:
        git = Path(cwd) / ".git"
        if git.is_file():  # worktree: `gitdir: <path>`
            git = Path(git.read_text().split("gitdir:", 1)[1].strip())
            if not git.is_absolute():
                git = Path(cwd) / git
            git = Path(str(git).split("/worktrees/")[0]) if "/worktrees/" in str(git) else git
        ex = git / "info" / "exclude"
        if not git.is_dir():
            return
        txt = ex.read_text() if ex.exists() else ""
        if ".claude/abofles-memo" not in txt:
            ex.parent.mkdir(parents=True, exist_ok=True)
            ex.write_text(txt + ("" if not txt or txt.endswith("\n") else "\n") + ".claude/abofles-memo.*\n")
    except Exception:
        pass


def break_minutes(cwd):
    """`- Break = N` (minutes away before the resume block is shown) or `Break = off`; default 10."""
    v = (override_value(cwd, "Break") or "10").strip().lower()
    if v in ("off", "0", "none"):
        return 0
    m = re.match(r"(\d+)", v)
    return int(m.group(1)) if m else 10


class memo_lock:
    """The memo is shared by every session in a project; serialise read-modify-write."""
    def __init__(self, cwd):
        key = re.sub(r"[^A-Za-z0-9]", "_", os.path.realpath(cwd or os.getcwd()))[-120:]
        self.path = STATE_DIR / "memo-locks" / f"{key}.lock"  # never inside the project: a stray .lock there shows in git status
        self.fh = None
    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(self.path, "w")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except Exception:
            self.fh = None
        return self
    def __exit__(self, *a):
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            except Exception:
                pass


def memo_read(cwd):
    """Sections of the memo file as {name: body}; missing file -> empty sections."""
    sec = {k: "" for k in MEMO_SECTIONS}
    try:
        txt = memo_path(cwd).read_text()
    except Exception:
        return sec
    cur = None
    for line in txt.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            cur = m.group(1) if m.group(1) in sec else None
            continue
        if cur:
            sec[cur] += line + "\n"
    return {k: v.strip("\n") for k, v in sec.items()}


def memo_write(cwd, sec, session_id=""):
    path = memo_path(cwd)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    head = f"# Abo Fles memo — {Path(cwd or os.getcwd()).name}\nUpdated: {stamp}" + (f" · session {session_id[:8]}" if session_id else "") + "\n"
    body = "".join(f"\n## {k}\n{sec.get(k, '').strip()}\n" for k in MEMO_SECTIONS)
    try:
        new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(head + body)
        os.replace(tmp, path)
        if new:
            git_exclude_memo(cwd)
    except Exception:
        pass


def memo_updated(cwd):
    """The `Updated:` stamp of the memo, or None."""
    try:
        m = re.search(r"^Updated: (\S+ \S+)", memo_path(cwd).read_text(), re.M)
        return m.group(1) if m else None
    except Exception:
        return None


def clip(t, n=160):
    t = " ".join((t or "").split())
    if len(t) <= n:
        return t
    cut = t[: n - 1]
    return (cut[: cut.rfind(" ")] if " " in cut[n // 2:] else cut) + "…"


def parse_receipt(text):
    """The receipt the model printed -> {header, done, why, check, open}. Full form (one `- `label` → …` line per field),
    short form (`🧾 … · open: …`) and the old `done   x` columns all parse; missing fields are ''."""
    out = {"header": "", "done": "", "why": "", "check": "", "open": ""}
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        sm = re.match(r"^[-*•]\s+(.+)$", line) if cur and (raw.startswith((" ", "\t")) or not re.match(r"^-\s*`", line)) else None
        if sm and cur and not re.match(r"^-\s*`(done|why|check|open)`", line):
            out[cur] = (out[cur] + "; " if out[cur] else "") + sm.group(1).strip()  # a sub-bullet item of the field above
            continue
        cur = None
        if line.startswith("🧾") and not out["header"]:
            h = re.sub(r"\*\*", "", line[1:]).strip()
            if " · open:" in h:
                h, _, op = h.partition(" · open:")
                out["open"] = out["open"] or op.strip()
            out["header"] = h.strip()
            continue
        m = re.match(r"^-\s*`(done|why|check|open)`\s*→\s*(.*)$", line) or re.match(r"^(done|why|check|open)\s{2,}(\S.*)$", line)
        if m and not out[m.group(1)]:
            out[m.group(1)] = m.group(2).strip()
            cur = m.group(1)
    real = out["header"] and (out["done"] and (out["check"] or out["why"]) or out["open"] and " · " in out["header"])
    return out if real else None


def needs_items(open_line):
    """Follow-ups the user must look at: ATTENTION, FAIL, owner decisions, questions. Not `none`, not routine chain state."""
    if not open_line or re.match(r"none\b", open_line.strip(), re.I):
        return []
    return [clip(x) for x in re.split(r";\s*", open_line) if x.strip() and NEEDS_RE.search(x)]


def memo_journal(cwd, session_id, rc):
    with memo_lock(cwd):
        _memo_journal(cwd, session_id, rc)


def _memo_journal(cwd, session_id, rc):
    """Append a receipt to the journal (newest first, JOURNAL_KEEP kept) and its must-see items to Needs you."""
    sec = memo_read(cwd)
    stamp = time.strftime("%m-%d %H:%M")
    bits = [clip(rc["header"], 120)]
    for k in ("done", "check", "open"):
        if rc.get(k):
            bits.append(f"{k}: {clip(rc[k])}")
    entry = f"- {stamp} · " + (f"s:{sid8(session_id)} · " if session_id else "") + " · ".join(bits)
    lines = [l for l in sec["Journal"].splitlines() if l.strip()]
    sec["Journal"] = "\n".join([entry] + lines)[: 20000]
    sec["Journal"] = "\n".join(sec["Journal"].splitlines()[:JOURNAL_KEEP])
    need = [l for l in sec["Needs you"].splitlines() if l.strip()]
    have = [need_key(l) for l in need]
    for item in needs_items(rc.get("open")):
        key = need_key(item)
        if not any(h == key or similar(h, key, 0.8) for h in have):
            need.append(f"{len(need) + 1}. [ ] {stamp} · {item}" + (f" (s:{sid8(session_id)})" if session_id else ""))
            have.append(key)
    sec["Needs you"] = "\n".join(need)
    memo_write(cwd, sec, session_id)


def memo_needs(cwd, session_id, item):
    """Add one item to Needs you (deduplicated)."""
    with memo_lock(cwd):
        _memo_needs(cwd, session_id, item)


def sid8(session_id):
    return (session_id or "")[:8]


def need_key(line):
    """The item text of a Needs-you line without number, box, stamp, session tag and resolution note — for deduplication."""
    t = re.sub(r"^\d+\. \[.\] \S+ \S+ · ", "", line.strip()).split(" → resolved")[0]
    t = re.sub(r"\s*\(s:[0-9a-f]{4,8}\)\s*$", "", t)
    return " ".join(re.findall(r"[\w\u0600-\u06FF]+", t.lower()))[:120]


def _memo_needs(cwd, session_id, item):
    sec = memo_read(cwd)
    need = [l for l in sec["Needs you"].splitlines() if l.strip()]
    key = need_key(clip(item))
    if not any(need_key(l) == key or similar(need_key(l), key, 0.8) for l in need):
        need.append(f"{len(need) + 1}. [ ] {time.strftime('%m-%d %H:%M')} · {clip(item)}" + (f" (s:{sid8(session_id)})" if session_id else ""))
    sec["Needs you"] = "\n".join(need)
    memo_write(cwd, sec, session_id)


def memo_resolve_matching(cwd, question):
    """Tick every open Needs-you item the answered question covers (word overlap). Returns the count."""
    with memo_lock(cwd):
        sec = memo_read(cwd)
        lines = sec["Needs you"].splitlines()
        n = 0
        for i, l in enumerate(lines):
            if "[ ]" in l and similar(need_key(l), question, 0.5):
                lines[i] = l.replace("[ ]", "[x]", 1) + f" → resolved {time.strftime('%m-%d %H:%M')}: answered"
                n += 1
        if n:
            sec["Needs you"] = "\n".join(lines)
            memo_write(cwd, sec)
        return n


def memo_decision(cwd, session_id, question, answer):
    with memo_lock(cwd):
        _memo_decision(cwd, session_id, question, answer)


def _memo_decision(cwd, session_id, question, answer):
    sec = memo_read(cwd)
    lines = [l for l in sec["Decisions"].splitlines() if l.strip()]
    lines.append(f"- {time.strftime('%m-%d %H:%M')} · {clip(question, 140)} → {clip(answer, 140)}")
    sec["Decisions"] = "\n".join(lines[-60:])
    memo_write(cwd, sec, session_id)


def memo_resolve(cwd, n, note=""):
    """Tick item n of Needs you. Returns the item text or None."""
    with memo_lock(cwd):
        return _memo_resolve(cwd, n, note)


def _memo_resolve(cwd, n, note=""):
    sec = memo_read(cwd)
    lines = sec["Needs you"].splitlines()
    for i, l in enumerate(lines):
        if l.startswith(f"{n}. [ ] "):
            lines[i] = l.replace("[ ]", "[x]", 1) + f" → resolved {time.strftime('%m-%d %H:%M')}" + (f": {clip(note, 120)}" if note else "")
            sec["Needs you"] = "\n".join(lines)
            memo_write(cwd, sec)
            return l
    return None


NOW_BLOCKS = 6  # Now blocks kept (one per session that wrote one; several sessions may share a project root)


def now_blocks(now_text):
    """The Now section as [(sid8 or "", block text)] — one block per session, split on `Session   <id>` lines."""
    blocks, cur, buf = [], "", []
    for line in (now_text or "").splitlines():
        m = re.match(r"^Session\s+(\S+)", line)
        if m:
            if buf and "".join(buf).strip():
                blocks.append((cur, "\n".join(buf).strip()))
            cur, buf = m.group(1)[:8], []
            continue
        buf.append(line)
    if buf and "".join(buf).strip():
        blocks.append((cur, "\n".join(buf).strip()))
    return blocks


def memo_now(cwd, text, session_id=""):
    """Replace this session's block of the Now section (what /abofles:memo writes); other sessions' blocks and the hook
    sections stay. Several Claude sessions in one project root each keep their own Now."""
    me = sid8(session_id)
    body = f"Written   {time.strftime('%Y-%m-%d %H:%M')}\n" + re.sub(r"^(Written|Session)\s+.*\n?", "", text.strip(), flags=re.M).strip()
    with memo_lock(cwd):
        sec = memo_read(cwd)
        others = [(k, b) for k, b in now_blocks(sec["Now"]) if k != me and k][:NOW_BLOCKS - 1]
        mine = (f"Session   {me}\n" if me else "") + body
        sec["Now"] = "\n\n".join([mine] + [f"Session   {k}\n{b}" for k, b in others])
        memo_write(cwd, sec, session_id)


def span(minutes):
    """`3 days 2 hours 5 min` — the largest unit first, zero units left out, `0 min` when nothing passed."""
    minutes = int(minutes or 0)
    d, h, m = minutes // 1440, minutes % 1440 // 60, minutes % 60
    parts = [f"{d} day{'s' if d != 1 else ''}" if d else "", f"{h} hour{'s' if h != 1 else ''}" if h else "", f"{m} min" if m else ""]
    return " ".join(x for x in parts if x) or "0 min"


def split_items(text):
    """Items of one field: split on ` · ` and on `; ` outside parentheses/brackets/backticks — a long line the user
    cannot scan becomes one sub-bullet per idea."""
    out, buf, depth, tick = [], "", 0, False
    i = 0
    while i < len(text):
        c = text[i]
        if c == "`":
            tick = not tick
        elif not tick and c in "([{":
            depth += 1
        elif not tick and c in ")]}":
            depth = max(0, depth - 1)
        if depth == 0 and not tick and (text.startswith(" · ", i) or text.startswith("; ", i)):
            out.append(buf.strip())
            buf = ""
            i += 3 if text.startswith(" · ", i) else 2
            continue
        buf += c
        i += 1
    out.append(buf.strip())
    return [x for x in out if x]


def field_lines(tag, items):
    """`- \`tag\` → one item` when there is one; the tag alone and one indented sub-bullet per item when there are more."""
    items = [x for x in items if x]
    if not items:
        return []
    if len(items) == 1:
        return [f"- `{tag}` → {items[0]}"]
    return [f"- `{tag}` →"] + [f"  - {x}" for x in items]


def resume_block(cwd, away_min=None, session_id="", guide=None):
    """The short block to print after a break, a compact or a new session. None when there is no memo.
    With several sessions in one project root: this session's Now block and receipts; the others' only as labelled hints."""
    if not memo_path(cwd).exists():
        return None
    sec = memo_read(cwd)
    me = sid8(session_id)
    blocks = now_blocks(sec["Now"])
    mine = next((b for k, b in blocks if k == me), None)
    if mine is None and not me:
        mine = next((b for k, b in blocks if not k), None)
    others = [(k, b) for k, b in blocks if k and k != me]
    if mine is None and len(blocks) == 1 and not blocks[0][0]:
        try:  # a memo written before sessions were tagged: it is mine only when this session wrote it last
            writer = re.search(r"· session (\w+)", memo_path(cwd).read_text()[:300])
        except Exception:
            writer = None
        if not me or (writer and writer.group(1) == me):
            mine = blocks[0][1]
        else:
            others = [(writer.group(1) if writer else "untagged", blocks[0][1])] + others
    now = {}
    key = None
    for line in (mine or "").splitlines():
        m = re.match(r"^(Written|Task|Done|Left|Decisions|Next|Verify|Tree)\s+(.*)$", line)  # one space after `Decisions` (9 chars, padded to 10)
        if m:
            key = m.group(1)
            now.setdefault(key, []).append(m.group(2).strip())
        elif key and line.strip() and key not in ("Tree",):
            now[key].append(line.strip())  # a continuation line, or a second `Left` item written without its label
    written = (now.get("Written") or [None])[0]
    age = ""
    newer = 0
    if written:
        try:
            age_min = int((time.time() - time.mktime(time.strptime(written, "%Y-%m-%d %H:%M"))) // 60)
            age = f" · now written {written} ({span(age_min)} ago)" if age_min >= 60 else f" · now written {written}"
            wm = written[5:]
            if written[:4] == time.strftime("%Y"):  # journal stamps carry no year: compare only within the year the memo was written
                newer = sum(1 for l in sec["Journal"].splitlines() if re.match(r"- (\d\d-\d\d \d\d:\d\d)", l) and re.match(r"- (\d\d-\d\d \d\d:\d\d)", l).group(1) > wm
                            and (not me or f"s:{me}" in l))
        except Exception:
            pass
    open_items = [l for l in sec["Needs you"].splitlines() if "[ ]" in l]
    jall = [l for l in sec["Journal"].splitlines() if l.strip()]
    jmine = [l for l in jall if f"s:{me}" in l] if me else jall
    jother = [l for l in jall if l not in jmine]
    journal = jmine[:3] or [re.sub(r"· s:([0-9a-f]+) ·", r"· (session \1, not this one) ·", l) for l in jother[:2]]
    head = f"📍 **Resume** · memo {memo_updated(cwd) or '?'}" + (f" · away {span(away_min)}" if away_min else "") + (f" · session {me}" if me else "") + age
    lines = [head]
    items = lambda k: [i for x in now.get(k, []) if x for i in split_items(x)]
    if mine is None and others:
        lines.append("- `now` → no Now section from this session yet — " + ", ".join(f"session {k} wrote: {clip(next((l.split(None, 1)[1] for l in b.splitlines() if l.startswith('Task')), ''), 70)}" for k, b in others[:3]) + " (their work, not yours)")
    lines += field_lines("now", items("Task"))
    lines += field_lines("left", items("Left"))
    lines += field_lines("next", items("Next"))
    if newer:
        lines.append(f"- `since` → {newer} receipt{'s' if newer > 1 else ''} of this session after its Now section was written — `now`/`next` above may be stale; trust `last` and the journal")
    if open_items:
        shown = [re.sub(r"^(\d+)\. \[ \] \S+ \S+ · ", r"\1) ", l) for l in open_items[:6]]
        more = f"+{len(open_items) - 6} more" if len(open_items) > 6 else ""
        lines.append(f"- `needs you` → {len(open_items)} open" + (f": {shown[0]}" if len(shown) == 1 and not more else ""))
        if len(shown) > 1 or more:
            lines += [f"  - {x}" for x in shown] + ([f"  - {more}"] if more else [])
    else:
        lines.append("- `needs you` → none")
    if journal:
        lines += field_lines("last", [clip(re.sub(r"^- ", "", l), 140) for l in journal])
    if guide:
        lines.append(f"- `guide` → {guide}")
    return "\n".join(lines)


def resume_note(block, why):
    return (f"abofles RESUME ({why}): print the block below **verbatim, first in your reply** — do not re-read the transcript "
            f"or files to rebuild it — then handle the prompt as usual (route lines, the `main:` line the hook hands you at a task's first spawn, receipts). Resolve an item with `python3 \"{Path(__file__).resolve().parent.parent / 'scripts' / 'memo.py'}\" resolve <n> \"<note>\"` once the user settles it.\n\n{block}")


def decision(data):
    """PostToolUse on AskUserQuestion: log every question the session asked and the user's answer to the memo."""
    if in_subagent(data):
        return
    if "started" not in load_state(data.get("session_id", "")):
        return
    ti = data.get("tool_input") or {}
    resp = data.get("tool_response")
    answers = {}
    if isinstance(resp, dict):
        answers = resp.get("answers") or {}
    elif isinstance(resp, str):
        try:
            answers = (json.loads(resp) or {}).get("answers") or {}
        except Exception:
            answers = {}
    sid = data.get("session_id", "")
    st = load_state(sid)
    cwd = project_root(data, st)
    note = None
    for q in ti.get("questions") or []:
        qt = (q or {}).get("question") or ""
        a = answers.get(qt) if isinstance(answers, dict) else None
        if not qt or not a or dismissed(str(a)):
            continue  # a dismissed question is not a decision
        memo_decision(cwd, sid, question_line(qt, (q or {}).get("header")), str(a))
        memo_resolve_matching(cwd, qt)  # the Needs-you item that raised this question is answered now
        if GATE_MARK.lower() in qt.lower():
            with state_lock(sid):
                st = load_state(sid)
                note = apply_gate_answer(st, str(a))
                save_state(sid, st)
    if note:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": f"abofles: {note} — recorded; continue the task."}}))


def dismissed(answer):
    return bool(re.match(r"\s*\[?\s*user (dismissed|cancel)", answer or "", re.I))


def question_line(question, header=None):
    """The sentence that is the question (first one ending in ? / ؟), not the story before it: what Decisions keeps."""
    q = " ".join((question or "").split())
    q = re.sub(r"\s*[—–-]\s*read the explanation above first\s*$", "", q, flags=re.I)
    m = re.search(r"[^?؟.。!]*[?؟]", q)
    sent = (m.group(0).strip() if m else q)
    if len(sent) < 12:
        sent = q
    return (f"[{header}] " if header and header.lower() not in sent.lower() else "") + sent


STOP_WORDS = {"the", "and", "for", "that", "this", "with", "from", "should", "which", "what", "when", "where", "does", "will",
              "are", "was", "were", "have", "has", "not", "you", "your", "our", "its", "into", "than", "then", "only", "also",
              "هل", "في", "من", "على", "عن", "أو", "او", "إلى", "الى", "هذا", "هذه", "ماذا", "متى", "أي", "اي", "كيف", "لماذا"}


def words_of(t):
    return {w for w in re.findall(r"[\w\u0600-\u06FF]{3,}", (t or "").lower()) if w not in STOP_WORDS}


def similar(a, b, bar=0.6):
    """The same text again, reworded: at least 3 shared content words, covering `bar` of the shorter side (the stored
    question sentence; the new text may carry WHY and EXPLAIN too). Never true for a short generic question."""
    wa, wb = words_of(a), words_of(b)
    short = min(len(wa), len(wb))
    if short < 2:
        return False
    shared = len(wa & wb)
    return shared >= min(3, short) and shared / short >= bar


# ── Agent gate: how many agents a task may spawn, asked once, then enforced ───────────────────────────
AGENT_BUDGETS = {"orchestrator": (2, 3, 5, 8), "worker": (1, 2, 4, 6)}  # per tier T1..T4
GATE_MARK = "Abo Fles agent gate"


def mode_of(st):
    return "orchestrator" if (st.get("main_model") or "opus") in ("opus", "fable") else "worker"


def gate_setting(cwd):
    """`- Agents = ask | auto | N | off` (default ask)."""
    v = (override_value(cwd, "Agents") or os.environ.get("ABOFLES_AGENTS") or "ask").strip().lower()
    if v.isdigit():
        return "fixed", int(v)
    return (v if v in ("ask", "auto", "off") else "ask"), None


def parallel_cap(cwd):
    """`- Parallel = M` (background spawns running at once, default 3; 0 = no cap)."""
    m = re.match(r"(\d+)", override_value(cwd, "Parallel") or "3")
    return int(m.group(1)) if m else 3


def tier_budget(cwd, st, tier):
    """Agents a task of this tier may spawn under `auto`: per-mode table, `- Agent budgets = a, b, c, d` override."""
    v = override_value(cwd, "Agent budgets")
    table = tuple(int(x) for x in re.findall(r"\d+", v or ""))[:4] if v else ()
    if len(table) != 4:
        table = AGENT_BUDGETS[mode_of(st)]
    return table[(tier or 2) - 1]


def task_budget(cwd, st, tier):
    """(budget or None for unlimited, source) for the current task."""
    setting, n = gate_setting(cwd)
    if setting == "off":
        return None, "Agents = off"
    if setting == "fixed":
        return n, f"Agents = {n}"
    gate = st.get("gate")
    if gate == "off":
        return None, "gate: off this session"
    if gate == "task" and st.get("task_budget") is not None:
        return st["task_budget"], "your answer for this task"
    if gate == "auto" or setting == "auto":
        t = max(tier or 2, st.get("task_tier_max") or 0)
        return tier_budget(cwd, st, t), f"auto · {tier_name(t)} · {mode_of(st)}"
    return None, "unset"


def gate_needed(cwd, st):
    """True when the session must ask the gate question before this spawn."""
    setting, _ = gate_setting(cwd)
    return setting == "ask" and not st.get("gate")


def gate_question(st):
    """The question the skill asks, in the shape the decision hook parses back."""
    m = mode_of(st)
    return (f"{GATE_MARK}: ask with AskUserQuestion, one question containing the words `{GATE_MARK}`, options in this order — "
            "1) `Auto (recommended)` — abofles sizes every task by topic, side and tier (Minor {0} · Normal {1} · Sensitive {2} · Critical {3} agents), no further questions this session; "
            "2) `This task: N agents` — N from your route plan, with the units and $ estimate, asked again next task; "
            "3) `Main session only` — 0 agents this task" + (" (costly: the main model does every read itself)" if m == "orchestrator" else "") + "; "
            "4) " + ("`Max: N agents · M parallel` for a Large task" if m == "orchestrator" else "`Switch main to Opus 5.5 and orchestrate` — end the turn with one line telling the user to pick Opus in the model picker and send \"go\"") +
            ". The user may type a number or `off` in Other. The hook records the answer; you do nothing else.").format(*AGENT_BUDGETS[m])


def apply_gate_answer(st, answer):
    """Parse the gate answer into the state. Returns a short note."""
    a = (answer or "").strip()
    low = a.lower()
    st["task_parallel"] = None
    st["budget_base"] = work_spawns(st)  # a fresh answer starts a fresh count: a stuck budget is released by answering again
    if low.startswith("auto"):
        st["gate"], st["task_budget"] = "auto", None
        return "agents: auto"
    if low.startswith("off") or "no limit" in low:
        st["gate"], st["task_budget"] = "off", None
        return "agents: off this session"
    if low.startswith("main"):
        st["gate"], st["task_budget"] = "task", 0
        return "agents: 0 this task"
    if low.startswith("switch"):
        st["gate"], st["task_budget"] = "task", 0
        return "agents: switch main to opus"
    m = re.search(r"(\d+)\s*agents?", low) or re.match(r"^\s*(\d+)\s*$", low)
    if m:
        st["gate"], st["task_budget"] = "task", int(m.group(1))
        pm = re.search(r"(\d+)\s*parallel", low)
        if pm:
            st["task_parallel"] = int(pm.group(1))
        return f"agents: {m.group(1)} this task"
    st["gate"], st["task_budget"] = "auto", None
    return "agents: auto (answer not understood)"


# ── Question gate: no AskUserQuestion before a Judge (and, on T3–T4, an Explainer) has seen it ───────────────────
QUESTION_ROUTE = {1: ("sonnet", "low", None, None), 2: ("sonnet", "medium", None, None), 3: ("sonnet", "medium", "opus", "medium"), 4: ("opus", "medium", "opus", "high")}


def questions_setting(cwd):
    v = (override_value(cwd, "Questions") or "judge").strip().lower()
    return "off" if v in ("off", "none", "0") else "judge"


def question_language(cwd):
    """`- Language = Arabic` (the language owner questions are written in), or None."""
    v = override_value(cwd, "Language") or override_value(cwd, "Questions language")
    return v.strip() if v else None


def question_gate_text(st, lang=None):
    rows = " · ".join(f"{tier_name(t)} {label(j, je)}" + (f" → {label(e, ee)}" if e else " (judges and explains)") for t, (j, je, e, ee) in QUESTION_ROUTE.items())
    return ("Abo Fles (ابو فليس): question gate — a Judge agent must see this question first. Spawn `abofles:abofles-judge` (first prompt line "
            "`abofles: <Topic> / Judge · T<tier>`; give it the question, the options, the task context, the files, what the user already decided, "
            f"`Language: {lang or '<the language the user writes in>'}` and `Line cap: 40`). "
            f"Routes: {rows}. ANSWERED → state the answer with its evidence in one line and continue, no question. ASK → AskUserQuestion whose question text is "
            "its QUESTION, a blank line, WHY, then the EXPLAIN block — all inside the question (the user reads the box; reply text printed right before the box is visible above it). "
            "The question box renders PLAIN TEXT: no markdown table, no `|`, no `**`, no code fence. The question text is QUESTION + WHY; the options are the option cards "
            "(label + `then:` as description) — never restate them in the question text; add EXPLAIN there only when it carries a fact the options do not (a worked example, numbers). "
            "When EXPLAIN is a table, diagram or worked example that needs markdown, print it first in your reply under "
            f"`{EXPLAIN_MARK} **Explanation for the question below**`, then ask with a plain summary inside and `{EXPLAIN_MARK} the full table/diagram is printed above this question` at the end "
            "(the hook checks the transcript and refuses the question until the explanation is printed). "
            "Options from OPTIONS (label + `then:` as the description), RECOMMEND first with `(Recommended)`. "
            "HANDOFF (T3–T4) → spawn `abofles:abofles-explainer` (`abofles: <Topic> / Explain · T<tier>`, same Language line) with the Judge's QUESTION, EVIDENCE and WHY, then ask from its reply. "
            "Re-asking the same round reworded needs no second judge (a SendMessage to the explainer, or the same questions again, pass). "
            "Only the Abo Fles agent gate question is exempt. `- Questions = off` in the override block turns this off.")


ASK_PLAIN = ("question judged — AskUserQuestion now: the question text is QUESTION, a blank line, WHY — nothing else, unless EXPLAIN adds a fact the options do not carry "
             "(a worked example with numbers, a timeline), then that as plain lines (no markdown table, no `|`, no `**`). Never restate the options in the question text: "
             "they are the option cards — label from OPTIONS, `then:` as the description, RECOMMEND first with `(Recommended)`")
ASK_MD = (f"question judged — its EXPLAIN needs markdown (table / diagram / example). In ONE assistant message, in this order: (1) the text `{EXPLAIN_MARK} **Explanation for the question below**` "
          "followed by the EXPLAIN block as real markdown — the user sees it rendered right above the question box when it is in the same message as the call; (2) the AskUserQuestion call, "
          f"whose question text is QUESTION, a blank line, WHY, ending with `{EXPLAIN_MARK} the full table/diagram is printed above this question` — no summary of the options in the text (they are the option cards). "
          "Never a tool call between the text and the question (the app folds text that is followed by other tool calls), never \"reply A, B or C in chat\" instead of the question box.")


REASK_WINDOW = 900  # seconds after an allowed question in which the same round may be asked again (reworded, translated) with no judge
GUIDE_WINDOW = 4 * 3600  # seconds back the guide looks for open FAIL/escalation rows when no task start is known
GATE_WAIT = 900  # seconds after a SendMessage to a gate agent during which the Stop hook does not demand the question (its reply is still coming)


def qgate(data):
    """PreToolUse on AskUserQuestion: allow only after a judge (ASK) or an explainer reply unlocked it."""
    if in_subagent(data):
        return
    ti = data.get("tool_input") or {}
    qlist = [((q or {}).get("question") or "") for q in ti.get("questions") or []]
    qs = " ".join(qlist)
    sid = data.get("session_id", "")
    with state_lock(sid):
        st = load_state(sid)
        if "started" not in st:
            return
        asked = st.get("asked") or []
        root = project_root(data, st)
        fast_minor = pace(root) == "fast" and (st.get("task_tier_max") or 0) <= 2  # Pace = fast: Minor/Normal questions go straight to the user
        if GATE_MARK.lower() in qs.lower() or questions_setting(root) == "off" or fast_minor:
            st["asked"] = (asked + [question_line(q) for q in qlist])[-12:]
            save_state(sid, st)
            return
        ok = st.get("judge_ok", 0)
        reask = bool(qlist) and all(any(similar(q, a) for a in asked) for q in qlist)  # the same round again, reworded: already judged
        reask = reask or (time.time() - st.get("last_ask_ts", 0)) < REASK_WINDOW  # or asked again right after (a translation shares no words)
        if ok > 0 or reask:
            if ok > 0:
                st["judge_ok"] = ok - 1
            st["explain_md"] = False
            st["last_ask_ts"] = int(time.time())
            st["asked"] = (asked + [question_line(q) for q in qlist])[-12:]
            save_state(sid, st)
            return
        save_state(sid, st)
    deny(question_gate_text(st, question_language(project_root(data, st))))


def sendmsg(data):
    """PostToolUse on SendMessage: a message to a Judge/Explainer agent (a cheap re-ask of the same round) brings a
    reply that counts as a judged question — unlock one AskUserQuestion."""
    if in_subagent(data):
        return
    ti = data.get("tool_input") or {}
    to = str(ti.get("to") or ti.get("recipient") or "").strip()
    if not to:
        return
    sid = data.get("session_id", "")
    try:
        rows = [json.loads(l) for l in ledger_path(sid).read_text().splitlines() if l.strip()]
    except Exception:
        rows = []
    gate_ids = {r.get("agent_id") for r in rows if side_of(r.get("agent") or "")[0] in ("judge", "explainer")}
    if to not in gate_ids and not re.search(r"judge|explain", to, re.I):
        return
    with state_lock(sid):
        st = load_state(sid)
        if "started" not in st:
            return
        st["judge_ok"] = st.get("judge_ok", 0) + 1
        st["gate_wait_ts"] = int(time.time())
        save_state(sid, st)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "abofles: message sent to a gate agent — one AskUserQuestion is unlocked for its reply. Wait for the reply (it arrives as a task result), then ask from its wording; do not ask with your own translation first."}}))


def explain_block(text):
    """The EXPLAIN section of a judge/explainer reply (to its end)."""
    m = re.search(r"^\s*EXPLAIN:\s*(.*)$", text, re.M | re.S)
    return (m.group(1) if m else "").strip().strip("`").strip()


def explain_needs_markdown(text):
    """True when EXPLAIN holds a table, a code fence or a box/flow diagram — things the plain-text question box turns
    into soup; such a block is printed as markdown above the question."""
    ex = explain_block(text)
    if not ex:
        return False
    return bool(re.search(r"^\s*\|.*\|\s*$", ex, re.M) or "```" in ex or re.search(r"[┌┐└┘│─├┤┬┴┼╔╗╚╝║═]", ex) or len(re.findall(r"^\s*\S.*(→|->|=>).*$", ex, re.M)) >= 3)


def judge_fields(text):
    """VERDICT / QUESTION / ANSWER / first EVIDENCE line of a judge reply (its first block)."""
    g = lambda k: (re.search(r"^\s*" + k + r":\s*(.+)$", text, re.M) or [None, ""])[1].strip()
    ev = re.search(r"^\s*EVIDENCE:\s*\n\s*-\s*(.+)$", text, re.M)
    return g("VERDICT").upper(), g("QUESTION"), g("ANSWER"), (ev.group(1).strip() if ev else "")


def judge_blocks(text):
    """A judge may answer several questions in one reply: one (verdict, question, answer, evidence) per VERDICT line."""
    starts = [m.start() for m in re.finditer(r"^\s*VERDICT:", text, re.M)]
    if len(starts) <= 1:
        v, q, a, e = judge_fields(text)
        return [(v, q, a, e)] if v else []
    out = []
    for i, st_ in enumerate(starts):
        chunk = text[st_: starts[i + 1] if i + 1 < len(starts) else len(text)]
        # the QUESTION of a block may be written before its VERDICT: look back to the previous block's end for it
        prev = text[starts[i - 1] if i else 0: st_]
        v, q, a, e = judge_fields(chunk)
        if not q:
            qm = re.findall(r"^\s*QUESTION:\s*(.+)$", prev, re.M)
            q = qm[-1].strip() if qm else ""
        out.append((v, q, a, e))
    return out


def pending_count(session_id):
    try:
        return sum(1 for l in ledger_path(session_id).read_text().splitlines() if l.strip() and json.loads(l).get("status") == "pending")
    except Exception:
        return 0


def transcript_tail(transcript_path, limit=1_000_000):
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def context_tokens(transcript_path):
    """Current context size in tokens: input + cache read + cache creation of the newest main-thread
    assistant message in the transcript (what the next request will carry). None when unknown."""
    for line in reversed(transcript_tail(transcript_path)):
        if '"usage"' not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "assistant" or r.get("isSidechain"):
            continue
        u = (r.get("message") or {}).get("usage") or {}
        if not u:
            continue
        return int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
    return None


def assistant_texts_after(transcript_path, offset):
    """Assistant text parts written to the transcript after byte `offset` (main thread only)."""
    out = []
    try:
        with open(transcript_path, "rb") as f:
            f.seek(max(0, offset))
            chunk = f.read().decode("utf-8", "replace")
    except Exception:
        return out
    for line in chunk.splitlines():
        if '"assistant"' not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "assistant" or r.get("isSidechain"):
            continue
        parts = (r.get("message") or {}).get("content") or []
        text = "\n".join(p.get("text") or "" for p in parts if isinstance(p, dict) and p.get("type") == "text").strip()
        if text:  # tool-use-only responses are not visible output; they neither acknowledge nor count as a reply
            out.append(text)
    return out


def receipt_printed_after(transcript_path, offset):
    """Best effort: the desktop app does not always persist text written next to a tool call."""
    return any(has_receipt(t) for t in assistant_texts_after(transcript_path, offset))


def has_receipt(text):
    return bool(re.search(r"^\s*🧾", text, re.M)) or "── receipt" in text


def context_block(tokens, mark, marks, in_task):
    """Both advice branches are always in the block; the model knows whether a task is really open, a hook does not
    (the spawn count is stale inside a single long turn — run 17). `in_task` is kept for callers but unused."""
    nxt = next((m for m in marks if m > mark), None)
    nxt_line = f"Next warning at {nxt}K." if nxt else "This is the last mark — compact before the window is full."
    block = (f"# ⚠️ **CONTEXT {tokens // 1000}K — RUN /abofles:memo, THEN /compact**\n"
             f"**Abo Fles (ابو فليس):** this session passed **{mark}K tokens** of context. {nxt_line}\n"
             f"**If no task is open:** stop here — run `/abofles:memo` (hand-off memo: done, left, decisions, next step), **then** `/compact`. Safe between tasks.\n"
             f"**If a task is open** (a chain running, edits half applied, a verifier not back): do **not** compact yet — finish the step, print the receipt, **then** memo and `/compact`.")
    return (f"abofles CONTEXT WATCH: context is {tokens:,} tokens (mark {mark}K passed). The turn is over — print the block below "
            f"**verbatim** now as your last output — heading, bold, all four lines — then add one line saying which branch applies. "
            f"Start no new work; the user decides on memo and /compact.\n\n{block}")


def context_watch(data, st):
    """Call under the state lock, from the Stop hook only: the warning shows at the end of a turn, when the model
    paused or finished — never at the start of a turn or between tool calls.
    Returns the advice text when a mark was just passed, else None. One warning per mark, never re-sent
    (the highest crossed one when several are jumped at once); the marks re-arm after a compact."""
    if in_subagent(data):
        return None
    path = data.get("transcript_path") or ""
    remember_transcript(data, st)
    tokens = context_tokens(path)
    if tokens is None:
        return None
    marks = context_marks(project_root(data, st))
    crossed = [m for m in marks if tokens >= m * 1000]
    warned = st.get("context_warned_at", 0)
    # a receipt printed since the last spawn closes the task (best effort — see receipt_printed_after)
    if st.get("spawns_since_receipt") and not background_running(data.get("session_id", "")) and receipt_printed_after(path, st.get("last_spawn_offset", 0)):
        reset_task(st)
    in_task = st.get("spawns_since_receipt", 0)
    if not crossed:
        if warned:
            st["context_warned_at"] = 0  # compacted: arm every mark again
        return None
    mark = crossed[-1]
    if warned >= mark:
        return None
    st["context_warned_at"] = mark
    return context_block(tokens, mark, marks, in_task)


def newest_transcript():
    """The transcript of the session that ran a hook most recently (its state file is the newest), else the
    newest transcript on disk. A command run from a session always fires the guard first, so this is that session."""
    try:
        states = sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in states[:3]:
            tp = (json.loads(p.read_text()) or {}).get("transcript_path")
            if tp and os.path.exists(tp):
                return Path(tp)
    except Exception:
        pass
    try:
        files = [p for p in (Path.home() / ".claude" / "projects").glob("*/*.jsonl")]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except Exception:
        return None


def state_path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id or "") or "unknown"
    return STATE_DIR / f"{sid}.json"


def load_state(session_id):
    try:
        return json.loads(state_path(session_id).read_text())
    except Exception:
        return {}


def save_state(session_id, st):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_path(session_id).write_text(json.dumps(st))
    except Exception:
        pass


class state_lock:
    """Parallel tool calls run hooks concurrently; serialise read-modify-write of the state file."""
    def __init__(self, session_id):
        self.path = state_path(session_id).with_suffix(".lock")
        self.fh = None
    def __enter__(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            self.fh = open(self.path, "w")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except Exception:
            self.fh = None
        return self
    def __exit__(self, *a):
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            except Exception:
                pass


def read_input():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        if (Path.home() / ".abofles" / "debug").exists():
            with open(Path.home() / ".abofles" / "debug.log", "a") as f:
                f.write(json.dumps({"mode": sys.argv[1] if len(sys.argv) > 1 else "", "ts": int(time.time()), "keys": sorted(data.keys()),
                                    "tool": data.get("tool_name"), "agent_id": data.get("agent_id"), "agent_type": data.get("agent_type"), "effort": data.get("effort"), "model": data.get("model"),
                                    "transcript": os.path.basename(data.get("transcript_path") or "")}) + "\n")
    except Exception:
        pass
    return data


def session_effort(data):
    """The session's effort level as Claude Code passes it to hooks (`effort: {"level": "high"}`), or None."""
    e = data.get("effort")
    if isinstance(e, dict):
        e = e.get("level")
    e = (e or "").strip().lower() if isinstance(e, str) else ""
    return e if e in EFFORTS else None


def in_subagent(data):
    """True when the hook fires inside a subagent: its output would reach the subagent, not the main session."""
    if data.get("agent_id") or data.get("agent_type"):
        return True
    return os.path.basename(data.get("transcript_path") or "").startswith("agent-")


def transcript_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def remember_transcript(data, st):
    """Keep this session's transcript path and effort in its state file, for `tokens`, bill.py and status.py (no stdin)."""
    if data.get("transcript_path"):
        st["transcript_path"] = data["transcript_path"]
    if data.get("cwd") and not in_subagent(data):
        st["cwd"] = data["cwd"]  # lets the CLIs find *this* project's session among several open ones
    e = session_effort(data)
    if e:
        st["effort"] = e
    st["last_activity"] = int(time.time())


def refresh_main_model(data, st):
    """Read the main session's model from its transcript (1MB tail) — only at start, post and Stop, not on every read."""
    tp = data.get("transcript_path") or st.get("transcript_path")
    if tp and not in_subagent(data):
        mm = main_model(tp)
        if mm:
            st["main_model"] = mm


def effort_note(data, st):
    """Once per session (and again when it changes): tell the model its own effort level — the skill's Step 0 needs it."""
    e = session_effort(data)
    if not e or st.get("effort_told") == e:
        return None
    st["effort_told"] = e
    return f"abofles: this session runs at effort `{e}` (read from the session settings by the hook). Use it in Step 0 and in the `main:` line; no need to call get_session."


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


MAIN_SUGGEST = {1: ("sonnet", "medium"), 2: ("sonnet", "medium"), 3: ("opus", "medium"), 4: ("opus", "high")}  # Step 0 table by tier


def main_line(st, tier):
    """The Step 0 `main:` line for this task, computed by the hook so it is never skipped: `fits` when the session's
    model and effort match the tier's suggestion, else the suggestion with the current setting."""
    t = tier or st.get("task_tier_max") or 2
    sm, se = MAIN_SUGGEST.get(t, ("opus", "medium"))
    cm, ce = st.get("main_model"), st.get("effort")
    if not cm:
        return None
    tn = tier_name(t) + ("" if tier or st.get("task_tier_max") else " (tier unknown — no abofles header)")
    if cm == sm and (not ce or ce == se):
        return f"main: {label(cm, ce)} fits this {tn} task" + ("" if ce else f" (suggested effort {EFFORT_LABEL[se]}, yours unknown)")
    return f"main: suggest {label(sm, se)} for this {tn} task (now {label(cm, ce) if ce else label(cm) + ' · effort unknown'}). Switch in the model picker, or say \"keep\"."


def midturn_receipt(data, st):
    """The newest receipt printed by the main thread since the last spawn, parsed — or None. Lets a receipt printed
    mid-turn close its task (the Stop hook only sees the turn's last message)."""
    if not st.get("spawns_since_receipt") or st.get("inflight"):
        return None
    tp = data.get("transcript_path") or st.get("transcript_path") or ""
    for t in reversed(assistant_texts_after(tp, st.get("last_spawn_offset", 0))):
        if has_receipt(t):
            return parse_receipt(t)
    return None


def pre(data):
    if data.get("tool_name") != "Agent":
        return
    ti = data.get("tool_input") or {}
    if ti.get("prompt", "").lstrip().startswith("abofles:skip"):
        return
    model = (ti.get("model") or "").strip().lower()
    effort = (ti.get("effort") or "").strip().lower()
    stype = ti.get("subagent_type") or ""
    problems = []
    if model not in MODELS:
        problems.append(f"model={model or 'missing'} (need one of {sorted(MODELS)})")
    if effort not in EFFORTS:
        problems.append(f"effort={effort or 'missing'} (need one of low|medium|high|xhigh|max)")
    if model == "fable" and any(s in stype for s in NO_FABLE):
        problems.append(f"fable is only for the Analyse and Plan sides; {stype} is not one")
    if problems:
        deny(
            "Abo Fles (ابو فليس) blocked this spawn: " + "; ".join(problems)
            + ". Route it first with the abofles skill (topic -> tier -> side), then pass both "
            "`model` and `effort` on the Agent call. To bypass once, start the prompt with `abofles:skip`."
        )
    if in_subagent(data):
        return
    sid = data.get("session_id", "")
    _, _, tier = parse_header(ti.get("prompt") or "")
    is_q = side_of(stype)[0] in ("judge", "explainer")
    with state_lock(sid):
        st = load_state(sid)
        cwd = project_root(data, st)
        remember_transcript(data, st)
        en = effort_note(data, st)
        if "started" in st and gate_needed(cwd, st):
            save_state(sid, st)
            deny("Abo Fles (ابو فليس): agent gate first — " + gate_question(st))
        close_stale_pending(st, sid, cwd)
        mid = midturn_receipt(data, st)  # a receipt printed between spawns (long autonomous turns) ends that task here, not at Stop
        if mid:
            reset_task(st)
        st["task_tier_max"] = max(st.get("task_tier_max") or 0, tier or 0)
        budget, src = task_budget(cwd, st, tier)
        used = budget_used(st) + st.get("inflight", 0)
        no_tier = not tier and not st.get("task_tier_max") and src.startswith("auto")
        cap = st.get("task_parallel") or parallel_cap(cwd)
        running = pending_count(sid) + st.get("inflight_bg", 0)
        over_budget = budget is not None and used >= budget and not is_q
        over_cap = bool(cap and ti.get("run_in_background") and running >= cap)
        ml = None
        if not over_budget and not over_cap and not is_q and work_spawns(st) == 0 and not st.get("inflight"):
            refresh_main_model(data, st)
            ml = main_line(st, tier)  # the task's first work spawn: hand over the Step 0 line so it is printed every task
        if not over_budget and not over_cap:  # reserve the slot now: parallel Agent calls run their hooks at the same time
            if not is_q:
                st["inflight"] = st.get("inflight", 0) + 1
            if ti.get("run_in_background"):
                st["inflight_bg"] = st.get("inflight_bg", 0) + 1
        save_state(sid, st)
    if mid:
        memo_journal(cwd, sid, mid)
    if over_budget:
        deny(f"Abo Fles (ابو فليس): this task's agent budget is {budget} ({src}{' — tier unknown: no `abofles: <Topic> / <Side> · T<n>` first line, sized as Normal' if no_tier else ''}) and {used} already ran or are running. Finish in the main session, "
             f"or ask the user to raise it (`/abofles:agents N`, or `agents N` in chat → run `python3 \"{Path(__file__).resolve().parent.parent / 'scripts' / 'agents.py'}\" set N`).")
    if over_cap:
        deny(f"Abo Fles (ابو فليس): {cap} background agents are already running (Parallel = {cap}). Wait for one to finish, or raise `Parallel` in the override block.")
    msgs = [m for m in (en, f"abofles: new task — print this line once, now (as the next line of your reply), exactly as given: `{ml}`" if ml else None) if m]
    if msgs:
        msg = "\n\n".join(msgs)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
              "permissionDecisionReason": msg.splitlines()[0], "additionalContext": msg}}))


def parse_header(prompt):
    """First line `abofles: <Topic> / <Side> · T<tier>` written by the skill. Side is a full word (Read, Analyse, Plan, Work, Verify); old one-letter codes still parse."""
    m = re.match(r"\s*abofles:\s*(.+?)\s*/\s*(Read|Analyse|Analyze|Plan|Work|Verify|Judge|Explain|[RAPWVJE])\b.*?(?:T([1-4]))?\s*$", prompt.splitlines()[0] if prompt else "", re.I)
    if not m:
        return None, None, None
    side = m.group(2)
    side = SIDE_FULL.get(side.upper(), side.capitalize().replace("Analyze", "Analyse")) if len(side) == 1 else side.capitalize().replace("Analyze", "Analyse")
    return m.group(1).strip(), side, (int(m.group(3)) if m.group(3) else None)


def response_text(resp):
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for k in ("content", "result", "output", "text"):
            if k in resp:
                return response_text(resp[k])
        return json.dumps(resp)
    if isinstance(resp, list):
        return "\n".join(response_text(x) for x in resp)
    return str(resp)


def tail_section(text, names):
    """Text from the first of the named sections (GAPS:, LEFT:, ...) to the end."""
    m = re.search(r"^\s*(" + "|".join(names) + r"):", text, re.M)
    return text[m.start():] if m else ""


SIDES = ("reader", "analyst", "planner", "worker", "verifier", "judge", "explainer")
LAST_SECTION = {"reader": "GAPS", "analyst": "RECOMMENDATION", "planner": "OPEN", "worker": "LEFT", "verifier": "NOTE", "judge": "EXPLAIN", "explainer": "EXPLAIN"}


def side_of(stype):
    k = next((k for k in SIDES if k in (stype or "")), "")
    return k, {"reader": "Read", "analyst": "Analyse", "planner": "Plan", "worker": "Work", "verifier": "Verify", "judge": "Judge", "explainer": "Explain"}.get(k, "?")


def resolve_cited(cwd, rel):
    """A cited repo-relative path, looked up from cwd, then its parents (3 levels) and its first-level folders — a
    workspace holds several repos and the agent may cite paths from another one's root. Returns the file or None."""
    if not rel:
        return None
    if os.path.isabs(rel):
        return rel if os.path.exists(rel) else None
    if "..." in rel or "…" in rel:
        return "abbreviated"  # `.../Handler.cs` — a shortened repeat of a path cited in full above, not a claim
    bases = [cwd or os.getcwd()]
    here = Path(cwd or os.getcwd())
    bases += [str(x) for x in list(here.parents)[:3]]
    try:
        subs = [d for d in here.iterdir() if d.is_dir() and not d.name.startswith(".")][:40]
        bases += [str(d) for d in subs]
        for d in subs:  # a workspace folder holding several repos: DCMP.Workspace/DCMP.BE/src/...
            bases += [str(x) for x in d.iterdir() if x.is_dir() and not x.name.startswith(".")][:40]
    except Exception:
        pass
    for b in bases:
        full = os.path.join(b, rel)
        if os.path.exists(full):
            return full
    return None


def analyze(text, stype, cap, cwd):
    """Check one reply. Returns (fields, warnings)."""
    kind, _ = side_of(stype)
    lines = [l for l in text.splitlines() if l.strip()]
    has_header = bool(re.search(r"^\s*STATUS:\s*(done|partial|blocked)", text, re.M)) and \
        bool(re.search(r"^\s*CONFIDENCE:\s*(high|medium|low)", text, re.M))
    status = (re.search(r"^\s*STATUS:\s*(\w+)", text, re.M) or [None, None])[1]
    conf = (re.search(r"^\s*CONFIDENCE:\s*(\w+)", text, re.M) or [None, None])[1]
    adjusted = []

    # a `done` header while GAPS/LEFT/OPEN admit unanswered requested parts -> partial
    admit = re.compile(r"\b(not (read|confirmed|checked|verified|collected|resolved|run|tested)|unresolved|unverified|could not|couldn't|skipped|needs? a read|left out|did not (read|check|verify|run))\b", re.I)
    # only the reader's GAPS and the worker's LEFT describe unanswered *requested* work;
    # OPEN (owner questions) and NOTE (attention text) are never scanned
    tail = tail_section(text, ("GAPS", "LEFT")) if kind in ("reader", "worker") else ""
    tail = tail.split("\nNOTE:")[0] if tail else tail
    out_of_scope = re.search(r"out of scope|outside (the )?scope|excluded by (the )?prompt|not in scope", tail or "", re.I)
    if status == "done" and tail and admit.search(tail) and not out_of_scope and not re.search(r"^\s*(GAPS|LEFT):\s*none\b", tail, re.I | re.M):
        status = "partial"
        adjusted.append("STATUS downgraded to partial: GAPS/LEFT admits unanswered parts")

    # `partial` whose GAPS/LEFT says none is finished work with a note (a cap overflow handled by `+N more`, a remark) -> done
    if status == "partial" and kind in ("reader", "worker") and re.search(r"^\s*(GAPS|LEFT):\s*none\b", tail or "", re.I | re.M):
        status = "done"
        adjusted.append("STATUS upgraded to done: GAPS/LEFT is none, so nothing requested is missing — no escalation")

    # planner: `partial` with owner questions in OPEN is not a failure, it is input needed
    owner_input = False
    if kind == "planner" and status == "partial":
        open_line = re.search(r"^\s*OPEN:\s*(.+)$", text, re.M)
        if open_line and not re.match(r"none\b", open_line.group(1).strip(), re.I):
            owner_input = True
    # worker: `partial` whose LEFT is an owner decision (not unfinished work) is input needed, not escalation
    if kind == "worker" and status == "partial":
        left_line = re.search(r"^\s*LEFT:\s*(.+)$", text, re.M)
        if left_line and re.search(r"owner.?s? ?decision|decision for (the )?owner|owner (must|needs? to|has to) (decide|choose|confirm|pick)|needs? (an )?owner", left_line.group(1), re.I):
            owner_input = True

    # reader citing a path that does not exist, or a line past the end of the file -> low
    bad_paths = []
    bad_lines = []
    if kind == "reader":
        seen = set()
        cited = set()
        for m in re.finditer(r"(?<![\w./\-])(/?(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]{1,6}):(\d+)", text):
            path, ln = m.group(1), int(m.group(2))
            rel = path[len(cwd) + 1:] if cwd and path.startswith(cwd.rstrip("/") + "/") else path
            full = resolve_cited(cwd, rel) or (path if os.path.exists(path) else None)
            if full == "abbreviated":
                continue
            cited.add(rel)
            if not full:
                if rel not in seen:
                    seen.add(rel)
                    bad_paths.append(rel)
                continue
            try:
                with open(full, "rb") as f:
                    n = sum(1 for _ in f)
                if ln > n and f"{rel}:{ln}" not in bad_lines:
                    bad_lines.append(f"{rel}:{ln}")
            except Exception:
                pass
        if bad_paths and len(bad_paths) * 2 >= len(cited):  # most cited paths missing (searched cwd, its parents and its folders)
            conf = "low"
            adjusted.append("CONFIDENCE downgraded to low: paths not found: " + ", ".join(bad_paths[:5]))
        elif bad_paths:
            adjusted.append("some cited paths not found (" + ", ".join(bad_paths[:3]) + ") — check them before relying on those facts")
        if bad_lines:
            conf = "low"
            adjusted.append("CONFIDENCE downgraded to low: line past end of file (a grep count pasted as a line?): " + ", ".join(bad_lines[:5]))

    # trailing text after the last section, and absolute paths anywhere
    trailing = 0
    abs_paths = []
    if kind in ("judge", "explainer"):
        abs_paths = sorted(set(re.findall(r"(?<![\w])(/(?:Users|home|var|tmp|opt|mnt|srv|private)/[^\s:`'\")]+|[A-Za-z]:\\[^\s:`'\")]+)", text)))
    elif kind:
        last = LAST_SECTION[kind]
        m = re.search(r"^\s*" + last + r":.*$", text, re.M)
        if m:
            after = [l for l in text[m.end():].splitlines() if l.strip() and l.strip() != "```"]
            if last == "OPEN":
                # one line per owner question is part of OPEN, not trailing text
                after = [l for l in after if not (re.search(r"\?.*assumed:", l, re.I) or l.lstrip().startswith("- "))]
            trailing = max(0, len(after) - (1 if last == "RECOMMENDATION" else 0))
        abs_paths = sorted(set(re.findall(r"(?<![\w])(/(?:Users|home|var|tmp|opt|mnt|srv|private)/[^\s:`'\")]+|[A-Za-z]:\\[^\s:`'\")]+)", text)))

    verdict = (re.search(r"^\s*VERDICT:\s*(PASS|FAIL)", text, re.M) or [None, None])[1]
    attention = bool(re.search(r"^\s*NOTE:\s*ATTENTION\b", text, re.M))
    open_questions = len(re.findall(r"\?.*assumed:", text, re.I)) if kind == "planner" else 0
    chars = sum(len(l) for l in lines)
    avg = chars / len(lines) if lines else 0
    # content lines = what the cap counts: not the header, not section labels, not the one-line tail sections
    label = re.compile(r"^\s*(STATUS|CONFIDENCE|VERDICT|FACTS|FINDINGS|PLAN|RISKS|CHANGED|EVIDENCE|ISSUES|GAPS|LEFT|OPEN|NOTE|RECOMMENDATION|RAN|VERIFY):\s*$", re.I)
    tail_line = re.compile(r"^\s*(STATUS|CONFIDENCE|VERDICT|GAPS|LEFT|NOTE|RECOMMENDATION|RAN|VERIFY):", re.I)
    content_lines = [l for l in lines if not label.match(l) and not tail_line.match(l) and l.strip() != "```"]

    fields = {
        "reply_lines": len(lines),
        "content_lines": len(content_lines),
        "reply_chars": chars,
        "open_questions": open_questions or None,
        "status": status,
        "confidence": conf,
        "verdict": verdict,
        "attention": attention or None,
        "owner_input": owner_input or None,
        "trailing_lines": trailing or None,
        "abs_paths": len(abs_paths) or None,
        "adjusted": adjusted or None,
        "bad_paths": bad_paths or None,
        "bad_lines": bad_lines or None,
    }

    warnings = list(adjusted)
    if not (stype or "").startswith("abofles:"):
        # other agent types (project agents, general-purpose) have their own reply format: only the verdict signals apply
        if verdict == "FAIL":
            warnings.append("VERDICT: FAIL — a criterion failed; fix via a W agent at the same or next setting, then re-verify. Do not accept the work")
        elif attention:
            warnings.append("verifier NOTE: ATTENTION — criteria pass but a critical issue outside them exists; show it to the user before closing")
        return fields, warnings
    # list lines (facts, findings, steps, changes, evidence, issues, risks) must stay short;
    # the one-line sections (GAPS, LEFT, OPEN, NOTE, RECOMMENDATION, RAN, VERIFY) may run longer
    one_line = re.compile(r"^\s*(GAPS|LEFT|OPEN|NOTE|RECOMMENDATION|RAN|VERIFY|STATUS|CONFIDENCE|VERDICT):|^\s*\+\d+ more:", re.I)
    long_lines = [] if kind in ("judge", "explainer") else [l for l in lines if len(l) > (400 if one_line.match(l) else 200)]
    if long_lines:
        sample = long_lines[0].strip()[:70]
        warnings.append(f"{len(long_lines)} line(s) too long (list lines max 200 chars, one-line sections max 400), e.g. \"{sample}…\" — split into one fact per line")
    if re.search(r"^\s*\+N more:", text, re.M):
        warnings.append("literal `+N more:` in reply — the agent copied the template; N must be the real count")
    if trailing:
        warnings.append(f"{trailing} line(s) after the last section — not part of the format; ignore them and ask for none next time")
    if abs_paths and kind not in ("judge", "explainer"):
        warnings.append(f"absolute paths in reply ({abs_paths[0][:60]}…) — require repo-relative paths")
    if verdict == "FAIL":
        warnings.append("VERDICT: FAIL — a criterion failed; fix via a W agent at the same or next setting, then re-verify. Do not accept the work")
    elif attention:
        warnings.append("verifier NOTE: ATTENTION — criteria pass but a critical issue outside them exists; show it to the user before closing")
    if kind and not has_header:
        warnings.append(f"reply from {stype} has no STATUS/CONFIDENCE header — treat CONFIDENCE as low")
    if cap and len(content_lines) > cap + 2:
        warnings.append(f"reply has {len(content_lines)} content lines, cap was {cap} — over the cap; ask for ranking and `+<n> more:` next time")
    if owner_input and kind == "worker":
        warnings.append("worker STATUS=partial because LEFT holds an owner decision — owner input needed, not escalation; put the decision under `open` in the receipt and ask the user. Next time the agent should write `LEFT: none (owner decision: …)` and STATUS done")
    elif owner_input:
        warnings.append("planner STATUS=partial with OPEN questions — owner input needed, not escalation; ask the user, then re-plan or proceed with the stated defaults")
    elif (conf == "low" or status in ("partial", "blocked")) and kind not in ("judge", "explainer"):
        warnings.append(f"STATUS={status} CONFIDENCE={conf} — escalation rule applies (Step 4), do not re-run at the same setting")
    return fields, warnings


def ledger_path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id or "") or "unknown"
    return LEDGER_DIR / f"{sid}.jsonl"


def emit(event, warnings, extra=None):
    msg = "\n\n".join(m for m in (("abofles: " + "; ".join(warnings)) if warnings else None, extra) if m)
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": msg}}))


def post(data):
    if data.get("tool_name") != "Agent":
        return
    ti = data.get("tool_input") or {}
    prompt = ti.get("prompt") or ""
    stype = ti.get("subagent_type") or ""
    topic, side, tier = parse_header(prompt)
    if side is None:
        side = side_of(stype)[1]
    cap_m = re.search(r"Line cap:\s*(\d+)", prompt)
    cap = int(cap_m.group(1)) if cap_m else None
    resp = data.get("tool_response")
    agent_id = resp.get("agentId") if isinstance(resp, dict) else None
    is_async = isinstance(resp, dict) and (resp.get("status") == "async_launched" or resp.get("isAsync") is True)

    entry = {
        "ts": int(time.time()),
        "session": data.get("session_id", ""),
        "cwd": data.get("cwd", ""),
        "agent_id": agent_id,
        "topic": topic,
        "side": side,
        "tier": tier,
        "model": (ti.get("model") or "").lower() or None,
        "effort": (ti.get("effort") or "").lower() or None,
        "agent": stype,
        "cap": cap,
        "description": ti.get("description", "")[:80],
    }
    warnings = []
    kind = side_of(stype)[0]
    unlock = 0
    if is_async:
        entry["status"] = "pending"
        entry["confidence"] = None
    else:
        text = response_text(resp)
        fields, warnings = analyze(text, stype, cap, project_root(data, load_state(data.get("session_id", ""))))  # paths resolve from the project root, not a drifted shell cwd
        entry.update(fields)
        if kind in ("judge", "explainer"):
            blocks = judge_blocks(text) if kind == "judge" else [judge_fields(text)]
            verdicts = [b[0] for b in blocks]
            verdict = "HANDOFF" if "HANDOFF" in verdicts else "ASK" if "ASK" in verdicts else (verdicts[0] if verdicts else "")
            q, a, ev = next(((b[1], b[2], b[3]) for b in blocks if b[0] == verdict), ("", "", ""))
            entry["verdict"] = verdict or None
            mroot = project_root(data, load_state(data.get("session_id", "")))
            if kind == "judge":
                for v, q1, a1, e1 in blocks:
                    if v == "ANSWERED" and q1:
                        memo_decision(mroot, data.get("session_id", ""), f"judge: {q1}", f"{a1}" + (f" ({e1})" if e1 else ""))
                        if (tier or 3) >= 3:  # a silent wrong answer on a sensitive decision must still reach the user's list
                            memo_needs(mroot, data.get("session_id", ""), f"judge decided ({tier_name(tier or 3)}): {q1} → {a1} — check")
                answered = [b for b in blocks if b[0] == "ANSWERED"]
                if answered and verdict != "ANSWERED":
                    warnings.append("judge ANSWERED " + "; ".join(f"{b[1]} → {b[2]}" for b in answered) + " — state those in one line each, do not ask them; the remaining question(s) below")
            if kind == "judge" and verdict == "ANSWERED":
                warnings.append("judge ANSWERED from evidence — state it in one line and continue, do not ask the user: " + "; ".join(f"{b[1]} → {b[2]}" + (f" ({b[3]})" if b[3] else "") for b in blocks))
            elif kind == "judge" and verdict == "HANDOFF":
                if (tier or 3) <= 2:
                    warnings.append("judge returned HANDOFF on a Minor/Normal question — it must explain itself; re-spawn it with the tier stated, or spawn the explainer")
                else:
                    warnings.append(f"judge HANDOFF — spawn `abofles:abofles-explainer` ({label(*QUESTION_ROUTE[tier or 3][2:])}) with its QUESTION, EVIDENCE and WHY, then ask")
            else:
                unlock = 1
                md = explain_needs_markdown(text)
                warnings.append(ASK_MD if md else ASK_PLAIN)
                with state_lock(data.get("session_id", "")):
                    stx = load_state(data.get("session_id", ""))
                    stx["explain_md"], stx["explain_denies"] = bool(md), 0
                    save_state(data.get("session_id", ""), stx)
        entry["warnings"] = warnings or None
    # orchestrator guard: a spawn resets the direct-read streak; receipt check: one more spawn this turn
    with state_lock(data.get("session_id", "")):
        st = load_state(data.get("session_id", ""))
        st["direct_reads"] = 0
        st["guard_warned_at"] = 0
        st["spawns"] = st.get("spawns", 0) + 1
        st["spawns_since_receipt"] = st.get("spawns_since_receipt", 0) + 1
        if kind in ("judge", "explainer"):
            st["task_judges"] = st.get("task_judges", 0) + 1  # question-gate spawns do not eat the agent budget
        else:
            st["inflight"] = max(0, st.get("inflight", 0) - 1)  # the slot reserved in pre is now a counted spawn
        if is_async:
            st["inflight_bg"] = max(0, st.get("inflight_bg", 0) - 1)  # now a `pending` ledger row
        if unlock:
            st["judge_ok"] = st.get("judge_ok", 0) + unlock
        st["task_units"] = st.get("task_units", 0.0) + units(entry["model"], entry["effort"])
        remember_transcript(data, st)
        refresh_main_model(data, st)  # before pricing: the baseline is the main session's current model
        st["task_base"] = st.get("task_base", 0.0) + units(st.get("main_model") or "opus", st.get("effort") or "high")
        if not is_async:
            entry.update(add_spend(st, entry["session"], agent_id, entry["model"], f"{side} {label(entry['model'], entry['effort'])}"))  # real tokens + $ from its transcript
        st["last_spawn_offset"] = transcript_size(data.get("transcript_path") or "")
        root = project_root(data, st)
        st["running_bg"] = pending_count(data.get("session_id", ""))
        save_state(data.get("session_id", ""), st)
        try:  # the ledger row below is not written yet: write it first so the guide sees this spawn
            LEDGER_DIR.mkdir(parents=True, exist_ok=True)
            with open(ledger_path(entry["session"]), "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            entry["_written"] = True
        except Exception:
            pass
        refresh_guide(root, st, data.get("session_id", ""))
        _, instruction = receipt_decision(root, st)
        budget, bsrc = task_budget(root, st, entry.get("tier"))
        used, total = budget_used(st), st.get("spawns", 0)
        if not tier and not is_async and (stype or "").startswith("abofles:") and kind not in ("judge", "explainer"):
            warnings.append("no `abofles: <Topic> / <Side> · T<tier>` first line in the prompt — tier unknown, so the agent budget was sized as 🟡 Normal and the ledger has no topic; put the header first next time")
        save_state(data.get("session_id", ""), st)
        if not entry.pop("_written", False):
            try:  # under the lock: stop() rewrites this file
                LEDGER_DIR.mkdir(parents=True, exist_ok=True)
                with open(ledger_path(entry["session"]), "a") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass
    if budget is not None and used == budget - 1 and budget > 1:
        warnings.append(f"1 spawn left in this task's agent budget ({budget}, {bsrc})")
    elif budget is not None and used >= budget:
        warnings.append(f"agent budget {budget} reached for this task ({bsrc}) — the next spawn is denied unless the user raises it")
    if total in (20, 50, 100, 200):
        warnings.append(f"{total} spawns this session so far — if the user did not ask for a run of this size, say so in one line with /abofles:bill's $")
    rnote = None if receipt_mode(root)[0] == "off" else instruction

    # session cap from the project override block
    cap_units = session_cap(root)
    if cap_units:
        try:
            rows = [json.loads(l) for l in ledger_path(entry["session"]).read_text().splitlines() if l.strip()]
            spent = sum(units(r.get("model"), r.get("effort")) for r in rows)
        except Exception:
            spent = 0
        if spent > cap_units:
            warnings.append(f"session cap {cap_units} units passed (now {spent:.0f}) — stop spawning and ask the user before the next spawn")
    emit("PostToolUse", warnings, rnote)


def start(data):
    """SessionStart: the marker the guard gates on, so it works from the first turn (before any spawn)."""
    sid = data.get("session_id", "")
    src = data.get("source") or "startup"
    with state_lock(sid):
        st = load_state(sid)
        st["started"] = int(time.time())
        st["direct_reads"] = 0
        reset_task(st)
        remember_transcript(data, st)
        if data.get("cwd") and (not st.get("root") or src in ("startup", "clear")):
            st["root"] = data["cwd"]  # the project root for memo and overrides: fixed here, never moved by a later `cd`
        refresh_main_model(data, st)
        en = effort_note(data, st)
        root = project_root(data, st)
        g = refresh_guide(root, st, sid)
        save_state(sid, st)
    if en:
        print(en)
    if memo_path(root).exists():
        git_exclude_memo(root)  # memos written before this rule existed
    block = resume_block(root, session_id=sid, guide=g)
    if block:
        print(resume_note(block, {"compact": "context was just compacted", "resume": "session resumed", "clear": "context cleared"}.get(src, "new session, memo found")))


def newest_state_path(cwd=None):
    """The state file of the most recently active session — preferring one whose cwd is this project when several
    sessions are open (a command runs in the project's directory; its own session touched the state last there)."""
    try:
        states = sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return None
    want = os.path.realpath(cwd or os.getcwd())
    inside = None
    for sp in states:
        try:
            st = json.loads(sp.read_text())
            root = os.path.realpath(st.get("root") or st.get("cwd") or "")
            if root and want == root:
                return sp
            if root and inside is None and want.startswith(root.rstrip("/") + "/"):
                inside = sp  # a command run from a subfolder of the project (after a `cd`) still belongs to that session
        except Exception:
            continue
    return inside or (states[0] if states else None)


def newest_session_id(cwd=None):
    sp = newest_state_path(cwd)
    return sp.stem if sp else ""


def newest_state(cwd=None):
    sp = newest_state_path(cwd)
    try:
        return json.loads(sp.read_text()) if sp else {}
    except Exception:
        return {}


READ_CMD = re.compile(r"^\s*(?:cd\s+\S+\s*&&\s*)?(grep|rg|ag|find|fd|cat|head|less|sed\s+-n|awk|ls|tree|git\s+(grep|log|show|blame|diff|status)|jq|python3\s+-c\s+['\"]print)\b")
WRITE_CMD = re.compile(r"(^|[^<>])>>?\s*[^&|]|<<|\btee\b")  # output redirected into a file, a heredoc, tee: not a read
MCP_READ = re.compile(r"^mcp__.*__(get|search|read|list|fetch|query|view|find|lookup|describe|execute_?read)(?!en|_?or_?create|_?and_?replace)", re.I)


def guard(data):
    """PreToolUse on Read/Grep/Glob and read-only Bash: more than 3 direct reads in a row means the main session
    is doing a Read agent's job. Warn via additionalContext (an `allow` reason is shown to the user only), never block.
    The desktop Code tab has no Grep/Glob tools, so Bash `grep`/`find`/`cat` count too; any other Bash breaks the streak."""
    tool = data.get("tool_name") or ""
    if in_subagent(data):
        return
    if tool.startswith("mcp__"):
        if not MCP_READ.match(tool):
            return  # a connector write or action: not a read, not a streak breaker either
        is_read = True
    elif tool not in ("Read", "Grep", "Glob", "Bash"):
        return
    elif tool == "Bash":
        cmd = (data.get("tool_input") or {}).get("command", "")
        bare = re.sub(r"'[^']*'|\"[^\"]*\"|\d?>&\d", "", cmd)  # a `>` inside quotes or `2>&1` is not a redirect into a file
        is_read = bool(READ_CMD.match(cmd)) and not WRITE_CMD.search(bare)
    else:
        is_read = True
    sid = data.get("session_id", "")
    with state_lock(sid):
        st = load_state(sid)
        if "started" not in st:
            return  # plugin not active in this session (no SessionStart marker)
        remember_transcript(data, st)
        en = effort_note(data, st)
        threshold = None
        if not is_read:
            st["direct_reads"] = 0
            st["guard_warned_at"] = 0
        else:
            st["direct_reads"] = st.get("direct_reads", 0) + 1
            n = st["direct_reads"]
            last = st.get("guard_warned_at", 0)
            threshold = next((t for t in GUARD_MARKS[pace(project_root(data, st))] if n >= t and last < t), None)
            if threshold:
                st["guard_warned_at"] = threshold
        save_state(sid, st)
    msgs = []
    if en:
        msgs.append(en)
    if threshold:
        msgs.append(f"abofles: {n} direct reads in a row by the main session (files, shell reads and connector lookups such as Jira) — "
                    f"in orchestrator mode this is a Read agent's job (haiku·low). Spawn one with a numbered question list, or finish in ≤3 calls.")
    if msgs:
        msg = "\n\n".join(msgs)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
              "permissionDecisionReason": msg.splitlines()[0], "additionalContext": msg}}))


def prompt(data):
    """UserPromptSubmit: the session effort note. The context watch runs at Stop, not here."""
    if in_subagent(data):
        return
    sid = data.get("session_id", "")
    rn = None
    with state_lock(sid):
        st = load_state(sid)
        cwd = project_root(data, st)
        last = st.get("last_activity")
        remember_transcript(data, st)
        en = effort_note(data, st)
        close_stale_pending(st, sid, cwd)
        mins = break_minutes(cwd)
        ptxt = (data.get("prompt") or "").lstrip()
        notification = ptxt.startswith("<") or "task-notification" in ptxt[:200] or "hand-back" in ptxt[:200].lower()
        if last and mins and not notification and (time.time() - last) >= mins * 60:
            away = int((time.time() - last) // 60)
            block = resume_block(cwd, away, session_id=sid, guide=refresh_guide(cwd, st, sid))
            if block:
                rn = resume_note(block, f"the user was away {span(away)}")
        save_state(sid, st)
    msg = "\n\n".join(m for m in (en, rn) if m)
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))


def background_running(session_id):
    """True when the ledger holds a background spawn of this session that has not completed yet."""
    try:
        return any(json.loads(l).get("status") == "pending" for l in ledger_path(session_id).read_text().splitlines() if l.strip())
    except Exception:
        return False


def receipt(data):
    """Stop: (1) if this turn spawned abofles agents and the final message has no receipt block, refuse the stop
    once so the 5-line receipt gets printed (`stop_hook_active` means we already did); (2) the context watch —
    a passed mark refuses the stop once so the warning is the last thing the user sees in the turn. Each mark
    warns once, so the second stop always goes through."""
    if in_subagent(data):
        return
    sid = data.get("session_id", "")
    text = data.get("last_assistant_message") or ""
    reasons = []
    rc = parse_receipt(text) if has_receipt(text) else None
    with state_lock(sid):
        st = load_state(sid)
        if "started" not in st:
            return
        st["last_activity"] = int(time.time())
        st["inflight"], st["inflight_bg"] = 0, 0  # no Agent call outlives the turn: a failed call never ran its post
        refresh_main_model(data, st)
        root = project_root(data, st)
        close_stale_pending(st, sid, root)
        refresh_guide(root, st, sid)
        pending = st.get("spawns_since_receipt", 0)
        unasked = (st.get("judge_ok", 0) > 0 and not data.get("stop_hook_active") and not background_running(sid)
                   and (time.time() - st.get("gate_wait_ts", 0)) > GATE_WAIT)  # before reset_task clears the unlock; not while a gate agent is still replying
        unasked_md = bool(st.get("explain_md"))
        if pending and has_receipt(text):
            reset_task(st)  # the receipt closes the task — even while a background agent of it is still running
        elif pending and not background_running(sid):  # a chain still running: the receipt is due when it ends
            kind, instruction = receipt_decision(root, st)
            if kind == "skip" or data.get("stop_hook_active"):
                reset_task(st)  # the task is closed (receipt not wanted, or the one nudge already spent)
            else:
                reasons.append(f"abofles: this turn spawned {pending} agent(s) and ended without the receipt. Print it now.\n" + instruction.removeprefix("abofles: "))
        elif not pending and st.get("gate") == "task" and not st.get("task_budget"):
            st["gate"], st["task_budget"], st["task_parallel"] = None, None, None  # "Main session only" was for that turn's task
        if st.get("judge_ok", 0) > 0 and not unasked:
            keep_unlock = st["judge_ok"]  # a gate agent is still replying: the unlock survives the task reset below
        else:
            keep_unlock = 0
        if unasked:
            st["judge_ok"] = max(st.get("judge_ok", 0), 1)  # keep the unlock alive for the question that must follow
            st["explain_md"] = unasked_md
            reasons.append("abofles: a judged question is still unasked (the Judge/Explainer unlocked it, no AskUserQuestion followed). Ask it now with AskUserQuestion — "
                           + (f"its markdown explanation goes in your reply text first, under `{EXPLAIN_MARK} **Explanation for the question below**`, then the question with a plain summary inside. " if unasked_md else "QUESTION, WHY and the plain EXPLAIN lines inside the question text. ")
                           + "Never end the turn with \"reply in chat\" instead of the question box.")
        if keep_unlock:
            st["judge_ok"] = max(st.get("judge_ok", 0), keep_unlock)
        cw = context_watch(data, st)
        if cw:
            reasons.append(cw)
        save_state(sid, st)
    if rc:
        memo_journal(root, sid, rc)
    if reasons:
        if len(reasons) == 1 and not cw:
            reasons[0] += " Nothing after it."
        print(json.dumps({"decision": "block", "reason": "\n\n".join(reasons)}))


def close_row(row, text, st, sid, cwd, how=""):
    """Fill a pending ledger row from the agent's final text (or close it without one). Caller holds the state lock."""
    stype = row.get("agent") or ""
    if text:
        fields, warnings = analyze(text, stype, row.get("cap"), row.get("cwd") or cwd)
    else:  # no reply text (killed, timed out): close the row anyway so the chain can end
        fields, warnings = {"status": "blocked", "confidence": "low"}, ["background agent ended without a reply"]
    row.update(fields)
    row.update(add_spend(st, sid, row.get("agent_id"), row.get("model"), f"{row.get('side') or '?'} {label(row.get('model'), row.get('effort'))}"))
    kind = side_of(stype)[0]
    if kind in ("judge", "explainer") and text:
        verdict, q, a, ev = judge_fields(text)
        row["verdict"] = verdict or None
        if kind == "judge" and verdict == "ANSWERED":
            memo_decision(cwd, sid, f"judge: {q}", f"{a}" + (f" ({ev})" if ev else ""))
            if (row.get("tier") or 3) >= 3:
                memo_needs(cwd, sid, f"judge decided ({tier_name(row.get('tier') or 3)}): {q} → {a} — check")
        elif not (kind == "judge" and verdict == "HANDOFF"):
            st["judge_ok"] = st.get("judge_ok", 0) + 1
    row["completed_ts"] = int(time.time())
    if how:
        warnings = list(warnings) + [how]
    row["warnings"] = warnings or None


def write_rows(path, rows):
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        os.replace(tmp, path)
    except Exception:
        pass


def last_assistant_text(path):
    text, _ = last_assistant_reply(path)
    return text


def last_assistant_reply(path):
    """(text, handed_back) of the newest assistant message in a transcript. handed_back is True when the agent ended
    its run with a SubagentHandback call — the background-agent equivalent of a final reply."""
    for line in reversed(transcript_tail(path)):
        if '"assistant"' not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "assistant":
            continue
        parts = (r.get("message") or {}).get("content") or []
        for p in parts:  # a background agent hands its report back through a tool call, not a text block
            if isinstance(p, dict) and p.get("type") == "tool_use" and "handback" in (p.get("name") or "").lower():
                msg = (p.get("input") or {}).get("message") or (p.get("input") or {}).get("report") or ""
                if msg:
                    return str(msg).strip(), True
        text = "\n".join(p.get("text") or "" for p in parts if isinstance(p, dict) and p.get("type") == "text").strip()
        if text:
            return text, False
    return "", False


STALE_AFTER = 90  # seconds without a transcript write: the background agent has finished (or died)


def close_stale_pending(st, sid, cwd):
    """Fallback for a SubagentStop that never reached the hook: a pending row whose transcript stopped growing
    STALE_AFTER seconds ago is closed from that transcript's last assistant text. Caller holds the state lock."""
    path = ledger_path(sid)
    try:
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except Exception:
        return 0
    closed = 0
    for row in rows:
        if row.get("status") != "pending":
            continue
        tp = agent_transcript(st, sid, row.get("agent_id"))
        if not tp or not tp.exists():
            continue
        try:
            age = time.time() - tp.stat().st_mtime
        except Exception:
            continue
        text, handed_back = last_assistant_reply(tp)
        if not handed_back and age < STALE_AFTER:
            continue
        close_row(row, text, st, sid, cwd, how="closed from its transcript (handed back; no SubagentStop)" if handed_back else f"closed from its transcript (no SubagentStop; idle {int(age)}s)")
        closed += 1
    if closed:
        write_rows(path, rows)
    return closed


def stop(data):
    """SubagentStop: fill the `pending` entry written at async launch. Sync spawns have no pending entry (PostToolUse logs them)."""
    agent_id = data.get("agent_id")
    text = data.get("last_assistant_message") or ""
    if not agent_id:
        return
    sid = data.get("session_id", "")
    path = ledger_path(sid)
    with state_lock(sid):  # read-update-write of the ledger and the state, serialised against post() and other stops
        try:
            rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        except Exception:
            return
        idx = next((i for i, r in enumerate(rows) if r.get("agent_id") == agent_id and r.get("status") == "pending"), None)
        if idx is None:
            return
        st = load_state(sid)
        cwd = project_root(data, st)
        if data.get("agent_transcript_path"):
            st["agent_transcripts"] = {**(st.get("agent_transcripts") or {}), agent_id: data["agent_transcript_path"]}
        close_row(rows[idx], text, st, sid, cwd)
        save_state(sid, st)
        write_rows(path, rows)
    # Never print anything here: SubagentStop output goes to the *subagent*, which then takes
    # another turn and its "Understood…" reply replaces the real result. Warnings stay in the
    # ledger (`warnings`) and are shown by /abofles:bill.


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = read_input() if mode != "tokens" else {}
        if mode == "pre":
            pre(data)
        elif mode == "post":
            post(data)
        elif mode == "stop":
            stop(data)
        elif mode == "guard":
            guard(data)
        elif mode == "start":
            start(data)
        elif mode == "receipt":
            receipt(data)
        elif mode == "prompt":
            prompt(data)
        elif mode == "decision":
            decision(data)
        elif mode == "qgate":
            qgate(data)
        elif mode == "sendmsg":
            sendmsg(data)
        elif mode == "tokens":
            p = newest_transcript()
            t = context_tokens(str(p)) if p else None
            e = newest_state().get("effort")
            print((f"context: {t:,} tokens ({t // 1000}K) · transcript {p.name}" if t is not None else "context: unknown (no transcript found)")
                  + (f" · session effort {e}" if e else ""))
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit(0)
