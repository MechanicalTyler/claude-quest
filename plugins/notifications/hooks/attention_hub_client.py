#!/usr/bin/env python3
"""
Shared attention-hub client for Claude hooks.

Builds per-session state events and delivers them to the attention hub over
HTTP. Every network operation uses a short timeout and swallows all failures:
an unreachable hub must never block or error a Claude session.

Also hosts the per-channel notification flags (CLAUDE_NOTIFY_MACOS /
CLAUDE_NOTIFY_SLACK) shared by the hook scripts.
"""

import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HUB_URL = "http://localhost:8765"
HUB_TIMEOUT_SECONDS = 2
MESSAGE_SNIPPET_MAX = 200
SESSION_NAME_MAX = 256
_FALSY_VALUES = {"0", "false", "no", "off"}

# Container-detection signals (module-level so tests can redirect them).
CONTAINER_MARKER_FILES = ("/.dockerenv", "/run/.containerenv")
CONTAINER_ENV_VARS = ("container", "KUBERNETES_SERVICE_HOST")
MOUNTINFO_PATH = "/proc/self/mountinfo"


def log_hub(message, log_file="attention_hub_client.log"):
    """Write a timestamped log message to ~/.claude/logs/{log_file}. Never raises."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_path = Path.home() / ".claude" / "logs" / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def get_hub_url():
    """Hub base URL from CLAUDE_ATTENTION_HUB_URL, default http://localhost:8765."""
    url = os.environ.get("CLAUDE_ATTENTION_HUB_URL", "").strip() or DEFAULT_HUB_URL
    return url.rstrip("/")


def get_host_label():
    """Host label from CLAUDE_HOST_LABEL, falling back to the machine hostname."""
    label = os.environ.get("CLAUDE_HOST_LABEL", "").strip()
    if label:
        return label
    try:
        return socket.gethostname() or "unknown-host"
    except Exception:
        return "unknown-host"


def _root_is_overlayfs():
    """True when the root filesystem (/) is an overlayfs mount.

    Reads /proc/self/mountinfo, whose per-line format places the mount point
    at field 5 and the filesystem type right after the "-" separator. An
    overlay root is a strong container signal for environments (some dev
    containers) that expose no marker file or env variable. Never raises;
    missing/unreadable mountinfo (e.g. non-Linux) means "not detected".
    """
    try:
        with open(MOUNTINFO_PATH, "r", encoding="utf-8") as f:
            for line in f:
                fields = line.split()
                if len(fields) < 5 or fields[4] != "/":
                    continue
                try:
                    separator = fields.index("-")
                except ValueError:
                    continue
                if len(fields) > separator + 1:
                    return fields[separator + 1].startswith("overlay")
        return False
    except Exception:
        return False


def detect_container():
    """Best-effort detection of whether this session runs inside a container.

    Signals (any one suffices): /.dockerenv (Docker), /run/.containerenv
    (Podman), the `container` env var (Podman/systemd-nspawn),
    KUBERNETES_SERVICE_HOST (Kubernetes pod), or — as a final fallback — an
    overlayfs root per /proc/self/mountinfo. Cgroup-text scanning is not used:
    it is unreliable on cgroup v2. Never raises.
    """
    try:
        for marker in CONTAINER_MARKER_FILES:
            if os.path.exists(marker):
                return True
        for env_var in CONTAINER_ENV_VARS:
            if os.environ.get(env_var, "").strip():
                return True
        return _root_is_overlayfs()
    except Exception:
        return False


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


def get_session_name(input_data):
    """Best-effort session name for the hook's session.

    Checks the hook input for a title field first, then falls back to scanning
    the transcript for the last {"type": "custom-title"} record — the line
    Claude Code appends on /rename. Returns "" for unnamed sessions. Never
    raises: a malformed transcript must not break a hook.
    """
    try:
        for key in ("session_title", "custom_title"):
            value = str(input_data.get(key) or "").strip()
            if value:
                return value[:SESSION_NAME_MAX]
        transcript_path = str(input_data.get("transcript_path") or "")
        if not transcript_path:
            return ""
        name = ""
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if '"custom-title"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("type") == "custom-title":
                    name = str(record.get("customTitle") or "").strip()
        return name[:SESSION_NAME_MAX]
    except Exception:
        return ""


def _waiting_marker_path(session_id):
    """Marker file path for a session, or None if the ID is unusable.

    The session ID becomes a filename, so reject anything empty, containing
    path separators, or that is a traversal component. Markers live in a
    dedicated subdirectory of ~/.claude/notifications/ so all of the plugin's
    transient state sits under one gitignorable path.
    """
    session_id = str(session_id or "").strip()
    if (not session_id or "/" in session_id or "\\" in session_id
            or "\x00" in session_id or session_id in (".", "..")):
        return None
    return Path.home() / ".claude" / "notifications" / "waiting-markers" / session_id


def set_waiting_marker(session_id):
    """Record that the hub was told this session is waiting on the user.

    Returns True on success. Never raises — any filesystem error means the
    marker simply is not set and PostToolUse stays on its fast path.
    """
    try:
        path = _waiting_marker_path(session_id)
        if path is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return True
    except Exception:
        return False


def has_waiting_marker(session_id):
    """True if the session has a waiting marker. Never raises."""
    try:
        path = _waiting_marker_path(session_id)
        return path is not None and path.is_file()
    except Exception:
        return False


def clear_waiting_marker(session_id):
    """Remove the session's waiting marker; return True if it existed.

    Never raises — any filesystem error behaves as "no marker".
    """
    try:
        path = _waiting_marker_path(session_id)
        if path is None or not path.is_file():
            return False
        path.unlink()
        return True
    except Exception:
        return False


def build_event_payload(session_id, cwd, state, message=None, session_name=None):
    """Build the state-event payload identifying this session to the hub."""
    snippet = (message or "").strip()
    if len(snippet) > MESSAGE_SNIPPET_MAX:
        snippet = snippet[: MESSAGE_SNIPPET_MAX - 3] + "..."
    return {
        "session_id": session_id,
        "session_name": (session_name or "").strip()[:SESSION_NAME_MAX],
        "project": os.path.basename(os.path.normpath(cwd)) if cwd else "unknown",
        "host": get_host_label(),
        "state": state,
        "message": snippet,
        "is_container": detect_container(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _issue_request(url, method, body, timeout, result):
    """Worker body for _request. Stores True/False in result["ok"]. Never raises."""
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        response = urllib.request.urlopen(req, timeout=timeout)
        try:
            result["ok"] = 200 <= getattr(response, "status", 200) < 300
        finally:
            response.close()
    except urllib.error.HTTPError as e:
        log_hub(f"Hub rejected request ({method} {url}): HTTP {e.code}")
        result["ok"] = False
    except Exception as e:
        log_hub(f"Hub unreachable ({method} {url}): {e}")
        result["ok"] = False


def _request(url, method, body=None):
    """Issue an HTTP request to the hub with a bounded total wall clock.

    urlopen's timeout only covers socket operations — DNS resolution
    (getaddrinfo) runs before it applies, so a black-holed or unresolvable hub
    URL could stall a hook well past the budget. The request runs in a daemon
    thread joined for HUB_TIMEOUT_SECONDS, capping total time regardless of
    where the delay occurs. Returns True on 2xx, False otherwise. Never raises.
    """
    result = {}
    try:
        worker = threading.Thread(
            target=_issue_request,
            args=(url, method, body, HUB_TIMEOUT_SECONDS, result),
            daemon=True,
        )
        worker.start()
        worker.join(HUB_TIMEOUT_SECONDS)
    except Exception as e:
        log_hub(f"Hub request failed to dispatch ({method} {url}): {e}")
        return False
    if "ok" not in result:
        log_hub(f"Hub request exceeded {HUB_TIMEOUT_SECONDS}s budget ({method} {url})")
        return False
    return result["ok"]


def report_state(session_id, cwd, state, message=None, session_name=None):
    """POST a state event to the hub. Swallows every failure; returns success bool."""
    if not session_id:
        return False
    payload = build_event_payload(session_id, cwd, state, message, session_name)
    return _request(f"{get_hub_url()}/api/events", "POST", payload)


def remove_session(session_id):
    """Ask the hub to forget a session. Swallows every failure; returns success bool."""
    if not session_id:
        return False
    quoted_id = urllib.parse.quote(str(session_id), safe="")
    return _request(f"{get_hub_url()}/api/sessions/{quoted_id}", "DELETE")
