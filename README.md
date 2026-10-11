# Sajadh92 Claude Code plugins

A Claude Code plugin marketplace.

| Plugin | What it does |
|---|---|
| [abofles](plugins/abofles) | Abo Fles (ابو فليس) counts every token: routes each subagent to the right model and effort. |

## Install

```
/plugin marketplace add Sajadh92/claude-plugins
/plugin install abofles@sajadh92
```

Then add to `~/.claude/CLAUDE.md`: `- Always use the abofles skill before spawning subagents, and at the start of each coding task to check the main session model.`

See [plugins/abofles/README.md](plugins/abofles/README.md) for a quick start, the override block and the full matrix. Changes: [CHANGELOG.md](CHANGELOG.md). License: MIT.
