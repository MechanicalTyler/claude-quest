# tests/test_pre_tool_use.py
import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


def run_pre_tool_use(hook_input, capsys):
    spec = importlib.util.spec_from_file_location(
        "notifications_pre_tool_use", HOOKS_DIR / "notifications_pre_tool_use.py"
    )
    with patch("sys.stdin", StringIO(json.dumps(hook_input))):
        mod = importlib.util.module_from_spec(spec)
        exit_code = 0
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit as e:
            exit_code = e.code or 0
    return exit_code, capsys.readouterr().out


def test_task_dispatch_marks_session_active(base_hook_input, active_subagent_home, capsys):
    # Why: this is the entire mechanism notifications' suppression depends on --
    # without a marker created here, the Stop hook has no signal a subagent runs.
    run_pre_tool_use({**base_hook_input, "tool_name": "Agent"}, capsys)
    marker_dir = active_subagent_home / "test-session-123"
    assert marker_dir.is_dir()
    assert len(list(marker_dir.iterdir())) == 1


def test_non_task_tool_creates_no_marker(base_hook_input, active_subagent_home, capsys):
    # Why: must be a complete no-op for every other tool.
    run_pre_tool_use({**base_hook_input, "tool_name": "Bash"}, capsys)
    assert not (active_subagent_home / "test-session-123").exists()


def test_task_dispatch_exits_zero_and_emits_no_decision_payload(base_hook_input, active_subagent_home, capsys):
    # Why: highest-severity property -- a hook that ever blocks a Task dispatch
    # would stop subagents from running entirely.
    exit_code, out = run_pre_tool_use({**base_hook_input, "tool_name": "Agent"}, capsys)
    assert exit_code == 0
    assert "decision" not in out
    assert out.strip() == ""


def test_missing_tool_name_exits_zero_with_no_marker(base_hook_input, active_subagent_home, capsys):
    # Why: malformed/untrusted hook input must degrade to a safe no-op.
    exit_code, out = run_pre_tool_use(dict(base_hook_input), capsys)
    assert exit_code == 0
    assert out.strip() == ""
    assert not (active_subagent_home / "test-session-123").exists()


def test_malformed_stdin_exits_zero(active_subagent_home, capsys):
    # Why: a hook that raises on bad input would break the tool call it is
    # supposed to be silently observing.
    spec = importlib.util.spec_from_file_location(
        "notifications_pre_tool_use", HOOKS_DIR / "notifications_pre_tool_use.py"
    )
    with patch("sys.stdin", StringIO("not json")):
        mod = importlib.util.module_from_spec(spec)
        exit_code = 0
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit as e:
            exit_code = e.code or 0
    assert exit_code == 0


def test_backgrounded_bash_creates_bash_kind_marker(base_hook_input, active_subagent_home, capsys):
    # Why: only backgrounded Bash calls should be tracked as active work.
    run_pre_tool_use({**base_hook_input, "tool_name": "Bash",
                       "tool_input": {"run_in_background": True, "description": "run suite"}}, capsys)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "subagent_tracker", HOOKS_DIR / "subagent_tracker.py"
    )
    tracker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tracker)
    marker = next((active_subagent_home / "test-session-123").iterdir())
    record = tracker._read_marker(marker)
    assert record["kind"] == "bash"
    assert record["label"] == "run suite"


def test_foreground_bash_creates_no_marker(base_hook_input, active_subagent_home, capsys):
    # Why: a foreground command already blocks the turn and is not a
    # false-suppression risk.
    run_pre_tool_use({**base_hook_input, "tool_name": "Bash",
                       "tool_input": {"command": "ls"}}, capsys)
    assert not (active_subagent_home / "test-session-123").exists()
