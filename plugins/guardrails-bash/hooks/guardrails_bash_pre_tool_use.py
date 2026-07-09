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


def is_dangerous_rm_command(command):
    normalized = ' '.join(command.lower().split())

    combined_flag_patterns = [
        r'\brm\s+(?:[^-\s]*\s+)*-[a-z]*r[a-z]*f(?:\s|$)',
        r'\brm\s+(?:[^-\s]*\s+)*-[a-z]*f[a-z]*r(?:\s|$)',
    ]
    for pattern in combined_flag_patterns:
        if re.search(pattern, normalized):
            return True

    if re.search(r'\brm\s+.*--recursive.*--force', normalized):
        return True
    if re.search(r'\brm\s+.*--force.*--recursive', normalized):
        return True

    has_r_flag = re.search(r'\brm\s+(?:.*\s+)?-[a-z]*r(?:\s|$)', normalized)
    has_f_flag = re.search(r'\brm\s+(?:.*\s+)?-[a-z]*f(?:\s|$)', normalized)
    if has_r_flag and has_f_flag:
        return True

    if re.search(r'\brm\s+(?:.*\s+)?-[a-z]*r', normalized):
        dangerous_paths = [
            r'\s+/$',
            r'\s+/\*',
            r'\s+~(?:/|\s|$)',
            r'\s+~/\*',
            r'\$HOME',
            r'\.\.\/',
            r'\s+\*(?:\s|$)',
        ]
        for path in dangerous_paths:
            if re.search(path, normalized):
                return True

    return False


def block_rm_rf_command(tool_name, tool_input):
    if tool_name == 'Bash':
        command = tool_input.get('command', '')
        if is_dangerous_rm_command(command):
            decision = {
                "decision": "block",
                "reason": "rm not allowed with -r or -f. Run again without -r or -f. Delete files individually if needed."
            }
            print(json.dumps(decision))
            sys.exit(1)


def block_tmp_directory_usage(tool_name, tool_input):
    if tool_name == 'Bash':
        command = tool_input.get('command', '')
        tmp_patterns = [
            r'\s+/tmp/',
            r'^/tmp/',
            r'[=>]/tmp/',
            r'--tmpdir[=\s]/tmp',
            r'TMPDIR=/tmp',
            r'\$TMPDIR.*=/tmp',
        ]
        for pattern in tmp_patterns:
            if re.search(pattern, command):
                decision = {
                    "decision": "block",
                    "reason": "Operations in /tmp are not allowed. Use `./.scratch/tmp/` in the project root instead for temporary file storage."
                }
                print(json.dumps(decision))
                sys.exit(1)


def add_timeout_to_gradle_test(tool_name, tool_input):
    if tool_name == 'Bash':
        command = tool_input.get('command', '')
        timeout = tool_input.get('timeout')

        test_patterns = [
            r'\bgradle\s+[^"]*:test\b',
            r'\bgradle\s+[^"]*Test\s',
            r'\bgradle\s+[^"]*Test$',
            r'\bgradle\s+[^"]*connectedDebugAndroidTest\b',
            r'\bgradle\s+[^"]*testDebugUnitTest\b',
            r'\bgradle\s+[^"]*androidTest\b',
            r'\bgradle\s+[^"]*connectedAndroidTest\b',
        ]

        if any(re.search(pattern, command) for pattern in test_patterns):
            wanted_timeout = 900000
            if timeout != wanted_timeout:
                decision = {
                    "decision": "block",
                    "reason": create_timeout_error_message("gradle", wanted_timeout, timeout)
                }
                print(json.dumps(decision))
                sys.exit(1)


def block_gradle_build_command(tool_name, tool_input):
    if tool_name == 'Bash':
        command = tool_input.get('command', '')
        if re.search(r'^\s*gradle\s+build\s*$', command) or re.search(r'^\s*gradle\s+build\s+(-\w+\s*)*$', command):
            decision = {
                "decision": "block",
                "reason": "The generic 'gradle build' command is not allowed. Please run individual builds instead, such as 'gradle composeApp:build', 'gradle server:build', or other specific module builds."
            }
            print(json.dumps(decision))
            sys.exit(1)


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})

        block_rm_rf_command(tool_name, tool_input)
        block_tmp_directory_usage(tool_name, tool_input)
        block_gradle_build_command(tool_name, tool_input)
        add_timeout_to_gradle_test(tool_name, tool_input)

        sys.exit(0)
    except json.JSONDecodeError:
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == '__main__':
    main()
