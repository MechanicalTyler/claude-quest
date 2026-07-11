"""
Tests for attention_hub_transcript.py — attention-hub's own copy of the
transcript-parsing helpers, ported from notifications' macos_notification.py
so attention-hub carries zero cross-plugin imports.
"""

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).parent.parent / "hooks" / "attention_hub_transcript.py"
_spec = importlib.util.spec_from_file_location("attention_hub_transcript", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

has_ask_user_question = _mod.has_ask_user_question
extract_latest_message = _mod.extract_latest_message


def test_returns_true_when_latest_assistant_has_ask(transcript_with_ask):
    # Why: attention_hub_stop.py needs this to route to needs_input, its own copy
    # must match notifications' behavior exactly.
    assert has_ask_user_question(transcript_with_ask) is True


def test_returns_false_when_latest_assistant_has_no_ask(transcript_without_ask):
    # Why: guards the "done" branch — a transcript with no AskUserQuestion must
    # not be misrouted to needs_input.
    assert has_ask_user_question(transcript_without_ask) is False


def test_returns_false_when_only_previous_assistant_had_ask(transcript_ask_then_no_ask):
    # Why: regression guard for the loop-break bug — only the LATEST assistant
    # message should be examined, not any earlier one.
    assert has_ask_user_question(transcript_ask_then_no_ask) is False


def test_returns_false_for_tool_use_only_transcript(transcript_tool_use_only):
    # Why: a transcript whose latest assistant message is tool_use-only (no
    # AskUserQuestion) must not false-positive into needs_input.
    assert has_ask_user_question(transcript_tool_use_only) is False


def test_extract_latest_message_returns_text(transcript_without_ask):
    # Why: attention_hub_stop.py's message snippet comes from this function —
    # it must extract the assistant's text content correctly.
    assert extract_latest_message(transcript_without_ask) == "Here is the function you requested."


def test_extract_latest_message_returns_none_for_missing_file():
    # Why: hooks must never raise on a missing transcript path — degrade to None.
    assert extract_latest_message("/nonexistent/path.jsonl") is None


def test_extract_latest_message_returns_none_for_tool_use_only(transcript_tool_use_only):
    # Why: a transcript with no text content in the latest assistant message
    # must return None, not crash or return a tool_use block's contents.
    assert extract_latest_message(transcript_tool_use_only) is None
