# notifications

System notifications when Claude completes tasks or needs input (macOS + Slack). Optionally also reports session state to the [`attention-hub`](../attention-hub) dashboard, if that plugin is installed alongside this one.

## What it does

- **Notification hook**: Sends message to Slack app + macOS notification when Claude needs user input (actionable types only); if attention-hub is installed, also reports `waiting` to its dashboard
- **Stop hook**: Sends message to Slack app + macOS "Task Complete" notification when Claude finishes; if attention-hub is installed, also reports `needs_input` or `done` (subagent sessions are skipped entirely). If any subagent dispatched by this session is still active, reports `working` instead of `done` and sends no notification — a genuine `needs_input` (the main agent asked a question) always overrides this

That's the entire hook set this plugin ships. All attention-tracking hooks (PreToolUse, PostToolUse, UserPromptSubmit, SessionEnd, SubagentStop) and the dashboard server now live in the separate [`attention-hub`](../attention-hub) plugin — install it to get the full dashboard experience for any agent, Claude Code or otherwise.

## Optional attention-hub integration

Many concurrent Claude sessions (local, docker, remote servers) make macOS/Slack notifications spammy and hard to track. If the [`attention-hub`](../attention-hub) plugin is also installed, this plugin's Notification and Stop hooks additionally report each session's state to its dashboard — a small self-hosted server with a web UI showing one color-coded row per session, sorted needs-attention first.

This is a soft dependency, auto-discovered at hook run time (a sibling-plugin lookup, with an optional `CLAUDE_ATTENTION_HUB_CLIENT_PATH` override) — nothing to configure. **If attention-hub is not installed, notifications still works exactly as before this integration: macOS/Slack notifications fire normally, hub reporting is simply skipped.** One behavior does depend on attention-hub actually being installed: the Stop hook's "don't notify while a background subagent is still running" suppression relies on active-subagent markers written by attention-hub's own PreToolUse/SubagentStop hooks. Running notifications standalone means every Stop is treated as a real completion — install both plugins together to restore that refinement.

### Docker containers and remote servers

Hooks find the hub via `CLAUDE_ATTENTION_HUB_URL` (default `http://localhost:8765`). Point it at the hub host's reachable address and optionally set a friendly host label:

```bash
# in a docker container
export CLAUDE_ATTENTION_HUB_URL=http://host.docker.internal:8765
export CLAUDE_HOST_LABEL=docker-build-box

# on a remote server (hub reachable over VPN/LAN)
export CLAUDE_ATTENTION_HUB_URL=http://10.0.0.5:8765
export CLAUDE_HOST_LABEL=staging-server
```

Sessions running inside a container are detected automatically — via `/.dockerenv` (Docker), `/run/.containerenv` (Podman), the `container` env var (Podman/systemd-nspawn), `KUBERNETES_SERVICE_HOST` (Kubernetes), or an overlayfs root filesystem as a fallback — and badged `container` in the expanded card. The hostname inside Docker defaults to the bare container ID, so give containers a readable host name with `CLAUDE_HOST_LABEL` (as above) or `docker run --hostname my-name`.

If the hub is down or unreachable, hooks degrade gracefully: they never block or error a Claude session, and macOS/Slack notifications still work.

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `CLAUDE_ATTENTION_HUB_URL` | `http://localhost:8765` | Attention hub base URL |
| `CLAUDE_HOST_LABEL` | machine hostname | Host name shown on the dashboard |
| `CLAUDE_NOTIFY_MACOS` | enabled | Set to `0`/`false`/`no`/`off` to disable macOS notifications |
| `CLAUDE_NOTIFY_SLACK` | enabled | Set to `0`/`false`/`no`/`off` to disable Slack notifications |

Both notification channels behave exactly as before when the flags are unset.

## Requirements

- macOS notifications: `brew install terminal-notifier`
- Slack app: must be running at `http://localhost:8080` (optional, gracefully degrades)
- Attention hub integration: install the [`attention-hub`](../attention-hub) plugin alongside this one (optional, gracefully degrades if absent)

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
