#!/usr/bin/env python3
"""Abo Fles memo: the work journal the hooks keep in `.claude/abofles-memo.md`.

    memo.py show                 the resume block (now · next · needs you · last receipts)
    memo.py show --all           the whole memo file
    memo.py resolve <n> [note] [--trace] [--session <sid>]   tick item n of "Needs you" (--trace: one "resolved by hand" line in Journal)
    memo.py reopen <n> [--trace] [--session <sid>]           turn a resolved item n back to open (drops the resolve note)
      --session <sid> stamps the trace with that session instead of the newest one (two sessions in one root)
      exit codes: 0 changed · 1 no such item · 2 usage (bad n, missing or empty --session value)
                  · 3 nothing to change (already resolved / already open) — no trace line is written
    memo.py note <text>          add a user note to Decisions (something settled in chat)
    memo.py now < text           replace the Now section from stdin (what /abofles:memo writes)
    memo.py path                 print the memo path

The hooks fill Journal (one line per receipt), Needs you (ATTENTION, FAIL, owner decisions from the
receipts' `open` line) and Decisions (every AskUserQuestion with its answer). Only Now is written by
the model, through `now`.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from abofles_hook import memo_path, memo_now, memo_resolve, memo_decision, memo_reopen, memo_trace, memo_read, resume_block, newest_state, newest_state_path, session_arg  # noqa: E402


def main():
    args = sys.argv[1:]
    if args[-2:] == ["--session", ""]:  # a command whose ${CLAUDE_SESSION_ID} expanded to nothing
        del args[-2:]
    sess = session_arg(args, keep=bool(args) and args[0] in ("resolve", "reopen"))  # those two read --session themselves
    st = newest_state(os.getcwd(), sess)
    cwd = st.get("root") or os.getcwd()  # the project root the session started in, not the folder a `cd` left us in
    sp = newest_state_path(os.getcwd(), sess)
    sid = sp.stem if sp else ""  # the session id (its state file), so the Now block and receipts carry the same tag
    cmd = args[0] if args else "show"
    if cmd == "path":
        print(memo_path(cwd))
    elif cmd == "show":
        if "--all" in args:
            try:
                print(memo_path(cwd).read_text())
            except Exception:
                print("abofles: no memo yet — it is written at the first receipt, or by /abofles:memo.")
            return
        block = resume_block(cwd, session_id=sid, guide=(st.get("guide") or {}).get("line"))
        print(block or "abofles: no memo yet — it is written at the first receipt, or by /abofles:memo.")
    elif cmd in ("resolve", "reopen"):
        undo = cmd == "reopen"
        usage = "usage: memo.py resolve <n> [note] [--trace] [--session <sid>]" if not undo else "usage: memo.py reopen <n> [--trace] [--session <sid>]"
        rest, a_sid = [], None
        i = 1
        while i < len(args):  # --session takes a value; everything else that is not --trace is the note
            if args[i] == "--session":
                v = args[i + 1] if i + 1 < len(args) else ""
                if not v.strip() or v.startswith("--"):
                    print(usage)
                    sys.exit(2)
                if a_sid is None:  # the first one wins: the user's own, before the command's appended fallback
                    a_sid = v
                i += 2
                continue
            if args[i] != "--trace":
                rest.append(args[i])
            i += 1
        if not rest or not rest[0].isdigit():
            print(usage)
            sys.exit(2)
        n = rest[0]
        if a_sid is not None:
            sid = re.sub(r"[^A-Za-z0-9_-]", "", a_sid) or "unknown"
        hit = memo_reopen(cwd, int(n)) if undo else memo_resolve(cwd, int(n), " ".join(rest[1:]))
        if not hit:
            try:
                already = any(l.startswith(f"{n}. [ ] " if undo else f"{n}. [x] ") for l in memo_read(cwd)["Needs you"].splitlines())
            except Exception:
                already = False
            if already:
                print(f"abofles: item {n} is already {'open' if undo else 'resolved'} ({memo_path(cwd)})")
                sys.exit(3)
            print(f"abofles: no {'resolved' if undo else 'open'} item {n} in Needs you ({memo_path(cwd)})")
            sys.exit(1)
        print(f"{'reopened' if undo else 'resolved'}: {hit}")
        if "--trace" in args:
            memo_trace(cwd, sid, f"{'reopened' if undo else 'resolved'} by hand: owner decision {n}: " + re.sub(r"\s*\(s:[0-9a-z-]{1,12}\)\s*$", "", re.sub(r"^\d+\. \[.\] \S+ \S+ · (owner decision:\s*)?", "", hit)))
    elif cmd == "note":
        text = " ".join(args[1:]).strip()
        if not text:
            print("usage: memo.py note <text>")
            return
        memo_decision(cwd, "", "note", text)
        print("noted")
    elif cmd == "now":
        text = sys.stdin.read()
        if not text.strip():
            print("usage: memo.py now < text")
            return
        memo_now(cwd, text, sid)
        print(memo_path(cwd))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
