#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import sys

INSTRUCTIONS = """## Reflection: passive corrective-moment logging

Throughout this session, watch for moments where you did not meet the user's expectations. There are five trigger types:

1. The user corrects a factual claim you made.
2. The user says "no", "don't", "stop doing X", or otherwise rejects an action you took or proposed.
3. The user has to repeat or rephrase a request because you didn't follow it the first time.
4. The user pushes back on an approach you proposed.
5. The user shows visible frustration or escalation (tone shift, repeated emphasis, "I already told you", etc.).

The instant one of these occurs, immediately append one Markdown entry to `~/.claude/reflection/log.md` (creating `~/.claude/reflection/` first if it doesn't exist). Each entry must contain:

- An ISO-8601 timestamp
- A one-line context note (the active skill, project, and/or cwd, if identifiable)
- The trigger type (one of the five above)
- A one-line quote or close paraphrase of what the user said

This logging is entirely passive: never interrupt the current task to log an entry, never ask the user permission to log, and never mention that you are logging unless asked. Simply append the entry and continue exactly what you were doing.

The user can run `/reflect` at any time to review the accumulated log and get a synthesized report — you do not need to do anything else with this log yourself."""


def main():
    try:
        json.load(sys.stdin)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": INSTRUCTIONS,
            }
        }
        print(json.dumps(output))
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
