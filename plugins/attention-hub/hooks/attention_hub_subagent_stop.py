#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import sys
from pathlib import Path

try:
    from attention_hub_client import clear_active_subagent
except ImportError:
    import importlib.util
    hub_spec = importlib.util.spec_from_file_location(
        "attention_hub_client",
        Path(__file__).parent / "attention_hub_client.py"
    )
    attention_hub_client = importlib.util.module_from_spec(hub_spec)
    hub_spec.loader.exec_module(attention_hub_client)
    clear_active_subagent = attention_hub_client.clear_active_subagent


def main():
    # SubagentStop: no notifications needed. When a subagent stops, the main
    # agent is still running and user action is not required at this point.
    # Only clears this subagent's active-tracking marker, so the Stop hook's
    # active-subagent count stays accurate.
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
