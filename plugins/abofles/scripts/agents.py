#!/usr/bin/env python3
"""Abo Fles agent gate: how many agents a task may spawn.

    agents.py                 show the current setting and this task's budget
    agents.py set auto        abofles sizes each task by tier (no more questions this session)
    agents.py set N           budget N for the current task (asked again next task)
    agents.py set off         no budget, no questions this session
    agents.py set ask         ask the gate question again at the next spawn

Acts on the session you type in: ABOFLES_SESSION, else `--session <id>` (the command passes its own session id), else the
newest prompt among this folder's sessions. Never a session of another project.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from abofles_hook import apply_gate_answer, gate_setting, task_budget, mode_of, AGENT_BUDGETS, state_lock, load_state, save_state, tier_name, newest_state_path, budget_used, work_spawns, session_arg  # noqa: E402


def main():
    args = sys.argv[1:]
    if args[-2:] == ["--session", ""]:  # a command whose ${CLAUDE_SESSION_ID} expanded to nothing
        del args[-2:]
    sess = session_arg(args)
    cwd = os.getcwd()
    sp = newest_state_path(cwd, sess)
    sid = sp.stem if sp else ""
    if args[:1] == ["set"] and len(args) > 1:
        if not sp:
            print("abofles: no session state yet")
            return
        v = args[1].strip().lower()
        with state_lock(sid):
            st = load_state(sid)
            if v == "ask":
                st["gate"], st["task_budget"], st["task_parallel"] = None, None, None
                note = "agents: ask at the next spawn"
            else:
                note = apply_gate_answer(st, v if not v.isdigit() else f"{v} agents")
            save_state(sid, st)
        print(note)
        return
    st = load_state(sid) if sid else {}
    cwd = st.get("root") or cwd
    setting, n = gate_setting(cwd)
    budget, src = task_budget(cwd, st, st.get("task_tier_max") or None)
    used, gate_runs = budget_used(st), st.get("task_judges", 0)
    print(f"Agents = {setting}{'' if n is None else ' ' + str(n)} · mode {mode_of(st)} · gate {st.get('gate') or 'unset'}")
    print(f"This task: {used} of budget {'none' if budget is None else budget} used ({src})" + (f" · {gate_runs} gate run{'s' if gate_runs != 1 else ''} not counted" if gate_runs else "") + (f" · {work_spawns(st)} work spawns since the receipt" if work_spawns(st) != used else ""))
    print("Auto table: " + " · ".join(f"{tier_name(i + 1)} {b}" for i, b in enumerate(AGENT_BUDGETS[mode_of(st)])))


if __name__ == "__main__":
    main()
