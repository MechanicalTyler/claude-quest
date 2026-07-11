#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import sys
from pathlib import Path

try:
    from subagent_tracker import clear_all_active_subagents
except ImportError:
    import importlib.util
    tracker_spec = importlib.util.spec_from_file_location(
        "subagent_tracker",
        Path(__file__).parent / "subagent_tracker.py"
    )
    subagent_tracker = importlib.util.module_from_spec(tracker_spec)
    tracker_spec.loader.exec_module(subagent_tracker)
    clear_all_active_subagents = subagent_tracker.clear_all_active_subagents


def main():
    # SessionEnd: clear this session's active-subagent markers so nothing
    # leaks on disk. No hub call -- this plugin has no hub relationship.
    try:
        input_data = json.load(sys.stdin)
        session_id = input_data.get("session_id", "")
        if not session_id:
            sys.exit(0)
        clear_all_active_subagents(session_id)
        sys.exit(0)
    except json.JSONDecodeError:
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
