"""
Tests for subagent_tracker.py -- notifications' own, fully independent
active-subagent marker tracker. Mirrors attention-hub's marker-function tests
in test_waiting_marker.py, minus the waiting-marker and hub-reporting pieces
(notifications has neither).
"""

import importlib.util
import os
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


@pytest.fixture
def tracker(active_subagent_home):
    """Load a fresh subagent_tracker with HOME redirected to tmp_path."""
    spec = importlib.util.spec_from_file_location(
        "subagent_tracker", HOOKS_DIR / "subagent_tracker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mark_one_subagent_active_counts_one(tracker, active_subagent_home):
    # Why: a single Agent dispatch must register exactly one active subagent so
    # the Stop hook can tell "background work in flight" from "nothing running".
    assert tracker.mark_subagent_active("session-abc") is True
    assert tracker.count_active_subagents("session-abc") == 1
    assert (active_subagent_home / "session-abc").is_dir()


def test_mark_two_subagents_active_counts_two(tracker, active_subagent_home):
    # Why: multiple concurrent dispatches must each get their own marker file.
    tracker.mark_subagent_active("session-abc")
    tracker.mark_subagent_active("session-abc")
    assert tracker.count_active_subagents("session-abc") == 2


def test_clear_one_marker_decrements_count_by_one(tracker, active_subagent_home):
    # Why: markers are interchangeable -- clearing must remove exactly one.
    tracker.mark_subagent_active("session-abc")
    tracker.mark_subagent_active("session-abc")
    assert tracker.clear_active_subagent("session-abc") is True
    assert tracker.count_active_subagents("session-abc") == 1


def test_clear_active_subagent_with_no_markers_returns_false(tracker, active_subagent_home):
    # Why: SubagentStop firing with nothing to clear must report "nothing
    # existed", not silently succeed.
    assert tracker.clear_active_subagent("never-marked") is False


def test_clear_active_subagent_flips_oldest_to_completed(tracker, active_subagent_home):
    # Why: no correlating ID is available, so FIFO (oldest active marker) is
    # the deterministic choice, matching attention-hub's own mechanism.
    tracker.mark_subagent_active("session-abc", label="first")
    dir_path = active_subagent_home / "session-abc"
    older = next(dir_path.iterdir())
    old_time = __import__("time").time() - 5
    os.utime(older, (old_time, old_time))
    tracker.mark_subagent_active("session-abc", label="second")

    assert tracker.clear_active_subagent("session-abc") is True
    records = {m.name: tracker._read_marker(m) for m in dir_path.iterdir()}
    completed = [r for r in records.values() if r["status"] == "completed"]
    active = [r for r in records.values() if r["status"] == "active"]
    assert len(completed) == 1
    assert len(active) == 1
    assert completed[0]["label"] == "first"


def test_clear_all_active_subagents_zeroes_count(tracker, active_subagent_home):
    # Why: session teardown must remove every marker at once.
    tracker.mark_subagent_active("session-abc")
    tracker.mark_subagent_active("session-abc")
    assert tracker.clear_all_active_subagents("session-abc") is True
    assert tracker.count_active_subagents("session-abc") == 0
    assert not (active_subagent_home / "session-abc").exists()


def test_clear_all_active_subagents_does_not_affect_other_sessions(tracker, active_subagent_home):
    # Why: teardown is per-session -- must never touch another session's markers.
    tracker.mark_subagent_active("session-abc")
    tracker.mark_subagent_active("session-xyz")
    tracker.clear_all_active_subagents("session-abc")
    assert tracker.count_active_subagents("session-xyz") == 1


def test_helpers_reject_hostile_session_ids(tracker, active_subagent_home):
    # Why: the session ID becomes a directory name -- path separators or
    # traversal must not let a malicious hook input escape the marker dir.
    for hostile in ("../escape", "a/b", "a\\b", "/etc/passwd", "..", ".", ""):
        assert tracker.mark_subagent_active(hostile) is False
        assert tracker.count_active_subagents(hostile) == 0
        assert tracker.clear_active_subagent(hostile) is False
        assert tracker.clear_all_active_subagents(hostile) is False


def test_helpers_tolerate_none_session_id(tracker, active_subagent_home):
    # Why: hook inputs are untrusted JSON -- a null session_id must behave as
    # "no markers", never raise.
    assert tracker.mark_subagent_active(None) is False
    assert tracker.count_active_subagents(None) == 0
    assert tracker.clear_active_subagent(None) is False
    assert tracker.clear_all_active_subagents(None) is False


def test_stale_marker_excluded_from_count_and_pruned(tracker, active_subagent_home):
    # Why: a crashed subagent that never fires SubagentStop must not wedge a
    # session on "working" forever.
    tracker.mark_subagent_active("session-abc")
    marker_dir = active_subagent_home / "session-abc"
    stale_marker = next(marker_dir.iterdir())
    old_time = __import__("time").time() - tracker.ACTIVE_SUBAGENT_TTL_SECONDS - 60
    os.utime(stale_marker, (old_time, old_time))
    assert tracker.count_active_subagents("session-abc") == 0
    assert not stale_marker.exists()


def test_mark_background_active_writes_kinded_json_record(tracker, active_subagent_home):
    # Why: backgrounded Bash dispatches must be tracked with their own kind,
    # matching attention-hub's mechanism.
    tracker.mark_background_active("session-abc", "bash", label="run tests")
    marker = next((active_subagent_home / "session-abc").iterdir())
    record = tracker._read_marker(marker)
    assert record["kind"] == "bash"
    assert record["label"] == "run tests"
    assert record["status"] == "active"


def test_list_active_work_returns_id_kind_label_status(tracker, active_subagent_home):
    # Why: the tracker's read surface must expose full per-marker identity.
    tracker.mark_subagent_active("session-abc", label="do the thing")
    work = tracker.list_active_work("session-abc")
    assert len(work) == 1
    assert work[0]["kind"] == "task"
    assert work[0]["label"] == "do the thing"
    assert work[0]["status"] == "active"


def test_count_active_subagents_excludes_completed(tracker, active_subagent_home):
    # Why: a retained completed marker must not inflate the count and wedge
    # the Stop hook's suppression check on "working" forever.
    tracker.mark_subagent_active("session-abc", label="x")
    tracker.mark_subagent_active("session-abc", label="y")
    tracker.clear_active_subagent("session-abc")
    assert tracker.count_active_subagents("session-abc") == 1
