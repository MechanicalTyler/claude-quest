# tests/test_notification_hook.py
import json
from io import StringIO
from unittest.mock import patch, MagicMock
import importlib.util
from pathlib import Path


def load_and_run_hook(hook_input: dict):
    """Run notifications_notification hook, return (slack_called, macos_called)."""
    spec = importlib.util.spec_from_file_location(
        "notifications_notification",
        Path(__file__).parent.parent / "hooks" / "notifications_notification.py"
    )
    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post") as mock_post, \
         patch("subprocess.run") as mock_subprocess:
        mock_post.return_value = MagicMock(status_code=200, text="ok")
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit:
            pass
        return mock_post.called, mock_subprocess.called


# --- Non-actionable types should NOT notify ---

def test_auth_success_no_slack(base_hook_input, transcript_without_ask):
    slack_called, _ = load_and_run_hook({
        **base_hook_input,
        "notification_type": "auth_success",
        "transcript_path": transcript_without_ask,
    })
    assert not slack_called, "auth_success must not send Slack notification"


def test_auth_success_no_macos(base_hook_input, transcript_without_ask):
    _, macos_called = load_and_run_hook({
        **base_hook_input,
        "notification_type": "auth_success",
        "transcript_path": transcript_without_ask,
    })
    assert not macos_called, "auth_success must not send macOS notification"


def test_unknown_type_no_slack(base_hook_input, transcript_without_ask):
    slack_called, _ = load_and_run_hook({
        **base_hook_input,
        "notification_type": "some_future_type",
        "transcript_path": transcript_without_ask,
    })
    assert not slack_called, "Unknown notification type must not send Slack notification"


def test_unknown_type_no_macos(base_hook_input, transcript_without_ask):
    _, macos_called = load_and_run_hook({
        **base_hook_input,
        "notification_type": "some_future_type",
        "transcript_path": transcript_without_ask,
    })
    assert not macos_called, "Unknown notification type must not send macOS notification"


# --- Actionable types MUST notify both channels ---

def test_permission_prompt_sends_slack(base_hook_input, transcript_without_ask):
    slack_called, _ = load_and_run_hook({
        **base_hook_input,
        "notification_type": "permission_prompt",
        "transcript_path": transcript_without_ask,
    })
    assert slack_called, "permission_prompt must send Slack notification"


def test_permission_prompt_sends_macos(base_hook_input, transcript_without_ask):
    _, macos_called = load_and_run_hook({
        **base_hook_input,
        "notification_type": "permission_prompt",
        "transcript_path": transcript_without_ask,
    })
    assert macos_called, "permission_prompt must send macOS notification"


def test_idle_prompt_sends_both(base_hook_input, transcript_without_ask):
    slack_called, macos_called = load_and_run_hook({
        **base_hook_input,
        "notification_type": "idle_prompt",
        "transcript_path": transcript_without_ask,
    })
    assert slack_called, "idle_prompt must send Slack notification"
    assert macos_called, "idle_prompt must send macOS notification"


def test_elicitation_dialog_sends_both(base_hook_input, transcript_without_ask):
    slack_called, macos_called = load_and_run_hook({
        **base_hook_input,
        "notification_type": "elicitation_dialog",
        "transcript_path": transcript_without_ask,
    })
    assert slack_called, "elicitation_dialog must send Slack notification"
    assert macos_called, "elicitation_dialog must send macOS notification"


# --- permission_prompt with tool_use-only transcript (no text in latest assistant message) ---

def test_permission_prompt_tool_use_only_transcript_sends_slack(base_hook_input, transcript_tool_use_only):
    """When permission_prompt fires and transcript has no text blocks, fallback to input message field."""
    slack_called, _ = load_and_run_hook({
        **base_hook_input,
        "notification_type": "permission_prompt",
        "message": "Claude needs your permission to use Bash",
        "transcript_path": transcript_tool_use_only,
    })
    assert slack_called, "permission_prompt with tool-use-only transcript must send Slack notification"


def test_permission_prompt_tool_use_only_transcript_sends_macos(base_hook_input, transcript_tool_use_only):
    """When permission_prompt fires and transcript has no text blocks, fallback to input message field."""
    _, macos_called = load_and_run_hook({
        **base_hook_input,
        "notification_type": "permission_prompt",
        "message": "Claude needs your permission to use Bash",
        "transcript_path": transcript_tool_use_only,
    })
    assert macos_called, "permission_prompt with tool-use-only transcript must send macOS notification"
