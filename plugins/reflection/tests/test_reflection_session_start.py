"""Tests for reflection_session_start.py — hooks.json registers this script
twice under SessionStart: once with no matcher (fires on every source) to
emit the base watch-and-log instructions, and once with matcher "startup" to
emit a conditional /reflect nudge. Each registration passes a distinct
--mode flag, and the script itself no longer inspects the SessionStart
payload's source field — the matcher in hooks.json is what restricts the
nudge registration to the startup event; resume, clear, compact, and fork
never invoke that registration at all.
"""

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


def run_main(session_start_hook, capsys, mode="instructions", session_id="s1"):
    """Invoke main() the way a hooks.json registration would: stdin carries
    the SessionStart payload (source is no longer read by the script, but a
    real invocation still receives it), argv carries the --mode this
    registration was configured with. Returns None when the hook emitted no
    stdout at all (the nudge registration's no-op path)."""
    payload = {"session_id": session_id, "source": "startup"}
    argv = ["reflection_session_start.py", f"--mode={mode}"]
    with patch("sys.stdin", StringIO(json.dumps(payload))), patch("sys.argv", argv):
        try:
            session_start_hook.main()
        except SystemExit:
            pass
    out = capsys.readouterr().out.strip()
    if not out:
        return None
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


class TestInstructionsMode:
    """The no-matcher registration: must always emit the base instructions,
    on every SessionStart source, and must never emit the nudge itself."""

    def test_emits_base_instructions(self, session_start_hook, reflection_home, capsys):
        # Why: acceptance criterion — this registration carries no matcher,
        # so it must fire and emit the base text regardless of log state.
        write_log(reflection_home, [REPORTED_ENTRY])
        output = run_main(session_start_hook, capsys, mode="instructions")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context

    def test_emits_base_instructions_with_open_entries(self, session_start_hook, reflection_home, capsys):
        # Why: this registration is unconditional — open log entries must
        # not change its output, since the nudge lives in the other
        # registration entirely.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, mode="instructions")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context

    def test_never_emits_nudge(self, session_start_hook, reflection_home, capsys):
        # Why: the nudge is exclusively the other registration's job — mixing
        # it into instructions mode would double it up once hooks.json merges
        # both registrations' output on a real startup event.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, mode="instructions")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" not in context

    def test_emits_on_missing_log(self, session_start_hook, capsys):
        # Why: first-ever session, no log file yet — must still emit the
        # base instructions, never crash.
        output = run_main(session_start_hook, capsys, mode="instructions")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context

    def test_hook_event_name_is_session_start(self, session_start_hook, reflection_home, capsys):
        # Why: regression guard — the hook must keep declaring itself as a
        # SessionStart hook.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, mode="instructions")
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_unrecognized_mode_falls_back_to_instructions(self, session_start_hook, capsys):
        # Why: an unrecognized or missing --mode must fail safe toward the
        # half of the behavior that must always ship, not silently no-op.
        with patch("sys.stdin", StringIO(json.dumps({"session_id": "s1"}))), patch(
            "sys.argv", ["reflection_session_start.py"]
        ):
            try:
                session_start_hook.main()
            except SystemExit:
                pass
        output = json.loads(capsys.readouterr().out.strip())
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" in context


class TestNudgeMode:
    """The matcher: "startup" registration: emits the /reflect nudge only
    when the log has an open entry, and never emits the base instructions
    (those come from the other registration)."""

    def test_no_open_entries_emits_nothing(self, session_start_hook, reflection_home, capsys):
        # Why: acceptance criterion — a log with nothing open must produce no
        # output at all from this registration, not an empty nudge block.
        write_log(reflection_home, [REPORTED_ENTRY])
        output = run_main(session_start_hook, capsys, mode="nudge")
        assert output is None

    def test_missing_log_emits_nothing(self, session_start_hook, capsys):
        # Why: first-ever session, no log file yet — must not nudge or crash.
        output = run_main(session_start_hook, capsys, mode="nudge")
        assert output is None

    def test_open_entry_nudges(self, session_start_hook, reflection_home, capsys):
        # Why: acceptance criterion — an explicitly open entry must produce
        # a /reflect nudge.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, mode="nudge")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" in context

    def test_unstatused_entry_nudges(self, session_start_hook, reflection_home, capsys):
        # Why: unstatused entries count as open — the nudge condition must
        # match has_open_entries exactly, not a stricter "status: open" check.
        write_log(reflection_home, [OPEN_ENTRY])
        output = run_main(session_start_hook, capsys, mode="nudge")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Unreviewed reflection log entries" in context

    def test_never_emits_base_instructions(self, session_start_hook, reflection_home, capsys):
        # Why: the base instructions are exclusively the other
        # registration's job — this registration must emit only the nudge.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, mode="nudge")
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "Reflection: passive corrective-moment logging" not in context

    def test_hook_event_name_is_session_start(self, session_start_hook, reflection_home, capsys):
        # Why: regression guard — the hook must keep declaring itself as a
        # SessionStart hook regardless of nudge state.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        output = run_main(session_start_hook, capsys, mode="nudge")
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_repeated_invocations_nudge_every_time(self, session_start_hook, reflection_home, capsys):
        # Why: there is no marker-file dedup — the nudge is a pure function
        # of log state, so it fires every time this registration runs while
        # entries remain open, not just the first.
        write_log(reflection_home, [OPEN_STATUS_ENTRY])
        first = run_main(session_start_hook, capsys, mode="nudge")
        assert "Unreviewed reflection log entries" in first["hookSpecificOutput"]["additionalContext"]

        second = run_main(session_start_hook, capsys, mode="nudge")
        assert "Unreviewed reflection log entries" in second["hookSpecificOutput"]["additionalContext"]


class TestHooksJsonRegistration:
    """The startup gating for the nudge lives in hooks.json's matcher, not
    in-script — these tests guard that config directly."""

    def _load(self):
        import json as _json
        from pathlib import Path

        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
        return _json.loads(hooks_path.read_text(encoding="utf-8"))

    def test_two_session_start_registrations(self):
        # Why: instructions and nudge must be split across two distinct
        # hooks.json entries for hooks.json's matcher to gate them
        # independently.
        registrations = self._load()["hooks"]["SessionStart"]
        assert len(registrations) == 2

    def test_one_registration_has_no_matcher_and_targets_instructions(self):
        # Why: the base instructions must fire on every SessionStart source,
        # which means this registration must carry no matcher restriction.
        registrations = self._load()["hooks"]["SessionStart"]
        unmatched = [r for r in registrations if "matcher" not in r]
        assert len(unmatched) == 1
        command = unmatched[0]["hooks"][0]["command"]
        assert "--mode=instructions" in command

    def test_one_registration_matches_startup_and_targets_nudge(self):
        # Why: the nudge must only run on the startup source — enforced by
        # hooks.json's matcher, not an in-script source check.
        registrations = self._load()["hooks"]["SessionStart"]
        startup_matched = [r for r in registrations if r.get("matcher") == "startup"]
        assert len(startup_matched) == 1
        command = startup_matched[0]["hooks"][0]["command"]
        assert "--mode=nudge" in command
