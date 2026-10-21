# Sajadh92 Claude Code plugins

A Claude Code plugin marketplace.

| Plugin | What it does |
|---|---|
| [abofles](plugins/abofles) | Abo Fles (ابو فليس) counts every token: routes each subagent to the right model and effort. |
| [abofles-guide](plugins/abofles-guide) 0.3.0 | Companion mod for abofles: the `🧭 next` guide as a band above the prompt box, with Use, Re-check, Resolve (confirm + Undo), Memo, Copy and Hide buttons. |

## Install

```
/plugin marketplace add Sajadh92/claude-plugins
/plugin install abofles@sajadh92
/plugin install abofles-guide@sajadh92   # optional: the band above the prompt box
```

## Updates

Auto-update is off by default for third-party marketplaces. Turn it on once: run `/plugin`, open **Marketplaces**, pick `sajadh92`, choose **Enable auto-update**. Claude Code then installs each new version at startup.

To update by hand instead:

```
/plugin marketplace update sajadh92
```

Then restart Claude Code.

Then add to `~/.claude/CLAUDE.md`: `- Use the abofles skill once per session, before the first coding task or subagent (never re-invoke it per task: it stays in context), and tier every task with it.`

See [plugins/abofles/README.md](plugins/abofles/README.md) for a quick start, the override block and the full matrix. Changes: [CHANGELOG.md](CHANGELOG.md). License: MIT.
