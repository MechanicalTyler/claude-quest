# attention-hub

A self-hosted, zero-dependency dashboard server that tracks which of your coding-agent sessions is waiting on you. Any agent or hook system can report to it over plain HTTP — it has no dependency on any particular agent.

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
- **Status history** — the last 20 state transitions (most recent first), each with the time it was entered, how long it lasted, and a `manual` badge when the change came from a manual override rather than a reported event

### Forcing a status

If the hub falls out of sync with reality, the **force status** buttons in the expanded panel set the state by hand — the current state's button is disabled. The override applies immediately and shows up in the history as `manual`, but it is not pinned: the next genuine reported event for the session overwrites it, so the hub always self-heals toward reality.

The buttons call a small API you can also script against:

```bash
curl -X POST http://localhost:8765/api/sessions/<session-id>/state \
  -H 'Content-Type: application/json' -d '{"state": "working"}'
```

Responses: `200` with the updated record, `400` for a missing/invalid state or malformed body, `404` for an unknown session — forcing never creates a session.

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
