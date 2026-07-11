#!/usr/bin/env python3
"""
Transcript-parsing helpers for attention-hub's own hooks.

Copied from the notifications plugin's macos_notification.py so attention-hub
carries no cross-plugin import: extracting the latest assistant message and
detecting an AskUserQuestion tool use are both needed by attention_hub_stop.py
and attention_hub_notification.py to compute state, independent of whether
notifications is installed.
"""

import json
from pathlib import Path
from datetime import datetime


def log_transcript(message, log_file="attention_hub_transcript.log"):
    """Write a timestamped log message to ~/.claude/logs/{log_file}. Never raises."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_path = Path.home() / ".claude" / "logs" / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def has_ask_user_question(transcript_path):
    """
    Check if the latest assistant message contains an AskUserQuestion tool use.

    Parses the transcript JSONL file and looks at only the most recent
    assistant message. Never raises.
    """
    try:
        if not transcript_path or not Path(transcript_path).exists():
            log_transcript(f"Transcript file not found: {transcript_path}")
            return False

        messages = []
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        if not messages:
            return False

        for entry in reversed(messages):
            message = entry.get("message", {})
            if message.get("role") == "assistant":
                content = message.get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            if item.get("name", "") == "AskUserQuestion":
                                return True
                break

        return False
    except Exception as e:
        log_transcript(f"Error checking for AskUserQuestion: {e}")
        return False


def extract_latest_message(transcript_path):
    """
    Extract the latest assistant text message from a JSONL transcript file.

    Returns the text content of the most recent assistant message, or None.
    """
    try:
        if not transcript_path or not Path(transcript_path).exists():
            return None

        messages = []
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        log_transcript(f"JSON decode error on line {line_num}: {e}")
                        continue

        for entry in reversed(messages):
            message = entry.get("message", {})
            if message.get("role") == "assistant":
                content = message.get("content", [])
                if isinstance(content, str) and content.strip():
                    return content.strip()
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            if text.strip():
                                return text.strip()
                break

        return None
    except Exception as e:
        log_transcript(f"Error extracting message: {e}")
        return None
