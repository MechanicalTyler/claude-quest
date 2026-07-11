# tests/test_pre_tool_use.py
import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


def run_pre_tool_use(hook_input, capsys):
    """Run attention_hub_pre_tool_use, return (exit_code, stdout)."""
    spec = importlib.util.spec_from_file_location(
        "attention_hub_pre_tool_use", HOOKS_DIR / "attention_hub_pre_tool_use.py"
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
    # Why: this is the entire mechanism the story depends on — without a marker
    # created here, the Stop hook has no signal that a subagent is running.
    run_pre_tool_use({**base_hook_input, "tool_name": "Task"}, capsys)
    marker_dir = active_subagent_home / "test-session-123"
    assert marker_dir.is_dir()
    assert len(list(marker_dir.iterdir())) == 1


def test_non_task_tool_creates_no_marker(base_hook_input, active_subagent_home, capsys):
    # Why: the hook must be a complete no-op for every other tool — marking
    # unrelated tool calls as "subagent active" would falsely mask real completions.
    run_pre_tool_use({**base_hook_input, "tool_name": "Bash"}, capsys)
    assert not (active_subagent_home / "test-session-123").exists()


def test_non_task_tool_makes_no_hub_or_network_calls(base_hook_input, active_subagent_home, capsys):
    # Why: PreToolUse fires before every tool call forever; any network activity on
    # the fast path would add latency to every single tool use in every session.
    with patch("urllib.request.urlopen") as mock_urlopen:
        run_pre_tool_use({**base_hook_input, "tool_name": "Bash"}, capsys)
        assert not mock_urlopen.called


def test_task_dispatch_exits_zero_and_emits_no_decision_payload(base_hook_input, active_subagent_home, capsys):
    # Why: highest-severity property in this change — a hook that ever blocks a
    # Task dispatch would stop subagents from running entirely.
    exit_code, out = run_pre_tool_use({**base_hook_input, "tool_name": "Task"}, capsys)
    assert exit_code == 0
    assert "decision" not in out
    assert out.strip() == ""


def test_non_task_tool_exits_zero_and_emits_no_decision_payload(base_hook_input, active_subagent_home, capsys):
    # Why: the pure-observer constraint applies to every tool_name, not just Task —
    # this hook must never gate any tool call under any circumstances.
    exit_code, out = run_pre_tool_use({**base_hook_input, "tool_name": "Bash"}, capsys)
    assert exit_code == 0
    assert "decision" not in out
    assert out.strip() == ""


def test_missing_tool_name_exits_zero_with_no_marker(base_hook_input, active_subagent_home, capsys):
    # Why: malformed/untrusted hook input must degrade to a safe no-op, never raise
    # or block.
    hook_input = dict(base_hook_input)
    exit_code, out = run_pre_tool_use(hook_input, capsys)
    assert exit_code == 0
    assert out.strip() == ""
    assert not (active_subagent_home / "test-session-123").exists()


def test_malformed_stdin_exits_zero(active_subagent_home, capsys):
    # Why: a hook that raises on bad input would break the tool call it is
    # supposed to be silently observing.
    spec = importlib.util.spec_from_file_location(
        "attention_hub_pre_tool_use", HOOKS_DIR / "attention_hub_pre_tool_use.py"
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


def test_task_dispatch_captures_description_as_label(base_hook_input, active_subagent_home, capsys):
    # Why: AC-3 -- markers must carry a usable identifier, not stay anonymous.
    # [Inference] the description field's presence on Task's tool_input is
    # unconfirmed -- see spec's verification decision; this test locks in
    # the assumed shape so a live-payload mismatch is a one-line fix here.
    run_pre_tool_use({**base_hook_input, "tool_name": "Task",
                       "tool_input": {"description": "fix the bug"}}, capsys)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "attention_hub_client", HOOKS_DIR / "attention_hub_client.py"
    )
    hub_client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hub_client)
    marker = next((active_subagent_home / "test-session-123").iterdir())
    assert hub_client._read_marker(marker)["label"] == "fix the bug"


def test_backgrounded_bash_creates_bash_kind_marker(base_hook_input, active_subagent_home, capsys):
    run_pre_tool_use({**base_hook_input, "tool_name": "Bash",
                       "tool_input": {"run_in_background": True, "description": "run suite"}}, capsys)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "attention_hub_client", HOOKS_DIR / "attention_hub_client.py"
    )
    hub_client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hub_client)
    marker = next((active_subagent_home / "test-session-123").iterdir())
    record = hub_client._read_marker(marker)
    assert record["kind"] == "bash"
    assert record["label"] == "run suite"


def test_foreground_bash_creates_no_marker(base_hook_input, active_subagent_home, capsys):
    # Why: only backgrounded Bash calls should be tracked -- a foreground
    # command already blocks the turn and is not a false-done risk.
    run_pre_tool_use({**base_hook_input, "tool_name": "Bash",
                       "tool_input": {"command": "ls"}}, capsys)
    assert not (active_subagent_home / "test-session-123").exists()


def test_workflow_dispatch_creates_workflow_kind_marker(base_hook_input, active_subagent_home, capsys):
    # Why: [Unverified] the "Workflow" tool_name string is an unconfirmed
    # assumption -- see spec's verification decision. This test locks in the
    # assumed detection so a live-payload mismatch is a one-line fix.
    run_pre_tool_use({**base_hook_input, "tool_name": "Workflow",
                       "tool_input": {"description": "run migration"}}, capsys)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "attention_hub_client", HOOKS_DIR / "attention_hub_client.py"
    )
    hub_client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hub_client)
    marker = next((active_subagent_home / "test-session-123").iterdir())
    assert hub_client._read_marker(marker)["kind"] == "workflow"


def test_persistent_monitor_creates_monitor_kind_marker(base_hook_input, active_subagent_home, capsys):
    # Why: [Unverified] the "Monitor" tool_name string is an unconfirmed
    # assumption -- same treatment as Workflow above.
    run_pre_tool_use({**base_hook_input, "tool_name": "Monitor",
                       "tool_input": {"persistent": True, "description": "watch logs"}}, capsys)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "attention_hub_client", HOOKS_DIR / "attention_hub_client.py"
    )
    hub_client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hub_client)
    marker = next((active_subagent_home / "test-session-123").iterdir())
    assert hub_client._read_marker(marker)["kind"] == "monitor"


def test_non_persistent_monitor_creates_no_marker(base_hook_input, active_subagent_home, capsys):
    run_pre_tool_use({**base_hook_input, "tool_name": "Monitor",
                       "tool_input": {"persistent": False}}, capsys)
    assert not (active_subagent_home / "test-session-123").exists()
