#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import sys
from pathlib import Path

try:
    from attention_hub_client import mark_subagent_active
except ImportError:
    import importlib.util
    hub_spec = importlib.util.spec_from_file_location(
        "attention_hub_client",
        Path(__file__).parent / "attention_hub_client.py"
    )
    attention_hub_client = importlib.util.module_from_spec(hub_spec)
    hub_spec.loader.exec_module(attention_hub_client)
    mark_subagent_active = attention_hub_client.mark_subagent_active


def main():
    # PreToolUse: pure observer, not a gate. Must always exit 0 and never
    # print a permission-decision payload -- if this hook ever blocked a Task
    # dispatch, subagents would stop running entirely, which is strictly
    # worse than the "shows waiting/done while working" bug it fixes.
    try:
        input_data = json.load(sys.stdin)
        if input_data.get("tool_name") == "Task":
            mark_subagent_active(input_data.get("session_id", ""))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
