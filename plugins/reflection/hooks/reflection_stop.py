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

    # Only nudge on what looks like a natural sign-off, not every turn.
    text = last_user_text(transcript_path)
    if not text or not SIGNOFF_PATTERN.search(text):
        sys.exit(0)

    # Only nudge if there is actually something unreviewed to reflect on.
    if not LOG_PATH.exists() or not LOG_PATH.read_text(encoding="utf-8").strip():
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
