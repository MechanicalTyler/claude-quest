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


def main():
    try:
        payload = json.load(sys.stdin)
        source = payload.get("source", "") if isinstance(payload, dict) else ""
    except Exception:
        source = ""

    # Base instructions must always ship (CLAUDE.md: "always present, regardless
    # of log state") even if the nudge decision itself fails partway through —
    # e.g. a corrupt log.md must only cost the nudge, never the instructions.
    context = INSTRUCTIONS
    # SessionStart also fires on resume/clear/compact/fork, all of which are
    # continuations of a session the user already started — the nudge must
    # only fire once, at the one event (startup) that begins a real session.
    try:
        if source == "startup" and has_open_entries(LOG_PATH):
            context += NUDGE
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
