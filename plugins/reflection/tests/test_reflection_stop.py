"""Tests for reflection_stop.py — dual-signal completion detection (sign-off
phrase OR a PM done-transition found in the transcript) and the open-entry
log gate. The done-transition signal exists because session sc-1242 moved a
story to Done purely via chat instruction, with no sign-off phrase, and the
text-only check missed it (sc-1255)."""

import json
from io import StringIO
from unittest.mock import patch

OPEN_ENTRY = (
    '- **2026-07-14T18:00:00Z** | context: dev-workflow | '
    'trigger: correction | "quoted correction"'
)
OPEN_STATUS_ENTRY = OPEN_ENTRY + " | status: open"
REPORTED_ENTRY = OPEN_ENTRY + (
    " | status: reported (report: ~/.claude/reflection/reports/"
    "2026-07-14T19-47-28.html, at: 2026-07-14T19:47:28Z)"
)


def write_log(reflection_home, lines):
    reflection_home.mkdir(parents=True, exist_ok=True)
    (reflection_home / "log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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


class TestOpenEntryGate:
    def test_open_status_entry_counts(self, stop_hook, reflection_home):
        # Why: an explicitly open entry is unreviewed work — the gate must pass.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        assert stop_hook.has_open_entries(stop_hook.LOG_PATH) is True

    def test_unstatused_entry_counts_as_open(self, stop_hook, reflection_home):
        # Why: entries written before status tracking existed have no status
        # segment; they must be treated as open, not silently dropped.
        write_log(reflection_home, [OPEN_ENTRY])
        assert stop_hook.has_open_entries(stop_hook.LOG_PATH) is True

    def test_all_reported_returns_false(self, stop_hook, reflection_home):
        # Why: the redundant-nudge fix — a fully reported log means nothing
        # new to reflect on, so the hook must stay silent.
        write_log(reflection_home, [REPORTED_ENTRY, REPORTED_ENTRY])
        assert stop_hook.has_open_entries(stop_hook.LOG_PATH) is False

    def test_mixed_log_counts_open(self, stop_hook, reflection_home):
        # Why: one open entry among reported ones is still unreviewed work.
        write_log(reflection_home, [REPORTED_ENTRY, OPEN_STATUS_ENTRY])
        assert stop_hook.has_open_entries(stop_hook.LOG_PATH) is True

    def test_missing_log_returns_false(self, stop_hook):
        # Why: no log file at all means nothing to review — never nudge.
        assert stop_hook.has_open_entries(stop_hook.LOG_PATH) is False

    def test_empty_log_returns_false(self, stop_hook, reflection_home):
        # Why: an empty file has no entries; the old any-content gate is gone.
        write_log(reflection_home, [""])
        assert stop_hook.has_open_entries(stop_hook.LOG_PATH) is False


def run_main(stop_hook, hook_input, capsys):
    with patch("sys.stdin", StringIO(json.dumps(hook_input))):
        try:
            stop_hook.main()
        except SystemExit:
            pass
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


class TestMainEndToEnd:
    def test_done_transition_blocks_with_reflect_reason(
        self, stop_hook, reflection_home, transcript_done_transition, capsys
    ):
        # Why: the story's acceptance test — a done-transition with NO sign-off
        # phrase in the last user message must still block with the reflect-now
        # reason when open entries exist.
        write_log(reflection_home, [OPEN_ENTRY])
        decision = run_main(stop_hook, {
            "session_id": "e2e-done",
            "transcript_path": transcript_done_transition,
        }, capsys)
        assert decision is not None
        assert decision["decision"] == "block"
        assert "/reflect" in decision["reason"]

    def test_signoff_still_blocks(
        self, stop_hook, reflection_home, transcript_signoff, capsys
    ):
        # Why: regression check named in the story — the existing text-based
        # sign-off detection must keep firing unchanged.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        decision = run_main(stop_hook, {
            "session_id": "e2e-signoff",
            "transcript_path": transcript_signoff,
        }, capsys)
        assert decision is not None
        assert decision["decision"] == "block"

    def test_fully_reported_log_does_not_block(
        self, stop_hook, reflection_home, transcript_signoff, capsys
    ):
        # Why: the redundant-nudge fix end to end — even on a clear sign-off,
        # a log where every entry is reported must produce no block.
        write_log(reflection_home, [REPORTED_ENTRY])
        assert run_main(stop_hook, {
            "session_id": "e2e-reported",
            "transcript_path": transcript_signoff,
        }, capsys) is None

    def test_no_signals_does_not_block(
        self, stop_hook, reflection_home, transcript_no_signals, capsys
    ):
        # Why: an ordinary mid-session turn (no sign-off, no done signal) must
        # never nudge, even with open entries waiting.
        write_log(reflection_home, [OPEN_ENTRY])
        assert run_main(stop_hook, {
            "session_id": "e2e-nosignal",
            "transcript_path": transcript_no_signals,
        }, capsys) is None

    def test_no_open_entries_skips_transcript_reads(
        self, stop_hook, reflection_home, tmp_path, capsys
    ):
        # Why: performance gate ordering (PR #85 review) — when nothing is
        # open to review, main() must short-circuit BEFORE the full-transcript
        # scans (last_user_text / has_done_transition). A nonexistent
        # transcript path proves it: any attempt to open the transcript would
        # raise FileNotFoundError out of run_main.
        write_log(reflection_home, [REPORTED_ENTRY])
        assert run_main(stop_hook, {
            "session_id": "e2e-cheap-gate-first",
            "transcript_path": str(tmp_path / "missing-transcript.jsonl"),
        }, capsys) is None
