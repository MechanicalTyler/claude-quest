#!/usr/bin/env python3
"""
Optional bridge to the attention-hub plugin's reporting client.

notifications no longer bundles any attention-tracking logic -- the hub
server, its reporting client, and the hooks whose sole job is hub reporting
all live in the separate attention-hub plugin. The Notification and Stop
hooks still have a secondary duty to report state to the hub (in addition to
their primary macOS/Slack job), so this module discovers attention-hub's
client (if that plugin is installed alongside notifications) and exposes the
handful of functions those two hooks need.

If attention-hub is not installed, or discovery fails for any reason, every
exposed function becomes a safe no-op returning a falsy/empty value -- the
Notification and Stop hooks must keep working (macOS/Slack unaffected)
whether or not attention-hub is present, exactly like an unreachable hub.
"""

import importlib.util
import os
from pathlib import Path


def _load_from(path):
    if path is None or not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("attention_hub_client", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _discover_client():
    override = os.environ.get("CLAUDE_ATTENTION_HUB_CLIENT_PATH", "").strip()
    if override:
        module = _load_from(Path(override))
        if module is not None:
            return module

    here = Path(__file__).resolve()

    # Local monorepo / direct-path install: plugins/<name>/hooks/... siblings.
    sibling = here.parents[2] / "attention-hub" / "hooks" / "attention_hub_client.py"
    module = _load_from(sibling)
    if module is not None:
        return module

    # Marketplace-cache install: cache/<marketplace>/<plugin>/<version>/hooks/...
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        try:
            marketplace_dir = Path(plugin_root).resolve().parent.parent
            for candidate in sorted(marketplace_dir.glob("attention-hub/*/hooks/attention_hub_client.py")):
                module = _load_from(candidate)
                if module is not None:
                    return module
        except Exception:
            pass

    return None


_client = _discover_client()


def available():
    """True if the attention-hub plugin's client was found and loaded."""
    return _client is not None


def report_state(session_id, cwd, state, message=None, session_name=None):
    if _client is None:
        return False
    return _client.report_state(session_id, cwd, state, message=message, session_name=session_name)


def get_session_name(input_data):
    if _client is None:
        return ""
    return _client.get_session_name(input_data)


def set_waiting_marker(session_id):
    if _client is None:
        return False
    return _client.set_waiting_marker(session_id)


def clear_waiting_marker(session_id):
    if _client is None:
        return False
    return _client.clear_waiting_marker(session_id)


def count_active_subagents(session_id):
    if _client is None:
        return 0
    return _client.count_active_subagents(session_id)


def log_hub(message, log_file="attention_hub_client.log"):
    if _client is None:
        return
    _client.log_hub(message, log_file=log_file)
