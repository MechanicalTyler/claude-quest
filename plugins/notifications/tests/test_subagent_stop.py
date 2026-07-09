# tests/test_subagent_stop.py
import json
import sys
from io import StringIO
from unittest.mock import patch, MagicMock
import importlib.util
from pathlib import Path


def load_hook(name):
    """Load a hook script as a module."""
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).parent.parent / "hooks" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_hook(hook_input: dict):
    """Run the subagent_stop hook with given stdin input, return (slack_called, macos_called)."""
    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post") as mock_post, \
         patch("subprocess.run") as mock_subprocess:
        mock_post.return_value = MagicMock(status_code=200, text="ok")
        try:
            mod = load_hook("notifications_subagent_stop")
            mod.main()
        except SystemExit:
            pass
        return mock_post.called, mock_subprocess.called


def test_subagent_stop_does_not_send_slack(base_hook_input, transcript_without_ask):
    """SubagentStop should never send Slack notifications."""
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    slack_called, _ = run_hook(hook_input)
    assert not slack_called, "SubagentStop must not send Slack notifications"


def test_subagent_stop_does_not_send_macos(base_hook_input, transcript_without_ask):
    """SubagentStop should never send macOS notifications."""
    hook_input = {**base_hook_input, "transcript_path": transcript_without_ask}
    _, macos_called = run_hook(hook_input)
    assert not macos_called, "SubagentStop must not send macOS notifications"
