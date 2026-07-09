#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# ///

import json
import sys
from pathlib import Path
from datetime import datetime


def log_input_request(tool_name, tool_input):
    log_path = Path.home() / ".claude" / "logs" / "pre_tool_use.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing log data or initialize empty list
    if log_path.exists():
        with open(log_path, 'r') as f:
            try:
                log_data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                log_data = []
    else:
        log_data = []

    # Append new data
    log_data.append({
        'tool_name': tool_name,
        'tool_input': tool_input
    })

    # Write back to file with formatting
    with open(log_path, 'w') as f:
        json.dump(log_data, f, indent=2)


def log_subagent_spawn(tool_name, tool_input):
    """
    Log when sub-agents are spawned via the Task tool.
    Provides visibility into sub-agent creation.
    """
    if tool_name == 'Task':
        log_path = Path.home() / ".claude" / "logs" / "subagent_spawns.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subagent_type = tool_input.get('subagent_type', 'unknown')
        description = tool_input.get('description', 'no description')

        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] Sub-agent spawned: {subagent_type} - {description}\n")


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})
        log_input_request(tool_name, tool_input)
        log_subagent_spawn(tool_name, tool_input)
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == '__main__':
    main()
