---
description: "Write the hand-off memo (task, done, left, decisions, next step) so the session can be compacted without losing the thread; then run /compact yourself"
argument-hint: "[path]"
allowed-tools: Read, Write, Bash(git *)
---

Write the hand-off memo for this session, then tell the user to run `/compact`. Arguments: $ARGUMENTS

1. Path: the argument if given, else `.claude/abofles-memo.md` in the project root. Overwrite it; the previous memo is the compacted past.

2. Content — exactly these sections, short lines, repo-relative paths, no transcript quotes:

```
# Abo Fles memo — <date> <time>

Task      <the current task in one line, or "none — between tasks">
Done      <what is finished, one line per item, files named>
Left      <what is not finished, one line per item>
Decisions <decisions the user made this session that must not be reopened, one per line>
Open      <follow-ups from receipts: partial, low, ATTENTION, open FAIL, owner decisions>
Next      <the first thing to do after the compact, one line>
Verify    <the command that proves the current state, with its expected result>
```

3. Run `git status --short` **before** writing the memo (so the memo file itself is not listed) and append its first 20 lines under `Tree` if the project is a git repository.

4. Reply with two lines: the memo path, then: `Memo saved. Now run /compact — the memo is read back with the project files after it.` The user runs `/compact` themselves (a command cannot). When the user typed `/abofles:memo`, those two lines are the whole reply. When the context watch made you run it mid-turn, print the two lines and continue the turn.
