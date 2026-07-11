#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import json
import sys
from pathlib import Path

try:
    from attention_hub_client import mark_subagent_active, mark_background_active
except ImportError:
    import importlib.util
    hub_spec = importlib.util.spec_from_file_location(
        "attention_hub_client",
        Path(__file__).parent / "attention_hub_client.py"
    )
    attention_hub_client = importlib.util.module_from_spec(hub_spec)
    hub_spec.loader.exec_module(attention_hub_client)
    mark_subagent_active = attention_hub_client.mark_subagent_active
    mark_background_active = attention_hub_client.mark_background_active


def _bash_background_label(tool_input):
    description = str(tool_input.get("description") or "").strip()
    if description:
        return description
    return str(tool_input.get("command") or "").strip()[:100]


def main():
    # PreToolUse: pure observer, not a gate. Must always exit 0 and never
    # print a permission-decision payload -- if this hook ever blocked a Task
    # dispatch, subagents would stop running entirely, which is strictly
    # worse than the "shows waiting/done while working" bug it fixes.
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name")
        tool_input = input_data.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        session_id = input_data.get("session_id", "")

        if tool_name == "Task":
            # [Inference] tool_input's description field is unconfirmed --
            # see spec's verification decision. Falls back to empty label.
            label = str(tool_input.get("description") or "").strip()
            mark_subagent_active(session_id, label=label)
        elif tool_name == "Bash" and tool_input.get("run_in_background"):
            mark_background_active(session_id, "bash", _bash_background_label(tool_input))
        elif tool_name == "Workflow":
            # [Unverified] "Workflow" tool_name string is an unconfirmed
            # assumption -- see spec's verification decision.
            label = (str(tool_input.get("description") or "").strip()
                     or str(tool_input.get("name") or "").strip())
            mark_background_active(session_id, "workflow", label)
        elif tool_name == "Monitor" and tool_input.get("persistent"):
            # [Unverified] "Monitor" tool_name string is an unconfirmed
            # assumption -- see spec's verification decision.
            label = str(tool_input.get("description") or "").strip()
            mark_background_active(session_id, "monitor", label)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
