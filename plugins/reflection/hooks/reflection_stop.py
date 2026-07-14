#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import re
import sys
from pathlib import Path

SIGNOFF_PATTERN = re.compile(
    r"\b("
    r"bye|goodbye|good night|"
    r"that'?s all|that is all|that'?s everything|"
    r"thanks[, ]+that'?s it|thank you[, ]+that'?s it|"
    r"done for now|i'?m done|im done|"
    r"nothing (else|more)|"
    r"see you|gtg|gotta go|talk (later|tomorrow)"
    r")\b",
    re.IGNORECASE,
)

LOG_PATH = Path.home() / ".claude" / "reflection" / "log.md"
NUDGE_DIR = Path.home() / ".claude" / "reflection" / "state"

# Second completion signal, alongside SIGNOFF_PATTERN: a PM story moved to a
# done-type workflow state via tool calls. Exists because session sc-1242
# ended with "Merged, deployed. Move the story to done" — a real completion
# with no sign-off phrase, which the text-only check missed entirely (sc-1255).
# Derived purely from the transcript JSONL: this hook has no MCP access.
PM_UPDATE_VERBS = ("update", "edit", "transition", "move", "set")
PM_ITEM_NOUNS = ("story", "stories", "task", "issue", "ticket")

# A type/name/state field whose quoted value, trimmed and case-insensitive,
# is a done-like word — matched over tool-result text.
DONE_STATE_PATTERN = re.compile(
    r'["\']?(?:type|name|state)["\']?\s*:\s*["\']\s*'
    r"(?:done|closed|resolved|complete|completed)"
    r'\s*["\']',
    re.IGNORECASE,
)


def _is_pm_update_tool(name):
    lowered = name.lower()
    if not lowered.startswith("mcp__"):
        return False
    return any(verb in lowered for verb in PM_UPDATE_VERBS) and any(
        noun in lowered for noun in PM_ITEM_NOUNS
    )


def _tool_result_text(part):
    content = part.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                chunks.append(text if isinstance(text, str) else json.dumps(item))
        return " ".join(chunks)
    if isinstance(content, dict):
        return json.dumps(content)
    return ""


def has_done_transition(transcript_path):
    saw_update_call = False
    saw_done_state = False
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "tool_use":
                        name = part.get("name")
                        if isinstance(name, str) and _is_pm_update_tool(name):
                            saw_update_call = True
                    elif part.get("type") == "tool_result":
                        if DONE_STATE_PATTERN.search(_tool_result_text(part)):
                            saw_done_state = True
                if saw_update_call and saw_done_state:
                    return True
    except OSError:
        return False
    return False


def has_open_entries(log_path):
    """At least one log entry still needs review: status segment says open,
    or the entry has no status segment at all (written before sc-1255 added
    status tracking). A fully-reported log must not trigger nudges."""
    if not log_path.exists():
        return False
    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        match = re.search(r"\|\s*status:\s*([A-Za-z]+)", line)
        if match is None or match.group(1).lower() == "open":
            return True
    return False


def last_user_text(transcript_path):
    with open(transcript_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message", {})
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            text = content if isinstance(content, str) else ""
        if text:
            return text
    return ""


def main():
    input_data = json.load(sys.stdin)

    # Avoid looping: if this Stop event was already produced by our own
    # earlier block on this turn, do not block again.
    if input_data.get("stop_hook_active"):
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    transcript_path = input_data.get("transcript_path", "")
    if not session_id or not transcript_path:
        sys.exit(0)

    # Only nudge once per session.
    NUDGE_DIR.mkdir(parents=True, exist_ok=True)
    marker = NUDGE_DIR / f"{session_id}.nudged"
    if marker.exists():
        sys.exit(0)

    # Only nudge if at least one entry is still open (unstatused entries
    # count as open) — a fully-reported log has nothing left to reflect on.
    # Checked first because it only reads the (small) log file: on the common
    # path — nothing logged, or everything already reported — it short-circuits
    # the full-transcript scans below, whose cost grows with session length.
    if not has_open_entries(LOG_PATH):
        sys.exit(0)

    # Only nudge on a completion signal — two independent signals, OR'd:
    # a sign-off phrase in the last user message, or a PM story moved to a
    # done-type state (see has_done_transition; added after sc-1242's
    # "Move the story to done" ended a session with no sign-off phrase).
    text = last_user_text(transcript_path)
    signed_off = bool(text and SIGNOFF_PATTERN.search(text))
    if not signed_off and not has_done_transition(transcript_path):
        sys.exit(0)

    marker.touch()

    output = {
        "decision": "block",
        "reason": (
            "This looks like the end of the session and there are unreviewed "
            "entries in ~/.claude/reflection/log.md. Run /reflect now to "
            "synthesize them into a report before finishing, then stop."
        ),
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
