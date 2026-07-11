"""
Tests for notifications_session_end.py -- clears notifications' own
active-subagent marker directory at session teardown. No hub `remove_session`
call: this plugin has no hub relationship to tear down.
"""

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


def run_hook(hook_input):
    spec = importlib.util.spec_from_file_location(
        "notifications_session_end", HOOKS_DIR / "notifications_session_end.py"
    )
    exit_code = 0
    with patch("sys.stdin", StringIO(json.dumps(hook_input))):
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit as e:
            exit_code = e.code or 0
    return exit_code


def test_session_end_clears_all_active_subagent_markers(base_hook_input, active_subagent_home):
    # Why: parallels attention-hub's own SessionEnd assertion -- ending a
    # session must clear every one of its active-subagent markers.
    marker_dir = active_subagent_home / "test-session-123"
    marker_dir.mkdir(parents=True)
    (marker_dir / "marker-1").touch()
    (marker_dir / "marker-2").touch()
    run_hook({**base_hook_input, "reason": "exit"})
    assert not marker_dir.exists()


def test_session_end_without_session_id_is_a_noop(base_hook_input, active_subagent_home):
    # Why: without a session ID there is nothing to key the cleanup to; the
    # hook must stay silent and exit 0.
    hook_input = {**base_hook_input, "reason": "exit"}
    hook_input["session_id"] = ""
    exit_code = run_hook(hook_input)
    assert exit_code == 0


def test_session_end_exits_zero_with_no_markers(base_hook_input, active_subagent_home):
    # Why: a session that never dispatched a subagent has no markers at all --
    # cleanup must be a safe no-op, not an error.
    exit_code = run_hook({**base_hook_input, "reason": "exit"})
    assert exit_code == 0


def test_session_end_does_not_affect_other_sessions(base_hook_input, active_subagent_home):
    # Why: teardown is per-session -- must never touch another session's markers.
    other_dir = active_subagent_home / "other-session"
    other_dir.mkdir(parents=True)
    (other_dir / "marker-1").touch()
    run_hook({**base_hook_input, "reason": "exit"})
    assert other_dir.exists()
