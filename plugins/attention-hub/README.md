# attention-hub

A self-hosted, zero-dependency dashboard server *and* a full set of Claude Code hooks that track which of your coding-agent sessions is waiting on you. Installing this plugin alone gives a Claude Code session everything it needs to report to the dashboard — no other plugin required. Any other agent or hook system can also report to the hub over plain HTTP, since the wire protocol is fully documented below.

## What it is

Many concurrent agent sessions (local, docker, remote servers) make per-machine notifications spammy and hard to track. The attention hub is a small server every session's reporting client posts state events to; its web dashboard shows one color-coded row per session:

- **Red** — `waiting` (blocked on a permission/question prompt) or `needs_input` (finished its turn by asking you something)
- **Yellow** — `done` (task complete, awaiting your review)
- **Green** — `working` (busy)

Each card's title is the session name if one was reported, falling back to the session ID, with the project as the subtitle. Cards sort needs-attention first, show time in state, the latest message snippet, and last-update age, refresh every 3 seconds, and have a per-card dismiss control for crashed/abandoned sessions. Sessions silent for over 24 hours are pruned automatically.

### Expanded card view

Clicking a card expands it; any number of cards may be open at once, and open cards stay open across the 3-second refresh. The detail panel shows:

- **Host** — with a `container` badge when the session runs inside a container
- **Full session ID** and the **full last message**
- **Last update** age
- **Active work** — each tracked subagent entry with its kind, label, status, and time in state
- **Status history** — the last 20 state transitions (most recent first), each with the time it was entered, how long it lasted, and a `manual` badge when the change came from a manual override rather than a reported event

### Forcing a status

If the hub falls out of sync with reality, the **force status** buttons in the expanded panel set the state by hand — the current state's button is disabled. The override applies immediately and shows up in the history as `manual`, but it is not pinned: the next genuine reported event for the session overwrites it, so the hub always self-heals toward reality.

The buttons call a small API you can also script against:

```bash
curl -X POST http://localhost:8765/api/sessions/<session-id>/state \
  -H 'Content-Type: application/json' -d '{"state": "working"}'
```

Responses: `200` with the updated record, `400` for a missing/invalid state or malformed body, `404` for an unknown session — forcing never creates a session.

## Reporting hooks

This plugin ships five Claude Code hooks that report session state to the dashboard automatically once installed — no configuration needed:

- **PreToolUse hook**: Pure observer — marks the session as having an active subagent when a `Task` dispatch is seen (every other tool is a no-op). Always exits `0` and never emits a permission-decision payload, so it can never block a tool call
- **PostToolUse hook**: Reports `working` to the hub when a tool completes after the session was flagged `waiting` (a tool can only complete once a pending permission/question was answered). Gated by a per-session marker file, so on normal tool calls (no marker) it exits instantly with zero network activity
- **UserPromptSubmit hook**: Reports `working` to the hub — answering a session automatically clears its needs-attention state
- **SessionEnd hook**: Removes the session from the hub (and cleans up its waiting marker and any active-subagent markers)
- **SubagentStop hook**: Clears one active-subagent marker for the session so the active-subagent count stays accurate

Transient hook state (waiting markers, active-subagent markers) lives under `~/.claude/attention-hub/`.

These five hooks report `working`/removal events only — they never send a `waiting`/`needs_input`/`done` event on their own, since deciding *when* a session needs attention is specific to the Notification and Stop lifecycle events. If you also install the [`notifications`](../notifications) plugin, its Notification and Stop hooks optionally report those states to this same dashboard (auto-discovered, no configuration). Installed alone, attention-hub still gives you the PreToolUse/PostToolUse/UserPromptSubmit/SessionEnd/SubagentStop tracking above; any other agent that wants `waiting`/`needs_input`/`done` reporting can POST directly to the [HTTP API](#http-api) documented below.

## Subagent Tracking and Retention

When a session reports an active subagent (via the PreToolUse hook), the hub tracks markers for each dispatched task, backgrounded command, workflow execution, or persistent monitor watch. Each marker carries:

- **Kind**: one of `task` (Task/Agent dispatch), `bash` (backgrounded Bash), `workflow` (Workflow dispatch), or `monitor` (persistent Monitor watch)
- **Label**: friendly identifier for the work (e.g., agent name, script name)
- **Status**: `active` or `completed`
- **Duration**: ISO timestamp when the subagent started, and (if completed) when it finished

The hub prunes markers based on two retention policies:

- **Active task-kind markers** (ACTIVE_SUBAGENT_TTL_SECONDS): pruned after 2 hours of inactivity, so long-running task dispatches are tracked across your session
- **Active background-kind markers** (bash, workflow, monitor; BACKGROUND_SUBAGENT_TTL_SECONDS): pruned after 15 minutes, since these tend to finish faster
- **Completed task-kind markers** (COMPLETED_RETENTION_SECONDS): stay visible in the expanded card view for 5 minutes before being pruned, so you can see recent work that finished

This tracking appears in the expanded card view's **Active work** section, showing each entry's kind, label, status, and elapsed time.

## Starting the hub

The hub is a manual-start, zero-dependency Python script (run it in tmux/screen; it does not survive reboot):

```bash
uv run hub/attention_hub.py
```

The server itself has no environment variables — it is configured entirely via CLI flags:

| Flag | Default | Meaning |
|------|---------|---------|
| `--port` | `8765` | Port to listen on |
| `--bind` | `0.0.0.0` | Bind address (`127.0.0.1` for localhost only) |
| `--state-file` | `~/.claude/attention_hub_state.json` | JSON persistence file (sessions survive hub restarts) |
| `--prune-hours` | `24` | Drop sessions silent for this many hours |

Open `http://localhost:8765/` for the dashboard.

## HTTP API

Any reporting client can integrate with the hub over plain HTTP.

### `POST /api/events`

Reports (creates or updates) a session's state. Body is a JSON object:

| Field | Required | Meaning |
|-------|----------|---------|
| `session_id` | yes | Stable identifier for the session; keys the dashboard row |
| `state` | yes | One of `waiting`, `needs_input`, `done`, `working` |
| `project` | no | Project/repo name shown as the card subtitle |
| `host` | no | Machine/host name |
| `message` | no | Short status message shown on the card (truncated to 200 chars) |
| `timestamp` | no | ISO-8601 timestamp of the event |
| `session_name` | no | Friendly display name; falls back to `session_id` when omitted |
| `is_container` | no | Boolean; badges the card when the session runs inside a container |

Responses: `200` with the stored record, `400` for a missing `session_id` or invalid `state`, `413` for an oversized body, `415` for a non-`application/json` `Content-Type`.

### `POST /api/sessions/{id}/state`

Manually forces a known session's state. Body: `{"state": "..."}`. `200` with the updated record, `400` for an invalid/missing state, `404` for an unknown session — never creates one.

### `DELETE /api/sessions/{id}`

Removes a session from the dashboard. `200` on success, `404` if unknown.

### `GET /api/sessions`

Returns `{"sessions": [...]}` — every tracked session with computed `state_seconds` and `age_seconds`.

## Security

The hub has **no authentication or TLS** and is intended for a trusted private network only (localhost, LAN, VPN/tailnet). Dashboard rows expose project names and message snippets. If remote machines do not need direct access, bind to localhost (`--bind 127.0.0.1`) or a VPN interface.

## Requirements

Python 3.8+, stdlib only. No third-party dependencies.

## Running tests

```bash
uv run --with pytest python -m pytest tests/
```

## License

MIT
