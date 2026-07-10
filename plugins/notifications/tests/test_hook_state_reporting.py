# tests/test_hook_state_reporting.py
import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

HOOKS_DIR = Path(__file__).parent.parent / "hooks"
ATTENTION_HUB_HOOKS_DIR = Path(__file__).parent.parent.parent / "attention-hub" / "hooks"


def run_hook_capture_hub(script_name, hook_input, hooks_dir=HOOKS_DIR):
    """Run a hook script, return list of (url, method, body) hub requests."""
    spec = importlib.util.spec_from_file_location(
        script_name.replace(".py", ""), hooks_dir / script_name
    )
    hub_requests = []

    def capture_urlopen(req, timeout=None):
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        hub_requests.append((req.full_url, req.get_method(), body))
        return MagicMock(status=200)

    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post") as mock_post, \
         patch("subprocess.run") as mock_subprocess, \
         patch("urllib.request.urlopen", side_effect=capture_urlopen):
        mock_post.return_value = MagicMock(status_code=200, text="ok")
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit:
            pass

    return hub_requests


def hub_events(hub_requests):
    return [body for url, method, body in hub_requests
            if url.endswith("/api/events") and method == "POST"]


# --- Notification hook -> waiting ---

def test_actionable_notification_reports_waiting(base_hook_input, transcript_without_ask):
    # Why: a permission prompt means Claude is blocked on the user; the hub must
    # learn "waiting" or the dashboard never turns red for blocked sessions.
    events = hub_events(run_hook_capture_hub("notifications_notification.py", {
        **base_hook_input,
        "notification_type": "permission_prompt",
        "transcript_path": transcript_without_ask,
    }))
    assert len(events) == 1
    assert events[0]["state"] == "waiting"
    assert events[0]["session_id"] == "test-session-123"


def test_non_actionable_notification_reports_nothing(base_hook_input, transcript_without_ask):
    # Why: non-actionable types (auth_success etc.) must not pollute the dashboard
    # with phantom "waiting" rows — the actionable filter gates hub reporting too.
    events = hub_events(run_hook_capture_hub("notifications_notification.py", {
        **base_hook_input,
        "notification_type": "auth_success",
        "transcript_path": transcript_without_ask,
    }))
    assert events == []


# --- Stop hook -> needs_input / done ---

def test_stop_with_ask_reports_needs_input(base_hook_input, transcript_with_ask):
    # Why: a Stop ending in AskUserQuestion means Claude asked the user something;
    # the dashboard row must go red (needs_input), not yellow.
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_with_ask,
    }))
    assert len(events) == 1
    assert events[0]["state"] == "needs_input"


def test_stop_without_ask_reports_done(base_hook_input, transcript_without_ask):
    # Why: a Stop with no pending question is "task complete, awaiting review" —
    # the yellow state that distinguishes finished sessions from blocked ones.
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
    }))
    assert len(events) == 1
    assert events[0]["state"] == "done"


def test_subagent_session_stop_reports_nothing(base_hook_input, transcript_without_ask):
    # Why: subagent sessions are internal; showing them as dashboard rows would
    # recreate the notification spam this feature exists to remove.
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
        "agent_type": "Explore",
    }))
    assert events == []


def test_stop_reports_message_snippet(base_hook_input, transcript_without_ask):
    # Why: red/yellow rows must show WHAT the session is asking/finished with, so
    # the user can triage from the dashboard without opening the terminal.
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
    }))
    assert events[0]["message"], "Stop event must carry the latest message snippet"


# --- Session name propagation ---

def named_transcript(tmp_path, base_lines_path):
    """Copy a fixture transcript and append a /rename custom-title record."""
    base = Path(base_lines_path).read_text(encoding="utf-8")
    path = tmp_path / "named_transcript.jsonl"
    path.write_text(
        base + json.dumps({"type": "custom-title", "customTitle": "tester",
                           "sessionId": "test-session-123"}) + "\n",
        encoding="utf-8",
    )
    return str(path)


def test_stop_reports_session_name_from_transcript(base_hook_input, transcript_without_ask, tmp_path):
    # Why: a renamed session must reach the hub with its name on the Stop event —
    # the moment the row turns yellow/red is when the label matters most.
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": named_transcript(tmp_path, transcript_without_ask),
    }))
    assert len(events) == 1
    assert events[0]["session_name"] == "tester"


def test_notification_reports_session_name(base_hook_input, transcript_without_ask, tmp_path):
    # Why: blocked (red) rows are the ones the user triages first; the waiting
    # event from the Notification hook must be name-labeled like the others.
    events = hub_events(run_hook_capture_hub("notifications_notification.py", {
        **base_hook_input,
        "notification_type": "permission_prompt",
        "transcript_path": named_transcript(tmp_path, transcript_without_ask),
    }))
    assert len(events) == 1
    assert events[0]["session_name"] == "tester"


def test_unnamed_session_reports_empty_name(base_hook_input, transcript_without_ask):
    # Why: sessions without a /rename must send an empty name so the dashboard
    # falls back to the project label — not omit the field or send garbage.
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
    }))
    assert events[0]["session_name"] == ""


# --- Waiting marker lifecycle (Notification sets, Stop clears) ---

def set_marker(marker_home, session_id="test-session-123"):
    """Drop a waiting marker for a session, as the Notification hook would."""
    marker_home.mkdir(parents=True, exist_ok=True)
    (marker_home / session_id).touch()


def test_actionable_notification_sets_waiting_marker(base_hook_input, transcript_without_ask, marker_home):
    # Why: the marker is the local record that the hub was told "waiting" — without
    # it, attention-hub's PostToolUse can never know the session resumed after a
    # permission prompt.
    run_hook_capture_hub("notifications_notification.py", {
        **base_hook_input,
        "notification_type": "permission_prompt",
        "transcript_path": transcript_without_ask,
    })
    assert (marker_home / "test-session-123").is_file()


def test_non_actionable_notification_sets_no_marker(base_hook_input, transcript_without_ask, marker_home):
    # Why: a marker for a non-blocked session would make the next tool call send a
    # spurious "working" report — markers must track only real waiting states.
    run_hook_capture_hub("notifications_notification.py", {
        **base_hook_input,
        "notification_type": "auth_success",
        "transcript_path": transcript_without_ask,
    })
    assert not (marker_home / "test-session-123").exists()


def test_stop_clears_marker(base_hook_input, transcript_without_ask, marker_home):
    # Why: a denied permission runs no tool, so Stop is the hook that must consume
    # the marker — otherwise the first tool of the NEXT turn reports stale "working".
    set_marker(marker_home)
    run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
    })
    assert not (marker_home / "test-session-123").exists()


# --- Active-subagent suppression (read via attention_hub_bridge) ---

def set_active_subagent_marker(active_subagent_home, session_id="test-session-123", name="marker-1"):
    """Drop an active-subagent marker for a session, as attention-hub's
    PreToolUse(Task) hook would."""
    marker_dir = active_subagent_home / session_id
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / name).touch()


def test_stop_with_active_subagent_reports_working_not_done(base_hook_input, transcript_without_ask, active_subagent_home):
    # Why: the core fix — a Stop while a subagent is still running must report
    # "working", not "done", so the hub row doesn't falsely flag for attention.
    set_active_subagent_marker(active_subagent_home)
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
    }))
    assert len(events) == 1
    assert events[0]["state"] == "working"


def test_stop_with_active_subagent_and_genuine_ask_reports_needs_input(base_hook_input, transcript_with_ask, active_subagent_home):
    # Why: needs_input always wins — a genuine AskUserQuestion must still report
    # needs_input even while background subagents are active.
    set_active_subagent_marker(active_subagent_home)
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_with_ask,
    }))
    assert len(events) == 1
    assert events[0]["state"] == "needs_input"


def test_subagent_stop_then_stop_reports_done_not_working(base_hook_input, transcript_without_ask, active_subagent_home):
    # Why: chained scenario spanning both plugins — a session with one
    # active-subagent marker that receives attention-hub's SubagentStop hook
    # (clearing it) followed immediately by notifications' Stop hook must
    # report done/needs_input as today, not working, confirming the marker's
    # absence correctly drives the branch (not just its presence). Exercises
    # attention-hub's real hook (not a stub) to prove the two plugins interact
    # correctly through the shared marker files on disk.
    set_active_subagent_marker(active_subagent_home, name="marker-1")
    run_hook_capture_hub("attention_hub_subagent_stop.py", {**base_hook_input},
                         hooks_dir=ATTENTION_HUB_HOOKS_DIR)
    events = hub_events(run_hook_capture_hub("notifications_stop.py", {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
    }))
    assert len(events) == 1
    assert events[0]["state"] == "done"


# --- Graceful degradation ---

def test_hooks_exit_zero_when_hub_down(base_hook_input, transcript_without_ask, monkeypatch):
    # Why: the graceful-degradation acceptance criterion — a dead hub must never
    # error either hook. Uses a real connection-refused, not a mock.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://127.0.0.1:1")
    for script, extra in [
        ("notifications_notification.py",
         {"notification_type": "permission_prompt", "transcript_path": transcript_without_ask}),
        ("notifications_stop.py", {"transcript_path": transcript_without_ask}),
    ]:
        spec = importlib.util.spec_from_file_location(
            script.replace(".py", ""), HOOKS_DIR / script
        )
        with patch("sys.stdin", StringIO(json.dumps({**base_hook_input, **extra}))), \
             patch("requests.post") as mock_post, \
             patch("subprocess.run") as mock_subprocess:
            mock_post.return_value = MagicMock(status_code=200, text="ok")
            mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
            mod = importlib.util.module_from_spec(spec)
            exit_code = 0
            try:
                spec.loader.exec_module(mod)
                mod.main()
            except SystemExit as e:
                exit_code = e.code or 0
            assert exit_code == 0, f"{script} must exit 0 when hub is unreachable"


def test_hooks_exit_zero_when_attention_hub_not_installed(base_hook_input, transcript_without_ask, monkeypatch):
    # Why: notifications must keep working standalone — if attention-hub isn't
    # installed (bridge discovery finds nothing), the Notification/Stop hooks
    # must still exit 0 and still send macOS/Slack, exactly like an unreachable
    # hub. Points the bridge's override env var at a path that doesn't exist to
    # simulate "attention-hub not installed" without touching real discovery.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_CLIENT_PATH", "/nonexistent/attention_hub_client.py")
    for script, extra in [
        ("notifications_notification.py",
         {"notification_type": "permission_prompt", "transcript_path": transcript_without_ask}),
        ("notifications_stop.py", {"transcript_path": transcript_without_ask}),
    ]:
        spec = importlib.util.spec_from_file_location(
            script.replace(".py", ""), HOOKS_DIR / script
        )
        with patch("sys.stdin", StringIO(json.dumps({**base_hook_input, **extra}))), \
             patch("requests.post") as mock_post, \
             patch("subprocess.run") as mock_subprocess:
            mock_post.return_value = MagicMock(status_code=200, text="ok")
            mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
            mod = importlib.util.module_from_spec(spec)
            exit_code = 0
            try:
                spec.loader.exec_module(mod)
                mod.main()
            except SystemExit as e:
                exit_code = e.code or 0
            assert exit_code == 0, f"{script} must exit 0 when attention-hub isn't installed"
            assert mock_post.called, f"{script} must still send Slack when attention-hub isn't installed"
            assert mock_subprocess.called, f"{script} must still send macOS when attention-hub isn't installed"
