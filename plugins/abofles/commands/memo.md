---
description: "Update the Now section of the work memo (task, done, left, decisions, next, verify) so the session can be compacted or paused without losing the thread; then run /compact yourself"
allowed-tools: Bash(python3 *), Bash(git *)
---

Update the memo's **Now** section for this session, then tell the user to run `/compact`.

The memo is two files in the project root — the directory the session started in, whatever `cd` happened since: the main memo `.claude/abofles-memo.md` (**Needs you**, **Decisions** = notes settled in chat, **Sessions** = one index line per session with a link) and this session's file `.claude/abofles-memo.d/<session>.md` (**Now**, **Journal** = one line per receipt, **Decisions** = the questions this session asked with their answers). `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/memo.py" path mine --session "${CLAUDE_SESSION_ID}"` prints the session file. The hook stamps Now with the time it was written; the resume block shows that age. The hooks also rewrite Now from each receipt (stamped `· from receipt`); this command writes the richer version before a compact. Everything else is kept by the hooks; never rewrite it.

1. Run `git status --short` first if the project is a git repository (first 20 lines go under `Tree`).

2. Write the Now section in one command (it lands in this session's file; the main memo's index line follows it) — short lines, repo-relative paths, no transcript quotes, exactly these labels padded with spaces:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/memo.py" now --session "${CLAUDE_SESSION_ID}" <<'EOF'
Task      <the current task in one line, or "none — between tasks">
Done      <what is finished, one line per item, files named>
Left      <what is not finished, one line per item — repeat the `Left` label on every line>
Decisions <decisions the user made this session that must not be reopened, one per line>
Next      <the first thing to do after the compact, one line>
Verify    <the command that proves the current state, with its expected result>
Tree      <first 20 lines of git status --short, or "clean">
EOF
```

3. Reply with two lines: the session file path (the script prints it), then: `Memo saved. Now run /compact — the resume block is shown again after it.` The user runs `/compact` themselves (a command cannot). When the user typed `/abofles:memo`, those two lines are the whole reply. When the context watch made you run it mid-turn, print the two lines and continue the turn.
