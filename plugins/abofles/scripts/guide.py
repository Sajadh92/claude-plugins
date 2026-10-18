#!/usr/bin/env python3
"""Abo Fles guide: what to do next, from the ledger, the memo, the state and the context size.

    guide.py          one line (the same the receipt and the resume block carry)
    guide.py --all    every item of the ladder, one per line

Ladder, highest first: open FAIL / ATTENTION · judged question unasked · owner decisions open ·
partial/low reply not escalated · background agents running · context or memo hygiene · agent budget
nearly out · the memo's Next. Advice only: it never spawns, blocks or changes anything.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from abofles_hook import guide_items, refresh_guide, load_state, save_state, state_lock, newest_state_path, guide_on, session_arg  # noqa: E402


def main():
    if sys.argv[-2:] == ["--session", ""]:  # a command whose ${CLAUDE_SESSION_ID} expanded to nothing
        del sys.argv[-2:]
    sess = session_arg(sys.argv)
    sp = newest_state_path(os.getcwd(), sess)
    if not sp:
        print("abofles: no session state yet")
        return
    sid = sp.stem
    st = load_state(sid)
    root = st.get("root") or os.getcwd()
    if not guide_on(root):
        print("abofles: guide is off (`- Guide = off` in the override block)")
        return
    if "--all" in sys.argv:
        for e, t in guide_items(root, st, sid):
            print(f"{e} {t}")
        return
    with state_lock(sid):
        st = load_state(sid)
        line = refresh_guide(root, st, sid)
        save_state(sid, st)
    print(line or "abofles: guide is off")


if __name__ == "__main__":
    main()
