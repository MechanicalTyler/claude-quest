#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# ///

import json
import sys
import re


def create_timeout_error_message(command_type, wanted_timeout, current_timeout):
    minutes = int(wanted_timeout / 60 / 1000)
    return f"You must set a timeout of {wanted_timeout}ms ({minutes} minutes) for {command_type} commands. This is not a test timeout error. Please retry the command with 'timeout': {wanted_timeout} in the tool parameters."


def add_timeout_to_docker_build(tool_name, tool_input):
    if tool_name == 'Bash':
        command = tool_input.get('command', '')
        timeout = tool_input.get('timeout')
        if re.search(r'\bdocker\s+build\b', command):
            wanted_timeout = 900000
            if timeout != wanted_timeout:
                decision = {
                    "decision": "block",
                    "reason": create_timeout_error_message("Docker build", wanted_timeout, timeout)
                }
                print(json.dumps(decision))
                sys.exit(1)


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})

        add_timeout_to_docker_build(tool_name, tool_input)

        sys.exit(0)
    except json.JSONDecodeError:
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == '__main__':
    main()
