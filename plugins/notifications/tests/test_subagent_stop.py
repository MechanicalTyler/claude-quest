"""
Tests for notifications_subagent_stop.py -- flips one active-subagent marker
to completed using notifications' own independent tracker.
"""

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


def run_hook(hook_input):
    """Run the subagent_stop hook, return (slack_called, macos_called)."""
    spec = importlib.util.spec_from_file_location(
        "notifications_subagent_stop", HOOKS_DIR / "notifications_subagent_stop.py"
    )
    with patch("sys.stdin", StringIO(json.dumps(hook_input))), \
         patch("requests.post") as mock_post, \
         patch("subprocess.run") as mock_subprocess:
        mock_post.return_value = MagicMock(status_code=200, text="ok")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit:
            pass
        return mock_post.called, mock_subprocess.called


def test_subagent_stop_does_not_send_slack(base_hook_input):
    # Why: SubagentStop should never send Slack -- the main agent is still running.
    slack_called, _ = run_hook(base_hook_input)
    assert not slack_called


def test_subagent_stop_does_not_send_macos(base_hook_input):
    # Why: SubagentStop should never send macOS -- user action isn't required yet.
    _, macos_called = run_hook(base_hook_input)
    assert not macos_called


def test_subagent_stop_clears_exactly_one_active_marker(base_hook_input, active_subagent_home):
    # Why: SubagentStop must flip exactly one marker to completed per
    # completed subagent -- both files remain, one flipped, one still active.
    marker_dir = active_subagent_home / "test-session-123"
    marker_dir.mkdir(parents=True)
    (marker_dir / "marker-1").touch()
    (marker_dir / "marker-2").touch()
    run_hook(base_hook_input)

    spec = importlib.util.spec_from_file_location(
        "subagent_tracker", HOOKS_DIR / "subagent_tracker.py"
    )
    tracker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tracker)

    remaining = list(marker_dir.iterdir())
    assert len(remaining) == 2
    records = [tracker._read_marker(m) for m in remaining]
    completed = [r for r in records if r["status"] == "completed"]
    active = [r for r in records if r["status"] == "active"]
    assert len(completed) == 1
    assert len(active) == 1


def test_subagent_stop_with_no_markers_is_a_noop(base_hook_input, active_subagent_home):
    # Why: SubagentStop firing with no active markers must not raise or crash.
    exit_code = 0
    spec = importlib.util.spec_from_file_location(
        "notifications_subagent_stop", HOOKS_DIR / "notifications_subagent_stop.py"
    )
    with patch("sys.stdin", StringIO(json.dumps(base_hook_input))):
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit as e:
            exit_code = e.code or 0
    assert exit_code == 0
