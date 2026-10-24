#!/usr/bin/env python3
"""Unit tests for hooks/abofles_hook.py. Run: python3 scripts/test_hooks.py"""
import io
import json
import os
import re
import shutil
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
        os.environ["ABOFLES_CLAUDE_HOME"] = str(Path(state, "claude-home"))  # no ~/.claude/settings.json, no plugin cache: the abofles-guide mod counts as not installed (resume prints as before)
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
        _cmds = [h["command"] for ev in _hj["hooks"].values() for grp in ev for h in grp["hooks"] if h["type"] == "command" and "run.py" in h["command"]]
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
        check("memo: same open item not duplicated; journal newest first", mf.read_text().split("## Sessions")[0].count("ATTENTION: USD orders uncapped") == 1 and sf("mm").read_text().count("ATTENTION: USD orders uncapped") == 2 + 1 and mf.read_text().count("[ ]") == 2)  # Needs you once; two journal lines and the Now block's Left (no Next copy) in the session file
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
        # Resume = off: no automatic block (start, compact, away); /abofles:resume and the guide keep working
        for _v in ("off", "OFF"):
            Path(cwd, "CLAUDE.md").write_text(f"## abofles overrides\n- Resume = {_v}\n")
            _o1, _o2 = run("start", {"session_id": "mm", "cwd": cwd, "source": "startup"}, led) or "", run("start", {"session_id": "mm", "cwd": cwd, "source": "compact"}, led) or ""
            check(f"memo: Resume = {_v} -> SessionStart startup/compact print no resume block", "abofles RESUME" not in _o1 and "abofles RESUME" not in _o2 and "📍" not in _o1 + _o2)
            stj = json.loads(stf.read_text()); stj["last_activity"] = int(time.time()) - 11 * 60; stf.write_text(json.dumps(stj))
            check(f"memo: Resume = {_v} -> prompt after 11 min away prints no resume block", "RESUME" not in ctx(run("prompt", {"session_id": "mm", "cwd": cwd}, led)))
            check(f"memo: Resume = {_v} -> memo.py show still prints the block", "📍 **Resume**" in memo("show"))
            _rs = _H0.resume_scope(cwd)
            check(f"memo: Resume = {_v} -> resume_scope ignores it", _rs[0] in ("project", "session", "all") and _rs[1] != "override")
        # aliases none / 0 and every SessionStart source: no automatic block
        for _v in ("off", "none", "0"):
            Path(cwd, "CLAUDE.md").write_text(f"## abofles overrides\n- Resume = {_v}\n")
            _outs = [run("start", {"session_id": "mm", "cwd": cwd, "source": s}, led) or "" for s in ("startup", "compact", "resume", "clear")]
            check(f"memo: Resume = {_v} -> no abofles RESUME at SessionStart startup/compact/resume/clear", all("abofles RESUME" not in o for o in _outs))
        # resume_off unit: aliases and case/space tolerated, near-misses and prose are not
        for _v, _want in (("off", True), ("None", True), (" 0 ", True), ("offf", False), ("project", False)):
            Path(cwd, "CLAUDE.md").write_text(f"## abofles overrides\n- Resume = {_v}\n")
            check(f"memo: resume_off({_v!r}) is {_want}", _H0.resume_off(cwd) is _want)
        Path(cwd, "CLAUDE.md").write_text("Notes\n- Resume = off\n\n## abofles overrides\n- Break = 30\n")
        check("memo: `- Resume = off` outside the overrides block is prose -> resume_off False", _H0.resume_off(cwd) is False)
        # location: <project>/.claude/CLAUDE.md and the user-level file both turn it off
        Path(cwd, "CLAUDE.md").unlink()
        _loc = {"project .claude/CLAUDE.md": Path(cwd, ".claude", "CLAUDE.md"), "user-level file": Path(_H0.USER_CLAUDE_MD)}
        for _name, _lp in _loc.items():
            _lp.parent.mkdir(parents=True, exist_ok=True)
            _lp.write_text("## abofles overrides\n- Resume = off\n")
            check(f"memo: Resume = off in the {_name} -> resume_off True", _H0.resume_off(cwd) is True)
            check(f"memo: Resume = off in the {_name} -> SessionStart(compact) prints no resume block", "abofles RESUME" not in (run("start", {"session_id": "mm", "cwd": cwd, "source": "compact"}, led) or ""))
            _lp.unlink()
        # memo.py show --scope all still prints the block under Resume = off
        Path(cwd, "CLAUDE.md").write_text("## abofles overrides\n- Resume = off\n")
        check("memo: Resume = off -> memo.py show --scope all still prints the block", "📍 **Resume**" in memo("show", "--scope", "all"))
        Path(cwd, "CLAUDE.md").unlink()
        check("memo: removing `Resume = off` restores SessionStart(compact) block", "RESUME (context was just compacted)" in (run("start", {"session_id": "mm", "cwd": cwd, "source": "compact"}, led) or ""))
        stj = json.loads(stf.read_text()); stj["last_activity"] = int(time.time()) - 11 * 60; stf.write_text(json.dumps(stj))
        check("memo: removing `Resume = off` restores the away block", "abofles RESUME (the user was away 11 min)" in ctx(run("prompt", {"session_id": "mm", "cwd": cwd}, led)))
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
        stf = sf("rt"); old = re.sub(r"Written   \d{4}-\d\d-\d\d \d\d:\d\d", time.strftime("Written   %Y-01-01 00:00"), stf.read_text()); stf.write_text(old)  # a regex, not this minute: the hook may have written it a minute ago  # a receipt rewrites Now itself: age it after the receipt
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
        check("guide: an open FAIL fill makes Claude re-check first and resolve only with the traced evidence",
              "re-check it first" in fi.get("fill", "") and "re-checked: <evidence>" in fi["fill"] and "say so and resolve it" not in fi["fill"])
        check("guide: the recheck command is the portable scripts/py form, not an absolute interpreter path",
              "scripts/py" in fi.get("recheck", "") and sys.executable not in fi["recheck"] and " -X utf8 " not in fi["recheck"])
        check("guide: an open FAIL has no blind resolve, a recheck prompt with the traced resolve command",
              fi.get("recheck", "").startswith("abofles: re-check the open FAIL on Unit Test (agent vf1abc)") and "--resolve vf1abc --session gu --trace" in fi["recheck"] and "re-checked: <evidence>" in fi["recheck"])
        out = run("post", dict(agent("sonnet", "high", "abofles:abofles-verifier", prompt="abofles: Unit Test / Verify · T2\nq\nLine cap: 20", resp="STATUS: done\nCONFIDENCE: high\nVERDICT: PASS\nEVIDENCE:\n- tests: 13 passed\nISSUES: none", cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: a later PASS on the topic closes the FAIL", "🔴 open FAIL" not in ctx(out))
        time.sleep(1.1)  # rows of the task are those after its start second
        out = run("post", dict(agent("haiku", "low", resp={"agentId": "es1abc", "content": "STATUS: partial\nCONFIDENCE: medium\nFACTS:\n- src/a.cs:1 — x\nGAPS: the Q2 method body was not read"}, cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: an unescalated partial names the next setting", "🟡 escalate · Read Haiku 5.5 · Low came back partial/medium — re-run that subtask at Haiku 5.5 · Medium" in ctx(out))
        yi = next((i for i in (json.loads(Path(state, "gu.json").read_text()).get("guide") or {}).get("items", []) if i["p"] == "🟡"), {})
        STx = Path(__file__).resolve().parent / "status.py"
        check("guide: an escalate item has no resolve/unresolve argv, its recheck carries the traced resolve command",
              yi.get("resolve") is None and yi.get("unresolve") is None and "--resolve es1abc --session gu" in (yi.get("recheck") or "") and "re-checked: <evidence>" in yi["recheck"]
              and "If you show evidence instead that the reply is sound, resolve it with `" in yi["recheck"] and yi["recheck"].startswith("abofles: the Read agent")
              and "--resolve es1abc --session gu" in yi["fill"] and yi["recheck"].index("re-run that subtask") < yi["recheck"].index("If you show evidence"))
        check("guide: the FAIL fill names the exact resolve command, not a bare --trace fragment", "--resolve vf1abc --session gu --trace" in fi["fill"] and "with `--trace" not in fi["fill"])
        check("guide: no item fill (open FAIL, escalate) lets Claude resolve on a bare claim",
              all("say so and resolve it" not in (i.get("fill") or "") for i in (json.loads(Path(state, "gu.json").read_text()).get("guide") or {}).get("items", []))
              and "re-checked: <evidence>" in yi.get("fill", "") and "sound, resolve it only with" in yi["fill"])
        ES_NOTE = "Read Haiku 5.5 · Low came back partial/medium"
        ES_RES = [sys.executable, "-X", "utf8", str(STx), "--resolve", "es1abc", "--session", "gu", "--trace", ES_NOTE]
        ES_UN = [sys.executable, "-X", "utf8", str(STx), "--unresolve", "es1abc", "--session", "gu", "--trace", ES_NOTE]
        pin("gu")
        genv = dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state)
        rr = _sp.run(ES_RES, cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: status --resolve --trace settles the row", rr.returncode == 0 and "resolved 1 entry" in rr.stdout)
        check("trace: one resolved-by-hand line in the Journal with the session tag", len([l for l in sf("gu").read_text().splitlines() if "· resolved by hand: escalate · Unit Test · Read " in l and l.count("escalate") == 1]) == 1)
        check("trace: the resume block does not list a hand-trace under last and counts no receipt for it", "resolved by hand: escalate" not in memo("show").split("- `last`")[-1] and "- `since` → 1 receipt" not in memo("show"))
        gout = _sp.run([sys.executable, str(GU := Path(__file__).resolve().parent / "guide.py"), "--all"], cwd=cwd, capture_output=True, text=True, env=genv).stdout
        check("trace: a resolved escalate leaves the guide", "🟡 escalate" not in gout)
        ur = _sp.run(ES_UN, cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: status --unresolve reopens the row", ur.returncode == 0 and "reopened 1 entry" in ur.stdout)
        gout = _sp.run([sys.executable, str(GU), "--all"], cwd=cwd, capture_output=True, text=True, env=genv).stdout
        check("trace: the guide shows the escalate again", "🟡 escalate" in gout)
        ur2 = _sp.run(ES_UN, cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: unresolve of an open row exits 3", ur2.returncode == 3 and "not resolved" in ur2.stdout)
        ur3 = _sp.run([sys.executable, str(STx), "--unresolve", "nope", "--session", "gu"], cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: unresolve miss exits 1", ur3.returncode == 1)
        _sp.run(ES_RES[:-2] + ["--trace"], cwd=cwd, capture_output=True, text=True, env=genv)
        _sp.run(ES_UN + ["--trace"], cwd=cwd, capture_output=True, text=True, env=genv)
        check("trace: --unresolve --trace writes reopened by hand", "· reopened by hand: escalate · Unit Test" in sf("gu").read_text())
        _sp.run(ES_UN, cwd=cwd, capture_output=True, text=True, env=genv)
        out = run("receipt", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "🧾 **3 Spawns · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → y\n- `open` → owner decision: cap per currency?"}, led)
        run("start", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "source": "resume"}, led)
        blk = run("start", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "source": "resume"}, led)
        check("guide: resume block carries the guide line, owner decision first after the task closed", "- `guide` → 🧭 🟠 " in blk and "owner decision" in blk)
        GU = Path(__file__).resolve().parent / "guide.py"
        gout = _sp.run([sys.executable, str(GU), "--all"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led)).stdout
        check("guide: CLI --all lists the ladder", gout.startswith("🟠 ") and "owner decision" in gout)
        od = ((json.loads(Path(state, "gu.json").read_text()).get("guide") or {}).get("items") or [{}])[0]
        check("guide: an owner decision item asks the user after judging; no resolve argv, a recheck with the traced memo.py command and AskUserQuestion",
              od.get("p") == "🟠" and od.get("fill", "").startswith("abofles: owner decision 1 is open: ") and od["fill"].endswith("Judge it first, then ask me with AskUserQuestion.")
              and od.get("resolve") is None and od.get("unresolve") is None
              and all(x in (od.get("recheck") or "") for x in ("resolve 1 --session gu", "memo.py", "re-checked: <evidence>", "--trace \"user answered: <answer>\"", "AskUserQuestion", "Re-check it first")))
        MEMOPY = str(Path(__file__).resolve().parent / "memo.py")
        OD_RES = [sys.executable, "-X", "utf8", MEMOPY, "resolve", "1", "settled in the test", "--trace", "--session", "gu"]
        OD_UN = [sys.executable, "-X", "utf8", MEMOPY, "reopen", "1", "--trace", "--session", "gu"]
        rout = _sp.run(OD_RES, cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state)).stdout
        check("guide: running the owner decision's resolve command ticks it in the memo", rout.startswith("resolved:") and "1. [x]" in mf.read_text())
        check("trace: memo resolve --trace journals the owner decision", any("resolved by hand: owner decision 1: " in l and "(s:" not in l.split("by hand:")[1] for l in sf("gu").read_text().splitlines()))
        rop = _sp.run(OD_UN, cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state))
        check("memo reopen: item is open again and the resolve note is gone", rop.returncode == 0 and any(l.startswith("1. [ ] ") and "→ resolved" not in l for l in mf.read_text().splitlines()))
        rop = _sp.run(OD_UN, cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state))
        check("memo reopen: an open item exits 3", rop.returncode == 3)
        _sp.run(OD_RES, cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state))
        out = run("post", dict(agent("sonnet", "high", "abofles:abofles-verifier", prompt="abofles: Unit Test / Verify · T2\nq\nLine cap: 20", resp="STATUS: done\nCONFIDENCE: high\nVERDICT: FAIL\nEVIDENCE:\n- tests: 1 failed\nISSUES:\n- src/b.cs:3 — null", cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: a FAIL of the open task is shown", "🔴 open FAIL · Unit Test" in ctx(out))
        time.sleep(1.1)  # the receipt closes the task in a later second than its rows
        run("receipt", {"session_id": "gu", "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → fixed src/b.cs in the main session, test green\n- `check` → y"}, led)
        time.sleep(1.1)
        out = run("post", dict(agent("haiku", "low", resp=good, cwd=cwd), session_id="gu", transcript_path=str(tr)), led)
        check("guide: a FAIL of a task already closed by its receipt is not carried into the next task", "🔴 open FAIL" not in ctx(out))
        STp = Path(__file__).resolve().parent / "status.py"
        sout = _sp.run([sys.executable, str(STp), "--resolve", "nope", "--trace", "re-checked: t"], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state)).stdout
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
        RC1 = "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → capped the surcharge in AqsatiRules.cs\n- `why` → money rule\n- `check` → `dotnet test` → 13 passed\n- `open` →\n  - wire the FE badge\n  - update the docs page\n- `next` → wire the FE badge"
        # 1. memo Now rewritten by the receipt
        pa = tempfile.mkdtemp(); sA = "autosess1"
        run("start", {"session_id": sA, "cwd": pa}, led)
        H.memo_now(pa, "Task      old task\nDone      old done\nLeft      old left\nDecisions keep: tables are printed above the box\nNext      old next\nVerify    old verify\nTree      M old.cs", sA)
        run("receipt", {"session_id": sA, "cwd": pa, "stop_hook_active": False, "last_assistant_message": RC1}, led)
        nowA = H.sess_read(pa, sA)["Now"]
        check("now auto: a receipt rewrites this session's Now (between tasks, Done, Left lines, Next = the receipt's own next, Verify)",
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
        # Next follows the receipt's own `next`; sub-bullets of `open` are single Left items; the 🧭 guide line is not copied
        RCH = "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → ok\n- `open` →\n  - QA did not test X, Y one by one; the full suite covers them\n  - update the docs page"
        pn = tempfile.mkdtemp(); sN = "nextsess1"
        run("start", {"session_id": sN, "cwd": pn}, led)
        run("receipt", {"session_id": sN, "cwd": pn, "stop_hook_active": False, "last_assistant_message": RCH + "\n- `next` → 🧭 🟠 1 owner decision open — ask (judge first): docs page"}, led)
        nowN = H.sess_read(pn, sN)["Now"]; blkN = H.resume_block(pn, session_id=sN)
        check("now auto: next = a 🧭 guide line -> no Next line, both open items kept as Left", "Next" not in nowN and "Left      QA did not test X, Y one by one; the full suite covers them\nLeft      update the docs page" in nowN)
        check("now auto: ... resume shows no `next` line, exactly 2 left items with the first intact, and the guide line is not duplicated",
              "- `next`" not in blkN and "- `left` →\n  - QA did not test X, Y one by one; the full suite covers them\n  - update the docs page" in blkN)
        nx_ = next((i for i in gitems(sN) if i.get("id") == "next"), None)
        check("now auto: ... and the band's ✅ item does not crash or go empty without a Next", nx_ is None or nx_.get("text"))
        check("now auto: ... no Next but Left items -> the ✅ item names the first left item, not 'pick the next ticket'",
              nx_ is None or nx_.get("text") == "no decision open — left from the memo: QA did not test X, Y one by one; the full suite covers them")
        # a one-line guide `next` is split at " · " only after the guide-line check: the pieces after the 🧭 head are guide items, not Next
        pn2 = tempfile.mkdtemp(); sN2 = "nextsess2"
        run("start", {"session_id": sN2, "cwd": pn2}, led)
        run("receipt", {"session_id": sN2, "cwd": pn2, "stop_hook_active": False, "last_assistant_message": RCH + "\n- `next` → 🧭 🟠 1 owner decision open — ask (judge first): docs page · 🟡 escalate · Work agent partial · 💰 agent budget 2 left"}, led)
        nowN2 = H.sess_read(pn2, sN2)["Now"]
        check("now auto: a one-line next that starts with 🧭 and has ` · ` pieces (🟡 escalate, 💰 budget) -> no Next line at all", "Next" not in nowN2 and "escalate" not in nowN2 and "agent budget" not in nowN2)
        run("receipt", {"session_id": sN2, "cwd": pn2, "stop_hook_active": False, "last_assistant_message": RCH + "\n- `next` → run the full suite · then docs"}, led)
        nowN3 = H.sess_read(pn2, sN2)["Now"]
        check("now auto: a one-line next without 🧭 is still split into Next items", "Next      run the full suite" in nowN3 and "Next      then docs" in nowN3)
        run("receipt", {"session_id": sN, "cwd": pn, "stop_hook_active": False, "last_assistant_message": RCH + "\n- `next` → none — wait for QA"}, led)
        check("now auto: next = none... -> no Next line while items are left", "Next" not in H.sess_read(pn, sN)["Now"])
        run("receipt", {"session_id": sN, "cwd": pn, "stop_hook_active": False, "last_assistant_message": RCH + "\n- `next` → <next step>"}, led)
        check("now auto: next = a <placeholder> -> no Next line", "Next" not in H.sess_read(pn, sN)["Now"])
        run("receipt", {"session_id": sN, "cwd": pn, "stop_hook_active": False, "last_assistant_message": RCH + "\n- `next` → wire the FE badge"}, led)
        blkN = H.resume_block(pn, session_id=sN)
        nx_ = next((i for i in gitems(sN) if i.get("id") == "next"), {})
        check("now auto: next = real text -> Next, resume `next` line, and nothing is copied from the first open item",
              "Next      wire the FE badge" in H.sess_read(pn, sN)["Now"] and "- `next` → wire the FE badge" in blkN)
        run("receipt", {"session_id": sN, "cwd": pn, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → ok\n- `open` → a; b"}, led)
        check("now auto: a one-line open `a; b` (no sub-bullets) is still two Left items", "Left      a\nLeft      b" in H.sess_read(pn, sN)["Now"])
        # a sub-bullet of `open` is one Needs-you item; a one-line open is still split; several `next` sub-bullets are several Next lines
        RCO = "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → ok\n- `open` →\n  - ATTENTION: bad thing; owner decision: pick?"
        pq = tempfile.mkdtemp(); sQ = "needsub1"
        run("start", {"session_id": sQ, "cwd": pq}, led)
        run("receipt", {"session_id": sQ, "cwd": pq, "stop_hook_active": False, "last_assistant_message": RCO}, led)
        nq = [l for l in H.memo_read(pq)["Needs you"].splitlines() if l.strip()]
        check("needs: one `open` sub-bullet with `; ` is one Needs-you item holding both halves", len(nq) == 1 and "ATTENTION: bad thing; owner decision: pick?" in nq[0])
        # NEEDS_RE: a word merely mentioned in a note is not a Needs-you item; a tag, an owner phrase or a question is
        _nr = {"Needs-you item 2 is out of date now that Confirm is gone, so it stays open for you.": False,
               "I resolved this session's FAIL, escalate and partial-Read follow-ups with evidence.": False,
               "verifier FAIL fixed in main session": False, "nothing is committed or shipped": False,
               "PR 1 needs your approval.": True, "ATTENTION: USD orders uncapped": True, "owner decision: cap per currency?": True,
               "open FAIL · topic: fix it": True, "FAIL: criterion 5": True, "VERDICT: FAIL on docs": True,
               "Should the key include the tenant?": True, "the owner must decide the window": True, "Posting it needs your OK.": True}
        check("needs: NEEDS_RE flags tags, owner phrases and questions, not a mentioned word (Confirm, a resolved FAIL)",
              all(bool(H.NEEDS_RE.search(k)) == v for k, v in _nr.items()))
        pq2 = tempfile.mkdtemp(); sQ2 = "needsub2"
        run("start", {"session_id": sQ2, "cwd": pq2}, led)
        run("receipt", {"session_id": sQ2, "cwd": pq2, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → ok\n- `open` → ATTENTION: x; ATTENTION: y"}, led)
        nq2 = [l for l in H.memo_read(pq2)["Needs you"].splitlines() if l.strip()]
        check("needs: a one-line open `ATTENTION: x; ATTENTION: y` is still two Needs-you items", len(nq2) == 2 and "ATTENTION: x" in nq2[0] and "ATTENTION: y" in nq2[1])
        pq3 = tempfile.mkdtemp(); sQ3 = "nextsub1"
        run("start", {"session_id": sQ3, "cwd": pq3}, led)
        run("receipt", {"session_id": sQ3, "cwd": pq3, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → ok\n- `open` → none\n- `next` →\n  - wire the FE badge\n  - update the docs page"}, led)
        nowQ = H.sess_read(pq3, sQ3)["Now"]; blkQ = H.resume_block(pq3, session_id=sQ3)
        nx_ = next((i for i in gitems(sQ3) if i.get("id") == "next"), {})
        check("next: two `next` sub-bullets -> two Next lines in Now", "Next      wire the FE badge\nNext      update the docs page" in nowQ and "wire the FE badge; update" not in nowQ)
        check("next: resume shows `next` with 2 sub-bullets; the guide ✅ item uses the first", "- `next` →\n  - wire the FE badge\n  - update the docs page" in blkQ and "next from the memo: wire the FE badge" in nx_.get("text", "") and "docs page" not in nx_.get("text", ""))
        run("receipt", {"session_id": sN, "cwd": pn, "stop_hook_active": False, "last_assistant_message": "🧾 **1 Spawn · 1 u · Saved 1%** vs Opus 5.5\n- `done` → x\n- `check` → ok\n- `open` → none\n- `next` → 🧭 something"}, led)
        check("now auto: open none + a guide-line next -> ready for the next task", "Next      none — ready for the next task" in H.sess_read(pn, sN)["Now"] and "Left" not in H.sess_read(pn, sN)["Now"])
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
        stb = H.session_memo_path(pb, sB); stb.write_text(re.sub(r"Written   \d{4}-\d\d-\d\d \d\d:\d\d", "Written   2020-01-01 00:00", stb.read_text()))
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
        check("guide: an escalate with no higher setting still has a recheck (stop and report, then the traced resolve)", "stop and report" in (e3.get("recheck") or "") and "--resolve wkx111 --session" in e3["recheck"] and "re-checked: <evidence>" in e3["recheck"] and e3.get("resolve") is None)
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
        time.sleep(1.1)
        run("post", iv(agent("haiku", "low", resp={"agentId": "esx111", "content": "STATUS: partial\nCONFIDENCE: low\nFACTS:\n- src/a.cs:1 — x\nGAPS: not read"}, cwd=pi_)), led)
        run("post", iv(jp(2, ask)), led)
        run("post", iv(agent("haiku", "low", resp={"status": "async_launched", "agentId": "bgx111", "prompt": "p", "description": "t"}, cwd=pi_)), led)
        run("prompt", {"session_id": sI, "cwd": pi_, "transcript_path": str(tri)}, led)
        iditems = {i["id"]: i for i in gitems(sI)}
        check("guide ids: fail:<agent>, ask, dec:<n>, bg:<agent>, ctx:<mark>, budget on their items", {"fail:vfx111", "ask", "dec:1", "bg:bgx111", "ctx:500", "budget"} <= set(iditems))
        check("guide ids: the owner-decision item has no resolve/reopen argv, its recheck carries `resolve 1 --session <sid>`",
              iditems.get("dec:1", {}).get("resolve") is None and iditems.get("dec:1", {}).get("unresolve") is None
              and f"resolve 1 --session {sI}" in (iditems.get("dec:1", {}).get("recheck") or "") and "AskUserQuestion" in iditems["dec:1"]["recheck"])
        # 13. the band never settles an item: every guide item has resolve/unresolve None; Claude's resolve is traced and undoable
        po_ = tempfile.mkdtemp(); run("start", {"session_id": "idsess2", "cwd": po_}, led); H.memo_needs(po_, "idsess2", "owner decision: elsewhere?")
        allst = dict(gstate(sI), review_missing={"names": ["qa"], "tier": 3, "topic": "Ids Topic", "ts": int(time.time())}, receipt_owed=True)
        led0_, H.LEDGER_DIR = H.LEDGER_DIR, Path(led)  # H reads the ledger the hook subprocesses wrote
        allit = H.guide_entries(pi_, allst, sI, scope="all")
        allids = {i["id"] for i in allit}
        check("guide: the fixture raises fail, esc, dec, review, receipt and dec:elsewhere items", {"fail:vfx111", "esc:esx111", "dec:1", "review", "receipt", "dec:elsewhere"} <= allids)
        check("guide: every item of the ladder has resolve and unresolve None", allit and all(i.get("resolve") is None and i.get("unresolve") is None and "resolve" in i and "unresolve" in i for i in allit))
        check("guide: the fail, esc and dec items carry a recheck, the others none", all(bool(i.get("recheck")) == (i["id"].split(":")[0] in ("fail", "esc") or i["id"] == "dec:1") for i in allit))
        sec_ = H.memo_read(pi_); sec_["Needs you"] = "- [ ] a free-text line with no number"; H.memo_write(pi_, sec_, sI)
        dn = next(i for i in H.guide_entries(pi_, gstate(sI), sI, scope="project") if i["id"] == "dec:?")
        H.LEDGER_DIR = led0_
        check("guide: an owner decision without a number has no recheck", dn.get("recheck") is None and dn.get("resolve") is None and dn.get("unresolve") is None)
        # Claude's resolve: the evidence in the Journal, Undo in the guide state until the turn after the next Stop
        pl_ = tempfile.mkdtemp(); sL = "lres1"
        run("start", {"session_id": sL, "cwd": pl_}, led)
        H.memo_needs(pl_, sL, "owner decision: pick A or B?")
        run("prompt", {"session_id": sL, "cwd": pl_, "prompt": "go"}, led)
        lenv = dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state)
        lmemo = lambda *a: _sp.run([sys.executable, "-X", "utf8", MEMOPY, *a, "--session", sL], cwd=pl_, capture_output=True, text=True, env=lenv)
        lres = lambda: (gstate(sL).get("guide") or {}).get("last_resolved")
        check("guide: no last_resolved before a resolve", lres() is None and "last_resolved" in (gstate(sL).get("guide") or {}))
        time.sleep(0.05)
        lr1 = lmemo("resolve", "1", "re-checked: X", "--trace")
        check("memo resolve --trace: the note lands in the Journal line as the evidence", lr1.returncode == 0 and any("resolved by hand: owner decision 1: " in l and l.endswith(" · re-checked: X") for l in H.sess_read(pl_, sL)["Journal"].splitlines()))
        lr = lres() or {}
        check("memo resolve: the guide state keeps last_resolved with the item text and the reopen argv",
              lr.get("text", "").startswith("owner decision 1: ") and "pick A or B" in lr["text"] and len(lr["text"]) <= 100 and isinstance(lr.get("ts"), float)
              and lr.get("unresolve") == ["bash", str(Path(MEMOPY).parent / "py").replace("\\", "/"), MEMOPY.replace("\\", "/"), "reopen", "1", "--trace", "--session", sL] and all(not i["id"].startswith("dec:") for i in gitems(sL)))
        ur_ = _sp.run(lr.get("unresolve") or ["false"], cwd=pl_, capture_output=True, text=True, env=lenv)
        check("memo Undo argv runs through the launcher from the project root and reopens the item", ur_.returncode == 0 and ur_.stdout.startswith("reopened:") and "1. [ ] " in H.memo_path(pl_).read_text() and lres() is None)
        lmemo("resolve", "1", "re-checked: X", "--trace")  # back to the resolved state the checks below expect
        lr = lres() or {}
        run("receipt", {"session_id": sL, "cwd": pl_, "stop_hook_active": False, "last_assistant_message": "done"}, led)
        check("last_resolved survives the Stop of the same turn", (lres() or {}).get("unresolve") == lr.get("unresolve"))
        time.sleep(0.05)
        run("prompt", {"session_id": sL, "cwd": pl_, "prompt": "next"}, led)
        check("last_resolved is still there during the next turn", lres() is not None)
        run("receipt", {"session_id": sL, "cwd": pl_, "stop_hook_active": False, "last_assistant_message": "done"}, led)
        check("last_resolved is gone after the next turn's Stop", lres() is None and "last_resolved" not in gstate(sL))
        lmemo("reopen", "1")
        ne_ = lmemo("resolve", "1")
        check("memo resolve without a note exits 2 with the evidence message and leaves the item open", ne_.returncode == 2 and "abofles: resolve needs evidence — add a note, e.g. --trace \"re-checked: <evidence>\" or \"user answered: <answer>\"" in ne_.stdout
              and "1. [ ] " in H.memo_path(pl_).read_text())
        nw_ = lmemo("resolve", "1", "   ", "--trace")
        check("memo resolve with a whitespace note exits 2 too, item still open", nw_.returncode == 2 and "resolve needs evidence" in nw_.stdout and "1. [ ] " in H.memo_path(pl_).read_text())
        lmemo("resolve", "1", "again")
        check("memo resolve without --trace still records last_resolved", lres() is not None)
        lo = lmemo("reopen", "1", "--trace")
        check("memo reopen clears last_resolved", lo.returncode == 0 and lres() is None)
        sL2 = "lres2"; run("start", {"session_id": sL2, "cwd": pl_}, led)
        run("post", dict(agent("haiku", "low", "abofles:abofles-reader", resp={"agentId": "lrx111", "content": "STATUS: partial\nCONFIDENCE: medium\nFACTS:\n- src/a.cs:1 — x\nGAPS: not read"}, cwd=pl_), session_id=sL2), led)
        lst = lambda *a: _sp.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve().parent / "status.py"), *a, "--session", sL2], cwd=pl_, capture_output=True, text=True, env=lenv)
        ls1 = lst("--resolve", "lrx111", "--trace", "re-checked: sound")
        lr2 = (gstate(sL2).get("guide") or {}).get("last_resolved") or {}
        check("status --resolve: last_resolved holds the --unresolve argv", ls1.returncode == 0 and lr2.get("unresolve", [])[:1] == ["bash"] and lr2["unresolve"][1].endswith("/scripts/py") and lr2["unresolve"][2:7] == [str(Path(__file__).resolve().parent / "status.py").replace("\\", "/"), "--unresolve", "lrx111", "--session", sL2] and lr2.get("text"))
        us_ = _sp.run(lr2["unresolve"], cwd=pl_, capture_output=True, text=True, env=lenv)
        check("status Undo argv runs through the launcher and reopens the row", us_.returncode == 0 and "reopened 1 entry" in us_.stdout)
        ns_, nt_ = lst("--resolve", "lrx111"), lst("--resolve", "lrx111", "--trace", "  ")
        check("status --resolve without trace text exits 2 with the evidence message, the row stays open",
              ns_.returncode == 2 and nt_.returncode == 2 and ns_.stdout.startswith("abofles: resolve needs evidence") and "user answered: <answer>" in ns_.stdout
              and not any(json.loads(l).get("resolved") for l in (Path(led) / f"{sL2}.jsonl").read_text().splitlines() if l.strip()))
        lst("--resolve", "lrx111", "--trace", "re-checked: sound")
        ls2 = lst("--unresolve", "lrx111")
        check("status --unresolve clears last_resolved", ls2.returncode == 0 and "last_resolved" not in gstate(sL2) and (gstate(sL2).get("guide") or {}).get("last_resolved") is None)
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

        # a stale-pending fallback must not close an agent that is still thinking; a stale close is re-graded by the real SubagentStop
        def sk_msg(kind, text="", sr="absent", mid="m", tok=0):
            usage = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": tok, "output_tokens": 0}
            if kind == "tool_result": return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
            if kind == "attachment": return {"type": "attachment", "attachment": {"type": "total_tokens_reminder", "text": "<total_tokens>1</total_tokens>"}}
            parts = {"tool_use": [{"type": "text", "text": text}, {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}] if text else [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
                     "thinking": [{"type": "thinking", "thinking": ""}], "text": [{"type": "text", "text": text}]}[kind]
            m = {"id": mid, "model": "claude-haiku-5-5", "usage": usage, "content": parts}
            if sr != "absent": m["stop_reason"] = sr
            return {"type": "assistant", "message": m}
        def sk_agent(sid_, aid, entries, age, **post_kw):
            run("start", {"session_id": sid_, "cwd": cwd, "transcript_path": str(tr)}, led)
            run("post", dict(post_kw.pop("pi_", pi), session_id=sid_, transcript_path=str(tr), tool_response=launch_(aid)), led)
            f = Path(cwd, sid_, "subagents", f"agent-{aid}.jsonl"); f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("".join(json.dumps(e) + "\n" for e in entries))
            os.utime(f, (time.time() - age, time.time() - age))
            return f
        sk_stop = lambda sid_, text="all done": run("receipt", {"session_id": sid_, "cwd": cwd, "transcript_path": str(tr), "stop_hook_active": False, "last_assistant_message": text}, led)
        sk_row = lambda sid_, aid: next(r for r in ledrows(sid_) if r.get("agent_id") == aid)
        out_ = None
        sk_agent("sk", "k1", [sk_msg("tool_use", "reading", "tool_use", "a"), sk_msg("tool_result"), sk_msg("attachment")], 200)
        out_ = sk_stop("sk")
        check("stale: an idle transcript ending in tool_use / tool_result / attachment is not closed (the agent is mid-work), no 'no receipt' nudge", sk_row("sk", "k1").get("status") == "pending" and "no receipt" not in json.dumps(out_ or {}))
        sk_agent("sk2", "k2", [sk_msg("text", "partial", "tool_use", "a"), sk_msg("thinking", sr=None, mid="b")], 200)
        sk_stop("sk2")
        check("stale: an idle transcript whose last entry is thinking-only (stop_reason None) stays pending", sk_row("sk2", "k2").get("status") == "pending")
        tfm_ = Path(cwd, "tf-malformed.jsonl"); tfm_.write_text('{"type":"assistant","message":"x"}\n')
        check("stale: a transcript entry whose message is not an object is not a finished turn and does not raise", H.turn_finished(tfm_) is False)
        sk_agent("sk2b", "k2b", [sk_msg("thinking", sr="end_turn", mid="a")], 200)
        sk_stop("sk2b")
        check("stale: an idle transcript whose last entry is thinking-only with stop_reason end_turn is not finished, stays pending", sk_row("sk2b", "k2b").get("status") == "pending")
        sk_agent("sk3", "k3", [sk_msg("text", good, "end_turn", "a", 50_000)], 200)
        sk_stop("sk3")
        r3_ = sk_row("sk3", "k3")
        check("stale: an idle transcript ending in an end_turn report closes the row, closed_by=stale", r3_.get("status") == "done" and r3_.get("closed_by") == "stale")
        sk_agent("sk4", "k4", [sk_msg("text", "partial notes", "tool_use", "a"), sk_msg("tool_result")], H.LOST_MIN * 60 + 10)
        sk_stop("sk4")
        r4_ = sk_row("sk4", "k4")
        check("stale: an unfinished transcript silent past LOST_MIN is closed with an 'unfinished' note, closed_by=stale", r4_.get("status") != "pending" and r4_.get("closed_by") == "stale" and any("unfinished" in w for w in r4_.get("warnings") or []))
        check("stale: the unfinished-timeout close without a graded status is blocked / low", r4_.get("status") == "blocked" and r4_.get("confidence") == "low")
        f5_ = sk_agent("sk5", "k5", [sk_msg("text", "Understood.", "end_turn", "a", 50_000)], 200)
        sk_stop("sk5")
        r5_ = sk_row("sk5", "k5"); t5_ = gstate("sk5").get("task_tokens", 0)
        with open(f5_, "a") as fh_: fh_.write(json.dumps(sk_msg("text", good, "end_turn", "b", 30_000)) + "\n")  # cumulative usage: 80k in total
        run("stop", {"session_id": "sk5", "agent_id": "k5", "last_assistant_message": good}, led)
        r5b_ = sk_row("sk5", "k5")
        check("stop: setup — a headerless stub was closed by the stale fallback with its tokens counted", r5_.get("closed_by") == "stale" and r5_.get("tokens") == 50_000 and t5_ == 50_000)
        check("stop: the real report re-grades a stale-closed row (done/high, closed_by gone) and the task counts the token delta only", r5b_.get("status") == "done" and r5b_.get("confidence") == "high" and "closed_by" not in r5b_ and r5b_.get("tokens") == 80_000 and gstate("sk5").get("task_tokens") == 80_000)
        jpi_ = agent("sonnet", "medium", "abofles:abofles-judge", prompt="abofles: X / Judge · T2\nq\nLine cap: 40", cwd=cwd)
        sk_agent("sk6", "k6", [sk_msg("text", "Understood.", "end_turn", "a", 1)], 200, pi_=jpi_)
        setst("sk6", gate="auto")
        sk_stop("sk6")
        ok6_ = gstate("sk6").get("judge_ok", 0)
        ask_ = "STATUS: done\nCONFIDENCE: high\nVERDICT: ASK\nQUESTION: q\nEVIDENCE:\n- a.cs:1 — x\nWHY: w\nOPTIONS:\n- A — means: m · then: t · pick when: p\nRECOMMEND: A — r"
        run("stop", {"session_id": "sk6", "agent_id": "k6", "last_assistant_message": ask_}, led)
        ok6b_ = gstate("sk6").get("judge_ok", 0)
        run("stop", {"session_id": "sk6", "agent_id": "k6", "last_assistant_message": ask_}, led)
        check("stop: a stale-closed judge stub, then the real VERDICT: ASK, unlocks once; a repeat stop for the agent adds no second unlock", sk_row("sk6", "k6").get("closed_by") is None and ok6b_ == ok6_ + 1 and gstate("sk6").get("judge_ok", 0) == ok6b_)

        # a SendMessage that resumes a finished agent re-opens its ledger row: it runs in the background again (no "no receipt" nudge while it works)
        rs_sync = lambda sid_, aid, name=None, stype="abofles:abofles-reader", text=good: run("post", dict(agent("haiku", "low", stype, prompt="abofles: Resume / R · T2\nq\nLine cap: 40" if "judge" not in stype else "abofles: Resume / Judge · T2\nq\nLine cap: 40", resp={"agentId": aid, "status": "completed", "content": [blk(text)], "usage": {}, "totalTokens": 9}, cwd=cwd), session_id=sid_, transcript_path=str(tr), tool_input=dict(agent("haiku", "low", stype, cwd=cwd)["tool_input"], **({"name": name} if name else {}))), led)
        rs_msg = lambda sid_, to, resp="absent": run("sendmsg", dict({"session_id": sid_, "cwd": cwd, "tool_name": "SendMessage", "tool_input": {"to": to, "message": "more"}}, **({} if resp == "absent" else {"tool_response": resp})), led)
        rs_ok = lambda aid: {"success": True, "message": "Resuming agent " + aid[:7], "resumedAgentId": aid, "pin": {"id": aid, "name": aid}}
        rs_row = lambda sid_, aid: next(r for r in ledrows(sid_) if r.get("agent_id") == aid)
        run("start", {"session_id": "rs0", "cwd": cwd, "transcript_path": str(tr)}, led)
        rs_sync("rs0", "q0")
        check("resume: control — a finished sync agent with no resume gets the 'no receipt' nudge", "no receipt" in json.dumps(sk_stop("rs0") or {}))
        run("start", {"session_id": "rs", "cwd": cwd, "transcript_path": str(tr)}, led)
        rs_sync("rs", "q1")
        sp_ = {k: gstate("rs").get(k) for k in ("spawns", "spawns_since_receipt", "task_units", "task_base", "task_judges")}
        tk_ = {k: gstate("rs").get(k) for k in ("task_tokens", "task_usd")}
        rs_msg("rs", "q1", rs_ok("q1"))
        q1_ = rs_row("rs", "q1")
        check("resume: a SendMessage whose response names resumedAgentId re-opens the agent's done row in place (pending, resumed=1, reopened_ts, no completed_ts)", q1_.get("status") == "pending" and q1_.get("resumed") == 1 and q1_.get("reopened_ts") and "completed_ts" not in q1_ and len(ledrows("rs")) == 1)
        check("resume: the reopened row drops the old confidence", "confidence" not in q1_)
        check("resume: not a new spawn — spawns, spawns_since_receipt, task_units, task_base and the token/usd totals unchanged; running_bg = 1", {k: gstate("rs").get(k) for k in sp_} == sp_ and {k: gstate("rs").get(k) for k in tk_} == tk_ and gstate("rs").get("running_bg") == 1)
        check("resume: the receipt gives no 'no receipt' nudge while the resumed agent runs", "no receipt" not in json.dumps(sk_stop("rs") or {}) and rs_row("rs", "q1").get("status") == "pending")
        run("stop", {"session_id": "rs", "agent_id": "q1", "last_assistant_message": good}, led)
        q1b_ = rs_row("rs", "q1")
        check("resume: the resumed agent's SubagentStop closes the row again, resumed stays 1, one row, same spawn count", q1b_.get("status") == "done" and q1b_.get("resumed") == 1 and q1b_.get("completed_ts") and len(ledrows("rs")) == 1 and gstate("rs").get("spawns") == sp_["spawns"] and all(r.get("status") != "pending" for r in ledrows("rs")))
        rs_sync("rs", "q2", name="helper-2")
        rs_msg("rs", "helper-2")  # `to` is the spawn name, the response has no shape to read: falls back to `to`
        q2_ = rs_row("rs", "q2")
        check("resume: a SendMessage `to` given as the spawn name (no tool_response) re-opens the row; the name is kept in the ledger", q2_.get("name") == "helper-2" and q2_.get("status") == "pending" and q2_.get("resumed") == 1)
        before_ = ledrows("rs")
        rs_msg("rs", "nobody-9", rs_ok("nobody-9")); rs_msg("rs", "q1", {"success": False, "error": "no such agent"})
        check("resume: a message to an unknown id, or one the harness reports as failed, leaves the ledger unchanged", ledrows("rs") == before_)
        # stale fallback: the reopened row is fresh for STALE_AFTER from reopened_ts, then closes from the transcript like any pending row
        run("start", {"session_id": "rs3", "cwd": cwd, "transcript_path": str(tr)}, led)
        rs_sync("rs3", "q3")
        f3_ = Path(cwd, "rs3", "subagents", "agent-q3.jsonl"); f3_.parent.mkdir(parents=True, exist_ok=True)
        f3_.write_text(json.dumps(sk_msg("text", good, "end_turn", "a", 1000)) + "\n"); os.utime(f3_, (time.time() - 600, time.time() - 600))
        rs_msg("rs3", "q3", rs_ok("q3"))
        sk_stop("rs3")
        check("resume: an old, finished transcript does not close the reopened row (reopened_ts is fresh)", rs_row("rs3", "q3").get("status") == "pending")
        rows3_ = ledrows("rs3"); rows3_[0]["reopened_ts"] = int(time.time()) - H.STALE_AFTER - 60
        Path(led, "rs3.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows3_))
        sk_stop("rs3")
        check("resume: a finished transcript older than reopened_ts (the old turn) does not close the reopened row even past STALE_AFTER", rs_row("rs3", "q3").get("status") == "pending")
        os.utime(f3_, (time.time() - H.STALE_AFTER - 30, time.time() - H.STALE_AFTER - 30))
        sk_stop("rs3")
        r3b_ = rs_row("rs3", "q3")
        check("resume: with reopened_ts older than STALE_AFTER and a finished transcript the receipt closes the row (closed_by=stale), no SubagentStop needed", r3b_.get("status") != "pending" and r3b_.get("closed_by") == "stale" and r3b_.get("resumed") == 1)
        # a resumed gate agent: sendmsg's own unlock counts once; the SubagentStop of the resumed turn does not unlock a second time
        run("start", {"session_id": "rs4", "cwd": cwd, "transcript_path": str(tr)}, led)
        setst("rs4", gate="auto")
        rs_sync("rs4", "q4", name="judge-r", stype="abofles:abofles-judge", text=ask_)
        ok4_ = gstate("rs4").get("judge_ok", 0)
        out4_ = rs_msg("rs4", "judge-r", rs_ok("q4"))
        ok4b_ = gstate("rs4").get("judge_ok", 0)
        run("stop", {"session_id": "rs4", "agent_id": "q4", "last_assistant_message": ask_}, led)
        q4_ = rs_row("rs4", "q4")
        check("resume: a resumed judge row is pending, sendmsg unlocks one question (SENDMSG_TEXT), the stop that closes it adds no judge_ok", "unlocked" in ctx(out4_) and ok4b_ == ok4_ + 1 and gstate("rs4").get("judge_ok", 0) == ok4b_ and q4_.get("status") == "done" and q4_.get("resumed") == 1)
        rs_sync("rs", "q5", name="plain-5")
        check("resume: a non-gate agent resume prints nothing (no SENDMSG_TEXT)", rs_msg("rs", "q5", rs_ok("q5")) is None)

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
        # 4b. the model's own receipt header closes the task (looks_like_receipt); the journal carries the computed header
        OWN = "🧾 **Receipt**\n- `done` → x\n- `why` → y\n- `check` → z\n- `open` → none\n- `next` → n"
        check("looks_like_receipt: own header with done+open fields counts (also the old columns); the computed header is not needed",
              H.looks_like_receipt(OWN) and H.looks_like_receipt("text\n🧾 Receipt\ndone   x\nopen   none") and not H.has_receipt(OWN))
        check("looks_like_receipt: a bare 🧾 line, a quoted one, prose about a receipt and fields without 🧾 are not a receipt",
              not H.looks_like_receipt("🧾 receipt coming") and not H.looks_like_receipt("> 🧾 **Receipt**\n- `done` → x\n- `open` → none") and not H.looks_like_receipt("the receipt has `done` and `open` fields")
              and not H.looks_like_receipt("🧾 **Receipt**\n- `done` → x") and not H.looks_like_receipt("- `done` → x\n- `open` → none") and not H.looks_like_receipt(""))
        b_task("bf1")
        hdr_ = re.sub(r"\*\*", "", H.receipt_header(gstate("bf1"))[1:]).strip()
        check("receipt: a receipt under the model's own header does not block, closes the task",
              stop_("bf1", OWN) is None and gstate("bf1").get("spawns_since_receipt") == 0 and "receipt_owed" not in gstate("bf1"))
        jt_ = sf("bf1").read_text()
        check("receipt: ... and the journal line carries the computed header with the parsed fields", hdr_ in jt_ and "· Receipt" not in jt_ and "done: x" in jt_ and "check: z" in jt_)
        b_task("bf2")
        check("receipt: a message with only `🧾 receipt coming` is still nudged, the task stays open",
              (stop_("bf2", "🧾 receipt coming") or {}).get("decision") == "block" and gstate("bf2").get("spawns_since_receipt") == 1)
        # 4c. a background chain that ended: the next notification prompt carries the receipt instruction (the launch carried none)
        bf_launch = lambda sid_, aid_: run("post", dict(agent("haiku", "low", resp=launch_(aid_), cwd=cwd), session_id=sid_, transcript_path=str(tr)), led)
        bf_done = lambda sid_, aid_: run("stop", {"session_id": sid_, "agent_id": aid_, "last_assistant_message": good}, led)
        NOTE = "<task-notification>agent finished</task-notification>"
        run("start", {"session_id": "bf3", "cwd": cwd, "transcript_path": str(tr)}, led)
        bf_launch("bf3", "bf3a"); bf_done("bf3", "bf3a")
        out_ = ctx(run("prompt", {"session_id": "bf3", "cwd": cwd, "prompt": NOTE}, led))
        check("notification: the last background agent finished -> hook context carries the receipt instruction and the computed header",
              "Receipt at task end" in out_ and "🧾 **1 Spawn" in out_ and "running" not in out_)
        run("start", {"session_id": "bf4", "cwd": cwd, "transcript_path": str(tr)}, led)
        bf_launch("bf4", "bf4a"); bf_launch("bf4", "bf4b"); bf_done("bf4", "bf4a")
        check("notification: another background agent still runs -> no receipt instruction", "Receipt at task end" not in ctx(run("prompt", {"session_id": "bf4", "cwd": cwd, "prompt": NOTE}, led)))
        run("start", {"session_id": "bf5", "cwd": cwd, "transcript_path": str(tr)}, led)
        bf_launch("bf5", "bf5a"); bf_done("bf5", "bf5a")
        check("notification: a real user prompt gets no receipt instruction", "Receipt at task end" not in ctx(run("prompt", {"session_id": "bf5", "cwd": cwd, "prompt": "and now?"}, led)))
        Path(state, "no-user-claude.md").write_text("## abofles overrides\n- Receipt = off\n")
        run("start", {"session_id": "bf6", "cwd": cwd, "transcript_path": str(tr)}, led)
        bf_launch("bf6", "bf6a"); bf_done("bf6", "bf6a")
        out_ = ctx(run("prompt", {"session_id": "bf6", "cwd": cwd, "prompt": NOTE}, led))
        check("notification: Receipt = off -> no receipt instruction", "Receipt at task end" not in out_ and "no receipt for this task" not in out_)
        Path(state, "no-user-claude.md").unlink()
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
        check("exit: status --resolve with no ledger at all exits 1", st_("--resolve", "abc", "--trace", "re-checked: t").returncode == 1)
        lf = Path(xh, "led", "xs.jsonl")
        lf.write_text('{"agent_id": "abc123", "status": "partial"}\nHALF{"agent_id":"abc9\n{"agent_id": "abd1", "status": "blocked"}\n')
        check("exit: status --resolve as the last arg exits 2", st_("--resolve").returncode == 2)
        check("exit: status --resolve with an empty id exits 2", st_("--resolve", "", "--session", "xs").returncode == 2)
        check("exit: status --resolve with a flag as id exits 2", st_("--resolve", "--trace").returncode == 2)
        check("exit: status --session without a value exits 2", st_("--resolve", "abc", "--session").returncode == 2)
        check("exit: status --unresolve with an empty session exits 2", st_("--unresolve", "abc", "--session", "", "--trace").returncode == 2)
        check("exit: status --session ../ is cleaned to a name in the ledger dir (no such ledger, exit 1)", st_("--resolve", "abc", "--session", "../../nope", "--trace", "re-checked: t").returncode == 1 and not Path(xh, "nope.jsonl").exists())
        r1 = st_("--resolve", "abc1", "--session", "xs", "--trace", "by test")
        txt = lf.read_text().splitlines()
        check("exit: status --resolve exits 0, marks the row, keeps the half-written line verbatim",
              r1.returncode == 0 and json.loads(txt[0]).get("resolved") is True and txt[1] == 'HALF{"agent_id":"abc9' and json.loads(txt[2]) == {"agent_id": "abd1", "status": "blocked"})
        memd = lambda s: Path(xp, ".claude", "abofles-memo.d", f"{s[:8]}.md")  # a trace lands in the file of the session it names
        mem = memd("xs")
        check("exit: status --resolve --trace wrote one Journal line", mem.read_text().count("resolved by hand:") == 1)
        r2 = st_("--resolve", "abc1", "--session", "xs", "--trace", "again")
        check("exit: status --resolve of a resolved row exits 3, writes no trace", r2.returncode == 3 and mem.read_text().count("resolved by hand:") == 1)
        check("exit: status --resolve miss exits 1", st_("--resolve", "zzz", "--session", "xs", "--trace", "re-checked: t").returncode == 1)
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
        m2 = me_("resolve", "1", "again", "--trace", "--session", "mysess")
        check("exit: memo resolve of a resolved item exits 3, writes no trace", m2.returncode == 3 and memd("mysess").read_text().count("by hand:") == n_)
        check("exit: memo resolve of a missing item exits 1", me_("resolve", "9", "re-checked: t").returncode == 1 and me_("reopen", "9").returncode == 1)
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
        check("scope: status --resolve cannot reach another project's row", sc_("status.py", "--resolve", "zzz9", "--session", sid_, "--trace", "re-checked: t").returncode == 1 and "resolved" not in Path(xh, "led", "otherS.jsonl").read_text())
        # this project's session: display and --resolve use the same ledger, with the appended session id
        Path(xh, "st", f"{sid_}.json").write_text(json.dumps({"root": os.path.realpath(xp), "last_prompt_ts": 1}))
        Path(xh, "led", f"{sid_}.jsonl").write_text('{"agent_id": "abc123", "topic": "MineTopic", "status": "partial", "model": "opus", "effort": "high"}\n')
        r = sc_("status.py", "--baseline", "opus", "--session", sid_)
        check("scope: status shows this project's own ledger row", "MineTopic" in r.stdout and "abc123" in r.stdout and "OtherProjectTopic" not in r.stdout)
        r = sc_("status.py", "--resolve", "abc1", "--session", sid_, "--trace", "re-checked: t")
        check("scope: status --resolve <id> --session <uuid> settles the row the display shows", r.returncode == 0 and json.loads(Path(xh, "led", f"{sid_}.jsonl").read_text())["resolved"] is True)
        # memo.py: the user's own --session wins over the command's appended one
        subprocess.run([sys.executable, "-c", "import sys,os; sys.path.insert(0, sys.argv[1]); import abofles_hook as h; h.memo_needs(os.getcwd(), 'sessAAAA', 'owner decision: pick A or B')", str(sdir.parent / "hooks")], cwd=xp, env=xenv)
        r = sc_("memo.py", "resolve", "1", "re-checked: t", "--trace", "--session", "mysessX", "--session", sid_)
        memx = lambda s: Path(xp, ".claude", "abofles-memo.d", f"{s[:8]}.md")
        check("session: memo resolve with the user's --session X plus an appended UUID traces into X's file", r.returncode == 0 and "· resolved by hand: owner decision 1" in memx("mysessX").read_text() and "owner decision" not in (memx(sid_).read_text() if memx(sid_).exists() else ""))
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
        check("start: SessionStart names the topic lookup command", "abofles: topic lookup = bash" in (st_out or "") and "scripts/py" in (st_out or "") and "topic.py" in (st_out or ""))
        check("skill: Step 2 tells the model to look the topic up, not read a list", "scripts/topic.py" in (sdir.parent / "skills/abofles/SKILL.md").read_text() and "100 topics" not in (sdir.parent / "skills/abofles/SKILL.md").read_text())

    # ---- Windows: no fcntl. A stub msvcrt (backed by flock) stands in; the hooks must load, lock and answer as on Unix.
    with tempfile.TemporaryDirectory() as led, tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as shim:
        Path(shim, "sitecustomize.py").write_text(
            "import sys, fcntl as _f\n"
            "class _M:\n"
            "    LK_NBLCK = 2; LK_UNLCK = 0; LK_LOCK = 1\n"
            "    calls = []\n"
            "    @staticmethod\n"
            "    def locking(fd, mode, n):\n"
            "        _M.calls.append(mode)\n"
            "        _f.lockf(fd, _f.LOCK_UN if mode == 0 else _f.LOCK_EX | _f.LOCK_NB, n, 0)\n"
            "sys.modules['msvcrt'] = _M\n"
            "sys.modules['fcntl'] = None\n"
            "import atexit, os\n"
            "atexit.register(lambda: open(os.environ['WIN_LOG'], 'a').write(','.join(map(str, _M.calls)) + '\\n'))\n")
        wlog = Path(shim, "calls.log")
        wenv = dict(os.environ, PYTHONPATH=shim, WIN_LOG=str(wlog), ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state, ABOFLES_USER_CLAUDE_MD=str(Path(state, "none.md")))
        wrun = lambda mode, payload: subprocess.run([sys.executable, str(HOOK.parent / "run.py"), mode], input=json.dumps(payload), capture_output=True, text=True, env=wenv)
        r = wrun("start", {"session_id": "win", "cwd": cwd, "source": "startup"})
        check("windows: hooks load without fcntl (SessionStart runs, prints the lookup line)", r.returncode == 0 and "topic lookup" in r.stdout and "Traceback" not in r.stderr)
        check("windows: state written under the msvcrt lock", Path(state, "win.json").exists() and "2" in wlog.read_text() and "0" in wlog.read_text())
        rr = [wrun("guard", {"session_id": "win", "cwd": cwd, "tool_name": "Grep", "tool_input": {}}) for _ in range(4)]
        check("windows: guard counts reads and warns on the 4th", all(x.returncode == 0 for x in rr) and "direct reads in a row" in rr[3].stdout)
        r = wrun("pre", dict(agent("haiku", None, cwd=cwd), session_id="win"))
        check("windows: pre still blocks a spawn without effort", "effort=missing" in r.stdout)
        Path(cwd, ".claude").mkdir(exist_ok=True)
        r = subprocess.run([sys.executable, str(sdir / "memo.py"), "now", "--session", "win"], input="Task      Arabic ✓ عربي 🧔\nNext      test\n", capture_output=True, text=True, env=wenv, cwd=cwd)
        check("windows: memo.py writes a Now section with emoji and Arabic", r.returncode == 0 and "عربي" in Path(cwd, ".claude", "abofles-memo.d", "win.md").read_text(encoding="utf-8"))
        hj = json.loads((HOOK.parent / "hooks.json").read_text())
        cmds = [h["command"] for ev in hj["hooks"].values() for grp in ev for h in grp["hooks"] if "run.py" in h["command"]]
        check("windows: every hook command goes through scripts/py (python3 -> python -> py -3)", cmds and all('bash "${CLAUDE_PLUGIN_ROOT}/scripts/py"' in c for c in cmds))
        check("windows: no Unix-only import left at module top", "\nimport fcntl\n" not in HOOK.read_text())
        import importlib.util as _iuw
        _hw = _iuw.spec_from_file_location("abofles_hook_win", str(HOOK)); HW = _iuw.module_from_spec(_hw); _hw.loader.exec_module(HW)
        check("windows: posix() normalises backslash paths for the worktree checks", HW.posix("C:\\repo\\.git\\worktrees\\wt") == "C:/repo/.git/worktrees/wt")

    # ---- launcher scripts/py: python3 -> python -> py -3, UTF-8 mode; hooks, commands and printed commands all use it
    with tempfile.TemporaryDirectory() as led, tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as fbin:
        sdir = Path(__file__).resolve().parent
        PY = sdir / "py"
        base = dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_STATE_DIR=state, ABOFLES_USER_CLAUDE_MD=str(Path(state, "none.md")))
        r = subprocess.run(["bash", str(PY), "-c", "import sys; print(sys.flags.utf8_mode)"], capture_output=True, text=True, env=base)
        check("launcher: scripts/py runs Python in UTF-8 mode", r.returncode == 0 and r.stdout.strip() == "1")
        # Windows-like PATH: python3 is the Store stub (exit 9009), python is real
        Path(fbin, "python3").write_text("#!/bin/sh\nexit 9009\n"); os.chmod(Path(fbin, "python3"), 0o755)
        os.symlink(sys.executable, Path(fbin, "python"))
        for tool in ("bash", "sh", "env", "dirname", "basename"):
            w = shutil.which(tool)
            if w and not Path(fbin, tool).exists():
                os.symlink(w, Path(fbin, tool))
        wenv = dict(base, PATH=fbin, ABOFLES_PY_PROBE="1")
        r = subprocess.run(["bash", str(PY), "-c", "import sys; print('ok', sys.flags.utf8_mode)"], capture_output=True, text=True, env=wenv)
        check("launcher: a python3 stub (exit 9009) is skipped and `python` runs", r.returncode == 0 and r.stdout.strip() == "ok 1")
        Path(fbin, "python").unlink()
        r = subprocess.run(["bash", str(PY), "-c", "print(1)"], capture_output=True, text=True, env=wenv)
        check("launcher: no Python at all -> one clear stderr line, exit 0 (hook never breaks the session)", r.returncode == 0 and "Python 3.8+ not found" in r.stderr and r.stdout == "")
        hj = json.loads((HOOK.parent / "hooks.json").read_text())
        cmds = [h["command"] for ev in hj["hooks"].values() for grp in ev for h in grp["hooks"] if "run.py" in h["command"]]
        check("launcher: every hook command runs bash scripts/py --hook hooks/run.py <mode>, no `||` (no double run)", len(cmds) == 11 and all(c.startswith('bash "${CLAUDE_PLUGIN_ROOT}/scripts/py" --hook "${CLAUDE_PLUGIN_ROOT}/hooks/run.py" ') and "||" not in c for c in cmds))
        r = subprocess.run(["bash", str(PY), "--hook", str(Path(state, "missing.py"))], capture_output=True, text=True, env=base)
        check("launcher: --hook always exits 0, even when Python fails (exit 2 would block the tool call)", r.returncode == 0)
        r = subprocess.run(["bash", str(PY), str(Path(state, "missing.py"))], capture_output=True, text=True, env=base)
        check("launcher: without --hook the script's own exit code passes through (commands see failures)", r.returncode == 2)
        check("launcher: scripts/py has LF line endings and .gitattributes keeps them on Windows checkouts", b"\r" not in PY.read_bytes() and "plugins/abofles/scripts/py text eol=lf" in (sdir.parents[2] / ".gitattributes").read_text())
        cache = Path(state, "py-path")
        Path(fbin, "python").symlink_to(sys.executable)
        r1 = subprocess.run(["bash", str(PY), "-c", "print(2)"], capture_output=True, text=True, env=dict(wenv, ABOFLES_PY_CACHE=str(cache)))
        check("launcher: the probed interpreter is cached for the next call", r1.stdout.strip() == "2" and cache.read_text().strip() == "python")
        Path(fbin, "python").unlink()
        r2 = subprocess.run(["bash", str(PY), "-c", "print(3)"], capture_output=True, text=True, env=dict(wenv, ABOFLES_PY_CACHE=str(cache)))
        check("launcher: a cached interpreter that disappeared is re-probed (no stale cache)", r2.returncode == 0 and "not found" in r2.stderr)
        src = HOOK.read_text()
        check("windows: the UTF-8 relaunch skips test_hooks.py and gen_matrix.py", '"test_hooks.py", "gen_matrix.py"' in src)
        r = subprocess.run(["bash", "-c", " ".join(cmds[0].replace("${CLAUDE_PLUGIN_ROOT}", str(sdir.parent)).split()[:4]) + " start"], input=json.dumps({"session_id": "lz", "cwd": cwd, "source": "startup"}), capture_output=True, text=True, env=base)
        check("launcher: the real hooks.json command line runs SessionStart", r.returncode == 0 and "topic lookup = bash" in r.stdout and "scripts/py" in r.stdout)
        cm = "".join(p.read_text() for p in (sdir.parent / "commands").glob("*.md"))
        docs = "".join(p.read_text() for p in [sdir.parent / "skills/abofles/SKILL.md", *(sdir.parent / "skills/abofles/references").glob("*.md")])
        check("launcher: no slash command or skill text tells the model to run python3 directly", "python3 \"${CLAUDE_PLUGIN_ROOT}" not in cm and "Bash(python3" not in cm and 'python3 "<plugin' not in docs and "Bash(bash *)" in cm)
        import importlib.util as _iul
        _hl = _iul.spec_from_file_location("abofles_hook_l", str(HOOK)); HL = _iul.module_from_spec(_hl); _hl.loader.exec_module(HL)
        check("launcher: printed commands use scripts/py with forward slashes", HL.shell_cmd("memo.py").startswith('bash "') and "/scripts/py\" \"" in HL.shell_cmd("memo.py") and "\\" not in HL.shell_cmd("memo.py"))
        # Windows path shapes (ntpath-style strings) in the prefix checks
        st = {"root": "C:\\work\\proj"}
        _rp = HL.os.path.realpath
        HL.os.path.realpath = lambda x: x
        try:
            check("windows: an edit under the launch root (backslash paths) counts for the root", HL.work_key(st, "C:\\work\\proj\\src\\a.cs") == "C:\\work\\proj")
        finally:
            HL.os.path.realpath = _rp
        check("windows: replace_file retries a PermissionError then succeeds", (lambda: (lambda calls: (setattr(HL.os, "replace", (lambda o: (lambda a, b: (calls.append(1), (_ for _ in ()).throw(PermissionError()) if len(calls) < 3 else o(a, b))))(HL.os.replace)), Path(state, "t.tmp").write_text("x"), HL.replace_file(Path(state, "t.tmp"), Path(state, "t.out")), Path(state, "t.out").exists() and len(calls) == 3)[-1])([]))())


    with tempfile.TemporaryDirectory() as led, tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as state:  # pane batch: its own dirs and environment
        os.environ["ABOFLES_STATE_DIR"] = state
        os.environ["ABOFLES_TEST_CWD"] = cwd
        os.environ["ABOFLES_USER_CLAUDE_MD"] = str(Path(state, "no-user-claude.md"))
        os.environ["ABOFLES_CONFIG"] = str(Path(state, "config.json"))
        os.environ["ABOFLES_CLAUDE_HOME"] = str(Path(state, "claude-home"))
        os.environ.pop("ABOFLES_SESSION", None)
        gstate = lambda sid_: json.loads(Path(state, f"{sid_}.json").read_text())
        # ── Pane batch: golden resume text, places, pane payload ──
        import importlib.util as _iug
        _hg = _iug.spec_from_file_location("abofles_hook_gold", str(HOOK)); HG = _iug.module_from_spec(_hg); _hg.loader.exec_module(HG)
        gp = str(Path(tempfile.mkdtemp(), "goldproj")); gs = "goldsess1"; HG.STATE_DIR = Path(tempfile.mkdtemp())  # empty registry: no other projects
        Path(gp, ".claude", "abofles-memo.d").mkdir(parents=True)
        Path(gp, ".claude", "abofles-memo.md").write_text(
            "# Abo Fles memo — gold\nUpdated: 2026-10-20 10:30 · session goldsess\nProject: x\n\n## Needs you\n"
            "1. [ ] 10-20 09:10 · owner decision: cap per unit or per order? (s:goldsess)\n2. [x] 10-20 09:11 · done thing (s:goldsess)\n3. [ ] 10-20 09:12 · ATTENTION: banner copy needs your OK (s:othersess)\n"
            "\n## Decisions\n\n## Sessions\n- [goldsess](abofles-memo.d/goldsess.md) · 10-20 10:30 · task: cap the surcharge · receipts: 2\n- [othersess](abofles-memo.d/othersess.md) · 10-20 09:00 · task: the banner · receipts: 1\n")
        Path(gp, ".claude", "abofles-memo.d", "goldsess.md").write_text(
            "# Session goldsess\nUpdated: 2026-10-20 10:30\nProject: x\n\n## Now\nWritten   2026-10-20 10:00\nTask      cap the surcharge in AqsatiRules.cs\nLeft      wire the FE badge; update the docs page\nNext      run the full suite\n"
            "\n## Journal\n- 10-20 10:20 · 🧾 **1 Spawn · Saved 5%** · done: capped it\n- 10-20 10:10 · 🧾 **2 Spawns** · done: read the rules\n- 10-20 10:05 · 🧾 **1 Spawn** · done: first\n- 10-20 09:50 · 🧾 old\n\n## Decisions\n")
        Path(gp, ".claude", "abofles-memo.d", "othersess.md").write_text("# Session othersess\n\n## Now\nWritten   2026-10-20 09:00\nTask      the banner\n\n## Journal\n- 10-20 09:00 · 🧾 **1 Spawn** · done: banner\n\n## Decisions\n")
        _t0 = time.time
        time.time = lambda: time.mktime(time.strptime("2026-10-20 13:30", "%Y-%m-%d %H:%M"))
        try:
            gold_out = {
                "project": HG.resume_block(gp, session_id=gs, guide="🧭 ✅ nothing open"),
                "away": HG.resume_block(gp, 42, session_id=gs),
                "session": HG.resume_block(gp, session_id=gs, scope="session"),
                "hint": HG.resume_block(gp, session_id="freshsess9"),
                "all": HG.resume_block(gp, session_id=gs, scope="all"),
            }
        finally:
            time.time = _t0
        GOLD = {
            'project': "📍 **Resume** · memo 2026-10-20 10:30 · session goldsess · now written 2026-10-20 10:00 (3 hours 30 min ago)\n- `now` → cap the surcharge in AqsatiRules.cs\n- `left` →\n  - wire the FE badge\n  - update the docs page\n- `next` → run the full suite\n- `since` → 3 receipts of this session after its Now section was written — `now`/`next` above may be stale; trust `last` and the journal\n- `needs you` → 2 open\n  - 1) owner decision: cap per unit or per order? (s:goldsess)\n  - 3) ATTENTION: banner copy needs your OK (s:othersess)\n- `last` →\n  - 10-20 10:20 · 🧾 **1 Spawn · Saved 5%** · done: capped it\n  - 10-20 10:10 · 🧾 **2 Spawns** · done: read the rules\n  - 10-20 10:05 · 🧾 **1 Spawn** · done: first\n- `guide` → 🧭 ✅ nothing open",
            'away': "📍 **Resume** · memo 2026-10-20 10:30 · away 42 min · session goldsess · now written 2026-10-20 10:00 (3 hours 30 min ago)\n- `now` → cap the surcharge in AqsatiRules.cs\n- `left` →\n  - wire the FE badge\n  - update the docs page\n- `next` → run the full suite\n- `since` → 3 receipts of this session after its Now section was written — `now`/`next` above may be stale; trust `last` and the journal\n- `needs you` → 2 open\n  - 1) owner decision: cap per unit or per order? (s:goldsess)\n  - 3) ATTENTION: banner copy needs your OK (s:othersess)\n- `last` →\n  - 10-20 10:20 · 🧾 **1 Spawn · Saved 5%** · done: capped it\n  - 10-20 10:10 · 🧾 **2 Spawns** · done: read the rules\n  - 10-20 10:05 · 🧾 **1 Spawn** · done: first",
            'session': "📍 **Resume** · memo 2026-10-20 10:30 · session goldsess · scope session · now written 2026-10-20 10:00 (3 hours 30 min ago)\n- `now` → cap the surcharge in AqsatiRules.cs\n- `left` →\n  - wire the FE badge\n  - update the docs page\n- `next` → run the full suite\n- `since` → 3 receipts of this session after its Now section was written — `now`/`next` above may be stale; trust `last` and the journal\n- `needs you` → 1 open: 1) owner decision: cap per unit or per order? (s:goldsess)\n- `last` →\n  - 10-20 10:20 · 🧾 **1 Spawn · Saved 5%** · done: capped it\n  - 10-20 10:10 · 🧾 **2 Spawns** · done: read the rules\n  - 10-20 10:05 · 🧾 **1 Spawn** · done: first",
            'hint': "📍 **Resume** · memo 2026-10-20 10:30 · session freshses\n- `project` → goldproj: 2 other sessions, newest goldsess · task: cap the surcharge — their work, not yours; `/abofles:resume --scope project` shows them\n- `needs you` → 2 open\n  - 1) owner decision: cap per unit or per order? (s:goldsess)\n  - 3) ATTENTION: banner copy needs your OK (s:othersess)",
            'all': "📍 **Resume** · memo 2026-10-20 10:30 · session goldsess · scope all · now written 2026-10-20 10:00 (3 hours 30 min ago)\n- `now` → cap the surcharge in AqsatiRules.cs\n- `left` →\n  - wire the FE badge\n  - update the docs page\n- `next` → run the full suite\n- `since` → 3 receipts of this session after its Now section was written — `now`/`next` above may be stale; trust `last` and the journal\n- `needs you` → 2 open\n  - 1) owner decision: cap per unit or per order? (s:goldsess)\n  - 3) ATTENTION: banner copy needs your OK (s:othersess)\n- `last` →\n  - 10-20 10:20 · 🧾 **1 Spawn · Saved 5%** · done: capped it\n  - 10-20 10:10 · 🧾 **2 Spawns** · done: read the rules\n  - 10-20 10:05 · 🧾 **1 Spawn** · done: first",
        }
        for _k, _v in GOLD.items():
            check(f"resume_block golden text ({_k}) is byte-identical", gold_out[_k] == _v)

        # places and the mod switch
        chome = Path(state, "claude-home"); HG.LEDGER_DIR = Path(led)
        def mod(on, key="abofles-guide@claude-plugins"):  # `on` True/False: a settings.json key; None: no settings file at all
            shutil.rmtree(chome, ignore_errors=True)
            if on is not None:
                chome.mkdir(parents=True); (chome / "settings.json").write_text(json.dumps({"enabledPlugins": {key: on}}))
        def put_md(proj, text):
            if text is None: Path(proj, "CLAUDE.md").unlink(missing_ok=True)
            else: Path(proj, "CLAUDE.md").write_text("## abofles overrides\n" + text)
        pc = tempfile.mkdtemp()
        mod(None)
        cached_ = HG.pane_enabled
        HG._PANE_ON.clear(); first_ = cached_(); mod(True); again_ = cached_(); HG._PANE_ON.clear(); fresh_ = cached_(); mod(None)
        check("pane_enabled: read once per process (place() asks three times per refresh); a new process reads again", first_ is False and again_ is False and fresh_ is True)
        HG.pane_enabled = HG.pane_enabled_uncached  # below, the files change inside this one process
        check("pane_enabled: no settings file and no plugin cache -> off", HG.pane_enabled() is False)
        (chome / "plugins" / "cache" / "mk" / "abofles-guide").mkdir(parents=True)
        check("pane_enabled: no settings file, abofles-guide folder in the plugin cache -> on", HG.pane_enabled() is True)
        mod(True); check("pane_enabled: enabledPlugins abofles-guide@… true -> on", HG.pane_enabled() is True)
        mod(False); (chome / "plugins" / "cache" / "mk" / "abofles-guide").mkdir(parents=True)
        check("pane_enabled: the key false wins over the cache folder -> off", HG.pane_enabled() is False)
        mod(True, "other-mod@x"); check("pane_enabled: only another plugin's key and no cache -> off", HG.pane_enabled() is False)
        (chome / "settings.json").write_text("{not json"); check("pane_enabled: unreadable settings and no cache -> off", HG.pane_enabled() is False)
        mod(None); pd_ = Path(state, "plugdirs"); (pd_ / "x" / "abofles-guide").mkdir(parents=True); (pd_ / "y").mkdir()
        os.environ["CLAUDE_CODE_PLUGIN_DIRS"] = str(pd_ / "y") + os.pathsep + str(pd_ / "x")
        check("pane_enabled: CLAUDE_CODE_PLUGIN_DIRS names a folder holding abofles-guide, no settings -> on", HG.pane_enabled() is True)
        os.environ["CLAUDE_CODE_PLUGIN_DIRS"] = str(pd_ / "x" / "abofles-guide")
        check("pane_enabled: CLAUDE_CODE_PLUGIN_DIRS names the abofles-guide folder itself -> on", HG.pane_enabled() is True)
        os.environ["CLAUDE_CODE_PLUGIN_DIRS"] = str(pd_ / "y")
        check("pane_enabled: CLAUDE_CODE_PLUGIN_DIRS without abofles-guide -> off", HG.pane_enabled() is False)
        os.environ["CLAUDE_CODE_PLUGIN_DIRS"] = str(pd_ / "x"); mod(False)
        check("pane_enabled: the enabledPlugins key false wins over CLAUDE_CODE_PLUGIN_DIRS -> off", HG.pane_enabled() is False)
        os.environ.pop("CLAUDE_CODE_PLUGIN_DIRS")
        mod(True)
        put_md(pc, None)
        check("place: default is pane for guide, resume and spawns", [HG.place(pc, w) for w in ("guide", "resume", "spawns")] == ["pane"] * 3)
        put_md(pc, "- Guide place = band\n- Resume place = output\n- Spawns place = Output\n")
        check("place: values read from the override block (case ignored)", [HG.place(pc, w) for w in ("guide", "resume", "spawns")] == ["band", "output", "output"])
        put_md(pc, "- Guide place = output\n- Resume place = band\n- Spawns place = nonsense\n")
        check("place: a value that is not one of the key's two -> pane", [HG.place(pc, w) for w in ("guide", "resume", "spawns")] == ["pane"] * 3)
        put_md(pc, "- Resume = off\n- Guide = off\n")
        check("place: `Resume =` and `Guide =` are other keys, they do not set a place", [HG.place(pc, w) for w in ("guide", "resume", "spawns")] == ["pane"] * 3)
        put_md(pc, "- Guide place = pane\n- Resume place = pane\n- Spawns place = pane\n")
        mod(False)
        check("place: without the mod guide is band and resume/spawns are output, whatever the override says", [HG.place(pc, w) for w in ("guide", "resume", "spawns")] == ["band", "output", "output"])
        put_md(pc, None)
        check("override_source: default when no file sets the key", HG.override_source(pc, "Pace") == (None, "default", None))
        put_md(pc, "- Pace = fast\n")
        uc = Path(state, "user-claude.md"); uc.write_text("## abofles overrides\n- Pace = normal\n- Break = 25\n")
        HG.USER_CLAUDE_MD = uc
        check("override_source: project file wins, then user, with the path", HG.override_source(pc, "Pace") == ("fast", "project", str(Path(pc, "CLAUDE.md"))) and HG.override_source(pc, "Break") == ("25", "user", str(uc)))
        HG.USER_CLAUDE_MD = Path(os.environ["ABOFLES_USER_CLAUDE_MD"]); put_md(pc, None)
        names = {k for k in HG.OVERRIDE_KEYS}
        check("OVERRIDE_KEYS: every simple key of overrides.md plus the three places, each with kind, options and default",
              names >= {"Main session", "Session cap", "Context marks", "Receipt", "Break", "Agents", "Parallel", "Agent budgets", "Questions", "Language", "Guide", "Review gate", "Resume", "Pace", "Guide place", "Resume place", "Spawns place"}
              and all(v["kind"] in ("select", "number", "text", "list") and "default" in v and (v["kind"] == "select") == bool(v["options"]) for v in HG.OVERRIDE_KEYS.values())
              and all(HG.OVERRIDE_KEYS[k]["default"] == "pane" for k in ("Guide place", "Resume place", "Spawns place")))
        forms = ["Unit Test / Work = haiku·medium", "Codebase Exploration & Onboarding / Read cap = 200", "Topic: Notifications & Messaging = T3", "Reviewers: FIN = finance, security, tester",
                 "Workflow: Code Health = Read, Work, Verify", "Review: Security / T4 = opus·xhigh", "Financial & Amount Calculations / Verify = opus·xhigh"]
        check("COMPLEX_FORMS: every complex form of overrides.md matches one, no simple key does", all(any(r.match(f) for r in HG.COMPLEX_FORMS) for f in forms)
              and not any(r.match(f"{k} = {v['default'] or 'x'}") for k, v in HG.OVERRIDE_KEYS.items() for r in HG.COMPLEX_FORMS))

        # pane payload
        ps = "panesess1"; pd = tempfile.mkdtemp()
        mod(True)
        put_md(pd, "- Pace = fast\n- Unit Test / Work = haiku·medium\n- Bogus = 1\n")
        HG.memo_now(pd, "Task      write the pane\nLeft      tests; docs\nNext      ship it " + "x" * 700, ps)
        HG.memo_needs(pd, ps, "owner decision: cap per unit or per order?")
        run("start", {"session_id": ps, "cwd": pd}, led)
        pn_ = gstate(ps).get("pane") or {}
        check("pane: start writes the payload with v, ts, root, sid, places, resume, spawns, overrides, cmd", {"v", "ts", "root", "sid", "places", "resume", "spawns", "overrides", "cmd"} <= set(pn_) and pn_["v"] == 1 and pn_["sid"] == ps and pn_["root"] == pd)
        check("pane: places are the effective ones (mod on -> pane)", pn_["places"] == {"guide": "pane", "resume": "pane", "spawns": "pane"})
        rs_ = pn_["resume"] or {}
        check("pane: resume has head, now, left, next, needs (n + text), needs_open, last", set(rs_) == {"head", "now", "left", "next", "needs", "needs_open", "last"} and rs_["now"] == ["write the pane"] and rs_["left"] == ["tests", "docs"]
              and rs_["needs"] == [{"n": 1, "text": "owner decision: cap per unit or per order?"}] and rs_["needs_open"] == 1 and rs_["head"].startswith("📍 Resume") and "**" not in rs_["head"] and "`" not in rs_["head"] and rs_["last"] == [])
        check("pane: resume texts are clipped to PANE_TEXT (600) characters", len(rs_["next"][0]) == HG.PANE_TEXT and rs_["next"][0].endswith("…"))
        ov_ = pn_["overrides"]; okeys = {k["key"]: k for k in ov_["keys"]}
        check("pane: overrides.keys has one entry per simple key with key, kind, options, value, source, default", [k["key"] for k in ov_["keys"]] == list(HG.OVERRIDE_KEYS) and all(set(k) == {"key", "kind", "options", "value", "source", "default"} for k in ov_["keys"]))
        check("pane: a set key shows its value and source, an unset one its default", okeys["Pace"]["value"] == "fast" and okeys["Pace"]["source"] == "project" and okeys["Break"]["value"] == "10" and okeys["Break"]["source"] == "default")
        check("pane: overrides.raw holds the lines the table cannot show (complex forms, unknown keys), files names both CLAUDE.md",
              [r["line"] for r in ov_["raw"]] == ["Unit Test / Work = haiku·medium", "Bogus = 1"] and all(r["source"] == "project" for r in ov_["raw"]) and ov_["files"] == {"project": str(Path(pd, "CLAUDE.md")), "user": os.environ["ABOFLES_USER_CLAUDE_MD"]})
        check("pane: cmd.overrides is the script_cmd argv prefix for overrides.py with the session", pn_["cmd"]["overrides"][:2] == ["bash", HG.posix(HG.SCRIPTS_DIR / "py")] and pn_["cmd"]["overrides"][2].endswith("/scripts/overrides.py") and pn_["cmd"]["overrides"][-2:] == ["--session", ps])
        check("pane: spawns empty at start", pn_["spawns"] == {"live": [], "rows": [], "totals": {"spawns": 0, "tokens": 0, "usd": 0.0, "base_usd": 0.0, "saved_pct": 0, "open_fail": 0}})
        # post: a sync spawn, a background spawn; stop closes the background one
        okrep = "STATUS: done\nCONFIDENCE: high\nFACTS:\n- src/a.cs:1 — x\nGAPS: none"
        pa_ = lambda **kw: dict(agent("haiku", "low", cwd=pd, **kw), session_id=ps)
        run("post", pa_(resp=okrep), led)
        pn_ = gstate(ps)["pane"]
        check("pane: a sync spawn lands in spawns.rows after post, with side/model/effort/status/confidence/topic/tier/task and no live row",
              len(pn_["spawns"]["rows"]) == 1 and pn_["spawns"]["live"] == [] and {k: pn_["spawns"]["rows"][0][k] for k in ("side", "model", "effort", "status", "topic", "tier", "task")} == {"side": "Read", "model": "haiku", "effort": "low", "status": "done", "topic": "Unit Test", "tier": 2, "task": "q"} and pn_["spawns"]["rows"][0]["confidence"] in ("high", "medium", "low")
              and set(pn_["spawns"]["rows"][0]) == {"ts", "side", "model", "effort", "topic", "tier", "status", "confidence", "tokens", "usd", "base_usd", "description", "verdict", "task"} and pn_["spawns"]["totals"]["spawns"] == 1)
        bgd = dict(agent("sonnet", "medium", "abofles:abofles-worker", prompt="abofles: Unit Test / W · T2\nwrite the cap test\nLine cap: 30", cwd=pd), session_id=ps, tool_response={"status": "async_launched", "agentId": "bgagent1"})
        run("post", bgd, led)
        pn_ = gstate(ps)["pane"]
        check("pane: a background spawn is in live (side, model, effort, description, ts) and in rows as pending", len(pn_["spawns"]["live"]) == 1 and set(pn_["spawns"]["live"][0]) == {"side", "model", "effort", "description", "ts"}
              and pn_["spawns"]["live"][0]["model"] == "sonnet" and pn_["spawns"]["rows"][-1]["status"] == "pending")
        run("stop", {"session_id": ps, "cwd": pd, "agent_id": "bgagent1", "last_assistant_message": "STATUS: done\nCONFIDENCE: medium\nCHANGED:\n- a.cs — cap\nRAN: ok\nLEFT: none"}, led)
        pn_ = gstate(ps)["pane"]
        check("pane: SubagentStop refreshes the payload: live empties, the row is graded", pn_["spawns"]["live"] == [] and pn_["spawns"]["rows"][-1]["status"] == "done" and pn_["spawns"]["rows"][-1]["confidence"] == "medium")
        check("pane: totals count every row; with no transcripts tokens and usd are 0", pn_["spawns"]["totals"]["spawns"] == 2 and pn_["spawns"]["totals"]["tokens"] == 0)
        # cap and clip, from a long ledger
        long_rows = [{"ts": 1000 + i, "side": "Read", "model": "haiku", "effort": "low", "topic": "T" * 700, "tier": 2, "status": "done", "confidence": "high", "tokens": 1000, "usd": 0.01, "base_usd": 0.04, "description": "d" * 700, "task": "t" * 700, "verdict": "PASS" if i % 2 else "FAIL"} for i in range(40)]
        stx = {}
        HG.refresh_pane(pd, stx, ps, long_rows)
        px = stx["pane"]["spawns"]
        check("pane: rows are the last 30 ledger rows, oldest first", len(px["rows"]) == 30 and px["rows"][0]["ts"] == 1010 and px["rows"][-1]["ts"] == 1039)
        check("pane: topic, description and task are clipped to PANE_TEXT characters", all(len(r[k]) <= HG.PANE_TEXT for r in px["rows"] for k in ("topic", "description", "task")))
        check("pane: totals are the sums over all 40 rows (as bill.py), saved_pct from the real dollars", px["totals"] == {"spawns": 40, "tokens": 40000, "usd": 0.4, "base_usd": 1.6, "saved_pct": 75, "open_fail": 0})
        # Guide = off: the guide empties, the pane stays
        put_md(pd, "- Guide = off\n")
        run("prompt", {"session_id": ps, "cwd": pd}, led)
        sx = gstate(ps)
        check("pane: Guide = off -> st.guide is None and st.pane is still written (every guide refresh site refreshes both)", sx.get("guide") is None and sx["pane"]["spawns"]["totals"]["spawns"] == 2 and okeys is not None
              and {k["key"]: k for k in sx["pane"]["overrides"]["keys"]}["Guide"]["value"] == "off")
        put_md(pd, None)

        # resume at start and prompt, by place
        sf_ = Path(state, f"{ps}.json")
        def away(min_=11):
            j = json.loads(sf_.read_text()); j["last_activity"] = int(time.time()) - min_ * 60; sf_.write_text(json.dumps(j))
        mod(True)
        o_ = run("start", {"session_id": ps, "cwd": pd, "source": "compact"}, led)
        check("resume pane: startup/compact gives Claude the block as context only (no print-verbatim note)", isinstance(o_, str) and o_.count(HG.PANE_CONTEXT_NOTE) == 1 and "do not print it" in o_ and "📍 **Resume**" in o_ and "RESUME" not in o_ and "verbatim" not in o_)
        away(); o_ = ctx(run("prompt", {"session_id": ps, "cwd": pd}, led))
        check("resume pane: a prompt after a break gives Claude the block as context only (do-not-print prefix, as at start)", o_.count(HG.PANE_CONTEXT_NOTE) == 1 and "do not print it" in o_ and "📍 **Resume**" in o_ and "RESUME" not in o_ and "verbatim" not in o_)
        put_md(pd, "- Resume = off\n")
        o_ = run("start", {"session_id": ps, "cwd": pd, "source": "compact"}, led) or ""
        away(); o2_ = ctx(run("prompt", {"session_id": ps, "cwd": pd}, led))
        check("resume pane: Resume = off -> no note at all, at start or after a break", "📍" not in o_ and "resume context" not in o_ and "📍" not in o2_ and "RESUME" not in o2_)
        put_md(pd, "- Resume place = output\n")
        o_ = run("start", {"session_id": ps, "cwd": pd, "source": "compact"}, led)
        check("resume output: Resume place = output -> today's print-verbatim note at start", isinstance(o_, str) and "abofles RESUME (context was just compacted)" in o_ and "verbatim, first in your reply" in o_ and HG.PANE_CONTEXT_NOTE not in o_)
        away(); o_ = ctx(run("prompt", {"session_id": ps, "cwd": pd}, led))
        check("resume output: Resume place = output -> today's note after a break", "abofles RESUME (the user was away 11 min)" in o_ and "verbatim, first in your reply" in o_)
        put_md(pd, None); mod(False)
        o_ = run("start", {"session_id": ps, "cwd": pd, "source": "compact"}, led)
        check("resume output: the mod not installed -> today's print-verbatim note whatever the place", isinstance(o_, str) and "abofles RESUME (context was just compacted)" in o_ and HG.PANE_CONTEXT_NOTE not in o_)
        mod(True)

        # bill.py --history
        bl = subprocess.run([sys.executable, str(sdir_ := Path(__file__).resolve().parent / "bill.py"), "--history", "--session", ps, "--baseline", "opus·high"], capture_output=True, text=True,
                            env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_SESSION=ps))
        bl_lines = [l for l in bl.stdout.splitlines() if l.strip()]
        check("bill --history: one line per spawn (side, status, confidence, model·effort) then the totals line", bl.returncode == 0 and len(bl_lines) == 3 and "Read" in bl_lines[0] and "done" in bl_lines[0] and "Haiku 5.5 · Low" in bl_lines[0]
              and "Work" in bl_lines[1] and "Sonnet 5.5 · Medium" in bl_lines[1] and "medium" in bl_lines[1] and bl_lines[2].startswith("Total: 2 spawns") and "saved" in bl_lines[2])
        check("bill --history: no summary sections (By model, Top topics)", "By model" not in bl.stdout and "Top topics" not in bl.stdout)
        Path(led, "histsess.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
            {"ts": 1792000000, "side": "Work", "status": "done", "confidence": "high", "model": "sonnet", "effort": "medium", "tokens": 1000, "usd": 0.01, "base_usd": 0.04, "topic": "X", "verdict": "FAIL"},
            {"ts": 1792000060, "side": "Verify", "status": "partial", "confidence": "low", "model": "haiku", "effort": "low", "tokens": 2000, "usd": 0.03, "base_usd": 0.06, "topic": "Y"})))
        bh = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "bill.py"), "--history", "--baseline", "opus·high"], capture_output=True, text=True, env=dict(os.environ, ABOFLES_LEDGER_DIR=led, ABOFLES_SESSION="histsess")).stdout.splitlines()
        hl = [l for l in bh if "Work" in l or "Verify" in l]
        check("bill --history: a row with real usage shows tokens, $ and its saved %, a row without shows dashes",
              len(hl) == 2 and "1K tok" in hl[0] and "$0.01" in hl[0] and "saved 75%" in hl[0] and "partial" in hl[1] and "low" in hl[1] and "saved 50%" in hl[1])
        check("bill --history: the totals line carries the same sums as the pane payload",
              any("Total: " in l and "· 3K tokens · $0.04 (same tokens on Opus 5.5 · High: $0.10) · saved 60% · 1 open FAIL" in l for l in bh)
              and HG.history_totals([json.loads(l) for l in Path(led, "histsess.jsonl").read_text().splitlines()]) == {"spawns": 2, "tokens": 3000, "usd": 0.04, "base_usd": 0.1, "saved_pct": 60, "open_fail": 1})
        check("commands: /abofles:spawns runs bill.py --history; /abofles:pane names the mod and falls back to memo.py show + bill.py --history",
              "bill.py\" --history" in (HOOK.parent.parent / "commands" / "spawns.md").read_text() and (lambda t: "abofles-guide" in t and "memo.py\" show" in t and "bill.py\" --history" in t)((HOOK.parent.parent / "commands" / "pane.md").read_text()))
        check("commands: /abofles:pane tells the user to type /abofles-pane and prints the text only when the mod is not enabled",
              (lambda t: "`/abofles-pane`" in t and "only when the `abofles-guide` mod is not enabled" in t)((HOOK.parent.parent / "commands" / "pane.md").read_text()))


        # ── overrides.py: the pane editor's writer ──
        OVP = Path(__file__).resolve().parent / "overrides.py"
        def ovrun(args, req=None, user=None, cwd_=None):
            env = dict(os.environ, ABOFLES_STATE_DIR=state)
            if user: env["ABOFLES_USER_CLAUDE_MD"] = str(user)
            return subprocess.run([sys.executable, str(OVP), *args], input=json.dumps(req) if req is not None else "", capture_output=True, text=True, env=env, cwd=cwd_)
        def ovproj():
            d = Path(tempfile.mkdtemp()); return d
        P0 = "# Proj\n\nIntro - Pace = fast (prose)\n\n"
        BLK = "## abofles overrides\n\n- Pace = normal\n- Bogus = 1\n- Unit Test / Work = haiku·medium\n- Break = 5\n\nA note about the block.\n\n"
        TAIL = "## Other\n- Break = 99\nlast line without newline"
        d1 = ovproj(); f1 = d1 / "CLAUDE.md"; f1.write_bytes((P0 + BLK + TAIL).encode())
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d1)], {"set": {"Pace": "fast", "Receipt": "savings 30"}})
        t_ = f1.read_text(); head_, tail_ = (P0 + BLK).split("- Pace = normal")[0], BLK.split("- Break = 5\n")[1] + TAIL
        check("overrides set: exit 0, prints the new overrides JSON with the value and its project source", r_.returncode == 0 and (lambda j: {k["key"]: k for k in j["keys"]}["Pace"]["value"] == "fast" and {k["key"]: k for k in j["keys"]}["Receipt"]["source"] == "project")(json.loads(r_.stdout)))
        check("overrides set: an existing key is edited in place (same line, same neighbours)", "- Pace = fast\n- Bogus = 1\n- Unit Test / Work = haiku·medium\n- Break = 5\n" in t_)
        check("overrides set: a new key lands after the block's last bullet, before its prose", "- Break = 5\n- Receipt = savings 30\n\nA note about the block." in t_)
        check("overrides set: every byte outside the block's bullets is kept (prose before, prose in and after the block, the next section, no final newline)", t_.startswith(P0 + "## abofles overrides\n\n- Pace = fast") and t_.endswith(tail_) and t_.count("Intro - Pace = fast (prose)") == 1 and "- Break = 99\nlast line without newline" in t_)
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d1)], {"set": {"Pace": "", "Break": "", "Receipt": "short"}})
        t2_ = f1.read_text()
        check("overrides set: \"\" removes the key's line in the block only (the `Break` in `## Other` stays), the others stay", "\n- Pace" not in t2_ and "- Break = 5" not in t2_ and "- Break = 99\nlast line without newline" in t2_ and "- Receipt = short" in t2_ and "- Bogus = 1" in t2_)
        check("overrides set: unknown keys, complex forms and prose are kept", "- Bogus = 1\n- Unit Test / Work = haiku·medium\n" in t2_ and "A note about the block." in t2_ and "Intro - Pace = fast (prose)" in t2_)
        # hardening: a planted temp-name symlink is never written through, a CLAUDE.md linking out of the project is refused,
        # a non-UTF-8 file and an over-long value are one-line refusals, a BOM is kept, and no temp file is left behind
        d9 = ovproj(); victim_ = d9 / "victim.txt"; victim_.write_text("keep me\n"); (d9 / "CLAUDE.md").write_text("# P\n")
        (d9 / "CLAUDE.md.abofles-tmp").symlink_to(victim_)
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d9)], {"set": {"Pace": "fast"}})
        check("overrides hardening: a symlink at the old temp name is not written through (the temp is a fresh mkstemp file)", r_.returncode == 0 and victim_.read_text() == "keep me\n" and "- Pace = fast" in (d9 / "CLAUDE.md").read_text() and not (d9 / "CLAUDE.md").is_symlink())
        check("overrides hardening: no temp file is left in the folder", not [x for x in d9.iterdir() if x.name.endswith(".abofles-tmp") and not x.is_symlink()])
        d10 = ovproj(); out_ = Path(tempfile.mkdtemp()) / "outside.md"; out_.write_text("# outside\n"); (d10 / "CLAUDE.md").symlink_to(out_)
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d10)], {"set": {"Pace": "fast"}})
        check("overrides hardening: a project CLAUDE.md that links out of the project is refused (exit 2), the target untouched", r_.returncode == 2 and "outside the project" in r_.stderr and out_.read_text() == "# outside\n")
        d11 = ovproj(); (d11 / "CLAUDE.md").write_bytes(b"# P\n\xff\xfe bad\n")
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d11)], {"set": {"Pace": "fast"}})
        check("overrides hardening: a CLAUDE.md that is not UTF-8 gives one line and exit 2, no traceback", r_.returncode == 2 and "not UTF-8" in r_.stderr and "Traceback" not in r_.stderr)
        d12 = ovproj(); (d12 / "CLAUDE.md").write_bytes(b"\xef\xbb\xbf# P\n\n## abofles overrides\n\n- Pace = normal\n")
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d12)], {"set": {"Pace": "fast"}})
        check("overrides hardening: a UTF-8 BOM is kept and the block under the first heading is still found", r_.returncode == 0 and (d12 / "CLAUDE.md").read_bytes() == b"\xef\xbb\xbf# P\n\n## abofles overrides\n\n- Pace = fast\n")
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d12)], {"set": {"Language": "x" * 600}})
        r2_ = ovrun(["set", "--scope", "project", "--cwd", str(d12)], {"set": {}, "raw": ["Topic: " + "y" * 600 + " = T3"]})
        check("overrides hardening: a value or a line over 500 characters is refused (exit 2)", r_.returncode == 2 and "longer than 500" in r_.stderr and r2_.returncode == 2 and "longer than 500" in r2_.stderr)
        if os.name != "nt":
            pdir_ = Path(tempfile.mkdtemp()) / "st"; pdir_.mkdir(mode=0o755); os.chmod(pdir_, 0o755); HG.private_dir(pdir_); nd_ = Path(tempfile.mkdtemp()) / "a" / "b"; HG.private_dir(nd_)
            check("state and ledger folders are owner-only: an older 755 folder is tightened, a new one is made 700", pdir_.stat().st_mode & 0o777 == 0o700 and nd_.stat().st_mode & 0o777 == 0o700)
        before_ = f1.read_bytes(); r_ = ovrun(["set", "--scope", "project", "--cwd", str(d1)], {"set": {"Pace": ""}})
        check("overrides set: removing a key that is not there changes nothing", r_.returncode == 0 and f1.read_bytes() == before_)
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d1)], {"set": {}, "raw": ["Topic: Billing = T3", "- Reviewers: FIN = tester"]})
        t3_ = f1.read_text()
        check("overrides set: raw lines replace only the complex-form lines (the old cell form goes), unknown key and simple keys stay", r_.returncode == 0 and "Unit Test / Work" not in t3_ and "- Topic: Billing = T3\n" in t3_ and "- Reviewers: FIN = tester\n" in t3_ and "- Bogus = 1" in t3_ and "- Receipt = short" in t3_ and "A note about the block." in t3_)
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d1)], {"set": {}, "raw": ["Topic: Billing = T3", "Reviewers: FIN = tester"]})
        r_ = ovrun(["set", "--scope", "project", "--cwd", str(d1)], {"set": {}, "raw": ["Bogus = 1", "Topic: Billing = T3", "Reviewers: FIN = tester"]})
        check("overrides set: an unknown line the pane lists with the forms may stay in raw (kept once, in place)", r_.returncode == 0 and f1.read_text() == t3_ and f1.read_text().count("- Bogus = 1") == 1)
        check("overrides set: the same raw lines again change nothing", r_.returncode == 0 and f1.read_text() == t3_)
        d2 = ovproj()
        check("overrides set: no CLAUDE.md yet -> the project's CLAUDE.md is created with the block", ovrun(["set", "--scope", "project", "--cwd", str(d2)], {"set": {"Guide place": "band"}}).returncode == 0 and (d2 / "CLAUDE.md").read_text() == "## abofles overrides\n\n- Guide place = band\n")
        d3 = ovproj(); (d3 / "CLAUDE.md").write_bytes(b"# T\r\nbody\r\n"); ovrun(["set", "--scope", "project", "--cwd", str(d3)], {"set": {"Pace": "fast"}})
        check("overrides set: a file without the block gets it appended after a blank line, the old bytes (CRLF too) kept", (d3 / "CLAUDE.md").read_bytes() == b"# T\r\nbody\r\n\r\n## abofles overrides\r\n\r\n- Pace = fast\r\n")
        d3b = ovproj(); (d3b / "CLAUDE.md").write_text("# T\nbody"); ovrun(["set", "--scope", "project", "--cwd", str(d3b)], {"set": {"Pace": "fast"}})
        check("overrides set: ... and \"\\n## abofles overrides\\n\\n\" when the file did not end with a newline", (d3b / "CLAUDE.md").read_text() == "# T\nbody\n\n## abofles overrides\n\n- Pace = fast\n")
        d3c = ovproj(); (d3c / "CLAUDE.md").write_text("# T\n"); ovrun(["set", "--scope", "project", "--cwd", str(d3c)], {"set": {"Pace": ""}})
        check("overrides set: removing from a file without a block does not create one", (d3c / "CLAUDE.md").read_text() == "# T\n")
        d4 = ovproj(); (d4 / ".claude").mkdir(); (d4 / "CLAUDE.md").write_text("# no block here\n"); (d4 / ".claude" / "CLAUDE.md").write_text("# T\n\n## Abofles Overrides\n- Pace = fast\n")
        ovrun(["set", "--scope", "project", "--cwd", str(d4)], {"set": {"Break": "7"}})
        check("overrides set: project scope picks .claude/CLAUDE.md when it holds the block (heading case ignored), CLAUDE.md untouched",
              (d4 / ".claude" / "CLAUDE.md").read_text() == "# T\n\n## Abofles Overrides\n- Pace = fast\n- Break = 7\n" and (d4 / "CLAUDE.md").read_text() == "# no block here\n")
        check("overrides: the pane's files.project is the file the writer picks (.claude/CLAUDE.md when it holds the block)", json.loads(ovrun(["get", "--json", "--cwd", str(d4)]).stdout)["files"]["project"] == str(d4 / ".claude" / "CLAUDE.md")
              and json.loads(ovrun(["get", "--json", "--cwd", str(d2)]).stdout)["files"]["project"] == str(d2 / "CLAUDE.md"))
        d5 = ovproj(); uf = Path(tempfile.mkdtemp()) / "sub" / "CLAUDE.md"
        r_ = ovrun(["set", "--scope", "user", "--cwd", str(d5)], {"set": {"Language": "Arabic"}}, user=uf)
        check("overrides set: user scope writes ABOFLES_USER_CLAUDE_MD (parent folder created), not the project", r_.returncode == 0 and uf.read_text() == "## abofles overrides\n\n- Language = Arabic\n" and not (d5 / "CLAUDE.md").exists()
              and json.loads(r_.stdout)["files"]["user"] == str(uf) and {k["key"]: k for k in json.loads(r_.stdout)["keys"]}["Language"]["source"] == "user")
        check("overrides: no atomic leftovers (the .abofles-tmp file is renamed away)", not list(uf.parent.glob("*.abofles-tmp")) and not list(d1.glob("*.abofles-tmp")))
        bad = [({"Receipt": "everything"}, "Receipt"), ({"Receipt": "savings x"}, "Receipt"), ({"Break": "soon"}, "Break"), ({"Agents": "many"}, "Agents"), ({"Pace": "turbo"}, "Pace"),
               ({"Agent budgets": "1, 2, 3"}, "Agent budgets"), ({"Context marks": "a, b"}, "Context marks"), ({"Nope": "1"}, "Nope"), ({"Language": "Ara\nbic"}, "Language")]
        d6 = ovproj(); (d6 / "CLAUDE.md").write_text("## abofles overrides\n- Pace = fast\n"); b6_ = (d6 / "CLAUDE.md").read_bytes()
        rs_ = [ovrun(["set", "--scope", "project", "--cwd", str(d6)], {"set": dict(sets_, Parallel="4")}) for sets_, _ in bad]
        check("overrides set: invalid values (bad option, savings x, Break soon, Agents many, short budgets, non-numbers, unknown key, two lines) exit 2 with one line naming the key",
              all(r.returncode == 2 and len(r.stderr.strip().splitlines()) == 1 and k in r.stderr for r, (_, k) in zip(rs_, bad)) and all(r.stdout == "" for r in rs_))
        check("overrides set: ... and nothing is written, not even the valid key sent along", (d6 / "CLAUDE.md").read_bytes() == b6_)
        for req_ in ({"set": {}, "raw": ["Topic: Billing"]}, {"set": {}, "raw": ["Pace = fast"]}):
            check(f"overrides set: raw line {req_['raw'][0]!r} (not a complex form / a simple key) exits 2", ovrun(["set", "--scope", "project", "--cwd", str(d6)], req_).returncode == 2)
        check("overrides set: not JSON on stdin / no scope exit 2", ovrun(["set", "--scope", "project", "--cwd", str(d6)]).returncode == 2 and ovrun(["set", "--cwd", str(d6)], {"set": {}}).returncode == 2)
        good = [("Agents", "AUTO", "auto"), ("Receipt", "savings 30", "savings 30"), ("Break", "off", "off"), ("Context marks", "100,150, 180", "100, 150, 180"), ("Agent budgets", "1, 2, 5, 8", "1, 2, 5, 8")]
        d7 = ovproj()
        ok7_ = ovrun(["set", "--scope", "project", "--cwd", str(d7)], {"set": {k: v for k, v, _ in good}}).returncode == 0 and ovrun(["set", "--scope", "project", "--cwd", str(d7)], {"set": {"Agents": 7}}).returncode == 0
        ok7_ = ok7_ and ovrun(["set", "--scope", "project", "--cwd", str(d7)], {"set": {"Agents": "auto"}}).returncode == 0
        t7_ = (d7 / "CLAUDE.md").read_text()
        check("overrides set: Agents N/auto, Receipt `savings N`, Break off, lists of numbers are accepted and written normalised", ok7_ and all(f"- {k} = {w}\n" in t7_ for k, _, w in good))
        # a change between our read and our write: abort, exit 3, nothing written
        import importlib.util as _iuo
        _so = _iuo.spec_from_file_location("abofles_overrides_race", str(OVP)); OVM = _iuo.module_from_spec(_so); _so.loader.exec_module(OVM)
        dr = ovproj(); fr = dr / "CLAUDE.md"; fr.write_text("## abofles overrides\n- Pace = fast\n")
        _edit = OVM.edit_text
        def _racing(old, sets, raw):
            out = _edit(old, sets, raw); fr.write_text("## abofles overrides\n- Pace = fast\n- Break = 7\n"); return out  # another writer lands between read and write
        OVM.edit_text = _racing
        _argv, _stdin, _env = sys.argv, sys.stdin, os.environ.get("ABOFLES_STATE_DIR")
        sys.argv = ["overrides.py", "set", "--scope", "project", "--cwd", str(dr)]; sys.stdin = io.StringIO(json.dumps({"set": {"Pace": "normal"}})); os.environ["ABOFLES_STATE_DIR"] = state
        _err, _out = io.StringIO(), io.StringIO()
        import contextlib as _cl
        with _cl.redirect_stderr(_err), _cl.redirect_stdout(_out):
            rc_ = OVM.main()
        sys.argv, sys.stdin = _argv, _stdin
        if _env is None: os.environ.pop("ABOFLES_STATE_DIR", None)
        else: os.environ["ABOFLES_STATE_DIR"] = _env
        check("overrides set: the file changed between read and write -> exit 3, the other writer's bytes stay, no temp file left, one stderr line",
              rc_ == 3 and fr.read_text() == "## abofles overrides\n- Pace = fast\n- Break = 7\n" and not list(dr.glob("*.abofles-tmp"))
              and _err.getvalue() == "abofles: CLAUDE.md changed while saving — reload the pane and save again\n" and _out.getvalue() == "")
        # get, and the pane payload after a set
        g_ = ovrun(["get", "--json", "--cwd", str(d7)])
        check("overrides get --json: prints the pane's overrides payload (files, keys with kind/options/value/source/default, raw)", g_.returncode == 0 and (lambda j: set(j) == {"files", "keys", "raw"} and [k["key"] for k in j["keys"]] == list(HG.OVERRIDE_KEYS) and {k["key"]: k for k in j["keys"]}["Agents"]["value"] == "auto")(json.loads(g_.stdout)))
        ds = ovproj(); ss = "ovsess1"; (ds / "CLAUDE.md").write_text("## abofles overrides\n- Pace = fast\n")
        run("start", {"session_id": ss, "cwd": str(ds)}, led)
        stamp_ = gstate(ss)["pane"]["ts"]; time.sleep(0)  # the session's state exists; the pane is refreshed by the set
        r_ = ovrun(gstate(ss)["pane"]["cmd"]["overrides"][3:] + ["set", "--scope", "project", "--cwd", str(ds)], {"set": {"Pace": "normal", "Guide place": "band"}})  # the argv the pane runs: `overrides.py --session S set --scope …`
        pk_ = {k["key"]: k for k in gstate(ss)["pane"]["overrides"]["keys"]}
        check("overrides set: with a session, the state's pane payload is refreshed under the lock (value, source and places follow) and the output is the same overrides",
              r_.returncode == 0 and pk_["Pace"]["value"] == "normal" and pk_["Guide place"]["value"] == "band" and gstate(ss)["pane"]["places"]["guide"] == "band" and json.loads(r_.stdout) == gstate(ss)["pane"]["overrides"])
        check("overrides set: ... the session's other state (cmd argv, root, sid) is kept", gstate(ss)["pane"]["cmd"]["overrides"][-2:] == ["--session", ss] and gstate(ss)["pane"]["sid"] == ss)
        rd_ = (HOOK.parent.parent / "README.md").read_text()
        sec_ = rd_[rd_.index("### Overrides"):]
        check("README: the Overrides table lists every OVERRIDE_KEYS key", all(f"| `{k}` |" in sec_ for k in HG.OVERRIDE_KEYS))
        form_marks = ["Topic / Side cap", "Topic / Side =", "Topic: Name", "Reviewers:", "Workflow:", "Review: <Tag>"]  # COMPLEX_FORMS order
        check("README: ... and every COMPLEX_FORMS form (one row each)", len(form_marks) == len(HG.COMPLEX_FORMS) and all(re.search(r"^\| `" + re.escape(m), sec_, re.M) for m in form_marks))
        check("README: ... with defaults from the code, the pane editor, /abofles:pane and /abofles:spawns", all(f"| `{k}` |" in sec_ and (v["default"] in sec_ if v["default"] else True) for k, v in HG.OVERRIDE_KEYS.items()) and "/abofles:pane" in sec_ and "/abofles:spawns" in sec_ and "pane" in sec_.split("| `Main session`")[0])
        check("overrides.md: the three place forms are described and the form count matches the code", all(f"`{w} place = " in (HOOK.parent.parent / "skills/abofles/references/overrides.md").read_text() for w in ("Guide", "Resume", "Spawns"))
              and f"Twenty-three forms" in (HOOK.parent.parent / "skills/abofles/references/overrides.md").read_text() and len(HG.OVERRIDE_KEYS) + len(HG.COMPLEX_FORMS) == 23)

    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
