# tests/test_channel_flags.py
import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock


def load_client():
    spec = importlib.util.spec_from_file_location(
        "attention_hub_client",
        Path(__file__).parent.parent / "hooks" / "attention_hub_client.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- Flag helpers ---

def test_macos_enabled_by_default(monkeypatch):
    # Why: defaults must preserve current behavior — macOS notifications keep
    # arriving for users who never set any flag.
    monkeypatch.delenv("CLAUDE_NOTIFY_MACOS", raising=False)
    assert load_client().macos_enabled() is True


def test_slack_enabled_by_default(monkeypatch):
    # Why: defaults must preserve current behavior — Slack notifications keep
    # arriving for users who never set any flag.
    monkeypatch.delenv("CLAUDE_NOTIFY_SLACK", raising=False)
    assert load_client().slack_enabled() is True


def test_macos_disabled_by_flag_values(monkeypatch):
    # Why: the story requires each channel to be individually disableable; the
    # accepted "off" spellings must all work so users aren't surprised.
    client = load_client()
    for value in ("0", "false", "no", "off", "FALSE", "Off"):
        monkeypatch.setenv("CLAUDE_NOTIFY_MACOS", value)
        assert client.macos_enabled() is False, f"{value!r} should disable macOS"


def test_slack_disabled_by_flag_values(monkeypatch):
    # Why: same disable contract for the Slack channel, independent of macOS.
    client = load_client()
    for value in ("0", "false", "no", "off"):
        monkeypatch.setenv("CLAUDE_NOTIFY_SLACK", value)
        assert client.slack_enabled() is False, f"{value!r} should disable Slack"


def test_truthy_values_keep_channel_enabled(monkeypatch):
    # Why: explicit "on" values (or junk) must not accidentally disable a channel —
    # only documented falsy spellings turn it off.
    client = load_client()
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("CLAUDE_NOTIFY_MACOS", value)
        assert client.macos_enabled() is True, f"{value!r} should keep macOS enabled"


# --- Hook-level gating ---

def run_notification_hook(hook_input):
    spec = importlib.util.spec_from_file_location(
        "notifications_notification",
        Path(__file__).parent.parent / "hooks" / "notifications_notification.py"
    )
    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post") as mock_post, \
         patch("subprocess.run") as mock_subprocess, \
         patch("urllib.request.urlopen") as mock_urlopen:
        mock_post.return_value = MagicMock(status_code=200, text="ok")
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        mock_urlopen.return_value = MagicMock(status=200)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit:
            pass
        return mock_post.called, mock_subprocess.called


def actionable_input(base_hook_input, transcript_without_ask):
    return {
        **base_hook_input,
        "notification_type": "permission_prompt",
        "transcript_path": transcript_without_ask,
    }


def test_slack_flag_suppresses_slack_only(monkeypatch, base_hook_input, transcript_without_ask):
    # Why: CLAUDE_NOTIFY_SLACK=0 must silence Slack without touching macOS —
    # flags are per-channel, not global.
    monkeypatch.setenv("CLAUDE_NOTIFY_SLACK", "0")
    monkeypatch.delenv("CLAUDE_NOTIFY_MACOS", raising=False)
    slack_called, macos_called = run_notification_hook(
        actionable_input(base_hook_input, transcript_without_ask))
    assert not slack_called, "Slack must be suppressed when CLAUDE_NOTIFY_SLACK=0"
    assert macos_called, "macOS must still send when only Slack is disabled"


def test_macos_flag_suppresses_macos_only(monkeypatch, base_hook_input, transcript_without_ask):
    # Why: CLAUDE_NOTIFY_MACOS=0 must silence macOS without touching Slack.
    monkeypatch.setenv("CLAUDE_NOTIFY_MACOS", "0")
    monkeypatch.delenv("CLAUDE_NOTIFY_SLACK", raising=False)
    slack_called, macos_called = run_notification_hook(
        actionable_input(base_hook_input, transcript_without_ask))
    assert slack_called, "Slack must still send when only macOS is disabled"
    assert not macos_called, "macOS must be suppressed when CLAUDE_NOTIFY_MACOS=0"


def run_stop_hook(hook_input, urlopen_side_effect=None):
    spec = importlib.util.spec_from_file_location(
        "notifications_stop",
        Path(__file__).parent.parent / "hooks" / "notifications_stop.py"
    )
    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post") as mock_post, \
         patch("subprocess.run") as mock_subprocess, \
         patch("urllib.request.urlopen",
               side_effect=urlopen_side_effect) as mock_urlopen:
        mock_post.return_value = MagicMock(status_code=200, text="ok")
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        if urlopen_side_effect is None:
            mock_urlopen.side_effect = None
            mock_urlopen.return_value = MagicMock(status=200)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit:
            pass
        return mock_post.called, mock_subprocess.called


def test_stop_slack_flag_suppresses_slack_only(monkeypatch, base_hook_input, transcript_without_ask):
    # Why: the Stop hook has its own gating branches; CLAUDE_NOTIFY_SLACK=0 must
    # silence its Slack send without touching macOS.
    monkeypatch.setenv("CLAUDE_NOTIFY_SLACK", "0")
    monkeypatch.delenv("CLAUDE_NOTIFY_MACOS", raising=False)
    slack_called, macos_called = run_stop_hook(
        {**base_hook_input, "transcript_path": transcript_without_ask})
    assert not slack_called, "Stop hook Slack must be suppressed when CLAUDE_NOTIFY_SLACK=0"
    assert macos_called, "Stop hook macOS must still send when only Slack is disabled"


def test_stop_macos_flag_suppresses_macos_only(monkeypatch, base_hook_input, transcript_without_ask):
    # Why: CLAUDE_NOTIFY_MACOS=0 must silence the Stop hook's macOS send without
    # touching Slack.
    monkeypatch.setenv("CLAUDE_NOTIFY_MACOS", "0")
    monkeypatch.delenv("CLAUDE_NOTIFY_SLACK", raising=False)
    slack_called, macos_called = run_stop_hook(
        {**base_hook_input, "transcript_path": transcript_without_ask})
    assert slack_called, "Stop hook Slack must still send when only macOS is disabled"
    assert not macos_called, "Stop hook macOS must be suppressed when CLAUDE_NOTIFY_MACOS=0"


def test_stop_hub_failure_does_not_stop_channels(monkeypatch, base_hook_input, transcript_without_ask):
    # Why: the spec requires a failing hub to never suppress the existing
    # macOS/Slack notifications — hub reporting is additive, not a gate.
    monkeypatch.delenv("CLAUDE_NOTIFY_MACOS", raising=False)
    monkeypatch.delenv("CLAUDE_NOTIFY_SLACK", raising=False)
    slack_called, macos_called = run_stop_hook(
        {**base_hook_input, "transcript_path": transcript_without_ask},
        urlopen_side_effect=ConnectionRefusedError("hub down"))
    assert slack_called and macos_called, \
        "Hub failure must not stop the Slack/macOS sends in the Stop hook"


def test_notification_hub_failure_does_not_stop_channels(monkeypatch, base_hook_input, transcript_without_ask):
    # Why: same hub-failure guarantee for the Notification hook path.
    monkeypatch.delenv("CLAUDE_NOTIFY_MACOS", raising=False)
    monkeypatch.delenv("CLAUDE_NOTIFY_SLACK", raising=False)
    spec = importlib.util.spec_from_file_location(
        "notifications_notification",
        Path(__file__).parent.parent / "hooks" / "notifications_notification.py"
    )
    hook_input = actionable_input(base_hook_input, transcript_without_ask)
    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post") as mock_post, \
         patch("subprocess.run") as mock_subprocess, \
         patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("hub down")):
        mock_post.return_value = MagicMock(status_code=200, text="ok")
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit:
            pass
        assert mock_post.called and mock_subprocess.called, \
            "Hub failure must not stop the Slack/macOS sends in the Notification hook"


def test_defaults_send_both_channels(monkeypatch, base_hook_input, transcript_without_ask):
    # Why: regression guard — with no flags set, both channels behave exactly as
    # before this feature (the story's "unchanged by default" criterion).
    monkeypatch.delenv("CLAUDE_NOTIFY_MACOS", raising=False)
    monkeypatch.delenv("CLAUDE_NOTIFY_SLACK", raising=False)
    slack_called, macos_called = run_notification_hook(
        actionable_input(base_hook_input, transcript_without_ask))
    assert slack_called and macos_called, "Defaults must send both channels"
