#!/usr/bin/env python3
"""Abo Fles memo: the work journal the hooks keep in `.claude/abofles-memo.md`.

    memo.py show                 the resume block (now · next · needs you · last receipts)
    memo.py show --all           the whole memo file
    memo.py resolve <n> [note]   tick item n of "Needs you"
    memo.py note <text>          add a user note to Decisions (something settled in chat)
    memo.py now < text           replace the Now section from stdin (what /abofles:memo writes)
    memo.py path                 print the memo path

The hooks fill Journal (one line per receipt), Needs you (ATTENTION, FAIL, owner decisions from the
receipts' `open` line) and Decisions (every AskUserQuestion with its answer). Only Now is written by
the model, through `now`.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from abofles_hook import memo_path, memo_now, memo_resolve, memo_decision, resume_block, newest_state, newest_state_path  # noqa: E402


def main():
    args = sys.argv[1:]
    st = newest_state()
    cwd = st.get("root") or os.getcwd()  # the project root the session started in, not the folder a `cd` left us in
    sp = newest_state_path()
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
    elif cmd == "resolve":
        if len(args) < 2 or not args[1].isdigit():
            print("usage: memo.py resolve <n> [note]")
            return
        hit = memo_resolve(cwd, int(args[1]), " ".join(args[2:]))
        print(f"resolved: {hit}" if hit else f"abofles: no open item {args[1]} in Needs you ({memo_path(cwd)})")
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
