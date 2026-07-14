import importlib.util
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
HOOKS_DIR = Path(__file__).parent.parent / "hooks"


@pytest.fixture
def reflection_home(tmp_path, monkeypatch):
    """Redirect HOME to tmp_path so LOG_PATH and NUDGE_DIR resolve into the
    test home, never the real ~/.claude/reflection state."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "reflection"


@pytest.fixture
def stop_hook(reflection_home):
    """Load reflection_stop.py fresh, after HOME is redirected, so its
    module-level LOG_PATH/NUDGE_DIR point into the test home."""
    spec = importlib.util.spec_from_file_location(
        "reflection_stop", HOOKS_DIR / "reflection_stop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture_copy(name, tmp_path):
    dest = tmp_path / name
    dest.write_text((FIXTURES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return str(dest)


@pytest.fixture
def transcript_done_transition(tmp_path):
    """mcp__ story-update call plus a done-type state in a later tool result."""
    return _fixture_copy("transcript_done_transition.jsonl", tmp_path)


@pytest.fixture
def transcript_done_transition_reversed(tmp_path):
    """Done-type state appears in a tool result before the update call."""
    return _fixture_copy("transcript_done_transition_reversed.jsonl", tmp_path)


@pytest.fixture
def transcript_update_call_only(tmp_path):
    """Signal A only: story-update call, no done-type value anywhere."""
    return _fixture_copy("transcript_update_call_only.jsonl", tmp_path)


@pytest.fixture
def transcript_done_result_only(tmp_path):
    """Signal B only: done-type state in a result, no update-ish call."""
    return _fixture_copy("transcript_done_result_only.jsonl", tmp_path)


@pytest.fixture
def transcript_taskupdate_completed(tmp_path):
    """Built-in TaskUpdate marking a to-do completed — not mcp__-prefixed."""
    return _fixture_copy("transcript_taskupdate_completed.jsonl", tmp_path)


@pytest.fixture
def transcript_signoff(tmp_path):
    """Last user message is a literal sign-off phrase; no tool calls."""
    return _fixture_copy("transcript_signoff.jsonl", tmp_path)


@pytest.fixture
def transcript_no_signals(tmp_path):
    """Plain conversation: no sign-off, no PM tool activity."""
    return _fixture_copy("transcript_no_signals.jsonl", tmp_path)


@pytest.fixture
def transcript_malformed(tmp_path):
    """Truncated JSONL line mid-file plus a valid done transition after it."""
    return _fixture_copy("transcript_malformed.jsonl", tmp_path)
