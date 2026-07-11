# tests/test_waiting_marker.py
import importlib.util
import os
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


@pytest.fixture
def hub_client(marker_home):
    """Load a fresh attention_hub_client with HOME redirected to tmp_path."""
    spec = importlib.util.spec_from_file_location(
        "attention_hub_client", HOOKS_DIR / "attention_hub_client.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_marker_set_check_clear_roundtrip(hub_client, marker_home):
    # Why: the marker is the entire debounce mechanism — set must create the file,
    # check must see it, and clear must remove it and report that it existed.
    assert hub_client.set_waiting_marker("session-abc") is True
    assert (marker_home / "session-abc").is_file()
    assert hub_client.has_waiting_marker("session-abc") is True
    assert hub_client.clear_waiting_marker("session-abc") is True
    assert not (marker_home / "session-abc").exists()
    assert hub_client.has_waiting_marker("session-abc") is False


def test_clear_missing_marker_returns_false(hub_client, marker_home):
    # Why: PostToolUse gates its only network call on clear's return value — a false
    # positive for a missing marker would defeat the zero-network fast path.
    assert hub_client.clear_waiting_marker("never-set") is False


def test_helpers_reject_hostile_session_ids(hub_client, marker_home):
    # Why: the session ID becomes a filename; path separators or traversal must not
    # let a malicious hook input write or delete files outside the marker dir.
    for hostile in ("../escape", "a/b", "a\\b", "/etc/passwd", "..", ".", ""):
        assert hub_client.set_waiting_marker(hostile) is False
        assert hub_client.has_waiting_marker(hostile) is False
        assert hub_client.clear_waiting_marker(hostile) is False
    assert not (marker_home.parent.parent.parent / "escape").exists()


def test_helpers_tolerate_unwritable_marker_dir(hub_client, marker_home):
    # Why: hooks must never raise — a read-only ~/.claude must degrade to "no
    # marker" silently instead of erroring the Claude session.
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    marker_home.mkdir(parents=True)
    marker_home.chmod(0o500)
    try:
        assert hub_client.set_waiting_marker("session-abc") is False
        assert hub_client.has_waiting_marker("session-abc") is False
        assert hub_client.clear_waiting_marker("session-abc") is False
    finally:
        marker_home.chmod(0o700)


def test_helpers_tolerate_none_session_id(hub_client, marker_home):
    # Why: hook inputs are untrusted JSON — a null session_id must behave as "no
    # marker", never raise.
    assert hub_client.set_waiting_marker(None) is False
    assert hub_client.has_waiting_marker(None) is False
    assert hub_client.clear_waiting_marker(None) is False


# --- Active-subagent marker mechanics ---


def test_mark_one_subagent_active_counts_one(hub_client, active_subagent_home):
    # Why: a single Task dispatch must register exactly one active subagent so the
    # Stop hook can tell "background work in flight" from "nothing running".
    assert hub_client.mark_subagent_active("session-abc") is True
    assert hub_client.count_active_subagents("session-abc") == 1
    assert (active_subagent_home / "session-abc").is_dir()


def test_mark_two_subagents_active_counts_two(hub_client, active_subagent_home):
    # Why: multiple concurrent Task dispatches from the same session must each get
    # their own marker file, not overwrite each other, so the count reflects reality.
    hub_client.mark_subagent_active("session-abc")
    hub_client.mark_subagent_active("session-abc")
    assert hub_client.count_active_subagents("session-abc") == 2


def test_mark_many_concurrent_subagents_all_count(hub_client, active_subagent_home):
    # Why: the uuid4-token exclusive-create scheme must scale to many parallel
    # dispatches without any filename collision silently dropping a marker.
    for _ in range(25):
        assert hub_client.mark_subagent_active("session-abc") is True
    assert hub_client.count_active_subagents("session-abc") == 25
    assert len(list((active_subagent_home / "session-abc").iterdir())) == 25


def test_mark_creates_uniquely_named_marker_files(hub_client, active_subagent_home):
    # Why: markers are named with a fresh uuid4 token specifically so concurrent
    # dispatches can never collide on a filename — verify the names are distinct.
    hub_client.mark_subagent_active("session-abc")
    hub_client.mark_subagent_active("session-abc")
    names = {p.name for p in (active_subagent_home / "session-abc").iterdir()}
    assert len(names) == 2


def test_clear_one_marker_decrements_count_by_one(hub_client, active_subagent_home):
    # Why: markers are interchangeable — only the count matters — so clearing must
    # remove exactly one, regardless of which, without needing a start/stop ID.
    hub_client.mark_subagent_active("session-abc")
    hub_client.mark_subagent_active("session-abc")
    hub_client.mark_subagent_active("session-abc")
    assert hub_client.clear_active_subagent("session-abc") is True
    assert hub_client.count_active_subagents("session-abc") == 2


def test_clear_active_subagent_with_no_markers_returns_false(hub_client, active_subagent_home):
    # Why: SubagentStop firing with nothing to clear (e.g. a denied Task dispatch
    # cleaned up elsewhere) must report "nothing existed", not silently succeed.
    assert hub_client.clear_active_subagent("never-marked") is False


def test_stale_marker_excluded_from_count_and_pruned(hub_client, active_subagent_home):
    # Why: a crashed subagent that never fires SubagentStop must not wedge a
    # session on "working" forever — TTL-expired markers are excluded and removed.
    hub_client.mark_subagent_active("session-abc")
    marker_dir = active_subagent_home / "session-abc"
    stale_marker = next(marker_dir.iterdir())
    old_time = __import__("time").time() - hub_client.ACTIVE_SUBAGENT_TTL_SECONDS - 60
    os.utime(stale_marker, (old_time, old_time))
    assert hub_client.count_active_subagents("session-abc") == 0
    assert not stale_marker.exists()


def test_fresh_and_stale_markers_mixed_counts_only_fresh(hub_client, active_subagent_home):
    # Why: pruning must be selective — a mix of one stale and one fresh marker must
    # prune only the stale one and still report the fresh one as active.
    hub_client.mark_subagent_active("session-abc")
    hub_client.mark_subagent_active("session-abc")
    marker_dir = active_subagent_home / "session-abc"
    markers = list(marker_dir.iterdir())
    old_time = __import__("time").time() - hub_client.ACTIVE_SUBAGENT_TTL_SECONDS - 60
    os.utime(markers[0], (old_time, old_time))
    assert hub_client.count_active_subagents("session-abc") == 1
    assert not markers[0].exists()
    assert markers[1].exists()


def test_clear_all_active_subagents_zeroes_count(hub_client, active_subagent_home):
    # Why: session teardown must remove every marker at once, not one at a time,
    # so SessionEnd cleanup stays a single cheap operation.
    hub_client.mark_subagent_active("session-abc")
    hub_client.mark_subagent_active("session-abc")
    assert hub_client.clear_all_active_subagents("session-abc") is True
    assert hub_client.count_active_subagents("session-abc") == 0
    assert not (active_subagent_home / "session-abc").exists()


def test_clear_all_active_subagents_does_not_affect_other_sessions(hub_client, active_subagent_home):
    # Why: session teardown is per-session — clearing one session's markers must
    # never touch another session's still-active subagents.
    hub_client.mark_subagent_active("session-abc")
    hub_client.mark_subagent_active("session-xyz")
    hub_client.clear_all_active_subagents("session-abc")
    assert hub_client.count_active_subagents("session-xyz") == 1


def test_clear_all_active_subagents_with_none_returns_false(hub_client, active_subagent_home):
    # Why: SessionEnd cleanup for a session that never dispatched a subagent must
    # report "nothing existed" rather than raising or fabricating success.
    assert hub_client.clear_all_active_subagents("never-marked") is False


def test_active_subagent_helpers_reject_hostile_session_ids(hub_client, active_subagent_home):
    # Why: the session ID becomes a directory name; path separators or traversal
    # must not let a malicious hook input write or delete files outside the
    # active-subagents dir — same contract as the waiting marker.
    for hostile in ("../escape", "a/b", "a\\b", "/etc/passwd", "..", ".", ""):
        assert hub_client.mark_subagent_active(hostile) is False
        assert hub_client.count_active_subagents(hostile) == 0
        assert hub_client.clear_active_subagent(hostile) is False
        assert hub_client.clear_all_active_subagents(hostile) is False
    assert not (active_subagent_home.parent.parent.parent / "escape").exists()


def test_active_subagent_helpers_tolerate_none_session_id(hub_client, active_subagent_home):
    # Why: hook inputs are untrusted JSON — a null session_id must behave as "no
    # markers", never raise.
    assert hub_client.mark_subagent_active(None) is False
    assert hub_client.count_active_subagents(None) == 0
    assert hub_client.clear_active_subagent(None) is False
    assert hub_client.clear_all_active_subagents(None) is False


def test_count_active_subagents_with_no_directory_returns_zero(hub_client, active_subagent_home):
    # Why: a session that never dispatched a subagent has no directory at all —
    # counting must treat "missing" the same as "empty", not error.
    assert hub_client.count_active_subagents("untouched-session") == 0


def test_mark_subagent_active_writes_labeled_json_record(hub_client, active_subagent_home):
    # Why: AC-1 requires a per-subagent id/label/status/started_at record,
    # not an anonymous touch file -- this is the write path for it.
    hub_client.mark_subagent_active("session-abc", label="fix the thing")
    marker = next((active_subagent_home / "session-abc").iterdir())
    record = hub_client._read_marker(marker)
    assert record["id"] == marker.name
    assert record["kind"] == "task"
    assert record["label"] == "fix the thing"
    assert record["status"] == "active"
    assert isinstance(record["started_at"], float)


def test_mark_background_active_writes_kinded_json_record(hub_client, active_subagent_home):
    # Why: this is the mechanism that closes AC-4 for Bash/Workflow/Monitor --
    # each background dispatch must get its own kinded, labeled marker.
    hub_client.mark_background_active("session-abc", "bash", label="run tests")
    marker = next((active_subagent_home / "session-abc").iterdir())
    record = hub_client._read_marker(marker)
    assert record["kind"] == "bash"
    assert record["label"] == "run tests"
    assert record["status"] == "active"


def test_mark_subagent_active_returns_false_when_write_marker_fails(hub_client, active_subagent_home, monkeypatch):
    # Why: a mid-write failure (e.g. disk full after the exclusive touch
    # succeeds) must be reported as failure, not silently swallowed into a
    # false "success" while the marker file has no/partial JSON body.
    monkeypatch.setattr(hub_client, "_write_marker", lambda path, record: False)
    assert hub_client.mark_subagent_active("session-abc") is False
