# notifications

System notifications when Claude completes tasks or needs input, plus a self-hosted attention hub that tracks which of your Claude sessions is waiting on you.

## What it does

- **Notification hook**: Sends message to Slack app + macOS notification when Claude needs user input (actionable types only); reports `waiting` to the attention hub
- **PreToolUse hook**: Pure observer — marks the session as having an active subagent when a `Task` dispatch is seen (every other tool is a no-op). Always exits `0` and never emits a permission-decision payload, so it can never block a tool call
- **Stop hook**: Sends message to Slack app + macOS "Task Complete" notification when Claude finishes; reports `needs_input` or `done` to the attention hub (subagent sessions are skipped entirely). If any subagent dispatched by this session is still active, reports `working` instead of `done` and sends no notification — a genuine `needs_input` (the main agent asked a question) always overrides this
- **UserPromptSubmit hook**: Reports `working` to the attention hub — answering a session automatically clears its needs-attention state
- **PostToolUse hook**: Reports `working` to the attention hub when a tool completes after the session was flagged `waiting` (a tool can only complete once a pending permission/question was answered) — so answering a permission dialog flips the row back to green without a new prompt. Gated by a per-session marker file under `~/.claude/notifications/waiting-markers/`, so on normal tool calls (no marker) it exits instantly with zero network activity. Note: the flip happens when the approved tool *finishes* — a long-running approved command keeps showing `waiting` until it completes
- **SessionEnd hook**: Removes the session from the attention hub (and cleans up its waiting marker and any active-subagent markers)
- **SubagentStop hook**: No notifications. Clears one active-subagent marker for the session so the Stop hook's active-subagent count stays accurate

## Attention hub

Many concurrent Claude sessions (local, docker, remote servers) make macOS/Slack notifications spammy and hard to track. This plugin's hooks report each session's state to an attention-hub dashboard — a small self-hosted server with a web UI showing one color-coded row per session, sorted needs-attention first.

The hub itself is a separate, standalone plugin so it can be installed and run independently of `notifications`. See the [`attention-hub`](../attention-hub) plugin for installation, running the dashboard, and its HTTP API.

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
- Attention hub: Python 3.8+ (stdlib only), started manually (optional, gracefully degrades)

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
