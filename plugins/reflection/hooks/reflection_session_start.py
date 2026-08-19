#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import re
import sys
from pathlib import Path

INSTRUCTIONS = """## Reflection: passive corrective-moment logging

Throughout this session, watch for moments where you did not meet the user's expectations. The trigger types:

1. The user corrects a factual claim you made.
2. The user says "no", "don't", "stop doing X", or otherwise rejects an action you took or proposed.
3. The user has to repeat or rephrase a request because you didn't follow it the first time.
4. The user pushes back on an approach you proposed.
5. The user shows visible frustration or escalation (tone shift, repeated emphasis, "I already told you", etc.).

The instant one of these occurs, immediately append one Markdown entry to `~/.claude/reflection/log.md` (creating `~/.claude/reflection/` first if it doesn't exist). Each entry must contain:

- An ISO-8601 timestamp
- A one-line context note (the active skill, project, and/or cwd, if identifiable)
- The trigger type (one of the types above)
- A one-line quote or close paraphrase of what the user said

This logging is entirely passive: never interrupt the current task to log an entry, never ask the user permission to log, and never mention that you are logging unless asked. Simply append the entry and continue exactly what you were doing.

The user can run `/reflect` at any time to review the accumulated log and get a synthesized report — you do not need to do anything else with this log yourself."""

NUDGE = """

## Unreviewed reflection log entries

`~/.claude/reflection/log.md` has at least one entry that has not been reviewed yet. Run `/reflect` now to synthesize it into a report."""

LOG_PATH = Path.home() / ".claude" / "reflection" / "log.md"
# Per-session-id marker files, not an in-memory or "once ever" flag: SessionStart
# fires on startup, resume, clear, compact, and fork within what a user considers
# one session, so a durable per-session-id marker is required to nudge at most
# once per real session.
NUDGE_DIR = Path.home() / ".claude" / "reflection" / "state"

# Only a top-level entry (`- **{ISO timestamp}** | ...`) carries a status
# segment. Legacy multi-line entries use unrelated sub-bullets ("- Context:",
# "- Quote:") that must not be mistaken for entries in their own right.
ENTRY_PREFIX = re.compile(r"^- \*\*[^*]+\*\*\s*\|")


def has_open_entries(log_path):
    """At least one log entry still needs review: status segment says open,
    or the entry has no status segment at all (written before status
    tracking existed). A fully-reported log must not trigger nudges."""
    if not log_path.exists():
        return False
    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not ENTRY_PREFIX.match(line):
            continue
        match = re.search(r"\|\s*status:\s*([A-Za-z]+)", line)
        if match is None or match.group(1).lower() == "open":
            return True
    return False


def already_nudged(session_id):
    """SessionStart fires on startup, resume, clear, compact, and fork — not
    once per session — so the nudge needs its own per-session-id dedup marker
    (mirrors the old Stop hook's ~/.claude/reflection/state/{id}.nudged)."""
    if not session_id:
        return False
    return (NUDGE_DIR / f"{session_id}.nudged").exists()


def mark_nudged(session_id):
    if not session_id:
        return
    NUDGE_DIR.mkdir(parents=True, exist_ok=True)
    (NUDGE_DIR / f"{session_id}.nudged").touch()


def main():
    try:
        payload = json.load(sys.stdin)
        session_id = payload.get("session_id", "") if isinstance(payload, dict) else ""
    except Exception:
        session_id = ""

    # Base instructions must always ship (CLAUDE.md: "always present, regardless
    # of log state") even if the nudge decision itself fails partway through —
    # e.g. a corrupt log.md or an unwritable state dir must only cost the nudge,
    # never the instructions.
    context = INSTRUCTIONS
    try:
        if has_open_entries(LOG_PATH) and not already_nudged(session_id):
            context += NUDGE
            mark_nudged(session_id)
    except Exception:
        pass

    try:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
