#!/usr/bin/env python3
"""Per-channel notification flags (CLAUDE_NOTIFY_MACOS / CLAUDE_NOTIFY_SLACK)."""

import os

_FALSY_VALUES = {"0", "false", "no", "off"}


def _channel_enabled(env_var):
    value = os.environ.get(env_var, "").strip().lower()
    if not value:
        return True
    return value not in _FALSY_VALUES


def macos_enabled():
    """macOS channel flag (CLAUDE_NOTIFY_MACOS). Defaults to enabled."""
    return _channel_enabled("CLAUDE_NOTIFY_MACOS")


def slack_enabled():
    """Slack channel flag (CLAUDE_NOTIFY_SLACK). Defaults to enabled."""
    return _channel_enabled("CLAUDE_NOTIFY_SLACK")
