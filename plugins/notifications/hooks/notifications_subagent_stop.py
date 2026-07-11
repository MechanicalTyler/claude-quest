#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import sys
from pathlib import Path

try:
    from subagent_tracker import clear_active_subagent
except ImportError:
    import importlib.util
    tracker_spec = importlib.util.spec_from_file_location(
        "subagent_tracker",
        Path(__file__).parent / "subagent_tracker.py"
    )
    subagent_tracker = importlib.util.module_from_spec(tracker_spec)
    tracker_spec.loader.exec_module(subagent_tracker)
    clear_active_subagent = subagent_tracker.clear_active_subagent


def main():
    # SubagentStop: no notifications needed -- the main agent is still
    # running. Only clears this subagent's active-tracking marker, so the
    # Stop hook's suppression check stays accurate.
    try:
        input_data = json.load(sys.stdin)
        session_id = input_data.get("session_id", "")
        if session_id:
            clear_active_subagent(session_id)
    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
