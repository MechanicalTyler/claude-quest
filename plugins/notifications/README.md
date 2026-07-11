# notifications

System notifications when Claude completes tasks or needs input (macOS + Slack). Fully standalone — no other plugin required.

## What it does

- **Notification hook**: Sends message to Slack app + macOS notification when Claude needs user input (actionable types only)
- **Stop hook**: Sends message to Slack app + macOS "Task Complete" notification when Claude finishes (subagent sessions are skipped entirely). If any subagent dispatched by this session is still active, sends no notification instead — a genuine `needs_input` (the main agent asked a question) always overrides this
- **PreToolUse hook**: Pure observer — marks the session as having active work when an `Agent` dispatch (a subagent call) or a backgrounded `Bash` call is seen; every other tool is a no-op. Always exits `0` and never emits a permission-decision payload, so it can never block a tool call
- **SubagentStop hook**: Flips one active-subagent marker for the session to `completed`, keeping the Stop hook's suppression check accurate
- **SessionEnd hook**: Clears the session's active-subagent markers so nothing leaks on disk

The PreToolUse/SubagentStop/SessionEnd hooks exist entirely to power the Stop hook's "don't notify while a background subagent is still running" suppression, via `subagent_tracker.py` — an independent local marker store scoped to this plugin (`~/.claude/notifications/active-subagents/`). This is fully self-contained: no shared code or file reads with the [`attention-hub`](../attention-hub) plugin, even when both are installed together.

## Docker containers and remote servers

If the hub-reporting features you want are the [`attention-hub`](../attention-hub) dashboard, install that plugin separately — it is now fully standalone and needs no configuration from this plugin.

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `CLAUDE_NOTIFY_MACOS` | enabled | Set to `0`/`false`/`no`/`off` to disable macOS notifications |
| `CLAUDE_NOTIFY_SLACK` | enabled | Set to `0`/`false`/`no`/`off` to disable Slack notifications |

Both notification channels behave exactly as before when the flags are unset.

## Requirements

- macOS notifications: `brew install terminal-notifier`
- Slack app: must be running at `http://localhost:8080` (optional, gracefully degrades)

## Installation

Add to `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "notifications@local": { "path": "/path/to/notifications" }
  }
}
```

## Running tests

```bash
uv run --with pytest --with requests python -m pytest tests/
```

## License

MIT
