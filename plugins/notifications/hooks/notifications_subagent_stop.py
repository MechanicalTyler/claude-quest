#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import sys


def main():
    # SubagentStop: no notifications needed.
    # When a subagent stops, the main agent is still running.
    # User action is not required at this point.
    sys.exit(0)


if __name__ == '__main__':
    main()
