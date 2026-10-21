#!/usr/bin/env python3
"""Abo Fles memo: the work journal the hooks keep in `.claude/abofles-memo.md`.

    memo.py show                 the resume block (now · next · needs you · last receipts)
    memo.py show --scope session|project|all   this session only / every session of this project (default) / other projects too
    memo.py show --all           the main memo, then this session's file
    memo.py show --main          the main memo only (Needs you, Decisions, Sessions index)
    memo.py scope [session|project|all]        print the scope in force and where it comes from; with a value, save it as the user default
    memo.py resolve <n> [note] [--trace] [--session <sid>]   tick item n of "Needs you" (--trace: one "resolved by hand" line in Journal)
    memo.py reopen <n> [--trace] [--session <sid>]           turn a resolved item n back to open (drops the resolve note)
      --session <sid> stamps the trace with that session instead of the newest one (two sessions in one root)
      exit codes: 0 changed · 1 no such item · 2 usage (bad n, missing or empty --session value)
                  · 3 nothing to change (already resolved / already open) — no trace line is written
    memo.py note <text>          add a user note to Decisions (something settled in chat)
    memo.py now < text           replace the Now section from stdin (what /abofles:memo writes)
    memo.py path                 print the main memo path (`path mine`: this session's file)
    memo.py move <root>          move this session's memo (its file, its Needs-you items, its index line) to project <root>
                                 and make <root> the session's project — for a session that was started in the wrong folder
      a write (resolve, reopen, note, now) from a folder with no session state, no --session and no memo exits 4 and writes nothing

Layout: `.claude/abofles-memo.md` (main: Needs you, Decisions = notes, Sessions = one index line per
session with a link) and `.claude/abofles-memo.d/<session>.md` (Now, Journal = one line per receipt,
Decisions = that session's questions with their answers). The hooks fill everything but Now, which
the model writes through `now`. The memo lives in the project the session's edits land in (the launch
folder until most edits go to another repository; the `edit` hook moves it then).
Scope precedence: `--scope` · `- Resume = …` in the override block · the saved default (`scope <value>`,
~/.abofles/config.json) · `project`.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from abofles_hook import memo_path, session_memo_path, sess_read, memo_now, memo_resolve, memo_decision, memo_reopen, memo_trace, memo_read, resume_block, newest_state, newest_state_path, session_arg, resume_scope, config_read, config_write, SCOPES, CONFIG_PATH, memo_move, load_state, save_state, state_lock, refresh_guide, guide_line  # noqa: E402


def scope_arg(args):
    """Take `--scope <value>` out of args; the value, or None. An unknown value exits 2."""
    if "--scope" not in args:
        return None
    i = args.index("--scope")
    v = args[i + 1].strip().lower() if i + 1 < len(args) else ""
    if v not in SCOPES:
        print("usage: memo.py show --scope session|project|all")
        sys.exit(2)
    del args[i:i + 2]
    return v


def main():
    args = sys.argv[1:]
    if args[-2:] == ["--session", ""]:  # a command whose ${CLAUDE_SESSION_ID} expanded to nothing
        del args[-2:]
    sess = session_arg(args, keep=bool(args) and args[0] in ("resolve", "reopen"))  # those two read --session themselves
    scope = scope_arg(args)
    st = newest_state(os.getcwd(), sess)
    cwd = st.get("project") or st.get("root") or os.getcwd()  # the project the session's edits moved the memo to, else where it started — never the folder a `cd` left us in
    sp = newest_state_path(os.getcwd(), sess)
    sid = sp.stem if sp else ""  # the session id (its state file), so the Now block and receipts carry the same tag
    cmd = args[0] if args else "show"
    if cmd in ("resolve", "reopen", "note", "now") and not st and not sess and not os.environ.get("ABOFLES_SESSION") and not memo_path(cwd).exists():
        # no session of this folder, no session named, no memo here: never start a stray memo in a folder a `cd` led to
        print("abofles: no session state and no memo for this folder — nothing written (run the command from the session that owns the memo, or name it with --session)")
        sys.exit(4)
    if cmd == "scope":
        want = (args[1] if len(args) > 1 else "").strip().lower()
        if want:
            if want not in SCOPES:
                print("usage: memo.py scope session|project|all")
                sys.exit(2)
            cfg = config_read()
            cfg["resume_scope"] = want
            if not config_write(cfg):
                print(f"abofles: could not write {CONFIG_PATH}")
                sys.exit(1)
        sc, src = resume_scope(cwd, scope)
        where = {"flag": "--scope", "override": "`- Resume = …` in the override block", "default": f"the saved default ({CONFIG_PATH})", "built-in": "built-in default"}[src]
        print(("saved as the default · " if want else "") + f"scope: {sc} (from {where})")
    elif cmd == "move":
        dest = os.path.realpath(args[1]) if len(args) > 1 and args[1].strip() else ""
        if not dest or not os.path.isdir(dest):
            print("usage: memo.py move <existing project folder>")
            sys.exit(2)
        if not sid or not st:
            print("abofles: no session state for this folder — nothing moved")
            sys.exit(4)
        if dest == os.path.realpath(cwd):
            print(f"abofles: the memo is already in {dest}")
            sys.exit(3)
        memo_move(cwd, dest, sid, "moved by hand (memo.py move)")
        with state_lock(sid):
            st2 = load_state(sid)
            if dest == os.path.realpath(st2.get("root") or ""):
                st2.pop("project", None)
            else:
                st2["project"] = dest
            refresh_guide(dest, st2, sid)
            save_state(sid, st2)
        print(f"moved: session {sid[:8]} → {memo_path(dest)}")
    elif cmd == "path":
        print(session_memo_path(cwd, sid) if "mine" in args[1:] else memo_path(cwd))
    elif cmd == "show":
        if "--all" in args or "--main" in args:
            try:
                out = memo_path(cwd).read_text()
            except Exception:
                print("abofles: no memo yet — it is written at the first receipt, or by /abofles:memo.")
                return
            if "--all" in args and sid and session_memo_path(cwd, sid).exists():
                out += "\n\n" + session_memo_path(cwd, sid).read_text()
            print(out)
            return
        # the guide line is computed here for the same scope as the block (the stored one follows the default scope)
        g = guide_line(cwd, st, sid, scope) if st else (st.get("guide") or {}).get("line")
        block = resume_block(cwd, session_id=sid, guide=g, scope=scope, explicit=scope is not None)
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
        print(session_memo_path(cwd, sid))  # where the Now section went
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
