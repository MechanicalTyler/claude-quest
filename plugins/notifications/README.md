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

Many concurrent Claude sessions (local, docker, remote servers) make macOS/Slack notifications spammy and hard to track. The attention hub is a small self-hosted server every session reports to; its web dashboard shows one color-coded row per session:

- **Red** — `waiting` (blocked on a permission/question prompt) or `needs_input` (finished its turn by asking you something)
- **Yellow** — `done` (task complete, awaiting your review)
- **Green** — `working` (you answered; Claude is busy)

Each card's title is the session name (set via `/rename`), falling back to the session ID for unnamed sessions, with the project (repo folder) as the subtitle. Cards sort needs-attention first, show time in state, the latest message snippet, and last-update age, refresh every 3 seconds, and have a per-card dismiss control for crashed/abandoned sessions. Sessions silent for over 24 hours are pruned automatically.

### Expanded card view

Clicking a card expands it; any number of cards may be open at once, and open cards stay open across the 3-second refresh. The detail panel shows:

- **Host** — with a `container` badge when the session runs inside a container
- **Full session ID** and the **full last message**
- **Last update** age
- **Status history** — the last 20 state transitions (most recent first), each with the time it was entered, how long it lasted, and a `manual` badge when the change came from a manual override rather than a hook

### Forcing a status

If the hub falls out of sync with reality (Claude is working but the card still says waiting), the **force status** buttons in the expanded panel set the state by hand — the current state's button is disabled. The override applies immediately and shows up in the history as `manual`, but it is not pinned: the next genuine hook event for the session overwrites it, so the hub always self-heals toward reality.

The buttons call a small API you can also script against:

```bash
curl -X POST http://localhost:8765/api/sessions/<session-id>/state \
  -H 'Content-Type: application/json' -d '{"state": "working"}'
```

Responses: `200` with the updated record, `400` for a missing/invalid state or malformed body, `404` for an unknown session — forcing never creates a session.

### Starting the hub

The hub is a manual-start, zero-dependency Python script (run it in tmux/screen; it does not survive reboot):

```bash
uv run hub/attention_hub.py
```

Options:

| Flag | Default | Meaning |
|------|---------|---------|
| `--port` | `8765` | Port to listen on |
| `--bind` | `0.0.0.0` | Bind address (`127.0.0.1` for localhost only) |
| `--state-file` | `~/.claude/attention_hub_state.json` | JSON persistence file (sessions survive hub restarts) |
| `--prune-hours` | `24` | Drop sessions silent for this many hours |

Open `http://localhost:8765/` for the dashboard.

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

### Security

The hub has **no authentication or TLS** and is intended for a trusted private network only (localhost, LAN, VPN/tailnet). Dashboard rows expose project names and assistant message snippets. If remote machines do not need direct access, bind to localhost (`--bind 127.0.0.1`) or a VPN interface.

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
