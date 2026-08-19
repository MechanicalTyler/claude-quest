import importlib.util
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


@pytest.fixture
def reflection_home(tmp_path, monkeypatch):
    """Redirect HOME to tmp_path so LOG_PATH resolves into the test home,
    never the real ~/.claude/reflection state."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "reflection"


@pytest.fixture
def session_start_hook(reflection_home):
    """Load reflection_session_start.py fresh, after HOME is redirected, so
    its module-level LOG_PATH resolves into the test home."""
    spec = importlib.util.spec_from_file_location(
        "reflection_session_start", HOOKS_DIR / "reflection_session_start.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
