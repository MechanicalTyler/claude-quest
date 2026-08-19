"""Tests for reflection_session_start.py — the SessionStart hook always emits
the base watch-and-log instructions, and conditionally appends a /reflect
nudge when the log has at least one entry that is still open (or unstatused)
AND the event's source is "startup". SessionStart also fires on resume,
clear, compact, and fork — those must never nudge, since they are
continuations of a session the user already started, not the start of a new
one."""

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
LEGACY_SUB_BULLETS = [
    "- Context: dev-workflow",
    '- Quote: "quoted correction"',
    "- Trigger type: correction",
]


def write_log(reflection_home, lines):
    reflection_home.mkdir(parents=True, exist_ok=True)
    (reflection_home / "log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_main(session_start_hook, capsys, source="startup", session_id="s1"):
    payload = {"session_id": session_id, "source": source}
    with patch("sys.stdin", StringIO(json.dumps(payload))):
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
        # Why: a fully-reported log has nothing left to reflect on — it must
        # not trigger a nudge just because entries exist.
        write_log(reflection_home, [REPORTED_ENTRY, REPORTED_ENTRY])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is False

    def test_missing_log_returns_false(self, session_start_hook):
        # Why: no log file yet (first-ever session) must not be mistaken for
        # an open entry — it must return False, not raise.
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is False

    def test_empty_log_returns_false(self, session_start_hook, reflection_home):
        # Why: a log file that exists but has no content must not be treated
        # as containing an open entry.
        write_log(reflection_home, [""])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is False

    def test_legacy_sub_bullets_do_not_count_as_open(self, session_start_hook, reflection_home):
        # Why: sub-bullets under a reported entry ("- Context:", "- Quote:")
        # start with "- " but carry no status segment of their own — they
        # must not latch has_open_entries true once the real entry is
        # reported.
        write_log(reflection_home, [REPORTED_ENTRY, *LEGACY_SUB_BULLETS])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is False

    def test_mixed_log_counts_open(self, session_start_hook, reflection_home):
        # Why: the realistic production shape — some entries already
        # reported, one still open — must still return True.
        write_log(reflection_home, [REPORTED_ENTRY, OPEN_STATUS_ENTRY])
        assert session_start_hook.has_open_entries(session_start_hook.LOG_PATH) is True


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

    def test_open_entry_nudges_on_startup(self, session_start_hook, reflection_home, capsys):
        # Why: acceptance criterion — an explicitly open entry on a startup
        # event must produce a /reflect nudge appended to additionalContext.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, source="startup")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" in context

    def test_unstatused_entry_nudges_on_startup(self, session_start_hook, reflection_home, capsys):
        # Why: unstatused entries count as open — the nudge condition must
        # match has_open_entries exactly, not a stricter "status: open" check.
        write_log(reflection_home, [OPEN_ENTRY])
        output = run_main(session_start_hook, capsys, source="startup")
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
        output = run_main(session_start_hook, capsys, source="startup")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context

    def test_hook_event_name_is_session_start(self, session_start_hook, reflection_home, capsys):
        # Why: regression guard — the hook must keep declaring itself as a
        # SessionStart hook regardless of nudge state.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, source="startup")
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"


class TestNudgeSourceFiltering:
    def test_resume_never_nudges(self, session_start_hook, reflection_home, capsys):
        # Why: resume is a continuation of an existing session, not a new
        # one — it must never nudge even with open entries.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, source="resume")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_clear_never_nudges(self, session_start_hook, reflection_home, capsys):
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, source="clear")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_compact_never_nudges(self, session_start_hook, reflection_home, capsys):
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, source="compact")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_fork_never_nudges(self, session_start_hook, reflection_home, capsys):
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, source="fork")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_missing_source_never_nudges(self, session_start_hook, reflection_home, capsys):
        # Why: an unrecognized/absent source must fail closed (no nudge),
        # never crash.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        with patch("sys.stdin", StringIO(json.dumps({"session_id": "s1"}))):
            try:
                session_start_hook.main()
            except SystemExit:
                pass
        output = json.loads(capsys.readouterr().out.strip())
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_base_instructions_present_on_non_startup_sources(
        self, session_start_hook, reflection_home, capsys
    ):
        # Why: the base watch-and-log instructions must ship on every
        # SessionStart event, not just startup — only the nudge is
        # startup-gated, so a compact mid-session doesn't lose the reminder.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, source="compact")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context

    def test_repeated_startup_events_nudge_every_time(
        self, session_start_hook, reflection_home, capsys
    ):
        # Why: there is no marker-file dedup anymore — the nudge is a pure
        # function of (source, log state), so it fires every startup event
        # while entries remain open, not just the first.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        first = run_main(session_start_hook, capsys, source="startup")
        assert "Unreviewed reflection log entries" in first["hookSpecificOutput"]["additionalContext"]

        second = run_main(session_start_hook, capsys, source="startup")
        assert "Unreviewed reflection log entries" in second["hookSpecificOutput"]["additionalContext"]
