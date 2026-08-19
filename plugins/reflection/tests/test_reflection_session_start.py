"""Tests for reflection_session_start.py — the SessionStart hook always emits
the base watch-and-log instructions, and conditionally appends a /reflect
nudge when the log has at least one entry that is still open (or unstatused).
The nudge moved here from the old Stop hook so it fires once, at session
start, instead of guessing when a session is "ending"."""

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


def run_main(session_start_hook, capsys):
    with patch("sys.stdin", StringIO(json.dumps({"session_id": "s1"}))):
        try:
            session_start_hook.main()
        except SystemExit:
            pass
    out = capsys.readouterr().out.strip()
    return json.loads(out)


class TestHasOpenEntries:
    def test_open_status_entry_counts(self, session_start_hook, reflection_home):
        # Why: an explicitly open entry is unreviewed work — the gate must pass.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is True

    def test_unstatused_entry_counts_as_open(self, session_start_hook, reflection_home):
        # Why: entries written before status tracking existed have no status
        # segment; they must be treated as open, not silently dropped.
        write_log(reflection_home, [OPEN_ENTRY])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is True

    def test_all_reported_returns_false(self, session_start_hook, reflection_home):
        write_log(reflection_home, [REPORTED_ENTRY, REPORTED_ENTRY])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is False

    def test_missing_log_returns_false(self, session_start_hook):
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is False

    def test_empty_log_returns_false(self, session_start_hook, reflection_home):
        write_log(reflection_home, [""])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is False


class TestSessionStartNudge:
    def test_no_open_entries_no_nudge(self, session_start_hook, reflection_home, capsys):
        # Why: acceptance criterion — a log with nothing open must not nudge.
        write_log(reflection_home, [REPORTED_ENTRY])
        output = run_main(session_start_hook, capsys)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_missing_log_no_nudge(self, session_start_hook, capsys):
        # Why: first-ever session, no log file yet — must not nudge or crash.
        output = run_main(session_start_hook, capsys)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_open_entry_nudges(self, session_start_hook, reflection_home, capsys):
        # Why: acceptance criterion — an explicitly open entry must produce a
        # /reflect nudge appended to additionalContext.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" in context

    def test_unstatused_entry_nudges(self, session_start_hook, reflection_home, capsys):
        # Why: unstatused entries count as open — the nudge condition must
        # match has_open_entries exactly, not a stricter "status: open" check.
        write_log(reflection_home, [OPEN_ENTRY])
        output = run_main(session_start_hook, capsys)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" in context

    def test_base_instructions_always_present_without_nudge(self, session_start_hook, reflection_home, capsys):
        # Why: the nudge is additive — suppressing it must never suppress the
        # base watch-and-log instructions the hook always emitted before.
        write_log(reflection_home, [REPORTED_ENTRY])
        output = run_main(session_start_hook, capsys)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context

    def test_base_instructions_always_present_with_nudge(self, session_start_hook, reflection_home, capsys):
        # Why: the nudge must be appended to, not a replacement for, the base
        # instructions.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context

    def test_hook_event_name_is_session_start(self, session_start_hook, reflection_home, capsys):
        # Why: regression guard — the hook must keep declaring itself as a
        # SessionStart hook regardless of nudge state.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys)
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
