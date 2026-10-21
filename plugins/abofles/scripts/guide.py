#!/usr/bin/env python3
"""Abo Fles guide: what to do next, from the ledger, the memo, the state and the context size.

    guide.py          one line (the same the receipt and the resume block carry)
    guide.py --all    every item of the ladder, one per line
    guide.py --scope session|project|all   owner decisions of this session only / of this project (default) / other projects counted too

Ladder, highest first: open FAIL / ATTENTION · judged question unasked · owner decisions open ·
partial/low reply not escalated · background agents running · context or memo hygiene · agent budget
nearly out · the memo's Next. Advice only: it never spawns, blocks or changes anything.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from abofles_hook import guide_items, refresh_guide, load_state, save_state, state_lock, newest_state_path, guide_on, session_arg, SCOPES  # noqa: E402


def scope_arg(argv):
    """Take `--scope <value>` out of argv; the value, or None. An unknown value exits 2."""
    if "--scope" not in argv:
        return None
    i = argv.index("--scope")
    v = argv[i + 1].strip().lower() if i + 1 < len(argv) else ""
    if v not in SCOPES:
        print("usage: --scope session|project|all")
        sys.exit(2)
    del argv[i:i + 2]
    return v


def main():
    if sys.argv[-2:] == ["--session", ""]:  # a command whose ${CLAUDE_SESSION_ID} expanded to nothing
        del sys.argv[-2:]
    sess = session_arg(sys.argv)
    scope = scope_arg(sys.argv)
    sp = newest_state_path(os.getcwd(), sess)
    if not sp:
        print("abofles: no session state yet")
        return
    sid = sp.stem
    st = load_state(sid)
    root = st.get("project") or st.get("root") or os.getcwd()  # the work root when the session's edits moved the memo
    if not guide_on(root):
        print("abofles: guide is off (`- Guide = off` in the override block)")
        return
    if "--all" in sys.argv or scope:
        for e, t in guide_items(root, st, sid, scope=scope):
            print(f"{e} {t}")
        return
    with state_lock(sid):
        st = load_state(sid)
        line = refresh_guide(root, st, sid)
        save_state(sid, st)
    print(line or "abofles: guide is off")


if __name__ == "__main__":
    main()
