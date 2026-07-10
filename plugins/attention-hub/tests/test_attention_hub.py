# tests/test_attention_hub.py
import importlib.util
import json
import socket
import threading
import urllib.request
from pathlib import Path

import pytest


def load_hub():
    spec = importlib.util.spec_from_file_location(
        "attention_hub",
        Path(__file__).parent.parent / "hub" / "attention_hub.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_event(session_id="sess-1", state="working", project="proj", host="mac",
               message="", timestamp="2026-06-11T00:00:00+00:00"):
    return {
        "session_id": session_id,
        "project": project,
        "host": host,
        "state": state,
        "message": message,
        "timestamp": timestamp,
    }


# --- Session name storage ---

def test_upsert_stores_session_name(tmp_path):
    # Why: the dashboard labels a row by session name when one is set; the store
    # must accept, persist, and echo the field or the feature is invisible.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert({**make_event(), "session_name": "tester"})
    assert store.list_sessions()[0]["session_name"] == "tester"


def test_upsert_session_name_defaults_empty(tmp_path):
    # Why: events from older clients omit session_name entirely; the store must
    # default it to "" so the dashboard's fallback-to-project logic has a value.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event())
    assert store.list_sessions()[0]["session_name"] == ""


def test_upsert_session_name_sticky_across_events(tmp_path):
    # Why: not every hook event re-derives the name (and a transient transcript
    # read failure sends ""); a known name must survive name-less updates instead
    # of flickering back to the project label.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert({**make_event(), "session_name": "tester"})
    store.upsert(make_event(state="done"))
    assert store.list_sessions()[0]["session_name"] == "tester"


def test_upsert_session_name_update_wins(tmp_path):
    # Why: /rename can happen mid-session; the newest non-empty name must replace
    # the stored one, otherwise renames never propagate to the dashboard.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert({**make_event(), "session_name": "old-name"})
    store.upsert({**make_event(), "session_name": "tester"})
    assert store.list_sessions()[0]["session_name"] == "tester"


def test_upsert_session_name_clamped(tmp_path):
    # Why: session_name is client-supplied input rendered on the dashboard; the
    # hub trusts no client to truncate for it (same rule as project/host).
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert({**make_event(), "session_name": "n" * 5000})
    assert len(store.list_sessions()[0]["session_name"]) <= hub.FIELD_MAX_CHARS


def test_load_sanitizes_session_name(tmp_path):
    # Why: the state file is hand-editable JSON; a missing or non-string
    # session_name must load as a clamped string, never crash the hub at boot.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"sessions": {
        "named": {"session_id": "named", "state": "working", "session_name": "x" * 5000},
        "legacy": {"session_id": "legacy", "state": "working"},
    }}))
    store = hub.AttentionStore(str(state_file))
    by_id = {s["session_id"]: s for s in store.list_sessions()}
    assert len(by_id["named"]["session_name"]) <= hub.FIELD_MAX_CHARS
    assert by_id["legacy"]["session_name"] == ""


def test_dashboard_title_is_session_name_with_id_fallback(tmp_path):
    # Why: the card hierarchy is session-first — the title must be the session
    # name, falling back to the session ID when unnamed, with the project as
    # the subtitle. Guards the dashboard JS actually consuming both fields.
    hub = load_hub()
    assert "s.session_name || s.session_id" in hub.DASHBOARD_HTML
    assert "subtitle.textContent = s.project" in hub.DASHBOARD_HTML


# --- Store: upsert / list / delete ---

def test_upsert_creates_session(tmp_path):
    # Why: the first event from a new session must create its dashboard row —
    # create-or-update semantics keyed by session ID.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event())
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sess-1"
    assert sessions[0]["state"] == "working"


def test_upsert_updates_existing_session(tmp_path):
    # Why: a state transition must update the existing row, never add a second
    # row for the same session — one discrete row per session is the core UX rule.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event(state="working"))
    store.upsert(make_event(state="waiting", message="May I run rm?"))
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["state"] == "waiting"
    assert sessions[0]["message"] == "May I run rm?"


def test_state_duration_resets_on_state_change_only(tmp_path):
    # Why: "waiting 4m" must measure time in the CURRENT state; repeated events in
    # the same state must not reset the clock, and a state change must.
    hub = load_hub()
    clock = {"now": 1000.0}
    store = hub.AttentionStore(str(tmp_path / "state.json"), now=lambda: clock["now"])
    store.upsert(make_event(state="working"))
    clock["now"] = 1060.0
    store.upsert(make_event(state="working"))
    clock["now"] = 1120.0
    working = store.list_sessions()[0]
    assert working["state_seconds"] == pytest.approx(120.0)
    store.upsert(make_event(state="waiting"))
    clock["now"] = 1130.0
    waiting = store.list_sessions()[0]
    assert waiting["state_seconds"] == pytest.approx(10.0)


def test_list_reports_last_update_age(tmp_path):
    # Why: the dashboard shows last-update age so stale/crashed sessions are
    # recognizable; the API must expose it.
    hub = load_hub()
    clock = {"now": 1000.0}
    store = hub.AttentionStore(str(tmp_path / "state.json"), now=lambda: clock["now"])
    store.upsert(make_event())
    clock["now"] = 1030.0
    assert store.list_sessions()[0]["age_seconds"] == pytest.approx(30.0)


def test_list_sorts_needs_attention_first(tmp_path):
    # Why: the dashboard answers "which instance is waiting on me" at a glance —
    # red (waiting/needs_input) must sort before yellow (done) before green (working).
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event(session_id="green", state="working"))
    store.upsert(make_event(session_id="yellow", state="done"))
    store.upsert(make_event(session_id="red1", state="waiting"))
    store.upsert(make_event(session_id="red2", state="needs_input"))
    states = [s["state"] for s in store.list_sessions()]
    assert states[:2] in ([["waiting", "needs_input"], ["needs_input", "waiting"]])
    assert states[2] == "done"
    assert states[3] == "working"


def test_upsert_truncates_long_message_server_side(tmp_path):
    # Why: the 200-char snippet cap must hold even when a peer bypasses the hook
    # client; otherwise a single event bloats in-memory state, the JSON file
    # rewritten on every event, and every 3s dashboard poll response.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event(message="x" * 5000))
    assert len(store.list_sessions()[0]["message"]) <= hub.MESSAGE_MAX_CHARS


def test_upsert_caps_identity_fields(tmp_path):
    # Why: session_id/project/host are stored verbatim into state and echoed in
    # every poll response; unbounded identity fields are a storage-exhaustion
    # vector for any network peer.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event(session_id="s" * 5000, project="p" * 5000, host="h" * 5000))
    row = store.list_sessions()[0]
    assert len(row["session_id"]) <= hub.FIELD_MAX_CHARS
    assert len(row["project"]) <= hub.FIELD_MAX_CHARS
    assert len(row["host"]) <= hub.FIELD_MAX_CHARS


def test_delete_removes_session(tmp_path):
    # Why: dismissing a crashed/abandoned session must actually drop it from the
    # store, not just hide it client-side.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event(session_id="a"))
    store.upsert(make_event(session_id="b"))
    assert store.delete("a") is True
    assert [s["session_id"] for s in store.list_sessions()] == ["b"]
    assert store.delete("missing") is False


# --- Persistence ---

def test_state_survives_restart(tmp_path):
    # Why: the hub is a manual-start script; restarting it must restore the
    # session list from the JSON file (the story's persistence criterion).
    hub = load_hub()
    state_file = str(tmp_path / "state.json")
    store = hub.AttentionStore(state_file)
    store.upsert(make_event(session_id="persisted", state="needs_input", message="Q?"))
    restored = hub.AttentionStore(state_file)
    sessions = restored.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "persisted"
    assert sessions[0]["state"] == "needs_input"
    assert sessions[0]["message"] == "Q?"


def test_legacy_state_record_missing_time_fields_loads(tmp_path):
    # Why: a hand-edited or older-format state file without state_since/last_update
    # must not KeyError every list_sessions call and blank the dashboard forever.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"sessions": {
        "legacy": {"session_id": "legacy", "state": "working"}
    }}))
    store = hub.AttentionStore(str(state_file))
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "legacy"
    assert sessions[0]["state_seconds"] >= 0


def test_corrupt_state_file_starts_empty(tmp_path):
    # Why: a truncated/corrupt JSON file must not crash the hub on start; it
    # degrades to an empty session list.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    state_file.write_text("{not json")
    store = hub.AttentionStore(str(state_file))
    assert store.list_sessions() == []


# --- Pruning ---

def test_sessions_silent_past_window_are_pruned(tmp_path):
    # Why: sessions that died without a SessionEnd must disappear after the prune
    # window instead of cluttering the dashboard forever.
    hub = load_hub()
    clock = {"now": 0.0}
    store = hub.AttentionStore(str(tmp_path / "state.json"), prune_hours=24,
                               now=lambda: clock["now"])
    store.upsert(make_event(session_id="old"))
    clock["now"] = 25 * 3600.0
    store.upsert(make_event(session_id="fresh"))
    ids = [s["session_id"] for s in store.list_sessions()]
    assert ids == ["fresh"]


def test_prune_window_configurable(tmp_path):
    # Why: the 24h window is configurable; a custom window must be honored.
    hub = load_hub()
    clock = {"now": 0.0}
    store = hub.AttentionStore(str(tmp_path / "state.json"), prune_hours=1,
                               now=lambda: clock["now"])
    store.upsert(make_event(session_id="old"))
    clock["now"] = 2 * 3600.0
    assert store.list_sessions() == []


# --- HTTP API + dashboard ---

@pytest.fixture
def hub_server(tmp_path):
    hub = load_hub()
    server = hub.create_server("127.0.0.1", 0, str(tmp_path / "state.json"), 24)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()
    server.server_close()


def http_json(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read().decode()
        return resp.status, json.loads(raw) if raw else None


def test_http_event_upsert_and_list(hub_server):
    # Why: end-to-end contract the hooks rely on — POST /api/events must surface
    # the session in GET /api/sessions with its state.
    status, _ = http_json(f"{hub_server}/api/events", "POST",
                          make_event(session_id="http-1", state="waiting", message="hi"))
    assert status == 200
    status, listing = http_json(f"{hub_server}/api/sessions")
    assert status == 200
    assert len(listing["sessions"]) == 1
    row = listing["sessions"][0]
    assert row["session_id"] == "http-1"
    assert row["state"] == "waiting"
    assert "state_seconds" in row and "age_seconds" in row


def test_http_delete_session(hub_server):
    # Why: the dashboard dismiss control calls DELETE /api/sessions/{id}; it must
    # remove the row server-side.
    http_json(f"{hub_server}/api/events", "POST", make_event(session_id="gone"))
    status, _ = http_json(f"{hub_server}/api/sessions/gone", "DELETE")
    assert status == 200
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"] == []


def test_http_delete_unknown_session_404(hub_server):
    # Why: deleting an unknown ID must be a clean 404, not a server error.
    req = urllib.request.Request(f"{hub_server}/api/sessions/nope", method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=5)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 404


def test_http_invalid_event_rejected(hub_server):
    # Why: an event without a session_id cannot key a row; the hub must reject it
    # with 400 instead of storing garbage.
    try:
        status, _ = http_json(f"{hub_server}/api/events", "POST", {"state": "working"})
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"] == []


def test_http_non_object_event_rejected_with_400(hub_server):
    # Why: a JSON array/string body must produce a clean 400, not an uncaught
    # AttributeError that kills the handler thread with no response.
    req = urllib.request.Request(
        f"{hub_server}/api/events", data=b'["not", "an", "object"]', method="POST",
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400


def raw_http(base, request_bytes):
    """Send a hand-crafted HTTP request and return the raw response text.

    Needed for malformed-header cases (negative/oversized/missing
    Content-Length) that urllib refuses to produce.
    """
    host, port = base.replace("http://", "").rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        sock.sendall(request_bytes)
        sock.settimeout(5)
        response = b""
        try:
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
        except socket.timeout:
            pass
    return response.decode("latin-1")


def test_http_post_negative_content_length_rejected(hub_server):
    # Why: a negative Content-Length used to reach rfile.read(-1), blocking the
    # handler thread until the client closed the socket — a trivially repeatable
    # thread-exhaustion attack under ThreadingHTTPServer. Must be a fast 400.
    response = raw_http(hub_server, (
        b"POST /api/events HTTP/1.1\r\n"
        b"Host: hub\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: -1\r\n"
        b"Connection: close\r\n\r\n"
    ))
    assert " 400 " in response.splitlines()[0]


def test_http_post_missing_content_length_rejected(hub_server):
    # Why: a missing or non-numeric Content-Length cannot bound the body read;
    # the hub must reject it instead of reading garbage or blocking.
    response = raw_http(hub_server, (
        b"POST /api/events HTTP/1.1\r\n"
        b"Host: hub\r\n"
        b"Content-Type: application/json\r\n"
        b"Connection: close\r\n\r\n"
    ))
    assert " 400 " in response.splitlines()[0]


def test_http_post_oversized_content_length_rejected(hub_server):
    # Why: an attacker-declared huge Content-Length used to buffer the whole
    # body in memory before parsing (OOM of a 0.0.0.0-bound process). The hub
    # must refuse oversized bodies up front without reading them.
    response = raw_http(hub_server, (
        b"POST /api/events HTTP/1.1\r\n"
        b"Host: hub\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 100000000\r\n"
        b"Connection: close\r\n\r\n"
    ))
    assert " 413 " in response.splitlines()[0]


def test_http_post_wrong_content_type_rejected(hub_server):
    # Why: a cross-origin "simple request" (text/plain fetch from any web page)
    # is delivered without a CORS preflight; accepting it would let an arbitrary
    # page forge or overwrite session rows. Requiring application/json forces a
    # failing preflight.
    body = json.dumps(make_event(session_id="csrf")).encode()
    req = urllib.request.Request(
        f"{hub_server}/api/events", data=body, method="POST",
        headers={"Content-Type": "text/plain"})
    try:
        urllib.request.urlopen(req, timeout=5)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 415
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"] == []


def test_http_invalid_state_rejected_with_400(hub_server):
    # Why: an unknown state value would render as an uncolored, unsortable row;
    # the hub must reject it at the API boundary with a clean 400.
    try:
        status, _ = http_json(f"{hub_server}/api/events", "POST",
                              make_event(state="exploded"))
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"] == []


def test_http_delete_percent_encoded_session_id(hub_server):
    # Why: the hook client percent-encodes session IDs; the hub must decode the
    # path or IDs with reserved characters could never be removed.
    http_json(f"{hub_server}/api/events", "POST", make_event(session_id="odd id/1"))
    status, _ = http_json(f"{hub_server}/api/sessions/odd%20id%2F1", "DELETE")
    assert status == 200
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"] == []


def test_dashboard_served_at_root(hub_server):
    # Why: the dashboard is the feature's only indicator surface; the root URL
    # must serve a self-contained HTML page that polls the sessions API.
    with urllib.request.urlopen(f"{hub_server}/", timeout=5) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        page = resp.read().decode()
    assert "/api/sessions" in page, "dashboard must poll the session-list endpoint"
    assert "dismiss" in page.lower(), "dashboard must expose a per-row dismiss control"


def make_clock_store(hub, tmp_path, start=1000.0):
    clock = {"now": start}
    store = hub.AttentionStore(str(tmp_path / "state.json"), now=lambda: clock["now"])
    return clock, store


# --- Dashboard: expandable cards, force buttons, container badge ---

def test_dashboard_expansion_set_outlives_render(tmp_path):
    # Why: render() replaces all children every 3 seconds; the set of expanded
    # session IDs must live OUTSIDE the render pass and be re-applied, or every
    # open card collapses itself on the next poll.
    hub = load_hub()
    assert "const expandedIds = new Set()" in hub.DASHBOARD_HTML
    assert "expandedIds.has(" in hub.DASHBOARD_HTML


def test_dashboard_dismiss_and_force_do_not_toggle_expansion(tmp_path):
    # Why: dismiss and force-status buttons sit inside the clickable card; their
    # clicks must not bubble into the expand/collapse toggle.
    hub = load_hub()
    assert hub.DASHBOARD_HTML.count("stopPropagation") >= 2


def test_dashboard_posts_to_force_state_endpoint(tmp_path):
    # Why: the force buttons are only useful if they target the real endpoint
    # with a JSON state body and refresh afterwards.
    hub = load_hub()
    assert '"/state"' in hub.DASHBOARD_HTML
    assert "JSON.stringify({ state:" in hub.DASHBOARD_HTML


def test_dashboard_force_buttons_disable_current_state(tmp_path):
    # Why: forcing the state a session is already in is a no-op; the current
    # state's button renders disabled so the control communicates that.
    hub = load_hub()
    assert "btn.disabled = s.state ===" in hub.DASHBOARD_HTML


def test_dashboard_detail_panel_renders_hub_knowledge(tmp_path):
    # Why: the expanded panel must surface the container badge, the manual
    # history badge, the full session ID, and the timeline fields the API now
    # serves — these markers guard the JS actually consuming them.
    hub = load_hub()
    for marker in ("is_container", "container", "manual", "entered_at",
                   "state_seconds", "s.history"):
        assert marker in hub.DASHBOARD_HTML, f"dashboard must consume {marker!r}"


# --- Status history: recording ---

def test_history_appends_entry_on_state_change(tmp_path):
    # Why: the expanded card's timeline is built from recorded transitions; every
    # actual state change (including first sighting) must append one entry with
    # the state, the time it was entered, and source "hook".
    hub = load_hub()
    clock, store = make_clock_store(hub, tmp_path)
    store.upsert(make_event(state="working"))
    clock["now"] = 1060.0
    store.upsert(make_event(state="waiting"))
    history = store.list_sessions()[0]["history"]
    assert [(e["state"], e["entered_at"], e["source"]) for e in history] == [
        ("working", 1000.0, "hook"),
        ("waiting", 1060.0, "hook"),
    ]


def test_history_no_entry_on_same_state_re_report(tmp_path):
    # Why: hooks re-report "working" on every prompt; a same-state event refreshes
    # last_update but must not flood the timeline with duplicate entries (mirrors
    # the existing state_since behavior).
    hub = load_hub()
    clock, store = make_clock_store(hub, tmp_path)
    store.upsert(make_event(state="working"))
    clock["now"] = 1060.0
    store.upsert(make_event(state="working"))
    assert len(store.list_sessions()[0]["history"]) == 1


def test_history_capped_with_oldest_dropped(tmp_path):
    # Why: unbounded history would grow the state file and every 3s poll response
    # forever; the cap must hold at 20 with the oldest entries dropped first.
    hub = load_hub()
    clock, store = make_clock_store(hub, tmp_path)
    states = ["working", "waiting"]
    for i in range(25):
        clock["now"] = 1000.0 + i
        store.upsert(make_event(state=states[i % 2]))
    history = store.list_sessions()[0]["history"]
    assert hub.HISTORY_MAX == 20
    assert len(history) == hub.HISTORY_MAX
    assert history[0]["entered_at"] == 1005.0  # five oldest dropped
    assert history[-1]["entered_at"] == 1024.0


def test_history_survives_restart(tmp_path):
    # Why: the hub is a manual-start script; timelines must be persisted in the
    # state file and restored on restart, not rebuilt from scratch.
    hub = load_hub()
    state_file = str(tmp_path / "state.json")
    store = hub.AttentionStore(state_file)
    store.upsert(make_event(state="working"))
    store.upsert(make_event(state="waiting"))
    restored = hub.AttentionStore(state_file)
    history = restored.list_sessions()[0]["history"]
    assert [e["state"] for e in history] == ["working", "waiting"]


# --- Status history: legacy load and sanitizing ---

def test_legacy_record_without_history_seeds_one_entry(tmp_path):
    # Why: pre-feature state files have records with no history; loading must seed
    # a one-entry history from the record's current state and state_since so the
    # dashboard timeline is never empty for old sessions.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"sessions": {
        "legacy": {"session_id": "legacy", "state": "waiting",
                   "state_since": 111.0, "last_update": 112.0},
    }}))
    store = hub.AttentionStore(str(state_file), now=lambda: 200.0)
    history = store.list_sessions()[0]["history"]
    assert history == [{"state": "waiting", "entered_at": 111.0, "source": "hook"}]


def test_load_discards_malformed_history_entries(tmp_path):
    # Why: the state file is hand-editable JSON; bogus entries (unknown state,
    # non-numeric time, non-dict) must be dropped on load, never crash the hub
    # or render garbage in the timeline.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"sessions": {
        "s": {"session_id": "s", "state": "working",
              "state_since": 50.0, "last_update": 60.0,
              "history": [
                  {"state": "working", "entered_at": 50.0, "source": "hook"},
                  {"state": "exploded", "entered_at": 51.0, "source": "hook"},
                  {"state": "waiting", "entered_at": "yesterday", "source": "hook"},
                  "junk",
              ]},
    }}))
    store = hub.AttentionStore(str(state_file), now=lambda: 200.0)
    history = store.list_sessions()[0]["history"]
    assert history == [{"state": "working", "entered_at": 50.0, "source": "hook"}]


def test_load_seeds_history_when_all_entries_malformed(tmp_path):
    # Why: if sanitizing drops every entry the record must fall back to the same
    # seeding as a legacy record — a session with an empty timeline is a bug.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"sessions": {
        "s": {"session_id": "s", "state": "done",
              "state_since": 70.0, "last_update": 80.0,
              "history": ["junk", 42]},
    }}))
    store = hub.AttentionStore(str(state_file), now=lambda: 200.0)
    history = store.list_sessions()[0]["history"]
    assert history == [{"state": "done", "entered_at": 70.0, "source": "hook"}]


def test_load_caps_history_at_limit(tmp_path):
    # Why: a hand-grown or pre-cap state file must not bypass the 20-entry bound;
    # the cap is enforced on load as well as on write.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    entries = [{"state": "working" if i % 2 == 0 else "waiting",
                "entered_at": float(i), "source": "hook"} for i in range(30)]
    state_file.write_text(json.dumps({"sessions": {
        "s": {"session_id": "s", "state": "waiting",
              "state_since": 29.0, "last_update": 29.0, "history": entries},
    }}))
    store = hub.AttentionStore(str(state_file), now=lambda: 100.0)
    history = store.list_sessions()[0]["history"]
    assert len(history) == hub.HISTORY_MAX
    assert history[-1]["entered_at"] == 29.0


# --- Container flag ---

def test_upsert_stores_container_flag(tmp_path):
    # Why: the dashboard's container badge only renders if the flag the client
    # sends is stored and served back by the sessions API.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert({**make_event(), "is_container": True})
    assert store.list_sessions()[0]["is_container"] is True


def test_container_flag_defaults_false(tmp_path):
    # Why: events from older clients omit is_container entirely; the store must
    # default it to False so every served row carries a boolean.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event())
    assert store.list_sessions()[0]["is_container"] is False


def test_container_flag_sticky_when_event_omits_it(tmp_path):
    # Why: a mixed fleet can send events with and without the field for the same
    # session; an omitting event must keep the previous value, not flicker the
    # badge off.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert({**make_event(), "is_container": True})
    store.upsert(make_event(state="done"))
    assert store.list_sessions()[0]["is_container"] is True


def test_load_defaults_container_flag_false(tmp_path):
    # Why: pre-feature state files have no is_container; legacy records must load
    # with the flag defaulting to False instead of crashing or serving None.
    hub = load_hub()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"sessions": {
        "legacy": {"session_id": "legacy", "state": "working"},
    }}))
    store = hub.AttentionStore(str(state_file))
    assert store.list_sessions()[0]["is_container"] is False


def test_container_flag_survives_restart(tmp_path):
    # Why: the badge must not disappear when the hub restarts; the flag is part
    # of the persisted record.
    hub = load_hub()
    state_file = str(tmp_path / "state.json")
    store = hub.AttentionStore(state_file)
    store.upsert({**make_event(), "is_container": True})
    restored = hub.AttentionStore(state_file)
    assert restored.list_sessions()[0]["is_container"] is True


# --- Force state: store ---

def test_force_state_updates_record_and_appends_manual_history(tmp_path):
    # Why: the force-status control exists to correct a stale state by hand; the
    # store must flip the state, reset state_since, and record the change in
    # history with source "manual" so the timeline shows who changed what.
    hub = load_hub()
    clock, store = make_clock_store(hub, tmp_path)
    store.upsert(make_event(state="waiting", message="stale?"))
    clock["now"] = 1060.0
    record = store.force_state("sess-1", "working")
    assert record["state"] == "working"
    assert record["state_since"] == 1060.0
    assert record["last_update"] == 1060.0
    last = record["history"][-1]
    assert (last["state"], last["entered_at"], last["source"]) == \
        ("working", 1060.0, "manual")


def test_force_state_leaves_message_unchanged(tmp_path):
    # Why: the override corrects only the state; wiping the last message would
    # destroy context the user may still need to read.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event(state="waiting", message="May I run rm?"))
    record = store.force_state("sess-1", "working")
    assert record["message"] == "May I run rm?"


def test_force_state_unknown_session_returns_none_and_never_creates(tmp_path):
    # Why: forcing is an operation on an EXISTING session — unlike events it must
    # signal not-found and never materialize a phantom row.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    assert store.force_state("ghost", "working") is None
    assert store.list_sessions() == []


def test_force_state_invalid_state_rejected(tmp_path):
    # Why: an unknown state would render as an uncolored, unsortable row; the
    # store must reject it before mutating anything.
    hub = load_hub()
    store = hub.AttentionStore(str(tmp_path / "state.json"))
    store.upsert(make_event(state="waiting"))
    with pytest.raises(ValueError):
        store.force_state("sess-1", "exploded")
    assert store.list_sessions()[0]["state"] == "waiting"


def test_force_state_same_state_noop_except_last_update(tmp_path):
    # Why: re-forcing the current state must not reset the state clock or add a
    # duplicate timeline entry — only last_update moves.
    hub = load_hub()
    clock, store = make_clock_store(hub, tmp_path)
    store.upsert(make_event(state="waiting"))
    clock["now"] = 1060.0
    record = store.force_state("sess-1", "waiting")
    assert record["state_since"] == 1000.0
    assert record["last_update"] == 1060.0
    assert len(record["history"]) == 1


def test_forced_state_survives_restart(tmp_path):
    # Why: a manual correction must persist exactly like a hook-driven change;
    # losing it on hub restart would silently resurrect the stale state.
    hub = load_hub()
    state_file = str(tmp_path / "state.json")
    store = hub.AttentionStore(state_file)
    store.upsert(make_event(state="waiting"))
    store.force_state("sess-1", "working")
    restored = hub.AttentionStore(state_file)
    row = restored.list_sessions()[0]
    assert row["state"] == "working"
    assert row["history"][-1]["source"] == "manual"


def test_hook_event_overwrites_forced_state(tmp_path):
    # Why: "real events win" — an override is not pinned; the next genuine hook
    # event replaces it exactly like any other state change, so the hub
    # self-heals toward reality.
    hub = load_hub()
    clock, store = make_clock_store(hub, tmp_path)
    store.upsert(make_event(state="waiting"))
    clock["now"] = 1060.0
    store.force_state("sess-1", "working")
    clock["now"] = 1120.0
    store.upsert(make_event(state="needs_input"))
    row = store.list_sessions()[0]
    assert row["state"] == "needs_input"
    assert row["history"][-1]["source"] == "hook"


# --- Force state: HTTP endpoint ---

def test_http_force_state_happy_path(hub_server):
    # Why: the dashboard's force buttons call this endpoint; a 200 must return
    # the updated record with the manual history entry the timeline renders.
    http_json(f"{hub_server}/api/events", "POST",
              make_event(session_id="f1", state="waiting"))
    status, body = http_json(f"{hub_server}/api/sessions/f1/state", "POST",
                             {"state": "working"})
    assert status == 200
    assert body["session"]["state"] == "working"
    assert body["session"]["history"][-1]["source"] == "manual"
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"][0]["state"] == "working"


def test_http_force_state_percent_encoded_session_id(hub_server):
    # Why: the dashboard percent-encodes session IDs into the path; the hub must
    # decode it or sessions with reserved characters could never be forced.
    http_json(f"{hub_server}/api/events", "POST",
              make_event(session_id="odd id/1", state="waiting"))
    status, _ = http_json(f"{hub_server}/api/sessions/odd%20id%2F1/state", "POST",
                          {"state": "working"})
    assert status == 200


def test_http_force_state_invalid_state_400(hub_server):
    # Why: an invalid state name must be a clean 400 with the session untouched.
    http_json(f"{hub_server}/api/events", "POST",
              make_event(session_id="f2", state="waiting"))
    try:
        status, _ = http_json(f"{hub_server}/api/sessions/f2/state", "POST",
                              {"state": "exploded"})
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"][0]["state"] == "waiting"


def test_http_force_state_missing_state_400(hub_server):
    # Why: a body without a state names nothing to force; must be 400, not a
    # KeyError that kills the handler thread.
    http_json(f"{hub_server}/api/events", "POST",
              make_event(session_id="f3", state="waiting"))
    try:
        status, _ = http_json(f"{hub_server}/api/sessions/f3/state", "POST", {})
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400


def test_http_force_state_malformed_body_400(hub_server):
    # Why: a non-JSON or non-object body must produce a clean 400, mirroring the
    # /api/events guards.
    http_json(f"{hub_server}/api/events", "POST",
              make_event(session_id="f4", state="waiting"))
    req = urllib.request.Request(
        f"{hub_server}/api/sessions/f4/state", data=b"{not json", method="POST",
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 400


def test_http_force_state_unknown_session_404_never_creates(hub_server):
    # Why: forcing an unknown session must 404 and never create a phantom row —
    # the semantic difference from /api/events.
    try:
        status, _ = http_json(f"{hub_server}/api/sessions/ghost/state", "POST",
                              {"state": "working"})
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 404
    _, listing = http_json(f"{hub_server}/api/sessions")
    assert listing["sessions"] == []


def test_http_force_state_wrong_content_type_rejected(hub_server):
    # Why: same CSRF reasoning as /api/events — a text/plain cross-origin fetch
    # must not be able to flip session states from an arbitrary web page.
    http_json(f"{hub_server}/api/events", "POST",
              make_event(session_id="f5", state="waiting"))
    req = urllib.request.Request(
        f"{hub_server}/api/sessions/f5/state", data=b'{"state": "working"}',
        method="POST", headers={"Content-Type": "text/plain"})
    try:
        urllib.request.urlopen(req, timeout=5)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 415


def test_http_sessions_payload_includes_history_and_container_flag(hub_server):
    # Why: the expanded card renders the timeline and badge from GET
    # /api/sessions rows; dropping either field makes the feature invisible.
    http_json(f"{hub_server}/api/events", "POST",
              {**make_event(session_id="p1", state="working"), "is_container": True})
    http_json(f"{hub_server}/api/events", "POST",
              make_event(session_id="p1", state="waiting"))
    _, listing = http_json(f"{hub_server}/api/sessions")
    row = listing["sessions"][0]
    assert row["is_container"] is True
    assert [e["state"] for e in row["history"]] == ["working", "waiting"]
    assert all(e["source"] == "hook" for e in row["history"])


def test_dashboard_data_one_row_per_session(hub_server):
    # Why: 5 sessions = 5 rows, never aggregated — verified at the data level the
    # page renders from (per spec, no browser automation).
    for i in range(5):
        http_json(f"{hub_server}/api/events", "POST",
                  make_event(session_id=f"s{i}", project=f"proj-{i}"))
    _, listing = http_json(f"{hub_server}/api/sessions")
    ids = sorted(s["session_id"] for s in listing["sessions"])
    assert ids == ["s0", "s1", "s2", "s3", "s4"]
