# tests/conftest.py
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def transcript_without_ask(tmp_path):
    """Transcript file where last assistant message has no AskUserQuestion."""
    src = FIXTURES_DIR / "transcript_without_ask.jsonl"
    dest = tmp_path / "transcript_without_ask.jsonl"
    dest.write_text(src.read_text())
    return str(dest)


@pytest.fixture
def marker_home(tmp_path, monkeypatch):
    """Redirect HOME to tmp_path so waiting-marker files (and hook logs) never
    touch the real ~/.claude. Returns the marker directory path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "attention-hub" / "waiting-markers"


@pytest.fixture
def active_subagent_home(tmp_path, monkeypatch):
    """Redirect HOME to tmp_path so active-subagent marker files (and hook
    logs) never touch the real ~/.claude. Returns the active-subagents
    directory path (parent of each session's own marker subdirectory)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "attention-hub" / "active-subagents"


@pytest.fixture
def base_hook_input():
    """Base stdin payload common to all hooks."""
    return {
        "session_id": "test-session-123",
        "transcript_path": "",
        "cwd": "/fake/test-project",
        "permission_mode": "default",
    }
