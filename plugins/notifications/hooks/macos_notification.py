#!/usr/bin/env python3
"""
Shared macOS notification utilities for Claude hooks.

This module provides functions to send smart macOS notifications that:
- Stack per project (using consistent titles)
- Show different subtitles based on notification type
- Use different sounds for different events
- Detect when Claude needs user input via AskUserQuestion tool
"""

import json
import subprocess
import os
from pathlib import Path
from datetime import datetime


def log_notification(message, log_file="macos_notification.log"):
    """Write a timestamped log message to ~/.claude/logs/{log_file}"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = Path.home() / ".claude" / "logs" / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def get_project_title():
    """
    Get the project directory name for consistent notification titles.
    This ensures all notifications from the same project stack together.

    Returns:
        str: Title in format "Claude - {project_directory_name}"
    """
    try:
        current_dir = os.getcwd()
        dir_name = os.path.basename(current_dir)
        return f"Claude - {dir_name}"
    except Exception as e:
        log_notification(f"⚠️ Could not get directory name: {e}")
        return "Claude"


def send_macos_notification(message, subtitle="", sound="Glass"):
    """
    Send a macOS notification using terminal-notifier with grouping and Terminal activation.

    Args:
        message (str): The notification message body
        subtitle (str): The subtitle text (e.g., "Needs Input", "Task Complete")
        sound (str): The notification sound name. Options:
                    - "Glass" (default, gentle)
                    - "Hero" (triumphant, for completions)
                    - "Tink" (subtle, for minor events)
                    - "" (empty string for silent notifications)

    Returns:
        bool: True if notification was sent successfully, False otherwise
    """
    try:
        # Get consistent title for notification stacking
        title = get_project_title()

        # Truncate message if too long (macOS notifications have limits)
        max_length = 200
        if len(message) > max_length:
            truncated_message = message[:max_length-3] + "..."
        else:
            truncated_message = message

        # Get project directory name for grouping (enables stacking)
        current_dir = os.getcwd()
        group_id = os.path.basename(current_dir)

        # Build terminal-notifier command
        cmd = [
            'terminal-notifier',
            '-message', truncated_message,
            '-title', title,
            '-group', group_id,  # This enables notification stacking by group
            '-activate', 'com.apple.Terminal'  # Focus Terminal when clicked
        ]

        if subtitle:
            cmd.extend(['-subtitle', subtitle])

        if sound:
            cmd.extend(['-sound', sound])

        log_notification(f"🍎 Sending macOS notification via terminal-notifier")
        log_notification(f"   Title: '{title}', Subtitle: '{subtitle}', Group: '{group_id}', Sound: '{sound}'")
        log_notification(f"   Message: {truncated_message[:50]}...")

        # Execute terminal-notifier command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            log_notification("✅ macOS notification sent successfully")
            return True
        else:
            log_notification(f"⚠️ macOS notification failed: {result.stderr.strip()}")
            return False

    except subprocess.TimeoutExpired:
        log_notification("⏰ macOS notification timed out")
        return False
    except FileNotFoundError:
        log_notification("❌ terminal-notifier not found!")
        log_notification("💡 Please install it with: brew install terminal-notifier")
        return False
    except Exception as e:
        log_notification(f"❌ Error sending macOS notification: {e}")
        return False


def has_ask_user_question(transcript_path):
    """
    Check if the latest assistant message contains an AskUserQuestion tool use.

    This function parses the transcript JSONL file and looks for the most recent
    assistant message to see if it contains a tool_use with name "AskUserQuestion".

    Args:
        transcript_path (str): Path to the transcript JSONL file

    Returns:
        bool: True if AskUserQuestion tool is found, False otherwise
    """
    try:
        if not transcript_path or not Path(transcript_path).exists():
            log_notification(f"📄 Transcript file not found: {transcript_path}")
            return False

        # Parse JSONL file - each line is a separate JSON object
        messages = []
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        messages.append(entry)
                    except json.JSONDecodeError:
                        continue

        if not messages:
            log_notification("📖 No messages found in transcript")
            return False

        log_notification(f"📖 Parsed {len(messages)} entries from transcript")

        # Find the most recent assistant message
        for entry in reversed(messages):
            message = entry.get('message', {})
            if message.get('role') == 'assistant':
                content = message.get('content', [])

                # Content should be an array of content blocks
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'tool_use':
                            tool_name = item.get('name', '')
                            if tool_name == 'AskUserQuestion':
                                log_notification(f"✅ Found AskUserQuestion tool in latest assistant message")
                                return True

                # We have now examined the most recent assistant message.
                # Do not fall through to older messages regardless of outcome.
                break

        log_notification("🔍 No AskUserQuestion tool found in latest assistant message")
        return False

    except Exception as e:
        log_notification(f"❌ Error checking for AskUserQuestion: {e}")
        return False


def extract_latest_message(transcript_path):
    """
    Extract the latest assistant text message from a JSONL transcript file.

    Returns the text content of the most recent assistant message, or None.
    """
    try:
        if not transcript_path or not Path(transcript_path).exists():
            log_notification(f"📄 Transcript file not found: {transcript_path}")
            return None

        messages = []
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        log_notification(f"⚠️ JSON decode error on line {line_num}: {e}")
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
        log_notification(f"❌ Error extracting message: {e}")
        return None
