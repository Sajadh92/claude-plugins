#!/usr/bin/env python3
"""Abo Fles hooks for the Agent tool.

    abofles_hook.py pre   -- PreToolUse:   block a spawn with no model/effort
    abofles_hook.py post  -- PostToolUse:  log the spawn; check the reply (sync) or log `pending` (async)
    abofles_hook.py stop  -- SubagentStop: fill the pending async entry from last_assistant_message (ledger only, prints nothing)
    abofles_hook.py guard   -- PreToolUse(Read|Grep|Glob): orchestrator guard — too many direct reads in a row
    abofles_hook.py start   -- SessionStart: write the session marker the guard gates on
    abofles_hook.py receipt -- Stop: refuse the stop once when the turn spawned agents and no receipt was printed
    abofles_hook.py prompt  -- UserPromptSubmit: context watch only (compact advice at 500K/600K/700K/750K/800K/850K/900K)
    abofles_hook.py tokens  -- CLI: print the context size of the newest session transcript (no stdin)

The context watch also runs inside `guard` and `pre` (PreToolUse — the one hook path whose additionalContext is
confirmed to reach the model in the desktop app; PostToolUse context was lost in run 14, so `post` never consumes
a mark). One send per mark, no re-send: PreToolUse/UserPromptSubmit context is delivered reliably to the main session,
and transcript text cannot be trusted for an acknowledgement (the desktop app does not always persist text
written next to a tool call — run 16). The block carries both advice branches; the model picks (no spawn-count hint — the count is stale in a single-turn session).
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
SIDE_FULL = {"R": "Read", "A": "Analyse", "P": "Plan", "W": "Work", "V": "Verify"}
LEDGER_DIR = Path(os.environ.get("ABOFLES_LEDGER_DIR", Path.home() / ".abofles" / "ledgers"))
STATE_DIR = Path(os.environ.get("ABOFLES_STATE_DIR", Path.home() / ".abofles" / "state"))
PRICE = {"haiku": 1, "sonnet": 20, "opus": 40, "fable": 100}
EFFORT = {"low": 0.5, "medium": 1, "high": 1.5, "xhigh": 2.5, "max": 4}


def units(model, effort):
    return PRICE.get(model or "", 40) * EFFORT.get(effort or "", 1.5)


def override_value(cwd, key):
    """`- <key> = <value>` inside the project's `## abofles overrides` block, or None."""
    for name in ("CLAUDE.md", ".claude/CLAUDE.md"):
        try:
            txt = (Path(cwd) / name).read_text()
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


CONTEXT_MARKS = (500, 600, 700, 750, 800, 850, 900)  # thousands of tokens


def context_marks(cwd):
    """`- Context marks = 100, 150, 180` (thousands of tokens) in the override block, else the defaults."""
    v = override_value(cwd, "Context marks")
    marks = sorted({int(x) for x in re.findall(r"\d+", v or "")}) if v else []
    return tuple(marks) or CONTEXT_MARKS


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
    return any("── receipt" in t for t in assistant_texts_after(transcript_path, offset))


def context_block(tokens, mark, marks, in_task):
    """Both advice branches are always in the block; the model knows whether a task is really open, a hook does not
    (the spawn count is stale inside a single long turn — run 17). `in_task` is kept for callers but unused."""
    nxt = next((m for m in marks if m > mark), None)
    nxt_line = f"Next warning at {nxt}K." if nxt else "This is the last mark — compact before the window is full."
    block = (f"# ⚠️ **CONTEXT {tokens // 1000}K — RUN /abofles:memo, THEN /compact**\n"
             f"**Abo Fles (ابو فليس):** this session passed **{mark}K tokens** of context. {nxt_line}\n"
             f"**If no task is open:** stop here — run `/abofles:memo` (hand-off memo: done, left, decisions, next step), **then** `/compact`. Safe between tasks.\n"
             f"**If a task is open** (a chain running, edits half applied, a verifier not back): do **not** compact yet — finish the step, print the receipt, **then** memo and `/compact`.")
    return (f"abofles CONTEXT WATCH: context is {tokens:,} tokens (mark {mark}K passed). Show the user the block below **verbatim, "
            f"first in your next visible output, before anything else** — heading, bold, all four lines — then continue. "
            f"You decide which branch applies.\n\n{block}")


def context_watch(data, st):
    """Call under the state lock, from a hook whose output reaches the model (PreToolUse, UserPromptSubmit).
    Returns the advice text when a mark was just passed, else None. One warning per mark, never re-sent
    (the highest crossed one when several are jumped at once); the marks re-arm after a compact."""
    if in_subagent(data):
        return None
    path = data.get("transcript_path") or ""
    remember_transcript(data, st)
    tokens = context_tokens(path)
    if tokens is None:
        return None
    marks = context_marks(data.get("cwd") or os.getcwd())
    crossed = [m for m in marks if tokens >= m * 1000]
    warned = st.get("context_warned_at", 0)
    # a receipt printed since the last spawn closes the task (best effort — see receipt_printed_after)
    if st.get("spawns_since_receipt") and receipt_printed_after(path, st.get("last_spawn_offset", 0)):
        st["spawns_since_receipt"] = 0
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
    e = session_effort(data)
    if e:
        st["effort"] = e


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
    with state_lock(sid):
        st = load_state(sid)
        remember_transcript(data, st)
        en = effort_note(data, st)
        cw = context_watch(data, st) if "started" in st else None
        save_state(sid, st)
    msg = "\n\n".join(m for m in (en, cw) if m)
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
              "permissionDecisionReason": context_reason(cw) if cw else en, "additionalContext": msg}}))


def context_reason(cw):
    """One user-visible line for the PreToolUse reason field."""
    return f"⚠ abofles CONTEXT WATCH — {cw.split('(', 1)[1].split(')', 1)[0]}: run /abofles:memo, then /compact"


def parse_header(prompt):
    """First line `abofles: <Topic> / <Side> · T<tier>` written by the skill. Side is a full word (Read, Analyse, Plan, Work, Verify); old one-letter codes still parse."""
    m = re.match(r"\s*abofles:\s*(.+?)\s*/\s*(Read|Analyse|Analyze|Plan|Work|Verify|[RAPWV])\b.*?(?:T([1-4]))?\s*$", prompt.splitlines()[0] if prompt else "", re.I)
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


SIDES = ("reader", "analyst", "planner", "worker", "verifier")
LAST_SECTION = {"reader": "GAPS", "analyst": "RECOMMENDATION", "planner": "OPEN", "worker": "LEFT", "verifier": "NOTE"}


def side_of(stype):
    k = next((k for k in SIDES if k in (stype or "")), "")
    return k, {"reader": "Read", "analyst": "Analyse", "planner": "Plan", "worker": "Work", "verifier": "Verify"}.get(k, "?")


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
        for m in re.finditer(r"(?<![\w./\-])(/?(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]{1,6}):(\d+)", text):
            path, ln = m.group(1), int(m.group(2))
            rel = path[len(cwd) + 1:] if cwd and path.startswith(cwd.rstrip("/") + "/") else path
            full = os.path.join(cwd, rel) if cwd else rel
            if not (os.path.exists(full) or os.path.exists(path)):
                if rel not in seen:
                    seen.add(rel)
                    bad_paths.append(rel)
                continue
            try:
                with open(full if os.path.exists(full) else path, "rb") as f:
                    n = sum(1 for _ in f)
                if ln > n and f"{rel}:{ln}" not in bad_lines:
                    bad_lines.append(f"{rel}:{ln}")
            except Exception:
                pass
        if bad_paths:
            conf = "low"
            adjusted.append("CONFIDENCE downgraded to low: paths not found: " + ", ".join(bad_paths[:5]))
        if bad_lines:
            conf = "low"
            adjusted.append("CONFIDENCE downgraded to low: line past end of file (a grep count pasted as a line?): " + ", ".join(bad_lines[:5]))

    # trailing text after the last section, and absolute paths anywhere
    trailing = 0
    abs_paths = []
    if kind:
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
    # list lines (facts, findings, steps, changes, evidence, issues, risks) must stay short;
    # the one-line sections (GAPS, LEFT, OPEN, NOTE, RECOMMENDATION, RAN, VERIFY) may run longer
    one_line = re.compile(r"^\s*(GAPS|LEFT|OPEN|NOTE|RECOMMENDATION|RAN|VERIFY|STATUS|CONFIDENCE|VERDICT):|^\s*\+\d+ more:", re.I)
    long_lines = [l for l in lines if len(l) > (400 if one_line.match(l) else 200)]
    if long_lines:
        sample = long_lines[0].strip()[:70]
        warnings.append(f"{len(long_lines)} line(s) too long (list lines max 200 chars, one-line sections max 400), e.g. \"{sample}…\" — split into one fact per line")
    if re.search(r"^\s*\+N more:", text, re.M):
        warnings.append("literal `+N more:` in reply — the agent copied the template; N must be the real count")
    if trailing:
        warnings.append(f"{trailing} line(s) after the last section — not part of the format; ignore them and ask for none next time")
    if abs_paths:
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
    elif conf == "low" or status in ("partial", "blocked"):
        warnings.append(f"STATUS={status} CONFIDENCE={conf} — escalation rule applies (Step 4), do not re-run at the same setting")
    return fields, warnings


def ledger_path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id or "") or "unknown"
    return LEDGER_DIR / f"{sid}.jsonl"


def emit(event, warnings):
    if warnings:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": "abofles: " + "; ".join(warnings)}}))


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
    if is_async:
        entry["status"] = "pending"
        entry["confidence"] = None
    else:
        fields, warnings = analyze(response_text(resp), stype, cap, data.get("cwd") or os.getcwd())
        entry.update(fields)
        entry["warnings"] = warnings or None
    try:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with open(ledger_path(entry["session"]), "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # orchestrator guard: a spawn resets the direct-read streak; receipt check: one more spawn this turn
    with state_lock(data.get("session_id", "")):
        st = load_state(data.get("session_id", ""))
        st["direct_reads"] = 0
        st["guard_warned_at"] = 0
        st["spawns"] = st.get("spawns", 0) + 1
        st["spawns_since_receipt"] = st.get("spawns_since_receipt", 0) + 1
        st["last_spawn_offset"] = transcript_size(data.get("transcript_path") or "")
        remember_transcript(data, st)
        save_state(data.get("session_id", ""), st)

    # session cap from the project override block
    cap_units = session_cap(data.get("cwd") or os.getcwd())
    if cap_units:
        try:
            rows = [json.loads(l) for l in ledger_path(entry["session"]).read_text().splitlines() if l.strip()]
            spent = sum(units(r.get("model"), r.get("effort")) for r in rows)
        except Exception:
            spent = 0
        if spent > cap_units:
            warnings.append(f"session cap {cap_units} units passed (now {spent:.0f}) — stop spawning and ask the user before the next spawn")
    emit("PostToolUse", warnings)


def start(data):
    """SessionStart: the marker the guard gates on, so it works from the first turn (before any spawn)."""
    sid = data.get("session_id", "")
    with state_lock(sid):
        st = load_state(sid)
        st["started"] = int(time.time())
        st["direct_reads"] = 0
        st["spawns_since_receipt"] = 0
        remember_transcript(data, st)
        en = effort_note(data, st)
        save_state(sid, st)
    if en:
        print(en)


def newest_state():
    """State file of the session that ran a hook most recently (a command run from a session fires the guard first)."""
    try:
        states = sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return json.loads(states[0].read_text()) if states else {}
    except Exception:
        return {}


READ_CMD = re.compile(r"^\s*(?:cd\s+\S+\s*&&\s*)?(grep|rg|ag|find|fd|cat|head|tail|less|sed\s+-n|awk|wc|ls|tree|git\s+(grep|log|show|blame|diff|status)|jq|python3\s+-c\s+['\"]print)\b")


def guard(data):
    """PreToolUse on Read/Grep/Glob and read-only Bash: more than 3 direct reads in a row means the main session
    is doing a Read agent's job. Warn via additionalContext (an `allow` reason is shown to the user only), never block.
    The desktop Code tab has no Grep/Glob tools, so Bash `grep`/`find`/`cat` count too; any other Bash breaks the streak."""
    tool = data.get("tool_name")
    if tool not in ("Read", "Grep", "Glob", "Bash") or in_subagent(data):
        return
    sid = data.get("session_id", "")
    is_read = tool != "Bash" or bool(READ_CMD.match((data.get("tool_input") or {}).get("command", "")))
    with state_lock(sid):
        st = load_state(sid)
        if "started" not in st:
            return  # plugin not active in this session (no SessionStart marker)
        remember_transcript(data, st)
        en = effort_note(data, st)
        cw = context_watch(data, st)
        threshold = None
        if not is_read:
            st["direct_reads"] = 0
            st["guard_warned_at"] = 0
        else:
            st["direct_reads"] = st.get("direct_reads", 0) + 1
            n = st["direct_reads"]
            last = st.get("guard_warned_at", 0)
            threshold = next((t for t in (4, 8, 16, 32) if n >= t and last < t), None)
            if threshold:
                st["guard_warned_at"] = threshold
        save_state(sid, st)
    msgs = []
    if en:
        msgs.append(en)
    if threshold:
        msgs.append(f"abofles: {n} direct reads in a row by the main session — in orchestrator mode this is a Read agent's job "
                    f"(haiku·low). Spawn one with a numbered question list, or finish in ≤3 calls.")
    if cw:
        msgs.append(cw)
    if msgs:
        msg = "\n\n".join(msgs)
        reason = context_reason(cw) if cw else msg.splitlines()[0]
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
              "permissionDecisionReason": reason, "additionalContext": msg}}))


def prompt(data):
    """UserPromptSubmit: context watch at the start of a user turn — the natural moment to compact."""
    if in_subagent(data):
        return
    sid = data.get("session_id", "")
    with state_lock(sid):
        st = load_state(sid)
        remember_transcript(data, st)
        en = effort_note(data, st)
        cw = context_watch(data, st)
        save_state(sid, st)
    msg = "\n\n".join(m for m in (en, cw) if m)
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))


def receipt(data):
    """Stop: if this turn spawned abofles agents and the final message has no receipt block, refuse the stop
    once so the 5-line receipt gets printed. `stop_hook_active` means we already did — let it stop."""
    if data.get("stop_hook_active"):
        return
    sid = data.get("session_id", "")
    text = data.get("last_assistant_message") or ""
    with state_lock(sid):
        st = load_state(sid)
        pending = st.get("spawns_since_receipt", 0)
        has_receipt = "── receipt" in text or re.search(r"^\s*done\s{2,}\S", text, re.M) is not None
        if pending and has_receipt:
            st["spawns_since_receipt"] = 0
            save_state(sid, st)
            return
        if not pending:
            return
        st["spawns_since_receipt"] = 0  # one nudge per turn; the retry sets stop_hook_active anyway
        save_state(sid, st)
    print(json.dumps({"decision": "block",
                      "reason": f"abofles: this turn spawned {pending} agent(s) and ended without the receipt. Print it now, exactly five lines: "
                                "── receipt ── / done / why / spend / check / open (follow-ups: every partial, low, ATTENTION, open FAIL). Nothing after it."}))


def stop(data):
    """SubagentStop: fill the `pending` entry written at async launch. Sync spawns have no pending entry (PostToolUse logs them)."""
    agent_id = data.get("agent_id")
    text = data.get("last_assistant_message") or ""
    if not agent_id or not text:
        return
    path = ledger_path(data.get("session_id", ""))
    try:
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except Exception:
        return
    idx = next((i for i, r in enumerate(rows) if r.get("agent_id") == agent_id and r.get("status") == "pending"), None)
    if idx is None:
        return
    row = rows[idx]
    stype = row.get("agent") or data.get("agent_type") or ""
    fields, warnings = analyze(text, stype, row.get("cap"), row.get("cwd") or data.get("cwd") or os.getcwd())
    row.update(fields)
    row["completed_ts"] = int(time.time())
    row["warnings"] = warnings or None
    try:
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    except Exception:
        pass
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
