# audit-trail

Logs every Claude tool call (input and output) to JSON files.

## What it does

- **PreToolUse hook**: Logs tool name + input to `~/.claude/logs/pre_tool_use.json`; logs Task tool spawns to `~/.claude/logs/subagent_spawns.log`
- **PostToolUse hook**: Logs full tool event (name + input + output) to `~/.claude/logs/post_tool_use.json`

Useful for debugging, auditing, and understanding what Claude did in a session.

## Installation

Add to `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "audit-trail@local": { "path": "/path/to/audit-trail" }
  }
}
```

## Log files

| File | Contents |
|------|---------|
| `~/.claude/logs/pre_tool_use.json` | Tool name + input before execution |
| `~/.claude/logs/post_tool_use.json` | Full tool event including output |
| `~/.claude/logs/subagent_spawns.log` | When Task tool spawns subagents |

## License

MIT
