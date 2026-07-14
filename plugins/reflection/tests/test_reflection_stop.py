"""Tests for reflection_stop.py — dual-signal completion detection (sign-off
phrase OR a PM done-transition found in the transcript) and the open-entry
log gate. The done-transition signal exists because session sc-1242 moved a
story to Done purely via chat instruction, with no sign-off phrase, and the
text-only check missed it (sc-1255)."""

import json
from io import StringIO
from unittest.mock import patch


class TestDoneTransitionSignal:
    def test_detected_when_call_and_done_result_present(self, stop_hook, transcript_done_transition):
        # Why: the core sc-1242 miss — an mcp__ story-update call plus a
        # done-type state in a tool result must count as a completion signal.
        assert stop_hook.has_done_transition(transcript_done_transition) is True

    def test_detected_regardless_of_order(self, stop_hook, transcript_done_transition_reversed):
        # Why: the done-type state may be fetched (workflows-list) before the
        # update call happens; order must not matter.
        assert stop_hook.has_done_transition(transcript_done_transition_reversed) is True

    def test_not_detected_with_update_call_only(self, stop_hook, transcript_update_call_only):
        # Why: a story update to a non-done state (estimate tweak) is not a
        # completion signal; both signals are required.
        assert stop_hook.has_done_transition(transcript_update_call_only) is False

    def test_not_detected_with_done_result_only(self, stop_hook, transcript_done_result_only):
        # Why: merely listing workflows (done state visible, no update call)
        # must not read as "work finished".
        assert stop_hook.has_done_transition(transcript_done_result_only) is False

    def test_builtin_taskupdate_does_not_trigger(self, stop_hook, transcript_taskupdate_completed):
        # Why: TaskUpdate marks in-session to-do items completed on nearly
        # every session; only mcp__-prefixed PM tools may satisfy Signal A.
        assert stop_hook.has_done_transition(transcript_taskupdate_completed) is False

    def test_no_signals_transcript_is_negative(self, stop_hook, transcript_no_signals):
        # Why: an ordinary conversation must never produce the done signal.
        assert stop_hook.has_done_transition(transcript_no_signals) is False

    def test_malformed_line_skipped_without_crash(self, stop_hook, transcript_malformed):
        # Why: transcripts can contain truncated lines; parsing must skip them
        # and still find signals in later valid lines.
        assert stop_hook.has_done_transition(transcript_malformed) is True

    def test_done_value_case_and_whitespace_insensitive(self, stop_hook, transcript_malformed):
        # Why: the spec requires " DONE " to match like "done" — value is
        # trimmed and compared case-insensitively (fixture's value is " DONE ").
        assert stop_hook.has_done_transition(transcript_malformed) is True
