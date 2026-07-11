#!/usr/bin/env python3
"""
Independent active-subagent marker tracker for the notifications plugin.

Mirrors attention-hub's marker-handling mechanism (attention_hub_client.py)
in behavior only -- no shared code, no cross-plugin import -- rooted at
~/.claude/notifications/active-subagents/ instead of attention-hub's path.
No HTTP reporting, no waiting-marker, no session-removal functions: this
tracker exists solely to preserve notifications' "suppress Task-Complete
while a background subagent is active" behavior standalone.
"""

import json
import shutil
import time
import uuid
from pathlib import Path

ACTIVE_SUBAGENT_TTL_SECONDS = 2 * 60 * 60
BACKGROUND_SUBAGENT_TTL_SECONDS = 15 * 60
COMPLETED_RETENTION_SECONDS = 5 * 60
LABEL_MAX_CHARS = 256


def _active_subagent_dir_path(session_id):
    """Per-session directory holding one marker file per active subagent.

    The session ID becomes a directory name, so reject anything empty,
    containing path separators, null bytes, or a traversal component.
    """
    session_id = str(session_id or "").strip()
    if (not session_id or "/" in session_id or "\\" in session_id
            or "\x00" in session_id or session_id in (".", "..")):
        return None
    return Path.home() / ".claude" / "notifications" / "active-subagents" / session_id


def _read_marker(path):
    """Parse a marker file's JSON body. Never raises."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            record = json.loads(text)
            if isinstance(record, dict) and record.get("kind") and record.get("status"):
                return record
    except Exception:
        pass
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = time.time()
    return {
        "id": path.name,
        "kind": "task",
        "label": "",
        "status": "active",
        "started_at": mtime,
    }


def _write_marker(path, record):
    """Write a marker record as JSON. Never raises."""
    try:
        path.write_text(json.dumps(record), encoding="utf-8")
        return True
    except Exception:
        return False


def _create_marker(session_id, kind, label=None):
    """Create one active-status marker of the given kind for this session."""
    try:
        dir_path = _active_subagent_dir_path(session_id)
        if dir_path is None:
            return False
        dir_path.mkdir(parents=True, exist_ok=True)
        marker_id = uuid.uuid4().hex
        marker_path = dir_path / marker_id
        marker_path.touch(exist_ok=False)
        return _write_marker(marker_path, {
            "id": marker_id,
            "kind": kind,
            "label": str(label or "")[:LABEL_MAX_CHARS],
            "status": "active",
            "started_at": time.time(),
        })
    except Exception:
        return False


def mark_subagent_active(session_id, label=None):
    """Record one active subagent dispatch for this session."""
    return _create_marker(session_id, "task", label)


def mark_background_active(session_id, kind, label=None):
    """Record one active background-tool dispatch for this session."""
    return _create_marker(session_id, kind, label)


def list_active_work(session_id):
    """List surviving active-work records for this session, pruning stale ones."""
    try:
        dir_path = _active_subagent_dir_path(session_id)
        if dir_path is None or not dir_path.is_dir():
            return []
        now = time.time()
        surviving = []
        for marker in dir_path.iterdir():
            try:
                if not marker.is_file():
                    continue
                record = _read_marker(marker)
                if record.get("status") == "completed":
                    completed_at = record.get("completed_at", now)
                    if now - completed_at > COMPLETED_RETENTION_SECONDS:
                        marker.unlink()
                        continue
                else:
                    ttl = (ACTIVE_SUBAGENT_TTL_SECONDS if record.get("kind") == "task"
                           else BACKGROUND_SUBAGENT_TTL_SECONDS)
                    age = now - marker.stat().st_mtime
                    if age > ttl:
                        marker.unlink()
                        continue
                surviving.append(record)
            except Exception:
                continue
        return surviving
    except Exception:
        return []


def count_active_subagents(session_id):
    """Count active-status markers for this session, across every kind."""
    try:
        return sum(1 for record in list_active_work(session_id)
                    if record.get("status") == "active")
    except Exception:
        return 0


def clear_active_subagent(session_id):
    """Flip the oldest still-active task-kind marker to status="completed"."""
    try:
        dir_path = _active_subagent_dir_path(session_id)
        if dir_path is None or not dir_path.is_dir():
            return False
        candidates = []
        for marker in dir_path.iterdir():
            if not marker.is_file():
                continue
            record = _read_marker(marker)
            if record.get("kind") == "task" and record.get("status") == "active":
                try:
                    mtime = marker.stat().st_mtime
                except Exception:
                    continue
                candidates.append((mtime, marker, record))
        if not candidates:
            return False
        candidates.sort(key=lambda c: c[0])
        _, marker, record = candidates[0]
        record["status"] = "completed"
        record["completed_at"] = time.time()
        _write_marker(marker, record)
        return True
    except Exception:
        return False


def clear_all_active_subagents(session_id):
    """Remove the entire active-subagent directory for this session at once."""
    try:
        dir_path = _active_subagent_dir_path(session_id)
        if dir_path is None or not dir_path.is_dir():
            return False
        shutil.rmtree(dir_path)
        return True
    except Exception:
        return False
