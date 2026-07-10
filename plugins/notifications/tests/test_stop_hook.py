# tests/test_stop_hook.py
import json
from io import StringIO
from unittest.mock import patch, MagicMock
import importlib.util
from pathlib import Path


def load_and_run_stop_hook(hook_input: dict):
    """Run notifications_stop hook, return (slack_payloads, macos_subtitles)."""
    spec = importlib.util.spec_from_file_location(
        "notifications_stop",
        Path(__file__).parent.parent / "hooks" / "notifications_stop.py"
    )
    slack_payloads = []
    macos_subtitles = []

    def capture_slack(url, json=None, timeout=None):
        slack_payloads.append(json)
        return MagicMock(status_code=200, text="ok")

    def capture_macos(cmd, **kwargs):
        if "-subtitle" in cmd:
            idx = cmd.index("-subtitle")
            macos_subtitles.append(cmd[idx + 1])
        return MagicMock(returncode=0, stderr="")

    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post", side_effect=capture_slack), \
         patch("subprocess.run", side_effect=capture_macos):
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit:
            pass

    return slack_payloads, macos_subtitles


def test_stop_always_sends_slack(base_hook_input, transcript_without_ask):
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    slack_payloads, _ = load_and_run_stop_hook(hook_input)
    assert len(slack_payloads) == 1, "Stop hook must always send exactly one Slack message"


def test_stop_always_sends_macos(base_hook_input, transcript_without_ask):
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    _, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert len(macos_subtitles) == 1, "Stop hook must always send exactly one macOS notification"


def test_stop_without_ask_uses_task_complete_subtitle(base_hook_input, transcript_without_ask):
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    _, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert macos_subtitles[0] == "Task Complete", \
        f"Expected 'Task Complete' subtitle, got {macos_subtitles[0]!r}"


def test_stop_with_ask_uses_needs_input_subtitle(base_hook_input, transcript_with_ask):
    hook_input = {**base_hook_input, "transcript_path": transcript_with_ask}
    _, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert macos_subtitles[0] == "Needs Input", \
        f"Expected 'Needs Input' subtitle, got {macos_subtitles[0]!r}"


def test_stop_without_ask_slack_hook_type(base_hook_input, transcript_without_ask):
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    slack_payloads, _ = load_and_run_stop_hook(hook_input)
    assert slack_payloads[0]["hook_type"] == "stop_complete", \
        f"Expected hook_type 'stop_complete', got {slack_payloads[0]['hook_type']!r}"


def test_stop_with_ask_slack_hook_type(base_hook_input, transcript_with_ask):
    hook_input = {**base_hook_input, "transcript_path": transcript_with_ask}
    slack_payloads, _ = load_and_run_stop_hook(hook_input)
    assert slack_payloads[0]["hook_type"] == "stop_needs_input", \
        f"Expected hook_type 'stop_needs_input', got {slack_payloads[0]['hook_type']!r}"


def test_stop_skips_all_notifications_in_subagent_context(base_hook_input, transcript_without_ask):
    """Stop hook must not notify when agent_type is present (subagent context)."""
    hook_input = {
        **base_hook_input,
        "transcript_path": transcript_without_ask,
        "agent_type": "Explore",  # real agent_type value from Claude Code SubagentStop schema
    }
    slack_payloads, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert len(slack_payloads) == 0, "Stop hook must not send Slack in subagent context"
    assert len(macos_subtitles) == 0, "Stop hook must not send macOS notification in subagent context"


def test_stop_still_notifies_when_agent_type_absent(base_hook_input, transcript_without_ask):
    """Stop hook must still notify when agent_type is absent (main agent context)."""
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    # Ensure agent_type is not present
    assert "agent_type" not in hook_input
    slack_payloads, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert len(slack_payloads) == 1, "Stop hook must send Slack in main agent context"
    assert len(macos_subtitles) == 1, "Stop hook must send macOS notification in main agent context"


# --- Active-subagent notification suppression ---


def test_stop_sends_zero_notifications_with_active_subagent(base_hook_input, transcript_without_ask, active_subagent_home):
    # Why: a Stop while a background subagent is still running is just the main
    # agent checking in — it must not spam Slack/macOS as if the task were done.
    marker_dir = active_subagent_home / "test-session-123"
    marker_dir.mkdir(parents=True)
    (marker_dir / "marker-1").touch()
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    slack_payloads, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert len(slack_payloads) == 0, "Stop hook must not send Slack while a subagent is active"
    assert len(macos_subtitles) == 0, "Stop hook must not send macOS notification while a subagent is active"


def test_stop_still_notifies_with_active_subagent_and_genuine_needs_input(base_hook_input, transcript_with_ask, active_subagent_home):
    # Why: regression guard for the needs_input-always-wins rule — a genuine
    # AskUserQuestion must still notify even while background subagents run.
    marker_dir = active_subagent_home / "test-session-123"
    marker_dir.mkdir(parents=True)
    (marker_dir / "marker-1").touch()
    hook_input = {**base_hook_input, "transcript_path": transcript_with_ask}
    slack_payloads, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert len(slack_payloads) == 1, "needs_input must still notify even with an active subagent"
    assert len(macos_subtitles) == 1, "needs_input must still notify even with an active subagent"
    assert macos_subtitles[0] == "Needs Input"


def test_stop_with_zero_active_subagents_notifies_as_before(base_hook_input, transcript_without_ask, active_subagent_home):
    # Why: regression guard — with no active-subagent markers at all, today's
    # notification behavior must be completely unchanged.
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    slack_payloads, macos_subtitles = load_and_run_stop_hook(hook_input)
    assert len(slack_payloads) == 1
    assert len(macos_subtitles) == 1
