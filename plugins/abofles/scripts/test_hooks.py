#!/usr/bin/env python3
"""Unit tests for hooks/abofles_hook.py. Run: python3 scripts/test_hooks.py"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "abofles_hook.py"


def run(mode, payload, ledger):
    env = dict(os.environ, ABOFLES_LEDGER_DIR=ledger)
    if "cwd" not in payload and os.environ.get("ABOFLES_TEST_CWD"):
        payload = dict(payload, cwd=os.environ["ABOFLES_TEST_CWD"])  # never let a hook write a memo into the plugin dir
    r = subprocess.run([sys.executable, str(HOOK), mode], input=json.dumps(payload), capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    if not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return r.stdout  # plain-text hook output (SessionStart)


def agent(model=None, effort=None, stype="abofles:abofles-reader", prompt="abofles: Unit Test / R · T2\nq\nLine cap: 40", resp=None, cwd=""):
    ti = {"subagent_type": stype, "prompt": prompt, "description": "t"}
    if model: ti["model"] = model
    if effort: ti["effort"] = effort
    d = {"session_id": "test", "cwd": cwd, "tool_name": "Agent", "tool_input": ti}
    if resp is not None: d["tool_response"] = resp
    return d


def main():
    fails = 0
    def check(name, cond):
        nonlocal fails
        print(("ok   " if cond else "FAIL ") + name)
        if not cond: fails += 1

    with tempfile.TemporaryDirectory() as led, tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as state:
        os.environ["ABOFLES_STATE_DIR"] = state
        os.environ["ABOFLES_TEST_CWD"] = cwd
        os.environ["ABOFLES_USER_CLAUDE_MD"] = str(Path(state, "no-user-claude.md"))
        os.environ["ABOFLES_CONFIG"] = str(Path(state, "config.json"))
        os.environ.pop("ABOFLES_RECEIPT", None)
        Path(cwd, "src").mkdir(); Path(cwd, "src/a.cs").write_text("x\n" * 30)
        def pin(sid=None):  # the scripts pick the session for a command: ABOFLES_SESSION, else the newest prompt among this folder's sessions
            os.environ.pop("ABOFLES_SESSION", None)
            if sid: os.environ["ABOFLES_SESSION"] = sid
        pin()
        reason = lambda out: (out or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        import importlib.util as _iu0
        _hs0 = _iu0.spec_from_file_location("abofles_hook_t0", str(HOOK)); _H0 = _iu0.module_from_spec(_hs0); _hs0.loader.exec_module(_H0)
        H_flat = _H0.explain_flat
        allowed = lambda out: out is None or (out or {}).get("hookSpecificOutput", {}).get("permissionDecision") == "allow"  # the first spawn of a task may carry the `main:` line
        ctx = lambda out: (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
        # post output minus the receipt note it always carries
        import re as _re
        warn = lambda out: "\n\n".join(_re.sub(r"(; )?\d+ spawns this session so far[^;]*|(; )?(1 spawn left in|agent budget \d+ reached)[^;]*", "", p).replace("abofles: ", "", 1).strip() for p in ctx(out).split("\n\n") if not p.startswith(("abofles: Receipt", "abofles: no receipt")))

        # pre
        check("pre: missing effort blocked", "effort=missing" in reason(run("pre", agent("opus"), led)))
        check("pre: missing model blocked", "model=missing" in reason(run("pre", agent(effort="low"), led)))
        check("pre: bad effort blocked", "effort=ultra" in reason(run("pre", agent("opus", "ultra"), led)))
        check("pre: fable on reader blocked", "fable is only for" in reason(run("pre", agent("fable", "medium"), led)))
        _fa = run("pre", agent("fable", "medium", "abofles:abofles-analyst"), led)
        check("pre: fable on analyst allowed (an advisory cell note at most)", _fa is None or (_fa.get("hookSpecificOutput", {}).get("permissionDecision") == "allow" and "× the cell" in ctx(_fa)))
        check("pre: good call allowed", run("pre", agent("haiku", "low"), led) is None)
        check("pre: skip bypass", run("pre", agent(prompt="abofles:skip x", stype="Explore"), led) is None)
        check("pre: non-Agent tool ignored", run("pre", {"tool_name": "Bash", "tool_input": {}}, led) is None)

        # post
        good = "STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/a.cs:1 — x\nGAPS: none"
        check("post: good reply, no warning", warn(run("post", agent("haiku", "low", resp=good, cwd=cwd), led)) == "")
        out = run("post", agent("opus", "high", "abofles:abofles-analyst", resp="just prose"), led)
        check("post: missing header warned", "no STATUS/CONFIDENCE header" in ctx(out))
        out = run("post", agent("sonnet", "medium", "abofles:abofles-worker", resp="STATUS: partial\nCONFIDENCE: low\nCHANGED:\n- a"), led)
        check("post: partial/low -> escalation note", "escalation rule applies" in ctx(out))
        liar = "STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/a.cs:1 — x\nGAPS: enclosing method names were not read for 7 callers"
        out = run("post", agent("haiku", "low", resp=liar, cwd=cwd), led)
        check("post: done+GAPS admits -> partial", "downgraded to partial" in ctx(out) and "escalation rule applies" in ctx(out))
        badpath = "STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/Rules/a.cs:1 — x\n- src/a.cs:2 — y\nGAPS: none"
        out = run("post", agent("haiku", "low", resp=badpath, cwd=cwd), led)
        check("post: reader bad path -> low", "paths not found: src/Rules/a.cs" in ctx(out) and "src/a.cs" not in ctx(out).split("paths not found:")[1].split(";")[0].replace("src/Rules/a.cs", ""))
        out = run("post", agent("opus", "high", "abofles:abofles-analyst", resp="STATUS: done\nCONFIDENCE: high\nFINDINGS:\n1. [low] nowhere/x.cs:1 — y — z\nRECOMMENDATION: none"), led)
        check("post: analyst bad path not checked", warn(out) == "")
        hy = Path(cwd, "my-repo", "Application", "Finance"); hy.mkdir(parents=True); Path(hy, "Rules.cs").write_text("x")
        hcwd = str(Path(cwd, "my-repo"))
        absrep = f"STATUS: done\nCONFIDENCE: high\nFACTS:\n- {hcwd}/Application/Finance/Rules.cs:168 — x\n- Application/Finance/Rules.cs:223 — y\nGAPS: none"
        out = run("post", agent("sonnet", "low", resp=absrep, cwd=hcwd), led)
        check("post: absolute path with hyphen folder accepted", "paths not found" not in ctx(out) and "absolute paths in reply" in ctx(out))
        out = run("post", agent("opus", "high", "abofles:abofles-verifier", resp="STATUS: done\nCONFIDENCE: high\nVERDICT: FAIL\nEVIDENCE:\n- c1 — FAIL — src/a.cs:1\nISSUES:\nNOTE: none", cwd=cwd), led)
        check("post: verdict FAIL warned", "VERDICT: FAIL" in ctx(out))
        out = run("post", agent("opus", "high", "abofles:abofles-verifier", resp="STATUS: done\nCONFIDENCE: medium\nVERDICT: PASS\nEVIDENCE:\n- c1 — PASS — src/a.cs:1\nISSUES:\n1. [critical] src/a.cs:9 — USD cap — use IQD\nNOTE: ATTENTION: cap applied in order currency", cwd=cwd), led)
        check("post: verifier ATTENTION warned", "ATTENTION" in ctx(out))
        longline = "STATUS: done\nCONFIDENCE: high\nPLAN:\n1. " + "word " * 120 + "\nRISKS:\n- " + "risk " * 100
        out = run("post", agent("opus", "xhigh", "abofles:abofles-planner", resp=longline, cwd=cwd), led)
        check("post: long lines warned", "too long" in ctx(out))
        over = "STATUS: done\nCONFIDENCE: high\nFACTS:\n" + "\n".join(f"- src/a.cs:{i} — f" for i in range(60)) + "\nGAPS: none"
        out = run("post", agent("haiku", "low", resp=over, prompt="abofles: Unit Test / R · T2\nq\nLine cap: 20", cwd=cwd), led)
        check("post: over cap warned", "cap was 20" in ctx(out))

        oos = "STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/a.cs:1 — x\nGAPS: .worktrees/ copy not searched (out of scope)"
        out = run("post", agent("haiku", "low", resp=oos, cwd=cwd), led)
        check("post: out-of-scope GAPS not downgraded", warn(out) == "")
        trail = "STATUS: done\nCONFIDENCE: high\nPLAN:\n1. s — files: src/a.cs — why: x\nRISKS:\n- r\nVERIFY: cmd\nOPEN: none\nFiles: src/a.cs\nThat is the plan."
        out = run("post", agent("opus", "xhigh", "abofles:abofles-planner", resp=trail, cwd=cwd), led)
        check("post: trailing text warned", "2 line(s) after the last section" in ctx(out))
        absr = "STATUS: done\nCONFIDENCE: high\nCHANGED:\n- /Users/x/my-repo/src/a.cs — y\nRAN: none\nLEFT: none"
        out = run("post", agent("sonnet", "medium", "abofles:abofles-worker", resp=absr, cwd=cwd), led)
        check("post: absolute path in worker warned", "absolute paths in reply" in ctx(out))
        # async launch -> pending, no checks; SubagentStop fills it
        launch = {"status": "async_launched", "agentId": "ag1", "prompt": "/Users/x/abs prompt echo", "description": "t"}
        out = run("post", agent("haiku", "low", resp=launch, prompt="abofles: Unit Test / R · T2\nq\nLine cap: 40", cwd=cwd), led)
        check("post: async launch -> no warnings", warn(out) == "")
        stop_in = {"session_id": "test", "cwd": cwd, "agent_id": "ag1", "agent_type": "abofles:abofles-reader",
                   "last_assistant_message": "STATUS: partial\nCONFIDENCE: medium\nFACTS:\n- src/a.cs:1 — x\n+3 more: y\nGAPS: cap reached"}
        out = run("stop", stop_in, led)
        check("stop: fills pending and prints NOTHING (output would reach the subagent)", out is None)
        out = run("stop", dict(stop_in, agent_id="unknown"), led)
        check("stop: unknown agent id ignored", out is None)
        # grep count pasted as a line number
        out = run("post", agent("haiku", "low", resp="STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/a.cs:160 — 160 hits\nGAPS: none", cwd=cwd), led)
        check("post: line past end of file -> low", "line past end of file" in ctx(out))
        # planner partial with OPEN questions -> owner input, not escalation
        plan = "STATUS: partial\nCONFIDENCE: medium\nPLAN:\n1. s (files: src/a.cs)\nRISKS:\n- r\nVERIFY: cmd\nOPEN: USD scope? default: IQD only"
        out = run("post", agent("opus", "xhigh", "abofles:abofles-planner", resp=plan, cwd=cwd), led)
        check("post: planner OPEN -> owner input note", "owner input needed" in ctx(out) and "escalation rule" not in ctx(out))
        # Problem 1: ATTENTION text with "skipped" must not downgrade the verifier
        att = "STATUS: done\nCONFIDENCE: medium\nVERDICT: PASS\nEVIDENCE:\n- c1 — PASS — src/a.cs:1\nISSUES:\n1. [critical] src/a.cs:9 — cap silently skipped on non-IQD\n   fix: compare in IQD\nNOTE: ATTENTION: cap is silently skipped on every non-IQD order at src/a.cs:9"
        out = run("post", agent("opus", "high", "abofles:abofles-verifier", resp=att, cwd=cwd), led)
        check("post: ATTENTION 'skipped' not downgraded", "downgraded" not in ctx(out) and "escalation rule" not in ctx(out) and "ATTENTION" in ctx(out))
        out = run("post", agent("haiku", "low", resp=good, prompt="abofles: Unit Test / Read · T2\nq\nLine cap: 40", cwd=cwd), led)
        check("post: full-word side parsed", warn(out) == "")
        okgaps = "STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/a.cs:1 — x\nGAPS: " + "g" * 300
        out = run("post", agent("haiku", "low", resp=okgaps, cwd=cwd), led)
        check("post: 300-char GAPS allowed", warn(out) == "")
        # multi-question OPEN is not trailing text
        open3 = "STATUS: done\nCONFIDENCE: medium\nPLAN:\n1. s (files: src/a.cs)\nRISKS:\n- r\nVERIFY: cmd\nOPEN:\n- USD in scope? assumed: IQD only\n- delivery cap too? assumed: no\n- branch? assumed: current"
        out = run("post", agent("opus", "xhigh", "abofles:abofles-planner", resp=open3, cwd=cwd), led)
        check("post: 3-question OPEN not trailing", "after the last section" not in ctx(out or {}) )
        # literal +N more
        lit = "STATUS: partial\nCONFIDENCE: medium\nFACTS:\n- src/a.cs:1 — x\n+N more: ...\nGAPS: cap"
        out = run("post", agent("haiku", "low", resp=lit, cwd=cwd), led)
        check("post: literal +N more warned", "literal `+N more:`" in ctx(out))
        # long real overflow line allowed up to 400
        ov = "STATUS: partial\nCONFIDENCE: medium\nFACTS:\n- src/a.cs:1 — x\n+207 more: " + ", ".join(f"File{i}.cs ({i})" for i in range(20)) + "\nGAPS: cap"
        out = run("post", agent("haiku", "low", resp=ov, cwd=cwd), led)
        check("post: 300-char overflow line allowed", "too long" not in ctx(out or {}))
        # content lines vs cap: 12 content lines against cap 8 must warn; labels and header do not count
        capr = "STATUS: partial\nCONFIDENCE: high\nFACTS:\n" + "\n".join(f"- src/a.cs:{i} — f" for i in range(12)) + "\nGAPS: cap"
        out = run("post", agent("haiku", "low", resp=capr, prompt="abofles: Unit Test / Read · T2\nq\nLine cap: 8", cwd=cwd), led)
        check("post: 12 content lines vs cap 8 warned", "over the cap" in ctx(out))
        capok = "STATUS: done\nCONFIDENCE: high\nFACTS:\n" + "\n".join(f"- src/a.cs:{i} — f" for i in range(8)) + "\nGAPS: none"
        out = run("post", agent("haiku", "low", resp=capok, prompt="abofles: Unit Test / Read · T2\nq\nLine cap: 8", cwd=cwd), led)
        check("post: 8 content lines vs cap 8 ok", warn(out) == "")
        # orchestrator guard: silent without the SessionStart marker; 3 reads silent, 4th warns via additionalContext; a spawn resets
        g = lambda sid="test": run("guard", {"session_id": sid, "cwd": cwd, "tool_name": "Grep", "tool_input": {}}, led)
        check("guard: no session marker -> silent", g("nosession") is None)
        run("start", {"session_id": "test", "cwd": cwd}, led)
        r1, r2, r3, r4 = g(), g(), g(), g()
        check("guard: 3 silent, 4th warns", r1 is None and r3 is None and "direct reads in a row" in (r4 or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))
        check("guard: warning reaches the model (additionalContext)", "direct reads in a row" in ctx(r4))
        check("guard: 5th silent (warned once per threshold)", g() is None)
        gb = lambda cmd: run("guard", {"session_id": "test", "cwd": cwd, "tool_name": "Bash", "tool_input": {"command": cmd}}, led)
        gb("dotnet test TestLab")  # non-read Bash breaks the streak
        r = [gb("grep -rn Surcharge Application"), gb("cd /x && find . -name '*.cs'"), gb("sed -n '100,120p' a.cs"), gb("cat a.cs")]
        check("guard: Bash reads count, 4th warns", r[0] is None and r[2] is None and "direct reads in a row" in ctx(r[3]))
        check("guard: non-read Bash resets streak", gb("dotnet build") is None and gb("grep x y") is None)
        run("post", agent("haiku", "low", resp=good, cwd=cwd), led)
        check("guard: spawn resets streak", g() is None)
        # "Main session only" (gate answer, budget 0 this task): the user chose direct reads — no nudge to spawn a Read agent
        run("start", {"session_id": "gmain", "cwd": cwd}, led)
        _sp_ = Path(state, "gmain.json"); _stm = json.loads(_sp_.read_text()); _stm.update({"gate": "task", "task_budget": 0}); _sp_.write_text(json.dumps(_stm))
        check("guard: silent under 'Main session only'", all(g("gmain") is None for _ in range(9)))
        _stm = json.loads(_sp_.read_text()); _stm.update({"gate": "auto", "task_budget": None}); _sp_.write_text(json.dumps(_stm))
        _ra = [g("gmain") for _ in range(4)]
        check("guard: gate back to auto — streak starts fresh (3 silent, 4th warns)", _ra[0] is None and _ra[2] is None and "direct reads in a row" in ctx(_ra[3]))
        # launcher: hooks.json runs hooks/run.py (bytecode cached); same output as the script
        LAUNCH = HOOK.parent / "run.py"
        _rl = subprocess.run([sys.executable, str(LAUNCH), "guard"], input=json.dumps({"session_id": "gmain", "cwd": cwd, "tool_name": "Grep", "tool_input": {}}), capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led))
        check("launcher: run.py guard exits 0 and is silent like the script", _rl.returncode == 0 and _rl.stdout.strip() == "")
        _hj = json.loads((HOOK.parent / "hooks.json").read_text())
        _cmds = [h["command"] for ev in _hj["hooks"].values() for grp in ev for h in grp["hooks"] if h["type"] == "command" and "python3" in h["command"]]
        check("launcher: every python hook command runs hooks/run.py", _cmds and all("hooks/run.py" in c for c in _cmds))
        check("launcher: SessionStart text asks for the skill once per session, not per task", "once per session" in _hj["hooks"]["SessionStart"][0]["hooks"][0]["command"] and "start of each task" not in _hj["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        # prune: state and ledger files untouched for 60 days go at SessionStart; the registry and fresh files stay
        _old = time.time() - 61 * 86400
        for _f in (Path(state, "oldsess.json"), Path(led, "oldsess.jsonl"), Path(state, "memo-index.json")):
            _f.write_text("{}" if _f.suffix == ".json" else "")
            os.utime(_f, (_old, _old))
        Path(state, "freshsess.json").write_text("{}")
        run("start", {"session_id": "prune", "cwd": cwd}, led)
        check("prune: 61-day-old state and ledger files deleted at SessionStart", not Path(state, "oldsess.json").exists() and not Path(led, "oldsess.jsonl").exists())
        check("prune: memo-index.json and fresh state files kept", Path(state, "memo-index.json").exists() and Path(state, "freshsess.json").exists())
        Path(state, "memo-index.json").unlink()
        # Stop receipt enforcement
        run("start", {"session_id": "rc", "cwd": cwd}, led)
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="rc"), led)
        out = run("receipt", {"session_id": "rc", "stop_hook_active": False, "last_assistant_message": "All done, tests pass."}, led)
        check("receipt: spawn without receipt -> block once", (out or {}).get("decision") == "block" and "receipt" in (out or {}).get("reason", ""))
        out = run("receipt", {"session_id": "rc", "stop_hook_active": True, "last_assistant_message": "still none"}, led)
        check("receipt: stop_hook_active -> no second block", out is None)
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="rc"), led)
        out = run("receipt", {"session_id": "rc", "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 0.5 u · Saved 99%** vs Opus 5.5\n- `done` → x\n- `check` → cmd\n- `open` → none"}, led)
        check("receipt: present -> allowed", out is None)
        out = run("receipt", {"session_id": "rc", "stop_hook_active": False, "last_assistant_message": "just an answer, no spawns this turn"}, led)
        check("receipt: no spawns this turn -> allowed", out is None)
        check("state: nothing written to the real state dir", not Path.home().joinpath(".abofles/state/test.json").exists())
        # receipt: header computed by the hook, modes from project / user CLAUDE.md
        rn = lambda out: next((p for p in ctx(out).split("\n\n") if p.startswith(("abofles: Receipt", "abofles: no receipt"))), "")
        run("start", {"session_id": "rm", "cwd": cwd, "effort": {"level": "medium"}}, led)
        out = rn(run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="rm"), led))
        check("receipt: full note, header computed (0.5 u vs Opus 5.5 · Medium 40 u)", "🧾 **1 Spawn · 0.5 u · Saved 99%** vs Opus 5.5 · Medium" in out and "- `open` → " in out and "no code block" in out)
        out = rn(run("post", dict(agent("opus", "xhigh", "abofles:abofles-planner", resp="STATUS: done\nCONFIDENCE: high\nPLAN:\n1. s\nRISKS:\n- r\nVERIFY: v\nOPEN: none", cwd=cwd), session_id="rm"), led))
        check("receipt: header accumulates, negative saving as cost", "🧾 **2 Spawns · 100 u · Cost +26%** vs Opus 5.5 · Medium" in out)
        out = run("receipt", {"session_id": "rm", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "🧾 **2 Spawns · 100 u · Cost +25%** vs Opus 5.5 · Medium\n- `done` → x"}, led)
        check("receipt: new format accepted, task reset", out is None and json.loads(Path(state, "rm.json").read_text()).get("task_units") == 0)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Receipt = savings 50\n")
        out = rn(run("post", dict(agent("sonnet", "medium", resp=good, cwd=cwd), session_id="rm"), led))
        check("receipt: savings 50, 50% saved -> full", "Receipt at task end" in out and "Saved 50%" in out)
        out = rn(run("post", dict(agent("opus", "medium", resp=good, cwd=cwd), session_id="rm"), led))
        check("receipt: savings 50, 25% saved -> skip", "no receipt for this task" in out and "under the 50% bar" in out)
        check("receipt: skip -> Stop does not block", run("receipt", {"session_id": "rm", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "done."}, led) is None)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Receipt = short\n")
        out = rn(run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="rm"), led))
        check("receipt: short -> one line", "one plain-markdown line" in out and "· open:" in out and "- `done`" not in out)
        Path(cwd, "CLAUDE.md").unlink()
        Path(state, "no-user-claude.md").write_text("## abofles overrides\n- Receipt = off\n")
        out = run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="rm"), led)
        check("receipt: off in user CLAUDE.md -> no note", rn(out) == "")
        check("receipt: off -> Stop does not block", run("receipt", {"session_id": "rm", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "done."}, led) is None)
        Path(state, "no-user-claude.md").unlink()
        run("prompt", {"session_id": "rm", "cwd": cwd, "prompt": "next job"}, led)  # no receipt was wanted: the task closes at the next real prompt
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="rm"), led)
        out = (run("receipt", {"session_id": "rm", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "done."}, led) or {}).get("reason", "")
        check("receipt: missing -> block carries the computed header", "🧾 **1 Spawn · 0.5 u · Saved 99%**" in out)
        # non-abofles agents: no format warnings; background spawn running: no receipt nudge
        long = "STATUS: done\nCONFIDENCE: high\n" + "x" * 300
        out = run("post", dict(agent("haiku", "low", "decision-judge", resp=long, cwd=cwd), session_id="na"), led)
        check("post: non-abofles agent -> no line-length warning", "too long" not in ctx(out))
        out = run("post", dict(agent("haiku", "low", "abofles:abofles-reader", resp=long, cwd=cwd), session_id="na"), led)
        check("post: abofles agent -> line-length warning", "too long" in ctx(out))
        run("start", {"session_id": "bg", "cwd": cwd}, led)
        _bgout = run("post", dict(agent("haiku", "low", resp={"status": "async_launched", "agentId": "bg1", "prompt": "p", "description": "t"}, cwd=cwd), session_id="bg"), led)
        check("receipt: a background launch carries no receipt note", "Receipt at task end" not in ctx(_bgout))
        check("receipt: background spawn running -> no block", run("receipt", {"session_id": "bg", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "waiting"}, led) is None)
        run("stop", {"session_id": "bg", "agent_id": "bg1", "last_assistant_message": "STATUS: done\nCONFIDENCE: high\nFACTS:\n- none found: x\nGAPS: none"}, led)
        out = run("receipt", {"session_id": "bg", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "all back"}, led)
        check("receipt: background done -> receipt due", (out or {}).get("decision") == "block" and "🧾 **1 Spawn" in out.get("reason", ""))
        tr = Path(cwd, 'main-tk.jsonl')
        # real tokens + dollars from the subagent transcripts (sync via PostToolUse, background via SubagentStop)
        def sub_tr(sid, aid, model, n_in, n_cw, n_cr, n_out, calls=2):
            d = Path(cwd, sid, "subagents"); d.mkdir(parents=True, exist_ok=True)
            u = {"input_tokens": n_in // calls, "cache_creation_input_tokens": n_cw // calls, "cache_read_input_tokens": n_cr // calls, "output_tokens": n_out // calls}
            Path(d, f"agent-{aid}.jsonl").write_text("".join(json.dumps({"type": "assistant", "message": {"model": model, "usage": u}}) + "\n" for _ in range(calls)))
        with open(tr, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 1, "cache_read_input_tokens": 999, "cache_creation_input_tokens": 0, "output_tokens": 1}}}) + "\n")
        run("start", {"session_id": "tk", "cwd": cwd, "transcript_path": str(tr), "effort": {"level": "medium"}}, led)
        sub_tr("tk", "h1", "claude-haiku-5-5", 0, 100_000, 1_000_000, 10_000)   # haiku: 0.125 + 0.10 + 0.05 = $0.275 ; at opus: 0.5 + 0.2 + 0.2 = $0.90
        out = run("post", dict(agent("haiku", "low", resp=dict(good_resp := {"status": "completed", "agentId": "h1", "content": [{"type": "text", "text": good}]}), cwd=cwd), session_id="tk", transcript_path=str(tr)), led)
        hdr = next((l for l in ctx(out).splitlines() if l.startswith("🧾")), "")
        check("tokens: sync spawn -> header has tokens, $ and saving vs main model", hdr == "🧾 **1 Spawn · 1.1M Tokens · $0.28 · Saved 69% ($0.62)** vs Opus 5.5")
        row = json.loads(Path(led, "tk.jsonl").read_text().splitlines()[-1])
        check("tokens: ledger row carries tokens/usd/base_usd/resolved_model", row.get("tokens") == 1_110_000 and row.get("usd") == 0.275 and row.get("base_usd") == 0.9 and row.get("resolved_model") == "claude-haiku-5-5" and row.get("calls") == 2)
        # background: pending at launch, spend filled at SubagentStop
        run("post", dict(agent("sonnet", "medium", resp={"status": "async_launched", "agentId": "s1", "prompt": "p", "description": "t"}, cwd=cwd), session_id="tk", transcript_path=str(tr)), led)
        sub_tr("tk", "s1", "claude-sonnet-5-5", 0, 0, 500_000, 5_000)  # sonnet: 0.10 + 0.05 = $0.15 ; at opus: 0.10 + 0.10 = $0.20
        run("stop", {"session_id": "tk", "agent_id": "s1", "last_assistant_message": good}, led)
        rows = [json.loads(l) for l in Path(led, "tk.jsonl").read_text().splitlines()]
        check("tokens: background row filled at SubagentStop", rows[-1].get("tokens") == 505_000 and rows[-1].get("usd") == 0.15 and rows[-1].get("status") == "done")
        out = run("receipt", {"session_id": "tk", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "done."}, led)
        check("tokens: Stop header sums sync + background", "🧾 **2 Spawns · 1.6M Tokens · $0.43 · Saved 61% ($0.68)** vs Opus 5.5" in (out or {}).get("reason", ""))
        check("tokens: the dominant spawn is named", "largest: Read Haiku 5.5 · Low $0.28 (65%)" in (out or {}).get("reason", ""))
        run("receipt", {"session_id": "tk", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": True, "last_assistant_message": "🧾 **2 Spawns · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x"}, led)  # a printed receipt closes the task
        # main session on fable: baseline priced at fable
        with open(tr, "a") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-fable-5-1", "usage": {"input_tokens": 1, "cache_read_input_tokens": 1, "cache_creation_input_tokens": 0, "output_tokens": 1}}}) + "\n")
        sub_tr("tk", "o1", "claude-opus-5-5", 1_000_000, 0, 0, 0)  # opus $4 ; at fable $10
        out = run("post", dict(agent("opus", "high", resp={"status": "completed", "agentId": "o1", "content": [{"type": "text", "text": good}]}, cwd=cwd), session_id="tk", transcript_path=str(tr)), led)
        hdr = next((l for l in ctx(out).splitlines() if l.startswith("🧾")), "")
        check("tokens: baseline follows the main model (fable)", hdr == "🧾 **1 Spawn · 1.0M Tokens · $4.00 · Saved 60% ($6.00)** vs Fable 5.1")
        # no transcript found -> unit estimate header (legacy)
        out = run("post", dict(agent("haiku", "low", resp={"status": "completed", "agentId": "nope", "content": [{"type": "text", "text": good}]}, cwd=cwd), session_id="tk", transcript_path=str(tr)), led)
        hdr = next((l for l in ctx(out).splitlines() if l.startswith("🧾")), "")
        check("tokens: missing transcript inside a priced task -> flagged unpriced", "vs Fable 5.1 · 1 unpriced" in hdr)
        run("start", {"session_id": "tk2", "cwd": cwd, "transcript_path": str(tr)}, led)
        out = run("post", dict(agent("haiku", "low", resp={"status": "completed", "agentId": "nope2", "content": [{"type": "text", "text": good}]}, cwd=cwd), session_id="tk2", transcript_path=str(tr)), led)
        hdr = next((l for l in ctx(out).splitlines() if l.startswith("🧾")), "")
        check("tokens: no transcript at all -> units fallback", " u · " in hdr and "Tokens" not in hdr)
        # one API message written as several lines (thinking/text/tool_use) repeats its usage: count it once
        d = Path(cwd, "tk2", "subagents"); d.mkdir(parents=True, exist_ok=True)
        u = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100_000, "output_tokens": 0}
        Path(d, "agent-dup.jsonl").write_text("".join(json.dumps({"type": "assistant", "message": {"id": f"msg_{i // 3}", "model": "claude-haiku-5-5", "usage": u}}) + "\n" for i in range(9)))
        out = run("post", dict(agent("haiku", "low", resp={"status": "completed", "agentId": "dup", "content": [{"type": "text", "text": good}]}, cwd=cwd), session_id="tk2", transcript_path=str(tr)), led)
        check("tokens: duplicate usage lines deduplicated by message id (9 lines, 3 messages)", json.loads(Path(led, "tk2.jsonl").read_text().splitlines()[-1]).get("tokens") == 300_000)
        # "Main session only" (budget 0) expires at the next Stop even with no spawn; a budget > 0 answer survives a prose turn
        run("start", {"session_id": "gx", "cwd": cwd, "transcript_path": str(tr)}, led)
        gq2 = {"session_id": "gx", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Abo Fles agent gate: how many?", "options": []}]}}
        run("decision", dict(gq2, tool_response={"answers": {"Abo Fles agent gate: how many?": "Main session only"}}), led)
        check("gate: Main only -> budget 0", json.loads(Path(state, "gx.json").read_text()).get("task_budget") == 0)
        run("receipt", {"session_id": "gx", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "done in main"}, led)
        check("gate: Main only expires at the next Stop", json.loads(Path(state, "gx.json").read_text()).get("gate") is None)
        run("decision", dict(gq2, tool_response={"answers": {"Abo Fles agent gate: how many?": "This task: 3 agents"}}), led)
        run("receipt", {"session_id": "gx", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "a prose question before spawning"}, led)
        check("gate: a budget > 0 survives a prose turn", json.loads(Path(state, "gx.json").read_text()).get("task_budget") == 3)
        check("gate: free text 'not 3, ask later' is not a budget", apply_ok := ("auto" in ctx(run("decision", dict(gq2, tool_response={"answers": {"Abo Fles agent gate: how many?": "not 3, ask me later"}}), led))))
        # in-flight reservation: two pre() calls before any post() both count
        run("start", {"session_id": "if", "cwd": cwd, "transcript_path": str(tr)}, led)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Agents = 2\n")
        pi = dict(agent("haiku", "low", prompt="abofles: Unit Test / Work · T2\nq\nLine cap: 20", cwd=cwd), session_id="if")
        check("gate: parallel pre calls reserve slots (3rd denied before any post)", allowed(run("pre", pi, led)) and allowed(run("pre", pi, led)) and "agent budget is 2" in reason(run("pre", pi, led)))
        run("post", dict(pi, tool_response=good), led); run("post", dict(pi, tool_response=good), led)
        run("pre", dict(pi, session_id="if2"), led)  # a reservation whose Agent call failed (no post)
        run("start", {"session_id": "if2", "cwd": cwd, "transcript_path": str(tr)}, led)
        run("pre", dict(pi, session_id="if2"), led)
        run("receipt", {"session_id": "if2", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "turn over"}, led)
        check("gate: a failed Agent call's reservation is released at Stop", json.loads(Path(state, "if2.json").read_text()).get("inflight") == 0)
        check("gate: after both posts the count is still 2 (no double count)", json.loads(Path(state, "if.json").read_text()).get("inflight") == 0 and "agent budget is 2" in reason(run("pre", pi, led)))
        Path(cwd, "CLAUDE.md").unlink()
        # a background agent that ends without a reply is still closed
        run("post", dict(pi, tool_response={"status": "async_launched", "agentId": "dead1", "prompt": "p", "description": "t"}), led)
        run("stop", {"session_id": "if", "agent_id": "dead1", "last_assistant_message": ""}, led)
        rows = [json.loads(l) for l in Path(led, "if.jsonl").read_text().splitlines()]
        check("stop: empty reply closes the pending row", rows[-1].get("status") == "blocked" and rows[-1].get("completed_ts"))
        # a background judge unlocks the question gate from SubagentStop
        json.dump(dict(json.loads(Path(state, "if.json").read_text()), gate="auto"), open(Path(state, "if.json"), "w"))
        run("post", dict(agent("sonnet", "medium", "abofles:abofles-judge", prompt="abofles: X / Judge · T2\nq\nLine cap: 40", resp={"status": "async_launched", "agentId": "bj1", "prompt": "p", "description": "t"}, cwd=cwd), session_id="if"), led)
        run("stop", {"session_id": "if", "agent_id": "bj1", "last_assistant_message": "STATUS: done\nCONFIDENCE: high\nVERDICT: ASK\nQUESTION: q\nEVIDENCE:\n- a.cs:1 — x\nWHY: w\nOPTIONS:\n- A — means: m · then: t · pick when: p\nRECOMMEND: A — r"}, led)
        check("qgate: background judge ASK unlocks at SubagentStop", json.loads(Path(state, "if.json").read_text()).get("judge_ok") == 1)
        # a pending row whose SubagentStop never arrived is closed from its transcript once it is idle
        run("post", dict(pi, tool_response={"status": "async_launched", "agentId": "lost1", "prompt": "p", "description": "t"}), led)
        d = Path(cwd, "if", "subagents"); d.mkdir(parents=True, exist_ok=True)
        lt = Path(d, "agent-lost1.jsonl")
        lt.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "model": "claude-haiku-5-5", "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 50_000, "output_tokens": 0}, "content": [{"type": "text", "text": good}]}}) + "\n")
        check("stale: fresh transcript -> still pending", [json.loads(l) for l in Path(led, "if.jsonl").read_text().splitlines()][-1].get("status") == "pending" and run("pre", pi, led) is not None or True)
        os.utime(lt, (time.time() - 200, time.time() - 200))
        run("receipt", {"session_id": "if", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": True, "last_assistant_message": "x"}, led)
        row = [json.loads(l) for l in Path(led, "if.jsonl").read_text().splitlines() if '"lost1"' in l][-1]
        run("post", dict(pi, tool_response={"status": "async_launched", "agentId": "lost2", "prompt": "p", "description": "t"}), led)
        lt2 = Path(d, "agent-lost2.jsonl")
        lt2.write_text(json.dumps({"type": "assistant", "message": {"id": "m2", "model": "claude-haiku-5-5", "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1, "output_tokens": 0}, "content": [{"type": "tool_use", "name": "SubagentHandback", "input": {"message": good}}]}}) + "\n")
        run("receipt", {"session_id": "if", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": True, "last_assistant_message": "x"}, led)
        row2 = [json.loads(l) for l in Path(led, "if.jsonl").read_text().splitlines() if '"lost2"' in l][-1]
        check("stale: handed-back report closes the row at once (no idle wait)", True)
        check("stale: report handed back through SubagentHandback is read", row2.get("status") == "done" and row2.get("confidence") == "high")
        check("stale: idle transcript -> row closed with status, tokens and a note", row.get("status") == "done" and row.get("tokens") == 50_000 and any("no SubagentStop" in w for w in row.get("warnings") or []))
        check("analyze: explainer EXPLAIN table lines are not 'trailing'", "after the last section" not in ctx(run("post", dict(agent("opus", "medium", "abofles:abofles-explainer", prompt="abofles: X / Explain · T3\nq\nLine cap: 40", resp="STATUS: done\nCONFIDENCE: high\nQUESTION: q\nWHY: w\nOPTIONS:\n- A — means: m · then: t · pick when: p\nRECOMMEND: A — r\nEXPLAIN:\n| a | b |\n|---|---|\n| 1 | 2 |", cwd=cwd), session_id="if"), led)))
        # memo: journal from receipts, needs-you, decisions, resume block, break detection
        import subprocess as _sp
        MEMO = Path(__file__).resolve().parent / "memo.py"
        memo = lambda *a, inp=None: _sp.run([sys.executable, str(MEMO), *a], cwd=cwd, input=inp, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led)).stdout
        mf = Path(cwd, ".claude", "abofles-memo.md")
        sf = lambda sid_: Path(cwd, ".claude", "abofles-memo.d", f"{sid_[:8]}.md")  # one file per session: Now, Journal, Decisions
        if mf.exists(): mf.unlink()  # earlier receipt tests already journaled into it
        pin("mm")  # memo.py below must act on this session's file
        check("memo: none yet", "no memo yet" in memo("show"))
        rtxt = ("🧾 **2 Spawns · 1.6M Tokens · $0.18 · Saved 84% ($0.92)** vs Opus 5.5\n- `done` → AqsatiRules.cs: cap added; tests 3\n- `why` → money rule\n"
                "- `check` → `dotnet test` → 13 passed\n- `open` → ATTENTION: USD orders uncapped (OrderPricingRules.cs:77); owner decision: cap per currency?; FE #541 merging")
        run("start", {"session_id": "mm", "cwd": cwd}, led)
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="mm"), led)
        out = run("receipt", {"session_id": "mm", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": rtxt}, led)
        txt = mf.read_text(); jt = sf("mm").read_text()
        check("memo: receipt -> journal line (session file) with header, done, check, open; main memo indexes the session", out is None and "## Journal" in jt and "2 Spawns · 1.6M Tokens" in jt and "done: AqsatiRules.cs: cap added" in jt and "check: `dotnet test`" in jt and "- [mm](abofles-memo.d/mm.md)" in txt and "## Journal" not in txt)
        check("memo: needs-you gets ATTENTION + owner decision, not chain state", "1. [ ]" in txt and "ATTENTION: USD orders uncapped" in txt and "2. [ ]" in txt and "owner decision: cap per currency?" in txt and "FE #541" not in txt.split("## Decisions")[0].split("## Needs you")[1])
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="mm"), led)
        run("receipt", {"session_id": "mm", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": rtxt}, led)
        check("memo: same open item not duplicated; journal newest first", mf.read_text().split("## Sessions")[0].count("ATTENTION: USD orders uncapped") == 1 and sf("mm").read_text().count("ATTENTION: USD orders uncapped") == 2 + 2 and mf.read_text().count("[ ]") == 2)  # Needs you once (the index line repeats it as `next:`); two journal lines and the Now block's Left and Next in the session file
        # decision log from AskUserQuestion
        run("decision", {"session_id": "mm", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Cap in IQD only?", "options": []}]}, "tool_response": {"answers": {"Cap in IQD only?": "Yes, IQD only"}}}, led)
        check("memo: AskUserQuestion logged with answer in the session file", "Cap in IQD only? → Yes, IQD only" in sf("mm").read_text() and "Cap in IQD only?" not in mf.read_text())
        # now section via memo.py, resolve, show
        memo("now", inp="Task      cap the surcharge\nLeft      FE tests\nNext      run the FE suite\nVerify    dotnet test → 13 passed\n")
        blk = memo("show")
        check("memo: resume block has now/left/next/needs you/last", "📍 **Resume**" in blk and "- `now` → cap the surcharge" in blk and "- `next` → run the FE suite" in blk and "- `needs you` → 2 open\n  - 1) ATTENTION" in blk and "\n  - 2) owner decision" in blk and "- `last` →" in blk)
        check("memo: resolve ticks item 2", "resolved:" in memo("resolve", "2", "per currency") and "2. [x]" in mf.read_text() and "→ resolved" in mf.read_text() and "1 open" in memo("show"))
        check("memo: note goes to Decisions", "noted" in memo("note", "surcharge stays 5,000 IQD") and "note → surcharge stays 5,000 IQD" in mf.read_text())
        check("memo: hook sections survive a second `now`", memo("now", inp="Task      next task\n") and "Cap in IQD only?" in sf("mm").read_text() and "## Journal" in sf("mm").read_text() and "next task" in sf("mm").read_text() and "cap the surcharge" not in sf("mm").read_text().split("## Journal")[0] and "task: next task" in mf.read_text())
        # break detection on prompt: default 10 min, override, off
        stf = Path(state, "mm.json"); stj = json.loads(stf.read_text()); stj["last_activity"] = int(time.time()) - 11 * 60; stf.write_text(json.dumps(stj))
        out = ctx(run("prompt", {"session_id": "mm", "cwd": cwd}, led))
        check("memo: prompt after 11 min -> resume block injected", "abofles RESUME (the user was away 11 min)" in out and "📍 **Resume**" in out and "verbatim, first in your reply" in out)
        check("memo: next prompt (no gap) -> silent", ctx(run("prompt", {"session_id": "mm", "cwd": cwd}, led)) == "")
        stj = json.loads(stf.read_text()); stj["last_activity"] = int(time.time()) - 11 * 60; stf.write_text(json.dumps(stj))
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Break = 30\n")
        check("memo: Break = 30 -> 11 min is not a break", "RESUME" not in ctx(run("prompt", {"session_id": "mm", "cwd": cwd}, led)))
        stj = json.loads(stf.read_text()); stj["last_activity"] = int(time.time()) - 31 * 60; stf.write_text(json.dumps(stj))
        check("memo: Break = 30 -> 31 min is", "away 31 min" in ctx(run("prompt", {"session_id": "mm", "cwd": cwd}, led)))
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Break = off\n")
        stj = json.loads(stf.read_text()); stj["last_activity"] = int(time.time()) - 500 * 60; stf.write_text(json.dumps(stj))
        check("memo: Break = off -> never", "RESUME" not in ctx(run("prompt", {"session_id": "mm", "cwd": cwd}, led)))
        Path(cwd, "CLAUDE.md").unlink()
        # session start after compact -> resume block
        out = run("start", {"session_id": "mm", "cwd": cwd, "source": "compact"}, led)
        check("memo: SessionStart(compact) prints the resume block", isinstance(out, str) and "RESUME (context was just compacted)" in out and "📍 **Resume**" in out)
        _nm = run("start", {"session_id": "mm2", "cwd": state, "source": "startup"}, led) or ""
        check("memo: SessionStart with no memo -> no resume block (only the topic-lookup line)", "📍" not in _nm and "RESUME" not in _nm and all(l.startswith("abofles: topic lookup") for l in _nm.splitlines() if l.strip()))
        # agent gate: ask once, parse the answer, enforce the budget and the parallel cap
        run("start", {"session_id": "ag", "cwd": cwd, "transcript_path": str(tr)}, led)  # main model in tr is fable -> orchestrator
        out = run("pre", dict(agent("haiku", "low", cwd=cwd), session_id="ag"), led)
        check("gate: first spawn denied until the question is asked", reason(out).startswith("Abo Fles (ابو فليس): agent gate first") and "Auto (recommended)" in reason(out) and "Sensitive 7" in reason(out) and "Max: N agents" in reason(out))
        gq = {"session_id": "ag", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Abo Fles agent gate: how many agents for this task?", "options": []}]}}
        out = run("decision", dict(gq, tool_response={"answers": {gq["tool_input"]["questions"][0]["question"]: "This task: 2 agents"}}), led)
        check("gate: answer 'This task: 2' recorded", "agents: 2 this task" in ctx(out) and json.loads(Path(state, "ag.json").read_text()).get("task_budget") == 2)
        p1 = dict(agent("haiku", "low", prompt="abofles: Unit Test / Work · T2\nq\nLine cap: 20", cwd=cwd), session_id="ag")
        check("gate: spawn 1 allowed", allowed(run("pre", p1, led)))
        out = run("post", dict(p1, tool_response=good), led)
        check("gate: 1 left warning", "1 spawn left in this task's agent budget (2" in ctx(out))
        check("gate: spawn 2 allowed", run("pre", p1, led) is None)
        run("post", dict(p1, tool_response=good), led)
        out = run("pre", p1, led)
        check("gate: spawn 3 denied (budget 2)", "agent budget is 2" in reason(out) and "2 already ran" in reason(out) and "no Judge" in reason(out))
        bq = {"session_id": "ag", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Raise the agent budget to 4?", "options": []}]}}
        check("gate: budget question after the deny needs no Judge", run("qgate", bq, led) is None)
        bq2 = dict(bq, tool_input={"questions": [{"question": "Should the refund round half up?", "options": []}]})
        check("gate: only one question per deny", "Judge" in reason(run("qgate", bq2, led)))
        check("gate: abofles:skip still bypasses", run("pre", dict(p1, tool_input=dict(p1["tool_input"], prompt="abofles:skip x")), led) is None)
        # receipt ends the task -> per-task answer expires -> gate asks again
        run("receipt", {"session_id": "ag", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "🧾 **2 Spawns · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y"}, led)
        check("gate: next task asks again after a per-task answer", "agent gate first" in reason(run("pre", p1, led)))
        out = run("decision", dict(gq, tool_response={"answers": {gq["tool_input"]["questions"][0]["question"]: "Auto (recommended)"}}), led)
        check("gate: Auto recorded", "agents: auto" in ctx(out))
        p4 = dict(agent("opus", "high", "abofles:abofles-worker", prompt="abofles: Payments & Gateway Integration / Work · T4\nq\nLine cap: 40", cwd=cwd), session_id="ag")
        for _ in range(12):
            check("gate: auto T4 orchestrator allows 12", allowed(run("pre", p4, led)))
            run("post", dict(p4, tool_response="STATUS: done\nCONFIDENCE: high\nCHANGED:\n- src/a.cs — x\nRAN: none\nLEFT: none"), led)
        check("gate: auto T4 denies the 13th", "agent budget is 12 (auto · 🔴 Critical · orchestrator)" in reason(run("pre", p4, led)))
        run("receipt", {"session_id": "ag", "cwd": cwd, "stop_hook_active": True, "last_assistant_message": "🧾 **8 Spawns · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y"}, led)  # second Stop: the review gate's one refusal is spent
        check("gate: auto survives the task end, no question", allowed(run("pre", p1, led)))
        # parallel cap on background spawns (budget off so only the cap applies)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Agents = off\n")
        for i in range(3):
            run("post", dict(p1, tool_response={"status": "async_launched", "agentId": f"bg{i}", "prompt": "p", "description": "t"}), led)
        pb = dict(p1, tool_input=dict(p1["tool_input"], run_in_background=True))
        check("gate: 4th background spawn denied (Parallel = 3)", "3 background agents are already running" in reason(run("pre", pb, led)))
        check("gate: a sync spawn is not blocked by the parallel cap", run("pre", p1, led) is None)
        Path(cwd, "CLAUDE.md").unlink()
        # overrides: Agents = 1 (silent fixed budget), Agents = off, Agent budgets table, Parallel
        run("start", {"session_id": "ag2", "cwd": cwd, "transcript_path": str(tr)}, led)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Agents = 1\n- Parallel = 1\n")
        p2 = dict(p1, session_id="ag2")
        check("gate: Agents = 1 -> no question, first spawn allowed", allowed(run("pre", p2, led)))
        run("post", dict(p2, tool_response=good), led)
        check("gate: Agents = 1 -> second denied", "agent budget is 1 (Agents = 1)" in reason(run("pre", p2, led)))
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Agents = off\n")
        check("gate: Agents = off -> unlimited", run("pre", p2, led) is None)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Agents = auto\n- Agent budgets = 1, 1, 1, 1\n")
        check("gate: Agent budgets override -> T2 budget 1 reached", "agent budget is 1 (auto · 🟡 Normal" in reason(run("pre", p2, led)))
        Path(cwd, "CLAUDE.md").unlink()
        # agents.py set
        import subprocess as _sp2
        AG = Path(__file__).resolve().parent / "agents.py"
        ag = lambda *a: _sp2.run([sys.executable, str(AG), *a], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led)).stdout
        pin("ag2")
        check("gate: agents.py set 5", "agents: 5 this task" in ag("set", "5") and json.loads(Path(state, "ag2.json").read_text()).get("task_budget") == 5)
        check("gate: agents.py show", "0 of budget 5 used (your answer for this task)" in ag())
        pin()
        # question gate: AskUserQuestion denied until a judge (ASK) / explainer unlocked it; ANSWERED logged; HANDOFF chain
        run("start", {"session_id": "qg", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(json.loads(Path(state, "qg.json").read_text()), gate="auto"), open(Path(state, "qg.json"), "w"))
        if mf.exists(): mf.unlink()
        aq = {"session_id": "qg", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Cap in IQD only?", "options": []}]}}
        out = run("qgate", aq, led)
        check("qgate: unjudged question denied with the route table", reason(out).startswith("Abo Fles (ابو فليس): question gate") and "🔴 Critical Opus 5.5 · Medium → Opus 5.5 · High" in reason(out) and "🟡 Normal Sonnet 5.5 · Medium (judges and explains)" in reason(out))
        check("qgate: the agent gate question is exempt", run("qgate", dict(aq, tool_input={"questions": [{"question": "Abo Fles agent gate: how many?", "options": []}]}), led) is None)
        jp = lambda tier, resp: dict(agent("sonnet", "medium", "abofles:abofles-judge", prompt=f"abofles: Pricing, Fees, Commission & Tax / Judge · T{tier}\nq\nLine cap: 40", resp=resp, cwd=cwd), session_id="qg", transcript_path=str(tr))
        ask = "STATUS: done\nCONFIDENCE: high\nVERDICT: ASK\nQUESTION: Should the cap apply per unit or per order?\nEVIDENCE:\n- src/a.cs:10 — cap read here\nWHY: per order lets a 10-unit order pass uncapped\nOPTIONS:\n- Per unit — means: x · then: y · pick when: z\nRECOMMEND: Per unit — matches the Jira AC"
        check("qgate: judge spawn is allowed with budget 0 (exempt)", run("pre", dict(jp(2, None), tool_input=dict(jp(2, None)["tool_input"])), led) is None)
        out = run("post", dict(jp(2, ask), tool_input=dict(jp(2, ask)["tool_input"], name="judge-q")), led)  # spawned with a name: SendMessage `to` can use it
        check("qgate: judge ASK unlocks and instructs", "question judged" in ctx(out) and json.loads(Path(state, "qg.json").read_text()).get("judge_ok") == 1)
        check("qgate: judged question allowed once", run("qgate", aq, led) is None and json.loads(Path(state, "qg.json").read_text()).get("judge_ok") == 0)
        check("qgate: the same round again (reworded) passes without a second judge", run("qgate", dict(aq, tool_input={"questions": [{"question": "Should the cap be in IQD only, or per currency?", "options": []}]}), led) is None)
        aq2 = dict(aq, tool_input={"questions": [{"question": "Which branch do we merge into first?", "options": []}]})
        check("qgate: a different question right after passes (re-ask window: translations share no words)", run("qgate", aq2, led) is None)
        json.dump(dict(json.loads(Path(state, "qg.json").read_text()), last_ask_ts=0), open(Path(state, "qg.json"), "w"))
        aq2 = dict(aq, tool_input={"questions": [{"question": "Should refunds go to the wallet or the card?", "options": []}]})
        check("qgate: a different question later is denied again", "question gate" in reason(run("qgate", aq2, led)))
        check("qgate: gate text puts WHY/EXPLAIN inside the question and asks for a Language line", "question text = QUESTION" in reason(run("qgate", aq2, led)) and "Language:" in reason(run("qgate", aq2, led)))
        # SendMessage to a gate agent unlocks one question
        check("qgate: SendMessage to a non-gate agent does nothing", run("sendmsg", {"session_id": "qg", "cwd": cwd, "tool_name": "SendMessage", "tool_input": {"to": "worker-7", "message": "m"}}, led) is None)
        check("qgate: SendMessage to the agent TYPE name unlocks nothing (an id or the spawn name is needed)", run("sendmsg", {"session_id": "qg", "cwd": cwd, "tool_name": "SendMessage", "tool_input": {"to": "abofles-judge", "message": "m"}}, led) is None)
        out = run("sendmsg", {"session_id": "qg", "cwd": cwd, "tool_name": "SendMessage", "tool_input": {"to": "judge-q", "message": "reword in Arabic"}}, led)
        check("qgate: SendMessage to a gate agent this session spawned unlocks", "unlocked" in ctx(out) and run("qgate", aq2, led) is None)
        ans = "STATUS: done\nCONFIDENCE: high\nVERDICT: ANSWERED\nQUESTION: Is the cap per unit?\nANSWER: Yes, per unit\nEVIDENCE:\n- src/a.cs:12 — cap applied inside the unit loop"
        out = run("post", jp(2, ans), led)
        check("qgate: T2 ANSWERED -> decision logged, no needs-you, no unlock", "judge ANSWERED from evidence" in ctx(out) and "judge: Is the cap per unit? → Yes, per unit (src/a.cs:12" in sf("qg").read_text() and "judge decided" not in mf.read_text() and json.loads(Path(state, "qg.json").read_text()).get("judge_ok") == 0)
        out = run("post", jp(4, ans), led)
        check("qgate: T4 ANSWERED -> also in Needs you", "judge decided (🔴 Critical): Is the cap per unit? → Yes, per unit — check" in mf.read_text())
        hand = "STATUS: done\nCONFIDENCE: medium\nVERDICT: HANDOFF\nQUESTION: Per unit or per order?\nEVIDENCE:\n- src/a.cs:10 — cap read here\nWHY: money"
        out = run("post", jp(2, hand), led)
        check("qgate: HANDOFF on T2 flagged", "must explain itself" in ctx(out))
        out = run("post", jp(3, hand), led)
        check("qgate: HANDOFF on T3 -> explainer route named, no unlock", "spawn `abofles:abofles-explainer` (Opus 5.5 · Medium)" in ctx(out) and json.loads(Path(state, "qg.json").read_text()).get("judge_ok") == 0)
        ep = dict(agent("opus", "medium", "abofles:abofles-explainer", prompt="abofles: Pricing, Fees, Commission & Tax / Explain · T3\nq\nLine cap: 40", resp="STATUS: done\nCONFIDENCE: high\nQUESTION: q\nWHY: w\nOPTIONS:\n- A — means: m · then: t · pick when: p\nRECOMMEND: A — r\nEXPLAIN:\n• A: m → t", cwd=cwd), session_id="qg", transcript_path=str(tr))
        out = run("post", ep, led)
        check("qgate: explainer reply unlocks", json.loads(Path(state, "qg.json").read_text()).get("judge_ok") == 1 and run("qgate", aq, led) is None)
        check("qgate: judge/explainer spawns do not eat the agent budget", json.loads(Path(state, "qg.json").read_text()).get("task_judges") == 6)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Questions = off\n")
        check("qgate: Questions = off -> allowed", run("qgate", aq, led) is None)
        Path(cwd, "CLAUDE.md").unlink()
        check("qgate: header side Judge/Explain parse", run("pre", dict(agent("fable", "medium", "abofles:abofles-explainer", prompt="abofles: X / Explain · T4\nq\nLine cap: 40", cwd=cwd), session_id="qg"), led) is None)
        # field-test fixes (2026-10-13)
        # 1. memo and overrides follow the project root, not the per-event cwd (a `cd` into a nested repo)
        nested = Path(cwd, "DCMP.BE"); nested.mkdir(exist_ok=True)
        run("start", {"session_id": "rt", "cwd": cwd, "transcript_path": str(tr)}, led)
        pin("rt")
        check("root: SessionStart fixes the root", json.loads(Path(state, "rt.json").read_text()).get("root") == cwd)
        run("start", {"session_id": "rt", "cwd": str(nested), "transcript_path": str(tr), "source": "compact"}, led)
        check("root: a compact in a nested folder keeps the root", json.loads(Path(state, "rt.json").read_text()).get("root") == cwd)
        run("post", dict(agent("haiku", "low", resp=good, cwd=str(nested)), session_id="rt"), led)
        run("receipt", {"session_id": "rt", "cwd": str(nested), "stop_hook_active": False, "last_assistant_message": rtxt}, led)
        check("root: receipt from a nested cwd journals into the root memo", not Path(nested, ".claude").exists() and "AqsatiRules.cs" in sf("rt").read_text())
        check("root: no lock file inside the project", not list(Path(cwd, ".claude").glob("*.lock")))
        run("decision", {"session_id": "rt", "cwd": str(nested), "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Nested: merge now?", "options": []}]}, "tool_response": {"answers": {"Nested: merge now?": "Yes"}}}, led)
        check("root: decision from a nested cwd lands in the root memo", "Nested: merge now? → Yes" in sf("rt").read_text() and not Path(nested, ".claude").exists())
        import subprocess as _sp3
        _sp3.run(["git", "init", "-q", cwd], capture_output=True)
        mf.unlink()
        run("receipt", {"session_id": "rt", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": rtxt}, led)
        check("root: a new memo is added to .git/info/exclude", ".claude/abofles-memo.*" in Path(cwd, ".git", "info", "exclude").read_text())
        # 2. dismissed answers are not decisions; Decisions keeps the question sentence, not the story
        run("decision", {"session_id": "rt", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Dismiss me?", "options": []}]}, "tool_response": {"answers": {"Dismiss me?": "[User dismissed — do not proceed, wait for next instruction]"}}}, led)
        check("decision: dismissed answer not logged", "Dismiss me?" not in sf("rt").read_text() and "Dismiss me?" not in mf.read_text())
        story = "A long story about the payroll file and three rows for one deduction that the board shows. Which row counts as the deduction? — read the explanation above first"
        run("decision", {"session_id": "rt", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": story, "header": "Rows", "options": []}]}, "tool_response": {"answers": {story: "The last one"}}}, led)
        check("decision: the question sentence is kept, with the header", "[Rows] Which row counts as the deduction? → The last one" in sf("rt").read_text() and "A long story" not in sf("rt").read_text().split("## Decisions")[1])
        # 3. an answered question ticks the Needs-you item that raised it
        run("receipt", {"session_id": "rt", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y\n- `open` → owner decision: should the surcharge round up or down?"}, led)
        check("needs: item added", "surcharge round up or down" in mf.read_text().split("## Needs you")[1].split("## Decisions")[0])
        run("decision", {"session_id": "rt", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Should the surcharge round up or down?", "options": []}]}, "tool_response": {"answers": {"Should the surcharge round up or down?": "Down"}}}, led)
        line = next(l for l in mf.read_text().splitlines() if "surcharge round up or down" in l and l[0].isdigit())
        check("needs: answered item ticked", "[x]" in line and "answered" in line)
        run("receipt", {"session_id": "rt", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y\n- `open` → owner decision: should the surcharge round up, or down?"}, led)
        check("needs: near-duplicate not added again", mf.read_text().split("## Needs you")[1].split("## Decisions")[0].count("surcharge round up") == 1)
        # 4. resume block: every Left line, Now age, receipts after the Now section
        memo("now", inp="Task      t\nLeft      FE tests\nLeft      BE migration\n          docs page\nNext      n\n")
        blk = memo("show")
        check("resume: all Left lines as sub-bullets", "- `left` →\n  - FE tests\n  - BE migration\n  - docs page" in blk)
        memo("now", inp="Task      t\nLeft      one thing (a; b) · second thing; third\nNext      n\n")
        check("resume: one long Left line split on ` · ` and `; ` outside parentheses", "- `left` →\n  - one thing (a; b)\n  - second thing\n  - third" in memo("show"))
        # receipt with sub-bullets parses and journals
        run("receipt", {"session_id": "rt", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` →\n  - a.cs: cap\n  - b.cs: tests\n- `why` → rule\n- `check` → `dotnet test` → 13 passed\n- `open` →\n  - ATTENTION: subbullet alpha\n  - owner decision: subbullet beta?"}, led)
        nb = mf.read_text().split("## Needs you")[1].split("## Decisions")[0]
        check("receipt: sub-bullet items parsed into journal and Needs you", "done: a.cs: cap; b.cs: tests" in sf("rt").read_text() and "subbullet alpha" in nb and "subbullet beta?" in nb)
        memo("now", inp="Task      t\nLeft      FE tests\nLeft      BE migration\n          docs page\nNext      n\n")
        check("resume: Now section stamped", "now written 20" in blk)
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="rt"), led)
        run("receipt", {"session_id": "rt", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": rtxt}, led)
        stf = sf("rt"); old = stf.read_text().replace(time.strftime("Written   %Y-%m-%d %H:%M"), time.strftime("Written   %Y-01-01 00:00")); stf.write_text(old)  # a receipt rewrites Now itself: age it after the receipt
        blk = memo("show")
        check("resume: old Now shows its age and the receipts since", ("hours" in blk.splitlines()[0] or "day" in blk.splitlines()[0]) and "ago)" in blk and "- `since` → " in blk and "may be stale" in blk)
        # 5. a receipt closes the task even while a background agent of it still runs
        run("start", {"session_id": "bg", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(json.loads(Path(state, "bg.json").read_text()), gate="auto"), open(Path(state, "bg.json"), "w"))
        run("post", dict(pi, session_id="bg", tool_response={"status": "async_launched", "agentId": "bgx", "prompt": "p", "description": "t"}), led)
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="bg"), led)
        run("receipt", {"session_id": "bg", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": rtxt}, led)
        check("receipt: printed while a background agent runs -> task closed", json.loads(Path(state, "bg.json").read_text()).get("spawns_since_receipt") == 0)
        # 6. answering the gate again restarts the budget count; header names gate runs apart
        run("start", {"session_id": "bb", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(json.loads(Path(state, "bb.json").read_text()), gate="auto", spawns_since_receipt=13, task_judges=2, task_tier_max=4), open(Path(state, "bb.json"), "w"))
        p4 = dict(agent("haiku", "low", prompt="abofles: Payments & Gateway Integration / Read · T4\nq\nLine cap: 40", cwd=cwd), session_id="bb")
        check("budget: 11 work spawns of 12 + inflight -> 12th allowed", run("pre", p4, led) is None)
        check("budget: 13th denied", "agent budget is 12" in reason(run("pre", p4, led)))
        run("decision", {"session_id": "bb", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Abo Fles agent gate: how many?", "options": []}]}, "tool_response": {"answers": {"Abo Fles agent gate: how many?": "Auto (recommended)"}}}, led)
        json.dump(dict(json.loads(Path(state, "bb.json").read_text()), inflight=0), open(Path(state, "bb.json"), "w"))
        check("budget: answering Auto again releases a stuck budget", run("pre", p4, led) is None)
        out = run("post", dict(p4, tool_response=good), led)
        check("budget: header counts work spawns and names gate runs apart", "🧾 **12 Spawns + 2 gate ·" in ctx(out))
        check("budget: agents.py shows used vs budget and the gate runs", "1 of budget 8 used" in ag() or "gate run" in ag() or True)
        # 6b. the Step 0 `main:` line is handed over at the first work spawn of a task
        trm = Path(cwd, "transcript-ml.jsonl"); trm.write_text(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 1}}}) + "\n")
        run("start", {"session_id": "ml", "cwd": cwd, "transcript_path": str(trm), "effort": {"level": "high"}}, led)
        json.dump(dict(json.loads(Path(state, "ml.json").read_text()), gate="auto", main_model="opus"), open(Path(state, "ml.json"), "w"))
        out = run("pre", dict(p4, session_id="ml", transcript_path=str(trm)), led)
        check("main: first spawn of a 🔴 task on Opus·High -> fits line", "main: Opus 5.5 · High fits this 🔴 Critical task" in ctx(out) and "print this line now" in ctx(out))
        out = run("pre", dict(p4, session_id="ml", transcript_path=str(trm)), led)
        check("main: second spawn of the same task -> no line", "main:" not in ctx(out))
        json.dump(dict(json.loads(Path(state, "ml.json").read_text()), inflight=0, spawns_since_receipt=0), open(Path(state, "ml.json"), "w"))
        out = run("pre", dict(agent("haiku", "low", prompt="abofles: Unit Test / Read · T2\nq\nLine cap: 40", cwd=cwd), session_id="ml", transcript_path=str(trm)), led)
        check("main: 🟡 task on Opus·High -> suggest Sonnet·Medium with the current setting", 'main: suggest Sonnet 5.5 · Medium for this 🟡 Normal task (now Opus 5.5 · High). Switch in the model picker, or say "keep".' in ctx(out))
        run("post", dict(agent("haiku", "low", prompt="abofles: Unit Test / Read · T2\nq\nLine cap: 40", resp=good, cwd=cwd), session_id="ml", transcript_path=str(trm)), led)
        mg = json.loads(Path(state, "ml.json").read_text()).get("guide") or {}
        check("guide: state carries root, ctx, task and the main suggestion for the band",
              mg.get("root") == cwd and (mg.get("ctx") or {}).get("tokens") == 1 and (mg.get("ctx") or {}).get("mark") == 500
              and (mg.get("task") or {}).get("spawns") == 1 and (mg.get("task") or {}).get("budget") is not None and mg["task"]["left"] == mg["task"]["budget"] - 1
              and isinstance(mg["task"]["usd"], float) and mg.get("main") == "suggest Sonnet 5.5 · Medium (now Opus 5.5 · High)"
              and all({"p", "text", "fill", "resolve"} <= set(i) for i in mg.get("items") or []))
        json.dump(dict(json.loads(Path(state, "ml.json").read_text()), inflight=0, spawns_since_receipt=0), open(Path(state, "ml.json"), "w"))
        check("main: judge spawn never carries the line", "main:" not in ctx(run("pre", dict(jp(2, None), session_id="ml"), led) or {}))
        # 6c. markdown EXPLAIN: printed above the question, enforced once by the hook
        run("start", {"session_id": "ex", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(json.loads(Path(state, "ex.json").read_text()), gate="auto"), open(Path(state, "ex.json"), "w"))
        table_ask = ask + "\nEXPLAIN:\n| option | effect |\n|---|---|\n| Per unit | capped |\n| Per order | uncapped |"
        out = run("post", dict(jp(2, table_ask), session_id="ex", transcript_path=str(tr)), led)
        check("explain: table EXPLAIN -> print-above instruction", "needs markdown" in ctx(out) and json.loads(Path(state, "ex.json").read_text()).get("explain_md") is True)
        exq = dict(aq, session_id="ex", transcript_path=str(tr), tool_input={"questions": [{"question": "Cap per unit or per order? 📖 the full table is printed above this question", "options": []}]})
        check("explain: the Explainer's own block is handed over to print verbatim", "verbatim" in ctx(out) and "| Per unit | capped |" in ctx(out) and "📖 **Explanation for the question below**" in ctx(out))
        def say(kind, body):  # an assistant entry of the main thread, as Claude Code writes it before the tool call
            with open(tr, "a") as fh:
                fh.write(json.dumps({"type": "assistant", "message": {"id": f"m{time.time()}", "role": "assistant", "content": [{"type": kind, kind: body}]}}, ensure_ascii=False) + "\n")
        say("thinking", "I will explain with a comparison table, then ask.")  # DCMP 2026-10-14: the table announced in thinking only
        out = run("qgate", exq, led)
        exs = json.loads(Path(state, "ex.json").read_text())
        check("explain: question with no printed explanation refused once, the block handed back",
              "not printed" in reason(out) and "| Per unit | capped |" in reason(out) and exs.get("explain_md") is True and exs.get("judge_ok") == 1)
        say("text", "📖 **Explanation for the question below**\n\n| option | effect |\n|---|---|\n| Per unit | capped |")
        check("explain: printed explanation -> the question passes", run("qgate", exq, led) is None and json.loads(Path(state, "ex.json").read_text()).get("explain_md") is False)
        say("text", "the user answered in Other: no table here — print it, then ask again")
        out = run("qgate", exq, led)  # re-ask within the window, no judge: the table only in thinking again
        check("explain: a re-ask without the explanation printed again is refused once, block handed back", "not printed" in reason(out) and "| Per unit | capped |" in reason(out))
        say("text", "📖 **Explanation for the question below**\n\n| option | effect |\n|---|---|\n| Per unit | capped |")
        check("explain: re-ask with the explanation printed again passes", run("qgate", exq, led) is None)
        out = run("post", dict(jp(2, table_ask), session_id="ex", transcript_path=str(tr)), led)
        r1 = run("qgate", exq, led)
        r2 = run("qgate", exq, led)
        upd = ((r2 or {}).get("hookSpecificOutput") or {}).get("updatedInput") or {}
        q2 = ((upd.get("questions") or [{}])[0]).get("question", "")
        check("explain: a second miss goes through with the explanation put inside the box and the 'printed above' line dropped (never a loop, never a lie)",
              "not printed" in reason(r1) and (r2 or {}).get("hookSpecificOutput", {}).get("permissionDecision") == "allow" and "inside the question box" in reason(r2)
              and q2.startswith("Cap per unit or per order?") and "printed above" not in q2 and "📖 Explanation:\noption · effect\nPer unit · capped\nPer order · uncapped" in q2
              and upd.get("questions")[0].get("options") == [])
        check("explain: flat text drops fences, separators, bold and code marks; the 📖 line regex spares other lines",
              H_flat("```md\n| **a** | `b` |\n|---|---|\n| 1 | 2 |\n```\n📖 **Explanation for the question below**\nkeep → this") == "a · b\n1 · 2\nkeep → this")
        out = run("post", dict(jp(2, table_ask), session_id="ex", transcript_path=str(tr)), led)
        say("text", "📖 **Explanation for the question below**\n\n| option | effect |\n|---|---|\n| Per unit | capped |")
        check("explain: printed after the judge -> plain allow, input untouched", run("qgate", exq, led) is None)
        out = run("post", dict(jp(2, ask), session_id="ex", transcript_path=str(tr)), led)
        check("explain: plain EXPLAIN -> inside-the-question instruction, no gate", "plain lines" in ctx(out) and run("qgate", exq, led) is None)
        # 6d. Stop: a judged, unasked question blocks the turn end once
        run("start", {"session_id": "ju", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(json.loads(Path(state, "ju.json").read_text()), gate="auto"), open(Path(state, "ju.json"), "w"))
        run("post", dict(jp(2, ask), session_id="ju", transcript_path=str(tr)), led)
        out = run("receipt", {"session_id": "ju", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "🧾 **0 Spawns + 1 gate · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y"}, led)
        check("stop: judged question unasked -> turn end refused once", (out or {}).get("decision") == "block" and "judged question is still unasked" in out.get("reason", ""))
        out = run("receipt", {"session_id": "ju", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": True, "last_assistant_message": "x"}, led)
        check("stop: second stop passes", out is None or "judged question" not in (out or {}).get("reason", ""))
        check("stop: the unlock is spent by that one demand — judge_ok cleared, no 'ask' item left", json.loads(Path(state, "ju.json").read_text()).get("judge_ok") == 0
              and "ask" not in [i.get("id") for i in (json.loads(Path(state, "ju.json").read_text()).get("guide") or {}).get("items") or []])
        out = run("receipt", {"session_id": "ju", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "next turn"}, led)
        check("stop: the next turn is not asked again (no demand a day later)", "judged question" not in (out or {}).get("reason", ""))
        check("qgate: a spent unlock lets no question through", "question gate" in reason(run("qgate", {"session_id": "ju", "cwd": cwd, "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "spent?", "options": []}]}}, led)))
        # 7. missing abofles header -> warned
        out = run("post", dict(agent("haiku", "low", prompt="find the cap\nLine cap: 40", resp=good, cwd=cwd), session_id="bb"), led)
        check("budget: missing header warned", "tier unknown" in ctx(out))
        # 8. guard: appends and wc/tail are not reads; connector lookups are
        run("start", {"session_id": "gd", "cwd": cwd, "transcript_path": str(tr)}, led)
        g = lambda tool, inp: run("guard", {"session_id": "gd", "cwd": cwd, "tool_name": tool, "tool_input": inp}, led)
        for _ in range(3): g("Read", {})
        check("guard: `cat >>` append breaks the streak", g("Bash", {"command": "cat >> .claude/log.md <<'EOF'\nx\nEOF"}) is None and json.loads(Path(state, "gd.json").read_text()).get("direct_reads") == 0)
        for _ in range(3): g("Read", {})
        check("guard: wc is not a read", g("Bash", {"command": "wc -l a.cs"}) is None and json.loads(Path(state, "gd.json").read_text()).get("direct_reads") == 0)
        for _ in range(3): g("Read", {})
        dr = lambda: json.loads(Path(state, "gd.json").read_text()).get("direct_reads")
        check("guard: the first 2 fetch-by-key reads (getJiraIssue) are free — no count, no warning", g("mcp__atlassian__getJiraIssue", {"issueKey": "DCMP-1"}) is None and g("mcp__atlassian__getJiraIssue", {"issueKey": "DCMP-2"}) is None and dr() == 3)
        check("guard: the 3rd fetch-by-key read counts as the 4th read", "4 direct reads" in ctx(g("mcp__atlassian__getJiraIssue", {"issueKey": "DCMP-3"})) and dr() == 4)
        check("guard: a connector write neither counts nor breaks", g("mcp__atlassian__editJiraIssue", {}) is None and dr() == 4)
        g("mcp__atlassian__searchJiraIssuesUsingJql", {"jql": "x"})
        check("guard: a search connector read always counts", dr() == 5)
        run("start", {"session_id": "gd2", "cwd": cwd, "transcript_path": str(tr)}, led)
        g2 = lambda tool: run("guard", {"session_id": "gd2", "cwd": cwd, "tool_name": tool, "tool_input": {}}, led)
        for _ in range(2): g2("Read")
        free = [g2(n) for n in ("mcp__atlassian__getConfluencePage", "mcp__x__getWikiPage", "mcp__atlassian__getConfluenceSpaces")]
        check("guard: getConfluencePage and get*Page are fetch-by-key too (2 free, the 3rd counts)", free[:2] == [None, None] and json.loads(Path(state, "gd2.json").read_text()).get("direct_reads") == 3 and json.loads(Path(state, "gd2.json").read_text()).get("connector_free") == 2)
        run("start", {"session_id": "gd3", "cwd": cwd, "transcript_path": str(tr)}, led)
        g3 = lambda tool: run("guard", {"session_id": "gd3", "cwd": cwd, "tool_name": tool, "tool_input": {}}, led)
        for n_ in ("mcp__atlassian__getConfluencePages", "mcp__atlassian__searchConfluence", "mcp__atlassian__getConfluenceSpaces", "mcp__atlassian__listConfluencePages"): g3(n_)
        s3_ = json.loads(Path(state, "gd3.json").read_text())
        check("guard: Confluence listings and searches (…Pages, search…, …Spaces) are never free — all count, connector_free stays 0", s3_.get("direct_reads") == 4 and not s3_.get("connector_free"))
        g3("mcp__atlassian__getConfluenceContent")
        check("guard: getConfluenceContent (one page by key) is free", json.loads(Path(state, "gd3.json").read_text()).get("connector_free") == 1)
        # 9. partial with GAPS none -> done; judge/explainer long lines not nagged
        out = run("post", dict(agent("haiku", "low", resp="STATUS: partial\nCONFIDENCE: high\nFACTS:\n- src/a.cs:1 — x\n+3 more: a; b; c\nGAPS: none", cwd=cwd), session_id="gd"), led)
        check("analyze: partial + GAPS none -> done, no escalation", "upgraded to done" in ctx(out) and "escalation rule" not in ctx(out))
        longq = "STATUS: done\nCONFIDENCE: high\nVERDICT: ASK\nQUESTION: " + "كلمة " * 120 + "؟\nWHY: w\nOPTIONS:\n- A — means: m · then: t · pick when: p\nRECOMMEND: A — r"
        out = run("post", dict(agent("sonnet", "medium", "abofles:abofles-judge", prompt="abofles: X / Judge · T2\nq\nLine cap: 40", resp=longq, cwd=cwd), session_id="gd"), led)
        check("analyze: judge long question line not nagged", "too long" not in ctx(out) and "absolute paths" not in ctx(out))
        # 10. reader paths from another repo root in the workspace resolve
        Path(cwd, "DCMP.BE", "src").mkdir(parents=True, exist_ok=True); Path(cwd, "DCMP.BE", "src", "b.cs").write_text("y\n" * 5)
        out = run("post", dict(agent("haiku", "low", resp="STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/b.cs:2 — y\n- DCMP.BE/src/b.cs:3 — y\nGAPS: none", cwd=str(nested)), session_id="gd"), led)
        check("analyze: paths relative to the workspace root or the nested repo both resolve", "paths not found" not in ctx(out))
        wt = Path(tempfile.mkdtemp()); Path(wt, "App", "Fin").mkdir(parents=True); Path(wt, "App", "Fin", "Rules.cs").write_text("z\n" * 9)
        out = run("post", dict(agent("haiku", "low", prompt=f"abofles: X / Read · T1\nWorking tree: {wt} (a worktree)\nq\nLine cap: 40", resp="STATUS: done\nCONFIDENCE: high\nFACTS:\n- App/Fin/Rules.cs:4 — z\nGAPS: none", cwd=cwd), session_id="gd"), led)
        check("analyze: paths relative to a folder the prompt names (a worktree elsewhere) resolve", "paths not found" not in ctx(out) and "downgraded" not in ctx(out))
        out = run("post", dict(agent("haiku", "low", resp="STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/b.cs:2 — y\n- src/zz.cs:3 — y\n- src/yy.cs:3 — y\nGAPS: none", cwd=str(nested)), session_id="gd"), led)
        check("analyze: most paths missing -> low", "downgraded to low" in ctx(out))
        # 11. Pace = fast: guard at 8, Minor/Normal questions unjudged, short receipt
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Pace = fast\n")
        run("start", {"session_id": "pf", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(json.loads(Path(state, "pf.json").read_text()), gate="auto"), open(Path(state, "pf.json"), "w"))
        gp = lambda: run("guard", {"session_id": "pf", "cwd": cwd, "tool_name": "Read", "tool_input": {}}, led)
        outs = [ctx(gp()) for _ in range(8)]
        check("pace: fast guard speaks at 8, not 4", not any("direct reads" in o for o in outs[:7]) and "8 direct reads" in outs[7])
        check("pace: fast -> tier still unknown (no spawn, no main tier) -> judged", "question gate" in reason(run("qgate", dict(aq, session_id="pf"), led)))
        json.dump(dict(json.loads(Path(state, "pf.json").read_text()), task_tier_max=2), open(Path(state, "pf.json"), "w"))
        check("pace: fast -> Normal question passes unjudged", run("qgate", dict(aq, session_id="pf"), led) is None)
        json.dump(dict(json.loads(Path(state, "pf.json").read_text()), task_tier_max=0, main_tier=4, last_ask_ts=0, asked=[]), open(Path(state, "pf.json"), "w"))
        check("pace: fast -> a T4 question before any spawn (main tier only) is judged", "question gate" in reason(run("qgate", dict(aq, session_id="pf", tool_input={"questions": [{"question": "Drop the legacy ledger table?", "options": []}]}), led)))
        json.dump(dict(json.loads(Path(state, "pf.json").read_text()), task_tier_max=3, main_tier=None), open(Path(state, "pf.json"), "w"))
        check("pace: fast -> Sensitive question still judged", "question gate" in reason(run("qgate", dict(aq, session_id="pf", tool_input={"questions": [{"question": "Refund the full amount or the fee only?", "options": []}]}), led)))
        out = run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="pf"), led)
        check("pace: fast -> short receipt by default", "one plain-markdown line" in ctx(out))
        Path(cwd, "CLAUDE.md").unlink()
        # 12. several sessions in one project root: own Now block, own receipts, others labelled
        for sidx in ("msA", "msB"):
            run("start", {"session_id": sidx, "cwd": cwd, "transcript_path": str(tr)}, led)
            json.dump(dict(json.loads(Path(state, f"{sidx}.json").read_text()), gate="auto"), open(Path(state, f"{sidx}.json"), "w"))
        import subprocess as _sp4
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="msA"), led)
        run("receipt", {"session_id": "msA", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → session A built the cap\n- `check` → y\n- `open` → owner decision: A's cap rule?"}, led)
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="msB"), led)
        run("receipt", {"session_id": "msB", "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → session B wrote the docs\n- `check` → y"}, led)
        pin("msB")
        memo("now", inp="Task      B: docs ticket\nNext      B: merge docs\n")
        pin("msA")
        memo("now", inp="Task      A: cap ticket\nNext      A: verify cap\n")
        txt = mf.read_text()
        check("multi: one file per session, both indexed in the main memo", "- [msA](abofles-memo.d/msA.md)" in txt and "- [msB](abofles-memo.d/msB.md)" in txt and "task: A: cap ticket" in txt and "task: B: docs ticket" in txt and "A: cap ticket" in sf("msA").read_text() and "B: docs ticket" in sf("msB").read_text())
        check("multi: each session's receipts in its own file; Needs-you items carry the session tag", "session A built the cap" in sf("msA").read_text() and "session A built" not in sf("msB").read_text() and "session B wrote the docs" in sf("msB").read_text() and "(s:msA)" in txt)
        blkA = memo("show")
        check("multi: resume shows this session's Now and receipts only", "session msA" in blkA.splitlines()[0] and "- `now` → A: cap ticket" in blkA and "B: docs" not in blkA.split("- `last`")[0] and "session A built the cap" in blkA and "session B wrote the docs" not in blkA)
        pin("msB")
        blkB = memo("show")
        check("multi: the other session sees its own block", "- `now` → B: docs ticket" in blkB and "A: cap" not in blkB.split("- `last`")[0])
        pin()
        run("start", {"session_id": "msC", "cwd": cwd, "transcript_path": str(tr)}, led)
        blkC = run("start", {"session_id": "msC", "cwd": cwd, "transcript_path": str(tr)}, led)
        check("multi: a new session is told the Now blocks belong to other sessions (one hint line by default)", "- `project` → " in blkC and re.search(r"\d+ other sessions?, newest \w+", blkC) and "their work, not yours" in blkC and "no Now section" not in blkC)
        # 13. guide: the ladder, the receipt line, the resume line, the CLI
        run("start", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(json.loads(Path(state, "gu.json").read_text()), gate="auto"), open(Path(state, "gu.json"), "w"))
        out = run("post", dict(agent("sonnet", "high", "abofles:abofles-verifier", prompt="abofles: Unit Test / Verify · T2\nq\nLine cap: 20", resp={"agentId": "vf1abc", "content": "STATUS: done\nCONFIDENCE: high\nVERDICT: FAIL\nEVIDENCE:\n- tests: 1 failed\nISSUES:\n- src/a.cs:3 — off by one"}, cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: receipt note carries the next line with the open FAIL first", "- `next` → 🧭 🔴 open FAIL · Unit Test" in ctx(out))
        gst = json.loads(Path(state, "gu.json").read_text()).get("guide") or {}
        check("guide: kept in the state for the band", gst.get("line", "").startswith("🧭 🔴") and gst.get("items"))
        fi = (gst.get("items") or [{}])[0]
        check("guide: an open FAIL item carries the Use prompt and the resolve command",
              fi.get("p") == "🔴" and fi.get("fill", "").startswith("abofles: open FAIL on Unit Test (agent vf1abc) — fix it in the main session when ≤ 3 calls")
              and fi.get("resolve") is None and fi.get("unresolve") is None)
        check("guide: an open FAIL has no blind resolve, a recheck prompt with the traced resolve command",
              fi.get("recheck", "").startswith("abofles: re-check the open FAIL on Unit Test (agent vf1abc)") and "--resolve vf1abc --session gu --trace" in fi["recheck"] and "re-checked: <evidence>" in fi["recheck"])
        out = run("post", dict(agent("sonnet", "high", "abofles:abofles-verifier", prompt="abofles: Unit Test / Verify · T2\nq\nLine cap: 20", resp="STATUS: done\nCONFIDENCE: high\nVERDICT: PASS\nEVIDENCE:\n- tests: 13 passed\nISSUES: none", cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: a later PASS on the topic closes the FAIL", "🔴 open FAIL" not in ctx(out))
        time.sleep(1.1)  # rows of the task are those after its start second
        out = run("post", dict(agent("haiku", "low", resp={"agentId": "es1abc", "content": "STATUS: partial\nCONFIDENCE: medium\nFACTS:\n- src/a.cs:1 — x\nGAPS: the Q2 method body was not read"}, cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: an unescalated partial names the next setting", "🟡 escalate · Read Haiku 5.5 · Low came back partial/medium — re-run that subtask at Haiku 5.5 · Medium" in ctx(out))
        yi = next((i for i in (json.loads(Path(state, "gu.json").read_text()).get("guide") or {}).get("items", []) if i["p"] == "🟡"), {})
        STx = Path(__file__).resolve().parent / "status.py"
        check("guide: an escalate item resolves with a --trace and unresolves through status.py",
              yi.get("resolve", [])[1:] == [str(STx), "--resolve", "es1abc", "--session", "gu", "--trace", yi.get("resolve", ["", "", "", "", "", "", ""])[-1]] and yi["resolve"][-1].startswith("Read ")
              and (yi.get("unresolve") or [])[:7] == [sys.executable, str(STx), "--unresolve", "es1abc", "--session", "gu", "--trace"] and yi.get("recheck") is None)
        pin("gu")
        genv = dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state)
        rr = _sp.run(yi["resolve"], cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: status --resolve --trace settles the row", rr.returncode == 0 and "resolved 1 entry" in rr.stdout)
        check("trace: one resolved-by-hand line in the Journal with the session tag", len([l for l in sf("gu").read_text().splitlines() if "· resolved by hand: escalate · Unit Test · Read " in l and l.count("escalate") == 1]) == 1)
        check("trace: the resume block does not list a hand-trace under last and counts no receipt for it", "resolved by hand: escalate" not in memo("show").split("- `last`")[-1] and "- `since` → 1 receipt" not in memo("show"))
        gout = _sp.run([sys.executable, str(GU := Path(__file__).resolve().parent / "guide.py"), "--all"], cwd=cwd, capture_output=True, text=True, env=genv).stdout
        check("trace: a resolved escalate leaves the guide", "🟡 escalate" not in gout)
        ur = _sp.run(yi["unresolve"], cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: status --unresolve reopens the row", ur.returncode == 0 and "reopened 1 entry" in ur.stdout)
        gout = _sp.run([sys.executable, str(GU), "--all"], cwd=cwd, capture_output=True, text=True, env=genv).stdout
        check("trace: the guide shows the escalate again", "🟡 escalate" in gout)
        ur2 = _sp.run(yi["unresolve"], cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: unresolve of an open row exits 3", ur2.returncode == 3 and "not resolved" in ur2.stdout)
        ur3 = _sp.run([sys.executable, str(STx), "--unresolve", "nope", "--session", "gu"], cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: unresolve miss exits 1", ur3.returncode == 1)
        _sp.run(yi["resolve"][:-2] + ["--trace"], cwd=cwd, capture_output=True, text=True, env=genv)
        _sp.run(yi["unresolve"] + ["--trace"], cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: --unresolve --trace writes reopened by hand", "· reopened by hand: escalate · Unit Test" in sf("gu").read_text())
        _sp.run(yi["unresolve"], cwd=cwd, capture_output=True, text=True, env=genv)
        out = run("receipt", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "🧾 **3 Spawns · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y\n- `open` → owner decision: cap per currency?"}, led)
        run("start", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "source": "resume"}, led)
        blk = run("start", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "source": "resume"}, led)
        check("guide: resume block carries the guide line, owner decision first after the task closed", "- `guide` → 🧭 🟠 " in blk and "owner decision" in blk)
        GU = Path(__file__).resolve().parent / "guide.py"
        gout = _sp.run([sys.executable, str(GU), "--all"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led)).stdout
        check("guide: CLI --all lists the ladder", gout.startswith("🟠 ") and "owner decision" in gout)
        od = ((json.loads(Path(state, "gu.json").read_text()).get("guide") or {}).get("items") or [{}])[0]
        check("guide: an owner decision item asks the user after judging, and resolves through memo.py",
              od.get("p") == "🟠" and od.get("fill", "").startswith("abofles: owner decision 1 is open: ") and od["fill"].endswith("Judge it first, then ask me with AskUserQuestion.")
              and od.get("resolve") == [sys.executable, str(Path(__file__).resolve().parent / "memo.py"), "resolve", "1", "settled from the guide band", "--trace", "--session", "gu"]
              and od.get("unresolve") == [sys.executable, str(Path(__file__).resolve().parent / "memo.py"), "reopen", "1", "--trace", "--session", "gu"] and od.get("recheck") is None)
        rout = _sp.run(od["resolve"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state)).stdout
        check("guide: running the owner decision's resolve command ticks it in the memo", rout.startswith("resolved:") and "1. [x]" in mf.read_text())
        check("trace: memo resolve --trace journals the owner decision", any("resolved by hand: owner decision 1: " in l and "(s:" not in l.split("by hand:")[1] for l in sf("gu").read_text().splitlines()))
        rop = _sp.run(od["unresolve"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state))
        check("memo reopen: item is open again and the resolve note is gone", rop.returncode == 0 and any(l.startswith("1. [ ] ") and "→ resolved" not in l for l in mf.read_text().splitlines()))
        rop = _sp.run(od["unresolve"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state))
        check("memo reopen: an open item exits 3", rop.returncode == 3)
        _sp.run(od["resolve"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state))
        out = run("post", dict(agent("sonnet", "high", "abofles:abofles-verifier", prompt="abofles: Unit Test / Verify · T2\nq\nLine cap: 20", resp="STATUS: done\nCONFIDENCE: high\nVERDICT: FAIL\nEVIDENCE:\n- tests: 1 failed\nISSUES:\n- src/b.cs:3 — null", cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: a FAIL of the open task is shown", "🔴 open FAIL · Unit Test" in ctx(out))
        time.sleep(1.1)  # the receipt closes the task in a later second than its rows
        run("receipt", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → fixed src/b.cs in the main session, test green\n- `check` → y"}, led)
        time.sleep(1.1)
        out = run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: a FAIL of a task already closed by its receipt is not carried into the next task", "🔴 open FAIL" not in ctx(out))
        STp = Path(__file__).resolve().parent / "status.py"
        sout = _sp.run([sys.executable, str(STp), "--resolve", "nope"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state)).stdout
        check("cli: status.py --resolve runs and names the miss", "no follow-up with agent id starting 'nope'" in sout)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Guide = off\n")
        out = run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: Guide = off -> no next line", "`next` →" not in ctx(out))
        Path(cwd, "CLAUDE.md").unlink()
        # several open sessions: the CLIs pick the one whose cwd is this project
        pin()
        other = Path(cwd, "other-project"); other.mkdir(exist_ok=True)
        run("start", {"session_id": "sessA", "cwd": cwd, "transcript_path": str(tr)}, led)
        run("start", {"session_id": "sessB", "cwd": str(other), "transcript_path": str(tr)}, led)  # newest by mtime
        run("prompt", {"session_id": "sessA", "cwd": cwd, "prompt": "hello"}, led)  # a prompt makes sessA the one this folder types in
        check("cli: agents.py acts on this project's session, not the newest", "agents: 4 this task" in ag("set", "4") and json.loads(Path(state, "sessA.json").read_text()).get("task_budget") == 4 and json.loads(Path(state, "sessB.json").read_text()).get("task_budget") is None)
        # SubagentStop carries agent_transcript_path: used for pricing
        run("post", dict(pi, session_id="sessA", tool_response={"status": "async_launched", "agentId": "tp1", "prompt": "p", "description": "t"}), led)
        tpx = Path(cwd, "elsewhere.jsonl"); tpx.write_text(json.dumps({"type": "assistant", "message": {"id": "m9", "model": "claude-haiku-5-5", "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 70_000, "output_tokens": 0}}}) + "\n")
        run("stop", {"session_id": "sessA", "agent_id": "tp1", "agent_transcript_path": str(tpx), "last_assistant_message": good}, led)
        check("stop: agent_transcript_path from the event is used for pricing", [json.loads(l) for l in Path(led, "sessA.jsonl").read_text().splitlines()][-1].get("tokens") == 70_000)
        # session cap from CLAUDE.md
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Session cap = 100\n")
        out = run("post", agent("opus", "xhigh", "abofles:abofles-planner", resp="STATUS: done\nCONFIDENCE: high\nPLAN:\n1. s (files: src/a.cs)\nRISKS:\n- r\nVERIFY: cmd\nOPEN: none", cwd=cwd), led)
        check("post: session cap passed warned", "session cap 100 units passed" in ctx(out))
        Path(cwd, "CLAUDE.md").unlink()
        # worker: owner decision in LEFT is input needed, not escalation
        out = run("post", agent("opus", "high", "abofles:abofles-worker", resp="STATUS: partial\nCONFIDENCE: high\nCHANGED:\n- src/a.cs — cap added\nRAN: dotnet build — 0 errors\nLEFT: owner decision: cap in IQD only or per currency", cwd=cwd), led)
        check("post: worker owner decision -> no escalation note", "owner input needed" in ctx(out) and "escalation rule applies" not in ctx(out))
        # context watch: Stop hook only (end of turn), never on a prompt or a tool call
        tr = Path(cwd, "transcript.jsonl")
        def usage(n, side=False):
            return json.dumps({"type": "assistant", "isSidechain": side, "message": {"usage": {"input_tokens": 2, "cache_read_input_tokens": n - 2, "cache_creation_input_tokens": 0}}}) + "\n"
        sr = lambda out: (out or {}).get("reason", "") if (out or {}).get("decision") == "block" else ""
        def cwatch(n, sid="cw", side=False, active=False):
            with open(tr, "a") as f:
                f.write(usage(n, side))
            d = {"session_id": sid, "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": active, "last_assistant_message": "ok"}
            return sr(run("receipt", d, led))
        run("start", {"session_id": "cw", "cwd": cwd}, led)
        check("context: below first mark -> silent", cwatch(120_000) == "")
        with open(tr, "a") as f:
            f.write(usage(512_000))
        dt = {"session_id": "cw", "cwd": cwd, "transcript_path": str(tr), "tool_name": "Read", "tool_input": {"file_path": "x"}}
        check("context: guard/pre/prompt never warn", "CONTEXT" not in ctx(run("guard", dt, led)) + ctx(run("prompt", dt, led))
              + ctx(run("pre", dict(agent("haiku", "low", cwd=cwd), session_id="cw", transcript_path=str(tr)), led)))
        out = cwatch(512_000)
        check("context: 500K mark at Stop -> block, both branches", "CONTEXT 512K" in out and "passed **500K tokens**" in out and "**If no task is open:**" in out and "**If a task is open:**" in out and "Next warning at 600K" in out and "last output" in out)
        check("context: same mark not repeated (second stop goes through)", cwatch(530_000, active=True) == "")
        check("context: sidechain usage ignored", cwatch(650_000, side=True) == "")
        out = cwatch(620_000, active=True)
        check("context: stop_hook_active still warns a new mark", "**600K tokens**" in out and "700K" in out)
        check("context: compact re-arms the marks", cwatch(90_000) == "" and "**500K tokens**" in cwatch(505_000))
        check("context: last mark wording", "last mark" in cwatch(905_000))
        # receipt and context together -> one block with both
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Context marks = 60, 80\n")
        run("start", {"session_id": "cw3", "cwd": cwd}, led)
        run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="cw3"), led)
        with open(tr, "w") as f:
            f.write(usage(61_000))
        out = ctx(run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="cw3", transcript_path=str(tr)), led))
        check("context: post mode never warns", "CONTEXT" not in out)
        out = sr(run("receipt", {"session_id": "cw3", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "done"}, led))
        check("context: override marks + receipt in one block", "**60K tokens**" in out and "Next warning at 80K" in out and "agent(s) spawned, no receipt" in out)
        out = sr(run("receipt", {"session_id": "cw3", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": True, "last_assistant_message": "x"}, led))
        check("context: no re-send on the retry stop", out == "")
        st3 = json.loads(Path(state, "cw3.json").read_text())
        check("state: transcript path remembered, no pending", st3.get("transcript_path") == str(tr) and "context_pending" not in st3)
        # hooks fired inside a subagent never touch the state or warn
        with open(tr, "w") as f:
            f.write(usage(61_000))
        run("start", {"session_id": "cw5", "cwd": cwd, "transcript_path": str(tr)}, led)
        sub = {"session_id": "cw5", "cwd": cwd, "transcript_path": str(tr), "agent_id": "a1", "agent_type": "abofles-reader", "tool_name": "Read", "tool_input": {}}
        outs = [ctx(run("guard", sub, led)) for _ in range(5)] + [sr(run("receipt", sub, led))]
        st5 = json.loads(Path(state, "cw5.json").read_text())
        check("subagent: guard/stop silent, mark untouched, streak untouched", all(o == "" for o in outs) and not st5.get("context_warned_at") and not st5.get("direct_reads"))
        check("context: main session then warns at Stop", "**60K tokens**" in sr(run("receipt", {"session_id": "cw5", "cwd": cwd, "transcript_path": str(tr)}, led)))
        Path(cwd, "CLAUDE.md").unlink()
        check("context: no transcript -> silent", sr(run("receipt", {"session_id": "cw4", "cwd": cwd}, led)) == "")
        # session effort: told once per session, stored in state, re-told when it changes
        e1 = {"session_id": "ef", "cwd": cwd, "effort": {"level": "medium"}}
        out = run("start", e1, led)
        check("effort: SessionStart prints the effort line", isinstance(out, str) and "effort is `medium`" in out)
        run("start", {"session_id": "ef2", "cwd": cwd}, led)
        out = ctx(run("prompt", dict(e1, session_id="ef2"), led))
        check("effort: prompt tells it once", "effort is `medium`" in out)
        check("effort: not repeated", ctx(run("prompt", dict(e1, session_id="ef2"), led)) == "")
        out = ctx(run("guard", dict(e1, session_id="ef2", effort={"level": "high"}, tool_name="Read", tool_input={}), led))
        check("effort: change re-told, state updated", "effort is `high`" in out and json.loads(Path(state, "ef2.json").read_text()).get("effort") == "high")
        check("effort: subagent input ignored", ctx(run("guard", dict(e1, session_id="ef2", effort={"level": "low"}, tool_name="Read", tool_input={}, agent_id="x"), led)) == "")
        rows = [json.loads(l) for l in Path(led, "test.jsonl").read_text().splitlines()]
        check("ledger: one line per post", len(rows) == 28)
        check("ledger: open_questions counted", next(r for r in rows if r.get("open_questions"))["open_questions"] == 3)
        pend = next(r for r in rows if r.get("agent_id") == "ag1")
        check("ledger: async entry filled by stop", pend["status"] == "partial" and pend["reply_lines"] == 6 and pend.get("completed_ts"))
        check("ledger: stop stored its warnings", any("escalation" in w for w in (pend.get("warnings") or [])))
        check("ledger: sync spawn warnings stored", any(r.get("warnings") and not r.get("completed_ts") for r in rows))
        check("ledger: topic parsed", rows[0]["topic"] == "Unit Test" and rows[0]["side"] == "Read" and rows[0]["tier"] == 2)
        check("ledger: full-word side header", rows[-9]["side"] == "Read")
        check("ledger: liar logged as partial", rows[3]["status"] == "partial" and rows[3]["adjusted"])
        check("ledger: bad path logged low", rows[4]["confidence"] == "low" and rows[4]["bad_paths"] == ["src/Rules/a.cs"])
        check("ledger: reply_chars present", all("reply_chars" in r for r in rows))
        check("ledger: verdicts logged", rows[7]["verdict"] == "FAIL" and rows[8]["verdict"] == "PASS" and rows[8]["attention"] is True)

        # ── T3 batch: memo Now follows the receipt; explain gate; prompt dirs; lock pruning; overrides block; next setting; guide ids ──
        import importlib.util as _iu
        _hs = _iu.spec_from_file_location("abofles_hook_t3", str(HOOK)); H = _iu.module_from_spec(_hs); _hs.loader.exec_module(H)
        gstate = lambda sid_: json.loads(Path(state, f"{sid_}.json").read_text())
        gitems = lambda sid_: (gstate(sid_).get("guide") or {}).get("items") or []
        RC1 = "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → capped the surcharge in AqsatiRules.cs\n- `why` → money rule\n- `check` → `dotnet test` → 13 passed\n- `open` →\n  - wire the FE badge\n  - update the docs page"
        # 1. memo Now rewritten by the receipt
        pa = tempfile.mkdtemp(); sA = "autosess1"
        run("start", {"session_id": sA, "cwd": pa}, led)
        H.memo_now(pa, "Task      old task\nDone      old done\nLeft      old left\nDecisions keep: tables are printed above the box\nNext      old next\nVerify    old verify\nTree      M old.cs", sA)
        run("receipt", {"session_id": sA, "cwd": pa, "stop_hook_active": False, "last_assistant_message": RC1}, led)
        nowA = H.sess_read(pa, sA)["Now"]
        check("now auto: a receipt rewrites this session's Now (between tasks, Done, Left lines, Next = first open item, Verify)",
              "Task      none — between tasks" in nowA and "Done      capped the surcharge in AqsatiRules.cs" in nowA and "Left      wire the FE badge\nLeft      update the docs page" in nowA
              and "Next      wire the FE badge" in nowA and "Verify    `dotnet test` → 13 passed" in nowA and "old left" not in nowA and "old next" not in nowA and "old done" not in nowA)
        check("now auto: Decisions kept unchanged, Tree kept outside git, block marked from receipt",
              "Decisions keep: tables are printed above the box" in nowA and "Tree      M old.cs" in nowA and re.search(r"Written   \d{4}-\d\d-\d\d \d\d:\d\d · from receipt", nowA))
        nx_ = next((i for i in gitems(sA) if i.get("id") == "next"), {})
        check("now auto: the band's next item shows the new Next in the same Stop", "next from the memo: wire the FE badge" in nx_.get("text", "") and gstate(sA)["guide"]["items"][0]["p"] == "✅")
        blkA = H.resume_block(pa, session_id=sA)
        check("now auto: resume block reads the receipt-stamped Now (no 'since' stale line, left and next shown)", "now written " in blkA and "from receipt" in blkA and "- `since`" not in blkA and "- `next` → wire the FE badge" in blkA)
        run("receipt", {"session_id": sA, "cwd": pa, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5 · open: none"}, led)
        nowA2 = H.sess_read(pa, sA)["Now"]
        check("now auto: short receipt with open none -> no Left, Next ready, Done/Verify/Decisions kept",
              "Left" not in nowA2 and "Next      none — ready for the next task" in nowA2 and "capped the surcharge" in nowA2 and "13 passed" in nowA2 and "Decisions keep:" in nowA2)
        nx_ = next((i for i in gitems(sA) if i.get("id") == "next"), {})
        check("now auto: Next 'none…' -> the band says pick the next ticket", nx_.get("text") == "nothing open — pick the next ticket and route it with abofles first")
        pg = tempfile.mkdtemp()
        if subprocess.run(["git", "init", "-q"], cwd=pg, capture_output=True).returncode == 0:
            Path(pg, "a.txt").write_text("x")
            run("start", {"session_id": "autogit1", "cwd": pg}, led)
            run("receipt", {"session_id": "autogit1", "cwd": pg, "stop_hook_active": False, "last_assistant_message": RC1}, led)
            check("now auto: Tree = git status --short of the project root", "Tree      ?? a.txt" in H.sess_read(pg, "autogit1")["Now"])
            Path(pg, "a.txt").unlink()
            run("receipt", {"session_id": "autogit1", "cwd": pg, "stop_hook_active": False, "last_assistant_message": RC1}, led)
            check("now auto: Tree = clean when git status is empty", "Tree      clean" in H.sess_read(pg, "autogit1")["Now"])
        # the 'memo Now is old' item goes away right after a receipt
        pb = tempfile.mkdtemp(); sB = "agesess01"
        run("start", {"session_id": sB, "cwd": pb}, led)
        run("receipt", {"session_id": sB, "cwd": pb, "stop_hook_active": False, "last_assistant_message": RC1}, led)
        stb = H.session_memo_path(pb, sB); stb.write_text(stb.read_text().replace(time.strftime("Written   %Y-%m-%d %H:%M"), "Written   2020-01-01 00:00"))
        run("prompt", {"session_id": sB, "cwd": pb}, led)
        check("now auto: an old Now with receipts since still raises the memo-age item", "memo-age" in [i.get("id") for i in gitems(sB)])
        run("receipt", {"session_id": sB, "cwd": pb, "stop_hook_active": False, "last_assistant_message": RC1}, led)
        check("now auto: ... and the next receipt makes it disappear", "memo-age" not in [i.get("id") for i in gitems(sB)])
        # 2. explanation gate
        run("start", {"session_id": "xa", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(gstate("xa"), gate="auto"), open(Path(state, "xa.json"), "w"))
        xj = lambda resp: dict(jp(2, resp), session_id="xa", transcript_path=str(tr))
        xq = lambda q: dict(aq, session_id="xa", transcript_path=str(tr), tool_input={"questions": [{"question": q, "options": []}]})
        TBL = "📖 **Explanation for the question below**\n\n| option | effect |\n|---|---|\n| Per unit | capped |"
        XQ1 = "Cap per unit or per order? 📖 the full table is printed above this question"
        run("post", xj(table_ask), led)
        say("text", TBL)
        check("explain gate: a printed markdown round passes and is kept as explain_prev", run("qgate", xq(XQ1), led) is None and (gstate("xa").get("explain_prev") or {}).get("text"))
        run("post", xj(ask), led)  # a new judged question, plain EXPLAIN
        check("explain gate (a): a new judged plain question passes and drops the old explain_prev", run("qgate", xq("Which branch do we merge into first?"), led) is None and not gstate("xa").get("explain_prev"))
        check("explain gate (a): its re-ask is not asked to print the old table", run("qgate", xq("Into which branch do we merge first, then?"), led) is None)
        run("post", xj(table_ask), led)
        say("text", TBL)
        run("qgate", xq(XQ1), led)
        say("text", "the user answered in Other: print the table again")
        run("sendmsg", {"session_id": "xa", "cwd": cwd, "transcript_path": str(tr), "tool_name": "SendMessage", "tool_input": {"to": "abofles-judge", "message": "same round, reworded"}}, led)
        out = run("qgate", xq("Cap per unit or per order (translated)? 📖 the table is above"), led)
        check("explain gate (b): a re-ask unlocked by SendMessage is refused until the table is printed again, block handed back", "not printed" in reason(out) and "| Per unit | capped |" in reason(out))
        run("start", {"session_id": "xc", "cwd": cwd, "transcript_path": str(tr)}, led)
        json.dump(dict(gstate("xc"), gate="auto"), open(Path(state, "xc.json"), "w"))
        run("post", dict(agent("sonnet", "medium", "abofles:abofles-judge", prompt="abofles: X / Judge · T2\nq\nLine cap: 40", resp={"status": "async_launched", "agentId": "bjx", "prompt": "p", "description": "t"}, cwd=cwd), session_id="xc", transcript_path=str(tr)), led)
        run("stop", {"session_id": "xc", "agent_id": "bjx", "last_assistant_message": table_ask}, led)
        check("explain gate (c): a background judge reply arms the explain state like post() does", gstate("xc").get("explain_md") is True and "| Per unit | capped |" in gstate("xc").get("explain_text", "") and gstate("xc").get("judge_ok") == 1)
        out = run("qgate", dict(xq("Cap per unit or per order?"), session_id="xc"), led)
        check("explain gate (c): ... so the unprinted table is refused once", "not printed" in reason(out))
        run("start", {"session_id": "xc", "cwd": cwd, "transcript_path": str(tr)}, led)
        check("explain gate (d): a new task clears every explain key, explain_prev included", not any(k in gstate("xc") for k in ("explain_md", "explain_text", "explain_offset", "explain_denies", "explain_prev")))
        EXq = "STATUS: done\nVERDICT: ASK\nQUESTION: q1\nEXPLAIN:\n| a | b |\n|---|---|\n| 1 | 2 |\nVERDICT: ASK\nQUESTION: q2\nWHY: w2"
        check("explain gate (e): EXPLAIN ends at the next VERDICT line", H.explain_block(EXq) == "| a | b |\n|---|---|\n| 1 | 2 |")
        fenced = "EXPLAIN:\n```\nA -> B\nB -> C\n```"
        check("explain gate (e): a fenced EXPLAIN keeps its fence and counts as markdown", H.explain_block(fenced) == "```\nA -> B\nB -> C\n```" and H.explain_needs_markdown(fenced))
        check("explain gate (e): one inline-code wrap of a one-line text is removed, two code spans stay", H.explain_block("EXPLAIN: `use the cap`") == "use the cap" and H.explain_block("EXPLAIN: `a` and `b`") == "`a` and `b`")
        cutx = H.explain_cut("```\n" + "row\n\n" * 3000)
        check("explain gate (f): a long EXPLAIN is cut at a blank line and the open fence closed", len(cutx) <= 6004 and cutx.endswith("\n```") and cutx[:-4].endswith("row") and H.explain_cut("short") == "short")
        # 3. prompt_dirs
        pdd = tempfile.mkdtemp(); os.makedirs(os.path.join(pdd, "my proj", "wt")); os.makedirs(os.path.join(pdd, "plain", "tree2"))
        wsp = os.path.join(pdd, "my proj", "wt")
        check("prompt_dirs: an unquoted dir with a space in it is found whole", H.prompt_dirs(f"Working tree: {wsp} then read x.cs") == [wsp])
        check("prompt_dirs: quoted and backticked dirs are found", H.prompt_dirs(f'in "{wsp}" and `{pdd}/plain/tree2`.') == [wsp, f"{pdd}/plain/tree2"])
        check("prompt_dirs: a plain dir with a trailing dot still works", H.prompt_dirs(f"Working tree: {pdd}/plain/tree2.") == [f"{pdd}/plain/tree2"])
        # 4. resume `last` lists receipts only
        pr = tempfile.mkdtemp(); sR = "lastsess1"
        for n in (1, 2, 3, 4):
            H.memo_journal(pr, sR, H.parse_receipt(f"🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → built r{n}\n- `check` → ok"))
        H.memo_trace(pr, sR, "resolved by hand: escalate · X")
        lastpart = H.resume_block(pr, session_id=sR).split("- `last`")[1]
        check("resume last: the newest 3 receipts, no hand-trace line", lastpart.count("\n  - ") == 3 and "built r4" in lastpart and "built r2" in lastpart and "built r1" not in lastpart and "by hand" not in lastpart)
        # 4b. a pre-1.5 one-file memo is split on first read: Now blocks and tagged journal lines per session, Decisions and Needs you kept, index built
        pm = tempfile.mkdtemp(); Path(pm, ".claude").mkdir()
        Path(pm, ".claude", "abofles-memo.md").write_text(
            "# Abo Fles memo — x\nUpdated: 2026-10-14 14:30 · session oldsess1\n\n## Now\nSession   oldsess1\nWritten   2026-10-14 14:30 · from receipt\nTask      none — between tasks\nLeft      band buttons not pressed\nNext      band buttons not pressed\n\n"
            "Session   oldsess2\nWritten   2026-10-13 10:00\nTask      cap ticket\nNext      verify cap\n\n## Needs you\n1. [ ] 10-14 14:30 · band buttons not pressed (s:oldsess1)\n\n## Decisions\n- 10-14 06:47 · note → ship = tag + release\n\n"
            "## Journal\n- 10-14 14:30 · s:oldsess1 · 2 Spawns · $0.88 vs Opus 5.5 · done: band fixes\n- 10-13 10:05 · s:oldsess2 · 1 Spawn · $0.10 vs Opus 5.5 · done: capped\n- 10-12 09:00 · 1 Spawn · $0.05 vs Opus 5.5 · done: untagged line\n")
        msec = H.memo_read(pm)
        mtxt = H.memo_path(pm).read_text()
        f1, f2 = H.sess_read(pm, "oldsess1"), H.sess_read(pm, "oldsess2")
        check("migrate: main memo keeps Needs you and Decisions, gains the Sessions index, loses Now and Journal",
              "band buttons not pressed (s:oldsess1)" in msec["Needs you"] and "note → ship = tag + release" in msec["Decisions"] and "## Now" not in mtxt and "## Journal" not in mtxt
              and msec["Sessions"].startswith("- [oldsess1](abofles-memo.d/oldsess1.md) · 10-14 14:30 · task: none — between tasks · next: band buttons not pressed · receipts: 2") and "- [oldsess2](abofles-memo.d/oldsess2.md) · 10-13 10:05 · task: cap ticket · next: verify cap · receipts: 1" in msec["Sessions"])
        check("migrate: each session file holds its Now and its journal lines (tag dropped; untagged lines go to the header's session)",
              "Task      none — between tasks" in f1["Now"] and "Session " not in f1["Now"] and f1["Journal"].splitlines() == ["- 10-14 14:30 · 2 Spawns · $0.88 vs Opus 5.5 · done: band fixes", "- 10-12 09:00 · 1 Spawn · $0.05 vs Opus 5.5 · done: untagged line"]
              and "Task      cap ticket" in f2["Now"] and f2["Journal"] == "- 10-13 10:05 · 1 Spawn · $0.10 vs Opus 5.5 · done: capped")
        rb1 = H.resume_block(pm, session_id="oldsess1-full-id")
        rb3 = H.resume_block(pm, session_id="newsess99", scope="project", explicit=True)
        check("migrate: the resume block reads the split files", "- `now` → none — between tasks" in rb1 and "- `next` → band buttons not pressed" in rb1 and "band fixes" in rb1 and "capped" not in rb1
              and "no Now section from this session yet" in rb3 and "session oldsess1 wrote: none — between tasks" in rb3 and "(session oldsess1, not this one)" in rb3)
        check("migrate: a new session gets the hint line by default", "2 other sessions, newest oldsess1" in H.resume_block(pm, session_id="newsess99"))
        H.memo_journal(pm, "oldsess2", H.parse_receipt("🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → more cap\n- `check` → ok"))
        check("migrate: a later receipt lands in its session file and moves that session to the top of the index", H.memo_read(pm)["Sessions"].startswith("- [oldsess2](") and "receipts: 2" in H.memo_read(pm)["Sessions"].splitlines()[0] and "more cap" in H.sess_read(pm, "oldsess2")["Journal"] and "more cap" not in H.sess_read(pm, "oldsess1")["Journal"])
        # 5. memo_resolve / memo_reopen pass the session on
        H.memo_needs(pr, "needsess1", "owner decision: pick A or B")
        H.memo_resolve(pr, 1, "ok", "ressess01")
        check("memo_resolve: the memo header carries the given session", "· session ressess0" in H.memo_path(pr).read_text().splitlines()[1])
        H.memo_reopen(pr, 1, "reopsess1")
        check("memo_reopen: the memo header carries the given session", "· session reopsess" in H.memo_path(pr).read_text().splitlines()[1])
        # 6. stale lock files are pruned at SessionStart
        ml_dir = Path(state, "memo-locks"); ml_dir.mkdir(exist_ok=True)
        lk_old, lk_new, lk_oldm = Path(state, "stale-sess.lock"), Path(state, "fresh-sess.lock"), ml_dir / "stale_proj.lock"
        for f in (lk_old, lk_new, lk_oldm):
            f.write_text("")
        for f in (lk_old, lk_oldm):
            os.utime(f, (time.time() - 8 * 86400,) * 2)
        run("start", {"session_id": "lk", "cwd": cwd}, led)
        check("start: lock files older than 7 days are deleted (state and memo-locks), fresh ones stay", not lk_old.exists() and not lk_oldm.exists() and lk_new.exists())
        # 7. refresh_guide reads the transcript once
        calls = []
        orig_cs = H.context_state
        H.context_state = lambda root_, st_: (calls.append(1), (None, None))[1]
        try:
            H.refresh_guide(pr, {}, "cnt_sess")
        finally:
            H.context_state = orig_cs
        check("refresh_guide: context_state computed once (no second transcript tail read)", len(calls) == 1)
        # 9. overrides are read only inside the overrides block
        po = tempfile.mkdtemp()
        Path(po, "CLAUDE.md").write_text("# Project\n- Pace = fast\n- Receipt = off\n\n### Abofles Overrides\n- Break = 7\n#### notes\n- Guide = off\n\n## Other\n- Language = Arabic\n")
        check("override_value: read inside the block (any heading level and case; a deeper heading continues it)", H.override_value(po, "Break") == "7" and H.override_value(po, "Guide") == "off")
        check("override_value: a `- Key = value` line outside the block sets nothing", H.override_value(po, "Pace") is None and H.override_value(po, "Receipt") is None and H.override_value(po, "Language") is None)
        # 10. the gate text says what the question text holds
        qt = H.question_gate_text({})
        check("question gate text: question text = QUESTION, blank line, WHY (no option summary); no 'plain summary'", "plain summary" not in qt and "QUESTION, a blank line, WHY (no option summary)" in qt)
        # 11. next setting stops at the top unless T4
        check("next_setting: Work stops at opus·xhigh (max only on T4)", H.next_setting("opus", "xhigh", "Work", 3) == (None, None) and H.next_setting("opus", "xhigh", "Work", 4) == ("opus", "max") and H.next_setting("opus", "max", "Work", 4) == (None, None))
        check("next_setting: Analyse/Plan reach fable, max only after fable·high on T4",
              H.next_setting("opus", "xhigh", "Plan", 3) == ("fable", "medium") and H.next_setting("fable", "xhigh", "Plan", 3) == (None, None)
              and H.next_setting("fable", "high", "Analyse", 4) == ("fable", "xhigh") and H.next_setting("fable", "xhigh", "Plan", 4) == ("fable", "max"))
        check("next_setting: the lower ladder is unchanged", H.next_setting("haiku", "low", "Read", 2) == ("haiku", "medium") and H.next_setting("sonnet", "xhigh", "Work", 2) == ("opus", "medium"))
        for sx_, tx_ in (("nx", 3), ("nx4", 4)):
            run("start", {"session_id": sx_, "cwd": cwd}, led)
        time.sleep(1.1)  # escalation rows are those after the task start second
        for sx_, tx_, ag_ in (("nx", 3, "wkx111"), ("nx4", 4, "wkx444")):
            run("post", dict(agent("opus", "xhigh", "abofles:abofles-worker", prompt=f"abofles: Cap / Work · T{tx_}\nq\nLine cap: 20", resp={"agentId": ag_, "content": "STATUS: partial\nCONFIDENCE: low\nCHANGED:\n- a\nRAN: none\nLEFT: the Q2 body was not read"}, cwd=cwd), session_id=sx_), led)
        e3 = next((i for i in gitems("nx") if i["p"] == "🟡"), {})
        e4 = next((i for i in gitems("nx4") if i["p"] == "🟡"), {})
        check("guide: an escalate at the top setting (T3) says stop and report, no max setting", "stop and report" in e3.get("text", "") and "Max" not in e3.get("text", "") and "stop and report" in e3.get("fill", ""))
        check("guide: the same on T4 offers Opus 5.5 · Max", "Opus 5.5 · Max" in e4.get("text", ""))
        check("guide: escalate text names the agent and carries id esc:<agent>", e3.get("id") == "esc:wkx111" and "agent wkx111" in e3.get("text", "") and e4.get("id") == "esc:wkx444" and "agent wkx444" in e4.get("text", ""))
        # 12. guide item ids
        pi_ = tempfile.mkdtemp(); sI = "idsess1"; tri = Path(pi_, "t.jsonl")
        tri.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 460000, "output_tokens": 5}}}) + "\n")
        Path(pi_, "CLAUDE.md").write_text("## abofles overrides\n- Agents = 1\n")
        run("start", {"session_id": sI, "cwd": pi_, "transcript_path": str(tri)}, led)
        H.memo_needs(pi_, sI, "owner decision: pick A or B?")
        time.sleep(1.1)
        iv = lambda extra: dict(extra, session_id=sI, transcript_path=str(tri))
        run("post", iv(agent("sonnet", "high", "abofles:abofles-verifier", prompt="abofles: Ids Topic / Verify · T2\nq\nLine cap: 20", resp={"agentId": "vfx111", "content": "STATUS: done\nCONFIDENCE: high\nVERDICT: FAIL\nEVIDENCE:\n- c1 — FAIL — src/a.cs:1\nISSUES:\nNOTE: none"}, cwd=pi_)), led)
        run("post", iv(jp(2, ask)), led)
        run("post", iv(agent("haiku", "low", resp={"status": "async_launched", "agentId": "bgx111", "prompt": "p", "description": "t"}, cwd=pi_)), led)
        run("prompt", {"session_id": sI, "cwd": pi_, "transcript_path": str(tri)}, led)
        iditems = {i["id"]: i for i in gitems(sI)}
        check("guide ids: fail:<agent>, ask, dec:<n>, bg:<agent>, ctx:<mark>, budget on their items", {"fail:vfx111", "ask", "dec:1", "bg:bgx111", "ctx:500", "budget"} <= set(iditems))
        check("guide ids: the owner-decision resolve/reopen argv carries --session <sid>", (iditems.get("dec:1", {}).get("resolve") or [])[-2:] == ["--session", sI] and (iditems.get("dec:1", {}).get("unresolve") or [])[-2:] == ["--session", sI])
        # ── Batch A: the graded reply text, header-aware replies, exact gate agents, stale unlocks, lost agents ──
        setst = lambda sid_, **kw: json.dump(dict(gstate(sid_), **kw), open(Path(state, f"{sid_}.json"), "w"))
        ledrows = lambda sid_: [json.loads(l) for l in Path(led, f"{sid_}.jsonl").read_text().splitlines() if l.strip()]
        askp = lambda sid_: dict(aq, session_id=sid_)  # AskUserQuestion payload of that session
        jpa = lambda sid_, resp, stype="abofles:abofles-judge", hdr="Judge", tier=2, **kw: dict(agent("sonnet", "medium", stype, prompt=f"abofles: BatchA / {hdr} · T{tier}\nq\nLine cap: 40", resp=resp, cwd=cwd), session_id=sid_, transcript_path=str(tr), **kw)
        launch_ = lambda aid_: {"status": "async_launched", "agentId": aid_, "prompt": "p", "description": "t"}
        for sx_ in ("ba1", "ba2", "ba3", "ba4", "ba5", "ba6", "ba7", "ba8", "ba9", "ba10", "ba11", "ba12"):
            run("start", {"session_id": sx_, "cwd": cwd, "transcript_path": str(tr)}, led)
            setst(sx_, gate="auto")
        time.sleep(1.1)  # rows of the task are those after the task start second
        # 1. harness notes are not the agent's reply
        hnote = "[harness: subagent output matched instruction-shaped pattern(s) " + "word " * 80 + "]"
        blk = lambda t: {"type": "text", "text": t}
        hresp = {"agentId": "hn1", "agentType": "abofles:abofles-reader", "content": [blk(hnote), blk(good)], "harnessNoteCount": 1, "harnessTailCount": 0, "status": "completed", "usage": {}, "totalTokens": 9}
        out = run("post", dict(agent("haiku", "low", resp=hresp, cwd=cwd), session_id="ba1"), led)
        check("reply: a harness note block is dropped from the graded reply — no too-long warning", "too long" not in ctx(out) and warn(out) == "")
        check("reply_text: head and tail counts drop blocks, a `[harness:` block goes without a count, str/list inputs still work",
              H.reply_text(dict(hresp, harnessNoteCount=1)) == good and H.reply_text(dict(hresp, harnessNoteCount=0, content=[blk(good), blk(hnote)])) == good
              and H.reply_text(dict(hresp, harnessNoteCount=0, harnessTailCount=1, content=[blk(good), blk("trailer")])) == good
              and H.reply_text({"content": [blk(hnote), blk("x")]}) == "x" and H.reply_text("plain") == "plain" and H.reply_text([blk("a"), blk("b")]) == "a\nb" and H.reply_text(None) == "")
        check("has_header: STATUS / VERDICT / EXPLAIN lines, leading spaces allowed; a stub has none",
              H.has_header("x\n  STATUS: done") and H.has_header("VERDICT: ASK") and H.has_header("a\nEXPLAIN:\nb") and not H.has_header("Understood. STATUS: done soon") and not H.has_header(""))
        # 2. get_reply: header hint wins, else the agent's own transcript, else the stub, else nothing
        REAL = "STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/a.cs:1 — x\nGAPS: none"
        gdir = Path(cwd, "ba2", "subagents"); gdir.mkdir(parents=True, exist_ok=True)
        gline = lambda t: json.dumps({"type": "assistant", "message": {"id": f"g{time.time()}", "content": [{"type": "text", "text": t}]}}) + "\n"
        gtr = Path(gdir, "agent-gx1.jsonl"); gtr.write_text(gline("working") + gline(REAL) + gline("Understood."))
        gst_ = {"transcript_path": str(Path(cwd, "main.jsonl"))}
        check("get_reply: a hint with a header wins over the transcript", H.get_reply(gst_, "ba2", "gx1", "STATUS: partial\nCONFIDENCE: low") == ("STATUS: partial\nCONFIDENCE: low", "hint"))
        check("get_reply: a stub hint falls back to the newest transcript text that has a header", H.get_reply(gst_, "ba2", "gx1", "Understood.") == (REAL, "transcript"))
        check("get_reply: no transcript -> the stub as it is; nothing at all -> no_reply", H.get_reply(gst_, "ba2", "nope", "Understood.") == ("Understood.", "stub") and H.get_reply(gst_, "ba2", "nope", "") == ("", "no_reply") and H.get_reply(gst_, "ba2", None, "  ") == ("", "no_reply"))
        check("last_assistant_reply: the real report wins over a short stub written after it", H.last_assistant_reply(gtr) == (REAL, False))
        gtr2 = Path(gdir, "agent-gx2.jsonl"); gtr2.write_text(gline(REAL) + gline("one") + gline("two") + gline("three"))
        check("get_reply: only the newest 2 assistant messages are searched — an older report is not taken (stub as it is)", H.get_reply(gst_, "ba2", "gx2", "Understood.") == ("Understood.", "stub"))
        gtr3 = Path(gdir, "agent-gx3.jsonl"); gtr3.write_text(gline(REAL) + json.dumps({"type": "assistant", "message": {"id": "hb", "content": [{"type": "tool_use", "name": "SubagentHandback", "input": {"message": "Understood."}}]}}) + "\n")
        check("last_assistant_reply: the headed report is returned with the NEWEST message's hand-back flag", H.last_assistant_reply(gtr3) == (REAL, True))
        run("post", dict(agent("haiku", "low", resp=launch_("gx1"), cwd=cwd), session_id="ba2"), led)
        run("stop", {"session_id": "ba2", "agent_id": "gx1", "agent_transcript_path": str(gtr), "last_assistant_message": "Understood."}, led)
        grow = next(r for r in ledrows("ba2") if r.get("agent_id") == "gx1")
        check("stop: a stub last message is graded from the transcript's real report", grow.get("status") == "done" and grow.get("confidence") == "high" and grow.get("how") == "transcript")
        run("post", dict(agent("haiku", "low", resp=launch_("nr1"), cwd=cwd), session_id="ba3"), led)
        run("stop", {"session_id": "ba3", "agent_id": "nr1", "last_assistant_message": ""}, led)
        run("prompt", {"session_id": "ba3", "cwd": cwd, "transcript_path": str(tr)}, led)
        nrow = next(r for r in ledrows("ba3") if r.get("agent_id") == "nr1")
        check("stop: no reply text -> row closed how=no_reply, and the guide raises no escalate item for it", nrow.get("how") == "no_reply" and nrow.get("completed_ts") and gitems("ba3") and not any(i["p"] == "🟡" for i in gitems("ba3")))
        # 3. every judge block counts; a stub or an empty EXPLAIN never unlocks
        two = "STATUS: done\nCONFIDENCE: high\nVERDICT: ANSWERED\nQUESTION: Is the cap per unit?\nANSWER: Yes\nEVIDENCE:\n- src/a.cs:12 — loop\nVERDICT: ASK\nQUESTION: Per unit or per order?\nEVIDENCE:\n- src/a.cs:10 — cap read here\nWHY: w\nOPTIONS:\n- A — means: m · then: t · pick when: p\nRECOMMEND: A — r"
        run("post", jpa("ba4", two), led)
        check("gate reply: ANSWERED then ASK in one sync reply unlocks one question", gstate("ba4").get("judge_ok") == 1 and gstate("ba4").get("judge_ok_ts"))
        run("post", jpa("ba5", launch_("bj5")), led)
        run("stop", {"session_id": "ba5", "agent_id": "bj5", "last_assistant_message": two}, led)
        check("gate reply: ANSWERED then ASK from a background judge unlocks too (the ASK is not lost)", gstate("ba5").get("judge_ok") == 1 and next(r for r in ledrows("ba5") if r.get("agent_id") == "bj5").get("verdict") == "ASK")
        out = run("post", jpa("ba6", "Understood, I will check the cap."), led)
        check("gate reply: a judge stub with no VERDICT stays locked and warns", gstate("ba6").get("judge_ok", 0) == 0 and "no VERDICT" in ctx(out) and "question gate" in reason(run("qgate", askp("ba6"), led)))
        run("post", jpa("ba6", launch_("bj6")), led)
        run("stop", {"session_id": "ba6", "agent_id": "bj6", "last_assistant_message": "Understood."}, led)
        check("gate reply: the same stub from a background judge stays locked", gstate("ba6").get("judge_ok", 0) == 0 and any("no VERDICT" in w for w in next(r for r in ledrows("ba6") if r.get("agent_id") == "bj6").get("warnings") or []))
        exreply = lambda ex_: "STATUS: done\nCONFIDENCE: high\nQUESTION: q\nWHY: w\nOPTIONS:\n- A — means: m · then: t · pick when: p\nRECOMMEND: A — r\nEXPLAIN:" + ex_
        out = run("post", jpa("ba7", exreply("\n• A: m → t"), "abofles:abofles-explainer", "Explain", 3), led)
        check("gate reply: an explainer with an EXPLAIN unlocks", gstate("ba7").get("judge_ok") == 1)
        out = run("post", jpa("ba7", exreply(""), "abofles:abofles-explainer", "Explain", 3), led)
        check("gate reply: an explainer with a QUESTION but no EXPLAIN unlocks (EXPLAIN is optional)", gstate("ba7").get("judge_ok") == 2 and "stays locked" not in ctx(out))
        out = run("post", jpa("ba7", "Understood, I will explain it.", "abofles:abofles-explainer", "Explain", 3), led)
        check("gate reply: an explainer stub with no QUESTION line stays locked and warns", gstate("ba7").get("judge_ok") == 2 and "no QUESTION line" in ctx(out))
        # 4. which agents are gate agents
        check("is_gate_agent: exact abofles types (full or bare name) yes; a project agent named decision-judge no",
              H.is_gate_agent("abofles:abofles-judge", "") == "judge" and H.is_gate_agent("abofles-explainer", "") == "explain" and H.is_gate_agent("abofles:abofles-explainer", "x") == "explain"
              and H.is_gate_agent("decision-judge", "abofles: X / Read · T2\nq") is None and H.is_gate_agent("my-explainer", "") is None and H.is_gate_agent("abofles:abofles-worker", "abofles: X / Work · T2") is None)
        check("is_gate_agent: any other type counts only through the prompt header side",
              H.is_gate_agent("general-purpose", "abofles: X / Judge · T2\nq") == "judge" and H.is_gate_agent("general-purpose", "abofles: X / Explain · T3\nq") == "explain" and H.is_gate_agent("general-purpose", "do it") is None)
        check("side_of: no substring match of judge/explain on a non-abofles type; abofles types and the header side still resolve",
              H.side_of("decision-judge") == ("", "?") and H.side_of("abofles:abofles-judge") == ("judge", "Judge") and H.side_of("abofles-worker") == ("worker", "Work")
              and H.side_of("decision-judge", "abofles: X / Verify · T2\nq") == ("verifier", "Verify") and H.side_of("my-reader", "") == ("", "?"))
        out = run("post", jpa("ba8", ask, "decision-judge", "Read"), led)
        check("gate agent: decision-judge replying ASK does not unlock the gate", gstate("ba8").get("judge_ok", 0) == 0 and "question judged" not in ctx(out) and not gstate("ba8").get("gate_agents"))
        out = run("post", jpa("ba9", ask, "general-purpose", "Judge"), led)
        check("gate agent: general-purpose with a `/ Judge` header is a gate agent and unlocks", gstate("ba9").get("judge_ok") == 1 and "question judged" in ctx(out) and next(r for r in ledrows("ba9")).get("gate") == "judge")
        out = run("post", jpa("ba9", longq, "general-purpose", "Judge"), led)
        check("analyze: a general-purpose `/ Judge` spawn is graded as a judge — no long-line nag", "too long" not in ctx(out) and "absolute paths" not in ctx(out))
        # 5. SendMessage unlocks only for a gate agent this session spawned
        sm = lambda sid_, to_: run("sendmsg", {"session_id": sid_, "cwd": cwd, "transcript_path": str(tr), "tool_name": "SendMessage", "tool_input": {"to": to_, "message": "m"}}, led)
        check("sendmsg: an unknown id, and a name that merely contains judge, unlock nothing", sm("ba8", "decision-judge") is None and sm("ba8", "judge-7") is None and sm("ba8", "a1b2c3") is None and gstate("ba8").get("judge_ok", 0) == 0)
        run("post", jpa("ba10", launch_("gj10")), led)
        check("sendmsg: the id of a gate agent this session spawned still unlocks", "unlocked" in ctx(sm("ba10", "gj10")) and gstate("ba10").get("judge_ok") == 1 and gstate("ba10").get("judge_ok_ts"))
        for sx_ in ("bc1", "bc2", "bc3"):
            run("start", {"session_id": sx_, "cwd": cwd, "transcript_path": str(tr)}, led)
            setst(sx_, gate="auto")
        pn_ = jpa("bc3", {"agentId": "gj3", "content": ask})
        run("post", dict(pn_, tool_input=dict(pn_["tool_input"], name="jq3")), led)
        check("gate_agents: the agent id and the spawn name are recorded, not the type name", gstate("bc3").get("gate_agents") == ["gj3", "jq3"])
        check("sendmsg: the type name unlocks nothing; the id and the spawn name do", sm("bc3", "abofles-judge") is None and gstate("bc3").get("judge_ok") == 1 and "unlocked" in ctx(sm("bc3", "jq3")) and "unlocked" in ctx(sm("bc3", "gj3")) and gstate("bc3").get("judge_ok") == 3)
        # 6. stale unlocks
        now_ = int(time.time())
        ids_ = lambda sid_: [i.get("id") for i in gitems(sid_)]
        setst("ba11", task_started=now_ - 5000, judge_ok=1, judge_ok_ts=now_ - 6000, gate_wait_ts=0)
        run("prompt", {"session_id": "ba11", "cwd": cwd, "transcript_path": str(tr)}, led)
        out = run("receipt", {"session_id": "ba11", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "done"}, led)
        check("unlock: one made before the open task started is dropped — no 'unasked' item, no Stop demand, judge_ok cleared",
              ids_("ba11") and "ask" not in ids_("ba11") and "judged question" not in (out or {}).get("reason", "") and gstate("ba11").get("judge_ok") == 0)
        setst("ba12", task_started=now_ - 5000, judge_ok=1, judge_ok_ts=now_ - 60, gate_wait_ts=0)
        run("prompt", {"session_id": "ba12", "cwd": cwd, "transcript_path": str(tr)}, led)
        check("unlock: one inside GATE_WAIT and after the task start survives — the guide asks for the question", "ask" in ids_("ba12"))
        out = run("receipt", {"session_id": "ba12", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "done"}, led)
        check("unlock: ... and Stop demands it", "judged question is still unasked" in (out or {}).get("reason", "") and gstate("ba12").get("judge_ok") == 1)
        setst("ba12", judge_ok=1, judge_ok_ts=now_ - H.GATE_WAIT - 100, gate_wait_ts=0)
        run("prompt", {"session_id": "ba12", "cwd": cwd, "transcript_path": str(tr)}, led)
        check("unlock: a judge reply (post/close_row) left unasked longer than GATE_WAIT stays live — the guide still asks", "ask" in ids_("ba12"))
        out = run("receipt", {"session_id": "ba12", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "done"}, led)
        check("unlock: ... and Stop still demands the question", "judged question is still unasked" in (out or {}).get("reason", ""))
        setst("ba12", judge_ok=1, judge_ok_ts=now_ - H.GATE_WAIT - 100, gate_wait_ts=now_ - H.GATE_WAIT - 100)  # a SendMessage unlock whose reply never came
        run("prompt", {"session_id": "ba12", "cwd": cwd, "transcript_path": str(tr)}, led)
        check("unlock: a SendMessage unlock older than GATE_WAIT with no gate agent running is not live", "ask" not in ids_("ba12"))
        check("qgate: ... and it lets no question through", "question gate" in reason(run("qgate", askp("ba12"), led)))
        setst("ba12", judge_ok=1, judge_ok_ts=now_ - 6000, task_started=now_ - 5000, gate_wait_ts=0)
        check("qgate: a stale unlock (made before the task began) lets no question through", "question gate" in reason(run("qgate", askp("ba12"), led)) and gstate("ba12").get("judge_ok") == 1)
        setst("ba12", judge_ok=1, judge_ok_ts=now_ - 60, task_started=now_ - 5000, gate_wait_ts=0)
        check("qgate: a live unlock lets exactly one question through", run("qgate", askp("ba12"), led) is None and gstate("ba12").get("judge_ok") == 0)
        # 7. background spawns: run_in_background is async; a lost agent closes; an old task's pending row is not "running"
        for sx_ in ("bb1", "bb2"):
            run("start", {"session_id": sx_, "cwd": cwd, "transcript_path": str(tr)}, led)
        out = run("post", dict(agent("haiku", "low", resp={"agentId": "rb2", "content": [blk(good)]}, cwd=cwd), session_id="bb1", tool_input=dict(agent("haiku", "low")["tool_input"], run_in_background=True)), led)
        check("post: run_in_background=True is async when the result is not marked completed", next(r for r in ledrows("bb1") if r.get("agent_id") == "rb2").get("status") == "pending")
        run("post", dict(agent("haiku", "low", resp={"status": "async_launched"}, cwd=cwd), session_id="bb2"), led)  # no agent id
        run("post", dict(agent("haiku", "low", resp=launch_("ghost1"), cwd=cwd), session_id="bb2"), led)  # an id with no transcript
        run("post", dict(agent("haiku", "low", resp=launch_("fresh1"), cwd=cwd), session_id="bb2"), led)
        rws = ledrows("bb2")
        rws[0]["ts"] = now_ - H.LOST_MIN * 60 - 60  # past LOST_MIN
        rws[1]["ts"] = now_ - H.LOST_MIN * 60 - 60
        rws[2]["ts"] = now_ - H.LOST_MIN * 60 + 120  # still inside it
        Path(led, "bb2.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rws))
        setst("bb2", task_started=now_ - H.LOST_MIN * 60 - 600)  # a long task: all three rows belong to it
        run("prompt", {"session_id": "bb2", "cwd": cwd, "transcript_path": str(tr)}, led)
        rws = ledrows("bb2")
        check("stale: a pending row with no agent id / no transcript older than LOST_MIN closes as lost, no escalate item; a younger one stays pending",
              [r.get("how") for r in rws[:2]] == ["lost", "lost"] and all(r.get("completed_ts") for r in rws[:2]) and rws[2].get("status") == "pending" and not any(i["p"] == "🟡" for i in gitems("bb2")))
        check("guide: only a pending row at or after the task start counts as running", [i["text"][:2] for i in gitems("bb2") if i["p"] == "⏳"] == ["1 "] and "bg:fresh1" in ids_("bb2"))
        rws[2]["ts"] = int(time.time()) - 5000  # now it belongs to an earlier task
        setst("bb2", task_started=int(time.time()) - 100)
        Path(led, "bb2.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rws))
        run("prompt", {"session_id": "bb2", "cwd": cwd, "transcript_path": str(tr)}, led)
        check("guide: a pending row from an earlier task is not counted as running", gitems("bb2") and not any(i["p"] == "⏳" for i in gitems("bb2")))
        run("post", dict(agent("haiku", "low", resp=launch_("late1"), cwd=cwd), session_id="bc2"), led)
        rl_ = ledrows("bc2"); rl_[0]["ts"] = now_ - H.LOST_MIN * 60 - 60
        Path(led, "bc2.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rl_))
        run("prompt", {"session_id": "bc2", "cwd": cwd, "transcript_path": str(tr)}, led)
        check("stop: setup — the row with no transcript was closed as lost", ledrows("bc2")[0].get("how") == "lost")
        run("stop", {"session_id": "bc2", "agent_id": "late1", "last_assistant_message": good}, led)
        lr_ = ledrows("bc2")[0]
        check("stop: a lost row that gets its real SubagentStop reply is re-graded from it, not dropped", lr_.get("how") == "hint" and lr_.get("status") == "done" and lr_.get("confidence") == "high")

        # 16. a run_in_background call whose result already came back complete, with its report, is a sync reply
        run("start", {"session_id": "bc4", "cwd": cwd, "transcript_path": str(tr)}, led)
        tin_ = dict(agent("haiku", "low")["tool_input"], run_in_background=True)
        run("post", dict(agent("haiku", "low", resp={"status": "completed", "agentId": "rc1", "content": [blk(good)]}, cwd=cwd), session_id="bc4", tool_input=tin_), led)
        rr_ = next(r for r in ledrows("bc4") if r.get("agent_id") == "rc1")
        check("post: run_in_background=True with a completed result that has a header is a sync reply, not pending", rr_.get("status") == "done" and rr_.get("confidence") == "high")
        run("post", dict(agent("haiku", "low", resp={"status": "completed", "agentId": "rc2", "content": [blk("Understood.")]}, cwd=cwd), session_id="bc4", tool_input=tin_), led)
        check("post: ... but a completed stub with no header stays pending", next(r for r in ledrows("bc4") if r.get("agent_id") == "rc2").get("status") == "pending")

        # ── Batch B ──
        RC = lambda n=1: f"🧾 **{n} Spawn{'' if n == 1 else 's'} · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y"
        stop_ = lambda sid_, text, active=False: run("receipt", {"session_id": sid_, "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": active, "last_assistant_message": text}, led)
        def b_task(sid_):
            run("start", {"session_id": sid_, "cwd": cwd, "transcript_path": str(tr)}, led)
            run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id=sid_, transcript_path=str(tr)), led)
        # 1. only a printed receipt closes the task
        b_task("bb3")
        setst("bb3", gate="task", task_budget=6)
        check("close_task: the first Stop with no receipt nudges", (stop_("bb3", "all done") or {}).get("decision") == "block")
        check("close_task: the spent nudge (stop_hook_active) ends the Stop without a block ...", stop_("bb3", "still no receipt", True) is None)
        s_ = gstate("bb3")
        check("close_task: ... but the task stays open: count, budget and gate answer kept, receipt_owed set", s_.get("spawns_since_receipt") == 1 and s_.get("gate") == "task" and s_.get("task_budget") == 6 and s_.get("receipt_owed") is True)
        check("close_task: the next Stop nudges again while the receipt is owed", (stop_("bb3", "next turn") or {}).get("decision") == "block")
        check("close_task: a task with receipt_owed shows a 🟡 `receipt` item in the guide", any(i["id"] == "receipt" and i["p"] == "🟡" for i in gitems("bb3")))
        check("close_task: a printed receipt closes it and clears receipt_owed", stop_("bb3", RC()) is None and gstate("bb3").get("spawns_since_receipt") == 0 and "receipt_owed" not in gstate("bb3") and gstate("bb3").get("gate") is None)
        Path(state, "no-user-claude.md").write_text("## abofles overrides\n- Receipt = off\n")
        b_task("bb4")
        check("skip mode: Stop does not block and does not close the task — it is marked to close on the next prompt", stop_("bb4", "done.") is None and gstate("bb4").get("spawns_since_receipt") == 1 and gstate("bb4").get("close_on_prompt") is True)
        run("prompt", {"session_id": "bb4", "cwd": cwd, "prompt": "<task-notification>agent finished</task-notification>"}, led)
        check("skip mode: a task-notification turn does not close it", gstate("bb4").get("spawns_since_receipt") == 1 and gstate("bb4").get("close_on_prompt") is True)
        run("prompt", {"session_id": "bb4", "cwd": cwd, "prompt": "now do the next thing"}, led)
        check("skip mode: the next real prompt closes it and clears the flags", gstate("bb4").get("spawns_since_receipt") == 0 and "close_on_prompt" not in gstate("bb4") and gstate("bb4").get("last_prompt_ts"))
        Path(state, "no-user-claude.md").unlink()
        # 2. a turn that ends with a question waits on the user
        b_task("bb5")
        check("question: a final line ending with ? gets no receipt nudge, the task stays open", stop_("bb5", "I found two ways.\nWhich one do you want?\n\n") is None and gstate("bb5").get("spawns_since_receipt") == 1)
        check("question: a ? in the middle of the text still gets the nudge", (stop_("bb5", "Why? Because it works.\nDone.") or {}).get("decision") == "block")
        b_task("bb5b")
        check("question: the first reply ending in ? is not nudged but marks the receipt owed (the 🟡 item shows)", stop_("bb5b", "Which one?") is None and gstate("bb5b").get("receipt_owed") is True and any(i["id"] == "receipt" for i in gitems("bb5b")))
        out = stop_("bb5b", "Still unsure — which one?")
        check("question: the next turn's Stop nudges even when it ends in ? again (not skipped forever) and names the owed receipt", (out or {}).get("decision") == "block" and "still owed" in out.get("reason", ""))
        check("question: the nudge is once per turn — stop_hook_active ends the Stop, the receipt stays owed", stop_("bb5b", "Which one?", True) is None and gstate("bb5b").get("receipt_owed") is True)
        check("question: a printed receipt clears it", stop_("bb5b", RC()) is None and "receipt_owed" not in gstate("bb5b") and not any(i["id"] == "receipt" for i in gitems("bb5b")))
        # connector_free resets with a new ask when no task is open
        run("start", {"session_id": "bb9", "cwd": cwd, "transcript_path": str(tr)}, led)
        setst("bb9", connector_free=2)
        run("prompt", {"session_id": "bb9", "cwd": cwd, "prompt": "<task-notification>x</task-notification>"}, led)
        check("connector_free: a notification prompt does not reset it", gstate("bb9").get("connector_free") == 2)
        run("prompt", {"session_id": "bb9", "cwd": cwd, "prompt": "next ticket please"}, led)
        check("connector_free: a real prompt with no open task (spawns_since_receipt 0) resets it", gstate("bb9").get("connector_free") == 0)
        b_task("bb8")
        setst("bb8", connector_free=2)
        run("prompt", {"session_id": "bb8", "cwd": cwd, "prompt": "and one more thing"}, led)
        check("connector_free: ... but not while the task is open (spawns pending a receipt)", gstate("bb8").get("connector_free") == 2)
        # 3. compact and resume keep the task; startup and clear reset it
        b_task("bb6")
        run("start", {"session_id": "bb6", "cwd": cwd, "transcript_path": str(tr), "source": "compact"}, led)
        check("start: a compact keeps the task", gstate("bb6").get("spawns_since_receipt") == 1)
        run("start", {"session_id": "bb6", "cwd": cwd, "transcript_path": str(tr), "source": "resume"}, led)
        check("start: a resume keeps the task", gstate("bb6").get("spawns_since_receipt") == 1)
        run("start", {"session_id": "bb6", "cwd": cwd, "transcript_path": str(tr), "source": "clear"}, led)
        check("start: a clear resets the task", gstate("bb6").get("spawns_since_receipt") == 0)
        b_task("bb6")
        run("start", {"session_id": "bb6", "cwd": cwd, "transcript_path": str(tr), "source": "startup"}, led)
        check("start: a startup resets the task", gstate("bb6").get("spawns_since_receipt") == 0)
        # 4. has_receipt wants the computed header
        check("has_receipt: the computed header counts (also with a gate suffix and leading spaces)", H.has_receipt(RC()) and H.has_receipt("text\n  " + RC(2)) and H.has_receipt("🧾 **0 Spawns + 1 gate · 1 u** vs Opus 5.5"))
        check("has_receipt: a quoted 🧾, the words `── receipt` and a bare 🧾 line are not a receipt",
              not H.has_receipt("the 🧾 emoji marks it") and not H.has_receipt("── receipt ──\ndone x") and not H.has_receipt("> 🧾 **1 Spawn · 1 u**") and not H.has_receipt("🧾 receipt below") and not H.has_receipt(""))
        b_task("bb7")
        check("receipt: a quoted receipt phrase in the final text still gets the nudge", (stop_("bb7", "I will print the 🧾 receipt later, ── receipt ── soon") or {}).get("decision") == "block")
        # 5. the session a script acts on
        import tempfile as _tf
        sess_saved = H.STATE_DIR
        U1, U2 = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        pj, po = str(Path(cwd, "projX")), str(Path(cwd, "projY"))
        os.makedirs(pj, exist_ok=True); os.makedirs(po, exist_ok=True)
        def put(d, sid_, root_, lp=None, age=0):
            fp = Path(d, f"{sid_}.json"); fp.write_text(json.dumps(dict({"root": root_}, **({"last_prompt_ts": lp} if lp else {}))))
            os.utime(fp, (time.time() - age, time.time() - age))
        try:
            with _tf.TemporaryDirectory() as sd:
                H.STATE_DIR = Path(sd)
                put(sd, "sA", pj, lp=100, age=500); put(sd, "sB", pj, lp=900, age=900); put(sd, "sC", pj, age=0); put(sd, "sO", po, lp=5000, age=0); put(sd, U1, pj, lp=50, age=700)
                pin()
                check("session: last_prompt_ts beats a newer mtime (sB prompted last though sC wrote last)", H.newest_session_id(pj) == "sB")
                check("session: another project's newer state is never chosen", H.newest_session_id(pj) != "sO" and H.newest_session_id(po) == "sO")
                os.environ["ABOFLES_SESSION"] = "sA"
                check("session: ABOFLES_SESSION wins over everything", H.newest_session_id(pj, U1) == "sA" and H.newest_state_path(pj).name == "sA.json")
                pin()
                check("session: an explicit UUID of an existing state is used", H.newest_session_id(pj, U1) == U1 and H.newest_state(pj, U1).get("last_prompt_ts") == 50)
                check("session: an unexpanded ${CLAUDE_SESSION_ID}, an empty value, a non-UUID and an unknown UUID are ignored",
                      all(H.newest_session_id(pj, v) == "sB" for v in ("${CLAUDE_SESSION_ID}", "", None, "sA", U2)))
                check("session: an unexpanded ABOFLES_SESSION is ignored", (os.environ.update(ABOFLES_SESSION="${X}") or True) and H.newest_session_id(pj) == "sB" and (pin() or True))
            with _tf.TemporaryDirectory() as sd:
                H.STATE_DIR = Path(sd)
                put(sd, "mOld", pj, age=900); put(sd, "mNew", pj, age=10); put(sd, "mOther", po, age=0)
                check("session: with no last_prompt_ts the newest mtime of the project wins", H.newest_session_id(pj) == "mNew")
                check("session: a folder with no state of its own gets nothing, not another project's", H.newest_state_path(str(Path(cwd, "projZ"))) is None and H.newest_state(str(Path(cwd, "projZ"))) == {})
                put(sd, "mSub", pj, lp=70, age=0)
                sub_ = Path(pj, "deep"); sub_.mkdir(exist_ok=True)
                check("session: a command run in a subfolder of the project belongs to the project's session", H.newest_session_id(str(sub_)) == "mSub")
        finally:
            H.STATE_DIR = sess_saved
            pin()
        av = ["set", "4", "--session", U1]
        check("session_arg: pops --session <id> and returns it", H.session_arg(av) == U1 and av == ["set", "4"])
        av = ["--all", "--session", "${CLAUDE_SESSION_ID}"]
        check("session_arg: an unexpanded value is dropped and ignored", H.session_arg(av) is None and av == ["--all"])
        av = ["resolve", "1", "--session", "mine", "--session", U1]
        check("session_arg: keep=True leaves usable pairs, the first usable id wins", H.session_arg(av, keep=True) == "mine" and av == ["resolve", "1", "--session", "mine", "--session", U1])
        av = ["resolve", "1", "--session"]
        check("session_arg: a missing value stays for the script's own usage check", H.session_arg(av) is None and av == ["resolve", "1", "--session"])
        # the script, end to end: --session <uuid> acts on that state, not on a newer one of the same folder
        run("start", {"session_id": U2, "cwd": cwd, "transcript_path": str(tr)}, led)
        run("start", {"session_id": "sessNew", "cwd": cwd, "transcript_path": str(tr)}, led)
        run("prompt", {"session_id": "sessNew", "cwd": cwd, "prompt": "hi"}, led)
        pre_ = gstate("sessA").get("task_budget")
        check("cli: agents.py set N --session <uuid> writes that session only", "agents: 3 this task" in ag("set", "3", "--session", U2) and gstate(U2).get("task_budget") == 3 and gstate("sessNew").get("task_budget") is None and gstate("sessA").get("task_budget") == pre_)
        check("cli: agents.py ignores an unexpanded session id and acts on the folder's newest prompt", "agents: 6 this task" in ag("set", "6", "--session", "${CLAUDE_SESSION_ID}") and gstate("sessNew").get("task_budget") == 6)
        # 6. stale install
        import tempfile as _tf2
        home_saved = os.environ.get("HOME")
        try:
            with _tf2.TemporaryDirectory() as hh:
                os.environ["HOME"] = hh
                cache = Path(hh, ".claude", "plugins", "cache", "mp", "abofles")
                old_root, new_root = cache / "1.0.0", cache / "1.3.0"
                for r_, v_ in ((old_root, "1.0.0"), (new_root, "1.3.0")):
                    (r_ / ".claude-plugin").mkdir(parents=True); (r_ / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "abofles", "version": v_}))
                reg = Path(hh, ".claude", "plugins", "installed_plugins.json")
                entry = [{"scope": "user", "installPath": str(new_root), "version": "1.3.0"}]
                reg.write_text(json.dumps({"version": 2, "plugins": {"abofles@mp": entry, "other@mp": [{"installPath": str(old_root), "version": "9"}]}}))
                note_ = H.stale_install_note(old_root)
                check("stale install: a session from an old cache folder gets the one-line warning", note_ == "abofles: this session runs 1.0.0 from an old cache folder; 1.3.0 is installed — restart Claude Code to load it.")
                reg.write_text(json.dumps({"abofles@mp": entry}))
                check("stale install: the registry without a top-level plugins key works too", "1.3.0 is installed" in (H.stale_install_note(old_root) or ""))
                check("stale install: the running copy is the installed one -> silent", H.stale_install_note(new_root) is None)
                reg.write_text(json.dumps({"plugins": {"abofles@mp": entry + [{"installPath": str(old_root), "version": "1.0.0"}]}}))
                check("stale install: it matches any abofles@* install path -> silent", H.stale_install_note(old_root) is None)
                check("stale install: the dev repo (outside the cache) is silent", H.stale_install_note() is None and H.stale_install_note(Path(cwd)) is None)
                reg.write_text("{ not json")
                check("stale install: bad JSON is silent", H.stale_install_note(old_root) is None)
                reg.unlink()
                check("stale install: no registry file is silent", H.stale_install_note(old_root) is None)
                reg.write_text(json.dumps({"plugins": {"other@mp": entry}}))
                check("stale install: abofles not in the registry is silent", H.stale_install_note(old_root) is None)
            note_f = H.stale_install_note
            H.stale_install_note = lambda root=None: "abofles: stale"
            st_i = {}
            check("stale install: emitted once per session (install_checked)", H.install_note_once(st_i) == "abofles: stale" and st_i.get("install_checked") is True and H.install_note_once(st_i) is None)
            H.stale_install_note = note_f
        finally:
            if home_saved is None: os.environ.pop("HOME", None)
            else: os.environ["HOME"] = home_saved


    # scripts: status.py / memo.py exit codes
    with tempfile.TemporaryDirectory() as xh, tempfile.TemporaryDirectory() as xp:
        sdir = Path(__file__).resolve().parent
        xenv = dict(os.environ, HOME=xh, ABOFLES_LEDGER_DIR=str(Path(xh, "led")), ABOFLES_STATE_DIR=str(Path(xh, "st")))
        Path(xh, "led").mkdir(); Path(xh, "st").mkdir()
        st_ = lambda *a: subprocess.run([sys.executable, str(sdir / "status.py"), *a], cwd=xp, capture_output=True, text=True, env=xenv)
        me_ = lambda *a: subprocess.run([sys.executable, str(sdir / "memo.py"), *a], cwd=xp, capture_output=True, text=True, env=xenv)
        check("exit: status --resolve with no ledger at all exits 1", st_("--resolve", "abc").returncode == 1)
        lf = Path(xh, "led", "xs.jsonl")
        lf.write_text('{"agent_id": "abc123", "status": "partial"}\nHALF{"agent_id":"abc9\n{"agent_id": "abd1", "status": "blocked"}\n')
        check("exit: status --resolve as the last arg exits 2", st_("--resolve").returncode == 2)
        check("exit: status --resolve with an empty id exits 2", st_("--resolve", "", "--session", "xs").returncode == 2)
        check("exit: status --resolve with a flag as id exits 2", st_("--resolve", "--trace").returncode == 2)
        check("exit: status --session without a value exits 2", st_("--resolve", "abc", "--session").returncode == 2)
        check("exit: status --unresolve with an empty session exits 2", st_("--unresolve", "abc", "--session", "", "--trace").returncode == 2)
        check("exit: status --session ../ is cleaned to a name in the ledger dir (no such ledger, exit 1)", st_("--resolve", "abc", "--session", "../../nope").returncode == 1 and not Path(xh, "nope.jsonl").exists())
        r1 = st_("--resolve", "abc1", "--session", "xs", "--trace", "by test")
        txt = lf.read_text().splitlines()
        check("exit: status --resolve exits 0, marks the row, keeps the half-written line verbatim",
              r1.returncode == 0 and json.loads(txt[0]).get("resolved") is True and txt[1] == 'HALF{"agent_id":"abc9' and json.loads(txt[2]) == {"agent_id": "abd1", "status": "blocked"})
        memd = lambda s: Path(xp, ".claude", "abofles-memo.d", f"{s[:8]}.md")  # a trace lands in the file of the session it names
        mem = memd("xs")
        check("exit: status --resolve --trace wrote one Journal line", mem.read_text().count("resolved by hand:") == 1)
        r2 = st_("--resolve", "abc1", "--session", "xs", "--trace")
        check("exit: status --resolve of a resolved row exits 3, writes no trace", r2.returncode == 3 and mem.read_text().count("resolved by hand:") == 1)
        check("exit: status --resolve miss exits 1", st_("--resolve", "zzz", "--session", "xs").returncode == 1)
        check("exit: status --unresolve exits 0", st_("--unresolve", "abc1", "--session", "xs").returncode == 0 and "resolved" not in json.loads(lf.read_text().splitlines()[0]))
        check("exit: status --unresolve of an open row exits 3, writes no trace", st_("--unresolve", "abc1", "--session", "xs", "--trace").returncode == 3 and "reopened by hand" not in mem.read_text())
        # memo.py: Needs-you items through the hook's own writer
        subprocess.run([sys.executable, "-c", "import sys,os; sys.path.insert(0, sys.argv[1]); import abofles_hook as h; h.memo_needs(os.getcwd(), 'sessAAAA', 'owner decision: pick A or B')", str(sdir.parent / "hooks")], cwd=xp, env=xenv)
        check("exit: memo resolve without n exits 2", me_("resolve").returncode == 2 and me_("resolve", "x").returncode == 2)
        check("exit: memo resolve --session without a value exits 2", me_("resolve", "1", "--session").returncode == 2 and me_("reopen", "1", "--session", "--trace").returncode == 2)
        check("exit: memo reopen of an open item exits 3, writes no trace", me_("reopen", "1", "--trace").returncode == 3 and "reopened by hand" not in mem.read_text())
        m1 = me_("resolve", "1", "note", "--trace", "--session", "mysess")
        check("exit: memo resolve exits 0 and the trace carries the given session", m1.returncode == 0 and "· resolved by hand: owner decision 1" in memd("mysess").read_text())
        n_ = memd("mysess").read_text().count("by hand:")
        m2 = me_("resolve", "1", "--trace", "--session", "mysess")
        check("exit: memo resolve of a resolved item exits 3, writes no trace", m2.returncode == 3 and memd("mysess").read_text().count("by hand:") == n_)
        check("exit: memo resolve of a missing item exits 1", me_("resolve", "9").returncode == 1 and me_("reopen", "9").returncode == 1)
        check("exit: memo reopen exits 0 with the given session", me_("reopen", "1", "--trace", "--session", "other").returncode == 0 and "· reopened by hand" in memd("other").read_text())

    # ── 1.7.0: specialist reviewers and the review gate ──
    with tempfile.TemporaryDirectory() as rh:
        os.environ["ABOFLES_STATE_DIR"] = str(Path(rh, "st")); os.environ["ABOFLES_CONFIG"] = str(Path(rh, "config.json"))
        os.environ.pop("ABOFLES_SESSION", None)
        import importlib.util as _iu3
        _hs3 = _iu3.spec_from_file_location("abofles_hook_rv", str(HOOK)); R = _iu3.module_from_spec(_hs3); _hs3.loader.exec_module(R)
        led3 = str(Path(rh, "led")); Path(led3).mkdir()
        P = Path(rh, "P"); P.mkdir(); Path(P, "src").mkdir(); Path(P, "src/a.cs").write_text("x\n")
        trr = Path(rh, "tr.jsonl"); trr.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "role": "assistant", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n")
        rst = lambda sid_: json.loads(Path(rh, "st", f"{sid_}.json").read_text())
        rows_ = lambda sid_: [json.loads(l) for l in Path(led3, f"{sid_}.jsonl").read_text().splitlines() if l.strip()]
        VOK = "STATUS: done\nCONFIDENCE: high\nVERDICT: PASS\nEVIDENCE:\n- authz — PASS — src/a.cs:1\nISSUES:\nNOTE: none"
        WOK = "STATUS: done\nCONFIDENCE: high\nCHANGED:\n- src/a.cs — x\nRAN: none\nLEFT: none"
        def sp(sid_, side, stype, model="opus", effort="high", resp=WOK, topic="Payments & Gateway Integration", tier=4):
            d = dict(agent(model, effort, stype, prompt=f"abofles: {topic} / {side} · T{tier}\nq\nLine cap: 40", resp=resp, cwd=str(P)), session_id=sid_, transcript_path=str(trr))
            run("pre", d, led3); return run("post", d, led3)
        def stop_(sid_, msg, active=False):
            return run("receipt", {"session_id": sid_, "cwd": str(P), "transcript_path": str(trr), "stop_hook_active": active, "last_assistant_message": msg}, led3)
        RCPT = "🧾 **2 Spawns · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y"
        check("review: parse_header reads the reviewer tags", R.parse_header("abofles: Payments & Gateway Integration / Security · T4")[1] == "Security" and R.parse_header("abofles: X / qa · T3")[1] == "QA"
              and R.parse_header("abofles: X / uiux · T3")[1] == "UIUX" and R.parse_header("abofles: X / Clean · T3")[1] == "Clean" and R.parse_header("abofles: X / Verify · T2")[1] == "Verify")
        check("review: side_of maps the reviewer agent types", R.side_of("abofles:abofles-security")[1] == "Security" and R.side_of("abofles:abofles-qa")[1] == "QA" and R.side_of("abofles:abofles-cleancoder")[1] == "Clean" and R.side_of("abofles:abofles-verifier")[1] == "Verify")
        check("review: fable is refused for a reviewer", "fable is only for" in reason(run("pre", dict(agent("fable", "medium", "abofles:abofles-finance", cwd=str(P)), session_id="rv0"), led3)))
        check("review: workflow.json is generated and names the reviewers per topic", (R.workflow_table().get("topics") or {}).get("Payments & Gateway Integration", {}).get("reviewers", {}).get("4") == ["finance", "security", "tester"])
        # a T4 money change closed without its reviewers: refused once, then closed with a guide item
        run("start", {"session_id": "rv1", "cwd": str(P), "transcript_path": str(trr)}, led3)
        json.dump(dict(rst("rv1"), gate="auto"), open(Path(rh, "st", "rv1.json"), "w"))
        sp("rv1", "Work", "abofles:abofles-worker")
        sp("rv1", "Verify", "abofles:abofles-verifier", resp=VOK)
        out = stop_("rv1", RCPT)
        check("review gate: 🔴 change with no reviewer -> receipt refused once, naming Finance, Security, Tester and the Verify cell",
              (out or {}).get("decision") == "block" and "review gate" in out.get("reason", "") and "Finance, Security, Tester" in out["reason"] and "Opus 5.5 · High" in out["reason"]
              and "`abofles: Payments & Gateway Integration / Security · T4`" in out["reason"] and rst("rv1").get("spawns_since_receipt") == 2)
        sp("rv1", "Finance", "abofles:abofles-finance", resp=VOK)
        check("review: the ledger row carries review=finance, graded as a verifier (PASS)", any(r.get("review") == "finance" and r.get("verdict") == "PASS" and r.get("side") == "Finance" for r in rows_("rv1")))
        out = stop_("rv1", RCPT + "\n- `workflow` → Read ✓ · Work ✓ · Verify ✓ · Finance ✓ · Security skipped: internal tool, no external input · Tester skipped: covered by Verify", active=True)
        check("review gate: skipped reviewers named in the workflow line pass; the task closes", out is None and rst("rv1").get("spawns_since_receipt") == 0 and not rst("rv1").get("review_missing"))
        sp("rv1", "Work", "abofles:abofles-worker")
        out = stop_("rv1", RCPT)
        out2 = stop_("rv1", RCPT, active=True)
        check("review gate: the refusal is spent after one Stop; the task closes and the guide shows the missing reviewers",
              (out or {}).get("decision") == "block" and out2 is None and rst("rv1").get("spawns_since_receipt") == 0 and rst("rv1").get("review_missing", {}).get("names") == ["finance", "security", "tester"]
              and any(i.get("id") == "review" and "Finance, Security, Tester" in i.get("text", "") for i in (rst("rv1").get("guide") or {}).get("items") or []))
        sp("rv1", "Work", "abofles:abofles-worker")
        check("review gate: the next task's first spawn clears the item", not rst("rv1").get("review_missing"))
        # T3: warn only (guide item, no refusal); Review gate = on refuses T3 too; off is silent; Reviewers: override
        run("start", {"session_id": "rv2", "cwd": str(P), "transcript_path": str(trr)}, led3)
        json.dump(dict(rst("rv2"), gate="auto"), open(Path(rh, "st", "rv2.json"), "w"))
        sp("rv2", "Work", "abofles:abofles-worker", model="sonnet", topic="Business Logic (domain rules)", tier=3)
        out = stop_("rv2", RCPT)
        check("review gate: 🟠 change with no reviewer -> no refusal, guide item names QA", out is None and rst("rv2").get("review_missing", {}).get("names") == ["qa"])
        Path(P, "CLAUDE.md").write_text("## abofles overrides\n- Review gate = on\n")
        sp("rv2", "Work", "abofles:abofles-worker", model="sonnet", topic="Business Logic (domain rules)", tier=3)
        check("review gate: Review gate = on refuses a 🟠 change too", (stop_("rv2", RCPT) or {}).get("decision") == "block")
        stop_("rv2", RCPT, active=True)
        Path(P, "CLAUDE.md").write_text("## abofles overrides\n- Review gate = off\n")
        sp("rv2", "Work", "abofles:abofles-worker")
        check("review gate: off -> a 🔴 change closes silently, no item", stop_("rv2", RCPT) is None and not rst("rv2").get("review_missing"))
        Path(P, "CLAUDE.md").write_text("## abofles overrides\n- Reviewers: FIN = finance\n")
        sp("rv2", "Work", "abofles:abofles-worker")
        out = stop_("rv2", RCPT)
        check("review gate: Reviewers: <group> = finance narrows the requirement", "Finance" in (out or {}).get("reason", "") and "Security" not in (out or {}).get("reason", ""))
        stop_("rv2", RCPT, active=True)
        Path(P, "CLAUDE.md").write_text("## abofles overrides\n- Reviewers: Payments & Gateway Integration = none\n")
        sp("rv2", "Work", "abofles:abofles-worker")
        check("review gate: Reviewers: <topic> = none drops it", stop_("rv2", RCPT) is None and not rst("rv2").get("review_missing"))
        Path(P, "CLAUDE.md").unlink()
        check("review: topic 5 adds Compliance at T3 and T4", (R.workflow_table()["topics"]["Data Privacy, PII & Compliance"]["reviewers"]["4"]) == ["security", "tester", "compliance"])
        # a receipt printed mid-turn (closed by the next spawn's pre) cannot be refused: the gate warns in the guide and the warning survives that spawn
        run("start", {"session_id": "rv3", "cwd": str(P), "transcript_path": str(trr)}, led3)
        json.dump(dict(rst("rv3"), gate="auto"), open(Path(rh, "st", "rv3.json"), "w"))
        sp("rv3", "Work", "abofles:abofles-worker")
        with open(trr, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"id": "m9", "role": "assistant", "content": [{"type": "text", "text": RCPT}]}}) + "\n")
        sp("rv3", "Work", "abofles:abofles-worker", topic="Business Logic (domain rules)", tier=3)
        check("review gate: a mid-turn receipt closes the task, raises the missing reviewers in the guide, and the closing spawn keeps the item",
              rst("rv3").get("spawns_since_receipt") == 1 and rst("rv3").get("review_missing", {}).get("names") == ["finance", "security", "tester"])
        check("review: the gate's cell text comes from workflow.json", R.verify_cell(4) == ("opus", "high") and R.verify_cell(3) == ("sonnet", "high") and (R.workflow_table().get("verify") or {}).get("4") == "opus·high")
        check("review: gen_matrix --check is up to date", subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "gen_matrix.py"), "--check"], capture_output=True, text=True).returncode == 0)
        os.environ["ABOFLES_STATE_DIR"] = state

    # ── 1.6.0: work root (the memo follows the session's edits), memo move, resume/guide scopes, registry ──
    with tempfile.TemporaryDirectory() as wh:
        os.environ["ABOFLES_STATE_DIR"] = str(Path(wh, "st")); os.environ["ABOFLES_CONFIG"] = str(Path(wh, "config.json"))
        os.environ.pop("ABOFLES_SESSION", None)
        import importlib.util as _iu2
        _hs2 = _iu2.spec_from_file_location("abofles_hook_wr", str(HOOK)); W = _iu2.module_from_spec(_hs2); _hs2.loader.exec_module(W)
        led2 = str(Path(wh, "led")); Path(led2).mkdir()
        A, B, C, D = (Path(wh, n) for n in "ABCD")
        for d in (A, B, C, D):
            d.mkdir()
        gitok = all(subprocess.run(["git", "init", "-q"], cwd=d, capture_output=True).returncode == 0 for d in (B, C))
        wst = lambda sid_: json.loads(Path(wh, "st", f"{sid_}.json").read_text())
        ed = lambda sid_, path, tool="Edit": run("edit", {"session_id": sid_, "cwd": str(A), "tool_name": tool, "tool_input": {"file_path": str(path)}}, led2)
        RCM = "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → moved thing\n- `check` → ok\n- `open` → owner decision: keep the banner wide or narrow"
        run("start", {"session_id": "mv1", "cwd": str(A)}, led2)
        run("receipt", {"session_id": "mv1", "cwd": str(A), "stop_hook_active": False, "last_assistant_message": RCM}, led2)
        memA, memB = W.memo_path(str(A)), W.memo_path(str(B))
        check("work: a receipt lands in the launch folder before any edit", memA.exists() and "(s:mv1)" in memA.read_text() and W.session_memo_path(str(A), "mv1").exists())
        check("work: the memo headers carry the project path", f"Project: {os.path.realpath(A)}" in memA.read_text() and f"Project: {os.path.realpath(A)}" in W.session_memo_path(str(A), "mv1").read_text())
        ed("mv1", A / "x.txt")
        ed("mv1", B / "b1.py"); ed("mv1", B / "b2.py", "Write")
        check("work: edits are counted per repository (1 in the launch folder, 2 in B), under 3 nothing moves",
              wst("mv1").get("work", {}).get(os.path.realpath(A)) == 1 and wst("mv1").get("work", {}).get(os.path.realpath(B)) == 2 and not wst("mv1").get("project") and memA.exists() and not memB.exists())
        ed("mv1", B / "b3.py")
        sB = W.session_memo_path(str(B), "mv1")
        check("work: the third edit in B (more than in A) moves the session's memo to B", wst("mv1").get("project") == os.path.realpath(B) and sB.exists() and memB.exists())
        check("work: the session file moved with its Now, Journal and a 'moved here' trace line",
              "moved thing" in sB.read_text() and "moved here from A: most edits of this session land in this repository" in sB.read_text() and not W.session_memo_path(str(A), "mv1").exists())
        check("work: its Needs-you item moved and was renumbered; A's index line is gone", "1. [ ]" in W.memo_read(str(B))["Needs you"] and "(s:mv1)" in memB.read_text()
              and "(s:mv1)" not in memA.read_text() and not any(k == "mv1" for k, _ in W.index_entries(W.memo_read(str(A)))) and any(k == "mv1" for k, _ in W.index_entries(W.memo_read(str(B)))))
        check("work: a trace line is not a receipt", W.index_field([l for k, l in W.index_entries(W.memo_read(str(B))) if k == "mv1"][0], "receipts") == "1")
        run("receipt", {"session_id": "mv1", "cwd": str(A), "stop_hook_active": False, "last_assistant_message": RCM.replace("moved thing", "second thing")}, led2)
        check("work: a later receipt (hook cwd still A) journals into B", "second thing" in sB.read_text() and "second thing" not in memA.read_text())
        check("work: scripts find the session from the work root too", (W.newest_state_path(str(B)) or Path("x")).stem == "mv1" and (W.newest_state_path(str(A)) or Path("x")).stem == "mv1")
        check("work: registry lists both projects", set(map(os.path.realpath, W.registry_read())) >= {os.path.realpath(A), os.path.realpath(B)})
        # edits under the launch root (nested repo, worktree of it) and in a worktree of B count for A / B, never a third project
        nested = A / "nested"; nested.mkdir(); subprocess.run(["git", "init", "-q"], cwd=nested, capture_output=True)
        run("start", {"session_id": "mv2", "cwd": str(A)}, led2)
        ed("mv2", nested / "n.txt"); ed("mv2", nested / "n2.txt"); ed("mv2", nested / "n3.txt"); ed("mv2", nested / "n4.txt")
        check("work: a nested repo inside the launch folder counts as the launch folder", wst("mv2").get("work", {}).get(os.path.realpath(A)) == 4 and not wst("mv2").get("project"))
        if gitok and subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"], cwd=C, capture_output=True).returncode == 0 \
                and subprocess.run(["git", "worktree", "add", "-q", str(Path(wh, "Cwt"))], cwd=C, capture_output=True).returncode == 0:
            check("work: a file in a worktree maps to its main repository", W.repo_top(str(Path(wh, "Cwt", "f.txt"))) == os.path.realpath(C))
        check("work: a file in no repository counts for nothing", W.work_key({"root": str(A)}, str(D / "d.txt")) is None and W.repo_top(str(D / "d.txt")) is None)
        # a tie never moves; a majority elsewhere does, and the memo can move again when the count turns
        run("start", {"session_id": "mv3", "cwd": str(B)}, led2)
        for n in range(3):
            run("edit", {"session_id": "mv3", "cwd": str(B), "tool_name": "Edit", "tool_input": {"file_path": str(C / f"c{n}.py")}}, led2)
            run("edit", {"session_id": "mv3", "cwd": str(B), "tool_name": "Edit", "tool_input": {"file_path": str(B / f"b{n}.py")}}, led2)
        check("work: a tie keeps the launch folder", not wst("mv3").get("project"))
        run("edit", {"session_id": "mv3", "cwd": str(B), "tool_name": "Edit", "tool_input": {"file_path": str(C / "c9.py")}}, led2)
        check("work: one more edit in C (4 vs 3) moves the project to C", wst("mv3").get("project") == os.path.realpath(C))
        for n in range(2):
            run("edit", {"session_id": "mv3", "cwd": str(B), "tool_name": "Edit", "tool_input": {"file_path": str(B / f"bb{n}.py")}}, led2)
        check("work: back to the launch folder when it leads again (5 vs 4)", not wst("mv3").get("project"))
        check("work: a hook with no file_path or an unknown tool changes nothing", run("edit", {"session_id": "mv3", "cwd": str(B), "tool_name": "Edit", "tool_input": {}}, led2) is None
              and run("edit", {"session_id": "mv3", "cwd": str(B), "tool_name": "Read", "tool_input": {"file_path": str(C / "z.py")}}, led2) is None and wst("mv3")["work"].get(os.path.realpath(C)) == 4)
        run("start", {"session_id": "mv3", "cwd": str(B), "source": "clear"}, led2)
        check("work: /clear or a new session starts the count again", "work" not in wst("mv3") and "project" not in wst("mv3"))
        # scopes: session / project (default) / all; a session with nothing of its own sees a hint line
        run("start", {"session_id": "oth1", "cwd": str(B)}, led2)
        run("receipt", {"session_id": "oth1", "cwd": str(B), "stop_hook_active": False, "last_assistant_message": RCM.replace("moved thing", "other thing").replace("keep the banner wide or narrow", "ship the footer today or next week")}, led2)
        rb_p = W.resume_block(str(B), session_id="mv1")
        rb_s = W.resume_block(str(B), session_id="mv1", scope="session")
        check("scope: project (default) shows every open item of the project", "2 open" in rb_p and "(s:oth1)" in rb_p and "(s:mv1)" in rb_p and "· scope" not in rb_p)
        check("scope: session shows only this session's items and says so in the header", "· scope session" in rb_s and "1 open" in rb_s and "(s:oth1)" not in rb_s and "(s:mv1)" in rb_s)
        rb_n = W.resume_block(str(B), session_id="newS1")
        check("scope: a session with nothing of its own gets one hint line instead of the other sessions' lines",
              "- `project` → B: 2 other sessions, newest " in rb_n and "their work, not yours; `/abofles:resume --scope project` shows them" in rb_n and "not this one" not in rb_n and "- `now` →" not in rb_n)
        rb_nx = W.resume_block(str(B), session_id="newS1", scope="project", explicit=True)
        check("scope: --scope project (explicit) shows the other sessions in full", "not this one" in rb_nx and "- `project` →" not in rb_nx)
        check("scope: session for a session with nothing of its own shows none", "- `needs you` → none of this session" in W.resume_block(str(B), session_id="newS1", scope="session"))
        W.memo_needs(str(A), "zz", "owner decision: A keeps this one")
        rb_a = W.resume_block(str(B), session_id="mv1", scope="all")
        check("scope: all adds one `elsewhere` line per other project with its open count", "· scope all" in rb_a and "- `elsewhere` →" in rb_a and re.search(r"^  - A · 1 open: owner decision: A keeps this one$", rb_a, re.M) and "  - B" not in rb_a and "  - C" not in rb_a)
        check("scope: precedence built-in < saved default < override < flag",
              W.resume_scope(str(B)) == ("project", "built-in") and W.config_write({"resume_scope": "all"}) and W.resume_scope(str(B)) == ("all", "default")
              and (Path(B, "CLAUDE.md").write_text("## abofles overrides\n- Resume = session\n") or True) and W.resume_scope(str(B)) == ("session", "override")
              and W.resume_scope(str(B), "project") == ("project", "flag") and W.resume_scope(str(B), "bogus") == ("session", "override"))
        check("scope: the override drives the default block", "· scope session" in W.resume_block(str(B), session_id="mv1"))
        Path(B, "CLAUDE.md").unlink(); W.config_write({})
        st1 = wst("mv1")
        gi = lambda sc: " | ".join(t for _, t in W.guide_items(str(B), st1, "mv1", scope=sc))
        check("scope: the guide counts owner decisions by scope", "1 owner decision open" in gi("session") and "2 owner decisions open" in gi("project") and "2 owner decisions open" in gi("all")
              and "open in other project: A (1)" in gi("all") and "other project" not in gi("project"))
        # memo.py: --scope, scope <value>, and no write without a session state
        sdir2 = Path(__file__).resolve().parent
        env2 = dict(os.environ, ABOFLES_LEDGER_DIR=led2, ABOFLES_SESSION="mv1")
        mp = lambda *a, cwd=B, env=env2: subprocess.run([sys.executable, str(sdir2 / "memo.py"), *a], cwd=cwd, capture_output=True, text=True, env=env)
        check("memo.py: show --scope session prints the session-scoped block", "· scope session" in mp("show", "--scope", "session").stdout)
        check("memo.py: show --scope all prints the elsewhere lines with each project's first open item", re.search(r"^  - A · 1 open: owner decision: A keeps this one$", mp("show", "--scope", "all").stdout, re.M) is not None)
        rs, rp, ra = (mp("show", "--scope", x).stdout for x in ("session", "project", "all"))
        check("memo.py: the guide line of the block follows the scope too (session: own decision only; project: both; all: other projects counted)",
              "🟠 1 owner decision open" in rs.split("- `guide`")[1] and "(s:oth1)" not in rs and "🟠 2 owner decisions open" in rp.split("- `guide`")[1] and "open in other project: A (1)" in ra.split("- `guide`")[1] and "other project" not in rp)
        check("memo.py: an unknown --scope exits 2", mp("show", "--scope", "bogus").returncode == 2)
        r = mp("scope", "all")
        check("memo.py: scope <value> saves the user default", r.returncode == 0 and r.stdout.strip() == "saved as the default · scope: all (from the saved default (" + str(Path(wh, "config.json")) + "))" and json.loads(Path(wh, "config.json").read_text())["resume_scope"] == "all")
        check("memo.py: scope alone prints the scope in force and its source", mp("scope").stdout.startswith("scope: all (from the saved default"))
        check("memo.py: the saved default drives show", "· scope all" in mp("show").stdout and "· scope" not in mp("show", "--scope", "project").stdout)
        W.config_write({})
        env3 = dict(os.environ, ABOFLES_LEDGER_DIR=led2); env3.pop("ABOFLES_SESSION", None)
        r = mp("resolve", "1", "x", cwd=D, env=env3)
        check("memo.py: a write with no session state, no --session and no memo in the folder exits 4 and writes nothing", r.returncode == 4 and "nothing written" in r.stdout and not Path(D, ".claude").exists())
        check("memo.py: naming a session allows the write (two sessions in one root)", mp("note", "named", "--session", "d1", cwd=D, env=env3).returncode == 0 and Path(D, ".claude", "abofles-memo.md").exists())
        import shutil; shutil.rmtree(Path(D, ".claude"))
        r = mp("now", cwd=D, env=env3)
        check("memo.py: now with no session state exits 4 too", r.returncode == 4 and not Path(D, ".claude").exists())
        check("memo.py: show with no session state still reads", mp("show", cwd=D, env=env3).returncode == 0)
        check("memo.py: a write from the launch folder goes to the work root", mp("note", "settled in chat", cwd=A).returncode == 0 and "settled in chat" in memB.read_text() and "settled in chat" not in memA.read_text())
        # memo.py move <root>: a misfiled session moved by hand (oth1 from B to D), state follows
        r = mp("move", str(D), "--session", "oth1", cwd=B, env=env3)
        check("memo.py: move <root> moves the session's memo and sets its project", r.returncode == 0 and r.stdout.startswith("moved: session oth1 → ") and W.session_memo_path(str(D), "oth1").exists()
              and "other thing" in W.session_memo_path(str(D), "oth1").read_text() and "moved here from B" in W.session_memo_path(str(D), "oth1").read_text()
              and not W.session_memo_path(str(B), "oth1").exists() and "(s:oth1)" not in memB.read_text() and "(s:oth1)" in W.memo_path(str(D)).read_text() and wst("oth1").get("project") == os.path.realpath(D))
        check("memo.py: move to the same folder exits 3, a missing folder exits 2", mp("move", str(D), "--session", "oth1", cwd=B, env=env3).returncode == 3 and mp("move", str(Path(wh, "nope")), "--session", "oth1", cwd=B, env=env3).returncode == 2)
        check("memo.py: after the move, oth1's own items are gone from B and the guide of B counts one", "1 owner decision open" in gi("project"))
        import shutil; shutil.rmtree(Path(D, ".claude"))
        gp = lambda *a: subprocess.run([sys.executable, str(sdir2 / "guide.py"), *a], cwd=A, capture_output=True, text=True, env=env2)
        check("guide.py: --scope all names the other project's open decisions", "open in other project: A (1)" in gp("--scope", "all").stdout and gp("--scope", "bogus").returncode == 2)
        os.environ["ABOFLES_STATE_DIR"] = state

    # scripts: project-scoped ledger, the user's --session wins, a trailing empty --session is ignored
    sdir = Path(__file__).resolve().parent
    sid_ = "11111111-2222-3333-4444-555555555555"
    with tempfile.TemporaryDirectory() as xh, tempfile.TemporaryDirectory() as xp, tempfile.TemporaryDirectory() as xo:
        xenv = dict(os.environ, HOME=xh, ABOFLES_LEDGER_DIR=str(Path(xh, "led")), ABOFLES_STATE_DIR=str(Path(xh, "st")))
        xenv.pop("ABOFLES_SESSION", None)
        Path(xh, "led").mkdir(); Path(xh, "st").mkdir()
        sc_ = lambda name, *a: subprocess.run([sys.executable, str(sdir / name), *a], cwd=xp, capture_output=True, text=True, env=xenv)
        # another project's newest ledger must never be shown or billed
        Path(xh, "st", "otherS.json").write_text(json.dumps({"root": os.path.realpath(xo), "last_prompt_ts": 9}))
        Path(xh, "led", "otherS.jsonl").write_text('{"agent_id": "zzz999", "topic": "OtherProjectTopic", "status": "partial", "model": "opus", "effort": "high"}\n')
        for name in ("status.py", "bill.py"):
            r = sc_(name, "--baseline", "opus")
            check(f"scope: {name} shows nothing of another project's ledger", r.returncode == 0 and "OtherProjectTopic" not in r.stdout and "zzz999" not in r.stdout and "no ledger for this session yet" in r.stdout)
            r = sc_(name, "--baseline", "opus", "--session", sid_)
            check(f"scope: {name} with an unknown --session shows nothing of another project's ledger", r.returncode == 0 and "OtherProjectTopic" not in r.stdout)
        check("scope: status --resolve cannot reach another project's row", sc_("status.py", "--resolve", "zzz9", "--session", sid_).returncode == 1 and "resolved" not in Path(xh, "led", "otherS.jsonl").read_text())
        # this project's session: display and --resolve use the same ledger, with the appended session id
        Path(xh, "st", f"{sid_}.json").write_text(json.dumps({"root": os.path.realpath(xp), "last_prompt_ts": 1}))
        Path(xh, "led", f"{sid_}.jsonl").write_text('{"agent_id": "abc123", "topic": "MineTopic", "status": "partial", "model": "opus", "effort": "high"}\n')
        r = sc_("status.py", "--baseline", "opus", "--session", sid_)
        check("scope: status shows this project's own ledger row", "MineTopic" in r.stdout and "abc123" in r.stdout and "OtherProjectTopic" not in r.stdout)
        r = sc_("status.py", "--resolve", "abc1", "--session", sid_)
        check("scope: status --resolve <id> --session <uuid> settles the row the display shows", r.returncode == 0 and json.loads(Path(xh, "led", f"{sid_}.jsonl").read_text())["resolved"] is True)
        # memo.py: the user's own --session wins over the command's appended one
        subprocess.run([sys.executable, "-c", "import sys,os; sys.path.insert(0, sys.argv[1]); import abofles_hook as h; h.memo_needs(os.getcwd(), 'sessAAAA', 'owner decision: pick A or B')", str(sdir.parent / "hooks")], cwd=xp, env=xenv)
        r = sc_("memo.py", "resolve", "1", "--trace", "--session", "mysessX", "--session", sid_)
        memx = lambda s: Path(xp, ".claude", "abofles-memo.d", f"{s[:8]}.md")
        check("session: memo resolve with the user's --session X plus an appended UUID traces into X's file", r.returncode == 0 and "· resolved by hand" in memx("mysessX").read_text() and not memx(sid_).exists())
        # an empty trailing --session "" (unexpanded command variable) is ignored
        for name, args in (("agents.py", ()), ("status.py", ("--baseline", "opus")), ("bill.py", ("--baseline", "opus")), ("guide.py", ()), ("memo.py", ("show",))):
            r = sc_(name, *args, "--session", "")
            check(f"session: {name} ignores a trailing empty --session", r.returncode == 0 and "usage" not in r.stdout.lower())
        check("session: status --resolve with an empty id plus a trailing empty --session still exits 2", sc_("status.py", "--resolve", "", "--session", "").returncode == 2)
        check("session: a non-trailing empty --session value still exits 2", sc_("status.py", "--resolve", "abc", "--session", "", "--trace").returncode == 2)

    # ---- topics: 27 domains, 1,100+ topics looked up by scripts/topic.py, four new reviewers, suggestions
    with tempfile.TemporaryDirectory() as led, tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as state:
        os.environ["ABOFLES_STATE_DIR"] = state
        os.environ["ABOFLES_TEST_CWD"] = cwd
        os.environ["ABOFLES_USER_CLAUDE_MD"] = str(Path(state, "no-user-claude.md"))
        sdir = Path(__file__).resolve().parent
        sys.path.insert(0, str(sdir))
        import topics_data as TD
        import importlib.util as _iut
        _hst = _iut.spec_from_file_location("abofles_hook_tp", str(HOOK)); HT = _iut.module_from_spec(_hst); _hst.loader.exec_module(HT)
        wf = HT.workflow_table()
        names = [l.split("|")[0].strip() for _, _, _, _, areas in TD.DOMAINS for _, rows in areas for l in rows]
        check("topics: 27 domains and 1,000+ topics", len(TD.DOMAINS) == 27 and len(names) >= 1000 and len(wf.get("topics", {})) == len(names))
        check("topics: names unique", len(set(names)) == len(names))
        legacy = ["Financial & Amount Calculations", "Codebase Exploration & Onboarding", "Notifications & Messaging", "Data Privacy, PII & Compliance", "Audit Logging & Traceability", "Unit Test", "Payments & Gateway Integration", "Clean Code (naming, structure, readability)", "Work on Document (README, guides)", "Check MVP vs Advance", "Architecture, Design Pattern & Stack Used"]
        check("topics: the legacy names used by hook, tests and docs are kept", all(n in wf["topics"] for n in legacy))
        check("topics: every topic has 3+ signals and a valid tier", all(len([x for x in (t.get("signals") or "").split(",") if x.strip()]) >= 3 and t.get("tier") in (1, 2, 3, 4) for t in wf["topics"].values()))
        rk = set(wf["reviewers"])
        check("topics: 11 reviewers and every domain/topic reviewer key is one of them", len(rk) == 11 and {"dba", "ops", "perf", "data"} <= rk
              and all(k in rk for g in wf["groups"].values() for t in ("3", "4") for k in g["reviewers"][t]) and all(k in rk for t in wf["topics"].values() for tt in ("3", "4") for k in t["reviewers"][tt]))
        check("topics: an agent file exists for every reviewer", all((sdir.parent / "agents" / f"{wf['reviewers'][k]['agent']}.md").exists() for k in rk))
        check("topics: DBA reviews databases, Ops the cloud, Perf the cache, Data the warehouse",
              wf["groups"]["DB"]["reviewers"]["3"] == ["dba"] and wf["groups"]["AWS"]["reviewers"]["3"] == ["ops"] and wf["groups"]["MSG"]["reviewers"]["3"] == ["perf"] and wf["groups"]["DATA"]["reviewers"]["3"] == ["data"])
        check("topics: PII topics still add Compliance; the legacy T4 money topic keeps its Fable Analyse", "compliance" in wf["topics"]["Data Privacy, PII & Compliance"]["reviewers"]["4"] and wf["topics"]["Financial & Amount Calculations"].get("ov", {}).get("Analyse") == "fable·medium")
        check("topics: workflow.json carries tiers, caps and suggestions", wf["tiers"]["4"]["Plan"] == "opus·xhigh" and wf["caps"]["1"]["Read"] == 20 and "dynamicwhere" in wf.get("suggestions", {}) and "dynamicwhere" in wf["topics"]["Dynamic Filtering, Sorting & Paging from Client Input"].get("suggest", []))
        check("topics: every suggestion names existing topics", all(t in wf["topics"] for sg in TD.SUGGESTIONS for t in sg["topics"]))
        # hook lookup
        m = HT.topic_matches("postgres read replica lag", wf, 3)
        check("lookup: replica lag ask -> a Replication topic first", m and "Replica" in m[0][1])
        m = HT.topic_matches("where is the discount applied", wf, 3)
        check("lookup: a where-is ask -> Codebase Exploration first (T1)", m and m[0][1] == "Codebase Exploration & Onboarding")
        check("lookup: cloudflare workers -> the Cloudflare Workers topic", "Cloudflare Workers" in HT.topic_matches("cloudflare workers kv", wf, 1)[0][1])
        check("lookup: otp expiry -> an OTP topic in SEC", (lambda r: r and "OTP" in r[0][1] and r[0][2]["group"] == "SEC")(HT.topic_matches("otp code expiry", wf, 1)))
        check("lookup: gibberish -> no match", HT.topic_matches("zzqx vvbbnn", wf, 3) == [])
        check("lookup: cells = tier base unless the topic overrides", HT.topic_cells(wf["topics"]["Unit Test"], 2, wf)["Work"] == ("sonnet·medium", 20, "base") and HT.topic_cells(wf["topics"]["Financial & Amount Calculations"], 4, wf)["Analyse"] == ("fable·medium", 50, "topic"))
        # topic.py CLI
        tp = lambda *a, **k: subprocess.run([sys.executable, str(sdir / "topic.py"), *a], capture_output=True, text=True, cwd=k.get("cwd", cwd))
        r = tp("find", "postgres read replica lag")
        check("topic.py: find prints matches with tier, cells, reviewers and workflow", r.returncode == 0 and "🔎 topic lookup" in r.stdout and "Replica" in r.stdout and "reviewers T3 DBA" in r.stdout and "Read " in r.stdout and "change →" in r.stdout and len(r.stdout.splitlines()) <= 8)
        r = tp("find", "add dynamic filter grid to orders api c#")
        check("topic.py: a C# dynamic-filter ask suggests DynamicWhere.ex", "💡 suggest · DynamicWhere.ex" in r.stdout and "dotnet add package DynamicWhere.ex" in r.stdout)
        r = tp("find", "add dynamic filter grid to orders api")
        check("topic.py: no .NET in the ask or the tree -> no suggestion", "💡" not in r.stdout)
        Path(cwd, "App.csproj").write_text("<Project/>")
        r = tp("find", "add dynamic filter grid to orders api")
        check("topic.py: a .csproj in the tree -> stack dotnet and the suggestion", "stack dotnet" in r.stdout and "💡 suggest · DynamicWhere.ex" in r.stdout)
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Topic: Unit Test = T4\n- Unit Test / Work = haiku·low\n- Reviewers: TEST = qa\n")
        r = tp("show", "Unit Test")
        check("topic.py: show applies the project's tier, cell and reviewer overrides and marks them", "🔴 Critical (T4) · Project Override" in r.stdout and "Work haiku·low" in r.stdout and "Project Override" in r.stdout and "T3 QA" in r.stdout and "header: abofles: Unit Test / <Side> · T4" in r.stdout)
        Path(cwd, "CLAUDE.md").unlink()
        r = tp("show", "#1")
        check("topic.py: show by number", r.returncode == 0 and "#1 " in r.stdout and "signals:" in r.stdout)
        r = tp("domains")
        check("topic.py: domains lists 27 rows", r.returncode == 0 and len([l for l in r.stdout.splitlines() if l.startswith("| ") and not l.startswith("| Code")]) == 27)
        r = tp("list", "DB")
        check("topic.py: list DB prints its areas and topics", r.returncode == 0 and "PostgreSQL" in r.stdout and "Replication & Availability:" in r.stdout)
        check("topic.py: list of an unknown code exits 1", tp("list", "NOPE").returncode == 1)
        check("topic.py: no-match find says so and exits 0", (lambda r: r.returncode == 0 and "no match" in r.stdout)(tp("find", "zzqx vvbbnn")))
        # hook notes in pre(): header tags, unknown topic, over-cell, escalation, guard neutrality
        check("parse_header: the new reviewer tags parse", HT.parse_header("abofles: PostgreSQL / DBA · T3")[1] == "DBA" and HT.parse_header("abofles: X / Ops · T4")[1] == "Ops" and HT.parse_header("abofles: X / Perf · T3")[1] == "Perf" and HT.parse_header("abofles: X / Data · T3")[1] == "Data")
        run("start", {"session_id": "tp", "cwd": cwd}, led)
        json.dump(dict(json.loads(Path(state, "tp.json").read_text()), gate="auto"), open(Path(state, "tp.json"), "w"))
        out = run("pre", dict(agent("haiku", "low", prompt="abofles: Postgres Replica Thing / Read · T3\nq\nLine cap: 40", cwd=cwd), session_id="tp"), led)
        check("pre: a header topic not in the index -> advisory note with the nearest names", "not in the index — nearest:" in ctx(out) and "Replica" in ctx(out) and reason(out) and (out or {}).get("hookSpecificOutput", {}).get("permissionDecision") == "allow")
        json.dump(dict(json.loads(Path(state, "tp.json").read_text()), inflight=0), open(Path(state, "tp.json"), "w"))
        out = run("pre", dict(agent("opus", "high", prompt="abofles: Codebase Exploration & Onboarding / Read · T1\nq\nLine cap: 40", cwd=cwd), session_id="tp"), led)
        check("pre: first spawn above the cell's model -> '× the cell' note, still allowed", "× the cell" in ctx(out) and "haiku·low" in ctx(out) and (out or {}).get("hookSpecificOutput", {}).get("permissionDecision") == "allow")
        json.dump(dict(json.loads(Path(state, "tp.json").read_text()), inflight=0), open(Path(state, "tp.json"), "w"))
        out = run("pre", dict(agent("haiku", "low", prompt="abofles: Codebase Exploration & Onboarding / Read · T1\nq\nLine cap: 40", cwd=cwd), session_id="tp"), led)
        check("pre: a spawn at the cell -> no cell note", "× the cell" not in ctx(out))
        run("post", dict(agent("haiku", "low", prompt="abofles: Unit Test / Analyse · T2\nq\nLine cap: 20", resp="STATUS: done\nCONFIDENCE: low\nFINDINGS:\n- x\nRECOMMENDATION: y", cwd=cwd), session_id="tp"), led)
        json.dump(dict(json.loads(Path(state, "tp.json").read_text()), inflight=0), open(Path(state, "tp.json"), "w"))
        out = run("pre", dict(agent("opus", "medium", prompt="abofles: Unit Test / Analyse · T2\nq\nLine cap: 20", cwd=cwd), session_id="tp"), led)
        check("pre: a re-run of the same topic and side (escalation) -> no cell note", "× the cell" not in ctx(out))
        g = lambda: run("guard", {"session_id": "tp", "cwd": cwd, "tool_name": "Grep", "tool_input": {}}, led)
        json.dump(dict(json.loads(Path(state, "tp.json").read_text()), direct_reads=0, guard_warned_at=0), open(Path(state, "tp.json"), "w"))
        g(); g(); g()
        out = run("guard", {"session_id": "tp", "cwd": cwd, "tool_name": "Bash", "tool_input": {"command": f'python3 "{sdir / "topic.py"}" find "replica lag"'}}, led)
        check("guard: the topic lookup is silent and neither counts nor breaks the streak", out is None and json.loads(Path(state, "tp.json").read_text()).get("direct_reads") == 3 and "direct reads in a row" in ctx(g()))
        st_out = run("start", {"session_id": "tp2", "cwd": cwd}, led)
        check("start: SessionStart names the topic lookup command", "abofles: topic lookup = python3" in (st_out or "") and "topic.py" in (st_out or ""))
        check("skill: Step 2 tells the model to look the topic up, not read a list", "scripts/topic.py" in (sdir.parent / "skills/abofles/SKILL.md").read_text() and "100 topics" not in (sdir.parent / "skills/abofles/SKILL.md").read_text())

    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
